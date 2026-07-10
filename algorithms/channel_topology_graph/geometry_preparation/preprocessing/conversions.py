"""基础几何准备中的图像/分辨率/类型转换 helper。"""

from __future__ import annotations

from typing import Any

import cv2
import numpy as np


def to_gray(raw_map: Any, config: dict[str, Any] | None = None) -> np.ndarray:
    """把原始输入转成单通道灰度图。"""

    # 当前 helper 不读配置，但保留参数位是为了维持预处理入口签名一致。
    _ = config
    # 原始输入允许多种容器，先统一抽出真正的图像数组。
    image = extract_image_array(raw_map)
    # 已经是单通道时直接沿用，避免无意义重编码。
    if image.ndim == 2:
        gray = image
    elif image.ndim == 3 and image.shape[2] == 1:
        # 单通道三维数组通常来自某些图像库的保守输出，这里压回二维。
        gray = image[:, :, 0]
    elif image.ndim == 3 and image.shape[2] == 3:
        # 这里统一按 OpenCV 的 BGR 灰度规则转，避免不同入口各自选转换公式。
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    else:
        raise ValueError(f"unsupported raw_map image shape: {image.shape}")
    # 最终统一成连续 `uint8` 灰度图，便于后续 OpenCV 与掩膜逻辑直接消费。
    return np.ascontiguousarray(to_uint8_gray(gray))


def derive_resolution(raw_map: Any, config: dict[str, Any] | None = None) -> float:
    """解析运行尺度分辨率。"""

    if config is None:
        config = {}

    # 分辨率优先级固定为显式配置 -> raw_map 标准字段 -> 兼容字段。
    candidates = [
        config.get("resolution_m_per_px"),
        raw_map.get("resolution_m_per_px") if isinstance(raw_map, dict) else None,
        raw_map.get("resolution") if isinstance(raw_map, dict) else None,
    ]
    # 显式 config 放在最前，是为了让外部覆盖值拥有单一真值优先级，而不是和 raw_map 字段并列竞争。
    # 候选值按顺序短路，一旦遇到合法正值就立即收口。
    for value in candidates:
        if value is None:
            continue
        # 只接受正值分辨率，零值和负值都应被视为脏输入。
        resolution = float(value)
        if resolution > 0:
            return resolution
    # 所有来源都无效时直接失败，避免后续长度换算默默漂移。
    # 这里不提供默认分辨率，是为了避免真实案例被静默套错尺度。
    raise ValueError("resolution_m_per_px must be provided and positive")


def derive_open_kernel_px(config: dict[str, Any], resolution_m_per_px: float) -> int:
    """把开运算核大小统一转成运行尺度像素。"""

    # 像素级门限一旦显式给出，就直接视为最高优先级真值。
    if "open_kernel_px" in config:
        return max(1, int(config["open_kernel_px"]))
    # 否则退回米制配置，再统一走同一个换算 helper。
    open_kernel_m = float(config.get("open_kernel_m", 0.6))
    return kernel_px_from_meters(open_kernel_m, resolution_m_per_px)


def derive_obstacle_expand_px(config: dict[str, Any], resolution_m_per_px: float) -> int:
    """把障碍物膨胀尺度统一转成运行尺度像素。"""

    if "obstacle_expand_px" in config:
        return max(1, int(config["obstacle_expand_px"]))
    if "obstacle_expand_m" in config:
        return kernel_px_from_meters(float(config["obstacle_expand_m"]), resolution_m_per_px)
    return derive_open_kernel_px(config, resolution_m_per_px)


def kernel_px_from_meters(kernel_m: float, resolution_m_per_px: float) -> int:
    """把米制长度转换成运行尺度像素长度。"""

    # 像素换算必须建立在正分辨率上，否则所有空间尺度都失真。
    if resolution_m_per_px <= 0:
        raise ValueError("resolution_m_per_px must be positive")
    # 最小核强制为 1，避免后续形态学分支出现零尺寸非法参数。
    return max(1, int(round(float(kernel_m) / float(resolution_m_per_px))))


