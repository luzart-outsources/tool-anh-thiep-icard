"""Nạp câu trả lời của ChatGPT (theo PROMPT MẸ) → tạo bộ (kit) mới hoàn chỉnh.

AI chỉ lo phần sáng tạo (phong cách, màu, mô tả từng món); phần kỹ thuật (font, kiểu chữ,
bóng đổ, cách tô ánh kim, quy tắc dọn rác) do tool tự suy ra để luôn chạy được.
"""
from __future__ import annotations

import json
import re
import unicodedata

from .catalog import BY_ID
from .config import ConfigError, Kit, Project
from .fills import hex_rgb

FONT_FILES = {"imperial": "fonts/ImperialScript-Regular.ttf", "pinyon": "fonts/PinyonScript-Regular.ttf",
              "greatvibes": "fonts/GreatVibes-Regular.ttf"}
HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


def slugify(s: str) -> str:
    s = unicodedata.normalize("NFD", s.replace("đ", "d").replace("Đ", "D"))
    s = "".join(c for c in s if unicodedata.category(c) != "Mn").lower()
    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", s)).strip("_") or "bo_moi"


def _strip_comments(raw: str) -> str:
    """Bỏ chú thích // … và /* … */ nằm NGOÀI chuỗi (ChatGPT hay chép cả chú thích của ví dụ)."""
    out, i, n, in_str = [], 0, len(raw), False
    while i < n:
        c = raw[i]
        if in_str:
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(raw[i + 1])
                i += 2
                continue
            if c == '"':
                in_str = False
        elif c == '"':
            in_str = True
            out.append(c)
        elif raw.startswith("//", i):
            while i < n and raw[i] != "\n":
                i += 1
            continue
        elif raw.startswith("/*", i):
            j = raw.find("*/", i + 2)
            i = n if j < 0 else j + 2
            continue
        else:
            out.append(c)
        i += 1
    return "".join(out)


def extract_json(text: str) -> dict:
    """Lấy khối JSON trong câu trả lời của ChatGPT (chịu được ```json, lời dẫn, chú thích, dấu phẩy thừa, ngoặc cong)."""
    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    raw = m.group(1) if m else text[text.find("{"): text.rfind("}") + 1]
    if not raw.strip():
        raise ConfigError("Không thấy khối JSON nào trong nội dung dán vào. Hãy chép NGUYÊN câu trả lời của ChatGPT.")
    quoted = _strip_comments(raw.replace("“", '"').replace("”", '"'))
    attempts = [raw, _strip_comments(raw), quoted, re.sub(r",\s*([}\]])", r"\1", quoted)]
    for cand in attempts:
        try:
            data = json.loads(cand)
            break
        except json.JSONDecodeError as e:
            err = e
    else:
        raise ConfigError(f"Khối JSON bị lỗi cú pháp (dòng {err.lineno}, cột {err.colno}): {err.msg}. "
                          "Thử bảo ChatGPT: \"Chỉ trả lại đúng khối JSON hợp lệ\".")
    if not isinstance(data, dict):
        raise ConfigError("Nội dung dán vào không phải một đối tượng JSON.")
    return data


def parse_ai_reply(text: str) -> dict:
    """Câu trả lời cho prompt mẹ kiểu cũ (có mục "assets")."""
    data = extract_json(text)
    if not isinstance(data.get("assets"), dict) or not data["assets"]:
        raise ConfigError("Khối JSON thiếu mục \"assets\" (mô tả từng món).")
    return data


def _lum(h: str) -> float:
    r, g, b = hex_rgb(h)
    return 0.299 * r + 0.587 * g + 0.114 * b


def _colors(v, n_min=1) -> list[str]:
    return [c for c in (v or []) if isinstance(c, str) and HEX.match(c.strip())][:6] if isinstance(v, list) else []


