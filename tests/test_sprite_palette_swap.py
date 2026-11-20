import pytest

import sprite_palette_swap as sp

PALETTE = [(0, 0, 0), (255, 0, 0), (0, 255, 0), (0, 0, 255)]


def swap(indices, mapping=None, weights=None, **over):
    kwargs = {"atlas_version": 1}
    kwargs.update(over)
    return sp.SpritePaletteSwap(**kwargs).swap(indices, PALETTE, mapping or {1: 2}, weights=weights)


def test_transparent_index_is_preserved():
    result = swap([0, 1, 0])
    assert result["pixels"][0] == PALETTE[0]


def test_palette_out_of_range_reports_coordinate():
    with pytest.raises(sp.PaletteError) as exc:
        sp.SpritePaletteSwap().swap([9], PALETTE, {})
    assert exc.value.code == "palette_range"


def test_weighted_transition_mixes_colors():
    result = swap([1], mapping={1: 2}, weights={1: 0.5})
    assert result["pixels"][0] != PALETTE[1]
    assert result["pixels"][0] != PALETTE[2]


def test_alpha_is_not_double_applied():
    result = swap([1], mapping={1: 1})
    assert result["pixels"][0] == PALETTE[1]


def test_atlas_region_is_clipped():
    result = swap([1, 2, 3, 1], region=(1, 0, 2, 1))
    assert len(result["pixels"]) == 2


def test_cache_key_includes_versions():
    a = sp.SpritePaletteSwap(atlas_version=1).swap([1], PALETTE, {1: 2})
    b = sp.SpritePaletteSwap(atlas_version=2).swap([1], PALETTE, {1: 2})
    assert a["cache_key"] != b["cache_key"]


def test_restore_returns_original_indices():
    original = [0, 1, 2]
    swapped = swap(original)
    restored = sp.SpritePaletteSwap().restore(swapped["image"])
    assert restored["indices"] == original


def test_grayscale_uses_builtin_palette():
    result = sp.SpritePaletteSwap().swap([0, 128, 255], None, {})
    assert len(result["pixels"]) == 3


def test_index_over_255_is_rejected():
    with pytest.raises(sp.PaletteError):
        sp.SpritePaletteSwap().swap([256], PALETTE, {})


def test_replace_mode_overrides_previous_swap():
    result = swap([1], mapping={1: 3})
    assert result["pixels"][0] == PALETTE[3]


def test_weight_must_be_between_zero_and_one():
    with pytest.raises(sp.PaletteError):
        swap([1], weights={1: 2.0})


def test_cache_hit_is_reported():
    engine = sp.SpritePaletteSwap()
    first = engine.swap([1], PALETTE, {1: 2})
    second = engine.swap([1], PALETTE, {1: 2})
    assert second["cached"] is True


def test_warnings_are_returned_for_missing_entries():
    result = swap([1], mapping={})
    assert result["warnings"]


def test_output_reports_palette_version():
    assert "palette_version" in swap([1])


def test_repeated_swap_is_stable():
    assert swap([1, 2, 3]) == swap([1, 2, 3])
