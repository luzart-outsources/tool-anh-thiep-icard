"""Dựng layer nền và layer hoa văn bằng Pillow – đặt ảnh 1:1, chính xác từng pixel."""
from __future__ import annotations

import cv2
import numpy as np
from PIL import Image

from .config import Kit, Layout
from .fills import fill_array, hex_rgb
from .layout import Placed


def resize_rgba(im: Image.Image, size: tuple[int, int]) -> Image.Image:
    """Đổi cỡ trên ảnh nhân sẵn alpha (premultiplied) để mép không bị viền đen/sáng."""
    if im.size == size:
        return im
    return im.convert("RGBa").resize(size, Image.LANCZOS).convert("RGBA")


def paste_over(canvas: Image.Image, im: Image.Image, x: int, y: int) -> None:
    """alpha_composite có cắt xén khi ảnh tràn ra ngoài khung."""
    W, H = canvas.size
    w, h = im.size
    x0, y0, x1, y1 = max(0, x), max(0, y), min(W, x + w), min(H, y + h)
    if x0 >= x1 or y0 >= y1:
        return
    canvas.alpha_composite(im.crop((x0 - x, y0 - y, x1 - x, y1 - y)), dest=(x0, y0))


def _rgba_from(color: np.ndarray, alpha: np.ndarray) -> Image.Image:
    a = np.clip(alpha * 255 + 0.5, 0, 255).astype(np.uint8)
    c = np.clip(color + 0.5, 0, 255).astype(np.uint8)
    return Image.fromarray(np.dstack([c, a]), "RGBA")


# ---------------------------------------------------------------- nền

def render_background(kit: Kit, layout: Layout, W: int, H: int) -> Image.Image:
    opts = {**kit.data.get("background", {}), **layout.data.get("background", {})}
    asset = opts.get("asset", "nen")
    path = kit.assets_dir / f"{asset}.png"
    if path.exists():
        im = Image.open(path).convert("RGB")
        iw, ih = im.size
        s = max(W / iw, H / ih)
        nw, nh = max(W, round(iw * s)), max(H, round(ih * s))
        im = im.resize((nw, nh), Image.LANCZOS)
        left, top = (nw - W) // 2, (nh - H) // 2
        im = im.crop((left, top, left + W, top + H))
    else:
        color = opts.get("color") or (kit.data.get("palette") or ["#1b3a2a"])[0]
        im = Image.new("RGB", (W, H), hex_rgb(color))
    v = float(opts.get("vignette", 0))
    if v > 0:
        arr = np.asarray(im).astype(np.float32)
        yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
        r2 = (((xx / (W - 1)) * 2 - 1) ** 2 + ((yy / (H - 1)) * 2 - 1) ** 2) / 2
        arr *= (1 - v * r2 ** 1.5)[..., None]
        im = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), "RGB")
    return im


# ---------------------------------------------------------------- hoa văn

