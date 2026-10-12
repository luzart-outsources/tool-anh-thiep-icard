"""Dùng chung cho các test Icard: mini project dựng được thiệp + server Icard giả lập."""
import json
import re
import shutil
import threading
from email.parser import BytesParser
from email.policy import default as email_policy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import cv2
import numpy as np
import pytest
from PIL import Image

from cardkit.config import Project

ROOT = Path(__file__).resolve().parents[1]

# Bộ demo xanh_lily chỉ có trên máy phát triển (kits/ không nằm trong repo giao khách)
needs_demo_kit = pytest.mark.skipif(not (ROOT / "kits" / "xanh_lily" / "kit.json").exists(),
                                    reason="cần bộ demo kits/xanh_lily (chỉ có trên máy phát triển)")


def make_icard_project(root: Path) -> Project:
    """Mẫu 'mini' (nền + vòng hoa văn) và 3 bố cục: the (có ô ảnh oval), sau (cùng khổ), ngang (khác khổ)."""
    (root / "fonts").mkdir()
    shutil.copy(ROOT / "fonts" / "CormorantGaramond-Variable.ttf", root / "fonts")
    kit = root / "kits" / "mini"
    (kit / "raw").mkdir(parents=True)
    img = np.zeros((300, 300, 3), np.uint8)
    img[:] = (255, 0, 255)
    cv2.circle(img, (150, 150), 100, (200, 160, 70), 12, lineType=cv2.LINE_AA)
    Image.fromarray(img).save(kit / "raw" / "vong.png")
    Image.new("RGB", (400, 560), (20, 60, 40)).save(kit / "raw" / "nen.png")
    (kit / "kit.json").write_text(json.dumps({
        "title": "Mini xanh", "palette": ["#143c28"],
        "fills": {"gold": {"type": "gradient", "angle": 180, "stops": [["#a17a47", 0], ["#f1d9a4", 1]]}},
        "fonts": {"serif": "fonts/CormorantGaramond-Variable.ttf"},
        "text_styles": {"caps": {"font": "serif", "weight": 600, "fill": "gold", "uppercase": True, "size": 40},
                        "body": {"font": "serif", "weight": 500, "fill": "gold", "size": 26}},
        "assets": {"nen": {"kind": "background"}, "vong": {"role": "crest", "desc": "gold ring", "label": "Vòng"}},
    }), encoding="utf-8")
    (root / "layouts").mkdir()
    base = {"canvas": {"w": 400, "h": 560},
            "ornaments": [{"id": "vien", "type": "border", "fill": "gold", "lines": [{"inset": 10, "width": 2}]},
                          {"id": "vong", "asset": "vong", "x": 200, "y": 200, "w": 200, "anchor": "c"},
                          {"id": "ke", "type": "rule", "x": 200, "y": 380, "length": 200, "thickness": 2,
                           "fill": "gold"}],
            "texts": [{"id": "tieu_de", "style": "caps", "text": "Thiệp cưới", "cx": 200, "cy": 440, "w": 300},
                      {"id": "ten", "style": "caps", "text": "An|Mai", "cx": 200, "cy": 500, "w": 300},
                      {"id": "dia_chi", "style": "body", "text": "Hà Nội\nViệt Nam", "cx": 150, "cy": 120,
                       "w": 200, "align": "left"}],
            "photos": [{"id": "anh1", "x": 200, "y": 200, "w": 120, "h": 120, "shape": "oval"}]}
    (root / "layouts" / "the.json").write_text(json.dumps({**base, "title": "Bìa"}), encoding="utf-8")
    (root / "layouts" / "sau.json").write_text(json.dumps({**base, "title": "Trang sau", "photos": []}),
                                               encoding="utf-8")
    (root / "layouts" / "ngang.json").write_text(json.dumps({**base, "canvas": {"w": 560, "h": 400}, "photos": []}),
                                                 encoding="utf-8")
    return Project(root)


class FakeIcard:
    """Bản thu nhỏ của icards-dashboard-backend: đủ các route tool dùng, cùng mã lỗi và định dạng phản hồi."""
    PASSWORD = "mat-khau-thu"

    def __init__(self):
        self.role = "admin"
        self.templates: dict[str, dict] = {}
        self.fonts: list[dict] = [{"_id": "f0", "name": "Arial", "url": "https://r2.test/arial"}]
        self.assets: list[dict] = []
        self.uploads: list[tuple[str, bytes]] = []
        self.calls: list[str] = []
        self.n = 0

    def nid(self) -> str:
        self.n += 1
        return f"{self.n:024x}"


def _multipart(handler, body: bytes):
    msg = BytesParser(policy=email_policy).parsebytes(
        b"Content-Type: " + handler.headers["Content-Type"].encode() + b"\r\n\r\n" + body)
    fields, files = {}, []
    for part in msg.iter_parts():
        name = part.get_param("name", header="content-disposition")
        if part.get_filename() is not None:
            files.append((name, part.get_filename(), part.get_payload(decode=True)))
        else:
            fields[name] = part.get_payload(decode=True).decode("utf-8")
    return fields, files


def _public(t: dict) -> dict:
    return {k: v for k, v in t.items() if k != "thumb"}


