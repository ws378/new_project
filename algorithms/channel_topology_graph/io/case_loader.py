"""真实 case 输入加载辅助函数。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

import cv2
import numpy as np
import yaml

LEGACY_CASE_PUBLIC_CONFIG_KEYS = (
    "coverage_radius",
    "grid_spacing_m",
    "robot_radius",
    "erode_radius",
    "erode_radius_m",
)
LEGACY_CASE_CTG_WIDTH_KEYS = (
    "sweep_max_spacing_m",
    "robot_cleaning_width_m",
)


@dataclass(slots=True)
class CasePlanningConfig:
    """Stage2-normalized planning_config contract for generated/real cases."""

    schema_version: int
    open_kernel_m: float
    obstacle_expand_m: float
    coverage_width_m: float
    robot_width_m: float
    free_node_min_clearance_m: float
    start_point_px: tuple[int, int]
    extras: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Guard the formal public case-planning contract against invalid values."""

        if int(self.schema_version) < 1:
            raise ValueError("planning_config schema_version must be >= 1")
        if float(self.open_kernel_m) <= 0.0:
            raise ValueError("planning_config open_kernel_m must be positive")
        if float(self.obstacle_expand_m) <= 0.0:
            raise ValueError("planning_config obstacle_expand_m must be positive")
        if float(self.coverage_width_m) <= 0.0:
            raise ValueError("planning_config coverage_width_m must be positive")
        if float(self.robot_width_m) <= 0.0:
            raise ValueError("planning_config robot_width_m must be positive")
        if float(self.free_node_min_clearance_m) < 0.0:
            raise ValueError("planning_config free_node_min_clearance_m must be >= 0")

    def __getitem__(self, key: str) -> Any:
        if hasattr(self, key) and key != "extras":
            return getattr(self, key)
        return self.extras[key]

    def get(self, key: str, default: Any = None) -> Any:
        if hasattr(self, key) and key != "extras":
            return getattr(self, key)
        return self.extras.get(key, default)

    def __contains__(self, key: object) -> bool:
        return isinstance(key, str) and ((hasattr(self, key) and key != "extras") or key in self.extras)

    def items(self) -> Iterator[tuple[str, Any]]:
        yield from self.to_dict().items()

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": int(self.schema_version),
            "open_kernel_m": float(self.open_kernel_m),
            "obstacle_expand_m": float(self.obstacle_expand_m),
            "coverage_width_m": float(self.coverage_width_m),
            "robot_width_m": float(self.robot_width_m),
            "free_node_min_clearance_m": float(self.free_node_min_clearance_m),
            "start_point_px": [int(self.start_point_px[0]), int(self.start_point_px[1])],
            **dict(self.extras),
        }


@dataclass(slots=True)
class CaseInput:
    """真实 case 输入封装。

    真实职责：
        把 case 目录里的地图 yaml、灰度图、区域约束和规划配置统一装配成
        可直接喂给 geometry_preparation 的运行输入。

    Args:
        case_dir:
            case 根目录。
        raw_map:
            喂给 geometry_preparation 的原始地图字典。
        region_constraint:
            喂给 geometry_preparation 的区域约束。
        planning_config:
            case 自带规划配置。
        meta:
            输入装配过程中的元信息。
    """

    case_dir: Path
    raw_map: dict[str, Any]
    region_constraint: np.ndarray
    planning_config: CasePlanningConfig
    meta: dict[str, Any]


def resolve_case_dir(case_dir: str | Path) -> Path:
    """把 case 目录规整成绝对路径。"""

    # 绝对路径有助于过程记录和 baseline 文档直接复用，不受当前 cwd 影响。
    return Path(case_dir).resolve()


def build_case_input_meta(
    *,
    case_assets: dict[str, Any],
    input_views: dict[str, Any],
    free_thresh_override: float | None,
) -> dict[str, Any]:
    """构造 `CaseInput.meta`。"""

    metadata = case_assets["metadata"]
    return {
        "map_yaml_path": str(case_assets["map_yaml_path"]),
        "image_path": str(case_assets["image_path"]),
        "region_path": str(case_assets["region_path"]),
        "planning_path": str(case_assets["planning_path"]),
        "crop_box_px": input_views["crop_box_px"],
        "free_thresh": float(
            metadata.get("free_thresh", 0.196) if free_thresh_override is None else free_thresh_override
        ),
        "resolution_m_per_px": float(metadata.get("resolution", 0.05)),
    }


