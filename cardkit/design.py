"""Bản thiết kế linh động: khách mô tả tự do → AI (ChatGPT) trả về MỘT JSON mô tả cả bộ thiệp → tool dựng.

AI quyết định: bao nhiêu thiệp, khổ nào (dọc/ngang/vuông/banner), hình dáng (có sẵn hoặc đường cắt SVG tự vẽ),
những món hoa văn nào (tự đặt tên, tự mô tả), bố cục từng phương án, ô chữ, ô ảnh, font, màu.
Tool giữ phần máy móc: đọc & tự sửa bản thiết kế, báo lỗi bố cục, gom món thành tờ để vẽ, tách nền, ghép, dựng chữ.

Toạ độ: mọi thiệp rộng UNIT = 1000; cao = 1000 × cao/rộng của khổ.
"""
from __future__ import annotations

import json
import re

from .config import ConfigError, Kit, Project, load_json
from .kitgen import DEFAULT_TEXT, extract_json, slugify
from .shapes import IDS as SHAPE_IDS, check_path
from .sizes import resolve_size

UNIT = 1000.0
KINDS = ("big", "wide", "tall", "small")
COLOR_KEYS = ("text", "accent", "metal")

# Bộ thiệp online luôn có ít nhất 4 trang lật cùng khổ (chuẩn mẫu cưới trên Icard) – thứ tự = thứ tự trang
PAGE_ROLES = {
    "bia": ("Bìa", "chữ lồng hoặc tiêu đề (Thiệp thành hôn / Save the date), tên cô dâu chú rể, ngày cưới"),
    "gia_dinh": ("Thông tin hai gia đình", "Lễ thành hôn, nhà trai – nhà gái: bố mẹ, địa chỉ hai bên, tên hai bạn"),
    "thiep_moi": ("Thiệp mời", "lời mời, ô tên khách mời (id \"khach\"), tên hai bạn, giờ, ngày, địa điểm, địa chỉ"),
    "cam_on": ("Cảm ơn", "lời cảm ơn khách đã đến chung vui, tên hai bạn, lời kết (With love)"),
}
# từ khoá nhận vai trò khi AI không khai "role" – xét theo thứ tự này ("Bìa thiệp mời" là bìa)
_ROLE_WORDS = [("cam_on", ("cam_on", "thank", "cam_ta")), ("gia_dinh", ("gia_dinh", "family", "nha_trai", "nha_gai")),
               ("bia", ("bia", "cover", "save_the_date", "trang_dau")),
               ("thiep_moi", ("thiep_moi", "loi_moi", "moi", "invitation", "invite", "join_us"))]


def infer_role(card_id: str, name: str = "") -> str:
    """Vai trò trang của một thiệp (bia | gia_dinh | thiep_moi | cam_on | khac) theo id / tên."""
    words = f"_{slugify(card_id)}_{slugify(name)}_"         # khớp nguyên từ: "_moi_" không khớp "moi_nhat"
    for role, keys in _ROLE_WORDS:
        if any(f"_{k}_" in words for k in keys):
            return role
    return "khac"


def card_role(card: dict) -> str:
    return card.get("role") or infer_role(card.get("id", ""), card.get("name", ""))   # bản thiết kế cũ: chưa có role


def missing_pages(design: dict) -> list[str]:
    have = {card_role(c) for c in design.get("cards", [])}
    return [r for r in PAGE_ROLES if r not in have]


def pages_message(design: dict) -> str:
    """Tin nhắn nhờ ChatGPT thêm các trang còn thiếu (rỗng nếu đủ 4 trang)."""
    miss = missing_pages(design)
    if not miss:
        return ""
    cards = design.get("cards", [])
    size = next((c["size"] for c in cards if card_role(c) in PAGE_ROLES), cards[0]["size"] if cards else "15x21")
    lines = "\n".join(f"- role \"{r}\" – {PAGE_ROLES[r][0]}: {PAGE_ROLES[r][1]}" for r in miss)
    return (f"Bộ thiệp online cần ĐỦ 4 trang cùng khổ (Bìa · Thông tin hai gia đình · Thiệp mời · Cảm ơn). Bản thiết kế "
            f"còn THIẾU trang:\n{lines}\nHãy THÊM các thiệp này vào \"cards\" (đúng role ở trên, khổ \"{size}\", cùng hình "
            "dáng với các thiệp hiện có), mỗi thiệp 1–2 phương án. DÙNG LẠI các item đã có, chỉ thêm item mới khi thật "
            f"cần; giữ nguyên các thiệp và phương án cũ. Ô chữ trùng nội dung với thiệp khác thì dùng CÙNG id. {FULL_JSON}")

def available_fonts(prj: Project) -> dict:
    """Font AI được chọn: mọi font trong thư viện (có sẵn + khách tự thêm) có đủ dấu tiếng Việt."""
    from .fontlib import list_fonts
    out = {}
    for f in list_fonts(prj.root):
        if f["vi_missing"]:
            continue
        desc = f["desc"] or f"{f['kind_label'].lower()} – {f['label']}"
        out[f["id"]] = {"file": f["file"], "kind": f["kind"], "desc": desc}
    return out


# ---------------------------------------------------------------- prompt cho ChatGPT

EXAMPLE = {
    "title": "Cúc trắng tối giản",
    "style": "delicate watercolor white daisies with soft sage-green leaves, airy and minimal, fine ink outlines",
    "background": {"color": "#F7F3EC", "draw": "soft cotton paper texture, warm ivory, very subtle fibers"},
    "colors": {"text": "#4E4A3F", "accent": "#9DAE8C", "metallic": False},
    "fonts": {
        "ten": {"font": "imperial", "weight": 400, "uppercase": False, "letter_spacing": 0, "color": "text"},
        "chu": {"font": "cormorant", "weight": 500, "uppercase": True, "letter_spacing": 0.12, "color": "text"},
    },
    "items": [
        {"id": "cum_cuc", "name": "Cụm cúc góc", "shape": "big", "hollow": False, "backdrop": False,
         "draw": "a loose cluster of white daisies and sage leaves for the TOP-LEFT corner, spreading right and down, "
                 "asymmetric"},
        {"id": "nhanh_la", "name": "Nhành lá mảnh", "shape": "small", "hollow": False, "backdrop": False,
         "draw": "one slender sage sprig lying horizontally, pointing right"},
    ],
    "cards": [{
        "id": "thiep_moi", "name": "Thiệp mời", "role": "thiep_moi", "size": "15x21cm", "shape": "bo_goc",
        "variants": [{
            "name": "Hoa góc chéo",
            "border": [{"inset": 28, "width": 2, "color": "accent"}],
            "items": [
                {"item": "cum_cuc", "x": 190, "y": 210, "w": 380, "h": 380, "rotate": 0, "flip": "", "mirror": "",
                 "opacity": 1},
                {"item": "cum_cuc", "x": 810, "y": 1190, "w": 380, "h": 380, "rotate": 0, "flip": "hv", "mirror": "",
                 "opacity": 1},
                {"item": "nhanh_la", "x": 500, "y": 700, "w": 160, "h": 60, "rotate": 0, "flip": "", "mirror": "",
                 "opacity": 1},
            ],
            "texts": [
                {"id": "loi_moi", "label": "Lời mời", "style": "chu", "text": "Trân trọng kính mời",
                 "x": 500, "y": 470, "w": 700, "size": 30, "align": "center"},
                {"id": "ten_chu_re", "label": "Tên chú rể", "style": "ten", "text": "Gia Minh",
                 "x": 500, "y": 600, "w": 760, "size": 110, "align": "center"},
                {"id": "ten_co_dau", "label": "Tên cô dâu", "style": "ten", "text": "Ái Ngọc",
                 "x": 500, "y": 820, "w": 760, "size": 110, "align": "center"},
                {"id": "ngay_cuoi", "label": "Ngày cưới", "style": "chu", "text": "15 . 12 . 2026",
                 "x": 500, "y": 960, "w": 600, "size": 36, "align": "center"},
            ],
            "photos": [],
        }],
    }],
}

