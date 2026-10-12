"""Thiệp cardkit đã xuất (manifest.json + pieces/) → templateData của Icard. Hàm thuần, không gọi mạng.

Renderer công khai của Icard (PageCanvas, Canvas 2D):
  - mọi trang scale theo pages[0].canvasWidth; ảnh nền kéo kín trang; item vẽ theo zIndex
  - chữ: textBaseline 'middle', dòng cao 1.3 × cỡ chữ, cả khối căn giữa dọc trong hộp, tự xuống dòng theo
    width, MỘT màu đặc, không letter-spacing / text-transform
  - ảnh: cắt kiểu cover theo hộp (hộp đúng tỉ lệ ảnh → không cắt gì)
Editor của Icard (DOM): hộp chữ padding 10px 5px, line-height 1.4, căn giữa dọc – cùng tâm với renderer.
Đường chân chữ so với tâm dòng ở cả hai: (ascent − descent)/2 × cỡ chữ → đặt tâm hộp để đường chân chữ
trung bình trùng bản cardkit.
"""
from __future__ import annotations

import hashlib
import io
import json
import re
import uuid
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from ..config import ConfigError
from .fonts import FontNeed, css_weight, features_for, font_meta, icard_category, icard_font_name, need_bytes

LINE_H = 1.3              # renderer công khai
EDITOR_LINE_H = 1.4       # editor (hộp chữ phải đủ cao cho editor)
PAD_X, PAD_Y = 5, 10      # padding hộp chữ trong editor
TEXT_MODES = ("edit", "guest", "lock", "drop")
GUEST_IDS = ("khach", "ten_khach", "khach_moi", "ten_khach_moi")   # ô tên khách mời → Icard tự điền tên từng khách
GUEST_TEXT = "[Tên Khách Mời]"
INVITATION_TYPES = ["Thiệp cưới", "Thiệp sinh nhật", "Thiệp sự kiện chung", "Thiệp cảm ơn", "Thiệp chúc mừng"]
IMG = "@img:"             # chỗ giữ URL ảnh trong templateData trước khi up


@dataclass
class Page:
    out_dir: Path          # thư mục thiệp đã xuất (render_card với pieces=True)
    name: str              # tên trang hiện trong editor Icard


@dataclass
class Options:
    logical_w: int = 454                       # bề rộng khung trang trên Icard (mẫu có sẵn của Icard: 454)
    ornaments: str = "merge"                   # merge = gộp hoa văn vào nền · layers = mỗi món một ảnh rời
    texts: dict = field(default_factory=dict)  # id ô chữ → {"mode": edit|lock|drop, "color": "#rrggbb"}
    background_color: str = "#FFFFFF"          # màu trang (lộ ra ngoài hình dáng thiệp không chữ nhật)
    max_px: int = 1920                         # Icard thu ảnh về tối đa 1920px rộng
    invitation_type: str = "Thiệp cưới"
    theme_color: str = "#ffffff"

    @classmethod
    def from_dict(cls, d: dict | None) -> "Options":
        d = d or {}
        o = cls(**{k: d[k] for k in ("logical_w", "ornaments", "texts", "background_color", "max_px",
                                     "invitation_type", "theme_color") if d.get(k) not in (None, "")})
        o.logical_w = int(o.logical_w)
        if not 200 <= o.logical_w <= 2000:
            raise ConfigError("Bề rộng khung Icard phải trong khoảng 200–2000.")
        if o.ornaments not in ("merge", "layers"):
            raise ConfigError("Chế độ hoa văn phải là 'merge' (gộp vào nền) hoặc 'layers' (lớp rời).")
        for tid, t in o.texts.items():
            if t.get("mode", "edit") not in TEXT_MODES:
                raise ConfigError(f"Ô chữ '{tid}': chế độ phải là một trong {', '.join(TEXT_MODES)}.")
            if t.get("color") and not re.fullmatch(r"#[0-9a-fA-F]{6}", t["color"]):
                raise ConfigError(f"Ô chữ '{tid}': màu '{t['color']}' không hợp lệ (dạng #rrggbb).")
        return o

    def mode(self, tid: str) -> str:
        return self.texts.get(tid, {}).get("mode") or default_mode(tid)


@dataclass
class Result:
    template_data: dict                        # URL ảnh = "@img:<sha1>"
    uploads: dict[str, bytes]                  # "@img:<sha1>" → PNG
    fonts: list[FontNeed]
    thumbnail: bytes                           # WebP 1200×800 theo quy cách thumbnail của Icard
    previews: list[Image.Image]                # giả lập trang trên Icard (để xem trước)
    warnings: list[str]


