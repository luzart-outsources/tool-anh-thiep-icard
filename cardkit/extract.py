"""Rút asset từ một thiệp phẳng có sẵn (tận dụng thiệp cũ đã ưng).

Bước 1 – không có spec: tách nền cả thiệp, đánh số các cụm hoa văn/chữ, sinh spec mẫu.
Bước 2 – có spec: cắt từng asset (chỉ lấy mảnh nằm trọn trong hộp, xoá vùng chữ),
dựng lại nền sạch, và (tuỳ chọn) sinh bản nháp layout tái tạo bố cục thiệp gốc.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw

from .config import ConfigError, load_json
from .keying import _uniform_field, clean_asset, cleaning_options, default_speck, key_with_background, remove_specks, to_rgba8


@dataclass
class CardKey:
    rgba: np.ndarray         # hoa văn + chữ đã tách nền (uint8)
    alpha: np.ndarray        # float 0..1
    bg_field: np.ndarray     # trường nền trơn ước lượng (float RGB)
    source: np.ndarray       # ảnh gốc (float RGB)
    fragments: np.ndarray    # nhãn mảnh liên thông (int32)
    frag_boxes: dict         # nhãn -> (x0, y0, x1, y1)
    border_mask: np.ndarray  # pixel thuộc đường viền chạy dọc/ngang gần hết thiệp


def key_card(path: Path, group_px: int = 5) -> CardKey:
    img = np.asarray(Image.open(path).convert("RGB")).astype(np.float32)
    seed = np.median(img.reshape(-1, 3), axis=0).astype(np.float32)
    B, noise = _uniform_field(img, seed, 10.0)
    alpha, color, _ = key_with_background(img, B, noise)
    alpha = remove_specks(alpha, 8)
    rgba = to_rgba8(alpha, color)

    h, w = alpha.shape
    lines = (alpha > 0.15).astype(np.uint8)
    v = cv2.morphologyEx(lines, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (1, 15)))
    v = cv2.morphologyEx(v, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, int(h * 0.45))))
    hz = cv2.morphologyEx(lines, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (15, 1)))
    hz = cv2.morphologyEx(hz, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (int(w * 0.45), 1)))
    core = v | hz
    # Nở vùng viền vào các pixel mép mờ của đường kẻ (khử răng cưa/JPEG), không ăn vào hoa văn đậm.
    border = cv2.dilate(core, np.ones((3, 3), np.uint8)).astype(bool) | \
        (cv2.dilate(core, np.ones((7, 7), np.uint8)).astype(bool) & (alpha < 0.4))
    # Sợi mảnh còn sót dọc mép thiệp (phần rìa đường kẻ) → cũng tính là viền, để không nối các hoa văn với nhau.
    rest = ((alpha > 0.05) & ~border).astype(np.uint8)
    n, lab, st, _ = cv2.connectedComponentsWithStats(rest, connectivity=8)
    edge = int(min(h, w) * 0.09)
    for i in range(1, n):
        x, y, bw, bh = st[i, :4]
        thin, long_ = min(bw, bh) <= 6, max(bw, bh) >= 25
        near = x < edge or y < edge or x + bw > w - edge or y + bh > h - edge
        if thin and long_ and near:
            border |= lab == i

    rest = ((alpha > 0.05) & ~border).astype(np.uint8)
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (group_px, group_px))
    n, labels, st, _ = cv2.connectedComponentsWithStats(cv2.dilate(rest, k), connectivity=8)
    boxes = {i: (int(st[i, 0]), int(st[i, 1]), int(st[i, 0] + st[i, 2]), int(st[i, 1] + st[i, 3]))
             for i in range(1, n)}
    return CardKey(rgba, alpha, B, img, labels, boxes, border)


def detect_border_lines(ck: CardKey, band: int = 90, thr: float = 0.35) -> list[dict]:
    """Các đường viền song song mép thiệp: [{inset, width}] theo px ảnh gốc, ngoài → trong."""
    a = ck.alpha * ck.border_mask
    h, w = a.shape
    y0, y1, x0, x1 = int(h * .3), int(h * .7), int(w * .3), int(w * .7)
    profiles = [a[y0:y1, :band].mean(0), a[y0:y1, w - band:][:, ::-1].mean(0),
                a[:band, x0:x1].mean(1), a[h - band:, x0:x1][::-1].mean(1)]
    sides = []
    for p in profiles:
        idx = np.flatnonzero(p > thr)
        groups = np.split(idx, np.flatnonzero(np.diff(idx) > 1) + 1) if len(idx) else []
        sides.append([(int(g[0]), int(g[-1] - g[0] + 1)) for g in groups if len(g)])
    n = min(len(s) for s in sides) if sides else 0
    if n == 0:
        return []
    good = [s for s in sides if len(s) == n]
    return [{"inset": round(float(np.mean([s[i][0] for s in good])), 1),
             "width": round(float(np.mean([s[i][1] for s in good])), 1)} for i in range(n)]


def write_candidates(ck: CardKey, source: Path, out_dir: Path, min_area: int = 400) -> tuple[Path, Path]:
    """Ảnh đánh số các cụm + spec mẫu để người dùng đặt tên và chọn."""
    out_dir.mkdir(parents=True, exist_ok=True)
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (15, 15))
    solid = ((ck.alpha > 0.05) & ~ck.border_mask).astype(np.uint8)
    n, _, st, _ = cv2.connectedComponentsWithStats(cv2.dilate(solid, k), connectivity=8)
    comps = sorted([tuple(int(v) for v in st[i, :4]) for i in range(1, n) if st[i, 4] >= min_area],
                   key=lambda b: (b[1] // 40, b[0]))
    vis = Image.open(source).convert("RGB")
    d = ImageDraw.Draw(vis)
    items = []
    for i, (x, y, w, h) in enumerate(comps):
        d.rectangle([x, y, x + w, y + h], outline=(255, 40, 40), width=2)
        d.text((x + 4, y + 3), str(i), fill=(255, 255, 0))
        items.append({"name": f"cum_{i:02d}", "box": [x, y, w, h], "keep": False})
    sheet = out_dir / f"{source.stem}_candidates.png"
    vis.save(sheet)
    spec = {
        "source": str(source).replace("\\", "/"),
        "_huong_dan": "Đổi 'name', đặt keep=true cho cụm muốn giữ; chỉnh 'box' [x,y,rộng,cao] nếu cần. "
                      "'erase': [[x,y,w,h]] xoá chữ trong hộp; 'mode': 'box' lấy mọi pixel trong hộp; "
                      "'mirror': 'x'|'y'|'xy' khi sinh layout nháp.",
        "canvas": {"w": 1748, "h": 2480},
        "assets": items,
        "texts": [],
        "border": {"fill": "gold_line"},
        "_background": {"name": "nen", "patch": 160, "seed": 7,
                        "_huong_dan": "đổi khoá thành \"background\" để dựng lại nền sạch từ thiệp này"},
    }
    spec_path = out_dir / f"{source.stem}_spec.json"
    spec_path.write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")
    return sheet, spec_path


def select_mask(ck: CardKey, box, erase=(), mode: str = "fragments", margin: int = 6) -> np.ndarray:
    x, y, w, h = box
    H, W = ck.alpha.shape
    if mode == "box":
        mask = np.zeros((H, W), bool)
        mask[max(0, y):y + h, max(0, x):x + w] = True
    else:
        X0, Y0, X1, Y1 = x - margin, y - margin, x + w + margin, y + h + margin
        keep = np.zeros(len(ck.frag_boxes) + 1, bool)
        for lab, (a0, b0, a1, b1) in ck.frag_boxes.items():
            if a0 >= X0 and b0 >= Y0 and a1 <= X1 and b1 <= Y1:
                keep[lab] = True
        mask = keep[ck.fragments]
    mask &= ~ck.border_mask
    for ex, ey, ew, eh in erase:
        mask[max(0, ey):ey + eh, max(0, ex):ex + ew] = False
    return mask


def crop_asset(ck: CardKey, box, erase=(), mode: str = "fragments", clean: dict | None = None
               ) -> tuple[Image.Image, list[int]]:
    """Asset đã cắt sát + khung bao nội dung [x, y, w, h] theo toạ độ ảnh gốc."""
    mask = select_mask(ck, box, erase, mode)
    full = ck.rgba.copy()
    full[..., 3] = np.where(mask, full[..., 3], 0)
    # Dọn rác NGAY khi cắt (cùng quy tắc với ingest) để khung bao đo ở đây khớp với asset cuối cùng –
    # bố cục nháp dựa vào khung bao này, lệch nhau là hoa văn bị kéo to/nhỏ khi ghép.
    x, y, w, h = box
    m = 12
    sy0, sx0 = max(0, y - m), max(0, x - m)
    sub = clean_asset(full[sy0:y + h + m, sx0:x + w + m], default_speck(*ck.alpha.shape), **(clean or {}))
    a = np.zeros(ck.alpha.shape, np.uint8)
    a[sy0:sy0 + sub.shape[0], sx0:sx0 + sub.shape[1]] = sub[..., 3]
    ys, xs = np.nonzero(a)
    if len(xs) == 0:
        raise ConfigError(f"Hộp {box} không chứa hoa văn nào (kiểm tra lại toạ độ).")
    x0, y0, x1, y1 = xs.min(), ys.min(), xs.max() + 1, ys.max() + 1
    rgba = ck.rgba[y0:y1, x0:x1].copy()
    rgba[..., 3] = a[y0:y1, x0:x1]
    rgba[rgba[..., 3] == 0, :3] = 0
    pad = 4  # chừa lề trong suốt, giống ảnh AI có lề – ingest sẽ cắt sát lại
    rgba = np.pad(rgba, ((pad, pad), (pad, pad), (0, 0)))
    return Image.fromarray(rgba, "RGBA"), [int(x0), int(y0), int(x1 - x0), int(y1 - y0)]


def synthesize_background(ck: CardKey, patch: int = 160, seed: int = 7, lighting_sigma: float = 45.0
                          ) -> Image.Image:
    """Dựng lại nền sạch: ghép ngẫu nhiên các mảnh texture lấy từ vùng nền trống,
    rồi chuyển ánh sáng tổng thể (vignette) của thiệp gốc sang."""
    rng = np.random.default_rng(seed)
    img = ck.source
    H, W, _ = img.shape
    clean = (ck.alpha < 0.02) & ~cv2.dilate(ck.border_mask.astype(np.uint8), np.ones((9, 9), np.uint8)).astype(bool)
    clean = cv2.erode(clean.astype(np.uint8), np.ones((7, 7), np.uint8))
    dist = cv2.distanceTransform(clean, cv2.DIST_C, 3)
    half = patch // 2
    while True:
        ys, xs = np.nonzero(dist >= half)
        if len(ys) >= 20 or half <= 24:
            break
        half = int(half * 0.8)
    if len(ys) == 0:
        raise ConfigError("Không tìm được vùng nền trống để lấy mẫu texture.")
    patch = half * 2
    step = int(patch * 0.75)
    ramp = np.minimum(1.0, np.minimum(np.arange(patch) + 1, np.arange(patch)[::-1] + 1) / (patch - step))
    wpatch = np.outer(ramp, ramp).astype(np.float32)[..., None]
    acc = np.zeros((H + 2 * patch, W + 2 * patch, 3), np.float32)
    wacc = np.zeros((H + 2 * patch, W + 2 * patch, 1), np.float32)
    for oy in range(0, H + patch, step):
        for ox in range(0, W + patch, step):
            i = rng.integers(len(ys))
            src = img[ys[i] - half:ys[i] + half, xs[i] - half:xs[i] + half]
            if rng.random() < 0.5:
                src = src[:, ::-1]
            acc[oy:oy + patch, ox:ox + patch] += src * wpatch
            wacc[oy:oy + patch, ox:ox + patch] += wpatch
    off = patch // 2
    synth = (acc / np.maximum(wacc, 1e-6))[off:off + H, off:off + W]

    m = clean.astype(np.float32)
    wsum = cv2.GaussianBlur(m, (0, 0), lighting_sigma)
    low_orig = cv2.GaussianBlur(img * m[..., None], (0, 0), lighting_sigma) / np.maximum(wsum, 1e-3)[..., None]
    far = wsum < 0.02
    low_orig[far] = cv2.GaussianBlur(ck.bg_field, (0, 0), lighting_sigma)[far]
    low_syn = cv2.GaussianBlur(synth, (0, 0), lighting_sigma)
    out = np.clip(synth - low_syn + low_orig, 0, 255).astype(np.uint8)
    return Image.fromarray(out, "RGB")


def _resolve_source(spec_path: Path, root: Path, src: str) -> Path:
    for cand in (Path(src), root / src, spec_path.parent / src):
        if cand.exists():
            return cand
    raise ConfigError(f"Không tìm thấy ảnh nguồn '{src}' (khai báo trong {spec_path.name}).")


def run_spec(spec_path: Path, raw_dir: Path, root: Path, layouts_dir: Path | None = None,
             overwrite_layout: bool = False, log=print) -> dict:
    spec = load_json(spec_path)
    source = _resolve_source(spec_path, root, spec["source"])
    log(f"  Tách nền cả thiệp {source.name} …")
    ck = key_card(source)
    H, W = ck.alpha.shape
    raw_dir.mkdir(parents=True, exist_ok=True)
    kit_json = raw_dir.parent / "kit.json"   # cùng quy tắc dọn với ingest → khung bao khớp asset cuối
    clean = cleaning_options(load_json(kit_json) if kit_json.exists() else {})
    meta = {"source": source.name, "size": [W, H], "assets": {}, "clean": clean}
    for item in spec.get("assets", []):
        if not item.get("keep", True):
            continue
        im, bbox = crop_asset(ck, item["box"], item.get("erase", []), item.get("mode", "fragments"), clean)
        p = raw_dir / f"{item['name']}.png"
        im.save(p)
        meta["assets"][item["name"]] = bbox
        log(f"  → raw/{p.name}  ({im.width}×{im.height})")
    bgs = spec.get("background")
    if bgs:
        im = synthesize_background(ck, bgs.get("patch", 160), bgs.get("seed", 7))
        p = raw_dir / f"{bgs.get('name', 'nen')}.png"
        im.save(p)
        log(f"  → raw/{p.name}  (nền dựng lại {im.width}×{im.height})")
    lines = detect_border_lines(ck)
    meta["border_lines"] = lines
    if lines:
        log("  Đường viền phát hiện: " + ", ".join(f"cách mép {l['inset']}px dày {l['width']}px" for l in lines))

    if spec.get("layout") and layouts_dir is not None:
        out = layouts_dir / f"{spec['layout']}.json"
        if out.exists() and not overwrite_layout:
            log(f"  (giữ nguyên layouts/{out.name} đã có – thêm --overwrite-layout để sinh lại bản nháp)")
        else:
            layouts_dir.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(layout_draft(spec, meta, ck), ensure_ascii=False, indent=2), encoding="utf-8")
            log(f"  → layouts/{out.name} (bản nháp bố cục)")
    return meta


def layout_draft(spec: dict, meta: dict, ck: CardKey) -> dict:
    """Bố cục nháp tái tạo thiệp gốc trên khung đích (toạ độ quy đổi theo tỉ lệ)."""
    W, H = meta["size"]
    cw = int(spec.get("canvas", {}).get("w", 1748))
    ch = int(spec.get("canvas", {}).get("h", round(cw * H / W)))
    s = cw / W
    r = lambda v: round(v * s, 1)
    orn = []
    bspec = spec.get("border")
    if bspec is not None and meta.get("border_lines"):
        orn.append({"id": "vien", "type": "border", "fill": bspec.get("fill", "gold_line"),
                    "lines": [{"inset": r(l["inset"]), "width": max(1, round(l["width"] * s))}
                              for l in meta["border_lines"]]})
    placements = [dict(it, asset=it["name"]) for it in spec.get("assets", []) if it.get("keep", True)]
    placements += spec.get("place", [])
    for it in placements:
        name = it["asset"]
        if it.get("box") and "name" not in it:   # dùng lại asset ở vị trí khác
            _, bbox = crop_asset(ck, it["box"], it.get("erase", []), it.get("mode", "fragments"), meta.get("clean"))
        else:
            bbox = meta["assets"][name]
        x, y, w, h = bbox
        el = {"id": it.get("id", name), "asset": name, "x": r(x + w / 2), "y": r(y + h / 2), "w": r(w), "anchor": "c"}
        if it.get("mirror"):
            el["mirror"] = it["mirror"]
        if it.get("flip"):
            el["flip"] = it["flip"]
        orn.append(el)
    texts = []
    for t in spec.get("texts", []):
        x, y, w, h = t["box"]
        el = {"id": t["id"], "style": t["style"], "text": t["text"],
              "cx": r(x + w / 2), "cy": r(t.get("cap_center_y", y + h / 2)), "w": r(t.get("max_w", w * 1.1))}
        if "size" in t:
            el["size"] = r(t["size"])
        for k in ("align",):
            if k in t:
                el[k] = t[k]
        texts.append(el)
    return {"title": spec.get("title", spec.get("layout")), "canvas": {"w": cw, "h": ch},
            "_nguon": f"sinh tự động từ {meta['source']} – chỉnh tay thoải mái",
            "ornaments": orn, "texts": texts}
