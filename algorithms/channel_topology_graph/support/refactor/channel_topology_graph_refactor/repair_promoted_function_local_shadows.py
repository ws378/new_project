"""修复模块级函数公开化后产生的局部变量遮蔽问题。"""

from __future__ import annotations

import argparse
import ast
import io
import tokenize
from pathlib import Path


def parse_args() -> argparse.Namespace:
    """解析命令行参数。"""

    parser = argparse.ArgumentParser(
        description="Repair local bindings that shadow promoted module-level function names.",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path("algorithms/channel_topology_graph"),
        help="Root package directory to scan and rewrite.",
    )
    return parser.parse_args()


def iter_python_files(root: Path) -> list[Path]:
    """按稳定顺序收集目录下所有 Python 文件。"""

    return sorted(path for path in root.rglob("*.py") if path.is_file())


def collect_module_function_names(tree: ast.Module) -> set[str]:
    """收集模块级函数名。"""

    return {
        str(node.name)
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def collect_function_local_bindings(node: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    """收集一个函数作用域内的局部绑定名。"""

    bindings = {
        str(arg.arg)
        for arg in node.args.posonlyargs + node.args.args + node.args.kwonlyargs
    }
    if node.args.vararg is not None:
        bindings.add(str(node.args.vararg.arg))
    if node.args.kwarg is not None:
        bindings.add(str(node.args.kwarg.arg))

    for inner in ast.walk(node):
        if isinstance(inner, ast.Name) and isinstance(inner.ctx, ast.Store):
            bindings.add(str(inner.id))
    return bindings


def collect_shadow_replacements(path: Path) -> dict[tuple[int, int], str]:
    """返回一个文件内所有局部遮蔽修复位置。"""

    text = path.read_text(encoding="utf-8")
    tree = ast.parse(text, filename=str(path))
    module_function_names = collect_module_function_names(tree)
    replacements: dict[tuple[int, int], str] = {}

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        shadowed_names = sorted(collect_function_local_bindings(node) & module_function_names)
        for shadowed_name in shadowed_names:
            replacement_name = f"{shadowed_name}_local"
            for inner in ast.walk(node):
                if isinstance(inner, ast.Name) and inner.id == shadowed_name:
                    replacements[(int(inner.lineno), int(inner.col_offset))] = replacement_name
                if isinstance(inner, ast.arg) and inner.arg == shadowed_name:
                    replacements[(int(inner.lineno), int(inner.col_offset))] = replacement_name
    return replacements


def collect_self_call_restorations(path: Path) -> dict[tuple[int, int], str]:
    """修复 `foo_local = foo_local(...)` 这类误改成自调用的模式。"""

    text = path.read_text(encoding="utf-8")
    tree = ast.parse(text, filename=str(path))
    module_function_names = collect_module_function_names(tree)
    restorations: dict[tuple[int, int], str] = {}

    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        value = node.value
        if not isinstance(target, ast.Name) or not isinstance(value, ast.Call):
            continue
        if not isinstance(value.func, ast.Name):
            continue
        target_name = str(target.id)
        func_name = str(value.func.id)
        if not target_name.endswith("_local"):
            continue
        if func_name != target_name:
            continue
        base_name = target_name[: -len("_local")]
        if base_name not in module_function_names:
            continue
        restorations[(int(value.func.lineno), int(value.func.col_offset))] = base_name
    return restorations


def rewrite_file(path: Path, replacements: dict[tuple[int, int], str]) -> int:
    """按位置精确替换一个文件中的遮蔽局部名字。"""

    if not replacements:
        return 0
    text = path.read_text(encoding="utf-8")
    tokens = list(tokenize.generate_tokens(io.StringIO(text).readline))
    rewritten: list[tokenize.TokenInfo] = []
    count = 0
    for token in tokens:
        key = (int(token.start[0]), int(token.start[1]))
        if token.type == tokenize.NAME and key in replacements:
            rewritten.append(token._replace(string=replacements[key]))
            count += 1
            continue
        rewritten.append(token)
    if count <= 0:
        return 0
    path.write_text(tokenize.untokenize(rewritten), encoding="utf-8")
    return count


def main() -> int:
    """执行修复。"""

    args = parse_args()
    root = args.root.resolve()
    rewritten_files = 0
    rewritten_tokens = 0
    for path in iter_python_files(root):
        replacements = collect_shadow_replacements(path)
        replacements.update(collect_self_call_restorations(path))
        changed = rewrite_file(path, replacements)
        if changed <= 0:
            continue
        rewritten_files += 1
        rewritten_tokens += changed
        print(f"{path}: repaired {changed} local shadow tokens")
    print(f"REPAIRED files={rewritten_files} tokens={rewritten_tokens}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
