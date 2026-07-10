"""多旧中心交汇的 clustered exit 提取逻辑。"""

from __future__ import annotations

import collections
import math

from .common import RING8, graph_distances, neighbors8, path_from_prev, to_global
from .path_cuts import exit_from_branch_path


def seed_groups_around_old(
    old_rc: tuple[int, int],
    residual: set[tuple[int, int]],
) -> list[list[tuple[int, int]]]:
    """按旧 `05` 逻辑把旧点周围 8 邻域方向分组。"""

    # 先查看旧中心 8 邻域上哪些位置命中了 residual 骨架。
    ring_hits: list[tuple[int, tuple[int, int]]] = []
    for index, (dr, dc) in enumerate(RING8):
        rc = (old_rc[0] + dr, old_rc[1] + dc)
        if rc in residual:
            ring_hits.append((index, rc))
    # 一个命中都没有时，说明该旧中心周围没有 outward 残余分支。
    # 此时旧中心不会贡献任何 clustered exit seed。
    if not ring_hits:
        return []

    # 相邻 ring index 归为同一组，表达同一方向簇。
    groups: list[list[tuple[int, int]]] = []
    cur_group = [ring_hits[0][1]]
    prev_idx = ring_hits[0][0]
    for index, rc in ring_hits[1:]:
        if index == prev_idx + 1:
            cur_group.append(rc)
        else:
            groups.append(cur_group)
            cur_group = [rc]
        prev_idx = index
    groups.append(cur_group)
    # 到这里 groups 还是线性 ring 顺序，需要额外处理首尾相接场景。
    # 这和普通一维分组不同，因为 ring 本质上是环结构。
    # 不处理首尾粘连的话，0 度附近会被错误拆成两组。

    # 若首尾在环上连成一片，需要把两端组拼回同一簇。
    if len(groups) >= 2 and ring_hits[0][0] == 0 and ring_hits[-1][0] == len(RING8) - 1:
        groups[0] = groups[-1] + groups[0]
        groups.pop()
    # 返回的每一组都可视作一个 seed direction。
    # 后续 multi-source BFS 会把同组 seed 视作同一条 branch 的起源。
    # 这让 ring seed 的方向语义在 clustered 场景里得以保留。
    return groups


