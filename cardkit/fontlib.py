"""Thư viện font: font có sẵn + font khách tự thêm (thư mục fonts/).

Mỗi font: id (để bản thiết kế / ô chữ tham chiếu), nhóm (viết tay / có chân / không chân / trang trí),
mô tả cho AI, có đủ dấu tiếng Việt không, có được phép nhúng không (OS/2 fsType), giấy phép ghi trong font.
Thông tin người dùng sửa (nhóm, mô tả, tên) lưu ở fonts/fonts.json, theo tên file.
"""
from __future__ import annotations

import io
import json
import re
from pathlib import Path

from .config import ConfigError

KINDS = {"script": "Viết tay", "serif": "Có chân", "sans": "Không chân", "deco": "Trang trí"}
FONT_INFO = {   # font có sẵn của tool
    "ImperialScript-Regular.ttf": ("imperial", "script", "chữ viết tay cổ điển, nét lượn bay bổng (hợp tên cô dâu chú rể)"),
    "GreatVibes-Regular.ttf": ("greatvibes", "script", "chữ viết tay đậm, mềm, dễ đọc"),
    "PinyonScript-Regular.ttf": ("pinyon", "script", "chữ viết tay thanh mảnh kiểu thư pháp Anh"),
    "CormorantGaramond-Variable.ttf": ("cormorant", "serif",
                                       "chữ có chân thanh lịch, cổ điển, đậm 300–700 (hợp tiêu đề, lời mời, thông tin)"),
}
_VI = "ăâđêôơưàảãáạằẳẵắặầẩẫấậèẻẽéẹềểễếệìỉĩíịòỏõóọồổỗốộờởỡớợùủũúụừửữứựỳỷỹýỵ"
VI_CHARS = _VI + _VI.upper()
EXTS = (".ttf", ".otf", ".woff", ".woff2")
MAX_BYTES = 25 * 1024 * 1024
_cache: dict[tuple[str, float], dict] = {}


def _slug(s: str) -> str:
    from .kitgen import slugify
    return slugify(s)


def fonts_dir(root: Path) -> Path:
    return Path(root) / "fonts"


def _reg_path(root: Path) -> Path:
    return fonts_dir(root) / "fonts.json"


def registry(root: Path) -> dict:
    p = _reg_path(root)
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    except (OSError, ValueError):
        return {}


def _save_registry(root: Path, reg: dict) -> None:
    _reg_path(root).write_text(json.dumps(reg, ensure_ascii=False, indent=2), encoding="utf-8")


def guess_kind(tt, family: str) -> str:
    """Đoán nhóm font từ tên + bảng OS/2 (sFamilyClass, PANOSE)."""
    name = family.lower()
    if any(w in name for w in ("script", "hand", "brush", "signature", "callig", "vibes", "pinyon", "dancing",
                               "writing", "pen ", "allura", "parisienne", "sacramento")):
        return "script"
    if any(w in name for w in ("sans", "grotesk", "grotesque", "gothic")):
        return "sans"
    os2 = tt["OS/2"] if "OS/2" in tt else None
    if os2 is not None:
        cls = (getattr(os2, "sFamilyClass", 0) >> 8) & 0xFF
        if cls == 10:
            return "script"
        if cls == 9:
            return "deco"
        if cls == 8:
            return "sans"
        if 1 <= cls <= 7:
            return "serif"
        p = getattr(os2, "panose", None)
        if p is not None:
            if p.bFamilyType == 3:
                return "script"
            if p.bFamilyType == 4:
                return "deco"
            if p.bFamilyType == 2 and p.bSerifStyle in (11, 12, 13):
                return "sans"
            if p.bFamilyType == 2 and 2 <= p.bSerifStyle <= 10:
                return "serif"
    return "sans"


