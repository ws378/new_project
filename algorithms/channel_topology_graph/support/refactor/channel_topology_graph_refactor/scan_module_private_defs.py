"""扫描 channel_topology_graph 源码中的模块级私有函数定义。"""

from __future__ import annotations

import argparse
import ast
from pathlib import Path


def iter_python_files(root: Path) -> list[Path]:
    """按稳定顺序收集目录下所有 Python 文件。"""

    return sorted(path for path in root.rglob("*.py") if path.is_file())


def collect_module_private_defs(path: Path) -> list[tuple[int, str]]:
    """返回一个文件中的模块级 `_...` 函数定义。"""

    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    private_defs: list[tuple[int, str]] = []
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not node.name.startswith("_") or node.name.startswith("__"):
            continue
        private_defs.append((int(node.lineno), str(node.name)))
    return private_defs


def scan_root(root: Path) -> list[tuple[Path, list[tuple[int, str]]]]:
    """扫描根目录并返回含模块级私有函数的文件列表。"""

    findings: list[tuple[Path, list[tuple[int, str]]]] = []
    for path in iter_python_files(root):
        private_defs = collect_module_private_defs(path)
        if private_defs:
            findings.append((path, private_defs))
    return findings


def parse_args() -> argparse.Namespace:
    """解析命令行参数。"""

    parser = argparse.ArgumentParser(
        description="Scan module-level underscore-prefixed function definitions under src/channel_topology_graph.",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path("algorithms/channel_topology_graph"),
        help="Root package directory to scan.",
    )
    return parser.parse_args()


def main() -> int:
    """执行扫描并输出结果。"""

    args = parse_args()
    root = args.root.resolve()
    findings = scan_root(root)
    if not findings:
        print(f"OK: no module-level private defs under {root}")
        return 0

    print(f"FOUND {sum(len(items) for _, items in findings)} module-level private defs under {root}")
    for path, items in findings:
        print(path)
        for lineno, name in items:
            print(f"  {lineno}: {name}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