def load_plan1_case_input(
    case_dir: str | Path,
    crop_pad_px: int = 20,
    free_thresh_override: float | None = None,
) -> CaseInput:
    """从 `plan1_aisle_graph_prototype` 的真实 case 目录加载输入。

    真实职责：
        复用当前研究主线的真实输入语义，把 yaml、pgm、region.json 和
        planning_config.json 收敛成新包 geometry_preparation 可直接消费的输入对象。

    Args:
        case_dir:
            case 目录路径。
        crop_pad_px:
            从区域掩膜反推出裁剪框时的外扩像素。
        free_thresh_override:
            可选自由空间阈值覆盖。为空时沿用 map yaml 中的 free_thresh。

    Returns:
        CaseInput:
            已统一装配好的真实输入对象。
    """

    # case 路径先转绝对路径，避免后续 meta 和 real-case compare 出现相对路径差异。
    case_dir = resolve_case_dir(case_dir)
    case_assets = load_case_assets(case_dir)
    input_views = build_case_input_views(
        case_assets=case_assets,
        crop_pad_px=crop_pad_px,
        free_thresh_override=free_thresh_override,
    )
    return build_case_input_result(
        case_dir=case_dir,
        case_assets=case_assets,
        input_views=input_views,
        planning_config=case_assets["planning_config"],
        free_thresh_override=free_thresh_override,
    )


def load_case_assets(case_dir: Path) -> dict[str, Any]:
    """读取 real-case 四类输入资产。"""

    # 四类输入文件是固定 real-case 套件的最小闭环，先全部解析出来。
    # 这些路径也会回写到 meta，供 baseline 与 smoke 输出统一留痕。
    map_yaml_path, image_path, region_path, planning_path = load_case_paths(case_dir)
    # 地图元信息、灰度图和规划参数在这里分开读取，保持输入来源一一对应。
    metadata = load_map_metadata(map_yaml_path)
    gray = load_gray_image(image_path)
    planning_config = normalize_case_planning_config(load_json(planning_path))
    region_payload = load_json(region_path)
    # 资产在这里全部读完后，后续 view 构造层就不再接触磁盘。
    # 读取顺序本身没有算法语义，但分开赋值更利于真实 case 排查单个资产异常。
    return {
        "map_yaml_path": map_yaml_path,
        "image_path": image_path,
        "region_path": region_path,
        "planning_path": planning_path,
        "metadata": metadata,
        "gray": gray,
        "planning_config": planning_config,
        "region_payload": region_payload,
    }


def normalize_case_planning_config(planning_config: dict[str, Any]) -> CasePlanningConfig:
    """Normalize case planning_config into stage2 formal public fields."""

    normalized = normalize_case_planning_payload(planning_config)
    if "schema_version" not in normalized:
        normalized["schema_version"] = 1
    start_point_raw = normalized.get("start_point_px", [0, 0])
    start_point_px = (
        int(start_point_raw[0]) if len(start_point_raw) >= 1 else 0,
        int(start_point_raw[1]) if len(start_point_raw) >= 2 else 0,
    )
    reserved = {
        "schema_version",
        "open_kernel_m",
        "obstacle_expand_m",
        "coverage_width_m",
        "robot_width_m",
        "free_node_min_clearance_m",
        "start_point_px",
    }
    return CasePlanningConfig(
        schema_version=int(normalized.get("schema_version", 1)),
        open_kernel_m=float(normalized.get("open_kernel_m", 0.6)),
        obstacle_expand_m=float(normalized.get("obstacle_expand_m", 0.6)),
        coverage_width_m=float(normalized.get("coverage_width_m", 0.55)),
        robot_width_m=float(normalized.get("robot_width_m", 0.55)),
        free_node_min_clearance_m=float(normalized.get("free_node_min_clearance_m", 0.35)),
        start_point_px=start_point_px,
        extras={key: value for key, value in normalized.items() if key not in reserved},
    )


