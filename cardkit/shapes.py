"""Hình dáng thiệp (đường cắt): mặt nạ cắt cả 3 layer + đường viền chạy theo mép hình.

Mặt nạ vẽ ở ×4 rồi thu nhỏ (mép mịn). Viền tính theo KHOẢNG CÁCH tới mép hình (distance
transform), nên song song với mọi đường cong – vòm, oval, răng cưa… không cần code riêng.
"""
from __future__ import annotations

import math
import re

import cv2
import numpy as np

SHAPES = [
    {"id": "chu_nhat", "label": "Chữ nhật"},
    {"id": "bo_goc", "label": "Bo góc"},
    {"id": "vom", "label": "Vòm"},
    {"id": "goc_lom", "label": "Góc lõm"},
    {"id": "oval", "label": "Oval"},
    {"id": "rang_cua", "label": "Răng cưa"},
    {"id": "cat_goc", "label": "Cắt góc"},
]
IDS = [s["id"] for s in SHAPES]


def _draw(kind: str, W: int, H: int) -> np.ndarray:
    m = np.zeros((H, W), np.uint8)
    if kind == "chu_nhat":
        m[:] = 255
    elif kind == "bo_goc":
        r = int(W * 0.06)
        cv2.rectangle(m, (r, 0), (W - r, H), 255, -1)
        cv2.rectangle(m, (0, r), (W, H - r), 255, -1)
        for cx, cy in ((r, r), (W - r, r), (r, H - r), (W - r, H - r)):
            cv2.circle(m, (cx, cy), r, 255, -1)
    elif kind == "vom":
        r = W // 2
        cv2.rectangle(m, (0, r), (W, H), 255, -1)
        cv2.circle(m, (r, r), r, 255, -1)
    elif kind == "goc_lom":                            # 4 góc khoét cong vào trong (kiểu khung tranh)
        r = int(W * 0.07)
        m[:] = 255
        for cx, cy in ((0, 0), (W, 0), (0, H), (W, H)):
            cv2.circle(m, (cx, cy), r, 0, -1)
    elif kind == "oval":
        cv2.ellipse(m, (W // 2, H // 2), (W // 2, H // 2), 0, 0, 360, 255, -1)
    elif kind == "rang_cua":
        r = max(4, int(W / 26))
        cv2.rectangle(m, (r, r), (W - r, H - r), 255, -1)
        nx = max(2, round((W - 2 * r) / (2 * r)))
        ny = max(2, round((H - 2 * r) / (2 * r)))
        for i in range(nx + 1):
            x = int(r + i * (W - 2 * r) / nx)
            cv2.circle(m, (x, r), r, 255, -1)
            cv2.circle(m, (x, H - r), r, 255, -1)
        for j in range(ny + 1):
            y = int(r + j * (H - 2 * r) / ny)
            cv2.circle(m, (r, y), r, 255, -1)
            cv2.circle(m, (W - r, y), r, 255, -1)
    elif kind == "cat_goc":
        c = int(W * 0.08)
        pts = np.array([(c, 0), (W - c, 0), (W, c), (W, H - c), (W - c, H), (c, H), (0, H - c), (0, c)], np.int32)
        cv2.fillPoly(m, [pts], 255)
    else:
        raise ValueError(f"Hình dáng không hỗ trợ: {kind}")
    return m


# ---------------------------------------------------------------- hình tự do: SVG path do AI / người dùng vẽ

_NUM = re.compile(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")
_CMDS = "MmLlHhVvCcSsQqTtAaZz"


def _tokens(d: str) -> list[str]:
    out, i, n = [], 0, len(d)
    while i < n:
        c = d[i]
        if c in _CMDS:
            out.append(c)
            i += 1
        elif c in " ,\t\r\n":
            i += 1
        else:
            m = _NUM.match(d, i)
            if not m:
                raise ValueError(f"ký tự lạ '{c}' ở vị trí {i}")
            out.append(m.group())
            i = m.end()
    return out


def _arc(x1, y1, rx, ry, phi_deg, fa, fs, x2, y2):
    """Cung elip SVG (điểm đầu-cuối → tâm, theo SVG 1.1 mục F.6.5) → các điểm trên cung."""
    if rx == 0 or ry == 0 or (x1 == x2 and y1 == y2):
        return [(x2, y2)]
    rx, ry = abs(rx), abs(ry)
    phi = math.radians(phi_deg)
    c, s = math.cos(phi), math.sin(phi)
    dx, dy = (x1 - x2) / 2, (y1 - y2) / 2
    x1p, y1p = c * dx + s * dy, -s * dx + c * dy
    lam = x1p ** 2 / rx ** 2 + y1p ** 2 / ry ** 2
    if lam > 1:
        rx, ry = rx * math.sqrt(lam), ry * math.sqrt(lam)
    num = rx * rx * ry * ry - rx * rx * y1p * y1p - ry * ry * x1p * x1p
    den = rx * rx * y1p * y1p + ry * ry * x1p * x1p
    co = math.sqrt(max(0.0, num / den)) if den else 0.0
    if fa == fs:
        co = -co
    cxp, cyp = co * rx * y1p / ry, -co * ry * x1p / rx
    cx, cy = c * cxp - s * cyp + (x1 + x2) / 2, s * cxp + c * cyp + (y1 + y2) / 2
    ang = lambda ux, uy, vx, vy: math.atan2(ux * vy - uy * vx, ux * vx + uy * vy)
    t1 = ang(1, 0, (x1p - cxp) / rx, (y1p - cyp) / ry)
    dt = ang((x1p - cxp) / rx, (y1p - cyp) / ry, (-x1p - cxp) / rx, (-y1p - cyp) / ry)
    if not fs and dt > 0:
        dt -= 2 * math.pi
    elif fs and dt < 0:
        dt += 2 * math.pi
    n = max(4, int(abs(dt) / (math.pi / 48)))
    pts = []
    for k in range(1, n + 1):
        t = t1 + dt * k / n
        px, py = rx * math.cos(t), ry * math.sin(t)
        pts.append((c * px - s * py + cx, s * px + c * py + cy))
    return pts


def path_polys(d: str, steps: int = 24) -> list[list[tuple[float, float]]]:
    """Đường SVG (M L H V C S Q T A Z, tuyệt đối/tương đối) → danh sách đa giác khép kín."""
    toks = _tokens(str(d))
    i, polys, cur = 0, [], []
    x = y = sx = sy = 0.0
    cmd, prev, ctrl = None, "", None

    def num():
        nonlocal i
        if i >= len(toks) or toks[i] in _CMDS:
            raise ValueError(f"thiếu số sau lệnh {cmd}")
        i += 1
        return float(toks[i - 1])

    def flag():
        nonlocal i
        if i >= len(toks):
            raise ValueError("thiếu cờ của lệnh cung A")
        t = toks[i]
        if t in ("0", "1"):
            i += 1
            return int(t)
        if t[0] in "01" and len(t) > 1 and t[1] != ".":   # cờ viết dính: "a10 10 0 0110 10"
            toks[i] = t[1:]
            return int(t[0])
        raise ValueError(f"cờ cung không hợp lệ '{t}'")

    def bez(p0, p1, p2, p3=None):
        out = []
        for k in range(1, steps + 1):
            t = k / steps
            if p3 is None:
                bx = (1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * p1[0] + t * t * p2[0]
                by = (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * p1[1] + t * t * p2[1]
            else:
                bx = (1 - t) ** 3 * p0[0] + 3 * (1 - t) ** 2 * t * p1[0] + 3 * (1 - t) * t * t * p2[0] + t ** 3 * p3[0]
                by = (1 - t) ** 3 * p0[1] + 3 * (1 - t) ** 2 * t * p1[1] + 3 * (1 - t) * t * t * p2[1] + t ** 3 * p3[1]
            out.append((bx, by))
        return out

    while i < len(toks):
        if toks[i] in _CMDS:
            cmd = toks[i]
            i += 1
        elif cmd is None:
            raise ValueError("đường phải bắt đầu bằng lệnh M")
        C, rel = cmd.upper(), cmd.islower()
        ox, oy = (x, y) if rel else (0.0, 0.0)
        if C == "Z":
            if len(cur) > 2:
                polys.append(cur)
            cur, x, y, ctrl = [], sx, sy, None
            prev = "Z"
            continue
        if C == "M":
            if len(cur) > 2:
                polys.append(cur)
            x, y = num() + ox, num() + oy
            sx, sy, cur, ctrl = x, y, [(x, y)], None
            cmd = "l" if rel else "L"                      # số tiếp theo sau M là lệnh L ngầm
            prev = "M"
            continue
        if not cur:
            cur = [(x, y)]
        if C == "L":
            x, y = num() + ox, num() + oy
            cur.append((x, y))
            ctrl = None
        elif C == "H":
            x = num() + ox
            cur.append((x, y))
            ctrl = None
        elif C == "V":
            y = num() + oy
            cur.append((x, y))
            ctrl = None
        elif C in "CS":
            if C == "C":
                c1 = (num() + ox, num() + oy)
            else:
                c1 = (2 * x - ctrl[0], 2 * y - ctrl[1]) if ctrl and prev in "CS" else (x, y)
            c2 = (num() + ox, num() + oy)
            end = (num() + ox, num() + oy)
            cur += bez((x, y), c1, c2, end)
            ctrl, (x, y) = c2, end
        elif C in "QT":
            if C == "Q":
                c1 = (num() + ox, num() + oy)
            else:
                c1 = (2 * x - ctrl[0], 2 * y - ctrl[1]) if ctrl and prev in "QT" else (x, y)
            end = (num() + ox, num() + oy)
            cur += bez((x, y), c1, end)
            ctrl, (x, y) = c1, end
        elif C == "A":
            rx, ry, rot = num(), num(), num()
            fa, fs = flag(), flag()
            end = (num() + ox, num() + oy)
            cur += _arc(x, y, rx, ry, rot, fa, fs, *end)
            (x, y), ctrl = end, None
        prev = C
    if len(cur) > 2:
        polys.append(cur)
    if not polys:
        raise ValueError("đường không tạo thành hình khép kín nào")
    return polys


def _fill_polys(polys, w: int, h: int, dW: float, dH: float) -> np.ndarray:
    m = np.zeros((h, w), np.uint8)
    pts = [np.round(np.array(p, np.float64) * [w / dW, h / dH] * 16).astype(np.int32) for p in polys if len(p) > 2]
    cv2.fillPoly(m, pts, 255, lineType=cv2.LINE_AA, shift=4)   # toạ độ 1/16 px cho mép mịn
    return m


def check_path(d: str, W: float, H: float) -> str | None:
    """Lỗi dễ hiểu nếu đường cắt không dùng được (None = ổn)."""
    try:
        polys = path_polys(d)
    except (ValueError, IndexError) as e:
        return f"đường SVG lỗi: {e}"
    m = _fill_polys(polys, 200, max(1, round(200 * H / W)), W, H)
    cover = float((m > 127).mean())
    if cover < 0.25:
        return f"hình chỉ phủ {cover:.0%} khung thiệp (toạ độ phải theo khung {W:g}×{H:g})"
    return None


def shape_mask(kind, W: int, H: int, ss: int = 4, design: tuple[float, float] | None = None) -> np.ndarray:
    """Mặt nạ float32 0..1 kích thước H×W, mép khử răng cưa.

    kind: tên hình có sẵn ("vom", "oval"…) hoặc {"path": "M…Z"} – đường SVG theo toạ độ khung thiết kế
    `design` (rộng, cao); khung khác tỉ lệ (đổi khổ) thì đường được giãn theo.
    """
    if isinstance(kind, dict):
        if kind.get("path"):
            dW, dH = design or (W, H)
            big = _fill_polys(path_polys(kind["path"]), W * ss, H * ss, dW, dH)
            return cv2.resize(big, (W, H), interpolation=cv2.INTER_AREA).astype(np.float32) / 255.0
        kind = kind.get("preset", "chu_nhat")
    if kind in (None, "", "chu_nhat"):
        return np.ones((H, W), np.float32)
    big = _draw(kind, W * ss, H * ss)
    return cv2.resize(big, (W, H), interpolation=cv2.INTER_AREA).astype(np.float32) / 255.0


def shape_label(kind) -> str:
    if isinstance(kind, dict):
        return kind.get("label") or "Hình riêng"
    return {z["id"]: z["label"] for z in SHAPES}.get(kind, str(kind))


def border_alpha(mask: np.ndarray, lines: list[tuple[float, float, float]]) -> np.ndarray:
    """Các nét viền song song mép hình: lines = [(cách mép px, độ dày px, độ đậm)]."""
    # Đệm 2px "ngoài hình" quanh ảnh: không có đệm thì mép ẢNH không được tính là mép hình
    # (cạnh thẳng trùng mép ảnh sẽ mất viền).
    inside = np.pad((mask > 0.5).astype(np.uint8), 2)
    d = cv2.distanceTransform(inside, cv2.DIST_L2, 5).astype(np.float32)[2:-2, 2:-2]
    d += mask - 0.5                                   # bù nửa pixel từ mép khử răng cưa
    out = np.zeros_like(mask)
    for inset, width, op in lines:
        a = np.clip(d - inset + 0.5, 0, 1) * np.clip(inset + width - d + 0.5, 0, 1)
        out = np.maximum(out, a * op)
    return out
