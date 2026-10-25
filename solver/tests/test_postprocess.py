import json

import numpy as np
import pytest

from windtunnel.postprocess import (
    _chain_lines,
    _as_point_data,
    diverging_colormap,
    export_slice_json,
    export_streamlines_json,
)

pytest.importorskip("meshio")


def test_colormap_endpoints():
    v = np.array([-1.5, 1.0, -0.25, 0.5])
    rgb = diverging_colormap(v, -1.5, 1.0)
    assert rgb[0].tolist() == [59, 76, 192]    # vmin -> 蓝
    assert rgb[1].tolist() == [180, 4, 38]     # vmax -> 红
    assert rgb[2].tolist() == [247, 247, 247]  # t=0.5 -> 白


def test_chain_lines_two_polylines():
    # 0-1-2 一条链，3-4 一条链
    pts = np.array([[0, 0, 0], [1, 0, 0], [2, 0, 0], [5, 5, 5], [6, 5, 5]], float)
    seg = np.array([[0, 1], [1, 2], [3, 4]])
    chains = _chain_lines(pts, seg)
    assert sorted(tuple(c) for c in chains) == [(0, 1, 2), (3, 4)]


def test_chain_lines_order_independent():
    pts = np.array([[0, 0, 0], [1, 0, 0], [2, 0, 0]], float)
    seg = np.array([[2, 1], [0, 1]])  # 打乱方向
    chains = _chain_lines(pts, seg)
    assert sorted(tuple(c) for c in chains) == [(0, 1, 2)]


def _write_vtk(tmp_path, m):
    import meshio

    path = tmp_path / "slice.vtk"
    meshio.write(path, m, binary=False)
    return path


def test_slice_json_cell_data_averaged(tmp_path):
    import meshio

    points = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [1, 1, 0]], float)
    faces = np.array([[0, 1, 2], [1, 3, 2]])
    cell_p = np.array([100.0, 300.0])  # 每三角一个压力值
    m = meshio.Mesh(
        points=points,
        cells=[("triangle", faces)],
        cell_data={"p": [cell_p]},
    )
    path = _write_vtk(tmp_path, m)
    out = tmp_path / "slice.json"
    export_slice_json(path, u_inf=30.0, out=out)
    data = json.loads(out.read_text())
    assert len(data["points"]) == 4 and len(data["faces"]) == 2
    # 顶点 0 只关联 tri0：Cp = 100/(0.5*1.2*900)；顶点 3 只关联 tri1
    denom = 0.5 * 1.2 * 900.0
    assert data["cp"][0] == pytest.approx(100.0 / denom, abs=1e-3)
    assert data["cp"][3] == pytest.approx(300.0 / denom, abs=1e-3)


def test_streamlines_json(tmp_path):
    import meshio

    points = np.array(
        [[0, 0, 0], [1, 0, 0], [2, 0, 0], [5, 5, 5], [6, 5, 5]], float
    )
    speed = np.array([10.0, 20.0, 30.0, 5.0, 6.0])
    m = meshio.Mesh(
        points=points,
        cells=[("line", np.array([[0, 1], [1, 2], [3, 4]]))],
        point_data={"U": np.column_stack([speed, np.zeros(5), np.zeros(5)])},
    )
    path = _write_vtk(tmp_path, m)
    out = tmp_path / "streamlines.json"
    export_streamlines_json(path, out)
    data = json.loads(out.read_text())
    assert len(data["lines"]) == 2
    assert data["lines"][0]["speed"] == [10.0, 20.0, 30.0]


def test_as_point_data_missing_field(tmp_path):
    import meshio

    m = meshio.Mesh(
        points=np.zeros((3, 3)), cells=[("triangle", np.array([[0, 1, 2]]))]
    )
    assert _as_point_data(m, "nope") is None