class OrnamentRenderer:
    def __init__(self, kit: Kit, W: int, H: int, scale: float, shape_mask=None):
        self.kit, self.W, self.H, self.scale = kit, W, H, scale
        self.shape_mask = shape_mask          # None = chữ nhật
        self._src: dict[str, Image.Image] = {}
        self._upscaled: dict[str, tuple[float, set]] = {}

    @property
    def warnings(self) -> list[str]:
        out = []
        for asset, (ratio, ids) in self._upscaled.items():
            w, h = self.source(asset).size
            out.append(f"asset '{asset}' ({w}×{h}) bị phóng to tới {ratio:.1f}× – có thể mềm nét "
                       f"(dùng ở: {', '.join(sorted(ids))}).")
        return out

    def natural_size(self, asset: str) -> tuple[int, int]:
        return self.source(asset).size

    def source(self, asset: str) -> Image.Image:
        if asset not in self._src:
            self._src[asset] = Image.open(self.kit.asset_path(asset)).convert("RGBA")
        return self._src[asset]

    def element(self, p: Placed) -> tuple[Image.Image, int, int]:
        """Ảnh RGBA của một mảnh và vị trí góc trên-trái trên khung."""
        el = p.el
        if p.type == "asset":
            src = self.source(el["asset"])
            ratio = max(p.w / src.width, p.h / src.height)
            if ratio > 1.15:
                prev, ids = self._upscaled.get(el["asset"], (0.0, set()))
                self._upscaled[el["asset"]] = (max(prev, ratio), ids | {p.id})
            im = resize_rgba(src, (p.w, p.h))
            if p.flip_h:
                im = im.transpose(Image.FLIP_LEFT_RIGHT)
            if p.flip_v:
                im = im.transpose(Image.FLIP_TOP_BOTTOM)
            op = float(el.get("opacity", 1))
            if op < 1:
                a = np.asarray(im).copy()
                a[..., 3] = (a[..., 3].astype(np.float32) * op).astype(np.uint8)
                im = Image.fromarray(a, "RGBA")
            if p.rot:              # xoay trên ảnh nhân sẵn alpha → mép không viền tối
                cx, cy = p.x + p.w / 2, p.y + p.h / 2
                im = im.convert("RGBa").rotate(-p.rot, resample=Image.BICUBIC, expand=True).convert("RGBA")
                return im, round(cx - im.width / 2), round(cy - im.height / 2)
            return im, p.x, p.y
        if p.type == "rule":
            return self._rule(p), p.x, p.y
        if p.type == "border":
            return self._border(p), 0, 0
        raise ValueError(p.type)

    def _rule(self, p: Placed) -> Image.Image:
        el = p.el
        horiz = el.get("orient", "h") == "h"
        length = p.w if horiz else p.h
        fade = float(el.get("fade", 0.25))
        fade_px = fade * length if fade <= 0.5 else fade * self.scale
        pos = np.arange(length, dtype=np.float32) + 0.5
        ramp = np.clip(np.minimum(pos, length - pos) / max(fade_px, 1e-3), 0, 1)
        ramp = ramp * ramp * (3 - 2 * ramp)
        alpha = np.tile(ramp, (p.h, 1)) if horiz else np.tile(ramp[:, None], (1, p.w))
        color = fill_array(self.kit.fill(el.get("fill", "gold")), p.w, p.h, self.kit.dir)
        return _rgba_from(color, alpha * float(el.get("opacity", 1)))

    def _border(self, p: Placed) -> Image.Image:
        el, W, H, s = p.el, self.W, self.H, self.scale
        if self.shape_mask is not None:       # hình không phải chữ nhật: viền song song mép hình
            from .shapes import border_alpha
            lines = [(float(ln["inset"]) * s, max(1.0, float(ln.get("width", 2)) * s), float(ln.get("opacity", 1)))
                     for ln in el.get("lines", [])]
            color = fill_array(self.kit.fill(el.get("fill", "gold")), W, H, self.kit.dir)
            return _rgba_from(color, border_alpha(self.shape_mask, lines))
        mask = np.zeros((H, W), np.float32)
        for ln in el.get("lines", []):
            i = int(round(float(ln["inset"]) * s))
            t = max(1, int(round(float(ln.get("width", 2)) * s)))
            op = float(ln.get("opacity", 1))
            m = np.zeros((H, W), np.float32)
            m[i:i + t, i:W - i] = 1
            m[H - i - t:H - i, i:W - i] = 1
            m[i:H - i, i:i + t] = 1
            m[i:H - i, W - i - t:W - i] = 1
            mask = np.maximum(mask, m * op)
        color = fill_array(self.kit.fill(el.get("fill", "gold")), W, H, self.kit.dir)
        return _rgba_from(color, mask)

    def shadow(self, layer: Image.Image, opts: dict | None) -> Image.Image | None:
        if not opts:
            return None
        s = self.scale
        src = np.asarray(layer)[..., 3]
        ys, xs = np.nonzero(src)
        if not len(xs):
            return None
        dx, dy = int(round(float(opts.get("dx", 0)) * s)), int(round(float(opts.get("dy", 3)) * s))
        blur = float(opts.get("blur", 4)) * s
        # Chỉ tính trong vùng bao quanh phần có hình (+ lề cho độ nhoè/độ lệch) thay vì cả khung.
        m = int(blur * 3) + abs(dx) + abs(dy) + 2
        H, W = src.shape
        x0, y0 = max(0, xs.min() - m), max(0, ys.min() - m)
        x1, y1 = min(W, xs.max() + 1 + m), min(H, ys.max() + 1 + m)
        a = np.zeros((y1 - y0, x1 - x0), np.float32)
        sx0, sy0 = max(x0, x0 - dx), max(y0, y0 - dy)
        sx1, sy1 = min(x1, x1 - dx), min(y1, y1 - dy)
        a[sy0 + dy - y0:sy1 + dy - y0, sx0 + dx - x0:sx1 + dx - x0] = src[sy0:sy1, sx0:sx1] / 255.0
        if blur > 0:
            a = cv2.GaussianBlur(a, (0, 0), blur)
        a *= float(opts.get("opacity", 0.45))
        color = np.broadcast_to(np.array(hex_rgb(opts.get("color", "#000000")), np.float32), (*a.shape, 3))
        out = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        out.paste(_rgba_from(color, a), (x0, y0))
        return out

    def compose(self, placed: list[Placed], shadow_opts: dict | None) -> Image.Image:
        W, H = self.W, self.H
        body = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        casts = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        has_cast = False
        for p in placed:
            im, x, y = self.element(p)
            paste_over(body, im, x, y)
            if p.el.get("shadow", True):
                paste_over(casts, im, x, y)
                has_cast = True
        sh = self.shadow(casts, shadow_opts) if has_cast else None
        return Image.alpha_composite(sh, body) if sh is not None else body