def remove_small_free_islands(mask: np.ndarray, min_area_px: int) -> np.ndarray:
    """去除自由空间中的小连通域。"""

    # 面积门限小于等于 1 时，不需要真正做连通域分析。
    if min_area_px <= 1:
        return np.where(mask > 0, 255, 0).astype(np.uint8)

    # 连通域统计只在标准 0/255 二值图上执行，避免灰度残值干扰面积判断。
    num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(np.where(mask > 0, 255, 0).astype(np.uint8), 8)
    cleaned = np.zeros_like(mask, dtype=np.uint8)
    for label in range(1, num_labels):
        # 背景 label=0 跳过，其余分量按面积门限决定保留与否。
        area_px = int(stats[label, cv2.CC_STAT_AREA])
        if area_px < min_area_px:
            continue
        # 满足门限的连通域完整保留，不做额外形状裁剪。
        cleaned[labels == label] = 255
    return cleaned


def extract_image_array(raw_map: Any) -> np.ndarray:
    """从外部输入中提取图像数组。"""

    # 直接数组输入是最简单路径，优先快速返回。
    if isinstance(raw_map, np.ndarray):
        return raw_map
    if isinstance(raw_map, dict):
        # 兼容多个常见键名，但只接受真正的 numpy 图像数组。
        for key in ("gray", "image", "map", "raw_map"):
            value = raw_map.get(key)
            if isinstance(value, np.ndarray):
                return value
    # 到这里还没返回，说明输入既不是数组，也没提供可识别图像键。
    raise TypeError("raw_map must be a numpy array or a dict containing a numpy image")


def extract_mask_array(source: Any, key: str) -> np.ndarray | None:
    """从字典样输入中提取掩膜数组。"""

    # 非字典输入视为“不提供该掩膜”，由上层决定后续兜底语义。
    if not isinstance(source, dict):
        return None
    value = source.get(key)
    # 键不存在或显式为 None 时，都按“无该掩膜”处理。
    if value is None:
        return None
    # 一旦提供掩膜，就要求它已经是数组，避免上层 silently 转错类型。
    if not isinstance(value, np.ndarray):
        raise TypeError(f"{key} must be a numpy array when provided")
    return value


def to_uint8_gray(gray: np.ndarray) -> np.ndarray:
    """把灰度图统一转成 `uint8`。"""

    # 已经是目标 dtype 时不重复拷贝缩放。
    if gray.dtype == np.uint8:
        return gray
    if np.issubdtype(gray.dtype, np.floating):
        # 浮点灰度既兼容 0~255，也兼容 0~1 表达，这里统一做有界转换。
        scaled = np.clip(gray, 0.0, 255.0)
        if scaled.max(initial=0.0) <= 1.0:
            scaled = scaled * 255.0
        return scaled.astype(np.uint8)
    # 其余整型或更宽类型统一裁到 0~255 再转 `uint8`。
    return np.clip(gray, 0, 255).astype(np.uint8)


def to_uint8_mask(mask: np.ndarray) -> np.ndarray:
    """把任意布尔/整型掩膜统一成 `0/255 uint8`。"""

    # 布尔掩膜直接映射成 0/255，保持二值语义最清晰。
    if mask.dtype == np.bool_:
        return np.where(mask, 255, 0).astype(np.uint8)
    if mask.dtype == np.uint8:
        # 即使已经是 `uint8`，也统一压成严格 0/255，避免残值泄漏。
        return np.where(mask > 0, 255, 0).astype(np.uint8)
    # 其它整数类型只看正负/零关系，不保留原始数值幅度。
    return np.where(mask.astype(np.int32) > 0, 255, 0).astype(np.uint8)


__all__ = [
    "derive_obstacle_expand_px",
    "derive_open_kernel_px",
    "derive_resolution",
    "extract_mask_array",
    "kernel_px_from_meters",
    "remove_small_free_islands",
    "to_gray",
    "to_uint8_mask",
]
