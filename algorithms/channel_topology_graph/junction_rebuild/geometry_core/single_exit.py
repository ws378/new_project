"""单旧中心交汇的 exit 提取逻辑。"""

from __future__ import annotations

import collections

from .common import graph_distances, neighbors8, path_from_prev, to_global
from .path_cuts import exit_from_branch_path


def extract_single_center_exits(
    local_ctx: dict[str, object],
    min_cut_px: float,
    probe_px: float,
    verify_px: float,
    stable_angle_deg: float,
    extra_push_px: float,
):
    """按单中心逻辑提取 outward exits。"""

    # 单中心场景下，所有 outward branch 都围绕同一个旧中心向外发散。
    # 这条路径专门服务于“一个旧节点重建为一个新节点”的常规交汇。
    # 因而这里不涉及 clustered exit 的多旧点合并判断。
    points_local = local_ctx["original_points_local"]
    old_local = local_ctx["old_points_local"][0]
    r0, _r1, c0, _c1 = local_ctx["crop_box"]
    dist_from_old, _ = graph_distances(old_local, points_local)
    # 先拿到“旧中心到所有局部骨架点”的 geodesic 距离，这是后续 core 扩张的基线。
    # 之后所有 step 变化，本质上都是在这张距离图上调一个阈值。

    def touching_components_for_step(step: int):
        """在给定 geodesic 半径下提取与核心区接触的残余分量。"""

        # `core` 代表距旧中心不超过当前半径的局部骨架核心。
        # step 增大时，残余分量通常会从多条 branch 逐渐并入核心区。
        # 所以后续只要观察分量数平台，就能估计合理核心半径。
        core = {point_rc for point_rc, distance in dist_from_old.items() if distance <= step}
        residual = points_local - core
        seen = set()
        comps = []
        # residual 上的每个连通分量都可能对应一条 outward branch。
        # 这里不提前按几何长度过滤，先完整恢复，再交给 cut 规则统一处理。
        for point_rc in residual:
            if point_rc in seen:
                continue
            # 每个残余分量都通过 BFS 收成一条局部 branch 候选。
            queue = collections.deque([point_rc])
            seen.add(point_rc)
            comp = {point_rc}
            while queue:
                cur = queue.popleft()
                # 这里只在 residual 内扩张，核心区本身不再重复吞入分量。
                # 因而 comp 的边界天然就是“贴着核心区的残余骨架”。
                for nxt in neighbors8(cur):
                    if nxt in residual and nxt not in seen:
                        seen.add(nxt)
                        queue.append(nxt)
                        comp.add(nxt)
            # 只保留真正贴着核心区的分量，孤立噪声分量直接丢弃。
            attach = [candidate for candidate in comp if any(nb in core for nb in neighbors8(candidate))]
            if not attach:
                continue
            # entry 选离旧中心最近的挂接点，尽量稳定代表分量入口。
            # 不直接使用任意 attach 点，是为了减少入口点对 BFS 起点的随机性。
            entry = min(attach, key=lambda candidate: dist_from_old.get(candidate, 10**9))
            allowed = set(comp) | {entry}
            dist_map, prev = graph_distances(entry, allowed)
            far = max(dist_map, key=dist_map.get)
            # 这里恢复的是“从 entry 到最远端”的 outward path。
            # path 与 entry 一起返回，方便后续在全局坐标上做正式截断。
            # 这一步不做截断，只负责把候选 branch 恢复完整。
            comps.append((path_from_prev(far, prev), entry))
        return comps

    best_step = 1
    max_step = 16
    # 先扫描不同 step 下的触达分量数量，再挑一个稳定平台作为核心半径。
    # step 上限保持小常数，避免把局部核心不必要地扩张到 branch 深处。
    # 在正常交汇尺度下，这个窗口足以覆盖“核心区到出口”的分裂过程。
    comps_by_step: dict[int, list[tuple[list[tuple[int, int]], tuple[int, int]]]] = {}
    counts: dict[int, int] = {}
    # 平台条件要求至少连续三步分量数不变，避免偶然抖动。
    # 这比直接取第一个达到 3 个分量的 step 更稳健。
    for step in range(1, max_step - 1):
        for probe_step in (step, step + 1, step + 2):
            if probe_step not in counts:
                comps = touching_components_for_step(probe_step)
                comps_by_step[probe_step] = comps
                counts[probe_step] = len(comps)
        comp_count = counts[step]
        if comp_count >= 3 and counts[step + 1] == comp_count and counts[step + 2] == comp_count:
            best_step = step
            break
    # 若始终找不到稳定平台，就沿用最小 step=1 的保守默认值。
    # 这意味着旧中心周围核心区尽量取小，只在平台证据明确时才向外扩张。

    exits = []
    best_components = comps_by_step.get(best_step)
    if best_components is None:
        best_components = touching_components_for_step(best_step)
    for branch_id, (path_local, entry_local) in enumerate(best_components):
        # 最终出口截断规则统一在全局坐标里执行，便于与节点几何其它模块对齐。
        # 因而 local path 在这里做一次全局回写后，就不再继续外泄 local 口径。
        path_global = [to_global(point_rc, r0, c0) for point_rc in path_local]
        entry_global = to_global(entry_local, r0, c0)
        # 每条 branch 都会落成一条正式 ExitTrace，供后续 support/sector 模块消费。
        # `branch_id` 只是当前局部枚举顺序，最终还会按角度重新排序。
        exits.append(
            exit_from_branch_path(
                branch_id=branch_id,
                old_center_global=local_ctx["old_points_global"][0],
                new_center_global=local_ctx["new_center_global"],
                path_global=path_global,
                entry_global=entry_global,
                min_cut_px=min_cut_px,
                probe_px=probe_px,
                verify_px=verify_px,
                stable_angle_deg=stable_angle_deg,
                extra_push_px=extra_push_px,
            )
        )
    # 最终按稳定方向排序，后续 sector/support 评估都依赖这个顺序。
    # 单中心逻辑的最终输出只是一组已排序 exits，不在这里做额外打分。
    # 这样 clustered/single-center 两条逻辑线在输出口径上保持一致。
    # 排序完成后，调用方可以直接把它们当作环顺序 exits 使用。
    exits.sort(key=lambda item: float(item.stable_theta_deg))
    return exits


__all__ = ["extract_single_center_exits"]
