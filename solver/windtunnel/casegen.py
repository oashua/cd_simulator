"""将 OpenFOAM case 模板渲染为具体 case 目录。"""

from __future__ import annotations

import math
import shutil
import string
from dataclasses import dataclass
from pathlib import Path

from .geometry import GeometryMeta

# 模板中全部 ${VAR}（与 templates/basecase 内 grep 结果保持一致）
_REQUIRED_VARS = (
    "AREF", "CAR_STL", "COFR_X", "COFR_Z", "END_TIME", "K_INF", "LOC_IN_MESH",
    "LREF", "NEARBOX", "NEARBOX_MAX", "NEARBOX_MIN", "NPROC", "NX", "NY", "NZ",
    "OMEGA_INF", "RELAX_P", "RELAX_TURB", "RELAX_U", "SEED_END", "SEED_START",
    "SLICE_POINT", "SURF_MAX", "SURF_MIN", "U_INF", "XMAX", "XMIN", "YMAX",
    "YMIN", "ZMAX", "ZMIN",
)


@dataclass
class CaseParams:
    u_inf: float                       # 来流风速 m/s
    cell_size: float                   # 背景网格尺寸 m
    n_procs: int
    iterations: int
    surf_min: int                      # refinementSurfaces 最小层级
    surf_max: int                      # refinementSurfaces 最大层级
    nearbox_level: int                 # 车周区域细化层级
    relax: tuple[float, float, float] = (0.5, 0.55, 0.55)  # p, U, k/omega


def _vec(v: tuple[float, float, float]) -> str:
    return f"({v[0]:.4f} {v[1]:.4f} {v[2]:.4f})"


def render_case(
    template_dir: Path, meta: GeometryMeta, case_dir: Path, p: CaseParams
) -> None:
    """渲染模板 -> case_dir，并复制车身 STL 为 constant/triSurface/car.stl。"""
    if case_dir.exists():
        raise FileExistsError(f"case 目录已存在，不覆盖: {case_dir}")

    length, width, height = meta.length, meta.width, meta.height
    cell = p.cell_size

    # 风洞域：入口前方 2L，出口后方 5L，两侧各 2.5W，顶部 4H（行业惯例 margin）
    x_min, x_max = -2.0 * length, 5.0 * length
    y_min, y_max = -2.5 * width, 2.5 * width
    z_min, z_max = 0.0, 4.0 * height

    nx = max(8, math.ceil((x_max - x_min) / cell))
    ny = max(8, math.ceil((y_max - y_min) / cell))
    nz = max(8, math.ceil((z_max - z_min) / cell))

    nearbox_min = (-0.75 * length, -1.0 * width, 0.05)
    nearbox_max = (1.75 * length, 1.0 * width, 2.2 * height)

    cofr_x, cofr_z = 0.0, height / 2.0
    # locationInMesh 必须在流体域内（车外）：取上游高处；
    # 若落在车体内，snappy subsetting 只保留车身附近网格，外域与 inlet/outlet 等 patch 全部丢失
    loc_in_mesh = (-1.5 * length, 0.0, 3.0 * height)
    slice_point = (0.0, 0.0, cofr_z)
    seed_pos = (-1.5 * length, 0.0, 0.5 * height)
    seed_length = 0.8 * width

    # 入流湍流：湍流强度 0.5%，长度尺度 0.1L（kOmegaSST 标准入口公式）
    k_inf = 1.5 * (0.005 * p.u_inf) ** 2
    omega_inf = math.sqrt(k_inf) / (0.09 ** 0.25 * 0.1 * length)

    values = {
        "U_INF": f"{p.u_inf:.2f}",
        "XMIN": f"{x_min:.3f}", "XMAX": f"{x_max:.3f}",
        "YMIN": f"{y_min:.3f}", "YMAX": f"{y_max:.3f}",
        "ZMIN": f"{z_min:.3f}", "ZMAX": f"{z_max:.3f}",
        "NX": str(nx), "NY": str(ny), "NZ": str(nz),
        "CELL": f"{cell:.4f}",
        # OpenFOAM dict key 不支持含 / 的路径（会被当字典路径拆开），只写文件名，
        # triSurfaceMesh / surfaceFeatureExtract 自动在 constant/triSurface/ 下搜索
        "CAR_STL": "car.stl",
        "LOC_IN_MESH": _vec(loc_in_mesh),
        "NEARBOX_MIN": _vec(nearbox_min),
        "NEARBOX_MAX": _vec(nearbox_max),
        "NEARBOX": str(p.nearbox_level),
        "SURF_MIN": str(p.surf_min), "SURF_MAX": str(p.surf_max),
        "COFR_X": f"{cofr_x:.3f}", "COFR_Z": f"{cofr_z:.3f}",
        "SLICE_POINT": _vec(slice_point),
        "SEED_START": _vec(
            (seed_pos[0], seed_pos[1] - seed_length / 2, seed_pos[2])
        ),
        "SEED_END": _vec(
            (seed_pos[0], seed_pos[1] + seed_length / 2, seed_pos[2])
        ),
        "K_INF": f"{k_inf:.6e}",
        "OMEGA_INF": f"{omega_inf:.6e}",
        "AREF": f"{meta.frontal_area:.4f}",
        "LREF": f"{length:.3f}",
        "NPROC": str(p.n_procs),
        "END_TIME": str(p.iterations),
        "RELAX_P": str(p.relax[0]),
        "RELAX_U": str(p.relax[1]),
        "RELAX_TURB": str(p.relax[2]),
    }
    missing = [k for k in _REQUIRED_VARS if k not in values]
    if missing:
        raise RuntimeError(f"casegen 缺少模板变量: {missing}")

    tpl = string.Template
    for src in sorted(Path(template_dir).rglob("*")):
        if src.is_dir():
            continue
        rel = src.relative_to(template_dir)
        dst = case_dir / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.name == "Allrun":
            shutil.copy(src, dst)  # bash 脚本原样复制，避免 $var 被 Template 吞掉
            dst.chmod(0o755)
        else:
            dst.write_text(tpl(src.read_text()).substitute(values))

    (case_dir / "constant" / "triSurface").mkdir(parents=True, exist_ok=True)
    shutil.copy(meta.path, case_dir / "constant" / "triSurface" / "car.stl")
