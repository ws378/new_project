"""全链 baseline 工具的公共归一化辅助。"""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np


def write_json(path: str | Path, payload: Any) -> None:
    """把 payload 以稳定格式写出为 JSON。"""

    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def load_json(path: str | Path) -> Any:
    """读取 JSON 文件。"""

    return json.loads(Path(path).read_text(encoding="utf-8"))


def normalize_case_spec(
    spec: Any,
    *,
    resolved_pipeline_config: dict[str, Any],
) -> dict[str, Any]:
    """把固定 case 规格转成稳定 JSON。"""

    return {
        "case_name": str(spec.case_name),
        "case_dir": str(spec.case_dir),
        "geometry_config": to_jsonable(resolved_pipeline_config["geometry_preparation"]),
        "junction_config": to_jsonable(resolved_pipeline_config["junction_rebuild"]),
        "topology_config": to_jsonable(resolved_pipeline_config["topology_graph_build"]),
        "coverage_config": to_jsonable(resolved_pipeline_config["coverage_planning"]),
        "runtime_config": to_jsonable(resolved_pipeline_config["runtime"]),
    }


def array_signature(array: Any) -> dict[str, Any]:
    """把数组压成稳定签名，避免 baseline 被整块矩阵撑大。"""

    view = np.asarray(array)
    return {
        "shape": [int(v) for v in view.shape],
        "dtype": str(view.dtype),
        "nonzero_count": int(np.count_nonzero(view)),
        "sha256": hashlib.sha256(view.tobytes(order="C")).hexdigest(),
    }


def mask_signature(mask: Any) -> dict[str, Any]:
    """把二值掩膜压成签名，并显式保留像素值空间。"""

    view = np.asarray(mask)
    signature = array_signature(view)
    signature["unique_values"] = [int(v) for v in np.unique(view)]
    return signature


def normalize_point(point_rc: Any) -> list[float]:
    """把 `(row, col)` 点转成稳定 JSON。"""

    point = tuple(point_rc or ())
    return [float(point[0]), float(point[1])]


def normalize_index_point(point_rc: Any) -> list[int]:
    """把整型 `(row, col)` 点转成稳定 JSON。"""

    point = tuple(point_rc or ())
    return [int(point[0]), int(point[1])]


def normalize_path(path_rc: Any) -> list[list[float]]:
    """把路径点列转成稳定 JSON。"""

    return [normalize_point(point) for point in tuple(path_rc or ())]


def to_jsonable(value: Any) -> Any:
    """把调试/校验/元信息转成可写 JSON 的稳定结构。"""

    if is_dataclass(value):
        return to_jsonable(asdict(value))
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, np.ndarray):
        return array_signature(value)
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return float(value)
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, dict):
        return {str(key): to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_jsonable(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)
