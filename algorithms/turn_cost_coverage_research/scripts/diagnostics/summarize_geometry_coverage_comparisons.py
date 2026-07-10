#!/usr/bin/env python3
"""汇总多区域两方案几何覆盖诊断 comparison_summary.json。"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, required=True, help="包含 *_两方案几何覆盖对比 目录的输出根目录。")
    parser.add_argument("--output-json", type=Path, required=True, help="汇总 JSON 输出路径。")
    parser.add_argument(
        "--require-area-underscore",
        action="store_true",
        help="只汇总名称包含 _area_<数字> 的正式批量区域，排除 area5 这类临时样例命名。",
    )
    return parser.parse_args()


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    args = parse_args()
    root = args.output_root.expanduser().resolve()
    rows: list[dict[str, Any]] = []
    for summary_path in sorted(root.glob("*_两方案几何覆盖对比/comparison_summary.json")):
        data = _read_json(summary_path)
        case_name = str(data.get("case_name", ""))
        if args.require_area_underscore and re.search(r"_area_\d+$", case_name) is None:
            continue
        row: dict[str, Any] = {
            "case_name": case_name,
            "summary_path": str(summary_path),
        }
        for key, values in data.get("metric_comparison", {}).items():
            if not isinstance(values, dict):
                continue
            row[f"{key}__shelfAware"] = values.get("shelfAware")
            row[f"{key}__ShelfAwareTurnCost"] = values.get("ShelfAware+TurnCost")
            row[f"{key}__delta"] = values.get("turn_cost_minus_shelfAware")
        rows.append(row)

    aggregate = {
        "version": "geometry_coverage_comparison_aggregate.v1",
        "source_root": str(root),
        "case_count": len(rows),
        "rows": rows,
    }
    args.output_json.expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
    args.output_json.expanduser().resolve().write_text(json.dumps(aggregate, ensure_ascii=False, indent=2), encoding="utf-8")
    print(args.output_json.expanduser().resolve())


if __name__ == "__main__":
    main()