def normalize_case_planning_payload(planning_config: dict[str, Any]) -> dict[str, Any]:
    """Normalize case planning payload and reject removed stage2 legacy keys."""

    normalized = dict(planning_config)
    found_legacy_public_keys = tuple(
        key for key in LEGACY_CASE_PUBLIC_CONFIG_KEYS if key in normalized
    )
    if found_legacy_public_keys:
        raise ValueError(
            "planning_config legacy public key is no longer supported: "
            + ", ".join(found_legacy_public_keys)
        )
    found_legacy_ctg_width_keys = tuple(
        key for key in LEGACY_CASE_CTG_WIDTH_KEYS if key in normalized
    )
    if found_legacy_ctg_width_keys:
        raise ValueError(
            "planning_config legacy width key is no longer supported: "
            + ", ".join(found_legacy_ctg_width_keys)
        )
    return normalized


def build_case_input_views(
    *,
    case_assets: dict[str, Any],
    crop_pad_px: int,
    free_thresh_override: float | None,
) -> dict[str, Any]:
    """构造 geometry_preparation 真正消费的输入视图。"""

    gray = case_assets["gray"]
    metadata = case_assets["metadata"]
    region_payload = case_assets["region_payload"]
    # 裁剪框和自由区语义都沿用旧 case 资产，保证新包与既有真实数据口径一致。
    # region 先转掩膜，再由掩膜推导 crop box，避免 polygon 数学差异影响裁剪边界。
    region_mask = build_region_mask_from_polygon(gray.shape, region_payload["polygon_points"])
    crop_box_px = crop_box_from_mask(region_mask, crop_pad_px)
    # free_mask 不从 region 扣，而是保留整图自由区真值，裁剪由 geometry_preparation 自己执行。
    free_mask = build_free_binary_from_gray(gray, metadata, free_thresh_override)
    # raw_map 是直接喂给 geometry_preparation 的对象，因此这里只保留 geometry_preparation 真正会消费的字段。
    raw_map = {
        "gray": gray,
        "free_mask": free_mask,
        "resolution_m_per_px": float(metadata.get("resolution", 0.05)),
        "map_yaml_path": str(case_assets["map_yaml_path"]),
        "image_path": str(case_assets["image_path"]),
    }
    return {
        "region_mask": region_mask,
        "crop_box_px": crop_box_px,
        "free_mask": free_mask,
        "raw_map": raw_map,
    }


def build_case_input_result(
    *,
    case_dir: Path,
    case_assets: dict[str, Any],
    input_views: dict[str, Any],
    planning_config: dict[str, Any],
    free_thresh_override: float | None,
) -> CaseInput:
    """组装最终 `CaseInput`。"""

    # meta 记录输入装配痕迹，方便 fixed-case baseline 与 real-case smoke 复核。
    # 阈值和分辨率也一起回写，避免后续排查时再回读 yaml。
    # 这里返回的是 stage-0 输入包，而不是直接触发任何算法计算。
    # 后续是否裁剪、是否写盘，全部留给显式 stage/pipeline 决定。
    return CaseInput(
        case_dir=case_dir,
        raw_map=input_views["raw_map"],
        region_constraint=input_views["region_mask"],
        planning_config=planning_config,
        meta=build_case_input_meta(
            case_assets=case_assets,
            input_views=input_views,
            free_thresh_override=free_thresh_override,
        ),
    )


def load_case_paths(case_dir: Path) -> tuple[Path, Path, Path, Path]:
    """解析 case 目录里的标准输入文件。"""

    # 真实 case 当前按“单 yaml + 单 pgm + 两个 json”组织，先做显式存在性检查。
    yaml_candidates = sorted(case_dir.glob("*.yaml"))
    pgm_candidates = sorted(case_dir.glob("*.pgm"))
    region_path = case_dir / "region.json"
    planning_path = case_dir / "planning_config.json"
    # yaml/pgm 当前默认取第一个候选，是为了贴合现有 case 目录的一图一配置结构。
    # 缺任一输入文件都视为 case 资产不完整，直接停止而不是做隐式猜测。
    # 这里故意不做“找最像的文件名”之类兜底，避免真实输入口径漂移。
    # 真实 case 目录一旦出现多文件歧义，也应先通过资产整理解决，而不是在这里猜。
    if not yaml_candidates:
        raise FileNotFoundError(f"no yaml found in {case_dir}")
    if not pgm_candidates:
        raise FileNotFoundError(f"no pgm found in {case_dir}")
    if not region_path.is_file():
        raise FileNotFoundError(f"region.json not found in {case_dir}")
    if not planning_path.is_file():
        raise FileNotFoundError(f"planning_config.json not found in {case_dir}")
    return yaml_candidates[0], pgm_candidates[0], region_path, planning_path


