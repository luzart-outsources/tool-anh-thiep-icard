"""Lệnh ingest: kits/<kit>/raw/ → kits/<kit>/assets/.

Ornament: tách nền (giữ alpha thật nếu có) → cắt sát → kiểm tra lỗi → ảnh QC.
Background: chỉ kiểm tra kích thước rồi chép sang.
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from .config import Kit
from .export import checker
from .fills import hex_rgb
from .keying import KeyingError, cleaning_options, remove_background

IMG_EXT = {".png", ".jpg", ".jpeg", ".webp"}


@dataclass
class IngestItem:
    name: str
    status: str = "ok"            # ok | warn | error | skip
    kind: str = "ornament"
    size: tuple = (0, 0)
    bg: str = ""
    notes: list = field(default_factory=list)

    def warn(self, msg):
        self.notes.append(msg)
        if self.status == "ok":
            self.status = "warn"


def find_upscaler(root: Path) -> Path | None:
    for name in ("realesrgan-ncnn-vulkan.exe", "realesrgan-ncnn-vulkan"):        # bản Windows · bản macOS/Linux
        for p in (root / "tools" / "realesrgan-ncnn-vulkan" / name, root / "tools" / name):
            if p.is_file():
                return p
    exe = shutil.which("realesrgan-ncnn-vulkan")
    return Path(exe) if exe else None


def upscale(img: Image.Image, factor: int, exe: Path) -> Image.Image:
    with tempfile.TemporaryDirectory() as td:
        src, dst = Path(td) / "in.png", Path(td) / "out.png"
        img.convert("RGB").save(src)
        subprocess.run([str(exe), "-i", str(src), "-o", str(dst), "-n", "realesrgan-x4plus", "-s", "4"],
                       check=True, capture_output=True)
        out = Image.open(dst).convert("RGB")
        if factor != 4:
            out = out.resize((img.width * factor, img.height * factor), Image.LANCZOS)
        return out


def _qc_image(raw: Image.Image, asset: Image.Image, bg_hex: str, h: int = 360) -> Image.Image:
    def fit(im):
        s = h / im.height
        return im.resize((max(1, round(im.width * s)), h), Image.LANCZOS)
    r = fit(raw.convert("RGB"))
    a = fit(asset)
    chk = checker(a.width, h, 12).convert("RGBA")
    chk.alpha_composite(a)
    on_bg = Image.new("RGBA", a.size, hex_rgb(bg_hex) + (255,))
    on_bg.alpha_composite(a)
    gap = 12
    out = Image.new("RGB", (r.width + 2 * a.width + 4 * gap, h + 2 * gap), (255, 255, 255))
    x = gap
    for im in (r, chk.convert("RGB"), on_bg.convert("RGB")):
        out.paste(im, (x, gap))
        x += im.width + gap
    return out


def _overview(kit: Kit, names: list[str], bg_hex: str, cell: int = 300) -> Image.Image | None:
    ims = []
    for n in names:
        p = kit.assets_dir / f"{n}.png"
        if p.exists() and kit.assets.get(n, {}).get("kind") != "background":
            ims.append((n, Image.open(p).convert("RGBA")))
    if not ims:
        return None
    cols = min(4, len(ims))
    rows = (len(ims) + cols - 1) // cols
    sheet = Image.new("RGBA", (cols * cell, rows * (cell + 28)), hex_rgb(bg_hex) + (255,))
    d = ImageDraw.Draw(sheet)
    for i, (n, im) in enumerate(ims):
        s = min((cell - 20) / im.width, (cell - 20) / im.height)
        t = im.resize((max(1, round(im.width * s)), max(1, round(im.height * s))), Image.LANCZOS)
        x0, y0 = (i % cols) * cell, (i // cols) * (cell + 28)
        sheet.alpha_composite(t, (x0 + (cell - t.width) // 2, y0 + 28 + (cell - t.height) // 2))
        d.text((x0 + 8, y0 + 6), f"{n}  {im.width}×{im.height}", fill=(255, 255, 255))
    return sheet.convert("RGB")


def ingest(kit: Kit, names: list[str] | None = None, force: bool = False, upscale_to: int = 0,
           log=print) -> list[IngestItem]:
    kit.assets_dir.mkdir(parents=True, exist_ok=True)
    qc_dir = kit.assets_dir / "_qc"
    qc_dir.mkdir(exist_ok=True)
    files = sorted(p for p in kit.raw_dir.glob("*") if p.suffix.lower() in IMG_EXT and not p.name.startswith("_"))
    if names:
        files = [p for p in files if p.stem in names]
        missing = set(names) - {p.stem for p in files}
        for m in sorted(missing):
            log(f"  ! Không thấy raw/{m}.png")
    if not files:
        log(f"  (raw/ của kit '{kit.name}' đang trống – xem PROMPTS.md để tạo asset)")
    bg_hex = (kit.data.get("palette") or ["#1b3a2a"])[0]
    exe = find_upscaler(kit.root) if upscale_to else None
    if upscale_to and exe is None:
        log("  ! Không tìm thấy realesrgan-ncnn-vulkan – bỏ qua bước phóng to (xem README).")
    items = []
    for f in files:
        it = IngestItem(f.stem)
        out = kit.assets_dir / f"{f.stem}.png"
        decl = kit.assets.get(f.stem)
        it.kind = (decl or {}).get("kind", "ornament")
        if not force and out.exists() and out.stat().st_mtime >= f.stat().st_mtime:
            it.status = "skip"
            it.size = Image.open(out).size
            items.append(it)
            continue
        if decl is None:
            it.warn("chưa khai báo trong kit.json (mục \"assets\") – coi là hoa văn")
        try:
            raw = Image.open(f)
            raw.load()
            if exe and max(raw.size) < upscale_to:
                factor = 2 if max(raw.size) * 2 >= upscale_to else 4
                raw = upscale(raw, factor, exe)
                it.notes.append(f"đã phóng to ×{factor} bằng Real-ESRGAN")
            if it.kind == "background":
                im = raw.convert("RGB")
                im.save(out)
                it.size = im.size
                it.bg = "nền thiệp"
                if im.width < 900 or im.height < 1300:    # ChatGPT xuất nền dọc 1024×1536 – đủ cho texture
                    it.warn(f"nền chỉ {im.width}×{im.height}px – sẽ bị phóng to khi in, nhưng nền texture thường vẫn ổn")
            else:
                arr = np.asarray(raw.convert("RGBA"))
                res = remove_background(arr, **cleaning_options(kit.data))
                it.bg = f"{res.info.kind}: {res.info.note}"
                a = res.rgba[..., 3]
                if not a.any():
                    raise KeyingError("sau khi tách nền không còn gì – nền và hoa văn quá giống màu nhau")
                if res.info.kind == "checker":
                    it.warn("ChatGPT vẽ ô caro GIẢ (không phải trong suốt thật). Đã cố tách; nếu mép xấu hãy "
                            "tạo lại trên nền màu đặc")
                residue = res.stats.get("key_residue", 0)
                if residue > 0.03:
                    it.warn(f"{residue:.0%} hoa văn còn ám màu phông (ánh phản chiếu của AI) – xem ảnh kiểm tra; "
                            "nếu thấy rõ thì vẽ lại, nhấn mạnh 'no color reflections from the background'")
                cov = res.stats.get("coverage", 0)
                if cov > 0.85:
                    it.warn("gần như cả ảnh là hoa văn – có thể tách nền thất bại")
                ring = np.concatenate([a[:2].ravel(), a[-2:].ravel(), a[:, :2].ravel(), a[:, -2:].ravel()])
                if (ring > 128).mean() > 0.01:
                    it.warn("hoa văn chạm mép ảnh – có thể bị AI cắt cụt, nên tạo lại với lề rộng hơn")
                ys, xs = np.nonzero(a)
                crop = res.rgba[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
                im = Image.fromarray(crop, "RGBA")
                im.save(out)
                it.size = im.size
                _qc_image(raw, im, bg_hex).save(qc_dir / f"{f.stem}.png")
        except KeyingError as e:
            it.status = "error"
            it.notes.append(str(e))
        except Exception as e:  # ảnh hỏng, định dạng lạ …
            it.status = "error"
            it.notes.append(f"{type(e).__name__}: {e}")
        items.append(it)
    ov = _overview(kit, [p.stem for p in sorted(kit.assets_dir.glob("*.png"))], bg_hex)
    if ov is not None:
        ov.save(qc_dir / "_tong_hop.png")
    _write_report(kit, items)
    return items


def _write_report(kit: Kit, items: list[IngestItem]) -> None:
    icon = {"ok": "✅", "warn": "⚠️", "error": "❌", "skip": "⏭️"}
    lines = [f"# Báo cáo ingest – kit `{kit.name}`", "",
             "| | Asset | Loại | Kích thước | Nền phát hiện | Ghi chú |", "|---|---|---|---|---|---|"]
    for it in items:
        size = f"{it.size[0]}×{it.size[1]}" if it.size[0] else ""
        note = "; ".join(it.notes) or ("(không đổi, bỏ qua)" if it.status == "skip" else "")
        lines.append(f"| {icon[it.status]} | {it.name} | {it.kind} | {size} | {it.bg} | {note} |")
    lines += ["", "Ảnh kiểm tra từng asset: `assets/_qc/<tên>.png` (gốc · trên nền caro · trên màu nền kit).",
              "Tổng hợp cả bộ: `assets/_qc/_tong_hop.png`."]
    (kit.dir / "ingest_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
