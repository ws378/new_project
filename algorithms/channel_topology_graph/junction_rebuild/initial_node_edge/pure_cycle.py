"""pure cycle 初始 node/edge 几何恢复 helper。"""

from __future__ import annotations

import multiprocessing as mp
import os
from concurrent.futures import ProcessPoolExecutor
from typing import Any

import cv2
import numpy as np

from ...geometry_preparation.pruning.neighbor_topology import (
    GROUP_COUNT_LUT,
    POPCOUNT_LUT,
    RING_OFFSETS,
    build_neighbor_mask_map,
    ring_groups_for_mask,
)
from ...geometry_preparation.pruning.trace import update_neighbor_masks_local


_PURE_CYCLE_WORKER_SKELETON01: np.ndarray | None = None


def _init_pure_cycle_worker(skeleton01: np.ndarray) -> None:
    global _PURE_CYCLE_WORKER_SKELETON01
    _PURE_CYCLE_WORKER_SKELETON01 = skeleton01


def _evaluate_cut_candidate_worker(cut_center_rc: tuple[int, int]):
    if _PURE_CYCLE_WORKER_SKELETON01 is None:
        raise RuntimeError("pure cycle worker skeleton is not initialized")
    return evaluate_cut_candidate(_PURE_CYCLE_WORKER_SKELETON01, cut_center_rc)


def build_largest_component_mask(binary01: np.ndarray) -> np.ndarray:
    """只保留单个最大 8 邻域连通分量。"""

    src = np.where(binary01 > 0, 255, 0).astype(np.uint8)
    num_labels, labels = cv2.connectedComponents(src, connectivity=8)
    if int(num_labels) <= 1:
        # 没有前景连通分量时，最大分量结果就应为空，而不是回退到原图。
        return np.zeros_like(binary01, dtype=np.uint8)
    best_label = max(range(1, int(num_labels)), key=lambda item: int(np.count_nonzero(labels == item)))
    return np.where(labels == best_label, 1, 0).astype(np.uint8)


def build_cycle_cut_inner_zone(
    skeleton01: np.ndarray,
    cut_center_rc: tuple[int, int],
) -> set[tuple[int, int]]:
    """以切口中心为核心，建立一个 3x3 的 inner_path 局部区域。"""

    pixel_set = {tuple(map(int, point_rc)) for point_rc in np.argwhere(skeleton01 > 0)}
    out: set[tuple[int, int]] = set()
    for dr in (-1, 0, 1):
        for dc in (-1, 0, 1):
            point_rc = (int(cut_center_rc[0] + dr), int(cut_center_rc[1] + dc))
            if point_rc in pixel_set:
                out.add(point_rc)
    return out


def endpoint_count(binary01: np.ndarray, neighbor_masks: np.ndarray | None = None) -> int:
    """统计当前骨架中的端点数量。"""

    masks = neighbor_masks if neighbor_masks is not None else build_neighbor_mask_map(binary01)
    return int(np.count_nonzero((binary01 > 0) & (GROUP_COUNT_LUT[masks] == 1)))


