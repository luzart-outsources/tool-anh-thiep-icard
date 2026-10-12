"""Tính vị trí hình học: neo (anchor), kích thước, nhân bản đối xứng (mirror).

Mọi thứ ở đây là hàm thuần – không đọc ảnh – để dễ kiểm thử.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .config import ANCHORS


@dataclass
class Placed:
    id: str                    # id duy nhất của mảnh (dùng đặt tên file pieces/)
    type: str                  # "asset" | "rule" | "border"
    x: int
    y: int
    w: int
    h: int
    flip_h: bool = False
    flip_v: bool = False
    el: dict = field(default_factory=dict)
    rot: float = 0.0           # độ, chiều kim đồng hồ, quanh tâm ô

    @property
    def box(self) -> list[int]:
        return [self.x, self.y, self.w, self.h]

    def bounds(self) -> tuple[int, int, int, int]:
        """Khung bao thật (đã tính xoay)."""
        if not self.rot:
            return self.x, self.y, self.w, self.h
        import math
        a = math.radians(self.rot)
        bw = abs(self.w * math.cos(a)) + abs(self.h * math.sin(a))
        bh = abs(self.w * math.sin(a)) + abs(self.h * math.cos(a))
        cx, cy = self.x + self.w / 2, self.y + self.h / 2
        return round(cx - bw / 2), round(cy - bh / 2), max(1, round(bw)), max(1, round(bh))


def element_size(el: dict, natural: tuple[int, int] | None) -> tuple[float, float]:
    """Kích thước hiển thị: cho 'w' hoặc 'h' (giữ tỉ lệ ảnh), hoặc cả hai."""
    if el.get("type", "asset") == "rule":
        length, th = float(el["length"]), float(el.get("thickness", 2))
        return (length, th) if el.get("orient", "h") == "h" else (th, length)
    nw, nh = natural or (1, 1)
    if "w" in el and "h" in el:
        # Ô w×h: món đặt vào được thu cho VỪA TRONG Ô, giữ tỉ lệ (ảnh AI mỗi lần một tỉ lệ khác, món thay
        # thế có dáng khác) – trừ khi layout ghi rõ "fit": "stretch".
        if el.get("fit") == "stretch":
            return float(el["w"]), float(el["h"])
        s = min(float(el["w"]) / nw, float(el["h"]) / nh)
        return nw * s, nh * s
    if "w" in el:
        return float(el["w"]), float(el["w"]) * nh / nw
    return float(el["h"]) * nw / nh, float(el["h"])


def expand(elements: list[dict], canvas: tuple[int, int], naturals: dict[str, tuple[int, int]],
           scale: float = 1.0) -> list[Placed]:
    """Biến danh sách phần tử trong layout thành danh sách mảnh đã đặt vị trí (px nguyên).

    mirror: "x" (thêm bản lật trái↔phải), "y" (trên↔dưới), "xy" (4 góc).
    """
    W, H = canvas
    out: list[Placed] = []
    auto = 0
    for el in elements:
        t = el.get("type", "asset")
        if t == "border":
            auto += 1
            out.append(Placed(el.get("id", f"vien{'' if auto == 1 else auto}"), "border",
                              0, 0, round(W * scale), round(H * scale), el=el))
            continue
        sw, sh = element_size(el, naturals.get(el.get("asset", "")))
        ax, ay = ANCHORS[el.get("anchor", "c")]
        left, top = float(el["x"]) - ax * sw, float(el["y"]) - ay * sh
        fh = el.get("flip") in ("h", "hv", "vh")
        fv = el.get("flip") in ("v", "hv", "vh")
        base_id = el.get("id") or el.get("asset") or f"{t}_{len(out)}"
        rot = float(el.get("rotate", 0) or 0)
        copies = [(left, top, fh, fv, rot)]
        mirror = el.get("mirror", "")
        if "x" in mirror:          # bản đối xứng: lật + xoay ngược chiều
            copies += [(W - l_ - sw, t_, not h_, v_, -r_) for (l_, t_, h_, v_, r_) in copies]
        if "y" in mirror:
            copies += [(l_, H - t_ - sh, h_, not v_, -r_) for (l_, t_, h_, v_, r_) in copies]
        for (l_, t_, h_, v_, r_) in copies:
            pid = base_id
            if mirror:
                side_x = "l" if l_ + sw / 2 < W / 2 else "r"
                side_y = "t" if t_ + sh / 2 < H / 2 else "b"
                pid += "_" + ("".join([side_y if "y" in mirror else "", side_x if "x" in mirror else ""]))
            out.append(Placed(pid, t, round(l_ * scale), round(t_ * scale),
                              max(1, round(sw * scale)), max(1, round(sh * scale)), h_, v_, el, r_))
    seen = {}
    for p in out:
        if p.id in seen:
            seen[p.id] += 1
            p.id = f"{p.id}_{seen[p.id]}"
        else:
            seen[p.id] = 1
    return out


def adapt_to_ratio(data: dict, target_w: int, target_h: int) -> tuple[dict, float]:
    """Giãn bố cục (thiết kế cho một khổ) sang khổ khác, KHÔNG làm méo hoa văn/chữ.

    Khung thiết kế được nới theo chiều dài hơn (dọc hoặc ngang) cho đúng tỉ lệ khổ đích; vị trí các món
    giãn theo, còn kích thước món, cỡ chữ, viền giữ nguyên trong đơn vị thiết kế. Trả về (layout mới,
    hệ số scale để render ra đúng target_w × target_h px).
    """
    import copy
    c = data.get("canvas", {})
    dW, dH = float(c.get("w", 1748)), float(c.get("h", 2480))
    s = min(target_w / dW, target_h / dH)
    nW, nH = target_w / s, target_h / s
    fx, fy = nW / dW, nH / dH
    out = copy.deepcopy(data)
    out["canvas"] = {"w": round(nW, 2), "h": round(nH, 2)}
    for el in out.get("ornaments", []):
        t = el.get("type", "asset")
        if t == "border":
            continue
        el["x"] = float(el["x"]) * fx
        el["y"] = float(el["y"]) * fy
        if t == "rule":                       # đường kẻ kéo dài theo chiều được giãn
            el["length"] = float(el["length"]) * (fx if el.get("orient", "h") == "h" else fy)
    for ph in out.get("photos", []):
        ph["x"] = float(ph["x"]) * fx
        ph["y"] = float(ph["y"]) * fy
    for tx in out.get("texts", []):
        tx["cx"] = float(tx["cx"]) * fx
        tx["cy"] = float(tx["cy"]) * fy
        tx["w"] = float(tx["w"]) * fx
    return out, s
