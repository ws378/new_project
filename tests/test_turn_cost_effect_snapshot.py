from __future__ import annotations

import json
from pathlib import Path

import pytest

from algorithms.turn_cost_coverage_research.scripts.diagnostics.build_effect_snapshot import (
    EffectGateConfig,
    build_snapshot,
    compare_snapshots,
)
from algorithms.turn_cost_coverage_research.scripts.diagnostics.effect_metric_contract import (
    EFFECT_METRIC_CONTRACT_VERSION,
    effect_metric_contract_payload,
    effect_metric_names,
    gated_effect_metric_names,
    not_gated_effect_metric_names,
)


def _write_path(path: Path, points: list[list[float]]) -> str:
    path.write_text(json.dumps(points, ensure_ascii=False), encoding="utf-8")
    return str(path)


def _summary(tmp_path: Path, *, coverage: float, long_jump_count: int, path_name: str = "path.json") -> dict[str, object]:
    return {
        "runner": "run_ui_shelf_turn_cost_grid_all_areas",
        "case_group": "ui_shelf_aware_turn_cost_node_generation_batch",
        "node_generation_mode": "turn_cost_repaired_grid",
        "area_count": 1,
        "success_count": 1,
        "failed_count": 0,
        "areas": [
            {
                "project_name": "beiguoshangcheng_floor_3",
                "area_id": 5,
                "status": "success",
                "returncode": 0,
                "final_path_pixels": _write_path(tmp_path / path_name, [[1, 2], [3, 4]]),
                "coverage_ratio": coverage,
                "narrow_coverage_ratio": 0.99,
                "long_jump_count": long_jump_count,
                "turn_hotspot_count": 2,
                "infeasible_segment_count": 0,
                "lane_over_dense_count": 3,
                "lane_over_sparse_count": 1,
                "lane_spacing_issue_count": 4,
                "segment_crossing_count": 5,
            }
        ],
    }


def test_effect_snapshot_hashes_final_path_and_summarizes_metrics(tmp_path: Path) -> None:
    snapshot = build_snapshot(_summary(tmp_path, coverage=0.998, long_jump_count=0))

    assert snapshot["area_count"] == 1
    assert snapshot["metric_contract"]["schema_version"] == EFFECT_METRIC_CONTRACT_VERSION
    area = snapshot["areas"][0]
    assert area["case_key"] == "beiguoshangcheng_floor_3#area5"
    assert area["final_path_pixels_sha256"]
    assert snapshot["metric_summary"]["coverage_ratio"]["min"] == pytest.approx(0.998)


def test_effect_metric_contract_is_single_source_for_gate_groups() -> None:
    payload = effect_metric_contract_payload()

    assert tuple(metric["name"] for metric in payload["metrics"]) == effect_metric_names()
    assert tuple(payload["gated_metrics"]) == gated_effect_metric_names()
    assert tuple(payload["not_gated_metrics"]) == not_gated_effect_metric_names()
    assert set(payload["gated_metrics"]).isdisjoint(set(payload["not_gated_metrics"]))
    assert "coverage_ratio" in payload["gated_metrics"]
    assert "lane_spacing_issue_count" in payload["not_gated_metrics"]
    assert all(metric["description_zh"] for metric in payload["metrics"])


def test_effect_snapshot_reads_formal_baseline_area_path(tmp_path: Path) -> None:
    area_dir = tmp_path / "area"
    area_dir.mkdir()
    (area_dir / "path_pixels.json").write_text("[[1, 2], [3, 4]]", encoding="utf-8")
    summary = {
        "runner": "run_shelf_aware_all_areas",
        "planner_mode": "shelf_aware_turn_cost",
        "area_count": 1,
        "success_count": 1,
        "failed_count": 0,
        "areas": [
            {
                "project_name": "beiguoshangcheng_floor_3",
                "area_id": 5,
                "status": "success",
                "area_run_dir": str(area_dir),
                "coverage_ratio": 0.998,
                "long_jump_count": 0,
                "infeasible_segment_count": 1,
            }
        ],
    }

    snapshot = build_snapshot(summary)

    area = snapshot["areas"][0]
    assert area["final_path_pixels"] == str(area_dir / "path_pixels.json")
    assert area["final_path_pixels_sha256"]
    assert area["metrics"]["coverage_ratio"] == pytest.approx(0.998)
    assert area["metrics"]["infeasible_segment_count"] == 1


