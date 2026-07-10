"""人工标注窗口的只读归因规则。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence


@dataclass(frozen=True)
class AttributionConfig:
    high_turn_deg: float = 70.0
    moderate_turn_deg: float = 30.0
    dense_gap_factor: float = 0.65
    sparse_gap_factor: float = 1.35


def attribute_annotated_windows(
    alignment: dict[str, Any],
    *,
    config: AttributionConfig | None = None,
) -> dict[str, Any]:
    """把对齐后的窗口数据归因为只读问题类型，不改变路径和质量规则。"""

    cfg = config or AttributionConfig()
    coverage_width_px = float(alignment.get("coverage_width_px", 0.0) or 0.0)
    windows = [
        _attribute_one_window(window, coverage_width_px=coverage_width_px, config=cfg)
        for window in alignment.get("windows", [])
    ]
    return {
        "scope": "manual_annotation_window_attribution",
        "note": "只读归因：primary 表示当前窗口内证据最强的可疑原因，不等同确定根因；不做路径修改，不生成新的全局质量判定。",
        "attribution_semantics": {
            "primary": "当前 bbox 内证据最强的可疑原因",
            "confidence": "证据强弱，不代表因果已被证明",
            "scope": "只对当前人工 bbox 命中的路径数据成立",
        },
        "coverage_width_px": coverage_width_px,
        "window_count": len(windows),
        "windows": windows,
    }


def _attribute_one_window(
    window: dict[str, Any],
    *,
    coverage_width_px: float,
    config: AttributionConfig,
) -> dict[str, Any]:
    signals = _collect_signals(window, coverage_width_px=coverage_width_px, config=config)
    attribution = _classify_window(window, signals)
    return {
        "window_id": window.get("window_id"),
        "title": window.get("title"),
        "category": window.get("category"),
        "bbox_xyxy": window.get("bbox_xyxy", []),
        "user_observation": window.get("user_observation", ""),
        "path_point_index_ranges": window.get("path_point_index_ranges", []),
        "path_segment_index_ranges": window.get("path_segment_index_ranges", []),
        "signals": signals,
        "attribution": attribution,
        "suspicious_strokes": _select_suspicious_strokes(window.get("matched_strokes", [])),
        "suspicious_candidates": _select_suspicious_candidates(window.get("matched_optimization_candidates", [])),
        "next_step_boundary": _next_step_boundary(window, signals, attribution),
    }


def _collect_signals(
    window: dict[str, Any],
    *,
    coverage_width_px: float,
    config: AttributionConfig,
) -> dict[str, Any]:
    turn_metrics = window.get("local_turn_metrics", {})
    segment_metrics = window.get("local_segment_metrics", {})
    lane = window.get("lane_inspection", {})
    lane_stats = lane.get("lane_gap_stats", {})
    strokes = list(window.get("matched_strokes", []))
    candidates = list(window.get("matched_optimization_candidates", []))
    max_turn = float(turn_metrics.get("max_turn_deg", 0.0) or 0.0)
    hotspot_count = len(turn_metrics.get("hotspot_point_indices", []) or [])
    min_gap = float(lane_stats.get("min_gap_px", 0.0) or 0.0)
    max_gap = float(lane_stats.get("max_gap_px", 0.0) or 0.0)
    dense_threshold = coverage_width_px * float(config.dense_gap_factor)
    sparse_threshold = coverage_width_px * float(config.sparse_gap_factor)
    high_risk_crossings = _sum_stroke_metric(strokes, "high_risk_crossing_count")
    all_crossings = _sum_stroke_metric(strokes, "crossing_count")
    fragment_count = sum(1 for stroke in strokes if str(stroke.get("segment_type")) == "fragment")
    connector_count = sum(1 for stroke in strokes if str(stroke.get("segment_type")) == "connector")
    unsafe_bad_count = sum(1 for stroke in strokes if str(stroke.get("action_label")) == "unsafe_bad")
    optimize_candidate_count = sum(1 for stroke in strokes if str(stroke.get("action_label")) == "optimize_candidate")
    candidate_kinds = _count_by_key(candidates, "candidate_kind")
    disjoint_path_visit_count = len(window.get("path_point_index_ranges", []) or [])
    return {
        "high_turn": bool(max_turn >= float(config.high_turn_deg)),
        "moderate_turn_hotspots": int(hotspot_count),
        "max_turn_deg": max_turn,
        "long_jump_count": int(segment_metrics.get("long_jump_count", 0) or 0),
        "max_segment_length_px": float(segment_metrics.get("max_segment_length_px", 0.0) or 0.0),
        "infeasible_segment_count": int(segment_metrics.get("infeasible_segment_count", 0) or 0),
        "lane_count": int(lane.get("lane_count", 0) or 0),
        "lane_gap_count": int(lane_stats.get("gap_count", 0) or 0),
        "lane_gap_min_px": min_gap,
        "lane_gap_max_px": max_gap,
        "lane_gap_target_px": coverage_width_px,
        "dense_lane_gap": bool(min_gap > 0.0 and min_gap < dense_threshold),
        "sparse_lane_gap": bool(max_gap > sparse_threshold),
        "high_risk_crossing_count": int(high_risk_crossings),
        "crossing_count_from_strokes": int(all_crossings),
        "fragment_stroke_count": int(fragment_count),
        "connector_stroke_count": int(connector_count),
        "unsafe_bad_stroke_count": int(unsafe_bad_count),
        "optimize_candidate_stroke_count": int(optimize_candidate_count),
        "candidate_kind_counts": candidate_kinds,
        "disjoint_path_visit_count": int(disjoint_path_visit_count),
    }


def _classify_window(window: dict[str, Any], signals: dict[str, Any]) -> dict[str, Any]:
    category = str(window.get("category", ""))
    reasons: list[str] = []
    labels: list[str] = []
    confidence = "medium"
    if signals["high_turn"] or signals["moderate_turn_hotspots"] >= 3:
        labels.append("局部急转或小折返")
        reasons.append("窗口内存在高转角或连续转角热点")
    if signals["infeasible_segment_count"] > 0 or signals["long_jump_count"] > 0:
        labels.append("连接段可行性风险")
        reasons.append("窗口内存在不可行段或长段")
    if signals["dense_lane_gap"] or signals["sparse_lane_gap"]:
        labels.append("lane 横向间距异常")
        reasons.append("窗口内 lane gap 偏离 coverage width")
    if signals["high_risk_crossing_count"] > 0 or signals["crossing_count_from_strokes"] >= 5:
        labels.append("交叉/重访组织风险")
        reasons.append("命中 stroke 中存在交叉或高风险交叉")
    if signals["fragment_stroke_count"] > 0 or signals["connector_stroke_count"] > 0:
        labels.append("短 fragment / connector 混入")
        reasons.append("窗口命中 fragment 或 connector stroke")
    if signals["disjoint_path_visit_count"] >= 3:
        labels.append("多次经过同一局部窗口")
        reasons.append("同一 bbox 命中多个不连续路径索引范围")

    if not labels:
        labels.append("人工窗口未命中明确诊断信号")
        reasons.append("当前 bbox 内真实路径信号不足，需要先复核 bbox 是否准确")
        confidence = "low"
    elif category == "lane_spacing_imbalance" and (signals["dense_lane_gap"] or signals["sparse_lane_gap"]):
        confidence = "high"
    elif category in {"micro_kink", "local_messy_lines"} and (signals["high_turn"] or signals["high_risk_crossing_count"] > 0):
        confidence = "high"

    primary = _primary_label(category, labels)
    return {
        "primary": primary,
        "labels": labels,
        "evidence_reasons": reasons,
        "confidence": confidence,
        "scope_warning": "该归因只对当前 bbox 内命中的真实路径数据成立，不能外推到整条走廊或整片路口。",
    }


def _primary_label(category: str, labels: Sequence[str]) -> str:
    if category == "lane_spacing_imbalance":
        for label in labels:
            if "lane" in label:
                return label
    if category == "micro_kink":
        for label in labels:
            if "急转" in label or "折返" in label:
                return label
    if category == "local_messy_lines":
        for label in labels:
            if "交叉" in label or "fragment" in label or "connector" in label:
                return label
    return str(labels[0])


def _select_suspicious_strokes(strokes: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    scored = []
    for stroke in strokes:
        metrics = stroke.get("metrics", {})
        score = 0
        if str(stroke.get("action_label")) == "unsafe_bad":
            score += 5
        if str(stroke.get("segment_type")) in {"fragment", "connector"}:
            score += 3
        score += min(5, int(metrics.get("high_risk_crossing_count", 0) or 0))
        score += min(4, int(metrics.get("infeasible_segment_count", 0) or 0))
        score += 1 if float(metrics.get("total_turn_deg", 0.0) or 0.0) >= 70.0 else 0
        if score <= 0:
            continue
        scored.append((score, stroke))
    selected = []
    for _, stroke in sorted(scored, key=lambda item: (-item[0], int(item[1].get("stroke_id", 0))))[:10]:
        selected.append(
            {
                "stroke_id": int(stroke.get("stroke_id", -1)),
                "segment_type": stroke.get("segment_type"),
                "action_label": stroke.get("action_label"),
                "classification": stroke.get("classification"),
                "point_index_range": stroke.get("point_index_range"),
                "segment_index_range": stroke.get("segment_index_range"),
                "reasons": stroke.get("reasons", []),
                "metrics": stroke.get("metrics", {}),
            }
        )
    return selected


def _select_suspicious_candidates(candidates: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    priority = {
        "infeasible_reconnect": 5,
        "crossing_reconnect": 4,
        "revisit_bridge_reconnect": 3,
        "lane_uniformity_local_fix": 2,
        "turn_cost_local_fix": 2,
    }
    scored = []
    for candidate in candidates:
        score = priority.get(str(candidate.get("candidate_kind")), 1)
        if str(candidate.get("classification")) == "bad":
            score += 2
        scored.append((score, candidate))
    selected = []
    for _, candidate in sorted(scored, key=lambda item: (-item[0], int(item[1].get("candidate_id", 0))))[:10]:
        selected.append(
            {
                "candidate_id": int(candidate.get("candidate_id", -1)),
                "stroke_id": int(candidate.get("stroke_id", -1)),
                "candidate_kind": candidate.get("candidate_kind"),
                "classification": candidate.get("classification"),
                "point_index_range": candidate.get("point_index_range"),
                "segment_index_range": candidate.get("segment_index_range"),
                "reasons": candidate.get("reasons", []),
            }
        )
    return selected


def _next_step_boundary(window: dict[str, Any], signals: dict[str, Any], attribution: dict[str, Any]) -> dict[str, Any]:
    allowed: list[str] = []
    forbidden: list[str] = [
        "不能把 bbox 外路径纳入该窗口归因",
        "不能在归因阶段移动点、删点或重连",
        "不能把人工窗口直接升级为全局质量规则",
    ]
    primary = str(attribution.get("primary", ""))
    if "lane" in primary:
        allowed.extend(["仅做窗口内 lane 位置和 gap 序列复核", "后续若优化，只允许局部 lane spacing 候选，不允许普通点到点 shortcut 替代 lane"])
    if "急转" in primary or "折返" in primary:
        allowed.extend(["仅检查热点 pivot 附近少量点", "优先判断是否为短 fragment 或 connector 插入导致"])
    if "交叉" in primary or "connector" in primary or "fragment" in primary:
        allowed.extend(["仅检查命中的 suspicious stroke/candidate", "后续优化必须先证明不降低覆盖率且不增加长跳跃"])
    if signals.get("disjoint_path_visit_count", 0) >= 3:
        forbidden.append("不能把多个不连续 path visit 合成单个连续重连窗口")
    if not allowed:
        allowed.append("先复核 bbox 是否准确，再决定是否需要新增诊断")
    return {"allowed": allowed, "forbidden": forbidden}


def _sum_stroke_metric(strokes: Sequence[dict[str, Any]], key: str) -> int:
    return int(sum(int(stroke.get("metrics", {}).get(key, 0) or 0) for stroke in strokes))


def _count_by_key(items: Sequence[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        value = str(item.get(key, "unknown"))
        counts[value] = counts.get(value, 0) + 1
    return counts
