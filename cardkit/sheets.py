"""Cắt một TỜ (ảnh ChatGPT vẽ nhiều hoa văn trên nền màu đặc) thành từng món.

Tách nền cả tờ → gom pixel thành từng hoa văn (nới dần khoảng nối cho tới khi số hoa văn
không vượt số món cần, để các mảnh rời của CÙNG một hoa văn – vd. nét dải phân cách và hoạ tiết
giữa – được ghép lại) → sắp theo thứ tự đọc (hàng trên→dưới, trong hàng trái→phải) → gán tên món.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from .config import ConfigError, Kit
from .keying import KeyingError, cleaning_options, remove_background


@dataclass
class Piece:
    bbox: tuple            # x, y, w, h trên tờ
    rgba: np.ndarray       # đã cắt sát, chỉ chứa hoa văn này


@dataclass
class SliceResult:
    pieces: list = field(default_factory=list)
    status: str = "ok"     # ok | thieu | thua
    note: str = ""


def reading_order(boxes: list[tuple]) -> list[int]:
    """Chỉ số các hộp theo thứ tự đọc: gom hàng theo chồng lấn chiều dọc, rồi trái→phải."""
    idx = sorted(range(len(boxes)), key=lambda i: boxes[i][1] + boxes[i][3] / 2)
    rows: list[list[int]] = []
    for i in idx:
        x, y, w, h = boxes[i]
        cy = y + h / 2
        for row in rows:
            top = min(boxes[j][1] for j in row)
            bot = max(boxes[j][1] + boxes[j][3] for j in row)
            if top <= cy <= bot:
                row.append(i)
                break
        else:
            rows.append([i])
    rows.sort(key=lambda r: np.mean([boxes[j][1] + boxes[j][3] / 2 for j in r]))
    return [j for r in rows for j in sorted(r, key=lambda j: boxes[j][0])]


def slice_rgba(rgba: np.ndarray, expected: int) -> SliceResult:
    a = rgba[..., 3]
    H, W = a.shape
    solid = (a > 25).astype(np.uint8)
    min_px = max(60, int(H * W * 0.0012))
    comps = []
    for frac in (0.004, 0.008, 0.014, 0.022, 0.035, 0.05):
        k = max(3, int(frac * min(H, W)) | 1)
        n, lab, st, _ = cv2.connectedComponentsWithStats(
            cv2.dilate(solid, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))), connectivity=8)
        cnt = np.bincount(lab[solid > 0], minlength=n)
        comps = [i for i in range(1, n) if cnt[i] >= min_px]
        if len(comps) <= expected:
            break
    boxes, masks = [], []
    for i in comps:
        m = (lab == i) & (solid > 0)
        ys, xs = np.nonzero(m)
        boxes.append((int(xs.min()), int(ys.min()), int(xs.max() - xs.min() + 1), int(ys.max() - ys.min() + 1)))
        masks.append(lab == i)
    res = SliceResult()
    cut = []
    for j in reading_order(boxes):
        x, y, w, h = boxes[j]
        crop = rgba[y:y + h, x:x + w].copy()
        crop[..., 3] = np.where(masks[j][y:y + h, x:x + w], crop[..., 3], 0)
        crop = np.pad(crop, ((6, 6), (6, 6), (0, 0)))      # lề trong suốt: mảnh cắt sát không bị coi là "chạm mép"
        res.pieces.append(Piece(boxes[j], crop))
        if x <= 2 or y <= 2 or x + w >= W - 2 or y + h >= H - 2:
            cut.append(len(res.pieces))
    if cut:
        res.note = f"hoa văn thứ {', '.join(map(str, cut))} chạm mép ảnh – có thể bị ChatGPT vẽ cụt"
    if len(res.pieces) < expected:
        res.status, res.note = "thieu", (f"chỉ tìm thấy {len(res.pieces)}/{expected} hoa văn – có thể ChatGPT vẽ "
                                         "thiếu, hoặc các hoa văn chạm nhau")
    elif len(res.pieces) > expected:
        res.status, res.note = "thua", f"tìm thấy {len(res.pieces)} hoa văn, nhiều hơn {expected} món cần"
    elif cut:
        res.status = "warn"
    return res


# ---------------------------------------------------------------- lưu trạng thái tờ trong kit

def _state_path(kit: Kit) -> Path:
    return kit.dir / "_sheets.json"


def load_state(kit: Kit) -> dict:
    p = _state_path(kit)
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    except (OSError, ValueError):
        return {}


def save_state(kit: Kit, st: dict) -> None:
    _state_path(kit).write_text(json.dumps(st, ensure_ascii=False, indent=2), encoding="utf-8")


def sheet_by_id(kit: Kit, sid: str) -> tuple[int, dict]:
    for n, s in enumerate(kit.data.get("plan", []), 1):
        if s["id"] == sid:
            return n, s
    raise ConfigError(f"Mẫu '{kit.name}' không có tờ '{sid}'.")


def process_sheet(kit: Kit, sid: str, data: bytes, filename: str) -> dict:
    """Nhận ảnh một tờ → tách nền, cắt, gán món theo thứ tự → raw/<món>.png. Trả về trạng thái tờ."""
    n, sheet = sheet_by_id(kit, sid)
    ext = Path(filename).suffix.lower() or ".png"
    sdir = kit.raw_dir / "_sheets"
    sdir.mkdir(parents=True, exist_ok=True)
    for old in sdir.glob(f"{sid}*"):
        old.unlink()
    src = sdir / f"{sid}{ext}"
    src.write_bytes(data)
    st = load_state(kit)
    items = sheet["items"]
    if sheet["kind"] == "bg":
        Image.open(src).convert("RGB").save(kit.raw_dir / "nen.png")
        st[sid] = {"file": src.name, "status": "ok", "note": "", "pieces": [{"file": "", "item": "nen", "bbox": None}]}
        save_state(kit, st)
        return st[sid]
    try:
        keyed = remove_background(np.asarray(Image.open(src).convert("RGBA")), **cleaning_options(kit.data))
    except KeyingError as e:
        st[sid] = {"file": src.name, "status": "loi", "note": str(e), "pieces": []}
        save_state(kit, st)
        return st[sid]
    res = slice_rgba(keyed.rgba, len(items))
    note = res.note
    residue = keyed.stats.get("key_residue", 0)
    if residue > 0.03:
        note = (note + "; " if note else "") + f"{residue:.0%} hoa văn còn ám màu nền"
    pieces = []
    for k, pc in enumerate(res.pieces):
        f = sdir / f"{sid}__{k}.png"
        Image.fromarray(pc.rgba, "RGBA").save(f)
        pieces.append({"file": f.name, "item": items[k] if k < len(items) else None, "bbox": list(pc.bbox)})
    st[sid] = {"file": src.name, "status": res.status, "note": note, "pieces": pieces,
               "bg": keyed.info.note}
    save_state(kit, st)
    apply_assignment(kit, sid)
    return load_state(kit)[sid]


def apply_assignment(kit: Kit, sid: str, assign: list | None = None) -> dict:
    """Chép mảnh đã gán sang raw/<món>.png (gán lại được khi ChatGPT xếp sai thứ tự)."""
    st = load_state(kit)
    if sid not in st:
        raise ConfigError("Tờ này chưa có ảnh.")
    pieces = st[sid]["pieces"]
    if assign is not None:
        for pc, item in zip(pieces, assign):
            pc["item"] = item or None
    sdir = kit.raw_dir / "_sheets"
    for pc in pieces:
        if pc["item"] and pc["file"]:
            for old in kit.raw_dir.glob(f"{pc['item']}.*"):
                old.unlink()
            (kit.raw_dir / f"{pc['item']}.png").write_bytes((sdir / pc["file"]).read_bytes())
    save_state(kit, st)
    return st[sid]
