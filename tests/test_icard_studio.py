"""Bàn làm việc – bước "Đăng lên Icard": API cục bộ + server Icard giả lập."""
import http.client
import json
import threading
from http.server import ThreadingHTTPServer

import pytest

from cardkit import studio
from cardkit.ingest import ingest
from cardkit.studio import Handler
from conftest import FakeIcard, make_icard_project

H = {"X-Cardkit": "1", "Content-Type": "application/json"}


@pytest.fixture()
def server(tmp_path):
    prj = make_icard_project(tmp_path)
    ingest(prj.kit("mini"), log=lambda *_: None)
    Handler.prj = prj
    studio._ICARD.update(client=None, log=[], busy=False)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv.server_address[1]
    srv.shutdown()
    studio._ICARD.update(client=None, log=[], busy=False)


def call(port, path, body=None, headers=H, host=None):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=300)
    hd = dict(headers)
    if host:
        hd["Host"] = host
    c.request("POST" if body is not None else "GET", path, json.dumps(body) if body is not None else None, hd)
    r = c.getresponse()
    data = r.read()
    try:
        return r.status, json.loads(data)
    except ValueError:
        return r.status, {"raw": data.decode("utf-8", "replace")}


def test_icard_api_rejects_foreign_requests(server):
    assert call(server, "/api/icard/session", headers={})[0] == 403                # thiếu header tuỳ chỉnh
    assert call(server, "/api/icard/session", host="evil.example:80")[0] == 403    # DNS rebinding
    code, s = call(server, "/api/icard/session")
    assert code == 200 and s["logged_in"] is False and s["default_server"].startswith("https://")
    code, err = call(server, "/api/icard/taxonomy")
    assert code == 401 and "đăng nhập" in err["error"]
    code, err = call(server, "/api/icard/login", {"server": "http://evil.example/api", "login": "a", "password": "b"})
    assert code == 400 and "https://" in err["error"]                               # không gửi mật khẩu qua http lạ


def test_fields_preview_login_push(server, fake_icard):
    code, f = call(server, "/api/icard/fields", {"kit": "mini", "layouts": ["the", "sau"]})
    assert code == 200 and [x["id"] for x in f["fields"]] == ["tieu_de", "ten", "dia_chi"]   # ô cùng id gộp một
    assert all(x["color"].startswith("#") and len(x["color"]) == 7 for x in f["fields"])
    assert {x["mode"] for x in f["fields"]} == {"edit"}
    code, pv = call(server, "/api/icard/preview", {"kit": "mini", "layouts": ["the", "sau"],
                                                   "opts": {"texts": {"ten": {"mode": "lock"}}}})
    assert code == 200 and len(pv["pages"]) == 2 and pv["thumbnail"].startswith("/f/") and pv["size"] == "454 × 636"
    code, err = call(server, "/api/icard/login", {"server": fake_icard.server, "login": "admin", "password": "sai"})
    assert code == 401 and "Sai tên đăng nhập" in err["error"]
    code, s = call(server, "/api/icard/login", {"server": fake_icard.server, "login": "admin",
                                                "password": FakeIcard.PASSWORD})
    assert code == 200 and s["logged_in"] and s["user"]["role"] == "admin"
    code, t = call(server, "/api/icard/taxonomy")
    assert code == 200 and t["taxonomy"][0]["title"] == "Thiệp Mời"
    meta = {"title": "Mini", "category": "Thiệp Mời", "group": "Thiệp Cưới", "type": "Hiện Đại"}
    code, r = call(server, "/api/icard/push", {"kit": "mini", "layouts": ["sau"], "opts": {}, "meta": meta})
    assert code == 200 and r["action"] == "create" and r["template_id"] in fake_icard.templates
    code, p = call(server, "/api/icard/progress")
    assert p["busy"] is False and p["lines"][-1] == "Xong."
    code, info = call(server, "/api/icard/kit/mini")
    assert info["template_id"] == r["template_id"] and info["last"]["meta"]["type"] == "Hiện Đại"
    assert info["standard_pages"] == ["bia", "gia_dinh", "thiep_moi", "cam_on"]
    code, s = call(server, "/api/icard/logout", {})
    assert s["logged_in"] is False
