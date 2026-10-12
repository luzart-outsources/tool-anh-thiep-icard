"""Chuyển thiệp cardkit → templateData của Icard (cần Chromium để dựng thiệp mẫu)."""
import io
import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from cardkit.config import ConfigError
from cardkit.export import render_card
from cardkit.icard.convert import (IMG, Options, Page, _icard_text, build, fill_urls, simulate_page, solid_color,
                                   text_item)
from cardkit.icard.fonts import css_weight, font_meta, icard_font_name, static_font_bytes
from cardkit.ingest import ingest
from conftest import make_icard_project

ROOT = Path(__file__).resolve().parents[1]
CORMORANT = ROOT / "fonts" / "CormorantGaramond-Variable.ttf"


@pytest.fixture(scope="module")
def pages(tmp_path_factory):
    root = tmp_path_factory.mktemp("icard")
    prj = make_icard_project(root)
    kit = prj.kit("mini")
    ingest(kit, log=lambda *_: None)
    kit = prj.kit("mini")
    out = {}
    for lay in ("the", "sau", "ngang"):
        d = root / "out" / lay
        render_card(kit, prj.layout(lay), out_dir=d, log=lambda *_: None)
        out[lay] = Page(d, lay)
    return out


def _manifest(page: Page) -> dict:
    return json.loads((page.out_dir / "manifest.json").read_text(encoding="utf-8"))


def _ink_box(im: Image.Image):
    a = np.asarray(im.convert("RGB")).astype(int)
    ys, xs = np.nonzero(np.abs(a - 255).sum(axis=2) > 60)
    return xs.min(), ys.min(), xs.max() + 1, ys.max() + 1


def test_editable_text_lands_where_cardkit_drew_it(pages):
    """Giả lập renderer Icard: mực chữ của ô sửa được trùng vị trí mực chữ cardkit (đã quy về khung logic)."""
    pg = pages["the"]
    m = _manifest(pg)
    k = 600 / m["canvas"]["w"]
    for t in m["texts"]:
        item, need, _ = text_item(t, pg.out_dir / "fonts" / t["font_file"], k, "#000000", 1)
        page = {"canvasWidth": 600, "canvasHeight": 840, "backgroundColor": "#FFFFFF", "items": [item]}
        x0, y0, x1, y1 = _ink_box(simulate_page(page, {}, {need.name: need}, 1.0))
        bx, by, bw, bh = (v * k for v in t["bbox"])
        fs = item["fontSize"]
        assert abs((y0 + y1) / 2 - (by + bh / 2)) < 0.15 * fs, t["id"]                # cùng tâm dọc
        if t["align"] == "center":
            assert abs((x0 + x1) / 2 - (bx + bw / 2)) < 0.12 * fs + 2, t["id"]       # cùng tâm ngang
        else:
            assert abs(x0 - bx) < 0.12 * fs + 2, t["id"]                            # giữ mép trái
        assert item["isCustomWidth"] is True and item["fontWeight"] == "normal"


def test_text_content_rules():
    assert _icard_text({"text": "Thiệp cưới", "uppercase": True}) == "THIỆP CƯỚI"
    assert _icard_text({"text": "P|A"}) == "P | A"
    assert solid_color("linear-gradient(170deg, rgb(161, 122, 71) 0%, rgb(241, 217, 164) 50%, rgb(201, 162, 107) 100%)") \
        == "#c9a26b"
    assert solid_color("texture") == "#333333"


