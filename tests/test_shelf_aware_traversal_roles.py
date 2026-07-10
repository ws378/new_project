from algorithms.coverage_planning.planners.shelf_aware_guarded.traversal_core.traversal_roles import (
    EDGE_ROLE_COVERAGE_LANE,
    EDGE_ROLE_FALLBACK_TRANSFER,
    EDGE_ROLE_REVISIT_BRIDGE,
    EDGE_ROLE_UNKNOWN,
    MOVE_SOURCE_GLOBAL_FALLBACK,
    MOVE_SOURCE_NORMAL_NEIGHBOR,
    MOVE_SOURCE_REVISIT_BRIDGE,
    RAW_EDGE_ROLE_VALUES,
    RAW_MOVE_SOURCE_VALUES,
    TRAVERSAL_PHASE_VALUES,
    edge_role_for_move_source,
)


def test_edge_role_for_move_source_maps_stable_provenance_values():
    assert edge_role_for_move_source(MOVE_SOURCE_NORMAL_NEIGHBOR) == EDGE_ROLE_COVERAGE_LANE
    assert edge_role_for_move_source(MOVE_SOURCE_REVISIT_BRIDGE) == EDGE_ROLE_REVISIT_BRIDGE
    assert edge_role_for_move_source(MOVE_SOURCE_GLOBAL_FALLBACK) == EDGE_ROLE_FALLBACK_TRANSFER
    assert edge_role_for_move_source("unexpected") == EDGE_ROLE_UNKNOWN


def test_move_source_and_edge_role_schema_values_remain_ordered():
    assert RAW_MOVE_SOURCE_VALUES == [
        "start",
        "normal_neighbor",
        "revisit_bridge",
        "global_fallback",
    ]
    assert RAW_EDGE_ROLE_VALUES == [
        "start",
        "coverage_lane",
        "revisit_bridge",
        "fallback_transfer",
    ]
    assert TRAVERSAL_PHASE_VALUES == [
        "normal_neighbor",
        "revisit_bridge",
        "global_fallback",
    ]
    assert TRAVERSAL_PHASE_VALUES == RAW_MOVE_SOURCE_VALUES[1:]
    assert len(set(TRAVERSAL_PHASE_VALUES)) == len(TRAVERSAL_PHASE_VALUES)
