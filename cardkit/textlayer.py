"""Dựng layer chữ bằng Chromium (Playwright).

Trình duyệt lo phần khó của chữ: dấu tiếng Việt, nét nối của font viết tay, chữ ánh kim
(background-clip: text) và bóng đổ. Mỗi ô chữ được chụp riêng (PNG trong suốt, cùng
khung) → vừa là "mảnh" cho web làm hiệu ứng, vừa ghép lại thành layer chữ.

Căn dọc theo metrics của font (tâm chữ hoa), không theo mực → đổi tên khách không làm
chữ nhảy vị trí.
"""
from __future__ import annotations

import base64
import html
import io
import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image

from .config import ConfigError, Kit
from .fills import fill_css


@dataclass
class TextPiece:
    id: str
    image: Image.Image
    info: dict = field(default_factory=dict)


def _font_metrics(path: Path) -> dict:
    from fontTools.ttLib import TTFont
    f = TTFont(path, lazy=True)
    upm = f["head"].unitsPerEm
    os2 = f["OS/2"] if "OS/2" in f else None
    cap = getattr(os2, "sCapHeight", 0) if os2 else 0
    xh = getattr(os2, "sxHeight", 0) if os2 else 0
    return {"cap": (cap / upm) if cap else 0.68, "xheight": (xh / upm) if xh else 0.45,
            "cmap": set(f.getBestCmap().keys()), "family": f["name"].getDebugName(1)}


def resolve_style(kit: Kit, slot: dict) -> dict:
    base = kit.text_styles.get(slot["style"])
    if base is None:
        raise ConfigError(f"Ô chữ '{slot.get('id')}': kit không có text_style '{slot['style']}'.")
    st = {**base, **{k: v for k, v in slot.items() if k in (
        "size", "weight", "fill", "letter_spacing", "uppercase", "line_height", "shadow", "font",
        "separator", "italic", "min_scale")}}
    st.setdefault("size", 60)
    st.setdefault("weight", 400)
    st.setdefault("line_height", 1.25)
    st.setdefault("letter_spacing", 0)
    return st


# Trình duyệt dựng chữ: Chromium tải riêng của Playwright, hoặc Chrome / Edge có sẵn trên máy khách
# (máy Windows luôn có Edge; máy Mac thường có Chrome) – để bản giao khách không phải tải thêm trình duyệt.
BROWSER_CHOICES = [(None, "Chromium (tải kèm)"), ("chrome", "Google Chrome"), ("msedge", "Microsoft Edge")]


def launch_browser(pw):
    errs = []
    for channel, _ in BROWSER_CHOICES:
        try:
            return pw.chromium.launch(channel=channel) if channel else pw.chromium.launch()
        except Exception as e:  # kênh này không có trên máy → thử kênh sau
            errs.append(str(e).splitlines()[0])
    raise ConfigError("Không mở được trình duyệt để dựng chữ. Cài Google Chrome (hoặc chạy: "
                      "python -m playwright install chromium) rồi thử lại.\n(" + " | ".join(errs) + ")")