PROMPT = """Bạn là nhà thiết kế thiệp cưới. Hãy lên BẢN THIẾT KẾ cho yêu cầu dưới đây.
Bước này CHƯA vẽ ảnh – chỉ trả về JSON. Một phần mềm sẽ dựng thiệp từ JSON này thành các lớp riêng (nền / hoa văn / chữ) cho website.

YÊU CẦU CỦA KHÁCH:
\"\"\"
<<REQUEST>>
\"\"\"

PHẦN MỀM DỰNG THIỆP THẾ NÀO (hãy thiết kế cho đúng cách này):
1. Mỗi hoa văn trong "items" sẽ được vẽ RIÊNG thành một ảnh (ở các tin nhắn sau, chính bạn sẽ vẽ), rồi được đặt lên thiệp theo toạ độ. Một item dùng lại được nhiều lần, ở nhiều thiệp: phóng to/thu nhỏ, lật, xoay, nhân đối xứng → dùng ÍT item nhưng dùng khéo (thường 4–10 item cho cả bộ, tối đa 14).
2. Chữ KHÔNG nằm trong ảnh: phần mềm dựng chữ bằng font thật theo các ô chữ trong "texts".
3. Nền thiệp: một màu phẳng, hoặc thêm một ảnh nền giấy/vân (khi background.draw có mô tả).
4. Hình dáng thiệp: chọn hình có sẵn hoặc tự vẽ đường cắt bằng SVG path.
5. Có thể thêm ô ảnh ("photos") để website chèn ảnh cô dâu chú rể.

SỐ LƯỢNG – BẮT BUỘC: bộ thiệp luôn có ÍT NHẤT 4 THIỆP CÙNG KHỔ, CÙNG HÌNH DÁNG – đó là 4 trang lật của thiệp cưới online, theo đúng thứ tự:
<<PAGES>>
Khách chỉ nhắc một thiệp (vd. "thiệp mời 15x21") thì vẫn làm đủ 4 thiệp trên, theo khổ đó. Khách muốn thêm thiệp khác (banner web, thiệp hình trái tim, thiệp cảm ơn rời…) thì thêm SAU 4 thiệp này với "role": "khac". Không nói khổ thì dùng 15x21cm. Số phương án mỗi thiệp theo yêu cầu khách (không nói thì 1–2). Các phương án của cùng một thiệp phải KHÁC NHAU RÕ RỆT (bố cục, vị trí hoa văn, nhịp chữ), không chỉ xê dịch nhẹ.

HỆ TOẠ ĐỘ: mọi thiệp rộng 1000 đơn vị; cao = 1000 × (cao ÷ rộng của khổ). Ví dụ 15x21cm → cao 1400; vuông → 1000; 1920x1080px → cao 562.5. Gốc (0,0) ở góc trên-trái, y tăng xuống dưới. Chừa lề ≥ 40 với mép thiệp; với hình không phải chữ nhật, mọi chữ phải nằm gọn trong hình.

TRẢ VỀ DUY NHẤT một khối ```json đúng cấu trúc như ví dụ (ví dụ chỉ minh hoạ cấu trúc với MỘT thiệp – bản của bạn phải đủ 4 thiệp như trên; nội dung làm theo yêu cầu khách):
<<EXAMPLE>>

Ý NGHĨA CÁC TRƯỜNG:
- style: phong cách vẽ CHUNG cho mọi hoa văn, viết bằng TIẾNG ANH (chất liệu, màu, nét, độ chi tiết).
- background.color: màu nền #RRGGBB. background.draw: mô tả ảnh nền giấy bằng tiếng Anh, hoặc "" nếu chỉ dùng màu phẳng.
- colors.text: màu chữ thường; colors.accent: màu nhấn (viền, chi tiết); colors.metallic: true nếu chữ/viền ánh kim (vàng, đồng…), khi đó thêm colors.metal = [màu tối, màu giữa, màu sáng]. Chữ phải đọc rõ trên nền: nền sáng thì màu chữ đủ đậm, nền tối thì đủ sáng.
- fonts: các kiểu chữ dùng trong bộ (đặt tên tuỳ ý). "font" chọn một trong: <<FONTS>>. "color": "text" | "accent" | "metal" | "#RRGGBB".
- items[].shape: "big" (món lớn: khung, vòng hoa, cụm hoa lớn) | "wide" (dải ngang dẹt) | "tall" (cao hẹp) | "small" (hoạ tiết nhỏ). items[].hollow: true nếu món rỗng giữa để đặt chữ/ảnh bên trong (khung, vòng hoa). items[].backdrop: true nếu món là lớp nền trang trí để chữ nằm đè lên (mảng màu nước loang, dải màu mờ, chấm/sao rải rác). items[].draw: mô tả để vẽ RIÊNG món đó, bằng tiếng Anh, nói rõ hướng (vd. "for the TOP-LEFT corner, growing diagonally toward the center") và đối xứng hay không. Hoa văn không bao giờ có chữ.
- cards[].role: "bia" | "gia_dinh" | "thiep_moi" | "cam_on" | "khac" (vai trò trang, xem phần SỐ LƯỢNG).
- cards[].size: vd. "15x21cm", "15x15cm", "21x15cm", "1080x1920px", "1920x1080px". cards[].shape: một trong <<SHAPES>>, hoặc {"path": "M … Z"} – SVG path tuyệt đối theo hệ toạ độ của chính thiệp đó, khép kín, phủ gần hết khung (vd. trái tim, vỏ sò, cái vé, vòm đôi, lục giác).
- variants[].items: x,y = TÂM của món; w,h = ô chứa món (ảnh được thu vừa trong ô, giữ tỉ lệ); rotate = độ, theo chiều kim đồng hồ; flip = "h" (lật ngang) | "v" (lật dọc) | "hv" | ""; mirror = "x" (thêm bản đối xứng trái↔phải qua trục giữa thiệp) | "y" (trên↔dưới) | "xy" (4 góc) | ""; opacity 0.1–1.
- variants[].border: các nét viền chạy song song mép hình dáng: inset = cách mép, width = độ dày, color như trên. [] = không viền.
- variants[].texts: id không dấu, có nghĩa (ten_chu_re, ten_co_dau, ngay_cuoi, gio, dia_diem…); nội dung giống nhau ở các thiệp thì dùng CÙNG id; ô tên khách mời dùng id "khach" (web tự điền tên từng khách). label = tên ô bằng tiếng Việt; text = chữ mẫu tiếng Việt có dấu (xuống dòng bằng \\n); x = tâm ngang, y = tâm dòng chữ; w = bề rộng tối đa (chữ dài hơn tự thu nhỏ); size = cỡ chữ (tên cô dâu chú rể khoảng 70–140, chữ thường 26–40); align = "center" | "left" | "right".
- variants[].photos: ô ảnh (x,y = tâm; w,h; shape như cards[].shape nhưng path theo khung riêng của ô). [] nếu không cần."""


def design_prompt(request: str, fonts: dict) -> str:
    font_list = "; ".join(f'"{fid}" ({f["desc"]})' for fid, f in fonts.items())
    shapes = ", ".join(f'"{s}"' for s in SHAPE_IDS + ["trai_tim"])
    pages = "\n".join(f'{i}. "{r}" – {lbl}: {desc}' for i, (r, (lbl, desc)) in enumerate(PAGE_ROLES.items(), 1))
    return (PROMPT.replace("<<PAGES>>", pages)
            .replace("<<REQUEST>>", request.strip() or "(khách chưa ghi yêu cầu – hãy tự đề xuất một bộ thiệp cưới đẹp)")
            .replace("<<EXAMPLE>>", "```json\n" + json.dumps(EXAMPLE, ensure_ascii=False, indent=1) + "\n```")
            .replace("<<FONTS>>", font_list).replace("<<SHAPES>>", shapes))


FULL_JSON = "Gửi lại TOÀN BỘ bản thiết kế (đủ mọi mục, cùng cấu trúc) trong MỘT khối ```json."


def fix_message(problems: dict) -> str:
    lines = "\n".join(f"- {where}: {p}" for where, ps in problems.items() for p in ps)
    return (f"Bản thiết kế còn vài lỗi bố cục, hãy sửa (chỉ sửa toạ độ/cỡ chữ cho hết lỗi, giữ nguyên ý tưởng):\n{lines}\n"
            f"{FULL_JSON}")


