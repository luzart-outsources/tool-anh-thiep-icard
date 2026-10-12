"""Kiểm thử đầu-cuối trên một kit tí hon tự sinh: ingest → render (cần Chromium của Playwright)."""
import json
import shutil
from pathlib import Path

import cv2
import numpy as np
import pytest
from PIL import Image

from cardkit.config import Project, validate
from cardkit.ingest import ingest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def mini_project(tmp_path):
    (tmp_path / "fonts").mkdir()
    shutil.copy(ROOT / "fonts" / "CormorantGaramond-Variable.ttf", tmp_path / "fonts")
    kit = tmp_path / "kits" / "mini"
    (kit / "raw").mkdir(parents=True)
    # asset hoa văn: vòng tròn vàng trên nền magenta đặc (đúng như prompt yêu cầu ChatGPT)
    img = np.zeros((300, 300, 3), np.uint8)
    img[:] = (255, 0, 255)
    cv2.circle(img, (150, 150), 100, (200, 160, 70), 12, lineType=cv2.LINE_AA)
    Image.fromarray(img).save(kit / "raw" / "vong.png")
    Image.new("RGB", (400, 560), (20, 60, 40)).save(kit / "raw" / "nen.png")
    (kit / "kit.json").write_text(json.dumps({
        "palette": ["#143c28"],
        "fills": {"gold": {"type": "gradient", "angle": 180, "stops": [["#a17a47", 0], ["#f1d9a4", 1]]}},
        "fonts": {"serif": "fonts/CormorantGaramond-Variable.ttf"},
        "text_styles": {"caps": {"font": "serif", "weight": 600, "fill": "gold", "uppercase": True, "size": 40}},
        "assets": {"nen": {"kind": "background"}, "vong": {"role": "crest", "desc": "gold ring"}},
    }), encoding="utf-8")
    (tmp_path / "layouts").mkdir()
    (tmp_path / "layouts" / "the.json").write_text(json.dumps({
        "canvas": {"w": 400, "h": 560},
        "ornaments": [
            {"id": "vien", "type": "border", "fill": "gold", "lines": [{"inset": 10, "width": 2}]},
            {"id": "vong", "asset": "vong", "x": 200, "y": 200, "w": 200, "anchor": "c"},
            {"id": "ke", "type": "rule", "x": 200, "y": 380, "length": 200, "thickness": 2, "fill": "gold"},
        ],
        "texts": [
            {"id": "tieu_de", "style": "caps", "text": "Thiệp cưới", "cx": 200, "cy": 440, "w": 300},
            {"id": "ten", "style": "caps", "text": "Ngắn", "cx": 200, "cy": 500, "w": 300, "group": "g"},
        ],
    }), encoding="utf-8")
    return Project(tmp_path)


def test_ingest_then_render(mini_project):
    prj = mini_project
    kit = prj.kit("mini")
    items = {it.name: it for it in ingest(kit, log=lambda *_: None)}
    assert items["vong"].status == "ok"
    assert items["nen"].status == "warn" and "nền chỉ 400×560px" in items["nen"].notes[0]   # nhỏ so với khổ in
    ring = np.asarray(Image.open(kit.assets_dir / "vong.png"))
    assert ring.shape[2] == 4 and ring[..., 3].max() == 255
    assert 210 <= ring.shape[0] <= 220              # cắt sát: đường kính 200 + nét 12 + mép khử răng cưa
    assert validate(kit, prj.layout("the")) == []

    pytest.importorskip("playwright")
    from cardkit.export import render_card
    out = prj.root / "out"
    try:
        res = render_card(kit, prj.layout("the"), data={"ten": "Một cái tên rất rất rất dài để thử tự thu nhỏ"},
                          out_dir=out, log=lambda *_: None)
    except Exception as e:  # máy không có Chromium của Playwright
        if "Chromium" in str(e):
            pytest.skip(str(e))
        raise
    for f in ("01_nen.png", "02_hoa_van.png", "03_text.png", "ghep.png", "sheet.png", "manifest.json",
              "preview.html"):
        assert (out / f).exists(), f
    layers = [Image.open(out / f) for f in ("01_nen.png", "02_hoa_van.png", "03_text.png")]
    assert all(im.size == (400, 560) for im in layers)          # cùng khung → chồng là khớp
    assert layers[1].mode == "RGBA" and layers[2].mode == "RGBA"
    m = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    ten = next(t for t in m["texts"] if t["id"] == "ten")
    x, y, w, h = ten["bbox"]
    assert w > 0 and x >= 200 - 150 - 1 and x + w <= 200 + 150 + 1   # mực nằm trong vùng an toàn
    assert any("thu nhỏ" in wmsg for wmsg in res["warnings"])
    assert {p["id"] for p in m["pieces"]} == {"vien", "vong", "ke"}
    assert not (out / "_build").exists()                           # không lẫn file gỡ lỗi vào bộ giao khách

    from cardkit.sizes import resolve_size
    out2 = prj.root / "out_phone"
    render_card(kit, prj.layout("the"), out_dir=out2, size=resolve_size("360x640px"), pieces=False, log=lambda *_: None)
    for f in ("01_nen.png", "02_hoa_van.png", "03_text.png", "ghep.png"):
        assert Image.open(out2 / f).size == (360, 640), f                  # đúng từng px theo khổ đã chọn

    # món / ô chữ bị ẩn trong trình chỉnh → không có trong bộ file giao khách
    from cardkit.config import Layout
    lay = prj.layout("the")
    d = json.loads(json.dumps(lay.data))
    d["ornaments"][2]["hidden"] = True
    d["texts"][0]["hidden"] = True
    out3 = prj.root / "out_hidden"
    render_card(kit, Layout("the", lay.path, d), out_dir=out3, log=lambda *_: None)
    m3 = json.loads((out3 / "manifest.json").read_text(encoding="utf-8"))
    assert {p["id"] for p in m3["pieces"]} == {"vien", "vong"} and [t["id"] for t in m3["texts"]] == ["ten"]