def browser_status() -> str | None:
    """Tên trình duyệt dựng chữ dùng được trên máy này (None = chưa có)."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        for channel, name in BROWSER_CHOICES:
            try:
                b = pw.chromium.launch(channel=channel) if channel else pw.chromium.launch()
                b.close()
                return name
            except Exception:
                continue
    return None


_PAGE_JS = r"""
window.layoutSlots = function (slots) {
  const out = {};
  for (const s of slots) {
    const el = document.getElementById('slot_' + s.key);
    const lines = Array.from(el.querySelectorAll('.ln'));
    const measure = () => {
      let maxW = 0;
      const ws = lines.map(ln => {
        const r = document.createRange(); r.selectNodeContents(ln.querySelector('.tx'));
        const w = r.getBoundingClientRect().width - s.ls_px_now();
        maxW = Math.max(maxW, w); return w;
      });
      return [ws, maxW];
    };
    let size = s.size, shrink = 1;
    const apply = () => { el.style.fontSize = size + 'px'; };
    s.ls_px_now = () => s.ls_em * size;
    apply();
    let [ws, maxW] = measure();
    for (let i = 0; i < 4 && maxW > s.w + 0.5; i++) {
      size = size * s.w / maxW; apply(); [ws, maxW] = measure();
    }
    shrink = size / s.size;
    const cap = s.cap * size, lh = s.lh * size, n = lines.length;
    const b0 = s.cy + cap / 2 - (n - 1) * lh / 2;
    lines.forEach((ln, i) => {
      const box = ln.getBoundingClientRect();
      const mark = ln.querySelector('.bl').getBoundingClientRect();
      const baseOff = mark.top - box.top;
      const padL = parseFloat(getComputedStyle(ln).paddingLeft);
      let x;
      if (s.align === 'left') x = s.cx - s.w / 2;
      else if (s.align === 'right') x = s.cx + s.w / 2 - ws[i];
      else x = s.cx - ws[i] / 2;
      ln.style.left = (x - padL) + 'px';
      ln.style.top = (b0 + i * lh - baseOff) + 'px';
    });
    out[s.key] = {font_size: size, shrink: shrink, baselines: lines.map((_, i) => b0 + i * lh)};
  }
  return out;
};
window.showOnly = function (key) {
  for (const el of document.querySelectorAll('.slot'))
    el.style.visibility = (key === null || el.dataset.key === key) ? 'visible' : 'hidden';
};
"""


def _build_html(kit: Kit, slots: list[dict], styles: dict, W: int, H: int) -> tuple[str, list[dict]]:
    faces, fams = [], {}
    for st in styles.values():
        key = st["font"]
        if key in fams:
            continue
        path = kit.font_path(key)
        fam = f"ck_{key}"
        fams[key] = fam
        b64 = base64.b64encode(path.read_bytes()).decode()
        fmt = "opentype" if path.suffix.lower() == ".otf" else "truetype"
        faces.append(f'@font-face{{font-family:"{fam}";src:url(data:font/{path.suffix[1:]};base64,{b64}) '
                     f'format("{fmt}");font-weight:100 900;font-style:normal;}}')
    body, meta = [], []
    for slot in slots:
        st = styles[slot["id"]]
        fill = fill_css(kit.fill(st.get("fill", "gold")), kit.dir)
        ls = st.get("letter_spacing", 0)
        ls_em = float(str(ls).replace("em", "")) if str(ls).endswith("em") or isinstance(ls, (int, float)) else 0.0
        css = [f'font-family:"{fams[st["font"]]}"', f"font-weight:{st['weight']}", f"letter-spacing:{ls_em}em",
               f"background-image:{fill}", "background-size:100% 100%"]
        if st.get("uppercase"):
            css.append("text-transform:uppercase")
        if st.get("italic"):
            css.append("font-style:italic")
        if st.get("shadow"):
            css.append(f"filter:{st['shadow']}")
        if st.get("numeric"):
            css.append(f"font-variant-numeric:{st['numeric']}")
        sep = st.get("separator")
        lines_html = []
        for line in str(slot["text"]).split("\n"):
            if sep and "|" in line:
                a, b = line.split("|", 1)
                bar_css = (f'width:{sep.get("width", 3)}px;height:{sep.get("height", 1.1)}em;'
                           f'margin:0 {sep.get("gap", 0.25)}em;vertical-align:{sep.get("drop", -0.1)}em;'
                           f'background-image:{fill};background-size:100% 100%')
                bar = f'<i class="sep" style="{html.escape(bar_css, quote=True)}"></i>'
                inner = f"{html.escape(a)}{bar}{html.escape(b)}"
            else:
                inner = html.escape(line)
            lines_html.append(f'<span class="ln" style="{html.escape(";".join(css), quote=True)}"><i class="bl"></i>'
                              f'<span class="tx">{inner}</span></span>')
        body.append(f'<div class="slot" id="slot_{slot["key"]}" data-key="{slot["key"]}">'
                    + "".join(lines_html) + "</div>")
        meta.append({"key": slot["key"], "size": float(st["size"]), "w": float(slot["w"]),
                     "cx": float(slot["cx"]), "cy": float(slot["cy"]) + float(slot.get("dy", 0)),
                     "align": slot.get("align", "center"), "lh": float(st["line_height"]),
                     "ls_em": ls_em, "cap": st["_cap"]})
    doc = f"""<!doctype html><html lang="vi"><head><meta charset="utf-8"><style>
{''.join(faces)}
html,body{{margin:0;padding:0;background:transparent;width:{W}px;height:{H}px;overflow:hidden}}
.slot{{position:absolute;left:0;top:0;width:{W}px;height:{H}px}}
.ln{{position:absolute;white-space:pre;line-height:1.5;padding:0.5em 0.7em;display:inline-block;
  -webkit-background-clip:text;background-clip:text;color:transparent;-webkit-text-fill-color:transparent}}