def more_message(card_name: str, n: int) -> str:
    return (f"Thêm {n} phương án bố cục MỚI cho thiệp \"{card_name}\", khác hẳn các phương án hiện có. "
            f"DÙNG LẠI các item đã có (không thêm item mới), giữ nguyên các phương án cũ. {FULL_JSON}")


def change_message(text: str) -> str:
    return (f"Sửa bản thiết kế theo yêu cầu sau: {text.strip()}\n"
            f"Giữ nguyên các item đã có (id và mô tả) nếu không cần đổi; chỉ thêm item mới khi thật cần. {FULL_JSON}")


# ---------------------------------------------------------------- đọc & chuẩn hoá câu trả lời của AI

_HEX = re.compile(r"^#?([0-9a-fA-F]{6}|[0-9a-fA-F]{3})$")


def _num(v, default=None, lo=None, hi=None):
    try:
        x = float(str(v).replace("em", "").replace("px", "").strip()) if isinstance(v, str) else float(v)
    except (TypeError, ValueError):
        return default
    if x != x:
        return default
    if lo is not None:
        x = max(lo, x)
    if hi is not None:
        x = min(hi, x)
    return round(x, 2)


def _hex(v, default):
    if isinstance(v, str) and _HEX.match(v.strip()):
        h = v.strip().lstrip("#")
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        return "#" + h.lower()
    return default


def _lum(h: str) -> float:
    r, g, b = (int(h[i:i + 2], 16) for i in (1, 3, 5))
    return 0.299 * r + 0.587 * g + 0.114 * b


def _get(d, *keys, default=None):
    if isinstance(d, dict):
        for k in keys:
            if k in d and d[k] not in (None, ""):
                return d[k]
    return default


def _color(v, default="text"):
    if isinstance(v, str):
        k = slugify(v)
        if k in COLOR_KEYS:
            return k
        if k in ("gold", "vang", "kim", "metallic", "anh_kim"):
            return "metal"
        h = _hex(v, None)
        if h:
            return h
    return default


def heart_path(W: float, H: float) -> str:
    """Trái tim chiếm gần hết khung (đỉnh lõm ở 30% chiều cao)."""
    f = lambda x, y: f"{x * W:.1f} {y * H:.1f}"
    return (f"M{f(.5, .97)} C{f(.18, .74)} {f(.02, .52)} {f(.03, .3)} C{f(.04, .1)} {f(.24, .02)} {f(.36, .03)} "
            f"C{f(.44, .04)} {f(.49, .1)} {f(.5, .18)} C{f(.51, .1)} {f(.56, .04)} {f(.64, .03)} "
            f"C{f(.76, .02)} {f(.96, .1)} {f(.97, .3)} C{f(.98, .52)} {f(.82, .74)} {f(.5, .97)} Z")


_SHAPE_ALIAS = {"rectangle": "chu_nhat", "rect": "chu_nhat", "hinh_chu_nhat": "chu_nhat", "square": "chu_nhat",
                "vuong": "chu_nhat", "rounded": "bo_goc", "rounded_rectangle": "bo_goc", "arch": "vom",
                "ellipse": "oval", "circle": "oval", "tron": "oval", "scallop": "rang_cua", "scalloped": "rang_cua",
                "cut_corner": "cat_goc", "octagon": "cat_goc"}


def _shape(v, W: float, H: float, notes: list, where: str):
    """Hình dáng → tên hình có sẵn hoặc {"path", "label"}; hình lỗi thì về chữ nhật và ghi chú."""
    path, label = None, None
    if isinstance(v, dict):
        path, label = _get(v, "path", "d"), _get(v, "label", "name", "ten")
        if not path:
            v = _get(v, "preset", "id", default="chu_nhat")
    if isinstance(v, str) and not path:
        s = v.strip()
        if s[:1] in ("M", "m") and re.search(r"\d", s):
            path = s
        else:
            k = slugify(s)
            k = _SHAPE_ALIAS.get(k, k)
            if k in SHAPE_IDS:
                return k
            if k in ("trai_tim", "heart", "tim"):
                return {"path": heart_path(W, H), "label": "Trái tim"}
            notes.append(f"{where}: không có hình dáng '{s}' → dùng hình chữ nhật.")
            return "chu_nhat"
    if path:
        err = check_path(str(path), W, H)
        if err:
            notes.append(f"{where}: {err} → dùng hình chữ nhật.")
            return "chu_nhat"
        return {"path": str(path), "label": str(label or "Hình riêng")}
    return "chu_nhat"


def _size(v, notes: list, where: str) -> dict:
    s = str(v or "a5").lower().replace("×", "x").replace(",", ".")
    m = re.search(r"(\d+(?:\.\d+)?)\s*x\s*(\d+(?:\.\d+)?)\s*(px|cm|mm)?", s)
    if m:
        a, b, unit = float(m.group(1)), float(m.group(2)), m.group(3) or ("px" if float(m.group(1)) > 80 else "cm")
        if unit == "mm":
            a, b, unit = a / 10, b / 10, "cm"
        spec = f"{a:g}x{b:g}" + ("px" if unit == "px" else "")
    else:
        spec = {"a4": "21x29.7", "a6": "10.5x14.8"}.get(re.sub(r"[^a-z0-9]", "", s), re.sub(r"[^a-z0-9.]", "", s))
    try:
        return resolve_size(spec)
    except ConfigError:
        notes.append(f"{where}: khổ '{v}' không đọc được → dùng A5 (14,8 × 21 cm).")
        return resolve_size("a5")


def _resolve_font(v, fonts: dict, prefer: str) -> tuple[str, bool]:
    """Tên font AI ghi (vd. "Imperial Script", "cormorant") → id font có sẵn. Trả về (id, có khớp không)."""
    key = re.sub(r"[^a-z0-9]", "", str(v or "").lower())
    for fid, f in fonts.items():
        stem = re.sub(r"[^a-z0-9]", "", f["file"].rsplit("/", 1)[-1].rsplit(".", 1)[0].lower())
        if key and (key == fid or key in stem or fid in key):
            return fid, True
    kind = "script" if any(w in key for w in ("script", "viettay", "hand", "calli")) else prefer
    for fid, f in fonts.items():
        if f["kind"] == kind:
            return fid, False
    return next(iter(fonts)), False


BACKDROP_WORDS = ("wash", "translucent", "transparen", "texture", "scatter", "speck", "dots", "confetti", "bokeh",
                  "glow", "haze", "mist", "backdrop", "background", "loang", "mảng màu", "rải rác", "chấm", "nền mờ")


