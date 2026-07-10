from tools.coverage_semantic_baseline_check import compare_baselines


def test_compare_baselines_ignores_timing_but_rejects_stable_semantic_drift():
    expected = [
        {
            "area_id": 1,
            "area_name": "A",
            "success": True,
            "error": "",
            "point_count": 3,
            "path_length_px": 12.0,
            "path_hash": "path-a",
            "edge_label_hash": "edge-a",
            "junction_label_hash": "junction-a",
            "graph_node_count": 2,
            "graph_edge_count": 1,
            "timing": {"plan_elapsed_s": 10.0},
        }
    ]
    actual_same_semantics = [
        {
            **expected[0],
            "timing": {"plan_elapsed_s": 0.1},
        }
    ]
    actual_drift = [
        {
            **expected[0],
            "path_hash": "path-b",
            "timing": {"plan_elapsed_s": 0.1},
        }
    ]

    assert compare_baselines(expected, actual_same_semantics) == []
    failures = compare_baselines(expected, actual_drift)
    assert len(failures) == 1
    assert "key=path_hash" in failures[0]