def _handler(state: FakeIcard):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _json(self, code, obj, cookie=None):
            b = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(b)))
            if cookie:
                self.send_header("Set-Cookie", cookie)
            self.end_headers()
            self.wfile.write(b)

        def _authed(self):
            if "token=ok" not in (self.headers.get("Cookie") or ""):
                self._json(401, {"message": "Bạn chưa đăng nhập."})
                return False
            return True

        def _role(self, *roles):
            if state.role not in roles:
                self._json(403, {"message": "Bạn không có quyền thực hiện hành động này."})
                return False
            return True

        def _body(self):
            n = int(self.headers.get("Content-Length") or 0)
            return self.rfile.read(n) if n else b""

        def do_GET(self):
            p = self.path.split("?")[0]
            state.calls.append("GET " + p)
            if not self._authed():
                return
            if p == "/api/v1/admin/users/me":
                return self._json(200, {"_id": "u1", "username": "admin", "role": state.role})
            if p == "/api/v1/admin/settings":
                return self._json(200, {"message": "ok", "data": {"headerNav": [
                    {"id": "c1", "title": "Thiệp Mời", "type": "category", "path": "/", "children": [
                        {"id": "g1", "title": "Thiệp Cưới", "type": "group", "path": "/", "children": [
                            {"id": "t1", "title": "Cổ Điển", "type": "type", "path": "/", "children": []},
                            {"id": "t2", "title": "Hiện Đại", "type": "type", "path": "/", "children": []}]}]}]}})
            if p == "/api/v1/admin/fonts":
                return self._json(200, {"status": "success", "data": state.fonts})
            m = re.fullmatch(r"/api/v1/admin/templates/(\w+)", p)
            if m:
                t = state.templates.get(m.group(1))
                return self._json(200, {"status": "success", "data": _public(t)}) if t else \
                    self._json(404, {"message": "Không tìm thấy"})
            self._json(404, {"message": "not found"})

        def do_DELETE(self):
            m = re.fullmatch(r"/api/v1/admin/templates/(\w+)", self.path)
            if m and self._authed():
                state.templates.pop(m.group(1), None)
                self.send_response(204)
                self.end_headers()

        def do_PUT(self):
            p, body = self.path, self._body()
            state.calls.append("PUT " + p)
            if not self._authed() or not self._role("admin", "designer"):
                return
            m = re.fullmatch(r"/api/v1/admin/templates/(\w+)", p)
            t = state.templates.get(m.group(1)) if m else None
            if t is None:
                return self._json(500, {"message": "Không tìm thấy mẫu thiệp để cập nhật."})
            fields, files = _multipart(self, body)
            for k in ("title", "category", "group", "type", "description", "isActive"):
                if k in fields:
                    t[k] = fields[k]
            t["templateData"] = json.loads(fields["templateData"])
            for name, fn, data in files:
                if name in ("image", "generatedThumbnail"):
                    t["imgSrc"] = f"https://r2.test/thumb-{state.nid()}"
                    t["thumb"] = data
            self._json(200, {"status": "success", "data": _public(t)})

        def do_POST(self):
            p, body = self.path, self._body()
            state.calls.append("POST " + p)
            if p == "/api/v1/admin/auth/login":
                j = json.loads(body)
                if j.get("password") != FakeIcard.PASSWORD:
                    return self._json(401, {"message": "Tên đăng nhập hoặc mật khẩu không chính xác."})
                return self._json(200, {"message": "Đăng nhập thành công!", "user": {"_id": "u1", "role": state.role}},
                                  cookie="token=ok; Path=/; HttpOnly")
            if not self._authed():
                return
            if p == "/api/v1/admin/assets/upload-batch":
                if not self._role("admin", "designer"):
                    return
                _, files = _multipart(self, body)
                urls = {}
                for name, fn, data in files:
                    state.uploads.append((name, data))
                    urls[name] = f"https://r2.test/{state.nid()}"
                return self._json(200, {"status": "success", "urls": urls})
            if p == "/api/v1/admin/templates":
                fields, files = _multipart(self, body)
                if any(t["title"] == fields["title"] for t in state.templates.values()):
                    return self._json(409, {"message": "Tên mẫu thiệp đã tồn tại."})
                if not any(n in ("image", "generatedThumbnail") for n, _, _ in files):
                    return self._json(400, {"message": "Ảnh đại diện là bắt buộc khi tạo mẫu mới."})
                tid = state.nid()
                t = {**fields, "_id": tid, "slug": fields["title"].lower().replace(" ", "-"),
                     "templateData": json.loads(fields["templateData"]), "imgSrc": f"https://r2.test/thumb-{tid}",
                     "thumb": files[0][2]}
                state.templates[tid] = t
                return self._json(201, {"status": "success", "data": _public(t)})
            if p == "/api/v1/admin/fonts":
                if not self._role("admin", "designer"):
                    return
                fields, files = _multipart(self, body)
                if any(f["name"] == fields["name"] for f in state.fonts):
                    return self._json(409, {"message": "Tên font này đã tồn tại."})
                f = {"_id": state.nid(), "name": fields["name"], "category": fields["category"],
                     "url": "https://r2.test/font", "data": len(files[0][2])}
                state.fonts.append(f)
                return self._json(201, {"status": "success", "data": f})
            if p == "/api/v1/design-assets":
                if not self._role("admin"):
                    return
                fields, files = _multipart(self, body)
                a = {"_id": state.nid(), **fields, "imgSrc": "https://r2.test/asset"}
                state.assets.append(a)
                return self._json(201, {"status": "success", "data": a})
            self._json(404, {"message": "not found"})
    return H


@pytest.fixture()
def fake_icard():
    state = FakeIcard()
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _handler(state))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    state.server = f"http://127.0.0.1:{srv.server_address[1]}/api/v1"
    yield state
    srv.shutdown()
