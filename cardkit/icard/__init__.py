"""Đăng mẫu thiệp lên Icard (kho mẫu thiệp online).

convert  – thiệp đã xuất (manifest + pieces) → templateData của Icard (hàm thuần, không mạng)
fonts    – font cardkit → font trên Icard (tách bản tĩnh từ font biến thiên)
client   – gọi API admin của Icard
publish  – điều phối: dựng thiệp → chuyển → up ảnh/font → tạo hoặc cập nhật mẫu
"""
import re

DEFAULT_SERVER = "https://adminapi.icards.com.vn/api/v1"
# Địa chỉ web của Icard mà người dùng hay dán nhầm (trang chủ, trang đăng nhập, trang admin, API khách)
ICARD_HOSTS = {"icards.com.vn", "www.icards.com.vn", "admin.icards.com.vn", "api.icards.com.vn",
               "adminapi.icards.com.vn"}


def normalize_server(url: str | None) -> str:
    """Địa chỉ người dùng gõ → địa chỉ API admin. Mọi địa chỉ thuộc icards.com.vn → API admin production;
    server khác (vd. chạy thử trên máy) giữ nguyên, chỉ bỏ dấu '/' cuối."""
    u = (url or "").strip()
    if not u:
        return DEFAULT_SERVER
    host = re.sub(r"^[a-z]+://", "", u, flags=re.I).split("/")[0].split(":")[0].lower()
    if host in ICARD_HOSTS:
        return DEFAULT_SERVER
    return u.rstrip("/")
