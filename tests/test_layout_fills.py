import numpy as np
import pytest

from cardkit.fills import fill_array, fill_css, hex_rgb
from cardkit.layout import expand


def test_mirror_xy_makes_four_symmetric_corners():
    el = {"id": "goc", "asset": "goc", "x": 40, "y": 30, "w": 200, "anchor": "tl", "mirror": "xy"}
    placed = expand([el], (1000, 1400), {"goc": (100, 150)})
    by_id = {p.id: p for p in placed}
    assert set(by_id) == {"goc_tl", "goc_tr", "goc_bl", "goc_br"}
    tl, tr, bl, br = (by_id[k] for k in ("goc_tl", "goc_tr", "goc_bl", "goc_br"))
    assert (tl.w, tl.h) == (200, 300)
    assert tr.x == 1000 - 40 - 200 and tr.y == 30 and tr.flip_h and not tr.flip_v
    assert bl.x == 40 and bl.y == 1400 - 30 - 300 and bl.flip_v and not bl.flip_h
    assert br.flip_h and br.flip_v


def test_anchor_center_and_height_sizing():
    el = {"asset": "a", "x": 500, "y": 700, "h": 100, "anchor": "c"}
    (p,) = expand([el], (1000, 1400), {"a": (300, 150)})
    assert (p.w, p.h) == (200, 100)
    assert (p.x, p.y) == (400, 650)


def test_scale_multiplies_geometry():
    el = {"asset": "a", "x": 100, "y": 100, "w": 50, "anchor": "tl"}
    (p,) = expand([el], (1000, 1400), {"a": (10, 10)}, scale=2.0)
    assert (p.x, p.y, p.w, p.h) == (200, 200, 100, 100)


def test_duplicate_ids_get_suffix():
    els = [{"asset": "a", "x": 0, "y": 0, "w": 10}, {"asset": "a", "x": 50, "y": 0, "w": 10}]
    ids = [p.id for p in expand(els, (100, 100), {"a": (10, 10)})]
    assert ids == ["a", "a_2"]


def test_vertical_rule_size():
    el = {"id": "truc", "type": "rule", "orient": "v", "x": 500, "y": 700, "length": 300, "thickness": 3}
    (p,) = expand([el], (1000, 1400), {})
    assert (p.w, p.h) == (3, 300) and (p.x, p.y) == (498, 550)


def test_gradient_endpoints_follow_css_angle():
    spec = {"type": "gradient", "angle": 180, "stops": [["#000000", 0], ["#ffffff", 1]]}
    arr = fill_array(spec, 4, 100)
    assert arr[0, 0, 0] < 5 and arr[-1, 0, 0] > 250      # 180deg = trên → dưới
    spec90 = {**spec, "angle": 90}
    arr = fill_array(spec90, 100, 4)
    assert arr[0, 0, 0] < 5 and arr[0, -1, 0] > 250      # 90deg = trái → phải
    assert "linear-gradient(180.0deg" in fill_css(spec)


@pytest.mark.parametrize("h,rgb", [("#fff", (255, 255, 255)), ("#C9A24B", (201, 162, 75))])
def test_hex_rgb(h, rgb):
    assert hex_rgb(h) == rgb


def test_box_slot_fits_any_aspect_inside_box():
    """Ô (w×h): món nào đặt vào cũng vừa trong ô, giữ tỉ lệ – món dẹt hay món cao đều không tràn."""
    el = {"asset": "a", "x": 500, "y": 300, "w": 400, "h": 40, "anchor": "c"}
    (flat,) = expand([el], (1000, 1400), {"a": (800, 50)})       # dẹt hơn ô → giới hạn theo bề rộng
    assert (flat.w, flat.h) == (400, 25) and flat.y == 300 - 12
    (tall,) = expand([el], (1000, 1400), {"a": (300, 100)})      # cao hơn ô → giới hạn theo chiều cao
    assert (tall.w, tall.h) == (120, 40) and (tall.x, tall.y) == (440, 280)


def test_box_slot_corner_hugs_its_anchor():
    el = {"id": "goc", "asset": "goc", "x": 30, "y": 30, "w": 300, "h": 400, "anchor": "tl", "mirror": "xy"}
    by = {p.id: p for p in expand([el], (1000, 1400), {"goc": (500, 500)})}
    assert (by["goc_tl"].x, by["goc_tl"].y, by["goc_tl"].w) == (30, 30, 300)    # bám góc trên-trái
    assert by["goc_br"].x + by["goc_br"].w == 1000 - 30 and by["goc_br"].y + by["goc_br"].h == 1400 - 30


def test_explicit_stretch_still_possible():
    (p,) = expand([{"asset": "a", "x": 0, "y": 0, "w": 100, "h": 100, "anchor": "tl", "fit": "stretch"}],
                  (1000, 1400), {"a": (10, 50)})
    assert (p.w, p.h) == (100, 100)


def test_sizes_resolve_presets_custom_any_orientation():
    from cardkit.config import ConfigError
    from cardkit.sizes import resolve_size
    assert resolve_size("a5")["px"] == (1748, 2480)
    assert resolve_size("12x18")["px"] == (1417, 2126)
    assert resolve_size("11,5 x 17")["px"] == (1358, 2008)
    assert resolve_size("phone")["px"] == (1080, 1920)
    assert resolve_size("21x15")["px"] == (2480, 1772)          # ngang, vuông… đều được
    assert resolve_size("web")["px"] == (1920, 1080)
    with pytest.raises(ConfigError):
        resolve_size("to lắm")


def test_adapt_to_taller_ratio_spreads_positions_but_keeps_sizes():
    from cardkit.layout import adapt_to_ratio
    data = {"canvas": {"w": 1000, "h": 1400},
            "ornaments": [{"asset": "a", "x": 500, "y": 700, "w": 200, "h": 100, "anchor": "c"},
                          {"type": "rule", "orient": "v", "x": 500, "y": 700, "length": 200, "thickness": 3}],
            "texts": [{"id": "t", "cx": 500, "cy": 1300, "w": 600, "size": 80}]}
    out, s = adapt_to_ratio(data, 1000, 1600)                     # khổ dài hơn
    assert s == 1.0 and out["canvas"]["h"] == 1600
    a, rule = out["ornaments"]
    assert a["y"] == pytest.approx(700 * 1600 / 1400) and (a["w"], a["h"]) == (200, 100)    # vị trí giãn, kích thước giữ
    assert rule["length"] == pytest.approx(200 * 1600 / 1400)                              # trục dọc kéo dài theo
    assert out["texts"][0]["size"] == 80 and data["canvas"]["h"] == 1400     # cỡ chữ giữ; layout gốc không bị sửa


@pytest.mark.parametrize("kind", ["chu_nhat", "bo_goc", "vom", "oval", "rang_cua", "cat_goc", "goc_lom"])
def test_shape_border_runs_along_every_edge(kind):
    from cardkit.shapes import border_alpha, shape_mask
    W, H = 300, 420
    m = shape_mask(kind, W, H)
    assert m[H // 2, W // 2] > 0.99                                 # giữa thiệp luôn ở trong hình
    b = border_alpha(m, [(10, 3, 1.0)])
    wave = W // 13 if kind == "rang_cua" else 0                     # mép răng cưa lượn sóng → viền lượn theo
    assert b[H // 2, 9:16 + wave].max() > 0.9                       # có viền dọc cạnh TRÁI
    assert b[H - 16 - wave:H - 9, W // 2].max() > 0.9               # có viền dọc cạnh DƯỚI
    assert (b * (1 - m)).max() < 0.05                               # viền không lọt ra ngoài hình
