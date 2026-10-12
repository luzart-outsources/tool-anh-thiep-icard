"""Bàn làm việc: các API chính chạy được trên một dự án tạm."""
import json
import shutil
import threading
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from cardkit.config import Project
from cardkit.studio import Handler
from conftest import needs_demo_kit

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def server(tmp_path):
    shutil.copytree(ROOT / "fonts", tmp_path / "fonts")
    shutil.copytree(ROOT / "layouts", tmp_path / "layouts")
    (tmp_path / "kits").mkdir()
    Handler.prj = Project(tmp_path)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}", tmp_path
    srv.shutdown()


def call(base, path, body=None, raw=None, headers=None):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    req = urllib.request.Request(base + path, data=data, headers=headers or {}, method="POST" if data is not None else "GET")
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        body = e.read()
        try:
            return e.code, json.loads(body)
        except ValueError:
            return e.code, {"raw": body.decode("utf-8", "replace")}


def test_state_new_kit_and_errors(server):
    base, root = server
    code, st = call(base, "/api/state")
    assert code == 200 and st["kits"] == [] and st["presets"]["tieu_chuan"]["sheets"] == 5
    code, err = call(base, "/api/kit/new", {"idea": "  ", "ids": []})
    assert code == 400 and "ý tưởng" in err["error"]
    code, d = call(base, "/api/kit/new", {"title": "Đỏ song hỷ", "idea": "Đỏ truyền thống, song hỷ", "ids": ["nen", "goc", "div_dai"]})
    assert code == 200 and d["name"] == "do_song_hy" and len(d["sheets"]) == len(d["sheets"]) > 0
    assert d["sheets"][0]["message"].startswith("Mình cần bạn vẽ") and "Đỏ truyền thống" in d["sheets"][0]["message"]
    code, err = call(base, "/api/kit/do_song_hy/sheet/to1", raw=b"x", headers={"X-Filename": "a.gif"})
    assert code == 400                                                    # định dạng không hỗ trợ → báo lỗi rõ
    code, _ = call(base, "/f/../../Windows/win.ini")
    assert code == 404                                                    # không đọc được file ngoài dự án


@needs_demo_kit
def test_layout_gallery_and_shape_render(server):
    base, root = server
    shutil.copytree(ROOT / "kits" / "xanh_lily" / "assets", root / "kits" / "demo" / "assets")
    shutil.copy(ROOT / "kits" / "xanh_lily" / "kit.json", root / "kits" / "demo" / "kit.json")
    code, j = call(base, "/api/kit/demo/layouts")
    assert code == 200 and len(j["layouts"]) >= 8
    vong = next(L for L in j["layouts"] if L["name"] == "vong_hoa")
    assert any("bỏ trống" in m for m in vong["missing"])                 # mẫu không có vòng hoa → báo bỏ trống
    code, pv = call(base, "/api/kit/demo/layout_preview", {"layout": "vom_hoa", "shape": "vom"})
    assert code == 200 and pv["url"].startswith("/f/kits/demo/_previews/vom_hoa__vom.png")
    code, r = call(base, "/api/render", {"kit": "demo", "layouts": ["thiep_moi"], "texts": {"ten_1": "An"},
                                          "khach": "t", "size": "10x15", "shape": "vom"})
    assert code == 200 and "không hợp hình Vòm" in " ".join(r["results"][0]["warnings"])


@needs_demo_kit
def test_layout_editor_save_preview_delete(server):
    base, root = server
    shutil.copytree(ROOT / "kits" / "xanh_lily" / "assets", root / "kits" / "demo" / "assets")
    shutil.copy(ROOT / "kits" / "xanh_lily" / "kit.json", root / "kits" / "demo" / "kit.json")
    code, ed = call(base, "/api/kit/demo/editor")
    assert code == 200 and ed["items"]["goc"]["own"] and ed["items"]["goc"]["w"] > 0
    assert ed["items"]["hoa_nho"]["real"] != "hoa_nho"                    # món thay thế: trình chỉnh thấy ảnh thật
    assert "script" in ed["fonts"] and 0.3 < ed["fonts"]["script"]["cap"] < 1 and "linear-gradient" in ed["fills"]["gold"]
    code, fr = call(base, "/api/kit/demo/frame", {"shape": "vom", "border": {"type": "border", "lines": [{"inset": 40, "width": 4}]},
                                                  "w": 1748, "h": 2480, "pw": 300})
    assert code == 200 and fr["mask"].startswith("data:image/png") and fr["border"].startswith("data:image/png")
    code, L = call(base, "/api/layout/vom_hoa")
    assert code == 200 and L["ornaments"]
    # ẩn một món + một ô chữ: dựng thử vẫn chạy, ô ẩn không hiện ở form khách
    L["ornaments"][1]["hidden"] = True
    L["texts"][0]["hidden"] = True
    code, pv = call(base, "/api/kit/demo/preview_data", {"data": L, "shape": "oval"})
    assert code == 200 and pv["url"].startswith("/f/kits/demo/_previews/_dang_chinh.png")
    code, err = call(base, "/api/layout/save", {"name": "vom_hoa", "title": "Vòm", "data": L})
    assert code == 400 and "có sẵn" in err["error"]                       # không ghi đè bố cục có sẵn
    code, s = call(base, "/api/layout/save", {"title": "Vòm của tôi", "data": L})
    assert code == 200 and s["name"] == "vom_cua_toi" and (root / "layouts" / "vom_cua_toi.json").exists()
    code, err = call(base, "/api/layout/save", {"title": "Vòm của tôi", "data": L})
    assert code == 400 and "Đã có" in err["error"]
    code, s = call(base, "/api/layout/save", {"name": "vom_cua_toi", "title": "Vòm của tôi", "data": L, "overwrite": True})
    assert code == 200
    code, j = call(base, "/api/kit/demo/layouts")
    mine = next(x for x in j["layouts"] if x["name"] == "vom_cua_toi")
    assert mine["custom"] and mine["title"] == "Vòm của tôi" and L["texts"][0]["id"] not in [t["id"] for t in mine["texts"]]
    assert j["layouts"][-1]["name"] == "vom_cua_toi"                      # bố cục riêng xếp sau bố cục có sẵn
    code, err = call(base, "/api/layout/delete", {"name": "bia"})
    assert code == 400 and (root / "layouts" / "bia.json").exists()
    code, _ = call(base, "/api/layout/delete", {"name": "vom_cua_toi"})
    assert code == 200 and not (root / "layouts" / "vom_cua_toi.json").exists()