def trace_open_chain_path(
    binary01: np.ndarray,
    neighbor_masks: np.ndarray | None = None,
) -> list[tuple[int, int]]:
    """沿 8 邻域环顺序追踪一条开口单链。"""

    pixels = [tuple(map(int, point_rc)) for point_rc in np.argwhere(binary01 > 0)]
    if not pixels:
        return []

    pixel_set = set(pixels)
    masks = neighbor_masks if neighbor_masks is not None else build_neighbor_mask_map(binary01)
    grouped_neighbors_by_pixel: dict[tuple[int, int], tuple[tuple[tuple[int, int], ...], ...]] = {}
    endpoints: list[tuple[int, int]] = []
    for point_rc in pixels:
        mask = int(masks[point_rc])
        occupied = [index for index in range(len(RING_OFFSETS)) if mask & (1 << index)]
        groups = ring_groups_for_mask(occupied)
        pixel_groups: list[tuple[int, int]] = []
        for group in groups:
            for index in group:
                dr, dc = RING_OFFSETS[index]
                neighbor_rc = (int(point_rc[0] + dr), int(point_rc[1] + dc))
                if neighbor_rc in pixel_set:
                    pixel_groups.append(neighbor_rc)
        grouped_pixels: list[tuple[tuple[int, int], ...]] = []
        offset = 0
        for group in groups:
            size = len(group)
            grouped_pixels.append(tuple(pixel_groups[offset : offset + size]))
            offset += size
        if len(grouped_pixels) == 1:
            endpoints.append(point_rc)
        elif len(grouped_pixels) != 2:
            # 纯开口单链只允许 1 组或 2 组局部邻接；更多组说明已经不是单链，可直接判失败。
            return []
        grouped_neighbors_by_pixel[point_rc] = tuple(grouped_pixels)

    if len(endpoints) != 2:
        # 开口单链必须恰好两个端点；端点数不对说明 residual 还没被收敛成唯一链。
        return []

    start_rc, goal_rc = sorted(endpoints)

    def pick_next(
        current_rc: tuple[int, int],
        candidates_rc: tuple[tuple[int, int], ...],
        prev_rc: tuple[int, int] | None,
    ) -> tuple[int, int] | None:
        if not candidates_rc:
            return None
        if prev_rc is None:
            return min(candidates_rc)
        in_vec = (int(current_rc[0] - prev_rc[0]), int(current_rc[1] - prev_rc[1]))
        best_point: tuple[int, int] | None = None
        best_key: tuple[int, int, int, int] | None = None
        for candidate_rc in candidates_rc:
            out_vec = (int(candidate_rc[0] - current_rc[0]), int(candidate_rc[1] - current_rc[1]))
            dot = int(in_vec[0] * out_vec[0] + in_vec[1] * out_vec[1])
            cross = abs(int(in_vec[0] * out_vec[1] - in_vec[1] * out_vec[0]))
            key = (-dot, cross, int(candidate_rc[0]), int(candidate_rc[1]))
            if best_key is None or key < best_key:
                best_key = key
                best_point = candidate_rc
        return best_point

    path_rc: list[tuple[int, int]] = []
    used_points: set[tuple[int, int]] = set()
    prev_rc: tuple[int, int] | None = None
    current_rc: tuple[int, int] | None = start_rc
    guard = len(pixels) * 5
    while guard > 0 and current_rc is not None:
        guard -= 1
        path_rc.append(current_rc)
        used_points.add(current_rc)
        if current_rc == goal_rc:
            break
        neighbor_groups = grouped_neighbors_by_pixel[current_rc]
        if prev_rc is None:
            candidates_rc = neighbor_groups[0]
        else:
            incoming_group_index: int | None = None
            for group_index, group_pixels in enumerate(neighbor_groups):
                if prev_rc in group_pixels:
                    incoming_group_index = group_index
                    break
            if incoming_group_index is None:
                return []
            outgoing_group = neighbor_groups[1 - incoming_group_index]
            filtered = tuple(point_rc for point_rc in outgoing_group if point_rc not in used_points or point_rc == goal_rc)
            candidates_rc = filtered or outgoing_group
        next_rc = pick_next(current_rc, candidates_rc, prev_rc)
        prev_rc, current_rc = current_rc, next_rc

    if not path_rc or path_rc[-1] != goal_rc:
        return []
    return path_rc


