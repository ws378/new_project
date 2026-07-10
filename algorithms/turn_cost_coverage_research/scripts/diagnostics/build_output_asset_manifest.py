#!/usr/bin/env python3
"""只读扫描 turn_cost_coverage_research/output 资产并生成本地 manifest。"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[4]
RESEARCH_ROOT = REPO_ROOT / "algorithms" / "turn_cost_coverage_research"
DEFAULT_OUTPUT_ROOT = RESEARCH_ROOT / "output"
DEFAULT_DOCS_ROOT = RESEARCH_ROOT / "docs"
DEFAULT_MANIFEST_PATH = DEFAULT_OUTPUT_ROOT / "output_asset_manifest.local.json"
DEFAULT_DELETE_CANDIDATES_PATH = DEFAULT_OUTPUT_ROOT / "output_delete_candidates.local.md"
DEFAULT_REVIEW_SUMMARY_PATH = (
    RESEARCH_ROOT
    / "docs"
    / "02_代码事实"
    / "04_output删除候选复核摘要.md"
)

STATUS_VALUES = (
    "baseline",
    "candidate_mode_evidence",
    "diagnostic",
    "rejected_evidence",
    "archived_reference",
    "superseded_but_referenced",
    "duplicate",
    "interrupted",
    "unknown_needs_review",
    "delete_candidate",
)

KEY_FILENAMES = {
    "summary.json",
    "metadata.json",
    "manifest.json",
    "comparison_summary.json",
    "path_pixels.json",
    "final_segment_provenance.json",
    "quality_guarded_post_opt_path_pixels.json",
    "batch_candidate_reconnect_path_pixels.json",
}


@dataclass(frozen=True)
class OutputAssetEntry:
    relative_path: str
    asset_type: str
    status: str
    recommended_action: str
    size_bytes: int
    file_count: int
    png_count: int
    json_count: int
    key_files: list[str]
    doc_reference_count: int
    doc_reference_files: list[str]
    mtime: str
    classification_reason: list[str]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT, help="要扫描的 output 根目录。")
    parser.add_argument("--docs-root", type=Path, default=DEFAULT_DOCS_ROOT, help="用于统计引用次数的 docs 根目录。")
    parser.add_argument(
        "--manifest-path",
        type=Path,
        default=DEFAULT_MANIFEST_PATH,
        help="--write-local 时写入的本地 manifest 路径。",
    )
    parser.add_argument("--write-local", action="store_true", help="写入本地 manifest。默认只打印摘要，不写文件。")
    parser.add_argument(
        "--write-delete-candidates-local",
        action="store_true",
        help="写入本地删除复核候选表。只列复核对象，不删除文件。",
    )
    parser.add_argument(
        "--delete-candidates-path",
        type=Path,
        default=DEFAULT_DELETE_CANDIDATES_PATH,
        help="--write-delete-candidates-local 时写入的本地 Markdown 路径。",
    )
    parser.add_argument(
        "--write-review-summary",
        action="store_true",
        help="写入可提交的删除复核摘要。只记录候选概览，不删除文件。",
    )
    parser.add_argument(
        "--review-summary-path",
        type=Path,
        default=DEFAULT_REVIEW_SUMMARY_PATH,
        help="--write-review-summary 时写入的 Markdown 路径。",
    )
    parser.add_argument("--limit", type=int, default=0, help="只扫描前 N 个顶层资产，用于快速 smoke。0 表示不限制。")
    return parser.parse_args()


def _relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def _read_text_safely(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def _load_doc_texts(docs_root: Path) -> dict[str, str]:
    if not docs_root.exists():
        return {}
    generated_review_summary = DEFAULT_REVIEW_SUMMARY_PATH.resolve()
    docs: dict[str, str] = {}
    for path in sorted(docs_root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in {".md", ".json", ".txt"}:
            continue
        if path.resolve() == generated_review_summary:
            continue
        docs[_relative(path)] = _read_text_safely(path)
    return docs


def _doc_references(asset_path: Path, docs: dict[str, str]) -> tuple[int, list[str]]:
    rel = _relative(asset_path)
    name = asset_path.name
    refs: list[str] = []
    for doc_path, text in docs.items():
        if rel in text or name in text:
            refs.append(doc_path)
    return len(refs), refs[:20]


def _load_asset_summary(asset_path: Path) -> dict[str, Any]:
    summary_path = asset_path if asset_path.is_file() else asset_path / "summary.json"
    if not summary_path.is_file():
        return {}
    try:
        payload = json.loads(summary_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _asset_status(asset_path: Path, doc_reference_count: int, summary: dict[str, Any]) -> tuple[str, list[str]]:
    name = asset_path.name
    lower = name.lower()
    reasons: list[str] = []
    if "baseline" in lower or "shelf_aware_all_areas" in lower or "ui_stable_all_areas" in lower:
        reasons.append("名称命中 baseline / shelf_aware_all_areas / ui_stable_all_areas。")
        return "baseline", reasons
    if "shelf_aware_turn_cost" in lower or "ui_shelf_turn_cost" in lower or "turn_cost_repaired_grid" in lower:
        reasons.append("名称命中 ShelfAware+TurnCost 候选 mode 证据。")
        return "candidate_mode_evidence", reasons
    if (
        "diagnostic" in lower
        or "诊断" in name
        or "两方案几何覆盖对比" in name
        or "geometry_coverage_comparison" in lower
        or "annotated_window" in lower
        or "lane_window_inspection" in lower
    ):
        reasons.append("名称命中 diagnostic / 诊断 / 几何对比 / 标注窗口 / lane inspection。")
        return "diagnostic", reasons
    if (
        "替换覆盖节点生成实验" in name
        or "batch_candidate_reconnect" in lower
        or "quality_guarded_post_opt" in lower
        or "shelf_path_turn_cost_reconnect" in lower
        or "shelf_path_turn_cost_post_opt" in lower
        or "shelf_path_turn_cost_node_snap" in lower
        or "shelf_path_lane_spacing_balance" in lower
        or "shelf_path_endpoint_alignment_guard" in lower
        or "shelf_path_lane_family" in lower
    ):
        reasons.append("名称命中已归档的非正式研究实验或失败路线证据。")
        return "rejected_evidence", reasons
    if "archived" in lower:
        reasons.append("名称命中 archived。")
        return "archived_reference", reasons
    if "duplicate" in lower or "重复" in name:
        reasons.append("名称命中 duplicate / 重复，进入删除前复核。")
        return "duplicate", reasons
    if "interrupted" in lower or "partial" in lower or "中断" in name:
        reasons.append("名称命中 interrupted / partial / 中断，进入删除前复核。")
        return "interrupted", reasons
    runner = str(summary.get("runner", ""))
    case_group = str(summary.get("case_group", ""))
    algorithm_scope = summary.get("algorithm_scope", {})
    algorithm_scope_type = ""
    if isinstance(algorithm_scope, dict):
        algorithm_scope_type = str(algorithm_scope.get("type", ""))
    summary_text = " ".join([runner, case_group, algorithm_scope_type]).lower()
    if "run_maptools_official_cases" in runner or "paper_official" in summary_text or "official_algorithm" in summary_text:
        reasons.append("summary 命中论文 official / MapTools official 复现实验，作为参考证据保留。")
        return "archived_reference", reasons
    if "square8" in summary_text or "axis_guided" in summary_text or "corridor_axis" in summary_text:
        reasons.append("summary 命中 square8 / axis-guided / corridor-axis 非正式研究证据。")
        return "rejected_evidence", reasons
    if "experiment" in summary_text or "non_official" in summary_text:
        reasons.append("summary 命中非正式 experiment / non_official 研究证据。")
        return "rejected_evidence", reasons
    if doc_reference_count > 0:
        reasons.append("未命中明确类型，但已被文档引用，暂按被引用证据保留。")
        return "superseded_but_referenced", reasons
    reasons.append("未命中明确类型，必须先补分类或替代证据，不能直接进入删除候选。")
    return "unknown_needs_review", reasons


def _recommended_action(status: str) -> str:
    if status in {"baseline", "candidate_mode_evidence", "diagnostic", "rejected_evidence", "archived_reference", "superseded_but_referenced"}:
        return "keep"
    if status == "unknown_needs_review":
        return "classify_before_delete"
    if status in {"duplicate", "interrupted", "delete_candidate"}:
        return "delete_after_review"
    return "review"


def _scan_asset(asset_path: Path, output_root: Path, docs: dict[str, str]) -> OutputAssetEntry:
    files = [asset_path] if asset_path.is_file() else [path for path in asset_path.rglob("*") if path.is_file()]
    size_bytes = 0
    png_count = 0
    json_count = 0
    key_files: list[str] = []
    latest_mtime = asset_path.stat().st_mtime
    for path in files:
        try:
            stat = path.stat()
        except OSError:
            continue
        size_bytes += int(stat.st_size)
        latest_mtime = max(latest_mtime, stat.st_mtime)
        if path.suffix.lower() == ".png":
            png_count += 1
        if path.suffix.lower() == ".json":
            json_count += 1
        if path.name in KEY_FILENAMES:
            key_files.append(path.relative_to(asset_path if asset_path.is_dir() else output_root).as_posix())
    doc_reference_count, doc_reference_files = _doc_references(asset_path, docs)
    summary = _load_asset_summary(asset_path)
    status, reasons = _asset_status(asset_path, doc_reference_count, summary)
    asset_type = "file" if asset_path.is_file() else "directory"
    return OutputAssetEntry(
        relative_path=asset_path.relative_to(output_root).as_posix(),
        asset_type=asset_type,
        status=status,
        recommended_action=_recommended_action(status),
        size_bytes=size_bytes,
        file_count=len(files),
        png_count=png_count,
        json_count=json_count,
        key_files=sorted(key_files)[:50],
        doc_reference_count=doc_reference_count,
        doc_reference_files=doc_reference_files,
        mtime=datetime.fromtimestamp(latest_mtime, tz=timezone.utc).isoformat(),
        classification_reason=reasons,
    )


def build_manifest(output_root: Path, docs_root: Path, limit: int) -> dict[str, Any]:
    output_root = output_root.expanduser().resolve()
    docs_root = docs_root.expanduser().resolve()
    docs = _load_doc_texts(docs_root)
    assets = sorted((path for path in output_root.iterdir() if path.name != ".gitignore"), key=lambda path: path.name)
    if limit > 0:
        assets = assets[:limit]
    entries = [_scan_asset(path, output_root, docs) for path in assets]
    status_counts: dict[str, int] = {status: 0 for status in STATUS_VALUES}
    for entry in entries:
        status_counts[entry.status] = status_counts.get(entry.status, 0) + 1
    return {
        "schema_version": "turn_cost_output_asset_manifest.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "output_root": _relative(output_root),
        "docs_root": _relative(docs_root),
        "asset_count": len(entries),
        "status_values": list(STATUS_VALUES),
        "status_counts": {key: value for key, value in status_counts.items() if value > 0},
        "entries": [asdict(entry) for entry in entries],
    }


def _format_size(size_bytes: int) -> str:
    units = ("B", "KB", "MB", "GB")
    value = float(size_bytes)
    for unit in units:
        if value < 1024.0 or unit == units[-1]:
            return f"{value:.1f}{unit}" if unit != "B" else f"{int(value)}B"
        value /= 1024.0
    return f"{int(size_bytes)}B"


def validate_review_summary_options(*, write_review_summary: bool, limit: int) -> None:
    """Prevent smoke scans from being committed as authoritative review summaries."""

    if bool(write_review_summary) and int(limit or 0) > 0:
        raise ValueError("--write-review-summary requires a full scan; do not combine it with --limit.")


def _delete_candidate_entries(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    entries = [dict(item) for item in manifest.get("entries", [])]
    candidates = [
        item
        for item in entries
        if str(item.get("recommended_action", "")) == "delete_after_review"
        and int(item.get("doc_reference_count", 0) or 0) == 0
        and str(item.get("status", "")) in {"duplicate", "interrupted", "delete_candidate"}
    ]
    return sorted(
        candidates,
        key=lambda item: (str(item.get("status", "")), -int(item.get("size_bytes", 0) or 0), str(item.get("relative_path", ""))),
    )


def build_delete_candidates_markdown(manifest: dict[str, Any]) -> str:
    """Build a human-readable review list without changing manifest statuses."""

    candidates = _delete_candidate_entries(manifest)
    lines: list[str] = [
        "# output 删除复核候选",
        "",
        "本文档由 `build_output_asset_manifest.py --write-delete-candidates-local` 生成。",
        "它只列出需要复核的本地 output 资产，不代表已经允许删除。",
        "",
        "## 1. 摘要",
        "",
        f"- manifest_schema: `{manifest.get('schema_version', '')}`",
        f"- generated_at: `{manifest.get('generated_at', '')}`",
        f"- output_root: `{manifest.get('output_root', '')}`",
        f"- asset_count: `{manifest.get('asset_count', 0)}`",
        f"- review_candidate_count: `{len(candidates)}`",
        "",
        "## 2. 删除前硬门槛",
        "",
        "- `doc_reference_count=0`；",
        "- 非 baseline / candidate / diagnostic / referenced；",
        "- 有更高质量替代证据，或确认是重复、失败、中断、临时产物；",
        "- 固定弱门禁复核无阻断；",
        "- 删除动作单独提交。",
        "",
        "## 3. 候选列表",
        "",
    ]
    if not candidates:
        lines.append("当前没有自动筛出的删除复核候选。")
        lines.append("")
        return "\n".join(lines)

    lines.append("| 路径 | 状态 | 大小 | 文件数 | PNG | JSON | 关键文件 | 最新修改时间 | 初判原因 |")
    lines.append("| --- | --- | ---: | ---: | ---: | ---: | --- | --- | --- |")
    for item in candidates:
        key_files = ", ".join(str(path) for path in item.get("key_files", [])[:5]) or "-"
        reasons = "；".join(str(reason) for reason in item.get("classification_reason", [])) or "-"
        lines.append(
            "| "
            + " | ".join(
                [
                    f"`{item.get('relative_path', '')}`",
                    f"`{item.get('status', '')}`",
                    _format_size(int(item.get("size_bytes", 0) or 0)),
                    str(int(item.get("file_count", 0) or 0)),
                    str(int(item.get("png_count", 0) or 0)),
                    str(int(item.get("json_count", 0) or 0)),
                    key_files,
                    f"`{item.get('mtime', '')}`",
                    reasons.replace("|", "/"),
                ]
            )
            + " |"
        )
    lines.append("")
    return "\n".join(lines)


def build_delete_review_summary_markdown(manifest: dict[str, Any], *, max_candidates: int = 20) -> str:
    """Build a source-controlled review summary without listing every asset."""

    candidates = _delete_candidate_entries(manifest)
    candidate_size = sum(int(item.get("size_bytes", 0) or 0) for item in candidates)
    status_counts = dict(manifest.get("status_counts", {}) or {})
    top_candidates = candidates[: max(0, int(max_candidates))]
    lines: list[str] = [
        "# output 删除候选复核摘要",
        "",
        "本文档由 `build_output_asset_manifest.py --write-review-summary` 生成。",
        "它是可提交的复核摘要，不是删除许可；具体删除仍必须单独复核并单独提交。",
        "",
        "## 1. 本次扫描概览",
        "",
        f"- manifest_schema: `{manifest.get('schema_version', '')}`",
        f"- generated_at: `{manifest.get('generated_at', '')}`",
        f"- output_root: `{manifest.get('output_root', '')}`",
        f"- docs_root: `{manifest.get('docs_root', '')}`",
        f"- asset_count: `{manifest.get('asset_count', 0)}`",
        f"- review_candidate_count: `{len(candidates)}`",
        f"- review_candidate_size: `{_format_size(candidate_size)}`",
        "",
        "## 2. 状态统计",
        "",
        "| 状态 | 数量 |",
        "| --- | ---: |",
    ]
    for status, count in sorted(status_counts.items()):
        lines.append(f"| `{status}` | {int(count)} |")
    lines.extend(
        [
            "",
            "## 3. 删除复核硬门槛",
            "",
            "- `doc_reference_count=0`；",
            "- 非 baseline / candidate / diagnostic / referenced；",
            "- 有更高质量替代证据，或确认是重复、失败、中断、临时产物；",
            "- 固定弱门禁确认无阻断；",
            "- 删除动作单独提交；",
            "- 删除提交说明必须写清影响范围、验证情况、证据路径和关联跟踪。",
            "- `unknown_needs_review` 只表示未命中自动分类规则，必须先补分类或替代证据，不能直接作为删除候选。",
            "",
            "## 4. Top 候选",
            "",
        ]
    )
    if not top_candidates:
        lines.append("当前没有自动筛出的删除复核候选。")
    else:
        lines.append("| 路径 | 状态 | 大小 | 文件数 | PNG | JSON | 关键文件 | 初判原因 |")
        lines.append("| --- | --- | ---: | ---: | ---: | ---: | --- | --- |")
        for item in top_candidates:
            key_files = ", ".join(str(path) for path in item.get("key_files", [])[:3]) or "-"
            reasons = "；".join(str(reason) for reason in item.get("classification_reason", [])) or "-"
            lines.append(
                "| "
                + " | ".join(
                    [
                        f"`{item.get('relative_path', '')}`",
                        f"`{item.get('status', '')}`",
                        _format_size(int(item.get("size_bytes", 0) or 0)),
                        str(int(item.get("file_count", 0) or 0)),
                        str(int(item.get("png_count", 0) or 0)),
                        str(int(item.get("json_count", 0) or 0)),
                        key_files.replace("|", "/"),
                        reasons.replace("|", "/"),
                    ]
                )
                + " |"
            )
    lines.extend(
        [
            "",
            "## 5. 当前处置结论",
            "",
            "- 本批只完成候选复核摘要，不删除 output；",
            "- `output/output_asset_manifest.local.json` 和 `output/output_delete_candidates.local.md` 仍是本地 ignored 证据，不提交；",
            "- `review_candidate_count=0` 只表示当前没有自动删除候选，不表示 output 已经完成体积收敛；",
            "- `rejected_evidence` 和 `archived_reference` 仍需后续按代表性证据策略做外部归档或压缩摘要，不能在本批直接删除。",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    args = parse_args()
    validate_review_summary_options(write_review_summary=args.write_review_summary, limit=args.limit)
    manifest = build_manifest(args.output_root, args.docs_root, args.limit)
    print(
        json.dumps(
            {
                "schema_version": manifest["schema_version"],
                "output_root": manifest["output_root"],
                "asset_count": manifest["asset_count"],
                "status_counts": manifest["status_counts"],
                "write_local": bool(args.write_local),
                "write_delete_candidates_local": bool(args.write_delete_candidates_local),
                "write_review_summary": bool(args.write_review_summary),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    if args.write_local:
        manifest_path = args.manifest_path.expanduser().resolve()
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(_relative(manifest_path))
    if args.write_delete_candidates_local:
        candidates_path = args.delete_candidates_path.expanduser().resolve()
        candidates_path.parent.mkdir(parents=True, exist_ok=True)
        candidates_path.write_text(build_delete_candidates_markdown(manifest), encoding="utf-8")
        print(_relative(candidates_path))
    if args.write_review_summary:
        review_path = args.review_summary_path.expanduser().resolve()
        review_path.parent.mkdir(parents=True, exist_ok=True)
        review_path.write_text(build_delete_review_summary_markdown(manifest), encoding="utf-8")
        print(_relative(review_path))


if __name__ == "__main__":
    main()