def test_design_flow_api(server):
    base, root = server
    reply = (ROOT / "tests" / "fixtures" / "design_reply_cuc.txt").read_text(encoding="utf-8")
    code, pr = call(base, "/api/design/prompt", {"request": "Thiệp cúc trắng"})
    assert code == 200 and "Thiệp cúc trắng" in pr["prompt"]
    code, err = call(base, "/api/design/import", {"text": "  "})
    assert code == 400
    code, dv = call(base, "/api/design/import", {"text": reply, "request": "Thiệp cúc trắng"})
    assert code == 200 and dv["name"] == "cuc_trang_han_quoc" and len(dv["cards"]) == 3 and dv["n_problems"] == 1
    assert "Dây cúc ngang" in dv["fix_message"] and any("la_xanh" in n for n in dv["import_notes"])
    k = dv["name"]
    code, st = call(base, "/api/state")
    assert st["kits"][0]["design"] and st["kits"][0]["variants"] == 7
    code, det = call(base, f"/api/kit/{k}")
    assert det["design"] and det["sheets"][0]["message"].startswith("Tuyệt. Giờ hãy VẼ")
    assert det["sheets"][2]["labels"] == ["Nhành lá", "Bông cúc nhỏ"]
    code, ls = call(base, f"/api/kit/{k}/layouts")
    loc = [x for x in ls["layouts"] if x["local"]]
    assert len(loc) == 7 and loc[3]["own_shape"] == "Trái tim" and "chưa vẽ" in loc[0]["missing"][0]
    code, m = call(base, f"/api/kit/{k}/message", {"kind": "more", "card": "Thiệp mời", "n": 2})
    assert "Thêm 2 phương án" in m["message"] and "TOÀN BỘ" in m["message"]
    code, L = call(base, f"/api/kit/{k}/layout/thiep_tim__1")
    assert code == 200 and L["_local"] and L["shape"]["label"] == "Trái tim"
    code, fr = call(base, f"/api/kit/{k}/frame", {"shape": L["shape"], "border": L["ornaments"][0], "w": 1000, "h": 1000, "pw": 200})
    assert code == 200 and fr["border"].startswith("data:image/png")
    code, sv = call(base, f"/api/kit/{k}/layout/save", {"name": "", "data": L, "as_new": True})
    assert code == 200 and sv["name"] == "thiep_tim__3"
    code, _ = call(base, f"/api/kit/{k}/layout/delete", {"name": "thiep_tim__3"})
    assert code == 200 and not (root / "kits" / k / "layouts" / "thiep_tim__3.json").exists()
    code, err = call(base, f"/api/kit/{k}/layout/delete", {"name": "../kit"})
    assert code == 400


def test_font_api(server):
    base, root = server
    code, fs = call(base, "/api/fonts")
    assert code == 200 and len(fs["fonts"]) == 4 and fs["fonts"][0]["url"].startswith("/f/fonts/")
    data = (ROOT / "fonts" / "PinyonScript-Regular.ttf").read_bytes()
    code, up = call(base, "/api/fonts/upload", raw=data, headers={"X-Filename": "pinyon%20copy.ttf"})
    assert code == 200 and up["font"]["id"] == "pinyon_script" and up["font"]["uploaded"]
    code, ed = call(base, "/api/fonts/pinyon_script", {"desc": "mảnh"})
    assert code == 200 and ed["font"]["desc"] == "mảnh"
    code, st = call(base, "/api/state")
    assert st["font_count"] == 5 and any(f["id"] == "pinyon_script" for f in st["fonts"])   # font viết tay tự thêm: chọn được cho tên
    code, err = call(base, "/api/fonts/upload", raw=b"abc", headers={"X-Filename": "x.otf"})
    assert code == 400 and "không phải file font" in err["error"]
    code, _ = call(base, "/api/fonts/pinyon_script/delete", {})
    assert code == 200