def rank_cut_candidates(skeleton01: np.ndarray, max_candidates: int = 24) -> list[tuple[int, int]]:
    """从 pure cycle 上挑出一小组空间分散、局部更稳定的切口候选。"""

    pixels = [tuple(map(int, point_rc)) for point_rc in np.argwhere(skeleton01 > 0)]
    if not pixels:
        return []

    neighbor_masks = build_neighbor_mask_map(skeleton01)
    density_map = cv2.filter2D(skeleton01.astype(np.uint8), -1, np.ones((5, 5), dtype=np.uint8), borderType=cv2.BORDER_CONSTANT)
    stable_pixels: list[tuple[int, int]] = []
    for point_rc in pixels:
        mask = int(neighbor_masks[point_rc])
        popcount = int(POPCOUNT_LUT[mask])
        group_count = int(GROUP_COUNT_LUT[mask])
        if popcount <= 2 and group_count == 2:
            stable_pixels.append(point_rc)
    pool = stable_pixels or pixels
    pool = sorted(pool, key=lambda point_rc: (int(density_map[point_rc]), int(point_rc[0]), int(point_rc[1])))

    selected: list[tuple[int, int]] = [pool[0]]
    while len(selected) < min(max_candidates, len(pool)):
        best_point: tuple[int, int] | None = None
        best_key: tuple[int, int, int, int] | None = None
        for point_rc in pool:
            if point_rc in selected:
                continue
            min_dist2 = min(
                int((point_rc[0] - chosen[0]) ** 2 + (point_rc[1] - chosen[1]) ** 2)
                for chosen in selected
            )
            key = (min_dist2, -int(density_map[point_rc]), -int(point_rc[0]), -int(point_rc[1]))
            if best_key is None or key > best_key:
                best_key = key
                best_point = point_rc
        if best_point is None:
            break
        selected.append(best_point)

    return selected


def chainify_cycle_residual(binary01: np.ndarray) -> np.ndarray:
    """把切口后的残余主分量收敛成唯一前进的开口单链。"""

    current01 = build_largest_component_mask(binary01)
    if int(np.count_nonzero(current01)) == 0:
        return current01

    neighbor_masks = build_neighbor_mask_map(current01)
    loop_count = 0
    while loop_count < 64:
        loop_count += 1
        candidate_points: list[tuple[int, int, int, int]] = []
        for point_rc in np.argwhere(current01 > 0):
            point_tuple = (int(point_rc[0]), int(point_rc[1]))
            mask = int(neighbor_masks[point_tuple])
            popcount = int(POPCOUNT_LUT[mask])
            group_count = int(GROUP_COUNT_LUT[mask])
            if group_count == 1:
                continue
            if popcount <= 2 and group_count <= 2:
                continue
            candidate_points.append((popcount, group_count, int(point_tuple[0]), int(point_tuple[1])))
        if not candidate_points:
            break

        candidate_points.sort(reverse=True)
        current_bad_count = int(np.count_nonzero((current01 > 0) & (POPCOUNT_LUT[neighbor_masks] > 2)))
        current_path = trace_open_chain_path(current01, neighbor_masks)
        current_path_len = len(current_path)
        removed = False
        for _popcount, _group_count, row, col in candidate_points:
            point_rc = (int(row), int(col))
            trial01 = current01.copy()
            trial01[point_rc] = 0
            trial01 = build_largest_component_mask(trial01)
            if int(np.count_nonzero(trial01)) == 0:
                continue

            changed_mask01 = np.where(current01 != trial01, 1, 0).astype(np.uint8)
            trial_neighbor_masks = neighbor_masks.copy()
            update_neighbor_masks_local(trial01, trial_neighbor_masks, changed_mask01)
            if endpoint_count(trial01, trial_neighbor_masks) != 2:
                # 删除这个点后若端点数不再是 2，就说明主分量被破坏成非单链结构。
                continue

            trial_bad_count = int(np.count_nonzero((trial01 > 0) & (POPCOUNT_LUT[trial_neighbor_masks] > 2)))
            if trial_bad_count > current_bad_count:
                continue

            trial_path = trace_open_chain_path(trial01, trial_neighbor_masks)
            if not trial_path or len(trial_path) < current_path_len:
                continue

            current01 = trial01
            neighbor_masks = trial_neighbor_masks
            removed = True
            break
        if not removed:
            break
    return current01