def load_map_metadata(map_yaml_path: Path) -> dict[str, Any]:
    """读取 map yaml。"""

    # yaml 内容可能为空文件，因此这里统一回退为空 dict。
    with map_yaml_path.open("r", encoding="utf-8") as file:
        return yaml.safe_load(file) or {}


def load_gray_image(image_path: Path) -> np.ndarray:
    """读取单通道灰度图。"""

    # 真实 case 的图片有时会被 cv2 读成多通道，因此这里统一压成灰度。
    image = cv2.imread(str(image_path), cv2.IMREAD_UNCHANGED)
    if image is None:
        raise FileNotFoundError(f"failed to load image: {image_path}")
    # 多通道图在 geometry_preparation 没有正式意义，统一按灰度解释。
    # 这里不做归一化，保留原始灰度值，阈值解释留给自由空间规则层处理。
    if image.ndim == 3:
        image = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    return image


def load_json(path: Path) -> dict[str, Any]:
    """读取 json 文件。"""

    # json 资产都按 utf-8 读取，避免中文路径/注释字段出现编码歧义。
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def build_free_binary_from_gray(
    gray: np.ndarray,
    metadata: dict[str, Any],
    free_thresh_override: float | None = None,
) -> np.ndarray:
    """沿用旧主线的灰度转自由空间规则。"""

    # `free_thresh_override` 只在显式传入时覆盖 yaml，保证 fixed-case 口径稳定。
    free_thresh = float(metadata.get("free_thresh", 0.196) if free_thresh_override is None else free_thresh_override)
    negate = int(metadata.get("negate", 0))
    # 统一先转到 0~1 浮点灰度，避免整数阈值比较带来的表达混乱。
    gray_float = gray.astype(np.float32) / 255.0

    # 旧地图语义里 `negate=0` 表示深色更像障碍，因此要先做一次反相占据率解释。
    occupancy = gray_float if negate else (1.0 - gray_float)
    # 这里输出的就是 geometry_preparation 正式自由掩膜语义，因此直接转成 0/255 二值图。
    is_free = occupancy < free_thresh
    return np.where(is_free, 255, 0).astype(np.uint8)


def build_region_mask_from_polygon(
    shape: tuple[int, int],
    polygon_points: list[list[int]],
) -> np.ndarray:
    """把区域多边形转成区域掩膜。"""

    # region.json 保存的是整型顶点序列，这里直接按 OpenCV 多边形填充语义落掩膜。
    # 掩膜才是 geometry_preparation 真正消费的正式区域约束对象。
    # 不在这里做几何平滑或闭合修复，保持与输入资产一一对应。
    points = np.asarray(polygon_points, dtype=np.int32)
    mask = np.zeros(shape, dtype=np.uint8)
    cv2.fillPoly(mask, [points], 255)
    return mask


def crop_box_from_mask(mask: np.ndarray, pad_px: int) -> tuple[int, int, int, int]:
    """从区域掩膜推导裁剪框。"""

    # 裁剪框由 region 的外接矩形推导，是 real-case 固定输入的一部分。
    points = np.argwhere(mask > 0)
    if points.size == 0:
        raise ValueError("empty region mask")
    # pad 在这里表达“运行时预留边界”，避免后续裁剪把区域边缘的有效信息切掉。
    # 四个边界都按闭区间像素极值推导，最后再转换成 Python slice 语义。
    top = max(0, int(points[:, 0].min()) - pad_px)
    left = max(0, int(points[:, 1].min()) - pad_px)
    bottom = min(mask.shape[0], int(points[:, 0].max()) + pad_px + 1)
    right = min(mask.shape[1], int(points[:, 1].max()) + pad_px + 1)
    return (top, left, bottom, right)
