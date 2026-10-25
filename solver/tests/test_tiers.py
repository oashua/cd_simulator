import pytest

from windtunnel.tiers import TIERS, Tier, select_tier


def test_low_tier_for_small_machine():
    assert select_tier(4, 16).name == "low"


def test_mid_tier_boundary():
    assert select_tier(8, 32).name == "mid"
    assert select_tier(32, 128).name == "mid"


def test_cpu_above_32_goes_high_even_with_moderate_mem():
    # cpu>32 即为 high（内存只是辅助条件）
    assert select_tier(64, 64).name == "high"


def test_high_tier():
    assert select_tier(64, 256).name == "high"


def test_invalid_inputs():
    with pytest.raises(ValueError):
        select_tier(0, 16)
    with pytest.raises(ValueError):
        select_tier(4, -1)


def test_tier_table_shape():
    assert len(TIERS) == 3
    names = [t.name for t in TIERS]
    assert names == ["low", "mid", "high"]
    for t in TIERS:
        assert isinstance(t, Tier)
        assert t.surface_min <= t.surface_max
        assert t.iterations > 0
        assert t.base_size_per_length > 0
