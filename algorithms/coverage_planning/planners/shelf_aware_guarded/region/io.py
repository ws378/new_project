"""区域配置文件读写。"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Sequence

from .masks import Point


def save_region_file(
  region_path: str,
  map_yaml: str,
  image_path: str,
  polygon_points: Sequence[Point],
  start_pixel: Point | None,
  planner_params: dict[str, Any],
  note: str = "",
) -> None:
  """将区域定义与配套元信息写入 json。
  
  写入前统一标准化字段与时间戳，便于历史区划文件按内容差异复核；写入失败由上层按任务策略处理。
  
  Args:
      region_path: 区域文件输出路径。
      map_yaml: map_yaml 源文件路径。
      image_path: 地图图像路径。
      polygon_points: 区域轮廓像素点。
      start_pixel: 起始点，可为空。
      planner_params: planner 配置快照。
      note: 额外注记。
  """
  path = Path(region_path)
  path.parent.mkdir(parents=True, exist_ok=True)
  now = datetime.now().isoformat(timespec="seconds")
  payload = {
    "version": 1,
    "map_yaml": str(Path(map_yaml)),
    "image_path": str(Path(image_path)),
    "polygon_points": [[int(x), int(y)] for x, y in polygon_points],
    "start_pixel": [int(start_pixel[0]), int(start_pixel[1])] if start_pixel is not None else None,
    "planner_params": planner_params,
    "created_at": now,
    "updated_at": now,
    "note": note,
  }
  with path.open("w", encoding="utf-8") as handle:
    json.dump(payload, handle, ensure_ascii=False, indent=2)


def load_region_file(region_path: str) -> dict[str, Any]:
  """读取区域 json 并返回原始 payload。
  
  仅反序列化返回，不做改写，避免区域文件作为事实源被二次映射污染。
  
  Args:
      region_path: 区域文件路径。
      
  Returns:
      dict: 文件中的原始 payload。
  """
  path = Path(region_path)
  with path.open("r", encoding="utf-8") as handle:
    payload = json.load(handle)
  return payload


def region_matches_map(region_payload: dict[str, Any], map_yaml: str) -> bool:
  """判断区域文件是否对应当前地图。
  
  同名但路径不同也可视作同一模板，降低跨目录重放误判。
  
  Args:
      region_payload: 读取到的区域 payload。
      map_yaml: 当前地图 yaml 路径。
      
  Returns:
      bool: 匹配则 True。
  """
  stored_map_yaml = region_payload.get("map_yaml")
  if not stored_map_yaml:
    # 配置文件丢失 map_yaml 则无法建立同源关系，直接判定不匹配。
    return False
  stored_path = Path(stored_map_yaml)
  current_path = Path(map_yaml)
  if str(stored_path.resolve()) == str(current_path.resolve()):
    # 同一路径可直接复用，名称不敏感的同源兜底才是兼容层语义。
    return True
  # 物理路径不一致时，只要文件名一致就视为同一地图模板，降低目录迁移导致的误判。
  return stored_path.name == current_path.name


def save_config_file(config_path: str, planner_params: dict[str, Any]) -> None:
  """持久化规划参数快照。
  
  仅持久化参数配置，不包含运行时临时状态，保障可回放链路可复现。
  
  Args:
      config_path: 配置文件路径。
      planner_params: 需要持久化的参数。
  """
  path = Path(config_path)
  path.parent.mkdir(parents=True, exist_ok=True)
  with path.open("w", encoding="utf-8") as handle:
    json.dump(planner_params, handle, ensure_ascii=False, indent=2)


def load_config_file(config_path: str) -> dict[str, Any]:
  """读取 planner 参数快照。
  
  返回原始字典供上层兼容处理，不在工具层进行兼容性转换。
  
  Args:
      config_path: 配置文件路径。
      
  Returns:
      dict: 原始参数字典。
  """
  path = Path(config_path)
  with path.open("r", encoding="utf-8") as handle:
    return json.load(handle)
