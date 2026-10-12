"""Tách nền (keying) cho asset hoa văn.

Mô hình ghép ảnh: I = α·F + (1−α)·B
  I: màu pixel quan sát được, F: màu hoa văn, B: màu nền, α: độ phủ.

Quy trình: ước lượng trường nền B (đặc / gradient nhẹ / texture nhẹ / ô caro giả)
→ trimap theo khoảng cách màu → ước lượng F từ lõi hoa văn → chiếu pixel lên
đoạn F–B để ra α → khử lem màu nền ở mép.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np


@dataclass
class BgInfo:
    kind: str                      # "alpha" | "uniform" | "checker" | "complex"
    color: tuple = (0, 0, 0)       # màu nền trung vị (RGB)
    noise: float = 0.0             # độ nhiễu/texture của nền (khoảng cách RGB)
    note: str = ""


@dataclass
class KeyResult:
    rgba: np.ndarray               # uint8 HxWx4, màu đã khử lem (straight alpha)
    info: BgInfo
    stats: dict = field(default_factory=dict)


def ring_width(h: int, w: int) -> int:
    return max(4, int(round(min(h, w) * 0.02)))


def ring_pixels(img: np.ndarray, width: int) -> np.ndarray:
    """Các pixel nằm trên dải viền ngoài của ảnh."""
    c = img.shape[2]
    parts = (img[:width], img[-width:], img[width:-width, :width], img[width:-width, -width:])
    return np.concatenate([p.reshape(-1, c) for p in parts])


def fill_from_mask(img: np.ndarray, mask: np.ndarray, sigmas, min_weight: float = 0.05,
                   downscale_to: int | None = None) -> np.ndarray:
    """Nội suy màu cho toàn ảnh từ các pixel mask=True (tích chập chuẩn hoá).

    Mỗi pixel lấy kết quả ở sigma nhỏ nhất có đủ trọng số mẫu xung quanh, nên
    vùng gần mẫu giữ chi tiết, vùng xa mẫu vẫn có giá trị hợp lý.
    """
    h, w = mask.shape
    m = mask.astype(np.float32)
    src = img.astype(np.float32)
    scale = 1.0
    if downscale_to and max(h, w) > downscale_to:
        scale = downscale_to / max(h, w)
        size = (max(1, round(w * scale)), max(1, round(h * scale)))
        src = cv2.resize(src, size, interpolation=cv2.INTER_AREA)
        m = cv2.resize(m, size, interpolation=cv2.INTER_AREA)
    num_src = src * m[..., None]
    out = np.zeros_like(src)
    done = np.zeros(m.shape, bool)
    for s in sigmas:
        wgt = cv2.GaussianBlur(m, (0, 0), s)
        num = cv2.GaussianBlur(num_src, (0, 0), s)
        ok = (wgt > min_weight) & ~done
        out[ok] = num[ok] / wgt[ok, None]
        done |= ok
        if done.all():
            break
    if not done.all():
        tot = float(m.sum())
        mean = num_src.reshape(-1, 3).sum(0) / tot if tot > 0 else src.reshape(-1, 3).mean(0)
        out[~done] = mean
    if scale != 1.0:
        out = cv2.resize(out, (w, h), interpolation=cv2.INTER_CUBIC)
    return out


# ---------------------------------------------------------------- phân tích nền

def _has_real_alpha(rgba: np.ndarray) -> bool:
    if rgba.shape[2] < 4:
        return False
    a = rgba[..., 3]
    return float((a < 250).mean()) > 0.01


def _checker_field(img: np.ndarray, rw: int):
    """Nhận diện nền ô caro vẽ giả. Trả về (B, note) hoặc None."""
    h, w, _ = img.shape
    ring = ring_pixels(img, rw).astype(np.float32)
    crit = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 20, 1.0)
    _, labels, centers = cv2.kmeans(ring, 2, None, crit, 3, cv2.KMEANS_PP_CENTERS)
    if np.linalg.norm(centers[0] - centers[1]) < 20 or not 0.2 < labels.mean() < 0.8:
        return None

    def lab(px):
        return (np.linalg.norm(px - centers[1], axis=-1)
                < np.linalg.norm(px - centers[0], axis=-1)).astype(np.int8)

    row, col = lab(img[2].astype(np.float32)), lab(img[:, 2].astype(np.float32))
    ridx, cidx = np.flatnonzero(np.diff(row)) + 1, np.flatnonzero(np.diff(col)) + 1
    inner = np.concatenate([np.diff(ridx), np.diff(cidx)])
    if len(inner) < 4:
        return None
    s = float(np.median(inner))
    if s < 4 or np.std(inner) / s > 0.25:
        return None
    ox, oy = ridx[0] % s, cidx[0] % s
    yy, xx = np.mgrid[0:h, 0:w]
    par = (np.floor((xx - ox) / s) + np.floor((yy - oy) / s)).astype(np.int64) % 2
    p_ref = par[2, 2]
    l_ref = row[2]
    B = np.where((par == p_ref)[..., None], centers[l_ref], centers[1 - l_ref]).astype(np.float32)
    fit = np.linalg.norm(ring_pixels(img.astype(np.float32), rw) - ring_pixels(B, rw), axis=1)
    if float((fit < 25).mean()) < 0.85:
        return None
    return B, f"ô caro giả, ô {s:.0f}px"


def _uniform_field(img: np.ndarray, seed: np.ndarray, seed_noise: float, iters: int = 3):
    """Trường nền trơn (nền đặc, gradient, texture nhẹ) + độ nhiễu còn lại."""
    d = np.linalg.norm(img - seed, axis=2)
    t = max(18.0, seed_noise * 3.0)
    m = d < t
    noise = seed_noise
    B = np.broadcast_to(seed, img.shape).astype(np.float32)
    for _ in range(iters):
        if m.sum() < 64:
            break
        B = fill_from_mask(img, m, sigmas=[2, 4, 8, 16, 32, 64], downscale_to=256)
        d = np.linalg.norm(img - B, axis=2)
        noise = float(np.percentile(d[m], 95))
        t = max(10.0, noise * 1.3 + 4.0)
        m = d < t
    return B, noise


def _opaque_ring(rgba: np.ndarray, rw: int) -> bool:
    """Viền ngoài ảnh gần như đặc hoàn toàn → nền vẫn còn đó dù ảnh có kênh alpha."""
    return float((ring_pixels(rgba[..., 3:4], rw)[:, 0] >= 250).mean()) >= 0.9


def analyze_background(rgba: np.ndarray) -> tuple[BgInfo, np.ndarray | None]:
    """Phân loại nền và (nếu được) dựng trường nền B cùng kích thước ảnh."""
    h, w = rgba.shape[:2]
    rw = ring_width(h, w)
    fake_alpha = False
    if _has_real_alpha(rgba):
        if not _opaque_ring(rgba, rw):
            return BgInfo("alpha", note="ảnh đã có nền trong suốt thật"), None
        fake_alpha = True       # AI xuất PNG trong suốt nhưng vẫn vẽ nền đặc → lọc lần 2 theo màu viền
    info, B = _analyze_rgb(rgba[..., :3].astype(np.float32), rw)
    if fake_alpha:
        info.note = "có kênh trong suốt nhưng viền ngoài vẫn là nền đặc → tách nền theo màu; " + info.note
    return info, B


def _analyze_rgb(img: np.ndarray, rw: int) -> tuple[BgInfo, np.ndarray | None]:
    ring = ring_pixels(img, rw)
    med = np.median(ring, axis=0)
    ring_noise = float(np.percentile(np.linalg.norm(ring - med, axis=1), 90))
    color = tuple(int(round(c)) for c in med)

    if ring_noise > 18:
        chk = _checker_field(img, rw)
        if chk is not None:
            B, note = chk
            res = np.linalg.norm(ring_pixels(img, rw) - ring_pixels(B, rw), axis=1)
            return BgInfo("checker", color, float(np.percentile(res, 95)), note), B

    B, noise = _uniform_field(img, med.astype(np.float32), ring_noise)
    res = np.linalg.norm(ring_pixels(img, rw) - ring_pixels(B, rw), axis=1)
    ring_res = float(np.percentile(res, 90))
    if ring_res > 45:
        return BgInfo("complex", color, ring_res, "nền phức tạp (có vật thể/texture mạnh)"), B
    note = "nền đặc" if noise < 12 else "nền có gradient/texture nhẹ"
    return BgInfo("uniform", color, noise, note), B


# ---------------------------------------------------------------- tách nền

def key_with_background(img: np.ndarray, B: np.ndarray, noise: float,
                        t_lo: float | None = None, t_hi: float | None = None):
    """Tính α và màu hoa văn đã khử lem khi biết trường nền B.

    Trả về (alpha float32 0..1, color float32 0..255, stats).
    """
    img = img.astype(np.float32)
    v = img - B
    d = np.linalg.norm(v, axis=2)
    t_lo = t_lo if t_lo is not None else max(8.0, noise * 1.15 + 3.0)
    t_hi = t_hi if t_hi is not None else max(2.0 * t_lo, t_lo + 30.0)
    fg = d >= t_hi
    bg = d <= t_lo
    core = cv2.erode(fg.astype(np.uint8), np.ones((3, 3), np.uint8)).astype(bool)
    if core.sum() < 50:
        core = fg

    # Màu hoa văn F: lan từ lõi ra vùng mép.
    F = fill_from_mask(img, core, sigmas=[1, 2, 4, 8, 16, 32], min_weight=0.02)
    u = F - B
    uu = (u * u).sum(2)
    a_proj = np.clip((v * u).sum(2) / np.maximum(uu, 1e-6), 0.0, 1.0)
    resid = np.linalg.norm(v - a_proj[..., None] * u, axis=2)
    collinear = resid / np.maximum(d, 1e-6) < 0.3
    reliable = (np.sqrt(uu) >= max(t_hi, 40.0)) & collinear
    a_ramp = np.clip((d - t_lo) / (t_hi - t_lo), 0.0, 1.0)

    alpha = np.where(reliable, a_proj, a_ramp)
    alpha = np.where(reliable & fg & (a_proj > 0.9), 1.0, alpha)
    alpha[core] = 1.0
    alpha[bg] = 0.0
    alpha[alpha < 0.03] = 0.0

    unmix = np.clip(B + v / np.maximum(alpha, 0.15)[..., None], 0, 255)
    # Khử nền chia cho α nên mọi sai lệch của nền ước lượng (vân nền, gradient) bị khuếch đại
    # và lộ ra thành viền ám màu (hồng tím trên nền xanh). Ở DẢI MÉP SÁT LÕI (mép khử răng cưa
    # của nét), mép chỉ lấy ĐỘ SÁNG từ phép khử nền, còn SẮC MÀU lấy từ lõi liền kề.
    # Vùng bán trong suốt nằm XA lõi (vd. thân lá mờ) là chất liệu riêng → giữ màu của chính nó.
    lw = np.array([0.299, 0.587, 0.114], np.float32)
    ratio = np.clip((unmix @ lw) / np.maximum(F @ lw, 1.0), 0.25, 1.6)
    shaded = np.clip(F * ratio[..., None], 0, 255)
    dist = cv2.distanceTransform((~core).astype(np.uint8), cv2.DIST_L2, 3)
    near = np.clip((4.0 - dist) / 2.0, 0, 1)[..., None]          # 1 khi cách lõi ≤2px, 0 khi ≥4px
    own = np.clip(B + v / np.maximum(alpha, 0.3)[..., None], 0, 255)   # màu riêng, khuếch đại có giới hạn
    main = near * shaded + (1 - near) * unmix
    faint = near * F + (1 - near) * own
    wgt = np.clip((alpha - 0.1) / 0.3, 0, 1)[..., None]
    color = wgt * main + (1 - wgt) * faint
    color = np.where((alpha >= 0.999)[..., None], img, color)
    stats = dict(t_lo=round(t_lo, 1), t_hi=round(t_hi, 1),
                 coverage=round(float((alpha > 0.5).mean()), 4))
    return alpha.astype(np.float32), color.astype(np.float32), stats


def remove_specks(alpha: np.ndarray, min_area: int, faint_max: float = 0.5) -> np.ndarray:
    """Xoá rác: cụm tách rời quá nhỏ, và cụm MỜ tách rời (không có lõi đặc).

    Hoa văn thật luôn có lõi đậm; cụm chỉ gồm pixel mờ (α < faint_max) mà nằm tách
    riêng là vân nền / nhiễu JPEG bị nhận nhầm – kể cả khi nó to hơn min_area.
    Quầng mờ dính liền hoa văn (mép, bóng) thuộc cùng cụm nên không bị ảnh hưởng.
    """
    if min_area <= 0:
        return alpha
    n, labels, st, _ = cv2.connectedComponentsWithStats((alpha > 0.0).astype(np.uint8), connectivity=8)
    if n <= 1:
        return alpha
    amax = np.zeros(n, np.float32)
    np.maximum.at(amax, labels.ravel(), alpha.ravel())
    area = st[:, cv2.CC_STAT_AREA]
    side = np.maximum(st[:, cv2.CC_STAT_WIDTH], st[:, cv2.CC_STAT_HEIGHT])
    faint_limit = max(400, int(alpha.size * 1e-3))
    compact_px = max(6, round(min(alpha.shape) * 0.006))
    # đốm vân nền: cụm tròn gọn vài px, không có lõi đặc (chấm hoa văn thật luôn có lõi α≈1)
    kill = (area < min_area) | ((amax < faint_max) & (area < faint_limit)) | ((amax < 0.75) & (side <= compact_px))
    kill[0] = False
    if not kill.any():
        return alpha
    out = alpha.copy()
    out[kill[labels]] = 0.0
    return out


def to_rgba8(alpha: np.ndarray, color: np.ndarray) -> np.ndarray:
    a = np.clip(alpha * 255.0 + 0.5, 0, 255).astype(np.uint8)
    c = np.clip(color + 0.5, 0, 255).astype(np.uint8)
    c[a == 0] = 0
    return np.dstack([c, a])


def default_speck(h: int, w: int) -> int:
    return max(6, int(h * w * 4e-6))


def cleaning_options(kit_data: dict) -> dict:
    """Tuỳ chọn dọn bóng tối từ kit.json → tham số cho clean_asset/remove_background.

    "drop_baked_shadow": true (mặc định: bỏ pixel tối chưa đặc) | false (giữ nguyên)
                         | {"max_lum": 40, "max_alpha": 1.0, "edge_lum": 65}
                           max_alpha 1.0: bỏ cả pixel tối ĐẶC – khi hoa văn của kit không có màu đen;
                           edge_lum: bỏ quầng xám tối bán trong suốt quanh nét.
    """
    opt = kit_data.get("drop_baked_shadow", True)
    if opt is False:
        return {"drop_dark": None, "dark_alpha": 0.95, "edge_dark": None}
    if opt is True:
        return {"drop_dark": 45.0, "dark_alpha": 0.95, "edge_dark": None}
    edge = opt.get("edge_lum")
    return {"drop_dark": float(opt.get("max_lum", 45)), "dark_alpha": float(opt.get("max_alpha", 0.95)) + 1e-6,
            "edge_dark": float(edge) if edge is not None else None}


def clean_asset(rgba: np.ndarray, min_speck: int, drop_dark: float | None = 45.0,
                dark_alpha: float = 0.95, edge_dark: float | None = None) -> np.ndarray:
    """Dọn rác một asset RGBA (uint8), dùng chung cho mọi nguồn ảnh.

    1. drop_dark: bỏ pixel TỐI mà chưa đặc (độ sáng < drop_dark, α < dark_alpha) – đó là bóng đổ
       AI vẽ sẵn / vân nền tối bám quanh hoa văn. Công cụ tự thêm bóng đổ đồng nhất khi ghép.
       Nét khắc tối nằm trong thân hoa văn đặc (α≈1) không bị ảnh hưởng. None = giữ nguyên.
       edge_dark: ngưỡng riêng cho pixel BÁN TRONG SUỐT – bỏ quầng xám tối lấm tấm quanh nét
       (bóng/vân nền), vẫn giữ mép sáng của nét vàng.
    2. remove_specks: bỏ hạt rời nhỏ / mờ (làm SAU bước 1 vì bỏ bóng có thể để lại hạt lẻ).
    """
    out = rgba.copy()
    alpha = out[..., 3].astype(np.float32) / 255
    if drop_dark is not None:
        lum = out[..., :3].astype(np.float32) @ np.array([0.299, 0.587, 0.114], np.float32)
        alpha[(lum < drop_dark) & (alpha < dark_alpha)] = 0.0
        if edge_dark is not None:
            alpha[(lum < edge_dark) & (alpha < 0.95)] = 0.0
    alpha = remove_specks(alpha, min_speck)
    out[..., 3] = np.where(alpha > 0, out[..., 3], 0)
    out[out[..., 3] == 0, :3] = 0
    return out


def remove_background(rgba: np.ndarray, *, min_speck: int | None = None,
                      drop_dark: float | None = 45.0, dark_alpha: float = 0.95,
                      edge_dark: float | None = None) -> KeyResult:
    """Tách nền một asset. `rgba`: uint8 HxWx3 hoặc HxWx4 (RGB)."""
    if rgba.shape[2] == 3:
        rgba = np.dstack([rgba, np.full(rgba.shape[:2], 255, np.uint8)])
    info, B = analyze_background(rgba)
    h, w = rgba.shape[:2]
    speck = min_speck if min_speck is not None else default_speck(h, w)
    stats: dict = {}
    if info.kind == "alpha":
        out = rgba   # đã trong suốt (AI xuất thẳng / cắt từ thiệp cũ) – vẫn dọn rác bên dưới
    elif info.kind == "complex":
        out = _try_rembg(rgba)
        if out is None:
            raise KeyingError(
                "Nền quá phức tạp để tách tự động. Hãy tạo lại asset trên nền MÀU ĐẶC "
                "(xem PROMPTS.md) hoặc cài rembg: pip install rembg[cpu]")
        info.note += "; đã dùng rembg (AI) làm phương án dự phòng"
    elif is_chroma_key(info.color):
        alpha, color, stats = key_chroma(rgba[..., :3].astype(np.float32), B, info.noise)
        info.note += f"; phông màu {info.color} → tách theo hiệu màu"
        out = to_rgba8(alpha, color)
    else:
        alpha, color, stats = key_with_background(rgba[..., :3].astype(np.float32), B, info.noise)
        out = to_rgba8(alpha, color)
    if info.kind != "alpha":            # chỗ vốn đã trong suốt trong ảnh gốc giữ nguyên trong suốt
        out[..., 3] = np.minimum(out[..., 3], rgba[..., 3])
    out = clean_asset(out, speck, drop_dark, dark_alpha, edge_dark)
    stats["coverage"] = round(float((out[..., 3] > 127).mean()), 4)
    if info.kind == "uniform" and is_chroma_key(info.color):
        stats["key_residue"] = round(key_residue(out, info.color), 4)
    return KeyResult(out, info, stats)


class KeyingError(RuntimeError):
    pass


def _try_rembg(rgba: np.ndarray):
    try:
        from rembg import remove  # type: ignore
    except Exception:
        return None
    from PIL import Image
    out = remove(Image.fromarray(rgba[..., :3]))
    return np.asarray(out.convert("RGBA"))


# ---------------------------------------------------------------- phông màu bão hoà (color-difference keying)

def _key_channels(key) -> np.ndarray:
    k = np.asarray(key, np.float32)
    return k >= 0.5 * k.max()          # kênh "trội" của màu phông (xanh dương: B; hồng tím: R,B; cyan: G,B)


def screen_map(x: np.ndarray, dom: np.ndarray) -> np.ndarray:
    """Lượng màu phông lấn trội: min(kênh trội) − max(kênh còn lại). Hoa văn thật có giá trị ≤ 0."""
    return x[..., dom].min(-1) - x[..., ~dom].max(-1)


def is_chroma_key(color) -> bool:
    c = np.asarray(color, np.float32)
    dom = _key_channels(c)
    return bool(dom.any() and not dom.all() and float(screen_map(c[None], dom)[0]) >= 100)


def despill(color: np.ndarray, dom: np.ndarray) -> np.ndarray:
    """Khử màu phông còn bám: hạ các kênh trội xuống bằng kênh còn lại lớn nhất."""
    excess = np.maximum(screen_map(color, dom), 0)[..., None]
    out = color.copy()
    out[..., dom] -= excess
    return out


def key_chroma(img: np.ndarray, B: np.ndarray, noise: float = 3.0):
    """Tách phông màu bão hoà bằng hiệu màu (chuẩn keying trong dựng phim).

    α = 1 − screen(pixel) / screen(phông). Pixel bán trong suốt (thân lá mờ, mép nét) cho α
    trung gian đúng – cách đo khoảng cách màu sẽ coi chúng là hoa văn đặc và giữ nguyên màu phông.
    """
    img = img.astype(np.float32)
    dom = _key_channels(B.reshape(-1, 3).mean(0))
    sB = np.maximum(screen_map(B, dom), 30.0)
    alpha = np.clip(1.0 - screen_map(img, dom) / sB, 0.0, 1.0)
    t = min(0.15, 3.0 * noise / float(np.median(sB)))
    alpha[alpha < t] = 0.0
    alpha[alpha > 1.0 - t] = 1.0
    unmix = B + (img - B) / np.maximum(alpha, 0.08)[..., None]
    color = np.clip(despill(np.where((alpha >= 1.0)[..., None], img, unmix), dom), 0, 255)
    return alpha.astype(np.float32), color.astype(np.float32), {"method": "chroma", "t": round(t, 3)}


def key_residue(rgba: np.ndarray, key) -> float:
    """Tỉ lệ pixel hoa văn (α>0.5) còn ám rõ màu phông – > vài % là ảnh có vấn đề."""
    dom = _key_channels(key)
    sk = float(screen_map(np.asarray(key, np.float32)[None], dom)[0])
    a = rgba[..., 3] > 127
    if not a.any() or sk <= 0:
        return 0.0
    s = screen_map(rgba[..., :3].astype(np.float32), dom)
    return float((s[a] > 0.25 * sk).mean())
