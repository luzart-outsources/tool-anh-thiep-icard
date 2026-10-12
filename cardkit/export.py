"""Lệnh render: bộ asset + bố cục (+ dữ liệu khách) → bộ file giao cho web của khách."""
from __future__ import annotations

import json
import shutil
import tempfile
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from . import __version__
from .config import ConfigError, Kit, Layout, asset_notes, load_json, validate
from .layout import adapt_to_ratio, expand
from .raster import OrnamentRenderer, paste_over, render_background
from .textlayer import render_texts


def load_data(path: Path | None) -> dict:
    if not path:
        return {}
    d = load_json(path)
    return d.get("texts", d)


def checker(w: int, h: int, cell: int = 16) -> Image.Image:
    yy, xx = np.mgrid[0:h, 0:w]
    c = np.where(((xx // cell + yy // cell) % 2)[..., None] == 0, 255, 204).astype(np.uint8)
    return Image.fromarray(np.repeat(c, 3, axis=2), "RGB")


def make_sheet(layers: list[tuple[str, Image.Image]], font_path: Path | None, panel_h: int = 900) -> Image.Image:
    W, H = layers[0][1].size
    pw = round(panel_h * W / H)
    gap, top = 24, 56
    sheet = Image.new("RGB", (gap + len(layers) * (pw + gap), top + panel_h + gap), (255, 255, 255))
    d = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.truetype(str(font_path), 34) if font_path else ImageFont.load_default()
    except Exception:
        font = ImageFont.load_default()
    for i, (label, im) in enumerate(layers):
        x = gap + i * (pw + gap)
        thumb = im.convert("RGBA").resize((pw, panel_h), Image.LANCZOS)
        bg = checker(pw, panel_h).convert("RGBA")
        bg.alpha_composite(thumb)
        sheet.paste(bg.convert("RGB"), (x, top))
        d.text((x, 10), label, fill=(20, 20, 20), font=font)
    return sheet


def render_card(kit: Kit, layout: Layout, *, data: dict | None = None, out_dir: Path,
                scale: float = 1.0, pieces: bool = True, debug: bool = False, size: dict | None = None,
                minimal: bool = False, shape: str | None = None, log=print) -> dict:
    """size: khổ thiệp (sizes.resolve_size; None = khổ thiết kế). minimal: chỉ xuất 3 layer + ảnh ghép."""
    t0 = time.time()
    if any(x.get("hidden") for x in layout.data.get("ornaments", []) + layout.data.get("texts", [])):
        layout = Layout(layout.name, layout.path, {
            **layout.data, "ornaments": [x for x in layout.data.get("ornaments", []) if not x.get("hidden")],
            "texts": [x for x in layout.data.get("texts", []) if not x.get("hidden")]})
    errs = validate(kit, layout)
    if errs:
        raise ConfigError("Cấu hình chưa hợp lệ:\n  - " + "\n  - ".join(errs))
    if size is None and layout.data.get("size"):  # thiệp do bản thiết kế tạo: tự mang khổ riêng
        from .sizes import resolve_size
        size = resolve_size(layout.data["size"])
    design0 = layout.size                          # khung gốc – toạ độ đường cắt SVG theo khung này
    if size is not None:                       # giãn bố cục sang khổ đã chọn, không méo hoa văn/chữ
        W, H = round(size["px"][0] * scale), round(size["px"][1] * scale)
        adapted, scale = adapt_to_ratio(layout.data, W, H)
        layout = Layout(layout.name, layout.path, adapted)
        dW, dH = round(W / scale), round(H / scale)
    else:
        dW, dH = layout.size
        W, H = round(dW * scale), round(dH * scale)
    # Hình dáng thiệp: bố cục khai báo hình hợp với nó ("shapes"); hình không hợp → dùng hình mặc định của bố cục
    from .shapes import IDS as SHAPE_IDS, shape_mask
    own = layout.data.get("shape")                  # hình riêng của thiệp (tên hình có sẵn hoặc {"path": …})
    if not shape and own:
        shape = own
    allowed = layout.data.get("shapes") or SHAPE_IDS
    shape_note = None
    if isinstance(shape, str) and shape and shape not in SHAPE_IDS:
        raise ConfigError(f"Hình dáng '{shape}' không có. Các hình: {', '.join(SHAPE_IDS)}")
    if isinstance(shape, dict):
        pass
    elif not shape or shape not in allowed:
        if shape:
            from .shapes import SHAPES
            lbl = {z["id"]: z["label"] for z in SHAPES}
            dflt = layout.data.get("shape_default") or allowed[0]
            shape_note = (f"Bố cục '{layout.data.get('title', layout.name)}' không hợp hình {lbl.get(shape, shape)} "
                          f"→ dùng hình {lbl.get(dflt, dflt)}.")
        shape = layout.data.get("shape_default") or allowed[0]
    smask = None if shape == "chu_nhat" else shape_mask(shape, W, H, design=design0)

    out_dir.mkdir(parents=True, exist_ok=True)
    pieces_dir = out_dir / "pieces"
    if pieces_dir.exists():
        shutil.rmtree(pieces_dir)
    if pieces:
        pieces_dir.mkdir()
    warnings: list[str] = [shape_note] if shape_note else []

    def clip(im: Image.Image) -> Image.Image:
        """Cắt ảnh theo hình dáng thiệp (ngoài hình = trong suốt)."""
        if smask is None:
            return im
        a = np.asarray(im.convert("RGBA")).copy()
        a[..., 3] = (a[..., 3].astype(np.float32) * smask + 0.5).astype(np.uint8)
        return Image.fromarray(a, "RGBA")

    # 1) Nền
    log("  [1/3] Nền …")
    nen = clip(render_background(kit, layout, W, H))
    nen.save(out_dir / "01_nen.png", compress_level=6)

    # 2) Hoa văn
    log("  [2/3] Hoa văn …")
    orn = OrnamentRenderer(kit, W, H, scale, smask)
    ornaments, notes = asset_notes(kit, layout)          # bộ thiếu món → dùng món thay / bỏ qua
    warnings += notes
    naturals = {el["asset"]: orn.natural_size(el["asset"]) for el in ornaments
                if el.get("type", "asset") == "asset"}
    placed = expand(ornaments, (dW, dH), naturals, scale)
    shadow = {**kit.data.get("ornament_shadow", {}), **layout.data.get("ornament_shadow", {})} \
        if layout.data.get("ornament_shadow", True) is not False else None
    hoa_van = clip(orn.compose(placed, shadow))
    hoa_van.save(out_dir / "02_hoa_van.png", compress_level=6)
    orn_manifest = []
    for p in placed:
        bx, by, bw, bh = p.bounds()
        entry = {"id": p.id, "layer": "hoa_van", "type": p.type,
                 "bbox": [max(0, bx), max(0, by), min(W, bx + bw) - max(0, bx), min(H, by + bh) - max(0, by)]}
        if p.rot:
            entry["rotate"] = round(p.rot, 2)
        if p.type == "asset":
            entry["asset"] = p.el["asset"]
            entry["flip"] = ("h" if p.flip_h else "") + ("v" if p.flip_v else "")
        if pieces:
            im = clip(orn.compose([p], shadow))
            f = f"pieces/hoa_van__{p.id}.png"
            im.save(out_dir / f, compress_level=6)
            entry["file"] = f
        orn_manifest.append(entry)
    warnings += orn.warnings

    # 3) Chữ
    log("  [3/3] Chữ …")
    data = data or {}
    known = {t["id"] for t in layout.texts}
    keys = {k for k in data if not k.startswith("_")}
    # Một file dữ liệu dùng chung cho cả bộ thiệp → thiếu ô ở layout này là bình thường;
    # chỉ báo khi không khoá nào khớp (nhiều khả năng chọn nhầm file / sai id).
    if keys and not keys & known:
        warnings.append(f"Không khoá nào trong dữ liệu khớp ô chữ của layout '{layout.name}' "
                        f"(các ô: {', '.join(sorted(known))}).")
    slots = [{**t, "text": data.get(t["id"], t.get("text", ""))} for t in layout.texts]
    slots = [s for s in slots if str(s["text"]).strip()]
    text_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    text_manifest = []
    if slots:
        build = out_dir / "_build"
        if build.exists():
            shutil.rmtree(build)
        if debug:
            tpieces, tw = render_texts(kit, slots, dW, dH, scale, build)
        else:  # trang HTML tạm (nhúng font ~MB) không được lẫn vào bộ file giao khách
            with tempfile.TemporaryDirectory(prefix="cardkit_") as td:
                tpieces, tw = render_texts(kit, slots, dW, dH, scale, Path(td))
        warnings += tw
        for tp in tpieces:
            if tp.image.size != (W, H):        # khung thiết kế số lẻ → ảnh chụp chữ có thể lệch 1px
                fixed = Image.new("RGBA", (W, H), (0, 0, 0, 0))
                fixed.paste(tp.image.crop((0, 0, min(W, tp.image.width), min(H, tp.image.height))), (0, 0))
                tp.image = fixed
            tp.image = clip(tp.image)
            text_layer.alpha_composite(tp.image)
            if pieces:
                f = f"pieces/text__{tp.id}.png"
                tp.image.save(out_dir / f, compress_level=6)
                tp.info["file"] = f
            text_manifest.append(tp.info)
    text_layer.save(out_dir / "03_text.png", compress_level=6)

    # Ô ảnh (website chèn ảnh cưới): mặt nạ từng ô + ô xám giữ chỗ trong ảnh ghép
    from .config import ANCHORS
    photo_manifest, holder = [], None
    for ph in layout.data.get("photos", []):
        pw, phh = float(ph.get("w", 300)), float(ph.get("h", 300))
        ax, ay = ANCHORS.get(ph.get("anchor", "c"), (.5, .5))
        x0, y0 = round((float(ph["x"]) - ax * pw) * scale), round((float(ph["y"]) - ay * phh) * scale)
        bw, bh = max(1, round(pw * scale)), max(1, round(phh * scale))
        m = shape_mask(ph.get("shape") or "chu_nhat", bw, bh, design=(pw, phh))
        full = np.zeros((H, W), np.float32)
        sx0, sy0, sx1, sy1 = max(0, x0), max(0, y0), min(W, x0 + bw), min(H, y0 + bh)
        if sx1 <= sx0 or sy1 <= sy0:
            warnings.append(f"Ô ảnh '{ph.get('id')}' nằm ngoài thiệp → bỏ qua.")
            continue
        full[sy0:sy1, sx0:sx1] = m[sy0 - y0:sy1 - y0, sx0 - x0:sx1 - x0]
        if smask is not None:
            full *= smask
        a8 = (full * 255 + 0.5).astype(np.uint8)
        hold = np.zeros((H, W, 4), np.uint8)
        hold[..., :3] = (214, 208, 199)
        hold[..., 3] = a8
        holder = Image.fromarray(hold, "RGBA") if holder is None else Image.alpha_composite(holder, Image.fromarray(hold, "RGBA"))
        entry = {"id": ph.get("id", f"anh{len(photo_manifest) + 1}"), "label": ph.get("label", "Ảnh"),
                 "bbox": [sx0, sy0, sx1 - sx0, sy1 - sy0], "shape": ph.get("shape") or "chu_nhat",
                 "note": "Ảnh đặt giữa 01_nen và 02_hoa_van; dùng file mặt nạ để cắt ảnh theo hình ô"}
        if pieces:
            mk = np.zeros((H, W, 4), np.uint8)
            mk[..., :3] = 255
            mk[..., 3] = a8
            f = f"pieces/anh__{entry['id']}.png"
            Image.fromarray(mk, "RGBA").save(out_dir / f, compress_level=6)
            entry["file"] = f
        photo_manifest.append(entry)

    # Ghép + ảnh so sánh
    ghep = nen.convert("RGBA")
    if holder is not None:
        ghep.alpha_composite(holder)
    ghep.alpha_composite(hoa_van)
    ghep.alpha_composite(text_layer)
    ghep = ghep.convert("RGB") if smask is None else ghep     # thiệp có hình: ngoài hình trong suốt
    ghep.save(out_dir / "ghep.png", compress_level=6)
    if minimal:                               # dùng cho ảnh xem trước mẫu
        return {"out_dir": out_dir, "warnings": warnings, "seconds": round(time.time() - t0, 1), "pieces": 0}
    label_font = None
    for st in kit.text_styles.values():
        try:
            label_font = kit.font_path(st["font"])
            if "script" not in st["font"]:
                break
        except ConfigError:
            pass
    make_sheet([("01_nen", nen), ("02_hoa_van", hoa_van), ("03_text", text_layer), ("Ghép lại", ghep)],
               label_font).save(out_dir / "sheet.png", compress_level=6)

    # Font đi kèm (web của khách cần để hiển thị chữ sửa được)
    fonts_out = out_dir / "fonts"
    if fonts_out.exists():
        shutil.rmtree(fonts_out)
    fonts_out.mkdir()
    font_list = {}
    keys = {st["font"] for st in kit.text_styles.values()} | {t["font"] for t in layout.texts if t.get("font")}
    for key in sorted(keys):
        try:
            fp = kit.font_path(key)
        except ConfigError:
            continue
        shutil.copy2(fp, fonts_out / fp.name)
        for lic in fp.parent.glob("OFL*.txt"):   # OFL-ImperialScript.txt ↔ ImperialScript-Regular.ttf
            if fp.name.lower().startswith(lic.stem[4:].lower()) or lic.name == "OFL.txt":
                shutil.copy2(lic, fonts_out / lic.name)
        own_lic = fp.parent / f"{fp.stem}-LICENSE.txt"       # giấy phép lấy từ chính font khách tải lên
        if own_lic.exists():
            shutil.copy2(own_lic, fonts_out / own_lic.name)
        font_list[fp.name] = f"fonts/{fp.name}"

    manifest = {
        "generator": f"cardkit {__version__}",
        "kit": kit.name, "layout": layout.name,
        "canvas": {"w": W, "h": H}, "scale": round(scale, 4), "shape": shape,
        "size": ({"label": size["label"], **({"cm": list(size["cm"]), "dpi": 300} if "cm" in size else {})}
                 if size else None),
        "layers": [{"id": "nen", "file": "01_nen.png", "z": 1},
                   {"id": "hoa_van", "file": "02_hoa_van.png", "z": 2},
                   {"id": "text", "file": "03_text.png", "z": 3}],
        "pieces": orn_manifest,
        "texts": text_manifest,
        **({"photos": photo_manifest} if photo_manifest else {}),
        "fonts": [{"file": v} for v in font_list.values()],
        "warnings": warnings,
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    write_preview(out_dir, manifest)
    return {"out_dir": out_dir, "warnings": warnings, "seconds": round(time.time() - t0, 1),
            "pieces": len(orn_manifest) + len(text_manifest)}


def write_preview(out_dir: Path, manifest: dict) -> None:
    tpl = (Path(__file__).parent / "preview_template.html").read_text(encoding="utf-8")
    (out_dir / "preview.html").write_text(
        tpl.replace("/*__MANIFEST__*/null", json.dumps(manifest, ensure_ascii=False)), encoding="utf-8")
