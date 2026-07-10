"""局部方向场构建与外部语义图对齐。

方向场以“无向轴”口径统一到 [0, pi)，后续清扫逻辑依赖该口径做决策。
外部 axis 先转向量再旋转，避免仿射插值时出现 pi 周期边界翻转。
"""

from __future__ import annotations

import math

import cv2
import numpy as np

from ..models import LocalDirectionConfig, PlannerConfig


def compute_local_direction_map(
  rotated_room_map: np.ndarray,
  coverage_width_px: int,
  config: LocalDirectionConfig,
) -> tuple[np.ndarray, np.ndarray]:
  """基于局部边界梯度估计可行走主轴和方向置信度。

  使用结构张量抑制单点噪声，输出两个图：方向轴和置信度。
  当 coverage 宽度不足时，方向场会显著抖动，因此把平滑尺度与 width 绑定。

  Args:
    rotated_room_map: 已旋转到主方向坐标系的可通行地图（255 表示 free）。
    coverage_width_px: 覆盖宽度像素，作为方向平滑下限。
    config: 方向场窗口与平滑参数。

  Returns:
    (angle_map, confidence_map)：angle 为无向轴角度 [0, pi)，confidence 为 0~1。
  """
  # rotated_room_map 已在房间主方向坐标系中；这里直接从可通行边界估计局部清扫主轴。
  edge_map = cv2.Canny(rotated_room_map, 50, 150, 3)
  # Canny 输出是 0/255，转成 0~1 浮点图后再做梯度，便于后续结构张量计算。
  edge_float = edge_map.astype(np.float32) / 255.0

  # Sobel 梯度描述边界法向变化，后续会旋转 90 度得到沿边界/通道方向。
  grad_x = cv2.Sobel(edge_float, cv2.CV_32F, 1, 0, ksize=3)
  grad_y = cv2.Sobel(edge_float, cv2.CV_32F, 0, 1, ksize=3)

  # 结构张量窗口必须是奇数，OpenCV GaussianBlur 才有明确中心像素。
  window_size_px = max(5, int(config.window_size_px))
  if window_size_px % 2 == 0:
    window_size_px += 1
  smooth_sigma = max(1.0, float(config.smooth_sigma))
  if coverage_width_px > 0:
    # 平滑尺度至少覆盖一部分清扫宽度，避免方向场被单像素边缘噪声主导。
    smooth_sigma = max(smooth_sigma, coverage_width_px * 0.4)

  # j_xx/j_yy/j_xy 是局部结构张量的三个分量，用于估计边界主方向和方向一致性。
  j_xx = cv2.GaussianBlur(grad_x * grad_x, (window_size_px, window_size_px), smooth_sigma)
  j_yy = cv2.GaussianBlur(grad_y * grad_y, (window_size_px, window_size_px), smooth_sigma)
  j_xy = cv2.GaussianBlur(grad_x * grad_y, (window_size_px, window_size_px), smooth_sigma)

  # edge_orientation 为边缘法向主方向；清扫通常沿边界切向运动，因此加 pi/2。
  edge_orientation = 0.5 * np.arctan2(2.0 * j_xy, j_xx - j_yy)
  travel_orientation = edge_orientation + (0.5 * math.pi)
  # 方向场是无向轴线，[0, pi) 内的 theta 和 theta+pi 表示同一清扫轴。
  travel_orientation = (travel_orientation + math.pi) % math.pi

  # coherence 越高表示局部结构方向越一致，作为方向场置信度。
  coherence_numerator = np.sqrt((j_xx - j_yy) ** 2 + 4.0 * (j_xy ** 2))
  coherence_denominator = j_xx + j_yy + 1e-6
  confidence = np.clip(coherence_numerator / coherence_denominator, 0.0, 1.0)
  # 障碍和图外区域不能提供有效方向，置信度强制清零。
  confidence *= (rotated_room_map == 255).astype(np.float32)
  return travel_orientation.astype(np.float32), confidence.astype(np.float32)


def normalize_axis_angle_map(angle_map: np.ndarray) -> np.ndarray:
  """把任意角度归一到无向轴范围 [0, pi)。

  外部来源可能出现负角或>2*pi 的值，统一归一后下游决策无需再处理周期边界。

  Args:
    angle_map: 角度图。

  Returns:
    np.ndarray: 折叠到 [0, pi) 的角度图。
  """
  # 外部输入可能包含任意角度范围，统一折叠成无向轴角 [0, pi)。
  return np.mod(np.asarray(angle_map, dtype=np.float32), np.float32(math.pi)).astype(np.float32)