.bl{{display:inline-block;width:0;height:0;vertical-align:baseline}}
.sep{{display:inline-block}}
</style></head><body>{''.join(body)}<script>{_PAGE_JS}</script></body></html>"""
    return doc, meta


def check_glyphs(text: str, cmap: set, uppercase: bool) -> str:
    t = text.upper() if uppercase else text
    return "".join(sorted({c for c in t if not c.isspace() and c != "|" and ord(c) not in cmap}))


def render_texts(kit: Kit, slots: list[dict], W: int, H: int, scale: float, work_dir: Path,
                 ) -> tuple[list[TextPiece], list[str]]:
    """Chụp từng ô chữ. `slots`: ô chữ trong layout đã thay nội dung khách hàng."""
    from playwright.sync_api import sync_playwright

    warnings: list[str] = []
    styles, metrics = {}, {}
    for i, slot in enumerate(slots):
        slot["key"] = f"k{i}"
        st = resolve_style(kit, slot)
        if st["font"] not in metrics:
            metrics[st["font"]] = _font_metrics(kit.font_path(st["font"]))
        m = metrics[st["font"]]
        st["_cap"] = float(st.get("cap_ratio", m["cap"]))
        st["_family"] = m["family"]
        styles[slot["id"]] = st
        miss = check_glyphs(str(slot["text"]), m["cmap"], bool(st.get("uppercase")))
        if miss:
            warnings.append(f"Ô chữ '{slot['id']}': font {m['family']} thiếu ký tự {miss!r}.")

    doc, meta = _build_html(kit, slots, styles, W, H)
    work_dir.mkdir(parents=True, exist_ok=True)
    page_path = work_dir / "text.html"
    page_path.write_text(doc, encoding="utf-8")

    pieces: list[TextPiece] = []
    with sync_playwright() as pw:
        browser = launch_browser(pw)
        page = browser.new_page(viewport={"width": W, "height": H}, device_scale_factor=scale)
        page.goto(page_path.as_uri())
        # @font-face chỉ tải khi được dùng → tải chủ động trước khi đo, nếu không sẽ đo bằng font dự phòng.
        status = page.evaluate("Promise.all([...document.fonts].map(f => f.load().then(() => f.status, () => 'error')))")
        if "error" in status:
            raise ConfigError("Chromium không nạp được font của kit (file font hỏng?).")
        for m in meta:
            m["size0"], m["w0"], m["cx0"] = m["size"], m["w"], m["cx"]
        fitted = page.evaluate("s => window.layoutSlots(s)", meta)
        shots = {}
        for m in meta:
            page.evaluate("k => window.showOnly(k)", m["key"])
            shots[m["key"]] = _fit_and_shoot(page, m, fitted[m["key"]], scale)

        # Nhóm đồng cỡ (vd. tên cô dâu & chú rể): cả nhóm dùng chung cỡ nhỏ nhất sau khi đã vừa khung.
        groups: dict[str, list[dict]] = {}
        for m, slot in zip(meta, slots):
            if slot.get("group"):
                groups.setdefault(slot["group"], []).append(m)
        id_of = {m["key"]: s["id"] for m, s in zip(meta, slots)}
        for gname, members in groups.items():
            target = min(shots[m["key"]][2]["font_size"] for m in members)
            limiter = min(members, key=lambda m: shots[m["key"]][2]["font_size"])
            ratio = target / limiter["size0"]
            if ratio < 0.99:
                warnings.append(f"Nhóm '{gname}' ({len(members)} ô) tự thu nhỏ còn {ratio * 100:.0f}% cho đồng cỡ – "
                                f"do ô '{id_of[limiter['key']]}' dài nhất.")
            for m in members:
                if shots[m["key"]][2]["font_size"] - target < 0.5:
                    continue
                m.update(size=target, w=m["w0"], cx=m["cx0"])
                page.evaluate("k => window.showOnly(k)", m["key"])
                info = page.evaluate("s => window.layoutSlots(s)", [m])[m["key"]]
                shots[m["key"]] = _fit_and_shoot(page, m, info, scale)

        for m, slot in zip(meta, slots):
            st = styles[slot["id"]]
            im, ink, info = shots[m["key"]]
            info["shrink"] = info["font_size"] / m["size0"]
            if info["shrink"] < 0.99 and not slot.get("group"):
                msg = f"Ô chữ '{slot['id']}' dài hơn vùng an toàn → đã tự thu nhỏ còn {info['shrink'] * 100:.0f}%."
                if info["shrink"] < float(st.get("min_scale", 0.6)):
                    msg += " Nên rút gọn nội dung hoặc nới 'w'."
                warnings.append(msg)
            pieces.append(TextPiece(slot["id"], im, {
                "id": slot["id"], "text": slot["text"], "style": slot["style"],
                "font_family": st["_family"], "font_file": Path(kit.font_path(st["font"])).name,
                "font_weight": st["weight"], "font_size": round(info["font_size"] * scale, 2),
                "letter_spacing_em": meta[len(pieces)]["ls_em"], "uppercase": bool(st.get("uppercase")),
                "align": slot.get("align", "center"), "fill_css": fill_css(kit.fill(st.get("fill", "gold")), kit.dir)
                if kit.fill(st.get("fill", "gold")).get("type") != "texture" else "texture",
                "shadow_css": st.get("shadow", ""), "numeric": st.get("numeric", ""),
                "italic": bool(st.get("italic")),
                "center": [round(float(slot["cx"]) * scale, 1), round((float(slot["cy"]) + float(slot.get("dy", 0))) * scale, 1)],
                "max_width": round(float(slot["w"]) * scale, 1),
                "baselines": [round(b * scale, 1) for b in info["baselines"]],
                "shrink": round(info["shrink"], 3), "bbox": ink}))
        browser.close()
    return pieces, warnings


def _fit_and_shoot(page, m: dict, info: dict, scale: float):
    """Chụp một ô chữ; 'w' là vùng an toàn tính theo MỰC THẬT.

    Nét uốn của font viết tay tràn khỏi bề rộng con chữ, nên nếu mực tràn khỏi
    [cx0−w0/2, cx0+w0/2] thì thu hẹp (giữ mép neo khi căn trái/phải) và dựng lại.
    """
    al, ar = m["cx0"] - m["w0"] / 2, m["cx0"] + m["w0"] / 2
    im, xs, ys = None, np.array([]), np.array([])
    for _ in range(4):
        png = page.screenshot(omit_background=True, type="png")
        im = Image.open(io.BytesIO(png)).convert("RGBA")
        ys, xs = np.nonzero(np.asarray(im)[..., 3] > 40)
        if not len(xs):
            break
        over_l = max(0.0, al - xs.min() / scale)
        over_r = max(0.0, (xs.max() + 1) / scale - ar)
        if over_l + over_r <= 1.0:
            break
        if m["align"] == "center":
            m["w"] -= 2 * max(over_l, over_r) + 1
        else:
            m["cx"] += (over_l - over_r) / 2
            m["w"] -= over_l + over_r + 1
        info = page.evaluate("s => window.layoutSlots(s)", [m])[m["key"]]
    ink = [int(xs.min()), int(ys.min()), int(xs.max() - xs.min() + 1), int(ys.max() - ys.min() + 1)] \
        if len(xs) else [0, 0, 0, 0]
    return im, ink, info
