"""Sweep graph 验证 helper。"""

from __future__ import annotations

from ...contracts import SweepCadenceInfo, SweepGraphInfo, SweepGraphValidation, SweepGroupInfo, SweepTransitionCandidateInfo


def validate_sweep_graph(
    sweep_group_info: SweepGroupInfo,
    sweep_transition_candidate_info: SweepTransitionCandidateInfo,
    sweep_graph_info: SweepGraphInfo,
    sweep_cadence_info: SweepCadenceInfo,
) -> SweepGraphValidation:
    """校验 sweep graph -> cadence 主线闭环。"""

    candidate_items = tuple(sweep_transition_candidate_info.get('items', ()))
    group_ids = {int(item['group_id']) for item in sweep_group_info.get('groups', ())}
    sweep_ids = {int(item['sweep_id']) for item in sweep_graph_info.get('sweeps', ())}
    route_sweep_ids = {int(sweep_id) for route in sweep_cadence_info.get('routes', ()) for sweep_id in route.get('sweep_sequence', ())}
    errors: list[str] = []
    if not group_ids:
        errors.append('sweep groups are empty')
    if not candidate_items:
        errors.append('sweep transition candidates are empty')
    if sweep_ids != route_sweep_ids:
        # cadence 必须覆盖 sweep graph 里的全部 sweep；少一个或多一个都说明主线闭环断了。
        errors.append('sweep cadence does not cover all sweeps exactly once')
    for route in sweep_cadence_info.get('routes', ()):
        prev_to_sweep_id = None
        prev_exit_end_type = None
        for segment in route.get('segments', ()):
            if prev_to_sweep_id is not None:
                if int(segment['from_sweep_id']) != int(prev_to_sweep_id):
                    errors.append('cadence segment continuity is broken')
                    break
                if str(segment['entry_end_type']) != str(prev_exit_end_type):
                    # 上一段的出口端和下一段的入口端必须无缝接上，否则 route 只是 id 串连而非真实连贯路径。
                    errors.append('cadence end-type continuity is broken')
                    break
            prev_to_sweep_id = int(segment['to_sweep_id'])
            prev_exit_end_type = str(segment['exit_end_type'])
    return {
        'valid': not errors,
        'error_count': int(len(errors)),
        'errors': errors,
        'group_count': int(len(group_ids)),
        'sweep_count': int(len(sweep_ids)),
        'candidate_count': int(len(candidate_items)),
        'strong_candidate_count': int(len(candidate_items)),
        'weak_candidate_count': 0,
        'fallback_candidate_count': 0,
    }


__all__ = ('validate_sweep_graph',)
