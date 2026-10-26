"""STL/OBJ 几何预处理：加载、修复、正则化、迎风面积估算。"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import trimesh

logger = logging.getLogger(__name__)


@dataclass
class GeometryMeta:
    length: float  # 车长 m（正则化后包围盒）
    width: float
    height: float
    frontal_area: float  # 迎风面积 m²（y-z 平面投影）
    center: tuple[float, float, float]  # 包围盒中心（x=y=0, z=height/2）
    path: Path  # cleaned.stl 输出路径


def _repair(mesh: trimesh.Trimesh) -> trimesh.Trimesh:
    """修复法向、补洞；仍不水密时用 pymeshfix 兜底，失败仅警告。"""
    mesh = mesh.copy()
    trimesh.repair.fix_normals(mesh)
    trimesh.repair.fill_holes(mesh)
    if mesh.is_watertight:
        return mesh
    logger.warning("网格非水密，尝试 pymeshfix 修复")
    try:
        import pymeshfix

        fixed = pymeshfix.MeshFix(mesh.vertices, mesh.faces)
        fixed.repair()
        mesh = trimesh.Trimesh(**fixed.mesh_data)
        trimesh.repair.fix_normals(mesh)
    except ImportError:
        logger.warning("pymeshfix 未安装，跳过兜底修复（snappyHexMesh 通常仍可处理）")
    except Exception as exc:  # noqa: BLE001 - 修复失败不应阻塞管线
        logger.warning("pymeshfix 修复失败（%s），继续使用原网格", exc)
    return mesh


def _frontal_area(mesh: trimesh.Trimesh, length: float, divisions: int = 60) -> float:
    """三角面片投影到 y-z 平面栅格化，格心落入任一投影三角形即计入。

    比 voxelized().sparse_indices 稳定：体素化在网格相位不利时每维外扩一圈
    （误差可达 2*pitch/尺寸），栅格化格心严格落在投影内部，误差仅 ~1/divisions。
    """
    pitch = length / divisions
    tri = np.asarray(mesh.vertices, dtype=float)[np.asarray(mesh.faces)][:, :, 1:]
    if tri.size == 0:
        return 0.0
    # 全局格点相位偏移 0.25*pitch，降低格心恰好压在投影边界上的概率
    origin = np.floor(tri.reshape(-1, 2).min(axis=0) / pitch) * pitch + 0.25 * pitch

    cells: set[tuple[int, int]] = set()
    for t in tri:
        cross = (t[1, 0] - t[0, 0]) * (t[2, 1] - t[0, 1]) - (t[1, 1] - t[0, 1]) * (
            t[2, 0] - t[0, 0]
        )
        if abs(cross) < 1e-18:  # 退化面片（零投影面积）跳过
            continue
        lo = np.floor((t.min(axis=0) - origin) / pitch).astype(int)
        hi = np.floor((t.max(axis=0) - origin) / pitch).astype(int)
        yy, zz = np.meshgrid(
            np.arange(lo[0], hi[0] + 1), np.arange(lo[1], hi[1] + 1)
        )
        py = origin[0] + yy.ravel() * pitch
        pz = origin[1] + zz.ravel() * pitch

        def side(px: np.ndarray, pz_: np.ndarray, a: np.ndarray, b: np.ndarray):
            return (px - a[0]) * (b[1] - a[1]) - (pz_ - a[1]) * (b[0] - a[0])

        d1, d2, d3 = side(py, pz, t[0], t[1]), side(py, pz, t[1], t[2]), side(
            py, pz, t[2], t[0]
        )
        inside = ((d1 >= 0) & (d2 >= 0) & (d3 >= 0)) | (
            (d1 <= 0) & (d2 <= 0) & (d3 <= 0)
        )
        cells.update(zip(yy.ravel()[inside].tolist(), zz.ravel()[inside].tolist()))
    return float(len(cells)) * pitch * pitch


def prepare_geometry(
    src: Path, out_dir: Path, scale: float = 1.0, voxel_divisions: int = 60
) -> GeometryMeta:
    """加载 STL/OBJ -> 修复 -> 缩放 -> 落地居中 -> 估算迎风面积 -> 导出 cleaned.stl。"""
    src = Path(src)
    out_dir = Path(out_dir)
    if not src.is_file():
        raise ValueError(f"模型文件不存在: {src}")
    if scale <= 0:
        raise ValueError(f"scale 必须为正数，收到 {scale}")

    mesh = trimesh.load(src, force="mesh", process=False)
    if len(mesh.faces) == 0:
        raise ValueError(f"模型不含三角面片: {src}")

    mesh = _repair(mesh)
    mesh.apply_scale(scale)

    # 正则化：min_z 落地，x/y 居中
    mesh.apply_translation([-mesh.bounds[:, 0].mean(), -mesh.bounds[:, 1].mean(), 0.0])
    mesh.apply_translation([0.0, 0.0, -mesh.bounds[0, 2]])

    ext = mesh.extents  # (L, W, H)
    if min(ext) <= 0:
        raise ValueError(f"模型包围盒非法: {ext}")
    length = float(ext[0])

    area = _frontal_area(mesh, length, divisions=voxel_divisions)

    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "cleaned.stl"
    mesh.export(out_path)

    center = (0.0, 0.0, float(ext[2]) / 2.0)
    return GeometryMeta(
        length=length,
        width=float(ext[1]),
        height=float(ext[2]),
        frontal_area=area,
        center=center,
        path=out_path,
    )