def test_merge_mode_bakes_ornaments_and_locked_text(pages):
    res = build([pages["the"]], Options(texts={"ten": {"mode": "lock"}, "dia_chi": {"mode": "drop"}}))
    pg = res.template_data["pages"][0]
    assert res.template_data["width"] == pg["canvasWidth"] == 454 and pg["canvasHeight"] == 636   # khung chuẩn Icard
    texts = [i for i in pg["items"] if i["type"] == "text"]
    assert [t["content"] for t in texts] == ["THIỆP CƯỚI"]                               # khoá → nền, bỏ → mất
    assert texts[0]["fontFamily"] == "Cormorant Garamond 600" and texts[0]["color"].startswith("#")
    photos = [i for i in pg["items"] if i["type"] == "image"]
    assert len(photos) == 1 and photos[0]["shape"] == "circle"                          # ô ảnh oval
    assert any("ô ảnh" in w for w in res.warnings)
    bg = Image.open(io.BytesIO(res.uploads[pg["backgroundImage"]])).convert("RGB")
    nen = Image.open(pages["the"].out_dir / "01_nen.png").convert("RGB")
    diff = np.abs(np.asarray(bg).astype(int) - np.asarray(nen).astype(int)).sum(axis=2)
    assert diff[95:110, 195:205].max() > 60                                             # vòng hoa văn đã ở trong nền
    ten = _manifest(pages["the"])["texts"][1]["bbox"]
    assert diff[ten[1]:ten[1] + ten[3], ten[0]:ten[0] + ten[2]].max() > 60               # chữ khoá in vào nền
    assert all(v.startswith(IMG) for v in [pg["backgroundImage"]] + [p["url"] for p in photos])
    assert [f.name for f in res.fonts] == ["Cormorant Garamond 600"]


def test_layers_mode_keeps_ornaments_and_locked_text_as_images(pages):
    res = build([pages["sau"]], Options(ornaments="layers", logical_w=600,
                                        texts={"ten": {"mode": "lock", "color": "#112233"}}))
    items = sorted(res.template_data["pages"][0]["items"], key=lambda i: i["zIndex"])
    kinds = [i["type"] for i in items]
    assert kinds == ["image", "image", "text", "text"]                                # vòng · chữ khoá · 2 ô sửa
    ring = Image.open(io.BytesIO(res.uploads[items[0]["url"]]))
    assert abs(ring.width / ring.height - items[0]["width"] / items[0]["height"]) < 0.02  # hộp đúng tỉ lệ ảnh
    assert 280 < items[0]["width"] < 340                                                # ~200/400 khung → ~300/600
    assert len({i["zIndex"] for i in items}) == len(items)


def test_pages_share_size_and_thumbnail(pages):
    with pytest.raises(ConfigError, match="cùng khổ"):
        build([pages["the"], pages["ngang"]], Options())
    res = build([pages["the"], pages["sau"]], Options(logical_w=454))
    td = res.template_data
    assert len(td["pages"]) == 2 and td["pages"][1]["canvasWidth"] == 454 == td["width"]
    assert td["settings"] == {"invitationType": "Thiệp cưới"}
    th = Image.open(io.BytesIO(res.thumbnail))
    assert th.size == (1200, 800) and th.getpixel((5, 5)) == (255, 255, 255)
    assert len(res.previews) == 2 and res.previews[0].size == (908, 1272)        # 454 × 560/400 = 635,6 → 636 → ×2


def test_fill_urls_and_options_validation():
    td = {"pages": [{"backgroundImage": IMG + "a", "items": [{"url": IMG + "b"}, {"content": "x"}]}]}
    out = fill_urls(td, {IMG + "a": "https://r2/a", IMG + "b": "https://r2/b"})
    assert out["pages"][0]["backgroundImage"] == "https://r2/a" and out["pages"][0]["items"][0]["url"] == "https://r2/b"
    with pytest.raises(ConfigError):
        fill_urls(td, {})
    with pytest.raises(ConfigError):
        Options.from_dict({"ornaments": "abc"})
    with pytest.raises(ConfigError):
        Options.from_dict({"texts": {"x": {"color": "red"}}})
    assert Options.from_dict({"logical_w": "500", "texts": {"x": {"mode": "lock"}}}).mode("x") == "lock"