def normalize_design(raw: dict, fonts: dict) -> tuple[dict, list[str]]:
    """Câu trả lời của AI → bản thiết kế chuẩn (đủ trường, số hợp lệ, id duy nhất) + ghi chú những gì đã tự sửa."""
    if not fonts:
        raise ConfigError("Thư mục fonts/ chưa có font nào.")
    notes: list[str] = []
    title = str(_get(raw, "title", "ten_bo", "name", default="Bộ thiệp mới")).strip()[:80]
    style = str(_get(raw, "style", "phong_cach", default="")).strip()
    bg_raw = _get(raw, "background", "nen", default={})
    if isinstance(bg_raw, str):
        bg_raw = {"color": bg_raw} if _HEX.match(bg_raw.strip()) else {"draw": bg_raw}
    background = {"color": _hex(_get(bg_raw, "color", "mau"), "#f6f1e7"),
                  "draw": str(_get(bg_raw, "draw", "ve", "mo_ta", default="")).strip()}
    col = _get(raw, "colors", "mau", default={}) or {}
    colors = {"text": _hex(_get(col, "text", "chu"), "#4a3f35"), "accent": _hex(_get(col, "accent", "nhan"), "#b08a45"),
              "metallic": bool(_get(col, "metallic", "anh_kim", default=False))}
    metal = sorted([c for c in (_hex(x, None) for x in (col.get("metal") or [])) if c], key=_lum) \
        if isinstance(col.get("metal"), list) else []
    if len(metal) >= 2:
        colors["metal"] = [metal[0], metal[len(metal) // 2] if len(metal) > 2 else metal[-1], metal[-1]]
    elif colors["metallic"]:
        colors["metal"] = list(DEFAULT_TEXT)

    # kiểu chữ
    fr = _get(raw, "fonts", "styles", "text_styles", "kieu_chu", default={}) or {}
    if isinstance(fr, list):
        fr = {str(_get(x, "id", "name", default=f"kieu{i}")): x for i, x in enumerate(fr) if isinstance(x, dict)}
    styles = {}
    for name, st in fr.items():
        st = st if isinstance(st, dict) else {"font": st}
        sid = slugify(str(name))
        fid, ok = _resolve_font(st.get("font"), fonts, "serif")
        if not ok:
            notes.append(f"Kiểu chữ '{name}': không có font '{st.get('font')}' → dùng '{fid}'.")
        styles[sid] = {"font": fid, "weight": int(_num(st.get("weight"), 400, 100, 900)),
                       "uppercase": bool(st.get("uppercase", False)), "italic": bool(st.get("italic", False)),
                       "letter_spacing": _num(st.get("letter_spacing"), 0, 0, 0.6),
                       "color": _color(st.get("color"), "metal" if colors["metallic"] else "text")}
    if not styles:
        sc, _ = _resolve_font("script", fonts, "script")
        se, _ = _resolve_font("", fonts, "serif")
        c = "metal" if colors["metallic"] else "text"
        styles = {"ten": {"font": sc, "weight": 400, "uppercase": False, "italic": False, "letter_spacing": 0, "color": c},
                  "chu": {"font": se, "weight": 500, "uppercase": False, "italic": False, "letter_spacing": 0, "color": c}}
        notes.append("Bản thiết kế không khai báo kiểu chữ → dùng 2 kiểu mặc định (viết tay + có chân).")

    # món hoa văn
    items, ids, alias = [], set(), {}
    for it in _get(raw, "items", "mon", "ornaments", default=[]) or []:
        it = it if isinstance(it, dict) else {"id": str(it)}
        orig = str(_get(it, "id", "name", "ten", default="mon"))
        iid = slugify(orig)
        if iid in ("nen", "bo_moi"):
            iid = "mon_" + iid
        base, k = iid, 2
        while iid in ids:
            iid, k = f"{base}_{k}", k + 1
        ids.add(iid)
        alias.setdefault(orig, iid)
        alias.setdefault(slugify(orig), iid)
        kind = str(_get(it, "shape", "dang", "kind", default="small")).lower()
        if kind not in KINDS:
            kind = {"lon": "big", "ngang": "wide", "doc": "tall", "nho": "small"}.get(slugify(kind), "small")
        name = str(_get(it, "name", "ten", default=iid)).strip()
        draw = str(_get(it, "draw", "ve", "desc", "mo_ta", default="")).strip()
        backdrop = it.get("backdrop")
        if backdrop is None:              # AI không khai → đoán từ mô tả (mảng màu loang, chấm rải rác…)
            backdrop = any(w in f"{name} {draw}".lower() for w in BACKDROP_WORDS)
        items.append({"id": iid, "name": name, "draw": draw, "shape": kind, "hollow": bool(it.get("hollow", False)),
                      "backdrop": bool(backdrop)})
    names = {i["id"]: i["name"] for i in items}

    # thiệp + phương án
    cards, cids = [], set()
    for ci, c in enumerate(_get(raw, "cards", "thiep", default=[]) or [], 1):
        if not isinstance(c, dict):
            continue
        cid = slugify(str(_get(c, "id", "name", "ten", default=f"thiep_{ci}")))
        base, k = cid, 2
        while cid in cids:
            cid, k = f"{base}_{k}", k + 1
        cids.add(cid)
        cname = str(_get(c, "name", "ten", default=cid)).strip()
        z = _size(_get(c, "size", "kho"), notes, f"Thiệp '{cname}'")
        wh = z.get("cm") or z["px"]                       # theo cm cho tròn số (15x21 → cao 1400, như prompt dặn AI)
        W, H = UNIT, round(UNIT * wh[1] / wh[0], 1)
        shape = _shape(_get(c, "shape", "hinh", default="chu_nhat"), W, H, notes, f"Thiệp '{cname}'")
        variants = []
        for vi, v in enumerate(_get(c, "variants", "phuong_an", default=[]) or [], 1):
            if isinstance(v, dict):
                variants.append(_variant(v, vi, W, H, alias, names, styles, fonts, notes, cname))
        if not variants:
            notes.append(f"Thiệp '{cname}' không có phương án bố cục nào → bỏ.")
            continue
        role = slugify(str(_get(c, "role", "vai_tro", default="") or ""))
        if role not in PAGE_ROLES and role != "khac":              # AI không khai / khai sai → đoán theo id, tên
            role = infer_role(cid, cname)
        cards.append({"id": cid, "name": cname, "role": role, "size": z["id"], "size_label": z["label"],
                      "px": list(z["px"]), "canvas": {"w": W, "h": H}, "shape": shape, "variants": variants})
    order = list(PAGE_ROLES)
    cards.sort(key=lambda c: order.index(c["role"]) if c["role"] in order else len(order))   # thứ tự trang
    if not cards:
        raise ConfigError("Bản thiết kế không có thiệp nào dùng được (mục \"cards\" trống hoặc sai cấu trúc).")
    used = {e["item"] for c in cards for v in c["variants"] for e in v["items"]}
    unused = [i["name"] for i in items if i["id"] not in used]
    if unused:
        notes.append(f"Các món chưa được đặt vào thiệp nào: {', '.join(unused)} (vẫn được vẽ, dùng khi chỉnh tay).")
    return {"title": title, "style": style, "background": background, "colors": colors, "styles": styles,
            "items": items, "cards": cards}, notes


def _variant(v, k, W, H, alias, names, styles, fonts, notes, cname) -> dict:
    name = str(_get(v, "name", "ten", default=f"Phương án {k}")).strip()
    where = f"{cname} / {name}"
    elems = [e for e in (_get(v, "items", "mon", "ornaments", default=[]) or []) if isinstance(e, dict)]
    texts = [t for t in (_get(v, "texts", "chu", default=[]) or []) if isinstance(t, dict)]
    photos = [p for p in (_get(v, "photos", "anh", default=[]) or []) if isinstance(p, dict)]
    # AI đôi khi ghi toạ độ theo % (0–100) thay vì theo khung 1000 → tự quy đổi
    vals = [abs(_num(e.get(a), 0)) for e in elems + photos for a in ("x", "y", "w", "h")] + \
           [abs(_num(t.get(a), 0)) for t in texts for a in ("x", "y", "w")]
    fx = fy = 1.0
    if vals and max(vals) <= 100.5:
        fx, fy = W / 100, H / 100
        notes.append(f"{where}: toạ độ ghi theo % → đã quy đổi sang khung {W:g}×{H:g}.")
    br = _get(v, "border", "vien", default=[])
    if isinstance(br, (int, float)) and not isinstance(br, bool):
        br = [{"inset": br}]
    elif br is True:
        br = [{"inset": 30, "width": 2}]
    elif isinstance(br, dict):
        br = [br]
    border = [{"inset": _num(b.get("inset"), 30, 0, 300), "width": _num(b.get("width"), 2, 0.5, 40),
               "color": _color(b.get("color"), "accent")} for b in (br or []) if isinstance(b, dict)]
    out_items = []
    for e in elems:
        ref = str(_get(e, "item", "id", "mon", "asset", default=""))
        iid = alias.get(ref) or alias.get(slugify(ref))
        if not iid:
            notes.append(f"{where}: món '{ref}' không có trong danh sách items → bỏ.")
            continue
        x, y = _num(e.get("x")), _num(e.get("y"))
        if x is None or y is None:
            notes.append(f"{where}: món '{names.get(iid, iid)}' thiếu toạ độ x/y → bỏ.")
            continue
        w, h = _num(e.get("w"), None, 1), _num(e.get("h"), None, 1)
        el = {"item": iid, "x": round(x * fx, 1), "y": round(y * fy, 1)}
        if w is None and h is None:
            w = 250 / fx
        if w is not None:
            el["w"] = round(w * fx, 1)
        if h is not None:
            el["h"] = round(h * fy, 1)
        rot = _num(_get(e, "rotate", "xoay", default=0), 0, -360, 360)
        if rot:
            el["rotate"] = rot
        flip = "".join(ch for ch in "hv" if ch in str(e.get("flip") or "").lower())
        mirror = "".join(ch for ch in "xy" if ch in str(e.get("mirror") or "").lower())
        if flip:
            el["flip"] = flip
        if mirror:
            el["mirror"] = mirror
        op = _num(e.get("opacity"), 1, 0.05, 1)
        if op < 1:
            el["opacity"] = op
        out_items.append(el)
    first = next(iter(styles))
    by_kind = {fonts[s["font"]]["kind"]: sid for sid, s in reversed(list(styles.items())) if s["font"] in fonts}
    out_texts, tids = [], set()
    for t in texts:
        tid = slugify(str(_get(t, "id", "label", "nhan", default="chu")))
        base, n = tid, 2
        while tid in tids:
            tid, n = f"{base}_{n}", n + 1
        tids.add(tid)
        label = str(_get(t, "label", "nhan", default=tid)).strip()
        st = slugify(str(_get(t, "style", "kieu", "font", default="")))
        if st not in styles:
            guess = by_kind.get("script") if tid.startswith("ten") or tid == "va" else by_kind.get("serif")
            if st:
                notes.append(f"{where}: ô chữ '{label}' dùng kiểu '{st}' không có → dùng '{guess or first}'.")
            st = guess or first
        x, y = _num(t.get("x", t.get("cx"))), _num(t.get("y", t.get("cy")))
        if x is None or y is None:
            notes.append(f"{where}: ô chữ '{label}' thiếu toạ độ → bỏ.")
            continue
        align = str(t.get("align") or "center").lower()
        align = {"left": "left", "trai": "left", "right": "right", "phai": "right"}.get(slugify(align), "center")
        out_texts.append({"id": tid, "label": label, "style": st, "text": str(_get(t, "text", "noi_dung", default=label)),
                          "x": round(x * fx, 1), "y": round(y * fy, 1),
                          "w": round(_num(t.get("w"), 0.8 * W / fx, 20) * fx, 1),
                          "size": round(_num(t.get("size"), 40 / fx, 1) * fx, 1), "align": align})
    out_photos, pids = [], set()
    for p in photos:
        pid = slugify(str(_get(p, "id", "label", default="anh")))
        while pid in pids:
            pid += "_2"
        pids.add(pid)
        x, y, w, h = (_num(p.get(a)) for a in ("x", "y", "w", "h"))
        if None in (x, y, w, h):
            notes.append(f"{where}: ô ảnh '{pid}' thiếu x/y/w/h → bỏ.")
            continue
        w, h = max(10.0, w * fx), max(10.0, h * fy)
        out_photos.append({"id": pid, "label": str(_get(p, "label", default="Ảnh cưới")), "x": round(x * fx, 1),
                           "y": round(y * fy, 1), "w": round(w, 1), "h": round(h, 1),
                           "shape": _shape(_get(p, "shape", default="chu_nhat"), w, h, notes, f"{where} / ô ảnh")})
    return {"name": name, "border": border, "items": out_items, "texts": out_texts, "photos": out_photos}


# ---------------------------------------------------------------- bản thiết kế → bố cục (layout) của tool

def _fill(color: str, line: bool = False) -> str:
    if color == "metal":
        return "gold_line" if line else "gold"
    return {"text": "ink", "accent": "accent"}.get(color, color)


def variant_layout(design: dict, card: dict, k: int) -> dict:
    v = card["variants"][k]
    orn, groups = [], {}
    for ln in v["border"]:
        groups.setdefault(ln["color"], []).append({"inset": ln["inset"], "width": ln["width"]})
    for n, (col, lines) in enumerate(groups.items(), 1):
        orn.append({"id": "vien" if n == 1 else f"vien_{n}", "type": "border", "fill": _fill(col, True), "lines": lines})
    seen: dict[str, int] = {}
    for e in v["items"]:
        seen[e["item"]] = seen.get(e["item"], 0) + 1
        el = {"id": e["item"] if seen[e["item"]] == 1 else f"{e['item']}_{seen[e['item']]}", "asset": e["item"],
              "x": e["x"], "y": e["y"], "anchor": "c"}
        for key in ("w", "h", "rotate", "flip", "mirror", "opacity"):
            if key in e:
                el[key] = e[key]
        orn.append(el)
    texts = []
    for t in v["texts"]:
        tx = {"id": t["id"], "label": t["label"], "style": t["style"], "text": t["text"],
              "cx": t["x"], "cy": t["y"], "w": t["w"], "size": t["size"]}
        if t["align"] != "center":
            tx["align"] = t["align"]
        texts.append(tx)
    # tên cô dâu & chú rể cùng kiểu chữ → cùng cỡ (tên dài không làm lệch tên ngắn)
    ten = [tx for tx in texts if tx["id"].startswith("ten_")]
    if len(ten) >= 2 and len({tx["style"] for tx in ten}) == 1:
        for tx in ten:
            tx["group"] = "ten"
    photos = [{k2: p[k2] for k2 in ("id", "label", "x", "y", "w", "h", "shape")} for p in v["photos"]]
    return {"title": f"{card['name']} – {v['name']}", "mo_ta": v["name"], "card": card["id"],
            "card_name": card["name"], "role": card.get("role") or infer_role(card["id"], card["name"]), "variant": k + 1, "canvas": dict(card["canvas"]), "size": card["size"],
            "shape": card["shape"], "ornaments": orn, "texts": texts, "photos": photos}


def _layout_mask(L: dict):
    from .shapes import shape_mask
    W, H = float(L["canvas"]["w"]), float(L["canvas"]["h"])
    shp = L.get("shape") or "chu_nhat"
    mw = 200
    mh = max(1, round(mw * H / W))
    return (None if shp == "chu_nhat" else shape_mask(shp, mw, mh, ss=2, design=(W, H))), mw, mh


def _text_box(t: dict, styles_meta: dict) -> tuple[tuple, float, float]:
    """Khung ước lượng của chữ (chưa cần dựng): (x0, y0, x1, y1), bề rộng mực ước tính, cỡ chữ."""
    st = styles_meta.get(t.get("style"), {})
    lines = str(t["text"]).split("\n")
    size = float(t.get("size") or st.get("size", 40))
    adv = 0.42 if st.get("kind") == "script" else (0.66 + float(st.get("ls", 0))) if st.get("uppercase") else 0.5
    est = min(float(t["w"]), max(len(s) for s in lines) * size * adv)
    cx, cy, w = float(t["cx"]), float(t["cy"]), float(t["w"])
    x0 = cx - w / 2 if t.get("align") == "left" else cx + w / 2 - est if t.get("align") == "right" else cx - est / 2
    span = (len(lines) - 1) * 1.15 * size
    return (x0, cy - span / 2 - 0.5 * size, x0 + est, cy + span / 2 + 0.35 * size), est, size


def layout_problems(L: dict, items_meta: dict, styles_meta: dict) -> list[dict]:
    """Lỗi bố cục dễ thấy, đo trên bản phác (chưa cần ảnh): chữ tràn mép / ra ngoài hình, chữ đè chữ, chữ đè giữa
    món đặc (không tính khung rỗng, lớp nền trang trí, món mờ, món phủ rộng), món nằm ngoài thiệp, chữ quá nhỏ.
    Mỗi lỗi: {kind, msg, t, t2, el, ph} – chỉ số để tự sửa."""
    from .layout import expand
    W, H = float(L["canvas"]["w"]), float(L["canvas"]["h"])
    mask, mw, mh = _layout_mask(L)

    def inside(x, y):
        if not (-0.5 <= x <= W + 0.5 and -0.5 <= y <= H + 0.5):
            return False
        return mask is None or mask[min(mh - 1, max(0, int(y / H * mh))), min(mw - 1, max(0, int(x / W * mw)))] > 0.5

    probs, boxes = [], []
    for i, t in enumerate(L.get("texts", [])):
        if t.get("hidden") or not str(t.get("text", "")).strip():
            continue
        box, est, size = _text_box(t, styles_meta)
        cy = float(t["cy"])
        label = t.get("label") or t["id"]
        pts = [(box[0], box[1]), (box[2], box[1]), (box[0], box[3]), (box[2], box[3]),
               ((box[0] + box[2]) / 2, box[1]), ((box[0] + box[2]) / 2, box[3]), (box[0], cy), (box[2], cy)]
        if not all(inside(*p) for p in pts):
            probs.append({"kind": "outside", "t": i, "msg": f"chữ '{label}' tràn ra ngoài "
                                                           + ("mép thiệp" if mask is None else "hình dáng thiệp")})
        if size < 0.017 * W:
            probs.append({"kind": "tiny", "t": i,
                          "msg": f"chữ '{label}' quá nhỏ (cỡ {size:g}) – khó đọc khi in, nên ≥ {0.02 * W:g}"})
        boxes.append((i, label, box))
    for a in range(len(boxes)):
        for b in range(a + 1, len(boxes)):
            (i, la, A), (j, lb, B) = boxes[a], boxes[b]
            iw, ih = min(A[2], B[2]) - max(A[0], B[0]), min(A[3], B[3]) - max(A[1], B[1])
            if iw > 0 and ih > 0:
                small = min((A[2] - A[0]) * (A[3] - A[1]), (B[2] - B[0]) * (B[3] - B[1]))
                if iw * ih > 0.2 * small:
                    probs.append({"kind": "overlap", "t": i, "t2": j, "msg": f"chữ '{la}' đè lên chữ '{lb}'"})
    src = [{**o, "_i": k} for k, o in enumerate(L.get("ornaments", []))
           if o.get("type", "asset") == "asset" and not o.get("hidden")]
    naturals = {o["asset"]: (float(o.get("w") or o.get("h") or 100), float(o.get("h") or o.get("w") or 100)) for o in src}
    flagged = set()
    for p in expand([{**o, "w": naturals[o["asset"]][0], "h": naturals[o["asset"]][1]} for o in src], (W, H), naturals):
        meta = items_meta.get(p.el["asset"], {})
        nm = meta.get("name", p.el["asset"])
        cx, cy = p.x + p.w / 2, p.y + p.h / 2
        if not (0 <= cx <= W and 0 <= cy <= H) and p.el["_i"] not in flagged:
            probs.append({"kind": "item_outside", "el": p.el["_i"], "msg": f"món '{nm}' nằm ngoài thiệp"})
            flagged.add(p.el["_i"])
        if meta.get("hollow") or meta.get("backdrop") or float(p.el.get("opacity", 1)) < 0.6 \
                or p.w * p.h > 0.3 * W * H:
            continue
        inner = (p.x + p.w * 0.25, p.y + p.h * 0.25, p.x + p.w * 0.75, p.y + p.h * 0.75)
        for i, label, b in boxes:
            tx, ty = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
            if inner[0] <= tx <= inner[2] and inner[1] <= ty <= inner[3]:
                probs.append({"kind": "on_item", "t": i, "el": p.el["_i"],
                              "msg": f"chữ '{label}' nằm đè lên giữa món '{nm}'"})
    for k, ph in enumerate(L.get("photos", [])):
        x0, y0 = float(ph["x"]) - float(ph["w"]) / 2, float(ph["y"]) - float(ph["h"]) / 2
        if not (0 <= float(ph["x"]) <= W and 0 <= float(ph["y"]) <= H):
            probs.append({"kind": "photo_outside", "ph": k, "msg": f"ô ảnh '{ph.get('label', ph['id'])}' nằm ngoài thiệp"})
        for i, label, b in boxes:
            tx, ty = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
            if x0 <= tx <= x0 + float(ph["w"]) and y0 <= ty <= y0 + float(ph["h"]):
                probs.append({"kind": "on_photo", "t": i, "ph": k,
                              "msg": f"chữ '{label}' đè lên ô ảnh '{ph.get('label', ph['id'])}'"})
    seen, out = set(), []
    for p in probs:
        if p["msg"] not in seen:
            seen.add(p["msg"])
            out.append(p)
    return out


def check_layout(L: dict, items_meta: dict, styles_meta: dict) -> list[str]:
    return [p["msg"] for p in layout_problems(L, items_meta, styles_meta)]


def _run_width(mask, mw, mh, W, H, cx, y0, y1) -> float:
    """Bề rộng đối xứng lớn nhất quanh cx mà mọi hàng trong [y0, y1] vẫn nằm trong hình."""
    import numpy as np
    c = min(mw - 1, max(0, int(cx / W * mw)))
    half = mw
    for r in range(max(0, int(y0 / H * mh)), min(mh, int(y1 / H * mh) + 1)):
        row = mask[r] > 0.5
        if not row[c]:
            return 0.0
        left = c - (np.argmin(row[c::-1]) if not row[:c + 1].all() else c + 1)
        right = (np.argmin(row[c:]) if not row[c:].all() else mw - c)
        half = min(half, c - left - 1, right - 1)
    return max(0.0, 2 * half * W / mw)


def autofix_layout(L: dict, items_meta: dict, styles_meta: dict) -> tuple[dict, list[str]]:
    """Tự sửa các lỗi bố cục đơn giản ngay trong tool (không cần quay lại ChatGPT):
    chữ tràn → thu hẹp ô chữ cho vừa trong hình (chữ tự thu nhỏ) hoặc dời vào trong; chữ chạm chữ cùng hàng → thu hẹp
    hai ô; chồng nhau trên dưới → dời chữ dưới xuống; chữ đè giữa món đặc → làm mờ món thành lớp nền; chữ quá nhỏ →
    tăng cỡ; món ngoài thiệp → kéo vào."""
    import copy
    L = copy.deepcopy(L)
    W, H = float(L["canvas"]["w"]), float(L["canvas"]["h"])
    mask, mw, mh = _layout_mask(L)
    margin, pad = 0.04 * W, 0.012 * W
    actions: list[str] = []
    tries: dict[str, int] = {}
    for _ in range(40):
        probs = layout_problems(L, items_meta, styles_meta)
        todo = [p for p in probs if tries.get(p["msg"], 0) < 3]
        if not todo:
            break
        p = todo[0]
        tries[p["msg"]] = tries.get(p["msg"], 0) + 1
        k = p["kind"]
        if k == "on_item":
            o = L["ornaments"][p["el"]]
            o["opacity"] = 0.35
            actions.append(f"làm mờ món '{items_meta.get(o['asset'], {}).get('name', o['asset'])}' (35%) để "
                           f"chữ '{L['texts'][p['t']].get('label', '')}' nổi rõ")
        elif k == "tiny":
            t = L["texts"][p["t"]]
            t["size"] = round(0.02 * W, 1)
            actions.append(f"tăng cỡ chữ '{t.get('label', t['id'])}' lên {t['size']:g}")
        elif k == "item_outside":
            o = L["ornaments"][p["el"]]
            o["x"], o["y"] = round(min(max(float(o["x"]), 0), W), 1), round(min(max(float(o["y"]), 0), H), 1)
            actions.append(f"kéo món '{items_meta.get(o['asset'], {}).get('name', o['asset'])}' vào trong thiệp")
        elif k == "outside":
            t = L["texts"][p["t"]]
            box, est, size = _text_box(t, styles_meta)
            label = t.get("label", t["id"])
            if mask is None:
                dx = max(0.0, margin - box[0]) - max(0.0, box[2] - (W - margin))
                dy = max(0.0, margin - box[1]) - max(0.0, box[3] - (H - margin))
                if est > W - 2 * margin:
                    t["w"] = round(W - 2 * margin, 1)
                t["cx"], t["cy"] = round(float(t["cx"]) + dx, 1), round(float(t["cy"]) + dy, 1)
                actions.append(f"dời/thu hẹp chữ '{label}' cho nằm trong mép thiệp")
            else:
                avail = _run_width(mask, mw, mh, W, H, float(t["cx"]), box[1], box[3]) * 0.92
                if avail >= 0.45 * est:
                    t["w"] = round(float(max(avail, 0.05 * W)), 1)
                    t.pop("align", None)
                    actions.append(f"thu hẹp ô chữ '{label}' cho nằm gọn trong hình (chữ tự thu nhỏ)")
                else:                      # chỗ này hình quá hẹp → dời chữ về phía có chỗ rộng hơn (gần tâm hình)
                    import numpy as np
                    rows = np.where((mask > 0.5).sum(1) > 0)[0]
                    mid_y = (rows.mean() + 0.5) * H / mh if len(rows) else H / 2
                    step = (0.03 * H) * (1 if mid_y > float(t["cy"]) else -1)
                    t["cy"] = round(float(t["cy"]) + float(step), 1)
                    actions.append(f"dời chữ '{label}' vào phía trong hình")
        elif k == "overlap":
            a, b = L["texts"][p["t"]], L["texts"][p["t2"]]
            A, ea, sa = _text_box(a, styles_meta)
            B, eb, sb = _text_box(b, styles_meta)
            if abs(float(a["cy"]) - float(b["cy"])) < 0.6 * max(sa, sb):          # cùng hàng → thu hẹp hai ô
                l, r, el_, er = (a, b, ea, eb) if float(a["cx"]) <= float(b["cx"]) else (b, a, eb, ea)
                room = float(r["cx"]) - float(l["cx"]) - pad
                f = room / max(1.0, el_ / 2 + er / 2)
                if f >= 0.4:
                    l["w"], r["w"] = round(el_ * min(f, 0.97), 1), round(er * min(f, 0.97), 1)
                    l.pop("align", None)
                    r.pop("align", None)
                    actions.append(f"thu nhỏ chữ '{l.get('label', '')}' và '{r.get('label', '')}' cho khỏi chạm nhau")
                else:
                    need = (el_ / 2 + er / 2 + pad) - (float(r["cx"]) - float(l["cx"]))
                    l["cx"], r["cx"] = round(float(l["cx"]) - need / 2, 1), round(float(r["cx"]) + need / 2, 1)
                    actions.append(f"giãn chữ '{l.get('label', '')}' và '{r.get('label', '')}' ra hai bên")
            else:                                                                  # trên–dưới → dời chữ dưới xuống
                up, lo, U, Lo = (a, b, A, B) if float(a["cy"]) <= float(b["cy"]) else (b, a, B, A)
                dy = U[3] - Lo[1] + pad
                if Lo[3] + dy <= H - margin:
                    lo["cy"] = round(float(lo["cy"]) + dy, 1)
                    actions.append(f"dời chữ '{lo.get('label', '')}' xuống cho khỏi đè chữ '{up.get('label', '')}'")
                else:
                    for t in (a, b):
                        t["size"] = round(float(t.get("size") or styles_meta.get(t.get("style"), {}).get("size", 40)) * 0.88, 1)
                    actions.append(f"thu nhỏ chữ '{a.get('label', '')}' và '{b.get('label', '')}' cho khỏi chồng nhau")
    return L, list(dict.fromkeys(actions))


# ---------------------------------------------------------------- tạo / cập nhật mẫu từ bản thiết kế

def item_usage(design: dict) -> dict:
    """Mỗi món: ô lớn nhất được dùng (đơn vị thiết kế) và tỉ lệ cao/rộng trung bình – để chọn khung ảnh khi vẽ."""
    out: dict[str, dict] = {}
    for c in design["cards"]:
        for v in c["variants"]:
            for e in v["items"]:
                w, h = e.get("w"), e.get("h")
                u = out.setdefault(e["item"], {"max": 0.0, "ratios": []})
                u["max"] = max(u["max"], w or 0, h or 0)
                if w and h:
                    u["ratios"].append(h / w)
    for u in out.values():
        r = sorted(u.pop("ratios"))
        u["ratio"] = r[len(r) // 2] if r else 1.0
    return out


def _item_desc(it: dict) -> str:
    extra = {"wide": " Dải nằm ngang, dẹt, dài.", "tall": " Cao và hẹp, dựng đứng."}.get(it["shape"], "")
    if it["hollow"]:
        extra += " Rỗng giữa: bên trong để trống hoàn toàn."
    return f"[{it['id']}] {it['name']} – {it['draw'] or it['name']}.{extra}"


def build_plan(design: dict, prev_plan: list | None, drawn: set) -> list[dict]:
    """Tờ cần vẽ. Tờ ĐÃ vẽ giữ nguyên; món mới (hoặc chưa vẽ) được xếp vào tờ mới."""
    from .plan import plan_sheets
    usage = item_usage(design)
    kinds, ratios = {}, {}
    # món dùng to hơn mức tờ chung đủ nét (4 món/tờ) → vẽ riêng một ảnh
    limit = {"small": 300, "tall": 650, "wide": 900}
    for it in design["items"]:
        u = usage.get(it["id"], {"max": 0, "ratio": 1.0})
        kind = "big" if u["max"] >= limit.get(it["shape"], 1e9) else it["shape"]
        kinds[it["id"]] = kind
        if kind == "big":
            ratios[it["id"]] = "dọc 2:3" if u["ratio"] > 1.25 else "ngang 3:2" if u["ratio"] < 0.8 else "vuông 1:1"
    ids = [it["id"] for it in design["items"]] + (["nen"] if design["background"]["draw"] else [])
    orient = {("doc" if c["canvas"]["h"] > c["canvas"]["w"] * 1.05 else
               "ngang" if c["canvas"]["w"] > c["canvas"]["h"] * 1.05 else "vuong") for c in design["cards"]}
    bg_ratio = {frozenset({"doc"}): "dọc 2:3", frozenset({"ngang"}): "ngang 3:2"}.get(frozenset(orient), "vuông 1:1")
    keep = [s for s in (prev_plan or []) if s["id"] in drawn]
    covered = {i for s in keep for i in s["items"]}
    start = 1 + max([int(re.sub(r"\D", "", s["id"]) or 0) for s in keep] or [0])
    return keep + plan_sheets([i for i in ids if i not in covered], kinds, ratios, with_bg=False,
                              bg_ratio=bg_ratio, start=start)


def kit_json_from_design(design: dict, request: str, fonts: dict, name: str, plan: list,
                         prev: dict | None = None) -> dict:
    prev = prev or {}
    bg, colors = design["background"]["color"], design["colors"]
    dark_bg = _lum(bg) < 110
    from .kitgen import readable_metal
    dark, mid, light = readable_metal(*(colors.get("metal") or DEFAULT_TEXT), bg)
    fills = {"gold": {"type": "gradient", "angle": 170,
                      "stops": [[dark, 0], [mid, 0.28], [light, 0.46], [mid, 0.63], [light, 0.8], [dark, 1]]},
             "gold_line": {"type": "gradient", "angle": 135,
                           "stops": [[dark, 0], [light, 0.35], [mid, 0.6], [light, 0.85], [dark, 1]]},
             "ink": colors["text"], "accent": colors["accent"]}
    if colors["metallic"] and prev.get("colors_from_images"):       # màu ánh kim đã đo từ ảnh thật → giữ
        fills.update({k: prev["fills"][k] for k in ("gold", "gold_line") if k in prev.get("fills", {})})
    sh_big = "drop-shadow(0 3px 2px rgba(0,0,0,.55))" if dark_bg else "drop-shadow(0 1.5px 1px rgba(90,60,20,.3))"
    styles = {}
    for sid, st in design["styles"].items():
        kind = fonts.get(st["font"], {}).get("kind", "serif")
        ts = {"font": st["font"], "weight": st["weight"], "fill": _fill(st["color"]), "size": 60,
              "line_height": 1.05 if kind == "script" else 1.15}
        if st["uppercase"]:
            ts["uppercase"] = True
        if st["italic"]:
            ts["italic"] = True
        if st["letter_spacing"]:
            ts["letter_spacing"] = f"{st['letter_spacing']}em"
        if kind != "script":
            ts["numeric"] = "lining-nums"
        if st["color"] == "metal":
            ts["shadow"] = sh_big
        styles[sid] = ts
    used_fonts = {st["font"] for st in design["styles"].values()}
    assets = {it["id"]: {"label": it["name"], "desc": _item_desc(it), "kind": it["shape"], "hollow": it["hollow"],
                         "backdrop": it.get("backdrop", False), "role": "ornament"} for it in design["items"]}
    draw_bg = design["background"]["draw"]
    if draw_bg:
        assets["nen"] = {"kind": "background", "label": "Nền giấy",
                         "desc": f"{draw_bg} – chỉ có chất giấy/hoạ tiết chìm thật nhạt, không hoa văn nổi, không chữ"}
    words = (design["style"] + " " + " ".join(it["draw"] for it in design["items"])).lower()
    dark_art = any(w in words for w in ("black", "ink line", "line art", "charcoal", "silhouette", "đen")) \
        or _lum(colors["accent"]) < 70
    return {
        "name": name, "title": design["title"], "design": True, "request": request,
        "idea": design["style"], "style": design["style"], "background_desc": draw_bg,
        "palette": [bg, colors["accent"], colors["text"]], "ornament_colors": [colors["accent"]],
        "key_color": "auto", "fills": fills, "auto_fills": ["gold", "gold_line"] if colors["metallic"] else [],
        "fonts": {f: fonts[f]["file"] for f in sorted(used_fonts) if f in fonts}, "text_styles": styles,
        "drop_baked_shadow": not dark_art,
        "ornament_shadow": ({"dx": 0, "dy": 3, "blur": 3, "opacity": 0.4, "color": "#000000"} if dark_bg
                            else {"dx": 0, "dy": 2, "blur": 3, "opacity": 0.18, "color": "#5a4020"}),
        "background": {"color": bg, "asset": "nen" if draw_bg else "", "vignette": 0.0},
        "assets": assets, "plan": plan, "colors_from_images": prev.get("colors_from_images", False),
    }


def write_layouts(kit: Kit, design: dict) -> list[str]:
    """Mỗi phương án → kits/<mẫu>/layouts/<thiệp>__<n>.json. Phương án đã chỉnh tay (_edited) được giữ."""
    d = kit.layouts_dir
    d.mkdir(exist_ok=True)
    notes, keep = [], set()
    for card in design["cards"]:
        for k in range(len(card["variants"])):
            name = f"{card['id']}__{k + 1}"
            f = d / f"{name}.json"
            keep.add(name)
            if f.exists() and load_json(f).get("_edited"):
                notes.append(f"'{card['name']} – phương án {k + 1}' đã chỉnh tay → giữ nguyên bản đã chỉnh.")
                continue
            f.write_text(json.dumps(variant_layout(design, card, k), ensure_ascii=False, indent=1), encoding="utf-8")
    for f in d.glob("*.json"):
        if f.stem not in keep and not load_json(f).get("_edited"):
            f.unlink()
    return notes


def import_design(prj: Project, text: str, kit_name: str | None = None, request: str = "") -> tuple[Kit, list[str]]:
    """Câu trả lời của AI → mẫu mới (hoặc cập nhật mẫu `kit_name`, giữ các món đã vẽ)."""
    from .sheets import load_state
    raw = extract_json(text)
    fonts = available_fonts(prj)
    design, notes = normalize_design(raw, fonts)
    prev, drawn = None, set()
    if not kit_name:
        same = [d.name for d in sorted(prj.kits_dir.glob("*"))
                if (d / "design_reply.txt").exists() and (d / "design_reply.txt").read_text(encoding="utf-8").strip() == text.strip()]
        if same:
            kit_name = same[0]
            notes.append(f"Câu trả lời này đã nhập vào mẫu '{same[0]}' trước đó → mở lại mẫu đó, không tạo mẫu trùng.")
    if kit_name:
        kit = prj.kit(kit_name)
        prev, name = kit.data, kit.name
        drawn = set(load_state(kit))
        request = request or prev.get("request", "")
    else:
        base = slugify(design["title"])
        name, n = base, 2
        while (prj.kits_dir / name).exists():
            name, n = f"{base}_{n}", n + 1
    d = prj.kits_dir / name
    (d / "raw").mkdir(parents=True, exist_ok=True)
    (d / "assets").mkdir(exist_ok=True)
    plan = build_plan(design, (prev or {}).get("plan"), drawn)
    kj = kit_json_from_design(design, request, fonts, name, plan, prev)
    (d / "kit.json").write_text(json.dumps(kj, ensure_ascii=False, indent=2), encoding="utf-8")
    (d / "design.json").write_text(json.dumps({**design, "request": request, "notes": notes}, ensure_ascii=False,
                                              indent=1), encoding="utf-8")
    (d / "design_reply.txt").write_text(text, encoding="utf-8")       # bản gốc AI trả về, để tra lại
    kit = prj.kit(name)
    notes += write_layouts(kit, design)
    return kit, notes


def load_design(kit: Kit) -> dict | None:
    f = kit.dir / "design.json"
    return load_json(f) if f.exists() else None


def local_layouts(kit: Kit) -> list[dict]:
    """Bố cục riêng của mẫu, xếp theo thứ tự thiệp trong bản thiết kế rồi số phương án."""
    if not kit.layouts_dir.exists():
        return []
    design = load_design(kit) or {"cards": []}
    order = {c["id"]: i for i, c in enumerate(design["cards"])}
    out = []
    for f in kit.layouts_dir.glob("*.json"):
        L = load_json(f)
        out.append({"name": f.stem, "data": L})
    out.sort(key=lambda x: (order.get(x["data"].get("card"), 99), x["data"].get("card", ""),
                            x["data"].get("variant", 99), x["name"]))
    return out


def styles_meta(kit: Kit, fonts: dict) -> dict:
    out = {}
    for sid, st in kit.text_styles.items():
        fid = st.get("font", "")
        kind = fonts.get(fid, {}).get("kind") or ("script" if "script" in fid else "serif")
        out[sid] = {"kind": kind, "uppercase": bool(st.get("uppercase")), "size": st.get("size", 60),
                    "ls": _num(st.get("letter_spacing"), 0) or 0}
    return out


def save_local_layout(kit: Kit, name: str, data: dict, as_new: bool) -> str:
    """Lưu phương án đã chỉnh trong trình kéo thả (đánh dấu _edited để nhập bản thiết kế mới không ghi đè)."""
    d = kit.layouts_dir
    d.mkdir(exist_ok=True)
    if as_new:
        card = data.get("card") or slugify(data.get("title", "thiep"))
        nums = [int(m.group(1)) for f in d.glob(f"{card}__*.json") if (m := re.search(r"__(\d+)$", f.stem))]
        k = max(nums or [0]) + 1
        name = f"{card}__{k}"
        data = {**data, "card": card, "variant": k, "mo_ta": data.get("mo_ta", "") + " (bản chỉnh)",
                "title": f"{data.get('card_name', card)} – phương án {k}"}
    elif not (d / f"{name}.json").exists():
        raise ConfigError(f"Mẫu không có phương án '{name}'.")
    (d / f"{name}.json").write_text(json.dumps({**data, "_edited": True}, ensure_ascii=False, indent=1),
                                    encoding="utf-8")
    return name


def autofix_kit(prj: Project, kit: Kit) -> list[dict]:
    """Tự sửa lỗi bố cục mọi phương án của mẫu; ghi lại những gì đã sửa vào chính bố cục (_autofix)."""
    meta = {a: {"name": v.get("label", a), "hollow": v.get("hollow"), "backdrop": v.get("backdrop")}
            for a, v in kit.assets.items() if isinstance(v, dict)}
    sm = styles_meta(kit, available_fonts(prj))
    out = []
    for x in local_layouts(kit):
        if not layout_problems(x["data"], meta, sm):
            continue
        L2, acts = autofix_layout(x["data"], meta, sm)
        if acts:
            L2["_autofix"] = list(dict.fromkeys(L2.get("_autofix", []) + acts))
            (kit.layouts_dir / f"{x['name']}.json").write_text(json.dumps(L2, ensure_ascii=False, indent=1),
                                                                encoding="utf-8")
        out.append({"name": x["name"], "title": x["data"].get("title", x["name"]), "actions": acts,
                    "left": check_layout(L2, meta, sm)})
    return out


def delete_local_layout(kit: Kit, name: str) -> None:
    f = kit.layouts_dir / f"{name}.json"
    if not re.fullmatch(r"[a-z0-9_]+", name) or not f.exists():
        raise ConfigError(f"Mẫu không có phương án '{name}'.")
    f.unlink()