def evaluate_cut_candidate(
    skeleton01: np.ndarray,
    cut_center_rc: tuple[int, int],
) -> tuple[tuple[tuple[int, int], ...], list[tuple[int, int]], tuple[int, int, int]] | None:
    """评估单个切口候选是否能恢复稳定 outer_path。"""

    inner_zone = tuple(sorted(build_cycle_cut_inner_zone(skeleton01, cut_center_rc)))
    if len(inner_zone) < 2:
        return None

    residual01 = skeleton01.copy()
    for point_rc in inner_zone:
        residual01[point_rc] = 0
    residual01 = chainify_cycle_residual(residual01)
    residual_pixel_count = int(np.count_nonzero(residual01))
    if residual_pixel_count == 0:
        return None

    neighbor_masks = build_neighbor_mask_map(residual01)
    if endpoint_count(residual01, neighbor_masks) != 2:
        return None

    outer_path_rc = trace_open_chain_path(residual01, neighbor_masks)
    if not outer_path_rc:
        return None

    score = (len(set(outer_path_rc)), residual_pixel_count, -len(inner_zone))
    return inner_zone, outer_path_rc, score


def evaluate_cut_candidates(
    skeleton01: np.ndarray,
    candidates: list[tuple[int, int]],
    *,
    parallel_workers: int = 0,
) -> list[tuple[tuple[tuple[int, int], ...], list[tuple[int, int]], tuple[int, int, int]] | None]:
    """按候选顺序评估 pure-cycle cut candidates，必要时使用进程并行。"""

    if parallel_workers <= 1 or len(candidates) < 8 or os.name != "posix":
        return [evaluate_cut_candidate(skeleton01, cut_center_rc) for cut_center_rc in candidates]
    worker_count = min(len(candidates), max(1, min(int(parallel_workers), (os.cpu_count() or 1))))
    if worker_count <= 1:
        return [evaluate_cut_candidate(skeleton01, cut_center_rc) for cut_center_rc in candidates]
    try:
        context = mp.get_context("fork")
        with ProcessPoolExecutor(
            max_workers=worker_count,
            mp_context=context,
            initializer=_init_pure_cycle_worker,
            initargs=(skeleton01,),
        ) as executor:
            return list(executor.map(_evaluate_cut_candidate_worker, candidates, chunksize=1))
    except (OSError, RuntimeError):
        # 进程池只是性能优化；环境不支持 fork/进程池时，回退顺序评估以保持功能可用。
        return [evaluate_cut_candidate(skeleton01, cut_center_rc) for cut_center_rc in candidates]


def find_best_cycle_cut_and_paths(
    skeleton01: np.ndarray,
    *,
    max_candidate_count: int = 24,
    parallel_workers: int = 0,
) -> tuple[tuple[int, int] | None, tuple[tuple[int, int], ...], list[tuple[int, int]]]:
    """为 pure cycle cut 选择切口，并恢复 inner/outer 两部分几何。"""

    best: tuple[tuple[int, int], tuple[tuple[int, int], ...], list[tuple[int, int]], tuple[int, int, int]] | None = None
    candidates = rank_cut_candidates(skeleton01, max_candidates=max_candidate_count)
    for cut_center_rc, evaluated in zip(
        candidates,
        evaluate_cut_candidates(skeleton01, candidates, parallel_workers=int(parallel_workers)),
    ):
        if evaluated is None:
            continue
        inner_zone, outer_path_rc, score = evaluated
        if best is None or score > best[3]:
            best = (cut_center_rc, inner_zone, outer_path_rc, score)
    if best is None:
        return None, (), []
    return best[0], best[1], best[2]


__all__ = (
    "build_cycle_cut_inner_zone",
    "build_largest_component_mask",
    "chainify_cycle_residual",
    "evaluate_cut_candidates",
    "endpoint_count",
    "find_best_cycle_cut_and_paths",
    "rank_cut_candidates",
    "trace_open_chain_path",
)
