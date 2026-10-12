"""Thư viện font: font có sẵn + font khách tự thêm (kiểm dấu tiếng Việt, quyền nhúng, đổi woff2, xoá an toàn)."""
import io
import json
import shutil
from pathlib import Path

import pytest
from fontTools import subset
from fontTools.ttLib import TTFont

from cardkit.config import ConfigError, Kit, Project
from cardkit.design import available_fonts
from cardkit.fontlib import add_font, delete_font, list_fonts, update_font

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def root(tmp_path):
    shutil.copytree(ROOT / "fonts", tmp_path / "fonts")
    (tmp_path / "kits").mkdir()
    return tmp_path


def _ascii_woff2(name: str) -> bytes:
    """Great Vibes cắt còn chữ không dấu, đổi tên họ font, đóng gói woff2 (giống font tải trên mạng thiếu tiếng Việt)."""
    tt = TTFont(ROOT / "fonts" / "GreatVibes-Regular.ttf")
    opts = subset.Options()
    opts.flavor, opts.name_IDs = "woff2", ["*"]
    s = subset.Subsetter(opts)
    s.populate(text="ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789 ")
    s.subset(tt)
    for rec in tt["name"].names:
        if rec.nameID in (1, 4, 16):
            rec.string = name
        elif rec.nameID == 6:
            rec.string = name.replace(" ", "")
    buf = io.BytesIO()
    tt.flavor = "woff2"
    tt.save(buf)
    return buf.getvalue()


def test_builtin_fonts_are_listed_with_kind_and_license(root):
    fs = {f["id"]: f for f in list_fonts(root)}
    assert set(fs) == {"imperial", "greatvibes", "pinyon", "cormorant"}
    assert fs["cormorant"]["kind"] == "serif" and fs["cormorant"]["label"] == "Cormorant Garamond"   # font biến thiên: tên họ
    assert all(f["builtin"] and not f["vi_missing"] and f["embed_ok"] and f["ofl"] for f in fs.values())


def test_upload_check_update_and_delete(root):
    f = add_font(root, "thu.woff2", _ascii_woff2("Thu Nghiem Script"))
    assert f["id"] == "thu_nghiem_script" and f["file"].endswith(".ttf") and f["kind"] == "script"   # woff2 → ttf, tên gợi ý viết tay
    assert f["uploaded"] and len(f["vi_missing"]) > 100
    assert (root / f["file"]).exists() and (root / "fonts" / "ThuNghiemScript-LICENSE.txt").exists()
    assert "thu_nghiem_script" not in available_fonts(Project(root))                 # thiếu dấu → AI không chọn
    g = add_font(root, "gv.ttf", (ROOT / "fonts" / "GreatVibes-Regular.ttf").read_bytes())
    assert g["id"] == "great_vibes" and g["file"] == "fonts/GreatVibes.ttf"
    g2 = add_font(root, "gv.ttf", (ROOT / "fonts" / "GreatVibes-Regular.ttf").read_bytes())
    assert g2["id"] == "great_vibes_2" and g2["file"] == "fonts/GreatVibes_2.ttf"           # tải lại lần nữa → không ghi đè
    assert "great_vibes" in available_fonts(Project(root))
    u = update_font(root, "great_vibes", kind="deco", desc="chữ trang trí cho tiêu đề")
    assert u["kind"] == "deco" and u["desc"] == "chữ trang trí cho tiêu đề"
    assert "chữ trang trí cho tiêu đề" in available_fonts(Project(root))["great_vibes"]["desc"]
    with pytest.raises(ConfigError):
        update_font(root, "great_vibes", kind="la")
    with pytest.raises(ConfigError):
        add_font(root, "hong.ttf", b"khong phai font")
    with pytest.raises(ConfigError):
        add_font(root, "anh.png", b"x")
    # ô chữ dùng font thư viện theo id dù mẫu không khai báo font đó
    kit = Kit("k", root / "kits" / "k", root, {"fonts": {}})
    assert kit.font_path("great_vibes") == root / g["file"]
    # xoá: font có sẵn → không; font đang dùng ở mẫu → không; còn lại → xoá cả giấy phép đi kèm
    with pytest.raises(ConfigError):
        delete_font(root, "imperial")
    (root / "kits" / "k").mkdir()
    (root / "kits" / "k" / "kit.json").write_text(json.dumps({"title": "Mẫu A", "fonts": {"ten": g["file"]}}), encoding="utf-8")
    with pytest.raises(ConfigError, match="Mẫu A"):
        delete_font(root, "great_vibes")
    delete_font(root, "thu_nghiem_script")
    assert not (root / f["file"]).exists() and not (root / "fonts" / "ThuNghiemScript-LICENSE.txt").exists()
    assert "thu_nghiem_script" not in {x["id"] for x in list_fonts(root)}
