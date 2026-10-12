"""Khởi động bản giao khách (bấm đúp "Mở Tool").

- Dữ liệu của khách (mẫu, font tự thêm, thiệp đã xuất) ở thư mục riêng – mặc định Documents/ThiepTool – nên thay
  bản tool mới không mất gì. Font và bố cục có sẵn được chép sang lần đầu (và bổ sung file mới khi cập nhật).
- Dựng chữ cần một trình duyệt Chromium: dùng Chrome/Edge có sẵn trên máy; không có thì tự tải bản gọn (một lần).
- Rồi mở bàn làm việc trên trình duyệt.

Chạy: python -m cardkit.launch --data <thư mục dữ liệu>
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

from . import __version__

APP = Path(__file__).resolve().parents[1]          # thư mục chứa cardkit/, fonts/, layouts/


def default_data_dir() -> Path:
    return Path.home() / "Documents" / "ThiepTool"


def prepare_data(data: Path, app: Path = APP) -> list[str]:
    """Tạo thư mục dữ liệu; chép font + bố cục có sẵn còn thiếu (không ghi đè thứ khách đã sửa)."""
    added = []
    for sub in ("kits", "output", "fonts", "layouts"):
        (data / sub).mkdir(parents=True, exist_ok=True)
    for sub in ("fonts", "layouts"):
        src = app / sub
        if not src.exists():
            continue
        for f in src.iterdir():
            dst = data / sub / f.name
            if f.is_file() and not dst.exists() and f.name != "fonts.json":
                shutil.copy2(f, dst)
                added.append(f"{sub}/{f.name}")
    return added


def ensure_browser(log=print) -> str:
    """Trình duyệt dùng để dựng chữ. Không có Chrome/Edge và chưa tải bản gọn → tải bản gọn (một lần)."""
    from .textlayer import browser_status
    ok = browser_status()
    if ok:
        return ok
    log("  Máy chưa có Chrome/Edge – đang tải trình duyệt dựng chữ (một lần, khoảng 100 MB)…")
    cmd = [sys.executable, "-m", "playwright", "install", "chromium", "--only-shell"]
    if subprocess.run(cmd).returncode != 0:
        subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"])
    ok = browser_status()
    if not ok:
        log("  ⚠ Chưa có trình duyệt dựng chữ – vẫn mở được tool, nhưng xuất thiệp sẽ báo lỗi. Cài Google Chrome rồi mở lại.")
    return ok or ""


def main(argv=None) -> None:
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(prog="cardkit.launch")
    ap.add_argument("--data", default=str(default_data_dir()))
    ap.add_argument("--port", type=int, default=8800)
    ap.add_argument("--no-browser", action="store_true", help="không tự mở trình duyệt")
    ap.add_argument("--check", action="store_true", help="chỉ chuẩn bị + kiểm tra, không mở bàn làm việc")
    a = ap.parse_args(argv)
    data = Path(a.data).expanduser().resolve()
    prepare_data(data)
    print(f"  Phiên bản {__version__} · dữ liệu của bạn: {data}")
    br = ensure_browser()
    if br:
        print(f"  Dựng chữ bằng: {br}")
    if a.check:
        return
    from .config import Project
    from .studio import serve
    print("  Đang mở bàn làm việc trên trình duyệt… (ĐỪNG đóng cửa sổ này khi còn dùng tool)\n")
    serve(Project(data), port=a.port, open_browser=not a.no_browser)


if __name__ == "__main__":
    main()
