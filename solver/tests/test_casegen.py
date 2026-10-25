from pathlib import Path

import pytest

from windtunnel.casegen import CaseParams, render_case
from windtunnel.geometry import GeometryMeta

P = Path(__file__).resolve().parent.parent / "templates" / "basecase"


def fake_meta(tmp_path: Path) -> GeometryMeta:
    stl = tmp_path / "cleaned.stl"
    stl.write_bytes(b"")  # 渲染只复制路径，不需要真实网格
    return GeometryMeta(
        length=4.5, width=1.9, height=1.4,
        frontal_area=2.2, center=(0.0, 0.0, 0.7), path=stl,
    )


PARAMS = CaseParams(
    u_inf=33.3, cell_size=0.1125, n_procs=16, iterations=2500,
    surf_min=2, surf_max=3, nearbox_level=2,
)


def test_render_case_completeness(tmp_path):
    meta = fake_meta(tmp_path)
    case = tmp_path / "case"
    render_case(P, meta, case, PARAMS)

    # 关键文件齐备
    for f in ["0/U", "0/p", "0/k", "0/omega", "0/nut",
              "constant/physicalProperties", "constant/momentumTransport",
              "constant/triSurface/car.stl",
              "system/blockMeshDict", "system/snappyHexMeshDict",
              "system/controlDict", "system/fvSolution", "system/decomposeParDict",
              "system/surfaces", "system/streamlines", "Allrun"]:
        assert (case / f).exists(), f"缺少 {f}"

    # 渲染后不应残留任何 ${VAR}
    for f in case.rglob("*"):
        if f.is_file() and f.name != "Allrun":
            assert "${" not in f.read_text(), f"{f} 仍有未替换变量"


def test_render_case_values(tmp_path):
    meta = fake_meta(tmp_path)
    case = tmp_path / "case"
    render_case(P, meta, case, PARAMS)

    bm = (case / "system" / "blockMeshDict").read_text()
    assert "xmin -9.000;" in bm     # -2L
    assert "xmax 22.500;" in bm     # +5L
    # OpenFOAM 小写变量引用未被 Template 吞掉
    assert "$xmin $ymin $zmin" in bm

    cd = (case / "system" / "controlDict").read_text()
    assert "endTime         2500;" in cd
    assert "magUInf         33.30;" in cd
    assert "Aref            2.2000;" in cd

    assert (case / "Allrun").stat().st_mode & 0o755


def test_render_case_refuses_overwrite(tmp_path):
    meta = fake_meta(tmp_path)
    case = tmp_path / "case"
    render_case(P, meta, case, PARAMS)
    with pytest.raises(FileExistsError):
        render_case(P, meta, case, PARAMS)