def inspect_font(path: Path) -> dict:
    """Thông tin kỹ thuật của một file font (có cache theo thời điểm sửa file)."""
    from fontTools.ttLib import TTFont
    path = Path(path)
    key = (str(path), path.stat().st_mtime)
    if key in _cache:
        return _cache[key]
    tt = TTFont(path, lazy=True)
    nm = tt["name"]
    family = str(nm.getBestFamilyName() or path.stem)
    sub = str(nm.getBestSubFamilyName() or "Regular")
    cmap = tt.getBestCmap() or {}
    missing = [c for c in VI_CHARS if ord(c) not in cmap]
    fs = getattr(tt["OS/2"], "fsType", 0) if "OS/2" in tt else 0
    lic = str(nm.getDebugName(13) or "").strip()
    url = str(nm.getDebugName(14) or "").strip()
    variable = "fvar" in tt
    info = {"family": family, "style": sub, "variable": variable,
            "label": family if variable or sub.lower() in ("regular", "normal", "book", "roman") else f"{family} {sub}",
            "vi_missing": "".join(dict.fromkeys(missing)), "embed_ok": not (fs & 0x0002),
            "license": (lic[:300] + ("…" if len(lic) > 300 else "")), "license_url": url,
            "ofl": "open font license" in (lic + url).lower() or "openfontlicense" in url.lower() or "ofl" in url.lower(),
            "kind_guess": guess_kind(tt, family + " " + sub)}
    tt.close()
    _cache[key] = info
    return info


def list_fonts(root: Path) -> list[dict]:
    reg = registry(root)
    out, ids = [], set()
    for f in sorted(fonts_dir(root).glob("*")):
        if f.suffix.lower() not in (".ttf", ".otf"):
            continue
        try:
            info = inspect_font(f)
        except Exception:                 # file hỏng: bỏ qua, không làm sập cả danh sách
            continue
        fid, kind, desc = FONT_INFO.get(f.name, (None, None, ""))
        r = reg.get(f.name, {})
        fid = r.get("id") or fid or _slug(info["label"])
        base, n = fid, 2
        while fid in ids:
            fid, n = f"{base}_{n}", n + 1
        ids.add(fid)
        kind = r.get("kind") or kind or info["kind_guess"]
        out.append({"id": fid, "file": f"fonts/{f.name}", "label": r.get("label") or info["label"], "kind": kind,
                    "kind_label": KINDS.get(kind, kind), "desc": r.get("desc", desc) or "",
                    "builtin": f.name in FONT_INFO, "uploaded": bool(r.get("uploaded")),
                    **{k: info[k] for k in ("family", "style", "variable", "vi_missing", "embed_ok", "license",
                                            "license_url", "ofl")}})
    return out


def font_file(root: Path, fid: str) -> Path | None:
    for f in list_fonts(root):
        if f["id"] == fid:
            return Path(root) / f["file"]
    return None