def rotate_external_axis_direction_map(
  *,
  axis_direction_map: np.ndarray,
  confidence_map: np.ndarray,
  rotation_matrix: np.ndarray,
  bounding_rect: tuple[int, int, int, int],
  rotated_room_map: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
  """将外部 axis 方向场旋转到当前覆盖坐标系，并重建置信度。

  无向角直接插值会在 0/pi 边界抖动，必须先转向量再旋转，否则方向切换会发生错误。

  Args:
    axis_direction_map: 外部提供的方向图，采用无向轴口径。
    confidence_map: 与 direction_map 对齐的置信度图。
    rotation_matrix: OpenCV 仿射矩阵。
    bounding_rect: 旋转输出画布参数（x,y,w,h）。
    rotated_room_map: 旋转后的地图，用于遮罩不参与路径评分的区域。

  Returns:
    tuple[np.ndarray, np.ndarray]:
      旋转后的方向图和置信度图（均在 0~pi 与 0~1 语义下）。
  """
  # 先规范外部角度和置信度，后续所有运算都按 float32 图像处理。
  axis = normalize_axis_angle_map(axis_direction_map)
  confidence = np.clip(np.asarray(confidence_map, dtype=np.float32), 0.0, 1.0)
  if axis.shape != confidence.shape:
    raise ValueError("外部轴向方向图必须与置信度图尺寸一致")
  _, _, width, height = bounding_rect
  # 直接旋转角度图会在 0/pi 边界产生插值错误，因此先转成带置信度的向量分量。
  vector_x = np.cos(axis).astype(np.float32) * confidence
  vector_y = np.sin(axis).astype(np.float32) * confidence
  # 使用线性插值旋转向量和置信度，保留外部方向场的平滑变化。
  rotated_x = cv2.warpAffine(vector_x, rotation_matrix, (width, height), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0.0)
  rotated_y = cv2.warpAffine(vector_y, rotation_matrix, (width, height), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0.0)
  rotated_confidence = cv2.warpAffine(confidence, rotation_matrix, (width, height), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0.0)

  # warpAffine 已经移动了像素位置，但向量方向本身也要乘以旋转矩阵的线性部分。
  linear = rotation_matrix[:, :2].astype(np.float32)
  transformed_x = linear[0, 0] * rotated_x + linear[0, 1] * rotated_y
  transformed_y = linear[1, 0] * rotated_x + linear[1, 1] * rotated_y
  # magnitude 反映插值后向量长度；方向相互抵消时置信度应随之下降。
  magnitude = np.sqrt(transformed_x * transformed_x + transformed_y * transformed_y)
  # 重新从旋转后的向量恢复无向轴角。
  rotated_axis = np.mod(np.arctan2(transformed_y, transformed_x), np.float32(math.pi)).astype(np.float32)
  rotated_confidence = np.clip(rotated_confidence * np.clip(magnitude, 0.0, 1.0), 0.0, 1.0)
  # 旋转后落在障碍区域的外部方向不参与能量评分。
  rotated_confidence *= (rotated_room_map == 255).astype(np.float32)
  return rotated_axis, rotated_confidence.astype(np.float32)


def blend_axis_with_image_gradient(
  *,
  axis_map: np.ndarray,
  axis_confidence: np.ndarray,
  gradient_map: np.ndarray,
  gradient_confidence: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
  """按置信度融合外部 axis 和图像梯度方向场。

  外部轴向更可靠时优先采用外部来源；无外部信号或置信度低时回退到梯度方向，避免全空洞。

  Args:
    axis_map: 外部轴向角度图。
    axis_confidence: 外部轴向置信度。
    gradient_map: 图像梯度方向图。
    gradient_confidence: 图像梯度置信度。

  Returns:
    tuple[np.ndarray, np.ndarray]: 融合后的方向图和置信度图。
  """
  # 两个方向场都按置信度转成向量后相加，避免角度平均时跨 0/pi 出错。
  axis_weight = np.clip(axis_confidence, 0.0, 1.0).astype(np.float32)
  gradient_weight = np.clip(gradient_confidence, 0.0, 1.0).astype(np.float32)
  axis_x = np.cos(axis_map).astype(np.float32) * axis_weight
  axis_y = np.sin(axis_map).astype(np.float32) * axis_weight
  gradient_x = np.cos(gradient_map).astype(np.float32) * gradient_weight
  gradient_y = np.sin(gradient_map).astype(np.float32) * gradient_weight
  combined_x = axis_x + gradient_x
  combined_y = axis_y + gradient_y
  # 合成向量长度越大，表示外部轴向和图像梯度越一致、置信度越高。
  magnitude = np.sqrt(combined_x * combined_x + combined_y * combined_y)
  combined = np.mod(np.arctan2(combined_y, combined_x), np.float32(math.pi)).astype(np.float32)
  # 最多两个单位置信向量相加，因此除以 2 归一到 0~1。
  confidence = np.clip(magnitude / 2.0, 0.0, 1.0).astype(np.float32)
  # 外部方向缺失的位置直接回落到图像梯度方向场。
  fallback_mask = axis_weight <= 1e-6
  combined[fallback_mask] = gradient_map[fallback_mask]
  confidence[fallback_mask] = gradient_confidence[fallback_mask]
  return combined, confidence


def rotate_external_edge_label_map(
  *,
  edge_label_map: np.ndarray,
  rotation_matrix: np.ndarray,
  bounding_rect: tuple[int, int, int, int],
  rotated_room_map: np.ndarray,
) -> np.ndarray:
  """将外部 edge_label_map 旋转到当前坐标系，并仅保留可通行区域标签。

  Args:
    edge_label_map: 边语义标签图。
    rotation_matrix: OpenCV 仿射矩阵。
    bounding_rect: 旋转输出画布参数（x, y, w, h）。
    rotated_room_map: 旋转后的地图。

  Returns:
    np.ndarray: 旋转后的 edge 标签图，非可通行区域设为 -1。
  """
  # edge label 是离散语义 id，必须使用最近邻插值，不能像方向场一样线性插值。
  _, _, width, height = bounding_rect
  labels = np.asarray(edge_label_map, dtype=np.float32)
  rotated = cv2.warpAffine(
    labels,
    rotation_matrix,
    (width, height),
    flags=cv2.INTER_NEAREST,
    borderMode=cv2.BORDER_CONSTANT,
    borderValue=-1.0,
  ).astype(np.int32)
  # 旋转后不在可通行区域内的 label 统一设为 -1，表示未归属 edge。
  rotated[rotated_room_map != 255] = -1
  return rotated


def resolve_local_direction_maps(
  *,
  room_map: np.ndarray,
  rotated_room_map: np.ndarray,
  rotation_matrix: np.ndarray,
  bounding_rect: tuple[int, int, int, int],
  coverage_width_px: int,
  config: PlannerConfig,
) -> tuple[np.ndarray, np.ndarray, str]:
  """解析方向场来源并返回最终 axis map 与来源标识。

  设计上优先外部方向场，失败或禁用时回退到图像梯度估计，避免主流程因依赖外部输入中断。

  Args:
    room_map: 原始 room map。
    rotated_room_map: 旋转后 room map。
    rotation_matrix: 仿射矩阵。
    bounding_rect: 旋转输出画布参数。
    coverage_width_px: 覆盖宽度像素。
    config: planner 配置。

  Returns:
    tuple[np.ndarray, np.ndarray, str]: 方向图、置信度图与来源标记。
  """
  # 优先使用外部轴向方向场；没有外部输入时才从图像梯度估计。
  if config.external_axis_direction_map is not None:
    if config.external_axis_confidence_map is None:
      raise ValueError("提供外部轴向方向图时必须同时提供外部轴向置信度图")
    # 外部方向图和置信度图必须与原始 room_map 对齐，旋转在本函数内部完成。
    external_axis = np.asarray(config.external_axis_direction_map, dtype=np.float32)
    external_confidence = np.asarray(config.external_axis_confidence_map, dtype=np.float32)
    if external_axis.shape != room_map.shape[:2]:
      raise ValueError("外部轴向方向图必须与房间地图尺寸一致")
    if external_confidence.shape != room_map.shape[:2]:
      raise ValueError("外部轴向置信度图必须与房间地图尺寸一致")
    # 将外部轴向从原图坐标系变换到旋转后的规划坐标系。
    axis_map, confidence_map = rotate_external_axis_direction_map(
      axis_direction_map=external_axis,
      confidence_map=external_confidence,
      rotation_matrix=rotation_matrix,
      bounding_rect=bounding_rect,
      rotated_room_map=rotated_room_map,
    )
    if config.external_axis_blend_with_image_gradient:
      # 融合模式下，外部语义方向是主来源，图像梯度用于补充局部缺失或低置信区域。
      gradient_map, gradient_confidence = compute_local_direction_map(
        rotated_room_map,
        coverage_width_px,
        config.local_direction,
      )
      blended_map, blended_confidence = blend_axis_with_image_gradient(
        axis_map=axis_map,
        axis_confidence=confidence_map,
        gradient_map=gradient_map,
        gradient_confidence=gradient_confidence,
      )
      return blended_map, blended_confidence, "external_axis_blended_with_image_gradient"
    # source 字符串写入 artifact，方便诊断当前方向场来源。
    return axis_map, confidence_map, "external_axis"
  # 默认路径：完全由旋转房间图像边界估计局部清扫方向。
  direction_map, confidence_map = compute_local_direction_map(
    rotated_room_map,
    coverage_width_px,
    config.local_direction,
  )
  return direction_map, confidence_map, "image_gradient"
