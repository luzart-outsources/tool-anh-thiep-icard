"""Kiểu tô màu dùng chung cho hoa văn vẽ bằng code (Pillow) và chữ (CSS).

Hai phía dùng cùng quy ước góc của CSS linear-gradient (0deg = từ dưới lên,
90deg = từ trái sang), nên đường viền và chữ có cùng kiểu ánh kim.
"""
from __future__ import annotations

import base64
import math
from pathlib import Path

import numpy as np
from PIL import Image


def hex_rgb(h: str) -> tuple[int, int, int]:
    h = h.strip().lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if len(h) not in (6, 8):
        raise ValueError(f"Mã màu không hợp lệ: #{h}")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _stops(spec) -> list[tuple[tuple[int, int, int], float]]:
    raw = spec["stops"]
    out = []
    for i, s in enumerate(raw):
        if isinstance(s, str):
            out.append((hex_rgb(s), i / max(1, len(raw) - 1)))
        else:
            out.append((hex_rgb(s[0]), float(s[1])))
    return out


def fill_array(spec: dict, w: int, h: int, base_dir: Path | None = None) -> np.ndarray:
    """Ảnh màu HxWx3 (float 0..255) phủ một hộp w×h theo kiểu tô."""
    t = spec.get("type", "color")
    if t == "color":
        return np.broadcast_to(np.array(hex_rgb(spec["color"]), np.float32), (h, w, 3)).copy()
    if t == "gradient":
        a = math.radians(float(spec.get("angle", 180)))
        dx, dy = math.sin(a), -math.cos(a)
        length = abs(w * dx) + abs(h * dy) or 1.0
        yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
        pos = ((xx + 0.5 - w / 2) * dx + (yy + 0.5 - h / 2) * dy) / length + 0.5
        stops = _stops(spec)
        ps = np.array([p for _, p in stops], np.float32)
        out = np.empty((h, w, 3), np.float32)
        for c in range(3):
            out[..., c] = np.interp(pos, ps, np.array([col[c] for col, _ in stops], np.float32))
        return out
    if t == "texture":
        p = Path(spec["image"])
        if base_dir is not None and not p.is_absolute():
            p = base_dir / p
        tex = Image.open(p).convert("RGB")
        tw, th = tex.size
        tiles = Image.new("RGB", (w, h))
        for y in range(0, h, th):
            for x in range(0, w, tw):
                tiles.paste(tex, (x, y))
        return np.asarray(tiles).astype(np.float32)
    raise ValueError(f"Kiểu tô không hỗ trợ: {t}")


def fill_css(spec: dict, base_dir: Path | None = None) -> str:
    """Giá trị CSS background-image tương đương."""
    t = spec.get("type", "color")
    if t == "color":
        c = spec["color"]
        return f"linear-gradient({c}, {c})"
    if t == "gradient":
        parts = ", ".join(f"rgb{col} {p * 100:.1f}%" for col, p in _stops(spec))
        return f"linear-gradient({float(spec.get('angle', 180)):.1f}deg, {parts})"
    if t == "texture":
        p = Path(spec["image"])
        if base_dir is not None and not p.is_absolute():
            p = base_dir / p
        b64 = base64.b64encode(p.read_bytes()).decode()
        mime = "image/png" if p.suffix.lower() == ".png" else "image/jpeg"
        return f"url(data:{mime};base64,{b64})"
    raise ValueError(f"Kiểu tô không hỗ trợ: {t}")