def test_effect_comparison_rejects_metric_regression(tmp_path: Path) -> None:
    baseline = build_snapshot(_summary(tmp_path, coverage=0.998, long_jump_count=0, path_name="baseline.json"))
    candidate = build_snapshot(_summary(tmp_path, coverage=0.990, long_jump_count=1, path_name="candidate.json"))

    comparison = compare_snapshots(
        baseline=baseline,
        candidate=candidate,
        config=EffectGateConfig(
            require_path_identity=False,
            coverage_epsilon=0.001,
            narrow_coverage_epsilon=0.0,
            allow_count_increase=0,
        ),
    )

    assert comparison["status"] == "fail"
    case = comparison["cases"][0]
    failed = {item["metric"] for item in case["metric_results"] if item["status"] == "fail"}
    assert {"coverage_ratio", "long_jump_count"} <= failed
    assert comparison["gate"]["gated_metrics"] == [
        "coverage_ratio",
        "long_jump_count",
        "infeasible_segment_count",
    ]
    assert "narrow_coverage_ratio" in comparison["gate"]["not_gated_metrics"]
    assert comparison["gate"]["metric_contract"] == effect_metric_contract_payload()


def test_effect_comparison_can_require_path_identity(tmp_path: Path) -> None:
    baseline_summary = _summary(tmp_path, coverage=0.998, long_jump_count=0, path_name="baseline.json")
    candidate_summary = _summary(tmp_path, coverage=0.998, long_jump_count=0, path_name="candidate.json")
    Path(candidate_summary["areas"][0]["final_path_pixels"]).write_text("[[1, 2], [5, 6]]", encoding="utf-8")

    comparison = compare_snapshots(
        baseline=build_snapshot(baseline_summary),
        candidate=build_snapshot(candidate_summary),
        config=EffectGateConfig(
            require_path_identity=True,
            coverage_epsilon=0.0,
            narrow_coverage_epsilon=0.0,
            allow_count_increase=0,
        ),
    )

    assert comparison["status"] == "fail"
    assert comparison["cases"][0]["path_identity_status"] == "fail"


def test_effect_comparison_reports_not_gated_metric_regression_without_failing(tmp_path: Path) -> None:
    baseline_summary = _summary(tmp_path, coverage=0.998, long_jump_count=0, path_name="baseline.json")
    candidate_summary = _summary(tmp_path, coverage=0.998, long_jump_count=0, path_name="candidate.json")
    baseline_summary["areas"][0]["lane_spacing_issue_count"] = 1
    candidate_summary["areas"][0]["lane_spacing_issue_count"] = 99

    comparison = compare_snapshots(
        baseline=build_snapshot(baseline_summary),
        candidate=build_snapshot(candidate_summary),
        config=EffectGateConfig(
            require_path_identity=False,
            coverage_epsilon=0.0,
            narrow_coverage_epsilon=0.0,
            allow_count_increase=0,
        ),
    )

    assert comparison["status"] == "pass"
    case = comparison["cases"][0]
    lane_result = next(item for item in case["metric_results"] if item["metric"] == "lane_spacing_issue_count")
    assert lane_result["status"] == "fail"
    assert "lane_spacing_issue_count" in comparison["gate"]["not_gated_metrics"]
    lane_summary = comparison["metric_status_summary"]["lane_spacing_issue_count"]
    assert lane_summary["gated"] is False
    assert lane_summary["status_counts"]["fail"] == 1
    assert lane_summary["baseline_available_count"] == 1
    assert lane_summary["candidate_available_count"] == 1


