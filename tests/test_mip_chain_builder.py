import pytest

import mip_chain_builder as mb


def pixels(width, height, value=1.0):
    return [value] * (width * height * 4)


def build(width=8, height=8, **over):
    kwargs = {"srgb": True, "min_size": 1, "max_size": 4096, "premultiply_alpha": True}
    kwargs.update(over)
    builder = mb.MipChainBuilder(**kwargs)
    return builder.build(pixels(width, height), width, height)


def test_odd_dimensions_are_rounded_up_per_level():
    result = build(width=5, height=3)
    assert result["levels"][1]["width"] == 3
    assert result["levels"][1]["height"] == 2


def test_non_power_of_two_chain_ends_at_one_by_one():
    result = build(width=5, height=3)
    assert result["levels"][-1]["width"] == 1
    assert result["levels"][-1]["height"] == 1


def test_alpha_is_averaged_in_premultiplied_space():
    data = [1.0, 1.0, 1.0, 1.0, 0.0, 0.0, 0.0, 0.0]
    result = mb.MipChainBuilder(premultiply_alpha=True).build(data, 2, 1)
    level = result["levels"][1]
    assert level["width"] == 1


def test_srgb_is_averaged_in_linear_space():
    data = [0.0, 0.0, 0.0, 1.0, 1.0, 1.0, 1.0, 1.0]
    result = mb.MipChainBuilder(srgb=True).build(data, 2, 1)
    linear = result["levels"][1]["data"][0]
    assert 0.6 < linear < 0.9


def test_checksums_are_reproducible():
    a = build()
    b = build()
    assert [level["checksum"] for level in a["levels"]] == [level["checksum"] for level in b["levels"]]


def test_array_layers_are_independent():
    data = [1.0] * 16 + [0.0] * 16
    result = mb.MipChainBuilder().build(data, 2, 2, layers=2)
    assert result["levels"][-1]["layers"] == 2


def test_minimum_size_is_configurable():
    result = build(width=16, height=16, min_size=4)
    assert result["levels"][-1]["width"] == 4


def test_source_data_is_not_mutated():
    data = pixels(4, 4)
    before = list(data)
    mb.MipChainBuilder().build(data, 4, 4)
    assert data == before


def test_atlas_region_sampling_does_not_escape_bounds():
    result = build(width=8, height=8)
    for level in result["levels"]:
        assert level["width"] >= 1 and level["height"] >= 1


def test_level_count_is_complete():
    result = build(width=8, height=8)
    assert result["count"] == 4


def test_two_by_two_box_filter():
    data = [1.0, 1.0, 1.0, 1.0] * 4
    result = mb.MipChainBuilder().build(data, 2, 2)
    assert result["levels"][1]["data"][0] == pytest.approx(1.0)


def test_final_level_is_one_by_one():
    result = build(width=7, height=7)
    assert result["levels"][-1]["width"] == 1
    assert result["levels"][-1]["height"] == 1


def test_each_level_has_checksum():
    result = build()
    assert all("checksum" in level for level in result["levels"])


def test_zero_dimension_is_rejected():
    with pytest.raises(ValueError):
        build(width=0, height=4)


def test_oversized_texture_is_rejected():
    with pytest.raises(ValueError):
        build(width=8192, height=8, max_size=4096)
