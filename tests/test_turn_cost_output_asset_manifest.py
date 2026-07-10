from __future__ import annotations

import json

from algorithms.turn_cost_coverage_research.scripts.diagnostics import build_output_asset_manifest as manifest_mod
from algorithms.turn_cost_coverage_research.scripts.diagnostics.build_output_asset_manifest import (
    build_delete_candidates_markdown,
    build_delete_review_summary_markdown,
    build_manifest,
    validate_review_summary_options,
)


def test_build_output_asset_manifest_classifies_and_counts_doc_references(tmp_path):
    output_root = tmp_path / "output"
    docs_root = tmp_path / "docs"
    baseline_dir = output_root / "run_20260523_161642_160632_shelf_aware_all_areas"
    diagnostic_dir = output_root / "run_20260527_201830_282334_geometry_readonly_diagnostic"
    unknown_dir = output_root / "run_20260517_000000_misc"
    baseline_dir.mkdir(parents=True)
    diagnostic_dir.mkdir(parents=True)
    unknown_dir.mkdir(parents=True)
    docs_root.mkdir(parents=True)

    (baseline_dir / "summary.json").write_text(json.dumps({"ok": True}), encoding="utf-8")
    (diagnostic_dir / "comparison_summary.json").write_text(json.dumps({"ok": True}), encoding="utf-8")
    (diagnostic_dir / "final_segment_provenance.json").write_text(json.dumps({"ok": True}), encoding="utf-8")
    (diagnostic_dir / "overview.png").write_bytes(b"png")
    (unknown_dir / "notes.txt").write_text("temporary", encoding="utf-8")
    (docs_root / "引用.md").write_text(
        "保留 run_20260517_000000_misc 作为历史讨论证据。",
        encoding="utf-8",
    )

    manifest = build_manifest(output_root, docs_root, limit=0)
    entries = {entry["relative_path"]: entry for entry in manifest["entries"]}

    assert manifest["schema_version"] == "turn_cost_output_asset_manifest.v1"
    assert manifest["asset_count"] == 3
    assert entries[baseline_dir.name]["status"] == "baseline"
    assert entries[diagnostic_dir.name]["status"] == "diagnostic"
    assert entries[diagnostic_dir.name]["png_count"] == 1
    assert entries[diagnostic_dir.name]["key_files"] == ["comparison_summary.json", "final_segment_provenance.json"]
    assert entries[unknown_dir.name]["status"] == "superseded_but_referenced"
    assert entries[unknown_dir.name]["doc_reference_count"] == 1
    assert entries[unknown_dir.name]["recommended_action"] == "keep"


def test_output_asset_delete_candidates_exclude_referenced_assets(tmp_path):
    output_root = tmp_path / "output"
    docs_root = tmp_path / "docs"
    referenced_dir = output_root / "run_20260517_referenced_misc"
    unreferenced_dir = output_root / "run_20260517_duplicate_misc"
    referenced_dir.mkdir(parents=True)
    unreferenced_dir.mkdir(parents=True)
    docs_root.mkdir(parents=True)

    (referenced_dir / "notes.txt").write_text("temporary", encoding="utf-8")
    (unreferenced_dir / "notes.txt").write_text("temporary", encoding="utf-8")
    (docs_root / "引用.md").write_text(
        "保留 run_20260517_referenced_misc 作为历史讨论证据。",
        encoding="utf-8",
    )

    manifest = build_manifest(output_root, docs_root, limit=0)
    markdown = build_delete_candidates_markdown(manifest)

    assert "`run_20260517_duplicate_misc`" in markdown
    assert "`run_20260517_referenced_misc`" not in markdown
    assert "review_candidate_count: `1`" in markdown


def test_output_asset_delete_candidates_are_sorted_by_size_with_review_gate(tmp_path):
    output_root = tmp_path / "output"
    docs_root = tmp_path / "docs"
    small_dir = output_root / "run_20260517_duplicate_small_misc"
    large_dir = output_root / "run_20260517_duplicate_large_misc"
    baseline_dir = output_root / "run_20260523_161642_160632_shelf_aware_all_areas"
    for path in (small_dir, large_dir, baseline_dir, docs_root):
        path.mkdir(parents=True)

    (small_dir / "notes.txt").write_bytes(b"small")
    (large_dir / "image.png").write_bytes(b"x" * 1024)
    (baseline_dir / "summary.json").write_text(json.dumps({"ok": True}), encoding="utf-8")

    manifest = build_manifest(output_root, docs_root, limit=0)
    markdown = build_delete_candidates_markdown(manifest)

    assert "删除前硬门槛" in markdown
    assert "review_candidate_count: `2`" in markdown
    assert markdown.index("`run_20260517_duplicate_large_misc`") < markdown.index("`run_20260517_duplicate_small_misc`")
    assert "`run_20260523_161642_160632_shelf_aware_all_areas`" not in markdown


