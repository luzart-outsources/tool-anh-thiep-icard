"""Đóng gói bản giao khách: dist/ThiepTool-<phiên bản>.zip (chạy được trên macOS và Windows).

Gói gồm: 2 nút mở ("Mở Tool (Mac).command", "Mở Tool (Windows).bat"), "Hướng dẫn.html" và app/ (mã cardkit, font,
bố cục có sẵn, script khởi động). KHÔNG gồm mẫu, ảnh, thiệp đã xuất của máy này.
Lần đầu khách mở, script tự tải bộ chạy uv → Python 3.12 + thư viện (cần mạng), rồi mở trình duyệt.

Chạy: python tools/build_release.py
"""
import shutil
import stat
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from cardkit import __version__  # noqa: E402
from cardkit.fontlib import FONT_INFO  # noqa: E402
from cardkit.studio import LAYOUT_ORDER  # noqa: E402

REL = ROOT / "release"
EXEC = {".command", ".sh"}                 # cần quyền chạy trên macOS
LF = {".command", ".sh"}                   # script Unix: xuống dòng LF
CRLF = {".bat", ".ps1"}                    # script Windows: CRLF


def _write_text(src: Path, dst: Path) -> None:
    t = src.read_text(encoding="utf-8-sig").replace("\r\n", "\n")   # -sig: bỏ BOM có sẵn (run.ps1) → không bị 2 BOM
    if dst.suffix in CRLF:
        t = t.replace("\n", "\r\n")
    data = t.encode("utf-8")
    if dst.suffix == ".ps1":
        data = b"\xef\xbb\xbf" + data      # PowerShell 5.1 cần BOM mới đọc đúng tiếng Việt
    dst.write_bytes(data)


def build() -> Path:
    out = ROOT / "dist" / "ThiepTool"
    if out.exists():
        shutil.rmtree(out)
    app = out / "app"
    app.mkdir(parents=True)
    shutil.copytree(ROOT / "cardkit", app / "cardkit", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    (app / "fonts").mkdir()
    for f in (ROOT / "fonts").iterdir():   # chỉ font có sẵn + giấy phép OFL (không lẫn font tự thêm trên máy này)
        if f.name in FONT_INFO or f.name.startswith("OFL"):
            shutil.copy2(f, app / "fonts" / f.name)
    (app / "layouts").mkdir()
    for name in LAYOUT_ORDER:              # chỉ thư viện bố cục có sẵn (không lẫn bố cục tự làm)
        shutil.copy2(ROOT / "layouts" / f"{name}.json", app / "layouts" / f"{name}.json")
    for f in (REL / "app").iterdir():
        if f.suffix in LF | CRLF:
            _write_text(f, app / f.name)
        else:
            shutil.copy2(f, app / f.name)
    (app / "VERSION").write_text(__version__ + "\n", encoding="utf-8")
    for f in REL.iterdir():
        if f.is_file():
            if f.suffix in LF | CRLF:
                _write_text(f, out / f.name)
            else:
                shutil.copy2(f, out / f.name)
    zp = ROOT / "dist" / f"ThiepTool-{__version__}.zip"
    zp.unlink(missing_ok=True)
    with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for p in sorted(out.rglob("*")):
            arc = "ThiepTool/" + p.relative_to(out).as_posix() + ("/" if p.is_dir() else "")
            zi = zipfile.ZipInfo(arc, date_time=(2026, 10, 2, 12, 0, 0))
            zi.create_system = 3            # Unix → macOS giữ quyền chạy cho .command / .sh
            if p.is_dir():
                zi.external_attr = (stat.S_IFDIR | 0o755) << 16 | 0x10
                z.writestr(zi, b"")
            else:
                mode = 0o755 if p.suffix in EXEC else 0o644
                zi.external_attr = (stat.S_IFREG | mode) << 16
                zi.compress_type = zipfile.ZIP_DEFLATED
                z.writestr(zi, p.read_bytes())
    return zp


if __name__ == "__main__":
    zp = build()
    print(f"Đã đóng gói: {zp} ({zp.stat().st_size / 1e6:.1f} MB)")