def build_kit_json(data: dict) -> tuple[dict, list[str]]:
    notes = []
    palette = _colors(data.get("palette")) or ["#1b3a2a"]
    orn = _colors(data.get("ornament_colors")) or ["#c9a24b"]
    txt = _colors(data.get("text_colors"))
    if len(txt) != 3:
        srt = sorted(orn, key=_lum)
        txt = [srt[0], srt[len(srt) // 2], srt[-1]]
        notes.append("Thiếu/không đủ 3 màu chữ (text_colors) → lấy từ màu hoa văn.")
    dark, mid, light = sorted(txt, key=_lum)
    dark_bg = _lum(palette[0]) < 110
    font_key = str(data.get("script_font", "imperial")).lower().replace(" ", "")
    if font_key not in FONT_FILES:
        notes.append(f"Kiểu chữ '{font_key}' không có → dùng 'imperial'.")
        font_key = "imperial"
    sh = ("drop-shadow(0 3px 2px rgba(0,0,0,.6))" if dark_bg else "drop-shadow(0 1.5px 1px rgba(90,60,20,.35))")
    sh_small = ("drop-shadow(0 2px 1.5px rgba(0,0,0,.65))" if dark_bg else "drop-shadow(0 1px 1px rgba(90,60,20,.3))")
    assets = {"nen": {"kind": "background", "label": "Nền giấy", "desc": data.get("background_desc", "")}}
    for aid, desc in data["assets"].items():
        aid = slugify(aid)
        if aid == "nen":
            continue
        m = BY_ID.get(aid)
        if m is None:
            notes.append(f"Món '{aid}' không có trong danh mục chuẩn → coi là hoa văn tự do (layout có sẵn không dùng tới).")
        assets[aid] = {"role": m.role if m else "ornament", "label": m.label if m else aid, "desc": str(desc).strip()}
    has_dark_ornament = any(_lum(c) < 70 for c in orn)
    kit = {
        "name": "",
        "title": data.get("tieu_de") or data.get("ten_bo") or "Bộ mới",
        "style": data.get("style", ""),
        "background_desc": data.get("background_desc", ""),
        "reference_prompt": data.get("reference_prompt", ""),
        "palette": palette,
        "ornament_colors": orn,
        "key_color": "auto",
        "fills": {
            "gold": {"type": "gradient", "angle": 170,
                     "stops": [[dark, 0], [mid, 0.28], [light, 0.46], [mid, 0.63], [light, 0.8], [dark, 1]]},
            "gold_line": {"type": "gradient", "angle": 135,
                          "stops": [[dark, 0], [light, 0.35], [mid, 0.6], [light, 0.85], [dark, 1]]},
        },
        "fonts": {"script": FONT_FILES[font_key], "serif": "fonts/CormorantGaramond-Variable.ttf"},
        "text_styles": {
            "script": {"font": "script", "fill": "gold", "size": 260, "shadow": sh},
            "caps": {"font": "serif", "weight": 600, "fill": "gold", "uppercase": True, "letter_spacing": "0.07em",
                     "numeric": "lining-nums", "size": 90, "shadow": sh_small},
            "caps_wide": {"font": "serif", "weight": 600, "fill": "gold", "uppercase": True,
                          "letter_spacing": "0.12em", "numeric": "lining-nums", "size": 46, "shadow": sh_small},
            "body": {"font": "serif", "weight": 600, "fill": "gold", "size": 60, "line_height": 1.07,
                     "numeric": "lining-nums", "shadow": sh_small},
            "monogram": {"font": "serif", "weight": 500, "fill": "gold", "uppercase": True, "size": 200,
                         "separator": {"width": 3, "height": 1.05, "gap": 0.22, "drop": -0.12}, "shadow": sh},
        },
        # hoa văn có màu tối thì không được bỏ pixel tối (sẽ ăn mất nét)
        "drop_baked_shadow": not has_dark_ornament,
        "ornament_shadow": ({"dx": 0, "dy": 3, "blur": 3, "opacity": 0.45, "color": "#000000"} if dark_bg
                            else {"dx": 0, "dy": 2, "blur": 3, "opacity": 0.22, "color": "#5a4020"}),
        "background": {"vignette": 0.0},
        "assets": assets,
    }
    return kit, notes


def create_kit(prj: Project, reply_text: str, overwrite: bool = False) -> tuple[Kit, list[str]]:
    data = parse_ai_reply(reply_text)
    kit_json, notes = build_kit_json(data)
    base = slugify(str(data.get("ten_bo") or data.get("tieu_de") or "bo_moi"))
    name, n = base, 2
    while (prj.kits_dir / name / "kit.json").exists() and not overwrite:
        name, n = f"{base}_{n}", n + 1
    if name != base:
        notes.append(f"Đã có mẫu '{base}' → đặt tên mẫu mới là '{name}'.")
    d = prj.kits_dir / name
    (d / "raw").mkdir(parents=True, exist_ok=True)
    (d / "assets").mkdir(exist_ok=True)
    kit_json["name"] = name
    (d / "kit.json").write_text(json.dumps(kit_json, ensure_ascii=False, indent=2), encoding="utf-8")
    (d / "ai_reply.txt").write_text(reply_text, encoding="utf-8")   # lưu bản gốc để tra lại
    kit = prj.kit(name)
    from .prompts import write_prompts
    write_prompts(kit)
    return kit, notes


# ---------------------------------------------------------------- tạo mẫu thẳng từ ý tưởng (không qua JSON)

DEFAULT_TEXT = ["#7a5a22", "#b08a45", "#e2c58a"]


def create_kit_from_idea(prj: Project, idea: str, ids: list[str], title: str = "") -> Kit:
    """Mẫu mới từ ý tưởng + danh sách món. Màu sắc sẽ được đo lại từ ảnh thật (derive_colors)."""
    from .catalog import BY_ID
    from .plan import VI, plan_sheets
    ids = [i for i in dict.fromkeys(ids) if i in BY_ID] or ["nen", "goc", "khung", "div_dai", "hoa_nho"]
    title = title.strip() or (" ".join(idea.split()[:5]) if idea.strip() else "Mẫu mới")
    data = {"tieu_de": title, "style": idea, "background_desc": "", "palette": ["#f2e9d8"],
            "ornament_colors": ["#c9a24b"], "text_colors": DEFAULT_TEXT, "script_font": "imperial",
            "assets": {i: VI.get(i, BY_ID[i].hint) for i in ids if i != "nen"}}
    kit_json, _ = build_kit_json(data)
    kit_json["assets"]["nen"]["desc"] = VI["nen"]
    base, name, n = slugify(title), slugify(title), 2
    while (prj.kits_dir / name / "kit.json").exists():
        name, n = f"{base}_{n}", n + 1
    d = prj.kits_dir / name
    (d / "raw").mkdir(parents=True, exist_ok=True)
    (d / "assets").mkdir(exist_ok=True)
    kit_json.update(name=name, title=title, idea=idea, plan=plan_sheets(ids), colors_from_images=False)
    (d / "kit.json").write_text(json.dumps(kit_json, ensure_ascii=False, indent=2), encoding="utf-8")
    return prj.kit(name)


def readable_metal(dark: str, mid: str, light: str, bg: str) -> tuple[str, str, str]:
    """Dải ánh kim đọc được trên nền: nền sáng → hạ độ sáng các màu (giữ sắc), nền tối → nâng lên.

    Chữ tô gradient vàng có màu sáng nhất gần trùng nền ngà sẽ gần như vô hình (lỗi gặp khi thử thật).
    """
    lb = _lum(bg)

    def scale(h: str, target: float, up: bool) -> str:
        r, g, b = (int(h[i:i + 2], 16) for i in (1, 3, 5))
        lum = _lum(h)
        if not up and lum > target:
            f = target / max(lum, 1)
            r, g, b = r * f, g * f, b * f
        elif up and lum < target:
            t = (target - lum) / max(255 - lum, 1)
            r, g, b = r + (255 - r) * t, g + (255 - g) * t, b + (255 - b) * t
        return "#%02x%02x%02x" % tuple(int(round(min(255, max(0, v)))) for v in (r, g, b))

    if lb >= 150:
        return scale(dark, lb - 140, False), scale(mid, lb - 100, False), scale(light, lb - 65, False)
    if lb <= 110:
        return scale(dark, lb + 70, True), scale(mid, lb + 110, True), scale(light, lb + 150, True)
    return dark, mid, light


def _hex(c) -> str:
    return "#%02x%02x%02x" % tuple(int(round(v)) for v in c)


def derive_colors(kit: Kit) -> dict | None:
    """Đo màu từ ảnh thật: màu nền thiệp, màu hoa văn, dải màu chữ ánh kim, độ đậm bóng.

    Chính xác hơn mã màu AI tự khai, và không cần người dùng nhập gì.
    """
    import numpy as np
    from PIL import Image
    rng = np.random.default_rng(0)
    px = []
    for aid, a in kit.assets.items():
        p = kit.assets_dir / f"{aid}.png"
        if aid == "nen" or not p.exists():
            continue
        arr = np.asarray(Image.open(p).convert("RGBA"))
        sel = arr[arr[..., 3] > 220][:, :3].astype(np.float32)
        if len(sel):
            px.append(sel[rng.choice(len(sel), min(len(sel), 15000), replace=False)])
    if not px:
        return None
    P = np.concatenate(px)
    lum = P @ np.array([0.299, 0.587, 0.114], np.float32)
    sat = (P.max(1) - P.min(1)) / np.maximum(P.max(1), 1)
    metal = P[(sat > 0.12) & (lum > 50)] if ((sat > 0.12) & (lum > 50)).sum() > 300 else P
    ml = metal @ np.array([0.299, 0.587, 0.114], np.float32)
    band = lambda lo, hi: np.median(metal[(ml >= np.percentile(ml, lo)) & (ml <= np.percentile(ml, hi))], axis=0)
    c_dark, c_mid, c_light = band(8, 25), band(40, 60), band(80, 96)
    lw = np.array([0.299, 0.587, 0.114], np.float32)
    if float((c_light - c_dark) @ lw) < 45:   # hoa văn gần như một màu → tự tạo dải ánh kim quanh màu chính
        c_dark = c_mid * 0.62
        c_light = c_mid + (255 - c_mid) * 0.45
    dark, mid, light = _hex(np.clip(c_dark, 0, 255)), _hex(c_mid), _hex(np.clip(c_light, 0, 255))
    nen0 = kit.assets_dir / "nen.png"
    bg0 = _hex(np.median(np.asarray(Image.open(nen0).convert("RGB")).reshape(-1, 3), axis=0)) if nen0.exists() \
        else (kit.data.get("background", {}).get("color") or kit.data.get("palette", ["#f2e9d8"])[0])
    dark, mid, light = readable_metal(dark, mid, light, bg0)
    import cv2
    _, _, centers = cv2.kmeans(P, 4, None, (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 20, 1.0), 2,
                               cv2.KMEANS_PP_CENTERS)
    ornament = [_hex(c) for c in sorted(centers, key=lambda c: -float(c @ np.array([.299, .587, .114])))]
    bg = kit.data.get("palette", ["#f2e9d8"])[0]
    nen = kit.assets_dir / "nen.png"
    if nen.exists():
        bg = _hex(np.median(np.asarray(Image.open(nen).convert("RGB")).reshape(-1, 3), axis=0))
    d = kit.data
    fresh, _ = build_kit_json({"palette": [bg], "ornament_colors": ornament, "text_colors": [dark, mid, light],
                               "script_font": "imperial", "assets": {"x": ""}})
    d["palette"] = [bg] + ornament
    d["ornament_colors"] = ornament
    # Mẫu từ bản thiết kế: chỉ đo lại các kiểu tô "ánh kim theo hoa văn"; màu chữ AI chọn (mực, màu nhấn) giữ nguyên
    for k in d.get("auto_fills", ["gold", "gold_line"]):
        if k in fresh["fills"]:
            d.setdefault("fills", {})[k] = fresh["fills"][k]
    for k, st in fresh["text_styles"].items():          # chỉ đổi bóng chữ theo nền sáng/tối, giữ font đã chọn
        if k in d.get("text_styles", {}):
            d["text_styles"][k]["shadow"] = st["shadow"]
    if d.get("auto_shadow", True):
        d["ornament_shadow"] = fresh["ornament_shadow"]
    d["colors_from_images"] = True
    (kit.dir / "kit.json").write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"bg": bg, "text": [dark, mid, light], "ornament": ornament}