def test_output_asset_review_summary_is_source_control_friendly(tmp_path):
    output_root = tmp_path / "output"
    docs_root = tmp_path / "docs"
    candidate_dir = output_root / "run_20260517_duplicate_misc"
    referenced_dir = output_root / "run_20260517_referenced_misc"
    baseline_dir = output_root / "run_20260523_161642_160632_shelf_aware_all_areas"
    for path in (candidate_dir, referenced_dir, baseline_dir, docs_root):
        path.mkdir(parents=True)

    (candidate_dir / "summary.json").write_bytes(b"x" * 2048)
    (referenced_dir / "summary.json").write_text(json.dumps({"ok": True}), encoding="utf-8")
    (baseline_dir / "summary.json").write_text(json.dumps({"ok": True}), encoding="utf-8")
    (docs_root / "引用.md").write_text("引用 run_20260517_referenced_misc。", encoding="utf-8")

    manifest = build_manifest(output_root, docs_root, limit=0)
    summary = build_delete_review_summary_markdown(manifest, max_candidates=5)

    assert "可提交的复核摘要，不是删除许可" in summary
    assert "review_candidate_count: `1`" in summary
    assert "review_candidate_size: `2.0KB`" in summary
    assert "`run_20260517_duplicate_misc`" in summary
    assert "`run_20260517_referenced_misc`" not in summary
    assert "`run_20260523_161642_160632_shelf_aware_all_areas`" not in summary
    assert "删除动作单独提交" in summary
    assert "`unknown_needs_review` 只表示未命中自动分类规则" in summary


def test_output_asset_review_summary_requires_full_scan():
    validate_review_summary_options(write_review_summary=True, limit=0)
    validate_review_summary_options(write_review_summary=False, limit=3)

    try:
        validate_review_summary_options(write_review_summary=True, limit=3)
    except ValueError as exc:
        assert "--write-review-summary requires a full scan" in str(exc)
    else:
        raise AssertionError("expected limited review summary to be rejected")


def test_output_asset_review_summary_excludes_named_keep_categories(tmp_path):
    output_root = tmp_path / "output"
    docs_root = tmp_path / "docs"
    candidate_dir = output_root / "run_20260517_duplicate_misc"
    baseline_dir = output_root / "run_20260523_161642_160632_shelf_aware_all_areas"
    turn_cost_dir = output_root / "run_20260618_shelf_aware_turn_cost_all_areas"
    diagnostic_dir = output_root / "run_20260527_geometry_readonly_diagnostic"
    for path in (candidate_dir, baseline_dir, turn_cost_dir, diagnostic_dir, docs_root):
        path.mkdir(parents=True)

    for path in (candidate_dir, baseline_dir, turn_cost_dir, diagnostic_dir):
        (path / "summary.json").write_text(json.dumps({"ok": True}), encoding="utf-8")

    manifest = build_manifest(output_root, docs_root, limit=0)
    summary = build_delete_review_summary_markdown(manifest, max_candidates=10)

    assert "review_candidate_count: `1`" in summary
    assert "`run_20260517_duplicate_misc`" in summary
    assert "`run_20260523_161642_160632_shelf_aware_all_areas`" not in summary
    assert "`run_20260618_shelf_aware_turn_cost_all_areas`" not in summary
    assert "`run_20260527_geometry_readonly_diagnostic`" not in summary


