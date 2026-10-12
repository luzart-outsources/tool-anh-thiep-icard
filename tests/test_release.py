"""Bản giao khách: gói zip đúng nội dung + quyền chạy trên macOS; dữ liệu khách tách riêng khỏi thư mục tool."""
import stat
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_prepare_data_copies_builtins_without_overwriting(tmp_path):
    from cardkit.launch import prepare_data
    data = tmp_path / "Documents" / "ThiepTool"
    added = prepare_data(data)
    assert (data / "kits").is_dir() and (data / "output").is_dir()
    assert (data / "fonts" / "ImperialScript-Regular.ttf").exists() and (data / "layouts" / "bia.json").exists()
    assert "layouts/bia.json" in added
    (data / "layouts" / "bia.json").write_text("{}", encoding="utf-8")       # khách đã sửa → không bị ghi đè
    assert prepare_data(data) == [] and (data / "layouts" / "bia.json").read_text(encoding="utf-8") == "{}"


def test_build_release_zip(tmp_path):
    r = subprocess.run([sys.executable, str(ROOT / "tools" / "build_release.py")], capture_output=True, cwd=ROOT,
                       env={**__import__("os").environ, "PYTHONIOENCODING": "utf-8"})
    assert r.returncode == 0, r.stderr.decode("utf-8", "replace")
    from cardkit import __version__
    z = zipfile.ZipFile(ROOT / "dist" / f"ThiepTool-{__version__}.zip")
    names = {i.filename: i for i in z.infolist()}
    mac = names["ThiepTool/Mở Tool (Mac).command"]
    assert (mac.external_attr >> 16) & stat.S_IXUSR and mac.flag_bits & 0x800          # chạy được + tên UTF-8
    assert (names["ThiepTool/app/run.sh"].external_attr >> 16) & stat.S_IXUSR
    assert b"\r" not in z.read("ThiepTool/app/run.sh") and z.read("ThiepTool/app/run.ps1")[:3] == b"\xef\xbb\xbf"
    assert b"\r\n" in z.read("ThiepTool/Mở Tool (Windows).bat")
    assert "ThiepTool/Hướng dẫn.html" in names and "ThiepTool/app/cardkit/launch.py" in names
    assert not any(n.startswith(("ThiepTool/app/kits", "ThiepTool/app/output", "ThiepTool/app/tests"))
                   or "__pycache__" in n or n.endswith("fonts.json") for n in names)  # không lẫn dữ liệu máy này
    req = z.read("ThiepTool/app/requirements-app.txt").decode()
    assert "opencv-python-headless" in req and "playwright" in req and "pytest" not in req
    assert "requests" in req                                                    # đăng lên Icard


# ---------------------------------------------------------------- bản cài bằng git (khách tự clone)

BOM = b"\xef\xbb\xbf"


def test_git_launchers_line_endings_and_bom():
    """Bash trên macOS lỗi với CRLF; PowerShell 5.1 đọc sai tiếng Việt nếu .ps1 thiếu BOM."""
    for f in ("MoTool-Mac.command", "release/app/run.sh", "release/Mở Tool (Mac).command"):
        b = (ROOT / f).read_bytes()
        assert b"\r" not in b and b.startswith(b"#!/bin/bash"), f
    for f in ("MoTool-Windows.bat", "release/Mở Tool (Windows).bat"):
        b = (ROOT / f).read_bytes()
        assert b.count(b"\r\n") == b.count(b"\n"), f
    ps = (ROOT / "release" / "app" / "run.ps1").read_bytes()
    assert ps.startswith(BOM) and not ps[3:].startswith(BOM) and ps.count(b"\r\n") == ps.count(b"\n")
    attrs = (ROOT / ".gitattributes").read_text(encoding="utf-8")
    for rule in ("*.sh       text eol=lf", "*.command  text eol=lf", "*.bat      text eol=crlf", "*.ps1      text eol=crlf"):
        assert rule in attrs


def test_gitignore_ships_builtins_only():
    """.gitignore khớp đúng font + bố cục có sẵn trong mã (thêm bố cục mới mà quên .gitignore → test báo)."""
    from cardkit.fontlib import FONT_INFO
    from cardkit.studio import LAYOUT_ORDER
    lines = set((ROOT / ".gitignore").read_text(encoding="utf-8").splitlines())
    assert {"/kits/", "/output/", "/dist/", "/fonts/*", "/layouts/*", "/MoTool.bat"} <= lines
    assert {f"!/layouts/{n}.json" for n in LAYOUT_ORDER} <= lines
    assert {f"!/fonts/{n}" for n in FONT_INFO} <= lines


def _bash():
    import shutil
    return shutil.which("bash")


def test_launchers_find_code_in_git_clone_and_in_zip(tmp_path):
    """run.sh / run.ps1 tìm đúng thư mục mã: repo git (<repo>/release/app/) và gói zip (ThiepTool/app/)."""
    import os
    import shutil
    env = {**os.environ, "THIEPTOOL_PRINT_PATHS": "1"}
    repo = tmp_path / "repo"
    (repo / "cardkit").mkdir(parents=True)
    shutil.copytree(ROOT / "release" / "app", repo / "release" / "app")
    zipapp = tmp_path / "ThiepTool" / "app"
    shutil.copytree(ROOT / "release" / "app", zipapp)
    (zipapp / "cardkit").mkdir()
    cases = [(repo / "release" / "app", repo), (zipapp, zipapp)]
    if _bash():
        for script_dir, want in cases:
            assert subprocess.run([_bash(), "-n", str(script_dir / "run.sh")]).returncode == 0
            out = subprocess.run([_bash(), str(script_dir / "run.sh")], env=env, capture_output=True,
                                 text=True, encoding="utf-8").stdout.split("\n")
            assert out[0].rstrip("/").endswith(want.name) and out[1].endswith("requirements-app.txt")
    if sys.platform == "win32":
        for script_dir, want in cases:
            out = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                                  str(script_dir / "run.ps1")], env=env, capture_output=True, text=True,
                                 encoding="utf-8").stdout.split("\n")
            assert Path(out[0].strip()) == want and out[1].strip().endswith("requirements-app.txt")
