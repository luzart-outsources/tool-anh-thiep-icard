"""Đăng mẫu lên Icard – chạy với server Icard giả lập (tests/conftest.py), không đụng Icard thật."""
import io
import json

import pytest
from PIL import Image

from cardkit.config import ConfigError
from cardkit.icard.client import IcardClient, IcardError
from cardkit.icard.publish import load_state, publish
from cardkit.ingest import ingest
from conftest import FakeIcard, make_icard_project

META = {"title": "Mini xanh lá", "category": "Thiệp Mời", "group": "Thiệp Cưới", "type": "Cổ Điển",
        "description": "Mẫu thử"}


@pytest.fixture()
def prj(tmp_path):
    p = make_icard_project(tmp_path)
    ingest(p.kit("mini"), log=lambda *_: None)
    return p


def _client(fake, login=True) -> IcardClient:
    c = IcardClient(fake.server)
    if login:
        c.login("admin", FakeIcard.PASSWORD)
    return c


def test_create_then_republish_updates_and_skips_unchanged_images(prj, fake_icard):
    c = _client(fake_icard)
    assert c.role == "admin" and c.taxonomy()[0]["children"][0]["title"] == "Thiệp Cưới"
    logs = []
    r1 = publish(prj, c, "mini", ["the", "sau"], {"ornaments": "layers"}, META, log=logs.append)
    assert r1["action"] == "create" and r1["pages"] == 2 and r1["skipped"] == 0
    assert r1["fonts_created"] == ["Cormorant Garamond 600", "Cormorant Garamond 500"]   # mỗi độ đậm một bản tĩnh
    t = fake_icard.templates[r1["template_id"]]
    assert t["isActive"] == "false" and t["category"] == "Thiệp Mời" and t["type"] == "Cổ Điển"   # mặc định: nháp
    td = t["templateData"]
    assert len(td["pages"]) == 2 and td["width"] == 454
    urls = [td["pages"][0]["backgroundImage"]] + [i["url"] for p in td["pages"] for i in p["items"] if i["type"] == "image"]
    assert urls and all(u.startswith("https://r2.test/") for u in urls)                  # không còn chỗ giữ @img:
    assert Image.open(io.BytesIO(t["thumb"])).format == "WEBP"
    assert len(fake_icard.uploads) == r1["uploaded"] > 0
    assert any("Up" in x for x in logs) and logs[-1] == "Xong."

    r2 = publish(prj, c, "mini", ["the", "sau"], {"ornaments": "layers"}, {**META, "is_active": True},
                 log=lambda *_: None)
    assert r2["action"] == "update" and r2["template_id"] == r1["template_id"]
    assert r2["uploaded"] == 0 and r2["skipped"] == r1["uploaded"] and r2["fonts_created"] == []   # không up lại
    assert len(fake_icard.templates) == 1 and fake_icard.templates[r1["template_id"]]["isActive"] == "true"
    st = load_state(prj.kit("mini"))[fake_icard.server]
    assert st["template_id"] == r1["template_id"] and st["last"]["layouts"] == ["the", "sau"]


def test_republish_keeps_approval_made_on_icard(prj, fake_icard):
    """Mẫu đã bấm "Duyệt ngay" trên admin Icard → đăng lại (không tích Hiển thị ngay) không được ẩn lại."""
    c = _client(fake_icard)
    r = publish(prj, c, "mini", ["sau"], {}, META, log=lambda *_: None)
    fake_icard.templates[r["template_id"]]["isActive"] = "true"                   # duyệt trên Icard
    r2 = publish(prj, c, "mini", ["sau"], {}, {**META, "is_active": False}, log=lambda *_: None)
    assert fake_icard.templates[r["template_id"]]["isActive"] == "true" and r2["active"] is True and r["active"] is False


def test_template_deleted_on_icard_is_recreated(prj, fake_icard):
    c = _client(fake_icard)
    r1 = publish(prj, c, "mini", ["sau"], {}, META, log=lambda *_: None)
    fake_icard.templates.clear()
    r2 = publish(prj, c, "mini", ["sau"], {}, META, log=lambda *_: None)
    assert r2["action"] == "create" and r2["template_id"] != r1["template_id"]


def test_login_and_permission_errors(prj, fake_icard):
    with pytest.raises(IcardError, match="Sai tên đăng nhập"):
        IcardClient(fake_icard.server).login("admin", "sai")
    with pytest.raises(IcardError, match="đăng nhập lại"):
        _client(fake_icard, login=False).fonts()
    with pytest.raises(ConfigError, match="tiêu đề"):
        publish(prj, _client(fake_icard), "mini", ["sau"], {}, {**META, "title": " "}, log=lambda *_: None)
    fake_icard.role = "marketing"
    with pytest.raises(IcardError, match="admin hoặc designer"):
        publish(prj, _client(fake_icard), "mini", ["sau"], {}, META, log=lambda *_: None)


@pytest.mark.parametrize("typed", ["https://icards.com.vn/sign-in", "icards.com.vn", "https://www.icards.com.vn/",
                                   "https://admin.icards.com.vn/login", "https://api.icards.com.vn/api",
                                   "adminapi.icards.com.vn", "https://adminapi.icards.com.vn/api/v1/"])
def test_web_addresses_of_icard_map_to_admin_api(typed):
    from cardkit.icard import DEFAULT_SERVER, normalize_server
    assert normalize_server(typed) == DEFAULT_SERVER == "https://adminapi.icards.com.vn/api/v1"


def test_other_servers_kept_and_html_reply_explained():
    from cardkit.icard import normalize_server
    from cardkit.icard.client import _message
    assert normalize_server(" http://127.0.0.1:5000/api/v1/ ") == "http://127.0.0.1:5000/api/v1"
    assert normalize_server("") == "https://adminapi.icards.com.vn/api/v1"

    class R:
        status_code, text, headers = 404, "<!doctype html><html>…</html>", {"Content-Type": "text/html"}

        def json(self):
            raise ValueError
    assert "không phải API" in _message(R()) and "<html" not in _message(R())


def test_title_conflict_has_clear_message(prj, fake_icard):
    fake_icard.templates["x"] = {"_id": "x", "title": META["title"]}
    with pytest.raises(IcardError, match="trùng tiêu đề"):
        publish(prj, _client(fake_icard), "mini", ["sau"], {}, META, log=lambda *_: None)


def test_existing_font_is_reused_and_design_assets_uploaded_once(prj, fake_icard):
    fake_icard.fonts.append({"_id": "f9", "name": "cormorant garamond 600"})       # trùng tên (không phân biệt hoa thường)
    c = _client(fake_icard)
    r = publish(prj, c, "mini", ["sau"], {}, META, design_assets=True, log=lambda *_: None)
    assert r["fonts_created"] == ["Cormorant Garamond 500"] and r["design_assets"] == ["Vòng"]
    assert fake_icard.assets[0]["assetType"] == "component" and fake_icard.assets[0]["name"] == "Mini xanh · Vòng"
    r = publish(prj, c, "mini", ["sau"], {}, META, design_assets=True, log=lambda *_: None)
    assert r["design_assets"] == [] and len(fake_icard.assets) == 1                     # không đăng trùng