def identify_local_branches(
    original_points_local: set[tuple[int, int]],
    old_points_local: list[tuple[int, int]],
    merged_center_local: tuple[int, int],
) -> list[dict[str, object]]:
    """按旧 `05` 的局部分支提取语义，恢复 clustered exits。"""

    # old 点自身不参与 residual branch 恢复，只把周围残余骨架拿出来分配。
    old_set = set(old_points_local)
    residual = original_points_local - old_set
    branch_instances: list[dict[str, object]] = []
    sources: list[dict[str, object]] = []
    for old_idx, old_rc in enumerate(old_points_local):
        # 每个旧中心按周围 seed group 产生若干 branch source。
        # source_id 用字符串编码，只为后续 owner/pixels_by_owner 做稳定键。
        groups = seed_groups_around_old(old_rc, residual)
        for group_idx, group in enumerate(groups):
            sources.append(
                {
                    "source_id": f"old{old_idx}_g{group_idx}",
                    "old_idx": old_idx,
                    "seed_group": group,
                }
            )

    # 没有任何 source 时，意味着 clustered exits 为空。
    # 这通常说明 merged center 周围的旧点已经把 residual 吞尽。
    if not sources:
        return []
    # source 的多少决定了后续 owner 竞争的初始种子数量。

    # 先做一次多源 BFS，把 residual 像素归属到最近的 source。
    owner: dict[tuple[int, int], str] = {}
    dist: dict[tuple[int, int], int] = {}
    queue = collections.deque()
    for source in sources:
        for point_rc in source["seed_group"]:
            if point_rc not in residual:
                continue
            if point_rc not in owner:
                owner[point_rc] = source["source_id"]
                dist[point_rc] = 0
                queue.append(point_rc)
                # 同一点如果被多个 seed group 共享，先到先占。
                # 这里没有再比较距离，因为所有 seed 初始距离都为零。
                # 这种“先到先占”已经足够给出稳定 owner 分区。

    while queue:
        cur = queue.popleft()
        cur_owner = owner[cur]
        cur_dist = dist[cur]
        for nxt in neighbors8(cur):
            if nxt not in residual or nxt in owner:
                continue
            owner[nxt] = cur_owner
            dist[nxt] = cur_dist + 1
            queue.append(nxt)
            # 一个 residual 像素一旦归属某个 source，就不会被再次抢占。
            # 这让 branch 归属结果保持单值，不出现共享像素。

    # owner 图再反聚合成每个 source 对应的 branch 像素集。
    pixels_by_owner: dict[str, set[tuple[int, int]]] = {}
    for point_rc, source_id in owner.items():
        pixels_by_owner.setdefault(source_id, set()).add(point_rc)

    for source in sources:
        source_id = source["source_id"]
        branch_pixels = pixels_by_owner.get(source_id, set())
        if not branch_pixels:
            continue
        # 只有真正分到像素的 source，才可能成长成正式 branch。
        # 否则该 source 只是在种子阶段存在，后续直接丢弃。

        # attach 点表达 branch 在 old cluster 周围真正贴上的位置。
        # attach 为空时说明该 source 虽扩张成功，但没有真正贴到 old cluster。
        attach_points = [point_rc for point_rc in branch_pixels if any(nb in old_set for nb in neighbors8(point_rc))]
        # attached_old_indices 记录它实际贴住了哪些旧中心。
        # 这一步是后面按单旧中心归类的关键前置。
        # 若 attached_old_indices 为空，这条 branch 的归属会非常不稳定。
        # 也正因此，attach 质量会直接影响 clustered exits 稳定性。
        # attached_old_indices 的数量也会决定该 branch 是否被保留。
        attached_old_indices = sorted(
            {
                index
                for point_rc in attach_points
                for index, old_candidate in enumerate(old_points_local)
                if any(nb == old_candidate for nb in neighbors8(point_rc))
            }
        )
        # attached_old_indices 会决定这条 branch 后面能否归入单一旧中心。
        # seed 选离 merged center 最近的 seed 点，作为 branch 正式入口。
        # 这能让入口点更接近新中心侧，便于后续 cut 规则稳定工作。
        seed = min(
            source["seed_group"],
            key=lambda point_rc: (
                point_rc[0] - merged_center_local[0]
            ) ** 2 + (
                point_rc[1] - merged_center_local[1]
            ) ** 2,
        )
        # allowed 把 seed group 自身也纳入，确保 path 恢复不会丢掉入口邻域。
        allowed = branch_pixels | set(source["seed_group"])
        dist_map, prev = graph_distances(seed, allowed)
        far = max(dist_map, key=dist_map.get)
        # 恢复的是从 seed 到 far 的 outward path，本阶段不做截断。
        # path_local 在这里仍保留 local 坐标，便于后续统一回写 global。
        # far 代表该 branch 在局部骨架上的最远外延端。
        # graph_distances 给出的也是离散 geodesic，而不是欧氏直线。
        # 因而 far 更接近“沿骨架最远”，而不是“几何上最远”。
        # 这也让 path_local 更符合真实骨架走向。
        # seed/far/path_local 三者共同定义了一条完整的局部分支实例。
        # 后续 clustered exit 只会在这条实例上做筛选和正式 cut。
        # 因而 branch_instances 本身已经是很接近最终出口的中间形态。
        # 这份中间形态也最适合做调试可视化和问题定位。
        branch_instances.append(
            {
                "branch_id": f"branch_{len(branch_instances) + 1:02d}",
                "pixels_local": branch_pixels,
                "attach_points_local": attach_points,
                "attached_old_indices": attached_old_indices,
                "seed_point_local": seed,
                "path_local": path_from_prev(far, prev),
                "farthest_point_local": far,
            }
        )
    # branch_instances 是 clustered exit 正式提取前的中间语义结果。
    # 每条实例都记录了附着旧中心信息和未截断路径。
    # 后续真正输出 exit 前，还会再次按 old center 和距离做筛选。
    return branch_instances