def test_output_asset_manifest_classifies_research_evidence_by_name(tmp_path):
    output_root = tmp_path / "output"
    docs_root = tmp_path / "docs"
    replacement_experiment = output_root / "替换覆盖节点生成实验_area5_20260522_122853"
    reconnect_experiment = output_root / "run_20260523_092418_912326_batch_candidate_reconnect"
    geometry_aggregate = output_root / "geometry_coverage_comparison_aggregate_20260527.json"
    for path in (replacement_experiment, reconnect_experiment, docs_root):
        path.mkdir(parents=True)
    geometry_aggregate.parent.mkdir(parents=True, exist_ok=True)

    (replacement_experiment / "实验1_规则节点_shelf原链路_最终诊断_summary.json").write_text("{}", encoding="utf-8")
    (reconnect_experiment / "summary.json").write_text(
        json.dumps({"algorithm_scope": {"type": "non_official_batch_window_experiment"}}),
        encoding="utf-8",
    )
    geometry_aggregate.write_text(json.dumps({"ok": True}), encoding="utf-8")

    manifest = build_manifest(output_root, docs_root, limit=0)
    entries = {entry["relative_path"]: entry for entry in manifest["entries"]}
    markdown = build_delete_candidates_markdown(manifest)

    assert entries[replacement_experiment.name]["status"] == "rejected_evidence"
    assert entries[replacement_experiment.name]["recommended_action"] == "keep"
    assert entries[reconnect_experiment.name]["status"] == "rejected_evidence"
    assert entries[geometry_aggregate.name]["status"] == "diagnostic"
    assert "`替换覆盖节点生成实验_area5_20260522_122853`" not in markdown
    assert "`run_20260523_092418_912326_batch_candidate_reconnect`" not in markdown
    assert "`geometry_coverage_comparison_aggregate_20260527.json`" not in markdown


def test_output_asset_manifest_classifies_official_summary_as_archived_reference(tmp_path):
    output_root = tmp_path / "output"
    docs_root = tmp_path / "docs"
    official_dir = output_root / "run_20260512_214903_845611"
    square8_dir = output_root / "run_20260517_192121_982018"
    misc_dir = output_root / "run_20260517_unreferenced_misc"
    for path in (official_dir, square8_dir, misc_dir, docs_root):
        path.mkdir(parents=True)

    (official_dir / "summary.json").write_text(
        json.dumps({"runner": "run_maptools_official_cases", "case_group": "maptools_official_algorithm_steps"}),
        encoding="utf-8",
    )
    (square8_dir / "summary.json").write_text(
        json.dumps({"case_group": "maptools_square8_axis_guided_graph_corridor_axis_atomic_flow"}),
        encoding="utf-8",
    )
    (misc_dir / "summary.json").write_text(json.dumps({"case_group": "misc"}), encoding="utf-8")

    manifest = build_manifest(output_root, docs_root, limit=0)
    entries = {entry["relative_path"]: entry for entry in manifest["entries"]}
    markdown = build_delete_candidates_markdown(manifest)

    assert entries[official_dir.name]["status"] == "archived_reference"
    assert entries[square8_dir.name]["status"] == "rejected_evidence"
    assert entries[misc_dir.name]["status"] == "unknown_needs_review"
    assert entries[misc_dir.name]["recommended_action"] == "classify_before_delete"
    assert "`run_20260512_214903_845611`" not in markdown
    assert "`run_20260517_192121_982018`" not in markdown
    assert "`run_20260517_unreferenced_misc`" not in markdown


def test_output_asset_manifest_ignores_generated_review_summary_self_references(tmp_path, monkeypatch):
    output_root = tmp_path / "output"
    docs_root = tmp_path / "docs"
    candidate_dir = output_root / "run_20260517_duplicate_misc"
    review_summary = docs_root / "02_代码事实" / "04_output删除候选复核摘要.md"
    candidate_dir.mkdir(parents=True)
    review_summary.parent.mkdir(parents=True)
    (candidate_dir / "summary.json").write_text(json.dumps({"ok": True}), encoding="utf-8")
    review_summary.write_text("Top 候选 `run_20260517_duplicate_misc`。", encoding="utf-8")
    monkeypatch.setattr(manifest_mod, "DEFAULT_REVIEW_SUMMARY_PATH", review_summary)

    manifest = build_manifest(output_root, docs_root, limit=0)
    entries = {entry["relative_path"]: entry for entry in manifest["entries"]}

    assert entries["run_20260517_duplicate_misc"]["doc_reference_count"] == 0
    assert entries["run_20260517_duplicate_misc"]["recommended_action"] == "delete_after_review"
