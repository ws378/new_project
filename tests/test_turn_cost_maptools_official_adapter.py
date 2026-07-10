import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from algorithms.turn_cost_coverage_research.src.adapters.official_maptools_adapter import (
    mask_to_component_polygons,
    mask_to_single_polygon,
)


def test_mask_to_single_polygon_preserves_hole() -> None:
    mask = np.zeros((20, 20), dtype=np.uint8)
    mask[2:18, 3:17] = 255
    mask[7:12, 8:13] = 0

    polygon = mask_to_single_polygon(mask, resolution_m_per_px=0.1)

    assert polygon.area < (16 * 14) * 0.01
    assert polygon.area > 1.0
    assert len(polygon.interiors) == 1


def test_mask_to_single_polygon_rejects_disconnected_components() -> None:
    mask = np.zeros((20, 20), dtype=np.uint8)
    mask[2:8, 2:8] = 255
    mask[12:18, 12:18] = 255

    with pytest.raises(ValueError, match="disconnected polygon components"):
        mask_to_single_polygon(mask, resolution_m_per_px=0.1)


def test_mask_to_component_polygons_keeps_all_disconnected_components() -> None:
    mask = np.zeros((20, 20), dtype=np.uint8)
    mask[2:8, 2:8] = 255
    mask[12:18, 12:18] = 255
    metadata: dict[str, object] = {}

    polygons = mask_to_component_polygons(mask, resolution_m_per_px=0.1, repair_metadata=metadata)

    assert len(polygons) == 2
    assert metadata["component_count"] == 2
    assert metadata["split_policy"] == "split_all_disconnected_components_no_drop_no_virtual_bridge"


def test_maptools_official_runner_writes_official_adapter_summary(tmp_path) -> None:
    pytest.importorskip("matplotlib", exc_type=ImportError)
    script = "algorithms/turn_cost_coverage_research/scripts/experiments/run_maptools_official_cases.py"
    result = subprocess.run(
        [
            sys.executable,
            script,
            "--project-dir",
            "examples/maptools_projects/fourfloor_20250923_8",
            "--area-id",
            "2",
            "--stop-after",
            "graph",
            "--fractional-solver",
            "highs",
            "--output-root",
            str(tmp_path),
        ],
        check=True,
        cwd=".",
        text=True,
        capture_output=True,
    )
    run_dir = result.stdout.strip().splitlines()[-1]
    root_summary = json.loads((Path(run_dir) / "summary.json").read_text(encoding="utf-8"))
    case = root_summary["cases"][0]

    assert root_summary["runner"] == "run_maptools_official_cases"
    assert root_summary["case_group"] == "maptools_official_algorithm_steps"
    assert root_summary["parameter_profile"] == "maptools_existing_preprocessing"
    assert root_summary["guidance"]["enabled"] is False
    assert root_summary["guidance"]["mode"] == "none"
    assert case["status"] == "success"
    assert case["case_group"] == "maptools_official_algorithm_steps"
    assert case["input"]["algorithm_source"] == "pcpptc official flow with MapTools existing geometry_preparation adapter"
    assert case["input"]["instance_source"] == "maptools_existing_geometry_preparation"
    assert case["input"]["adapter_metadata"]["adapter"] == "maptools_existing_preprocessing_to_official_polygon_instance"
    assert case["input"]["adapter_metadata"]["coverage_mode"] == "partial_penalty_only_no_hard_coverage"
    assert case["metrics"]["graph_node_count"] > 0
    assert case["metrics"]["guidance"]["enabled"] is False
    assert any(item["name"] == "00_maptools_adapter_metadata.json" for item in case["artifacts"])