def test_effect_comparison_ignores_metrics_missing_on_both_sides(tmp_path: Path) -> None:
    area_dir = tmp_path / "area"
    area_dir.mkdir()
    (area_dir / "path_pixels.json").write_text("[[1, 2], [3, 4]]", encoding="utf-8")
    summary = {
        "runner": "run_shelf_aware_all_areas",
        "planner_mode": "shelf_aware_turn_cost",
        "area_count": 1,
        "success_count": 1,
        "failed_count": 0,
        "areas": [
            {
                "project_name": "beiguoshangcheng_floor_3",
                "area_id": 5,
                "status": "success",
                "area_run_dir": str(area_dir),
                "coverage_ratio": 0.998,
                "long_jump_count": 0,
                "infeasible_segment_count": 0,
            }
        ],
    }

    comparison = compare_snapshots(
        baseline=build_snapshot(summary),
        candidate=build_snapshot(summary),
        config=EffectGateConfig(
            require_path_identity=True,
            coverage_epsilon=0.0,
            narrow_coverage_epsilon=0.0,
            allow_count_increase=0,
        ),
    )

    assert comparison["status"] == "pass"
    statuses = {item["metric"]: item["status"] for item in comparison["cases"][0]["metric_results"]}
    assert statuses["narrow_coverage_ratio"] == "not_available"
    assert statuses["turn_hotspot_count"] == "not_available"
    narrow_summary = comparison["metric_status_summary"]["narrow_coverage_ratio"]
    assert narrow_summary["status_counts"]["not_available"] == 1
    assert narrow_summary["baseline_available_count"] == 0
    assert narrow_summary["candidate_available_count"] == 0


def test_effect_comparison_records_not_gated_metric_missing_on_one_side_without_warning(tmp_path: Path) -> None:
    baseline_summary = _summary(tmp_path, coverage=0.998, long_jump_count=0, path_name="baseline.json")
    candidate_summary = _summary(tmp_path, coverage=0.998, long_jump_count=0, path_name="candidate.json")
    del candidate_summary["areas"][0]["lane_spacing_issue_count"]

    comparison = compare_snapshots(
        baseline=build_snapshot(baseline_summary),
        candidate=build_snapshot(candidate_summary),
        config=EffectGateConfig(
            require_path_identity=False,
            coverage_epsilon=0.0,
            narrow_coverage_epsilon=0.0,
            allow_count_increase=0,
        ),
    )

    assert comparison["status"] == "pass"
    statuses = {item["metric"]: item["status"] for item in comparison["cases"][0]["metric_results"]}
    assert statuses["lane_spacing_issue_count"] == "unknown"
    lane_summary = comparison["metric_status_summary"]["lane_spacing_issue_count"]
    assert lane_summary["gated"] is False
    assert lane_summary["status_counts"]["unknown"] == 1
    assert lane_summary["baseline_available_count"] == 1
    assert lane_summary["candidate_available_count"] == 0


def test_effect_comparison_warns_when_gated_metric_is_missing_on_one_side(tmp_path: Path) -> None:
    baseline_summary = _summary(tmp_path, coverage=0.998, long_jump_count=0, path_name="baseline.json")
    candidate_summary = _summary(tmp_path, coverage=0.998, long_jump_count=0, path_name="candidate.json")
    del candidate_summary["areas"][0]["coverage_ratio"]

    comparison = compare_snapshots(
        baseline=build_snapshot(baseline_summary),
        candidate=build_snapshot(candidate_summary),
        config=EffectGateConfig(
            require_path_identity=False,
            coverage_epsilon=0.0,
            narrow_coverage_epsilon=0.0,
            allow_count_increase=0,
        ),
    )

    assert comparison["status"] == "warn"
    statuses = {item["metric"]: item["status"] for item in comparison["cases"][0]["metric_results"]}
    assert statuses["coverage_ratio"] == "unknown"