def add_font(root: Path, filename: str, data: bytes) -> dict:
    """Thêm một file font. woff/woff2 được đổi sang ttf/otf (Chromium và Pillow đều đọc được)."""
    from fontTools.ttLib import TTFont
    ext = Path(filename).suffix.lower()
    if ext not in EXTS:
        raise ConfigError("Chỉ nhận file font .ttf, .otf, .woff hoặc .woff2.")
    if len(data) > MAX_BYTES:
        raise ConfigError("File font quá lớn (tối đa 25 MB).")
    try:
        tt = TTFont(io.BytesIO(data))
        tt["name"]
    except Exception:
        raise ConfigError(f"'{filename}' không phải file font hợp lệ.") from None
    if "glyf" not in tt and "CFF " not in tt and "CFF2" not in tt:
        raise ConfigError(f"'{filename}' không chứa nét chữ (có thể là font màu/bitmap) – hãy dùng font .ttf/.otf thường.")
    out_ext = ".otf" if ("CFF " in tt or "CFF2" in tt) else ".ttf"
    nm = tt["name"]
    family = str(nm.getBestFamilyName() or Path(filename).stem)
    sub = str(nm.getBestSubFamilyName() or "Regular")
    stem = re.sub(r"[^A-Za-z0-9]+", "", family) or "Font"
    if sub.lower() not in ("regular", "normal", "book", "roman"):
        stem += "-" + (re.sub(r"[^A-Za-z0-9]+", "", sub) or "Style")
    d = fonts_dir(root)
    d.mkdir(exist_ok=True)
    dest, n = d / f"{stem}{out_ext}", 2
    while dest.exists():
        dest, n = d / f"{stem}_{n}{out_ext}", n + 1
    if ext in (".woff", ".woff2"):
        tt.flavor = None
        tt.save(dest)
    else:
        dest.write_bytes(data)
    tt.close()
    info = inspect_font(dest)
    lic = info["license"]
    if lic:                                   # giấy phép đi kèm font khi giao khách
        (d / f"{dest.stem}-LICENSE.txt").write_text(lic + ("\n" + info["license_url"] if info["license_url"] else ""),
                                                    encoding="utf-8")
    ids = {f["id"] for f in list_fonts(root) if f["file"] != f"fonts/{dest.name}"}    # trừ chính file vừa lưu
    fid, k = _slug(info["label"]), 2
    base = fid
    while fid in ids:
        fid, k = f"{base}_{k}", k + 1
    reg = registry(root)
    reg[dest.name] = {"id": fid, "kind": info["kind_guess"], "label": info["label"], "desc": "", "uploaded": True}
    _save_registry(root, reg)
    return next(f for f in list_fonts(root) if f["file"] == f"fonts/{dest.name}")


def update_font(root: Path, fid: str, kind: str | None = None, desc: str | None = None, label: str | None = None) -> dict:
    f = next((x for x in list_fonts(root) if x["id"] == fid), None)
    if f is None:
        raise ConfigError(f"Không có font '{fid}'.")
    if kind is not None and kind not in KINDS:
        raise ConfigError("Nhóm font không hợp lệ.")
    reg = registry(root)
    r = reg.setdefault(Path(f["file"]).name, {"id": fid})
    r["id"] = fid
    if kind is not None:
        r["kind"] = kind
    if desc is not None:
        r["desc"] = desc.strip()[:200]
    if label is not None and label.strip():
        r["label"] = label.strip()[:80]
    _save_registry(root, reg)
    return next(x for x in list_fonts(root) if x["id"] == fid)


def fonts_in_use(root: Path, f: dict) -> list[str]:
    """Các mẫu đang dùng font này (theo file hoặc theo id ở ô chữ)."""
    used = []
    for kj in (Path(root) / "kits").glob("*/kit.json"):
        try:
            data = json.loads(kj.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        hit = f["file"] in data.get("fonts", {}).values() or f["id"] in data.get("fonts", {})
        if not hit:
            for lp in (kj.parent / "layouts").glob("*.json"):
                try:
                    if any(t.get("font") == f["id"] for t in json.loads(lp.read_text(encoding="utf-8")).get("texts", [])):
                        hit = True
                        break
                except (OSError, ValueError):
                    continue
        if hit:
            used.append(data.get("title") or kj.parent.name)
    return used


def delete_font(root: Path, fid: str) -> None:
    f = next((x for x in list_fonts(root) if x["id"] == fid), None)
    if f is None:
        raise ConfigError(f"Không có font '{fid}'.")
    if f["builtin"]:
        raise ConfigError("Font có sẵn của tool không xoá được.")
    used = fonts_in_use(root, f)
    if used:
        raise ConfigError(f"Font đang được dùng ở mẫu: {', '.join(used)} – đổi font ở các mẫu đó trước khi xoá.")
    p = Path(root) / f["file"]
    p.unlink(missing_ok=True)
    (p.parent / f"{p.stem}-LICENSE.txt").unlink(missing_ok=True)
    reg = registry(root)
    reg.pop(p.name, None)
    _save_registry(root, reg)
