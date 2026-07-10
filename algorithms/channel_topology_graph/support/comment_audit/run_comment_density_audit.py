"""注释密度审计脚本。

真实职责：
    对 `channel_topology_graph` 目标目录做函数级审计，检查两类硬约束：
    1. 所有函数必须有中文 docstring
    2. 行内注释密度必须达到“每 3 行有效代码至少 1 条注释”
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[4]
TARGET_DIRS = (
    REPO_ROOT / "algorithms/channel_topology_graph/contracts",
    REPO_ROOT / "algorithms/channel_topology_graph/coverage_planning",
    REPO_ROOT / "algorithms/channel_topology_graph/geometry_preparation",
    REPO_ROOT / "algorithms/channel_topology_graph/io",
    REPO_ROOT / "algorithms/channel_topology_graph/junction_rebuild",
    REPO_ROOT / "algorithms/channel_topology_graph/pipeline",
    REPO_ROOT / "algorithms/channel_topology_graph/renderers",
    REPO_ROOT / "algorithms/channel_topology_graph/stages",
    REPO_ROOT / "algorithms/channel_topology_graph/topology_graph_build",
)


@dataclass(frozen=True, slots=True)
class FunctionAudit:
    """单个函数的注释审计结果。"""

    file_path: str
    function_name: str
    lineno: int
    has_docstring: bool
    comment_lines: int
    effective_lines: int

    @property
    def density_ok(self) -> bool:
        """判断是否达到“每 3 行至少 1 条注释”的硬标准。"""

        # 纯空壳函数不需要再追注释密度，直接视为通过。
        if self.effective_lines == 0:
            return True
        # 其余函数严格按 1/3 阈值判断，不做“复杂度折扣”。
        return self.comment_lines * 3 >= self.effective_lines


def main() -> None:
    """执行默认目录的注释密度审计。"""

    # 先收集全量函数结果，再统一做缺口分组，避免边遍历边输出打乱顺序。
    audits = collect_function_audits()
    # docstring 缺口和密度缺口分开建表，后续输出才能一眼看出问题层级。
    doc_missing = [item for item in audits if not item.has_docstring]
    # 密度失败项保留完整审计对象，便于直接读取注释/有效行数差额。
    density_failed = [item for item in audits if not item.density_ok]

    # 先给出总览，方便快速判断是否已经进入清零阶段。
    print(f"total_functions={len(audits)}")
    print(f"doc_missing={len(doc_missing)}")
    print(f"density_failed={len(density_failed)}")

    # docstring 缺失和密度失败都按“文件 + 行号”稳定输出，便于逐轮消项。
    # 先报 docstring，是因为它属于更基础的结构缺口。
    for item in doc_missing:
        print(
            "DOC_MISSING",
            item.file_path,
            item.function_name,
            f"L{item.lineno}",
        )
    # 再报密度缺口，方便按 comment/effective 数量直接补足。
    for item in density_failed:
        print(
            "DENSITY_FAILED",
            item.file_path,
            item.function_name,
            f"L{item.lineno}",
            f"comment={item.comment_lines}",
            f"effective={item.effective_lines}",
        )

    # 只要还有 docstring 或密度缺口，就让脚本以失败态退出，便于接入工作流。
    # 这样 CI、人工脚本和过程记录都能共享同一套通过/失败口径。
    if doc_missing or density_failed:
        sys.exit(1)


def collect_function_audits() -> list[FunctionAudit]:
    """收集目标目录内所有函数的审计结果。"""

    audits: list[FunctionAudit] = []
    for target_dir in TARGET_DIRS:
        # 逐文件遍历可以把失败项稳定映射到真实文件，而不是只给总体统计。
        for file_path in sorted(target_dir.rglob("*.py")):
            audits.extend(audit_python_file(file_path))
    # 这里返回的是平铺函数表，后续总览和失败列表都基于同一份真值。
    return audits


def audit_python_file(file_path: Path) -> list[FunctionAudit]:
    """审计单个 Python 文件里的全部函数。"""

    # 审计口径基于 AST，而不是正则，这样能稳定识别嵌套函数和 async 函数。
    text = file_path.read_text(encoding="utf-8")
    lines = text.splitlines()
    # 语法树只解析一次，后续节点遍历与 docstring 检测都复用同一份结果。
    tree = ast.parse(text)
    audits: list[FunctionAudit] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        # 注释密度要排除 docstring 本身，否则函数头说明会掩盖行内注释缺口。
        docstring_span = find_docstring_span(node)
        # 行号范围直接取 AST 节点范围，避免正则切块导致缩进层级混乱。
        comment_lines, effective_lines = count_comment_and_effective_lines(
            lines=lines,
            start_lineno=node.lineno,
            end_lineno=node.end_lineno,
            docstring_span=docstring_span,
        )
        # has_docstring 与 span 分开记录，是因为“有 docstring”不等于“需要计入密度”。
        # 每个函数都记录成稳定审计对象，方便后续排序、统计和失败输出复用。
        # 这里不做实时筛选，确保后续既能看失败，也能看全量通过数。
        audits.append(
            FunctionAudit(
                file_path=str(file_path.relative_to(REPO_ROOT)),
                function_name=node.name,
                lineno=node.lineno,
                has_docstring=ast.get_docstring(node) is not None,
                comment_lines=comment_lines,
                effective_lines=effective_lines,
            )
        )
    # 单文件内部按行号排序，保证同一轮审计输出可复现。
    # 这里连嵌套函数也按真实定义行落位，方便补注释时精确回跳。
    return sorted(audits, key=lambda item: (item.file_path, item.lineno, item.function_name))


def find_docstring_span(node: ast.AST) -> tuple[int, int] | None:
    """返回函数 docstring 占用的行范围。"""

    # 只有函数体第一条语句是字符串常量时，才算 Python 正式 docstring。
    # 这和 `ast.get_docstring` 的核心判断口径保持一致。
    body = getattr(node, "body", None)
    if not body:
        return None
    first_stmt = body[0]
    # 第一条不是表达式时，说明函数头没有标准 docstring。
    if not isinstance(first_stmt, ast.Expr):
        return None
    value = getattr(first_stmt, "value", None)
    # 只有字符串常量才能作为正式 docstring，其它表达式都不算。
    if not isinstance(value, ast.Constant) or not isinstance(value.value, str):
        return None
    return (first_stmt.lineno, first_stmt.end_lineno)


def count_comment_and_effective_lines(
    lines: list[str],
    start_lineno: int,
    end_lineno: int,
    docstring_span: tuple[int, int] | None,
) -> tuple[int, int]:
    """统计函数体内的行内注释行数与有效代码行数。"""

    comment_lines = 0
    effective_lines = 0
    for lineno in range(start_lineno, end_lineno + 1):
        # docstring 是函数头说明，不计入“行内注释密度”。
        if docstring_span is not None and docstring_span[0] <= lineno <= docstring_span[1]:
            continue
        stripped = lines[lineno - 1].strip()
        # 空行不计密度，避免格式化风格影响结果。
        if not stripped:
            continue
        # 只有独立行注释计入密度；代码尾部注释当前不纳入口径。
        # 这样做是为了和参考文件的“块前注释”写法保持同一统计方式。
        if stripped.startswith("#"):
            comment_lines += 1
            continue
        # 其余非空非注释行一律算有效代码行。
        # 包括 `def` 行本身在内，因为函数签名同样需要行内解释来支撑可读性。
        effective_lines += 1
    # 返回两个原始计数，让阈值策略统一由上层 `density_ok` 控制。
    return comment_lines, effective_lines


if __name__ == "__main__":
    main()
