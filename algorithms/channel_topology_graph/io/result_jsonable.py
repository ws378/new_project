"""结果写盘用 JSON 归一辅助。"""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any

import numpy as np


def to_jsonable(value: Any) -> Any:
    """把结果对象里的调试字段转成可写 json 的形式。"""

    # dataclass 先展开成 dict，再递归归一，避免下层分支重复处理对象字段。
    if is_dataclass(value):
        return to_jsonable(asdict(value))
    if is_json_scalar(value):
        return value
    if isinstance(value, np.ndarray):
        return jsonify_ndarray(value)
    if isinstance(value, dict):
        return jsonify_mapping(value)
    if isinstance(value, (list, tuple)):
        return jsonify_sequence(value)
    # 对未知对象退化成字符串，只求“可写盘、可读”，不在这里发明新协议。
    # 这里的目标是稳定写盘，而不是完整保真序列化任意 Python 对象。
    return str(value)


def is_json_scalar(value: Any) -> bool:
    """判断值是否已经是天然 JSON 标量。"""

    # 标量和 None 直接保留，避免过度包装影响可读性。
    # 这类值已经天然满足 JSON 语义，不需要再做结构改写。
    return bool(isinstance(value, (str, int, float, bool)) or value is None)


def jsonify_ndarray(value: np.ndarray) -> dict[str, Any]:
    """把 ndarray 投影成紧凑的 JSON 友好摘要。"""

    # 调试数组不直接整块写入 summary，避免文件臃肿且难以阅读。
    return {
        "type": "ndarray",
        "shape": list(value.shape),
        "dtype": str(value.dtype),
        "nonzero_count": int(np.count_nonzero(value)),
    }


def jsonify_mapping(value: dict[Any, Any]) -> dict[str, Any]:
    """递归 JSON 化映射对象。"""

    # dict 统一递归展开，保证嵌套调试字段也能稳定写盘。
    return {str(key): to_jsonable(item) for key, item in value.items()}


def jsonify_sequence(value: list[Any] | tuple[Any, ...]) -> list[Any]:
    """递归 JSON 化序列对象。"""

    # list/tuple 统一递归展开，保证嵌套调试字段也能稳定写盘。
    return [to_jsonable(item) for item in value]
