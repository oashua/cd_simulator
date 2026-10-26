"""根据目标机器规格选择网格规模档位。

档位系数为工程经验值（背景网格尺寸按车长比例取），未经风洞标定，
首次实机运行时应结合计算时长与 Cd 稳定性微调。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Tier:
    name: str
    base_size_per_length: float  # 背景网格尺寸 = 该系数 × 车长
    surface_min: int             # snappy refinementSurfaces 最小细化层级
    surface_max: int             # snappy refinementSurfaces 最大细化层级
    nearbox_level: int           # 车周围 refinementBox 细化层级
    iterations: int              # simpleFoam 迭代步数上限


TIERS: tuple[Tier, ...] = (
    Tier("low",  1 / 28, 2, 2, 1, 1500),
    Tier("mid",  1 / 40, 2, 3, 2, 2500),
    Tier("high", 1 / 56, 3, 3, 2, 3500),
)


def select_tier(cpu_count: int, mem_gb: float) -> Tier:
    """按内存（硬约束）与核数选档。

    snappyHexMesh 边界层阶段的内存峰值（约 1-2 KB/cell）才是瓶颈，
    核多内存小的机器（如 WSL 默认分配）不能选高档，否则 OOM：
    mem_gb < 32            -> low
    mem_gb < 128 或核数<=32 -> mid
    其余                   -> high
    """
    if cpu_count <= 0 or mem_gb <= 0:
        raise ValueError(f"cpu_count 和 mem_gb 必须为正数，收到 {cpu_count}, {mem_gb}")
    if mem_gb < 32:
        return TIERS[0]
    if mem_gb < 128 or cpu_count <= 32:
        return TIERS[1]
    return TIERS[2]
