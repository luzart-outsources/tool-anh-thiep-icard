import cv2
import numpy as np
import pytest

from cardkit.keying import analyze_background, remove_background


def _synthetic(bg, noise=2.0, seed=0, h=320, w=320):
    """Hoa văn giả (vòng tròn vàng + nét mảnh kem + chi tiết nâu) có α chuẩn, ghép lên nền."""
    rng = np.random.default_rng(seed)
    ss = 4  # vẽ ở độ phân giải x4 rồi thu nhỏ để có mép khử răng cưa thật
    big = np.zeros((h * ss, w * ss), np.uint8)
    col = np.zeros((h * ss, w * ss, 3), np.uint8)
    cv2.circle(big, (w * ss // 2, h * ss // 2), 90 * ss, 255, 14 * ss)
    cv2.circle(col, (w * ss // 2, h * ss // 2), 90 * ss, (201, 162, 75), 14 * ss)
    cv2.line(big, (40 * ss, 60 * ss), (280 * ss, 90 * ss), 255, 2 * ss)
    cv2.line(col, (40 * ss, 60 * ss), (280 * ss, 90 * ss), (240, 230, 200), 2 * ss)
    cv2.circle(col, (w * ss // 2, h * ss // 2 - 90 * ss), 3 * ss, (90, 62, 30), -1)
    alpha = cv2.resize(big, (w, h), interpolation=cv2.INTER_AREA).astype(np.float32) / 255
    F = cv2.resize(col, (w, h), interpolation=cv2.INTER_AREA).astype(np.float32)
    F = F / np.maximum(alpha[..., None], 1e-3)  # màu thẳng (straight)
    F = np.clip(F, 0, 255)
    B = np.broadcast_to(np.array(bg, np.float32), (h, w, 3))
    I = alpha[..., None] * F + (1 - alpha[..., None]) * B + rng.normal(0, noise, (h, w, 3))
    return np.clip(I, 0, 255).astype(np.uint8), alpha, F


@pytest.mark.parametrize("bg", [(255, 0, 255), (15, 55, 38), (40, 60, 200)])
def test_recovers_alpha_on_flat_background(bg):
    img, alpha_true, _ = _synthetic(bg)
    res = remove_background(img)
    assert res.info.kind == "uniform"
    a = res.rgba[..., 3].astype(np.float32) / 255
    err = np.abs(a - alpha_true)
    assert err.mean() < 0.02
    edge = (alpha_true > 0.05) & (alpha_true < 0.95)
    assert err[edge].mean() < 0.2


def test_decontaminates_edge_color_on_magenta():
    img, alpha_true, F = _synthetic((255, 0, 255))
    res = remove_background(img)
    a = res.rgba[..., 3].astype(np.float32) / 255
    rgb = res.rgba[..., :3].astype(np.float32)
    edge = (alpha_true > 0.3) & (alpha_true < 0.9) & (a > 0.2)
    # màu mép không được ám hồng: kênh G không bị kéo tụt về 0 như nền magenta
    assert np.median(np.abs(rgb[edge] - F[edge]).max(axis=1)) < 45


def _textured(seed=3, h=320, w=320):
    """Nền xanh có vân chìm (như giấy damask) + đốm sáng li ti, ghép hoa văn lên."""
    rng = np.random.default_rng(seed)
    base = np.array((15, 55, 38), np.float32)
    tex = cv2.GaussianBlur(rng.normal(0, 1, (h, w)).astype(np.float32), (0, 0), 6)
    tex = tex / np.abs(tex).max() * 22
    flecks = (rng.random((h, w)) > 0.996).astype(np.float32)
    flecks = cv2.GaussianBlur(flecks, (0, 0), 1.2) * 400
    B = base + tex[..., None] + np.clip(flecks, 0, 45)[..., None] * np.array([1.0, 0.9, 0.5], np.float32)
    img, alpha, F = _synthetic((15, 55, 38), noise=0, seed=seed, h=h, w=w)
    a3 = alpha[..., None]
    I = a3 * F + (1 - a3) * B + rng.normal(0, 2, (h, w, 3))
    return np.clip(I, 0, 255).astype(np.uint8), alpha, F


def _isolated_faint(alpha):
    n, lab, st, _ = cv2.connectedComponentsWithStats((alpha > 0.02).astype(np.uint8), 8)
    amax = np.zeros(n)
    np.maximum.at(amax, lab.ravel(), alpha.ravel())
    return [i for i in range(1, n) if amax[i] < 0.6 and st[i, 4] < 400]


def test_textured_background_leaves_no_faint_specks():
    img, alpha_true, _ = _textured()
    res = remove_background(img)
    a = res.rgba[..., 3].astype(np.float32) / 255
    assert _isolated_faint(a) == []                       # không còn hạt mờ tách rời
    assert np.abs(a - alpha_true)[alpha_true > 0.95].mean() < 0.05   # vẫn giữ nguyên hoa văn


def test_textured_background_edges_keep_gold_hue():
    img, alpha_true, F = _textured()
    res = remove_background(img)
    a = res.rgba[..., 3].astype(np.float32) / 255
    rgb = res.rgba[..., :3].astype(np.float32)
    edge = (a > 0.1) & (a < 0.9) & (alpha_true > 0.05)
    gold_edge = edge & (F[..., 1] > F[..., 2] + 40)        # mép của nét vàng (G > B rõ)
    # mép nét vàng không được ngả hồng tím (B vượt G) do khử nền quá tay
    assert (rgb[gold_edge][:, 2] > rgb[gold_edge][:, 1]).mean() < 0.02


def test_edges_keep_core_hue_when_background_estimate_is_off():
    """Nền ước lượng lệch (vân nền thật khác nền trơn ước lượng) không được làm mép ám hồng tím."""
    from cardkit.keying import key_with_background
    img, alpha_true, F = _synthetic((15, 55, 38), noise=1.0)
    B_est = np.broadcast_to(np.array((15, 55 + 25, 38 - 10), np.float32), img.shape)  # lệch kênh G, B
    alpha, color, _ = key_with_background(img.astype(np.float32), B_est, 3.0)
    edge = (alpha > 0.2) & (alpha < 0.8) & (alpha_true > 0.05)
    assert edge.sum() > 100

    def chroma(c):
        return c / np.maximum(c.sum(-1, keepdims=True), 1)
    dev = np.abs(chroma(color[edge]) - chroma(F[edge])).sum(1)
    assert np.percentile(dev, 95) < 0.06          # sắc màu mép bám theo sắc màu hoa văn


def test_clean_asset_drops_baked_dark_shadow_only():
    from cardkit.keying import clean_asset
    rgba = np.zeros((120, 120, 4), np.uint8)
    rgba[30:90, 30:90] = (200, 160, 70, 255)                 # hoa văn vàng đặc
    rgba[90:100, 30:90] = (25, 20, 12, 150)                  # bóng tối nửa trong suốt AI vẽ sẵn, dính liền
    rgba[29, 30:90] = (190, 150, 70, 110)                    # mép khử răng cưa sáng (phải giữ)
    out = clean_asset(rgba, min_speck=6, drop_dark=45)
    assert (out[90:100, 30:90, 3] == 0).all()                # bóng tối bị bỏ
    assert (out[30:90, 30:90, 3] == 255).all()               # hoa văn nguyên vẹn
    assert (out[29, 30:90, 3] == 110).all()                  # mép sáng giữ nguyên
    kept = clean_asset(rgba, min_speck=6, drop_dark=None)
    assert (kept[90:100, 30:90, 3] == 150).all()             # tắt tuỳ chọn thì giữ


def test_real_alpha_asset_gets_specks_cleaned():
    rgba = np.zeros((200, 200, 4), np.uint8)
    rgba[50:150, 50:150] = (200, 160, 70, 255)
    rng = np.random.default_rng(0)
    for _ in range(40):                                  # hạt mờ lạc (vân nền / pixel lạc của AI)
        y, x = rng.integers(0, 45, 2)
        rgba[y:y + 2, x:x + 2] = (180, 150, 90, int(rng.integers(20, 120)))
    res = remove_background(rgba)
    a = res.rgba[..., 3].astype(np.float32) / 255
    assert _isolated_faint(a) == []
    assert (res.rgba[50:150, 50:150, 3] == 255).all()   # hoa văn giữ nguyên


def test_keeps_real_alpha():
    rgba = np.zeros((64, 64, 4), np.uint8)
    rgba[16:48, 16:48] = (200, 160, 70, 255)
    res = remove_background(rgba)
    assert res.info.kind == "alpha"
    assert np.array_equal(res.rgba, rgba)


def test_alpha_png_with_opaque_backdrop_is_still_keyed():
    """GPT trả PNG có kênh alpha nhưng nền vẫn là mảng màu đặc → vẫn tách nền (lọc lần 2)."""
    img, alpha_true, _ = _synthetic((0, 0, 255))
    rgba = np.dstack([img, np.full(img.shape[:2], 255, np.uint8)])
    rgba[140:170, 20:60, 3] = 0                          # lỗ trong suốt thật >1% ảnh → trước đây bị coi là "đã trong suốt"
    res = remove_background(rgba)
    assert res.info.kind == "uniform" and "viền" in res.info.note
    a = res.rgba[..., 3].astype(np.float32) / 255
    assert a[5:40, 5:40].max() == 0                      # nền xanh đã trong suốt
    assert np.abs(a - alpha_true)[alpha_true > 0.95].mean() < 0.05
    assert res.rgba[140:170, 20:60, 3].max() == 0        # chỗ vốn trong suốt vẫn trong suốt


def test_detects_fake_checkerboard():
    h = w = 256
    yy, xx = np.mgrid[0:h, 0:w]
    chk = ((xx // 16 + yy // 16) % 2).astype(bool)
    img = np.where(chk[..., None], np.uint8(255), np.uint8(204)).repeat(3, axis=2).astype(np.uint8)
    cv2.circle(img, (128, 128), 50, (180, 140, 60), -1)
    info, B = analyze_background(img)
    assert info.kind == "checker"
    res = remove_background(img)
    a = res.rgba[..., 3]
    assert a[128, 128] == 255 and a[5, 5] == 0 and a[5, 20] == 0


def test_cleaning_options_from_kit():
    from cardkit.keying import cleaning_options
    assert cleaning_options({}) == {"drop_dark": 45.0, "dark_alpha": 0.95, "edge_dark": None}
    assert cleaning_options({"drop_baked_shadow": False})["drop_dark"] is None
    o = cleaning_options({"drop_baked_shadow": {"max_lum": 40, "max_alpha": 1.0}})
    assert o["drop_dark"] == 40.0 and o["dark_alpha"] > 1.0      # bỏ cả pixel tối đặc (α = 1)


def test_edge_lum_drops_grey_halo_but_keeps_gold_edges():
    from cardkit.keying import clean_asset
    rgba = np.zeros((100, 100, 4), np.uint8)
    rgba[30:70, 30:70] = (200, 160, 70, 255)
    rgba[70:73, 30:70] = (60, 55, 50, 120)        # quầng xám tối bán trong suốt (lum ≈ 56)
    rgba[27:30, 30:70] = (170, 135, 60, 120)      # mép vàng bán trong suốt thật (lum ≈ 142)
    out = clean_asset(rgba, 6, drop_dark=40, dark_alpha=1.01, edge_dark=65)
    assert (out[70:73, 30:70, 3] == 0).all()
    assert (out[27:30, 30:70, 3] == 120).all() and (out[30:70, 30:70, 3] == 255).all()


def test_semi_transparent_region_far_from_core_keeps_its_own_hue():
    """Thân lá xanh bán trong suốt (không có lõi đặc) nằm cạnh viền vàng: không được bị tô sắc vàng."""
    from cardkit.keying import key_with_background
    h = w = 200
    B = np.broadcast_to(np.array((15, 55, 38), np.float32), (h, w, 3)).copy()
    alpha = np.zeros((h, w), np.float32)
    F = np.zeros((h, w, 3), np.float32)
    alpha[40:160, 40:60] = 1.0; F[40:160, 40:60] = (205, 165, 80)        # viền vàng đặc
    alpha[40:160, 60:140] = 0.5; F[40:160, 60:140] = (60, 95, 62)        # thân lá xanh xám gần màu nền, bán trong suốt
    img = alpha[..., None] * F + (1 - alpha[..., None]) * B
    a, col, _ = key_with_background(img, B, 3.0)
    leaf = (slice(50, 150), slice(70, 135))                               # xa viền vàng > 4px
    c = np.median(col[leaf].reshape(-1, 3), axis=0)
    assert c[1] > c[0] + 10, f"thân lá mất sắc xanh: {c}"


def _on_key(key=(0, 0, 255), leaf_alpha=0.4, noise=2.0):
    """Viền vàng đặc + thân lá xanh xám BÁN TRONG SUỐT trên phông màu bão hoà (như ảnh ChatGPT nền đặc)."""
    rng = np.random.default_rng(1)
    h = w = 220
    B = np.broadcast_to(np.array(key, np.float32), (h, w, 3))
    alpha = np.zeros((h, w), np.float32)
    F = np.zeros((h, w, 3), np.float32)
    alpha[30:190, 30:50] = 1.0; F[30:190, 30:50] = (205, 165, 80)
    alpha[30:190, 50:170] = leaf_alpha; F[30:190, 50:170] = (110, 140, 90)
    img = alpha[..., None] * F + (1 - alpha[..., None]) * B + rng.normal(0, noise, (h, w, 3))
    return np.clip(img, 0, 255).astype(np.uint8), alpha, F


@pytest.mark.parametrize("key", [(0, 0, 255), (0, 255, 255), (255, 0, 255)])   # màu phông tool có thể chọn khi hoa văn có lá xanh
def test_saturated_key_semi_transparent_leaf(key):
    img, alpha_true, F = _on_key(key)
    res = remove_background(img, drop_dark=None)
    a = res.rgba[..., 3].astype(np.float32) / 255
    rgb = res.rgba[..., :3].astype(np.float32)
    leaf = (slice(40, 180), slice(70, 160))
    assert abs(np.median(a[leaf]) - 0.4) < 0.12                       # độ phủ thân lá đúng
    c = np.median(rgb[leaf].reshape(-1, 3), axis=0)
    assert np.abs(c - np.array((110, 140, 90))).max() < 30, c        # màu lá thật, không ám màu phông
    assert np.median(a[30:190, 32:48]) > 0.97                         # viền vàng vẫn đặc


def test_flags_key_color_residue():
    """Ảnh còn sót màu phông (vd. ánh xanh dương phản chiếu trên kim loại) phải bị cảnh báo, không báo 'Xong'."""
    from cardkit.keying import key_residue
    rgba = np.zeros((100, 100, 4), np.uint8)
    rgba[20:80, 20:80] = (200, 160, 70, 255)
    assert key_residue(rgba, (0, 0, 255)) < 0.01
    rgba[20:50, 20:80] = (60, 70, 220, 255)                           # mảng đặc ám xanh dương
    assert key_residue(rgba, (0, 0, 255)) > 0.3