def test_variable_font_becomes_static_instance():
    assert icard_font_name(CORMORANT, 600) == "Cormorant Garamond 600"
    assert icard_font_name(CORMORANT, 900) == "Cormorant Garamond 700"                  # kẹp theo trục wght
    assert icard_font_name(ROOT / "fonts" / "ImperialScript-Regular.ttf", 400) == "Imperial Script"
    assert css_weight(ROOT / "fonts" / "ImperialScript-Regular.ttf", 700) == "bold"
    from fontTools.ttLib import TTFont
    st = TTFont(io.BytesIO(static_font_bytes(CORMORANT, 600)))
    assert "fvar" not in st and st["OS/2"].usWeightClass == 600
    m = font_meta(CORMORANT)
    assert m["ascent"] == 0.924 and m["descent"] == 0.287


def test_lining_numbers_are_frozen_into_the_uploaded_font():
    """Canvas của Icard không bật được font-variant-numeric → số thẳng hàng phải nằm sẵn trong cmap."""
    from fontTools.ttLib import TTFont
    from cardkit.icard.fonts import features_for
    feats = features_for(CORMORANT, "lining-nums")
    assert feats == ("lnum",) and features_for(CORMORANT, "") == ()
    assert features_for(ROOT / "fonts" / "ImperialScript-Regular.ttf", "tabular-nums") == ()   # font không có tnum
    assert icard_font_name(CORMORANT, 600, feats) == "Cormorant Garamond 600 Lining"
    plain = TTFont(io.BytesIO(static_font_bytes(CORMORANT, 600))).getBestCmap()[ord("2")]
    lining = TTFont(io.BytesIO(static_font_bytes(CORMORANT, 600, feats))).getBestCmap()[ord("2")]
    assert plain == "two" and lining != plain


def test_guest_name_slot(pages):
    """Ô tên khách mời → item isGuestName của Icard (Icard tự điền tên từng khách theo link mời)."""
    assert Options().mode("khach") == "guest" and Options().mode("ten") == "edit"
    assert Options(texts={"khach": {"mode": "edit"}}).mode("khach") == "edit"
    m = _manifest(pages["the"])
    t = {**m["texts"][0], "id": "khach", "text": "Ông/Bà: ............"}
    item, _, _ = text_item(t, pages["the"].out_dir / "fonts" / t["font_file"], 0.5, "#000000", 1, guest=True)
    assert item["isGuestName"] is True and item["content"] == "[Tên Khách Mời]"
    res = build([pages["the"]], Options(texts={"tieu_de": {"mode": "guest"}}))
    guests = [i for i in res.template_data["pages"][0]["items"] if i.get("isGuestName")]
    assert [g["content"] for g in guests] == ["[Tên Khách Mời]"]
    item, _, _ = text_item({**t, "italic": True}, pages["the"].out_dir / "fonts" / t["font_file"], 0.5, "#000000", 1)
    assert item["fontStyle"] == "italic"                                         # chữ nghiêng giữ nghiêng trên Icard


def test_library_has_standard_icard_set():
    """Bộ 4 trang chuẩn Icard có đủ trong thư viện bố cục, được đóng gói, và hợp lệ với mẫu demo."""
    from cardkit.config import Project, validate
    from cardkit.studio import ICARD_PAGES, LAYOUT_ORDER
    prj = Project(ROOT)
    assert ICARD_PAGES == ["bia", "gia_dinh", "thiep_moi", "cam_on"] and set(ICARD_PAGES) <= set(LAYOUT_ORDER)
    assert all((ROOT / "layouts" / f"{n}.json").exists() for n in LAYOUT_ORDER)
    lay = prj.layout("cam_on")
    assert {t["id"] for t in lay.texts} >= {"ten_1", "ten_2"}
    if (ROOT / "kits" / "xanh_lily" / "kit.json").exists():                   # bộ demo chỉ có trên máy phát triển
        assert validate(prj.kit("xanh_lily"), lay) == []
