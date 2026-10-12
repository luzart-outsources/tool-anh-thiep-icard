"""Khổ thiệp: khổ in phổ biến (300 DPI), màn hình điện thoại / banner web, hoặc tuỳ chỉnh – dọc, ngang, vuông."""
from __future__ import annotations

import re

from .config import ConfigError

DPI = 300

SIZES = [
    {"id": "a5", "label": "A5 – 14,8 × 21 cm", "cm": (14.8, 21.0)},
    {"id": "15x21", "label": "15 × 21 cm", "cm": (15.0, 21.0)},
    {"id": "13x18", "label": "13 × 18 cm", "cm": (13.0, 18.0)},
    {"id": "12x18", "label": "12 × 18 cm", "cm": (12.0, 18.0)},
    {"id": "10x15", "label": "10 × 15 cm", "cm": (10.0, 15.0)},
    {"id": "15x15", "label": "Vuông 15 × 15 cm", "cm": (15.0, 15.0)},
    {"id": "21x14.8", "label": "A5 ngang – 21 × 14,8 cm", "cm": (21.0, 14.8)},
    {"id": "phone", "label": "Màn hình điện thoại 9:16 (thiệp online)", "px": (1080, 1920)},
    {"id": "web", "label": "Banner web ngang 16:9", "px": (1920, 1080)},
]
BY_ID = {s["id"]: s for s in SIZES}


def cm_to_px(cm: float, dpi: int = DPI) -> int:
    return int(round(cm / 2.54 * dpi))


def resolve_size(spec: str | None) -> dict:
    """'a5' | '12x18' (cm) | '1080x1920px' | None → {id, label, px:(w,h), cm?}."""
    if not spec:
        spec = "a5"
    s = str(spec).strip().lower().replace(",", ".").replace(" ", "")
    if s in BY_ID:
        base = BY_ID[s]
    else:
        m = re.fullmatch(r"(\d+(?:\.\d+)?)[x×*](\d+(?:\.\d+)?)(px|cm)?", s)
        if not m:
            raise ConfigError(f"Khổ thiệp '{spec}' không hợp lệ. Dùng vd. a5, 12x18 (cm) hoặc 1080x1920px.")
        a, b, unit = float(m.group(1)), float(m.group(2)), m.group(3) or "cm"
        if unit == "px":
            base = {"id": f"{int(a)}x{int(b)}px", "label": f"{int(a)} × {int(b)} px", "px": (int(a), int(b))}
        else:
            if not (4 <= a <= 60 and 4 <= b <= 60):
                raise ConfigError("Kích thước tuỳ chỉnh phải trong khoảng 4–60 cm.")
            base = {"id": f"{a:g}x{b:g}", "label": f"{a:g} × {b:g} cm", "cm": (a, b)}
    out = dict(base)
    if "px" not in out:
        out["px"] = (cm_to_px(out["cm"][0]), cm_to_px(out["cm"][1]))
    w, h = out["px"]
    if not (64 <= w <= 12000 and 64 <= h <= 12000):
        raise ConfigError("Kích thước theo px phải trong khoảng 64–12000.")
    return out