# ------------------------------------------------------------------ tiện ích

def png_bytes(im: Image.Image) -> bytes:
    buf = io.BytesIO()
    im.save(buf, "PNG", compress_level=6)
    return buf.getvalue()


def webp_bytes(im: Image.Image, quality: int = 90) -> bytes:
    """Thumbnail: PUT của Icard up nguyên file (không thu nhỏ) → gửi WebP gọn thay vì PNG nặng."""
    buf = io.BytesIO()
    im.save(buf, "WEBP", quality=quality, method=6)
    return buf.getvalue()


def image_key(data: bytes) -> str:
    return IMG + hashlib.sha1(data).hexdigest()


def _hex(rgb) -> str:
    return "#{:02x}{:02x}{:02x}".format(*(int(round(c)) for c in rgb[:3]))


def solid_color(fill_css: str, fallback: str = "#333333") -> str:
    """Màu đặc đại diện cho kiểu tô cardkit (gradient ánh kim → màu có độ sáng trung vị)."""
    cols = [tuple(float(x) for x in m.groups()[:3])
            for m in re.finditer(r"rgba?\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)", fill_css or "")]
    cols += [tuple(int(h[i:i + 2], 16) for i in (0, 2, 4)) for h in re.findall(r"#([0-9a-fA-F]{6})\b", fill_css or "")]
    if not cols:
        return fallback
    cols.sort(key=lambda c: 0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2])
    return _hex(cols[(len(cols) - 1) // 2])


@lru_cache(maxsize=128)
def _pil_font(need: FontNeed, size: int) -> ImageFont.FreeTypeFont:
    """Font Pillow từ ĐÚNG file sẽ đăng lên Icard (bản tĩnh, tính năng đã đóng băng)."""
    return ImageFont.truetype(io.BytesIO(need_bytes(need)), max(1, size))


def _font(need: FontNeed, size: float) -> ImageFont.FreeTypeFont:
    return _pil_font(need, round(size))


def _measure(need: FontNeed, size: float, text: str) -> float:
    return _font(need, size).getlength(text)


def wrap_text(need: FontNeed, size: float, text: str, max_w: float) -> list[str]:
    """Cùng thuật toán xuống dòng với renderer Icard (wrapText): theo '\\n' rồi theo dấu cách."""
    out = []
    for para in text.split("\n"):
        if para == "":
            out.append("")
            continue
        words = para.split(" ")
        cur = words[0]
        for w in words[1:]:
            if _measure(need, size, cur + " " + w) < max_w:
                cur += " " + w
            else:
                out.append(cur)
                cur = w
        out.append(cur)
    return out


def _icard_text(t: dict) -> str:
    s = str(t.get("text", ""))
    if t.get("uppercase"):
        s = s.upper()
    return re.sub(r"\s*\|\s*", " | ", s)            # chữ lồng "G|N" → "G | N" (Icard không vẽ được vạch ngăn)


# ------------------------------------------------------------------ chuyển một ô chữ

def default_mode(tid: str) -> str:
    """Ô tên khách mời mặc định là ô tên khách của Icard; mọi ô khác: khách sửa được."""
    return "guest" if tid in GUEST_IDS else "edit"


def text_item(t: dict, font_path: Path, k: float, color: str, z: int,
              guest: bool = False) -> tuple[dict, FontNeed, list[str]]:
    """Ô chữ cardkit (mục manifest.texts) → item text của Icard + font cần có + ghi chú ("spacing": mất giãn chữ)."""
    notes = []
    weight = int(t.get("font_weight", 400))
    meta = font_meta(font_path)
    feats = features_for(font_path, t.get("numeric"))
    name = icard_font_name(font_path, weight, feats)
    need = FontNeed(font_path, weight, name, icard_category("script" if t.get("style") == "script" else None), feats)
    content = _icard_text(t)
    lines = content.split("\n")
    size_px = float(t["font_size"])                                  # cỡ chữ thật (đã thu nhỏ) ở khung xuất
    adv = max(_measure(need, size_px, ln) for ln in lines) if content else 0.0
    max_w = float(t["max_width"])
    fs = size_px * k
    inner = max(max_w, adv * 1.06) * k                               # đủ rộng để không tự xuống dòng
    width = inner + 2 * PAD_X
    cx = float(t["center"][0]) * k
    align = t.get("align", "center")
    if align == "left":
        x = (float(t["center"][0]) - max_w / 2) * k - PAD_X
    elif align == "right":
        x = (float(t["center"][0]) + max_w / 2) * k - width + PAD_X
    else:
        x = cx - width / 2
    baselines = t.get("baselines") or [float(t["center"][1])]
    cy = sum(baselines) / len(baselines) * k - (meta["ascent"] - meta["descent"]) / 2 * fs
    height = len(lines) * EDITOR_LINE_H * fs + 2 * PAD_Y
    if float(t.get("letter_spacing_em") or 0) > 0.02:
        notes.append("spacing")
    item = {"id": _uid(), "type": "text", "content": content,
            "x": _r(x), "y": _r(cy - height / 2), "width": _r(width), "height": _r(height),
            "rotation": 0, "opacity": 1, "visible": True, "locked": False, "zIndex": z,
            "fontFamily": name, "fontSize": _r(fs), "color": color, "fontWeight": css_weight(font_path, weight),
            "fontStyle": "italic" if t.get("italic") else "normal", "textDecoration": "none", "textAlign": align,
            "isGuestName": guest, "isCustomWidth": True}
    if guest:                            # Icard thay bằng tên từng khách theo link mời; hộp đủ rộng cho tên dài
        item.update(content=GUEST_TEXT)
    return item, need, notes


def image_item(key: str, box: tuple[float, float, float, float], z: int, shape: str = "square") -> dict:
    x, y, w, h = box
    return {"id": _uid(), "type": "image", "url": key, "x": _r(x), "y": _r(y), "width": _r(w), "height": _r(h),
            "rotation": 0, "opacity": 1, "visible": True, "locked": False, "zIndex": z,
            "brightness": 1, "contrast": 1, "grayscale": 0, "shape": shape,
            "imagePosition": {"x": 0, "y": 0, "scale": 1}}


def _uid() -> str:
    return uuid.uuid4().hex                    # không có '_' (Icard tách field background_<id> theo '_')


def _r(v: float) -> float:
    return round(float(v), 2)


def _crop_alpha(im: Image.Image) -> tuple[Image.Image, tuple[int, int, int, int]] | None:
    bb = im.getchannel("A").getbbox()
    return (im.crop(bb), bb) if bb else None


# ------------------------------------------------------------------ chuyển cả bộ

def build(pages: list[Page], opts: Options, title: str = "") -> Result:
    if not pages:
        raise ConfigError("Chọn ít nhất một thiệp làm trang.")
    uploads: dict[str, bytes] = {}
    images: dict[str, Image.Image] = {}
    fonts: dict[str, FontNeed] = {}
    warnings: list[str] = []
    spaced: list[str] = []                         # ô chữ mất giãn chữ trên Icard (gộp thành một cảnh báo)
    out_pages = []
    ratio0 = None
    WL = opts.logical_w

    def add_image(im: Image.Image) -> str:
        data = png_bytes(im)
        key = image_key(data)
        uploads[key] = data
        images[key] = im
        return key

    for pg in pages:
        man_path = pg.out_dir / "manifest.json"
        if not man_path.exists():
            raise ConfigError(f"Thiệp '{pg.name}' chưa được dựng (thiếu manifest.json).")
        m = json.loads(man_path.read_text(encoding="utf-8"))
        W, H = int(m["canvas"]["w"]), int(m["canvas"]["h"])
        ratio = H / W
        if ratio0 is None:
            ratio0 = ratio
        elif abs(ratio - ratio0) / ratio0 > 0.01:
            raise ConfigError("Các trang trên Icard phải cùng khổ (Icard lật trang theo khổ trang đầu) – "
                              f"'{pg.name}' khác khổ trang đầu.")
        HL = round(WL * ratio0)
        k = WL / W

        def layer(name: str) -> Image.Image:
            return Image.open(pg.out_dir / name).convert("RGBA")

        bg = layer("01_nen.png")
        pieces = {p["id"]: p for p in m.get("pieces", [])}
        if opts.ornaments == "merge":
            bg.alpha_composite(layer("02_hoa_van.png"))
        else:                                           # viền, đường kẻ do code vẽ → luôn nằm trong nền
            for p in pieces.values():
                if p.get("type") in ("border", "rule") and p.get("file"):
                    bg.alpha_composite(layer(p["file"]))
        items, z = [], 1

        # Ô ảnh cưới: ảnh giữ chỗ – khách thay ảnh trong editor Icard
        photos = m.get("photos", [])
        if photos and opts.ornaments == "merge":
            warnings.append(f"Trang '{pg.name}': ô ảnh nằm trên lớp nền (đã gộp hoa văn) – hoa văn đè lên ô ảnh "
                            "sẽ bị ảnh che; chọn chế độ 'Lớp rời' nếu cần hoa văn nằm trên ảnh.")
        for ph in photos:
            x0, y0, bw, bh = ph["bbox"]
            shape = "circle" if ph.get("shape") in ("oval", "tron") else "square"
            hold = Image.new("RGBA", (max(1, bw), max(1, bh)), (214, 208, 199, 255))
            items.append(image_item(add_image(hold), (x0 * k, y0 * k, bw * k, bh * k), z, shape))
            z += 1

        # Hoa văn rời (chế độ lớp rời): mỗi món một ảnh cắt sát
        if opts.ornaments == "layers":
            for p in pieces.values():
                if p.get("type", "asset") != "asset" or not p.get("file"):
                    continue
                cut = _crop_alpha(layer(p["file"]))
                if cut is None:
                    continue
                im, (x0, y0, x1, y1) = cut
                items.append(image_item(add_image(im), (x0 * k, y0 * k, (x1 - x0) * k, (y1 - y0) * k), z))
                z += 1

        # Chữ
        editable = []
        for t in m.get("texts", []):
            mode = opts.mode(t["id"])
            if mode == "drop":
                continue
            if mode == "lock":
                if not t.get("file"):
                    continue
                if opts.ornaments == "merge":
                    bg.alpha_composite(layer(t["file"]))
                else:
                    cut = _crop_alpha(layer(t["file"]))
                    if cut is not None:
                        im, (x0, y0, x1, y1) = cut
                        items.append(image_item(add_image(im), (x0 * k, y0 * k, (x1 - x0) * k, (y1 - y0) * k), z))
                        z += 1
                continue
            editable.append(t)
        for t in editable:
            fp = pg.out_dir / "fonts" / t["font_file"]
            if not fp.exists():
                raise ConfigError(f"Thiệp '{pg.name}' thiếu file font {t['font_file']} – dựng lại thiệp.")
            color = opts.texts.get(t["id"], {}).get("color") or solid_color(t.get("fill_css", ""))
            item, need, notes = text_item(t, fp, k, color, z, guest=opts.mode(t["id"]) == "guest")
            z += 1
            items.append(item)
            fonts.setdefault(need.name, need)
            if "spacing" in notes and t["id"] not in spaced:
                spaced.append(t["id"])

        if bg.width > opts.max_px:
            bg = bg.resize((opts.max_px, round(opts.max_px * bg.height / bg.width)), Image.LANCZOS)
        out_pages.append({"id": _uid(), "name": pg.name, "canvasWidth": WL, "canvasHeight": HL,
                          "backgroundColor": opts.background_color, "backgroundImage": add_image(bg),
                          "items": items})

    if spaced:
        warnings.append(f"Icard không hỗ trợ giãn chữ → ô {', '.join(spaced)} hơi khít hơn bản gốc "
                        "(đặt ô sang 'Khoá' nếu muốn giữ nguyên dáng chữ).")
    first_font = next((i["fontFamily"] for p in out_pages for i in p["items"] if i["type"] == "text"), "Arial")
    td = {"width": WL, "height": out_pages[0]["canvasHeight"], "pages": out_pages,
          "design": {"themeColor": opts.theme_color, "fontFamily": first_font},
          "settings": {"invitationType": opts.invitation_type}}
    font_paths = {f.name: f for f in fonts.values()}
    previews = [simulate_page(p, images, font_paths, 2.0) for p in out_pages]
    return Result(td, uploads, list(fonts.values()), webp_bytes(thumbnail(previews)), previews, warnings)


# ------------------------------------------------------------------ giả lập Icard (xem trước + thumbnail)

def simulate_page(page: dict, images: dict[str, Image.Image], fonts: dict[str, FontNeed], s: float) -> Image.Image:
    """Vẽ một trang đúng cách renderer công khai của Icard vẽ (Pillow thay cho Canvas 2D)."""
    W, H = round(page["canvasWidth"] * s), round(page["canvasHeight"] * s)
    can = Image.new("RGBA", (W, H), page.get("backgroundColor") or "#FFFFFF")
    if page.get("backgroundImage") in images:
        can.alpha_composite(images[page["backgroundImage"]].resize((W, H), Image.LANCZOS))
    for it in sorted(page["items"], key=lambda i: i.get("zIndex", 0)):
        if it.get("visible") is False:
            continue
        x, y, w, h = (it[c] * s for c in ("x", "y", "width", "height"))
        if it["type"] == "image" and it.get("url") in images:
            src = images[it["url"]]
            r = src.width / src.height
            dw, dh = (h * r, h) if r > w / h else (w, w / r)              # cover
            im = src.resize((max(1, round(dw)), max(1, round(dh))), Image.LANCZOS)
            im = im.crop((round((dw - w) / 2), round((dh - h) / 2), round((dw - w) / 2 + w), round((dh - h) / 2 + h)))
            if it.get("shape") == "circle":
                mask = Image.new("L", im.size, 0)
                ImageDraw.Draw(mask).ellipse((0, 0, im.width - 1, im.height - 1), fill=255)
                im.putalpha(Image.composite(im.getchannel("A"), mask, mask))
            can.alpha_composite(im, (round(x), round(y)))
        elif it["type"] == "text" and it.get("content") and it["fontFamily"] in fonts:
            need = fonts[it["fontFamily"]]
            fs = it["fontSize"] * s
            meta = font_meta(need.path)
            lines = wrap_text(need, fs, it["content"], w)
            lh = fs * LINE_H
            cy = y + h / 2
            font = _font(need, fs)
            d = ImageDraw.Draw(can)
            al = it.get("textAlign", "center")
            ax = {"left": (x, "ls"), "right": (x + w, "rs")}.get(al, (x + w / 2, "ms"))
            for i, ln in enumerate(lines):
                mid = cy - len(lines) * lh / 2 + lh / 2 + i * lh
                base = mid + (meta["ascent"] - meta["descent"]) / 2 * fs
                d.text((ax[0], base), ln, font=font, fill=it.get("color", "#000000"), anchor=ax[1])
    return can


def thumbnail(pages: list[Image.Image], W: int = 1200, H: int = 800) -> Image.Image:
    """Theo đúng quy cách thumbnail của Icard (600×400, lề 40; ≥2 trang: trang 2 lệch 85% ngang, 10% dọc),
    dựng ở 2× cho nét."""
    pad = round(40 * W / 600)
    out = Image.new("RGBA", (W, H), "#FFFFFF")
    aw, ah = W - pad, H - pad
    p1 = pages[0]
    if len(pages) == 1:
        sc = min(aw / p1.width, ah / p1.height)
        pw, ph = p1.width * sc, p1.height * sc
        out.alpha_composite(p1.resize((round(pw), round(ph)), Image.LANCZOS), (round((W - pw) / 2), round((H - ph) / 2)))
        return out.convert("RGB")
    p2 = pages[1]
    ox, vy, hc = 0.85, 0.10, 1.025
    sc = min(aw / (p1.width * (1 + ox)), ah / (p1.height * (1 + vy) * hc))
    pw, ph = p1.width * sc, p1.height * sc
    xb, yb = (W - pw * (1 + ox)) / 2, (H - (ph + ph * vy)) / 2
    k2 = W / 600
    for im, (px, py) in ((p2, (xb + pw * ox, yb + ph * vy)), (p1, (xb, yb))):
        im = im.resize((round(pw), round(ph)), Image.LANCZOS)
        sh = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        sh.paste((0, 0, 0, round(255 * 0.12)), (round(px), round(py + 3 * k2), round(px + pw), round(py + 3 * k2 + ph)))
        out.alpha_composite(sh.filter(ImageFilter.GaussianBlur(4 * k2)))
        out.alpha_composite(im, (round(px), round(py)))
    return out.convert("RGB")


def fill_urls(td: dict, urls: dict[str, str]) -> dict:
    """Thay chỗ giữ "@img:<sha1>" bằng URL thật sau khi up."""
    def walk(v):
        if isinstance(v, dict):
            return {k: walk(x) for k, x in v.items()}
        if isinstance(v, list):
            return [walk(x) for x in v]
        if isinstance(v, str) and v.startswith(IMG):
            if v not in urls:
                raise ConfigError("Ảnh chưa được up lên Icard: " + v)
            return urls[v]
        return v
    return walk(td)
