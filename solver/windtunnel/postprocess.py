"""OpenFOAM function object 输出 (VTK) -> 前端可视化数据 (glTF/JSON)。"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np

RHO_INF = 1.2  # 与 controlDict forceCoeffs 保持一致


# ---------------------------------------------------------------- 工具函数

def diverging_colormap(v: np.ndarray, vmin: float, vmax: float) -> np.ndarray:
    """三段线性 RGB (N,3) uint8：蓝 -> 白 -> 红，v 先 clip 到 [vmin, vmax]。"""
    stops = np.array(
        [[59, 76, 192], [247, 247, 247], [180, 4, 38]], dtype=np.float64
    )
    t = np.clip((np.asarray(v, dtype=np.float64) - vmin) / (vmax - vmin), 0.0, 1.0)
    idx = np.clip((t * 2.0).astype(int), 0, 1)  # 0: 蓝白段, 1: 白红段
    frac = t * 2.0 - idx
    rgb = stops[idx] * (1.0 - frac[:, None]) + stops[idx + 1] * frac[:, None]
    return rgb.astype(np.uint8)


def _triangles(mesh) -> np.ndarray:
    """取 meshio 网格的三角面片 block。"""
    for block in mesh.cells:
        if block.type == "triangle":
            return np.asarray(block.data)
    raise ValueError(f"VTK 中无 triangle cells: {[b.type for b in mesh.cells]}")


def _as_point_data(mesh, name: str) -> np.ndarray | None:
    """按名字取场；point data 直取，cell data 按关联次数平均到顶点。"""
    if name in mesh.point_data:
        return np.asarray(mesh.point_data[name])
    blocks = [
        (np.asarray(b.data), np.asarray(d[name]))
        for b, d in zip(mesh.cells, mesh.cell_data.values())
        if isinstance(d, dict) and name in d
    ]
    if not blocks:
        return None
    acc = np.zeros((len(mesh.points),) + np.shape(blocks[0][1])[1:])
    cnt = np.zeros(len(mesh.points))
    for idx, vals in blocks:
        np.add.at(acc, idx, vals)
        np.add.at(cnt, idx, 1.0)
    cnt = np.maximum(cnt, 1.0)
    return acc / cnt[:, None] if acc.ndim > 1 else acc / cnt


# ---------------------------------------------------------------- 导出

def export_surface_glb(vtk_path: Path, u_inf: float, out_glb: Path) -> None:
    """车身表面 Cp 顶点色 glTF。"""
    import meshio
    import trimesh

    m = meshio.read(vtk_path)
    faces = _triangles(m)
    p = _as_point_data(m, "p")
    if p is None:
        raise ValueError(f"VTK 缺少 p 场: {vtk_path}")
    cp = np.ravel(p) / (0.5 * RHO_INF * u_inf * u_inf)
    rgba = np.column_stack(
        [diverging_colormap(cp, -1.5, 1.0), np.full(len(cp), 255, np.uint8)]
    )
    tm = trimesh.Trimesh(vertices=np.asarray(m.points), faces=faces, process=False)
    tm.visual.vertex_colors = rgba
    out_glb.parent.mkdir(parents=True, exist_ok=True)
    tm.export(out_glb)


def _chain_lines(points: np.ndarray, seg: np.ndarray) -> list[list[int]]:
    """(M,2) 段索引表 -> 折线索引链（端点重合即连接）。"""
    from collections import defaultdict, deque

    ep: dict[int, list[int]] = defaultdict(list)
    for i, (a, b) in enumerate(seg):
        ep[int(a)].append(i)
        ep[int(b)].append(i)
    used = np.zeros(len(seg), bool)
    chains: list[list[int]] = []
    for start in range(len(seg)):
        if used[start]:
            continue
        used[start] = True
        chain = deque(int(x) for x in seg[start])
        for direction in (1, 0):  # 先向尾延伸，再向头延伸
            while True:
                tip = chain[-1] if direction else chain[0]
                nxt = next((si for si in ep[tip] if not used[si]), None)
                if nxt is None:
                    break
                used[nxt] = True
                a, b = (int(x) for x in seg[nxt])
                other = b if tip == a else a
                if direction:
                    chain.append(other)
                else:
                    chain.appendleft(other)
        chains.append(list(chain))
    return chains


def export_streamlines_json(vtk_path: Path, out: Path) -> None:
    """流线 polydata -> JSON 折线列表（含速度幅值）。"""
    import meshio

    m = meshio.read(vtk_path)
    pts = np.asarray(m.points)
    u = _as_point_data(m, "U")
    speed = (
        np.linalg.norm(np.asarray(u).reshape(len(pts), -1)[:, :3], axis=1)
        if u is not None
        else np.zeros(len(pts))
    )
    lines_out = []
    for block in m.cells:
        if block.type == "line":
            for chain in _chain_lines(pts, np.asarray(block.data)):
                idx = np.asarray(chain)
                lines_out.append(
                    {
                        "points": np.round(pts[idx], 4).tolist(),
                        "speed": np.round(speed[idx], 3).tolist(),
                    }
                )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"lines": lines_out}))


def export_slice_json(vtk_path: Path, u_inf: float, out: Path) -> None:
    """切片 polydata -> JSON（顶点 Cp 与速度幅值）。"""
    import meshio

    m = meshio.read(vtk_path)
    faces = _triangles(m)
    pts = np.asarray(m.points)
    p = _as_point_data(m, "p")
    u = _as_point_data(m, "U")
    cp = (
        np.ravel(p) / (0.5 * RHO_INF * u_inf * u_inf)
        if p is not None
        else np.zeros(len(pts))
    )
    vel = (
        np.linalg.norm(np.asarray(u).reshape(len(pts), -1)[:, :3], axis=1)
        if u is not None
        else np.zeros(len(pts))
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(
            {
                "points": np.round(pts, 4).tolist(),
                "faces": faces.tolist(),
                "cp": np.round(cp, 4).tolist(),
                "vel_mag": np.round(vel, 3).tolist(),
            }
        )
    )


# ---------------------------------------------------------------- 汇总

def collect(case_dir: Path, u_inf: float, out_dir: Path) -> dict:
    """定位三个 VTK 输出并导出 viewer 文件；解析日志生成 results dict。"""
    from .residuals import has_converged, is_diverged, parse_log, extract_final_cd

    case_dir = Path(case_dir)
    out_dir = Path(out_dir)
    viewer_dir = out_dir / "viewer"
    viewer_dir.mkdir(parents=True, exist_ok=True)

    def latest(patterns: list[str]) -> Path:
        hits = sorted(
            p for pat in patterns for p in case_dir.glob(f"postProcessing/**/{pat}")
        )
        if not hits:
            raise FileNotFoundError(f"找不到采样输出: {patterns} (case: {case_dir})")
        return hits[-1]

    export_surface_glb(
        latest(["car*.vtk", "*car*.vtk"]), u_inf, viewer_dir / "surface.glb"
    )
    export_slice_json(latest(["slice*.vtk"]), u_inf, viewer_dir / "slice.json")
    export_streamlines_json(
        latest(["particleTracks*.vtk", "*Tracks*.vtk"]), viewer_dir / "streamlines.json"
    )

    log_text = (case_dir / "log.simpleFoam").read_text(errors="replace")
    hist = parse_log(log_text)
    final = extract_final_cd(log_text)
    if final is None:
        raise RuntimeError("log.simpleFoam 中无 forceCoeffs 输出，无法计算 Cd")

    results = {
        "cd": final[0],
        "cd_f": final[1],
        "cd_r": final[2],
        "cl": hist.cl[-1] if hist.cl else math.nan,
        "iterations": hist.iters[-1] if hist.iters else 0,
        "converged": has_converged(hist) and not is_diverged(hist),
        "history": {
            "iters": hist.iters,
            "u": hist.u,
            "p": hist.p,
            "cd": hist.cd,
            "cl": hist.cl,
        },
    }
    (out_dir / "results.json").write_text(json.dumps(results, indent=2))
    return results
