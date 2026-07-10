"""CoveragePlanning 统一尺度换算 helper。"""

from __future__ import annotations

from typing import Iterable


def px_to_m(value_px: float, resolution_m_per_px: float) -> float:
    """把像素尺度标量统一换算成米。"""

    resolution = float(resolution_m_per_px)
    if resolution <= 0.0:
        raise ValueError('resolution_m_per_px must be positive')
    return float(value_px) * resolution



def m_to_px(value_m: float, resolution_m_per_px: float) -> float:
    """把米尺度标量统一换算成像素。"""

    resolution = float(resolution_m_per_px)
    if resolution <= 0.0:
        raise ValueError('resolution_m_per_px must be positive')
    return float(value_m) / resolution



def sequence_px_to_m(values_px: Iterable[float], resolution_m_per_px: float) -> tuple[float, ...]:
    """把像素序列统一换算成米序列。"""

    resolution = float(resolution_m_per_px)
    if resolution <= 0.0:
        raise ValueError('resolution_m_per_px must be positive')
    return tuple(float(value) * resolution for value in values_px)


__all__ = ('px_to_m', 'm_to_px', 'sequence_px_to_m')
