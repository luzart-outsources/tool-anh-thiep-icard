"""Gọi API admin của Icard (icards-dashboard-backend).

Đăng nhập trả JWT trong cookie httpOnly `token` (không có header Bearer) → giữ trong requests.Session,
chỉ trong bộ nhớ. Mật khẩu không được lưu ở đâu.
"""
from __future__ import annotations

import json

from . import DEFAULT_SERVER, normalize_server

UPLOAD_CHUNK = 12          # số ảnh mỗi lần upload-batch (Icard xử lý song song trong 1 request)


class IcardError(RuntimeError):
    def __init__(self, msg: str, status: int = 0):
        super().__init__(msg)
        self.status = status


def _message(r) -> str:
    try:
        j = r.json()
        return str(j.get("message") or j.get("error") or "")
    except ValueError:
        text = r.text or ""
        if "html" in str(r.headers.get("Content-Type", "")).lower() or text.lstrip()[:15].lower().startswith(("<!doctype", "<html")):
            return ("địa chỉ này là trang web, không phải API Icard – dùng " + DEFAULT_SERVER)
        return text[:200]


class IcardClient:
    def __init__(self, server: str = DEFAULT_SERVER, timeout: float = 120, session=None):
        import requests
        self.server = normalize_server(server)
        self.timeout = timeout
        self.s = session or requests.Session()
        self.s.headers.update({"Accept": "application/json"})
        self.user: dict | None = None

    # ---------------------------------------------------------------- HTTP

    def _req(self, method: str, path: str, *, what: str, ok=(200, 201, 204), **kw):
        import requests
        try:
            r = self.s.request(method, self.server + path, timeout=self.timeout, **kw)
        except requests.RequestException as e:
            raise IcardError(f"Không kết nối được Icard ({self.server}) khi {what}: {type(e).__name__}.") from None
        if r.status_code in ok:
            if r.status_code == 204 or not r.content:
                return {}
            try:
                return r.json()
            except ValueError:
                raise IcardError(f"Không đọc được phản hồi khi {what}: {_message(r) or 'không phải JSON'}.",
                                 r.status_code) from None
        msg = _message(r)
        if r.status_code == 401:
            self.user = None
            raise IcardError("Phiên đăng nhập Icard đã hết hạn hoặc chưa đăng nhập – hãy đăng nhập lại.", 401)
        if r.status_code == 403:
            raise IcardError(f"Tài khoản Icard không đủ quyền để {what}" + (f" ({msg})" if msg else "") + ".", 403)
        raise IcardError(f"Icard báo lỗi khi {what} (HTTP {r.status_code})" + (f": {msg}" if msg else "."),
                         r.status_code)

    # ---------------------------------------------------------------- tài khoản

    def login(self, login: str, password: str) -> dict:
        if not login or not password:
            raise IcardError("Nhập tên đăng nhập (hoặc email) và mật khẩu Icard.")
        try:
            j = self._req("POST", "/admin/auth/login", json={"login": login, "password": password},
                          what="đăng nhập", ok=(200,))
        except IcardError as e:
            if e.status == 401:
                raise IcardError("Sai tên đăng nhập hoặc mật khẩu Icard.", 401) from None
            raise
        if j.get("status") == "error":
            raise IcardError(j.get("message") or "Đăng nhập Icard thất bại.")
        self.user = j.get("user") or (j.get("data") or {}).get("user") or {}
        return self.user

    def me(self) -> dict:
        j = self._req("GET", "/admin/users/me", what="kiểm tra tài khoản")
        self.user = j.get("data") or j.get("user") or j
        return self.user

    @property
    def role(self) -> str:
        return str((self.user or {}).get("role", ""))

    def logout(self) -> None:
        self.s.cookies.clear()
        self.user = None

    # ---------------------------------------------------------------- dữ liệu

    def taxonomy(self) -> list[dict]:
        """Cây phân loại thiệp: [{title, children:[{title, children:[{title}]}]}] (category → group → type)."""
        j = self._req("GET", "/admin/settings", what="đọc danh mục thiệp")
        data = j.get("data") or {}
        return data.get("headerNav") or []

    def fonts(self) -> list[dict]:
        j = self._req("GET", "/admin/fonts", what="đọc danh sách font")
        return j.get("data") or []

    def upload_batch(self, files: dict[str, tuple[str, bytes, str]]) -> dict[str, str]:
        """files: tên field → (tên file, dữ liệu, mime). Trả tên field → URL ảnh trên Icard."""
        out: dict[str, str] = {}
        items = list(files.items())
        for i in range(0, len(items), UPLOAD_CHUNK):
            part = items[i:i + UPLOAD_CHUNK]
            j = self._req("POST", "/admin/assets/upload-batch", files=[(k, v) for k, v in part], what="upload ảnh")
            urls = j.get("urls") or {}
            missing = [k for k, _ in part if k not in urls]
            if missing:
                raise IcardError(f"Icard không trả URL cho {len(missing)} ảnh vừa upload.")
            out.update(urls)
        return out

    def _template_form(self, fields: dict) -> dict:
        form = {}
        for k, v in fields.items():
            if v is None:
                continue
            if isinstance(v, (dict, list)):
                v = json.dumps(v, ensure_ascii=False)
            elif isinstance(v, bool):
                v = "true" if v else "false"
            form[k] = str(v)
        return form

    def create_template(self, fields: dict, thumbnail: bytes) -> dict:
        j = self._req("POST", "/admin/templates", data=self._template_form(fields),
                      files=[("image", ("thumbnail.webp", thumbnail, "image/webp"))], what="tạo mẫu thiệp",
                      ok=(200, 201))
        return j.get("data") or j

    def update_template(self, tid: str, fields: dict, thumbnail: bytes | None = None) -> dict:
        files = [("generatedThumbnail", ("thumbnail.webp", thumbnail, "image/webp"))] if thumbnail else None
        j = self._req("PUT", f"/admin/templates/{tid}", data=self._template_form(fields), files=files,
                      what="cập nhật mẫu thiệp")
        return j.get("data") or j

    def get_template(self, tid: str) -> dict | None:
        try:
            j = self._req("GET", f"/admin/templates/{tid}", what="đọc mẫu thiệp")
        except IcardError as e:
            if e.status in (400, 404):
                return None
            raise
        return j.get("data") or j

    def delete_template(self, tid: str) -> None:
        self._req("DELETE", f"/admin/templates/{tid}", what="xoá mẫu thiệp")

    def create_font(self, name: str, category: str, data: bytes, filename: str) -> dict:
        j = self._req("POST", "/admin/fonts", data={"name": name, "category": category},
                      files=[("font", (filename, data, "font/ttf"))], what=f"đăng font '{name}'", ok=(200, 201))
        return j.get("data") or j

    def create_design_asset(self, name: str, asset_type: str, category: str, png: bytes) -> dict:
        j = self._req("POST", "/design-assets", data={"name": name, "assetType": asset_type, "category": category},
                      files=[("image", (f"{asset_type}.png", png, "image/png"))], what=f"đăng hoa văn '{name}'",
                      ok=(200, 201))
        return j.get("data") or j