def extract_clustered_exits(
    local_ctx: dict[str, object],
    min_cut_px: float,
    probe_px: float,
    verify_px: float,
    stable_angle_deg: float,
):
    """按 clustered 旧中心逻辑提取 exits。"""

    # 先恢复所有局部分支实例，再按各旧中心分别挑选候选出口。
    branches = identify_local_branches(
        original_points_local=local_ctx["original_points_local"],
        old_points_local=local_ctx["old_points_local"],
        merged_center_local=local_ctx["new_center_local"],
    )
    by_old: dict[int, list[dict[str, object]]] = {index: [] for index in range(len(local_ctx["old_points_local"]))}
    for branch in branches:
        if len(branch["attached_old_indices"]) != 1:
            # 同时贴多个旧中心的 branch 不适合直接归到单个旧中心出口。
            # 这类 branch 若强行保留，会把 clustered 语义重新混成共享出口。
            continue
        by_old[branch["attached_old_indices"][0]].append(branch)
    # 到这里，每个旧中心只保留“单独附着到自己”的 branch 候选。
    # 被多个旧中心共享的 branch 会在这里被主动丢弃。

    r0, _r1, c0, _c1 = local_ctx["crop_box"]
    exits = []
    next_id = 0
    for old_idx, _old_local in enumerate(local_ctx["old_points_local"]):
        candidates = by_old.get(old_idx, [])
        scored = []
        for branch in candidates:
            # 候选排序依据是 far 点到 merged center 的距离，越远越像正式 outward 分支。
            far = branch["farthest_point_local"]
            distance = math.hypot(
                float(far[0] - local_ctx["new_center_local"][0]),
                float(far[1] - local_ctx["new_center_local"][1]),
            )
            scored.append((distance, branch))
        # 先算完所有距离，再统一按距离倒序取前两条。
        scored.sort(key=lambda item: item[0], reverse=True)
        # 每个旧中心最多保留两条最强 outward 分支，和旧算法语义对齐。
        # 这避免一个旧中心附近出现过多碎片 branch 时把出口数冲高。
        # 同一旧中心的弱短 branch 会在这里被主动压掉。
        # 因而 clustered 场景下每个旧中心的出口数有一个显式上限。
        for _distance, branch in scored[:2]:
            path_global = [to_global(point_rc, r0, c0) for point_rc in branch["path_local"]]
            entry_global = to_global(branch["seed_point_local"], r0, c0)
            # 正式 cut 逻辑仍复用统一的 exit_from_branch_path。
            # 因而 clustered/single-center 两条链最终在 exit 结构上完全一致。
            exits.append(
                exit_from_branch_path(
                    branch_id=next_id,
                    old_center_global=local_ctx["old_points_global"][old_idx],
                    new_center_global=local_ctx["new_center_global"],
                    path_global=path_global,
                    entry_global=entry_global,
                    min_cut_px=min_cut_px,
                    probe_px=probe_px,
                    verify_px=verify_px,
                    stable_angle_deg=stable_angle_deg,
                )
            )
            next_id += 1
        # branch_id 只是当前 clustered 提取阶段的递增编号。
        # 真正消费时仍然会按 stable theta 重排。
        # 因而编号只用于调试与中间追踪，不表达几何顺序。
        # 这也避免了编号变动影响正式几何语义。
        # next_id 的存在只是为了保证每条 exit 有唯一中间标识。
        # 正式顺序最终仍由 stable theta 决定。
    # clustered exits 最终同样统一按 stable theta 排序。
    # 排序后的输出口径与 single-center exits 完全一致。
    # 这样后续 support/polygon 评估不需要关心它来自 clustered 分支。
    # 调试时也能直接把两类 exits 放到同一套可视化里。
    exits.sort(key=lambda item: float(item.stable_theta_deg))
    return exits


__all__ = (
    "seed_groups_around_old",
    "identify_local_branches",
    "extract_clustered_exits",
)
