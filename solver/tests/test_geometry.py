import pytest
import trimesh

from windtunnel.geometry import _frontal_area, prepare_geometry


def _box_on_ground(a=4.0, b=1.8, c=1.2):
    m = trimesh.creation.box(extents=(a, b, c))
    # 先悬空放置，测试 prepare_geometry 是否会自动落地
    m.apply_translation([10.0, -5.0, c / 2 + 0.3])
    return m


def test_prepare_normalizes_position(tmp_path):
    src = tmp_path / "car.stl"
    _box_on_ground().export(src)
    meta = prepare_geometry(src, tmp_path / "out")
    assert meta.length == pytest.approx(4.0)
    assert meta.width == pytest.approx(1.8)
    assert meta.height == pytest.approx(1.2)
    assert meta.center == pytest.approx((0.0, 0.0, 0.6))
    loaded = trimesh.load(meta.path, force="mesh", process=False)
    assert loaded.bounds[0][2] == pytest.approx(0.0)  # 落地
    assert loaded.bounds[:, 0].mean() == pytest.approx(0.0)  # x 居中


def test_prepare_applies_scale(tmp_path):
    src = tmp_path / "car.stl"
    _box_on_ground(a=400.0, b=180.0, c=120.0).export(src)  # 单位 cm
    meta = prepare_geometry(src, tmp_path / "out", scale=0.01)
    assert meta.length == pytest.approx(4.0)


def test_frontal_area_of_box():
    m = _box_on_ground()
    area = _frontal_area(m, length=4.0, divisions=100)
    assert area == pytest.approx(1.8 * 1.2, rel=0.05)  # 体素离散误差 5%


def test_missing_file(tmp_path):
    with pytest.raises(ValueError):
        prepare_geometry(tmp_path / "nope.stl", tmp_path)


def test_invalid_scale(tmp_path):
    src = tmp_path / "car.stl"
    _box_on_ground().export(src)
    with pytest.raises(ValueError):
        prepare_geometry(src, tmp_path / "out", scale=0.0)
