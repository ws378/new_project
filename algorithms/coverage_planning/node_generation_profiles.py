"""Coverage planner node generation profile contract."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

SHELF_CELL_ADJUSTED = "shelf_cell_adjusted"
TURN_COST_REGULAR_GRID = "turn_cost_regular_grid"
TURN_COST_REPAIRED_GRID = "turn_cost_repaired_grid"

SHELF_CELL_ADJUSTED_PROFILE_ID = "shelf_cell_adjusted_v1"
TURN_COST_REGULAR_GRID_PROFILE_ID = "turn_cost_regular_grid_v1"
TURN_COST_REPAIRED_GRID_PROFILE_ID = "turn_cost_repaired_grid_v1"

NODE_GENERATION_MODES = frozenset(
    {
        SHELF_CELL_ADJUSTED,
        TURN_COST_REGULAR_GRID,
        TURN_COST_REPAIRED_GRID,
    }
)


@dataclass(frozen=True)
class NodeGenerationProfile:
    """Formal registry record for a coverage node generation strategy."""

    profile_id: str
    mode: str
    strategy: str
    status: str
    provenance: str
    description: str
    applies_to_modes: tuple[str, ...]
    supports_repaired_grid_offset: bool = False
    supports_endpoint_alignment: bool = True
    supports_obstacle_ratio_filter: bool = True

    def metadata(self) -> dict[str, Any]:
        return {
            "profile_id": self.profile_id,
            "mode": self.mode,
            "strategy": self.strategy,
            "status": self.status,
            "provenance": self.provenance,
            "description": self.description,
            "applies_to_modes": list(self.applies_to_modes),
            "supports_repaired_grid_offset": bool(self.supports_repaired_grid_offset),
            "supports_endpoint_alignment": bool(self.supports_endpoint_alignment),
            "supports_obstacle_ratio_filter": bool(self.supports_obstacle_ratio_filter),
        }


NODE_GENERATION_PROFILE_REGISTRY: dict[str, NodeGenerationProfile] = {
    SHELF_CELL_ADJUSTED: NodeGenerationProfile(
        profile_id=SHELF_CELL_ADJUSTED_PROFILE_ID,
        mode=SHELF_CELL_ADJUSTED,
        strategy="cell_adjusted_free_point",
        status="formal_baseline",
        provenance="shelf_aware_guarded 原始网格节点生成策略",
        description="规则 coverage cell 中心不可通行时，在同 cell 内选择离障碍更远的可通行代表点。",
        applies_to_modes=("shelf_aware",),
        supports_repaired_grid_offset=False,
    ),
    TURN_COST_REGULAR_GRID: NodeGenerationProfile(
        profile_id=TURN_COST_REGULAR_GRID_PROFILE_ID,
        mode=TURN_COST_REGULAR_GRID,
        strategy="regular_grid_center_only",
        status="research_reference",
        provenance="turn-cost 研究中用于验证规则节点节拍的参考策略",
        description="只接受规则 grid center，可通行则生成节点，不对 blocked center 做补点。",
        applies_to_modes=("research",),
        supports_repaired_grid_offset=False,
    ),
    TURN_COST_REPAIRED_GRID: NodeGenerationProfile(
        profile_id=TURN_COST_REPAIRED_GRID_PROFILE_ID,
        mode=TURN_COST_REPAIRED_GRID,
        strategy="regular_grid_with_bounded_repair",
        status="candidate_mode_default",
        provenance="turn-cost 节点生成实验中保留规则节拍并恢复覆盖率的候选策略",
        description="规则 grid center 优先；中心不可通行时，仅在同 cell 内按最大偏移因子做受控补点。",
        applies_to_modes=("shelf_aware_turn_cost",),
        supports_repaired_grid_offset=True,
    ),
}


@dataclass(frozen=True)
class NodeGenerationSettings:
    """Node generation settings consumed by one coverage graph build."""

    mode: str = SHELF_CELL_ADJUSTED
    profile: NodeGenerationProfile = field(
        default_factory=lambda: resolve_node_generation_profile(SHELF_CELL_ADJUSTED)
    )
    repaired_grid_max_offset_factor: float = 0.35
    row_endpoint_alignment_enable: bool = False
    node_obstacle_ratio_filter_enable: bool = False
    node_obstacle_ratio_threshold: float = 0.45

    @classmethod
    def from_public_values(
        cls,
        *,
        node_generation_mode: str = SHELF_CELL_ADJUSTED,
        repaired_grid_max_offset_factor: float = 0.35,
        row_endpoint_alignment_enable: bool = False,
        node_obstacle_ratio_filter_enable: bool = False,
        node_obstacle_ratio_threshold: float = 0.45,
    ) -> "NodeGenerationSettings":
        mode = normalize_node_generation_mode(node_generation_mode)
        profile = resolve_node_generation_profile(mode)
        filter_enabled = bool(node_obstacle_ratio_filter_enable)
        return cls(
            mode=mode,
            profile=profile,
            repaired_grid_max_offset_factor=(
                float(repaired_grid_max_offset_factor)
                if mode == TURN_COST_REPAIRED_GRID
                else cls.repaired_grid_max_offset_factor
            ),
            row_endpoint_alignment_enable=bool(row_endpoint_alignment_enable),
            node_obstacle_ratio_filter_enable=filter_enabled,
            node_obstacle_ratio_threshold=(
                float(node_obstacle_ratio_threshold)
                if filter_enabled
                else cls.node_obstacle_ratio_threshold
            ),
        )

    def profile_metadata(self) -> dict[str, Any]:
        metadata = self.profile.metadata()
        metadata.update(
            {
                "repaired_grid_max_offset_factor": float(self.repaired_grid_max_offset_factor),
                "row_endpoint_alignment_enable": bool(self.row_endpoint_alignment_enable),
                "node_obstacle_ratio_filter_enable": bool(self.node_obstacle_ratio_filter_enable),
                "node_obstacle_ratio_threshold": float(self.node_obstacle_ratio_threshold),
            }
        )
        return metadata


def normalize_node_generation_mode(node_generation_mode: str) -> str:
    """Validate and return the canonical node generation mode name."""

    mode = str(node_generation_mode)
    if mode not in NODE_GENERATION_MODES:
        raise ValueError(
            "node_generation_mode must be shelf_cell_adjusted, "
            "turn_cost_regular_grid, or turn_cost_repaired_grid"
        )
    return mode


def resolve_node_generation_profile(node_generation_mode: str) -> NodeGenerationProfile:
    """Return the formal profile for a node generation mode."""

    mode = normalize_node_generation_mode(node_generation_mode)
    return NODE_GENERATION_PROFILE_REGISTRY[mode]
