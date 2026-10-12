"""Bàn làm việc: giao diện web cục bộ, đi theo từng bước (không cần gõ lệnh).

Ba việc:
  Tạo mẫu thiệp mới:  ① Ý tưởng  ② Vẽ trong 1 chat ChatGPT (theo tờ, kéo ảnh vào)  ③ Kiểm tra
  Làm thiệp cho khách: ① Chọn mẫu  ② Loại thiệp + thông tin khách  ③ Xuất & xem
  Đăng lên Icard:      ① Chọn mẫu  ② Trang + ô chữ (+ xem trước giả lập Icard)  ③ Thông tin + đăng nhập  ④ Đăng

Chỉ nghe trên 127.0.0.1 (máy này). Chạy: python -m cardkit studio  (hoặc bấm đúp MoTool.bat)
"""
from __future__ import annotations

import json
import mimetypes
import os
import threading
import time
import traceback
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote, unquote, urlparse

from .catalog import BY_ID, CATALOG, GROUPS, PRESETS
from .config import ConfigError, Layout, Project, asset_notes, load_json
from .ingest import IMG_EXT, ingest
from .kitgen import FONT_FILES, create_kit_from_idea, derive_colors, slugify
from .plan import chat_messages, plan_sheets, redo_message, sheet_title
from .prompts import ROLES, SCRIPT_FONTS, build_prompt, role_of
from .sheets import apply_assignment, load_state, process_sheet, sheet_by_id
from .shapes import SHAPES
from .sizes import SIZES, resolve_size

HTML = Path(__file__).parent / "studio.html"
_lock = threading.Lock()   # một việc nặng (tách nền / xuất thiệp) tại một thời điểm


def file_url(prj: Project, p: Path | None) -> str:
    if p is None or not p.exists():
        return ""
    return "/f/" + quote(p.resolve().relative_to(prj.root).as_posix()) + f"?t={int(p.stat().st_mtime)}"


def _status_path(kit) -> Path:
    return kit.dir / "_status.json"


def _load_status(kit) -> dict:
    p = _status_path(kit)
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    except (OSError, ValueError):
        return {}


def _ingest_items(kit, items: list[str]) -> None:
    items = [i for i in items if any(kit.raw_dir.glob(f"{i}.*"))]
    if not items:
        return
    res = ingest(kit, items, force=True, log=lambda *_: None)
    st = _load_status(kit)
    for it in res:
        st[it.name] = {"status": it.status, "notes": it.notes}
    _status_path(kit).write_text(json.dumps(st, ensure_ascii=False, indent=2), encoding="utf-8")


def ensure_preview(prj: Project, name: str, force: bool = False) -> Path | None:
    """Thiệp bìa thu nhỏ (khổ A5 dọc) làm ảnh đại diện của mẫu."""
    import shutil
    import tempfile
    from .export import render_card
    kit = prj.kit(name)
    out = kit.dir / "preview.png"
    if out.exists() and not force:
        return out
    from .design import local_layouts
    lays = sorted(prj.layouts_dir.glob("*.json"))
    loc = local_layouts(kit)
    if (not lays and not loc) or not any(i != "nen" for i in kit.have_assets()):
        return None
    if loc:
        lay = Layout(loc[0]["name"], kit.layouts_dir / f"{loc[0]['name']}.json", loc[0]["data"])
    else:
        lay = prj.layout("bia") if (prj.layouts_dir / "bia.json").exists() else prj.layout(lays[0].stem)
    with tempfile.TemporaryDirectory(prefix="cardkit_pv_") as td:
        render_card(kit, lay, out_dir=Path(td), scale=0.3, pieces=False, minimal=True, log=lambda *_: None)
        shutil.copy2(Path(td) / "ghep.png", out)
    return out


def kit_summary(prj: Project, name: str) -> dict:
    kit = prj.kit(name)
    have = kit.have_assets()
    ids = list(kit.assets)
    plan = kit.data.get("plan", [])
    state = load_state(kit)
    pv = kit.dir / "preview.png"
    thumb = pv if pv.exists() else None
    return {"name": kit.name, "title": kit.data.get("title", kit.name), "total": len(ids),
            "ready": sum(1 for i in ids if i in have), "sheets": len(plan),
            "sheets_done": sum(1 for s in plan if s["id"] in state),
            "done": all(i in have for i in ids), "thumb": file_url(prj, thumb), "has_preview": thumb is not None,
            "bg": (kit.data.get("palette") or ["#f2e9d8"])[0], "design": bool(kit.data.get("design")),
            "variants": len(list(kit.layouts_dir.glob("*.json"))) if kit.layouts_dir.exists() else 0}


def _font_list(prj: Project) -> list[dict]:
    from .fontlib import list_fonts
    return list_fonts(prj.root)


def script_fonts(prj: Project) -> list[dict]:
    """Kiểu chữ tên cô dâu chú rể cho mẫu cũ: 3 font có sẵn + font viết tay khách tự thêm."""
    names = {"imperial": "Imperial Script", "pinyon": "Pinyon Script", "greatvibes": "Great Vibes"}
    out = [{"id": k, "label": names[k], "hint": SCRIPT_FONTS[k]} for k in FONT_FILES]
    out += [{"id": f["id"], "label": f["label"], "hint": f["desc"] or "font tự thêm"} for f in _font_list(prj)
            if f["kind"] == "script" and not f["builtin"] and not f["vi_missing"]]
    return out


def kit_detail(prj: Project, name: str) -> dict:
    kit = prj.kit(name)
    status = _load_status(kit)
    plan = kit.data.get("plan", [])
    is_design = bool(kit.data.get("design"))
    desc = {a: v.get("desc") for a, v in kit.assets.items() if isinstance(v, dict) and v.get("desc")} if is_design else None
    labels = {a: v.get("label") for a, v in kit.assets.items() if isinstance(v, dict) and v.get("label")}
    msgs = chat_messages(kit.data.get("idea", kit.data.get("style", "")), plan, desc, design=is_design) if plan else []
    state = load_state(kit)
    sheets = []
    for n, s in enumerate(plan, 1):
        stt = state.get(s["id"])
        pieces = []
        if stt:
            for pc in stt["pieces"]:
                f = (kit.raw_dir / "_sheets" / pc["file"]) if pc["file"] else kit.assets_dir / "nen.png"
                pieces.append({"item": pc["item"], "url": file_url(prj, f)})
        problem = stt["note"] if stt and stt["status"] != "ok" else ""
        sheets.append({
            "id": s["id"], "n": n, "kind": s["kind"], "items": s["items"], "title": sheet_title(s, labels),
            "labels": [labels.get(i) or (BY_ID[i].label if i in BY_ID else i) for i in s["items"]],
            "message": msgs[n - 1] if msgs else "",
            "redo": redo_message(s, n, len(plan), problem or "tách các hoa văn thật xa nhau, đúng số lượng", desc),
            "done": stt is not None, "status": stt["status"] if stt else "empty", "note": stt["note"] if stt else "",
            "pieces": pieces, "src_url": file_url(prj, kit.raw_dir / "_sheets" / stt["file"]) if stt else ""})
    items = []
    for aid, a in kit.assets.items():
        asset = kit.assets_dir / f"{aid}.png"
        st = status.get(aid, {})
        items.append({"id": aid, "label": a.get("label", aid), "ready": asset.exists(),
                      "status": st.get("status") or ("ok" if asset.exists() else "empty"), "notes": st.get("notes", []),
                      "qc_url": file_url(prj, kit.assets_dir / "_qc" / f"{aid}.png"), "asset_url": file_url(prj, asset),
                      "prompt": build_prompt(kit, aid, "manual"),
                      "ratio": ROLES.get(role_of(kit, aid), ROLES["ornament"])["ratio"]})
    gold = kit.fill("gold")
    stops = ", ".join(f"{c} {p * 100:.0f}%" for c, p in gold.get("stops", [])) if gold.get("type") == "gradient" else ""
    cur = kit.data.get("fonts", {}).get("script")
    script = next((k for k, v in FONT_FILES.items() if v == cur), None) or \
        next((f["id"] for f in _font_list(prj) if f["file"] == cur), "imperial")
    return {**kit_summary(prj, name), "idea": kit.data.get("idea", ""), "sheets": sheets, "items": items,
            "text_css": f"linear-gradient(170deg, {stops})" if stops else "", "script": script,
            "colors_from_images": kit.data.get("colors_from_images", False), "dir": str(kit.dir),
            "design": is_design}


LAYOUT_ORDER = ["bia", "vom_hoa", "toi_gian", "goc_cheo", "hai_ben", "vong_hoa", "thiep_moi", "gia_dinh", "cam_on"]
# Bộ thiệp online chuẩn trên Icard (48/60 mẫu có sẵn): Bìa · Gia đình · Thiệp mời · Cảm ơn
ICARD_PAGES = ["bia", "gia_dinh", "thiep_moi", "cam_on"]


def _text_fields(L: dict) -> list[dict]:
    return [{"id": t["id"], "label": t.get("label", t["id"]), "text": t.get("text", ""),
             "multiline": "\n" in str(t.get("text", ""))} for t in L.get("texts", []) if not t.get("hidden")]


def layouts_info(prj: Project, kit=None) -> list[dict]:
    from .shapes import IDS as SHAPE_IDS, shape_label
    out = []
    if kit is not None:                          # thiệp do bản thiết kế tạo (mỗi phương án một bố cục)
        from .design import infer_role, local_layouts
        labels = {a: v.get("label", a) for a, v in kit.assets.items() if isinstance(v, dict)}
        for x in local_layouts(kit):
            L = x["data"]
            own = L.get("shape") or "chu_nhat"
            undrawn = sorted({labels.get(o["asset"], o["asset"]) for o in L.get("ornaments", [])
                              if o.get("type", "asset") == "asset" and not o.get("hidden")
                              and kit.resolve_asset(o["asset"]) is None})
            out.append({"name": x["name"], "title": L.get("title", x["name"]), "mo_ta": L.get("mo_ta", ""),
                        "local": True, "card": L.get("card", ""), "card_name": L.get("card_name", ""),
                        "role": L.get("role") or infer_role(L.get("card", ""), L.get("card_name", "")),
                        "edited": bool(L.get("_edited")), "own_shape": shape_label(own),
                        "size_label": resolve_size(L["size"])["label"] if L.get("size") else "",
                        "shapes": SHAPE_IDS, "shape_default": "own",
                        "missing": [f"{u} (chưa vẽ)" for u in undrawn], "texts": _text_fields(L), "custom": False})
    paths = sorted(prj.layouts_dir.glob("*.json"),
                   key=lambda q: (LAYOUT_ORDER.index(q.stem) if q.stem in LAYOUT_ORDER else 99, q.stem))
    for p in paths:
        L = load_json(p)
        shapes = L.get("shapes") or SHAPE_IDS
        missing = []
        if kit is not None:                      # món chính của bố cục mà mẫu không có (kể cả món thay)
            from .catalog import BY_ID
            for i in L.get("key_items", []):
                real = kit.resolve_asset(i)
                if real != i:
                    missing.append(f"{BY_ID[i].label if i in BY_ID else i} ({'dùng món thay' if real else 'bỏ trống'})")
        out.append({"name": p.stem, "title": L.get("title", p.stem), "mo_ta": L.get("mo_ta", ""), "local": False,
                    "shapes": shapes, "shape_default": L.get("shape_default") or shapes[0], "missing": missing,
                    "texts": _text_fields(L),
                    "custom": p.stem not in LAYOUT_ORDER})
    return out


def editor_assets(prj: Project, name: str) -> dict:
    """Dữ liệu cho trình chỉnh: ảnh + kích thước thật của từng món (đã tính món thay), font, kiểu chữ, màu tô."""
    from PIL import Image
    from .fills import fill_css
    from .textlayer import _font_metrics
    kit = prj.kit(name)
    have = kit.have_assets()
    is_design = bool(kit.data.get("design"))
    labels = {m.id: m.label for m in CATALOG}
    labels.update({a: v.get("label", a) for a, v in kit.assets.items() if isinstance(v, dict)})
    ids = [a for a in kit.assets if a != "nen"] + ([] if is_design else [m.id for m in CATALOG if m.id != "nen"])
    items = {}
    for aid in dict.fromkeys(ids):
        real = kit.resolve_asset(aid)
        if real:
            f = kit.assets_dir / f"{real}.png"
            w, h = Image.open(f).size
            items[aid] = {"url": file_url(prj, f), "w": w, "h": h, "real": real, "label": labels.get(aid, aid),
                          "own": aid in have}
    fonts = {}
    for key in kit.data.get("fonts", {}):
        try:
            fp = kit.font_path(key)
        except ConfigError:
            continue
        from .fontlib import FONT_INFO
        kind = FONT_INFO.get(fp.name, (None, "script" if "script" in key else "serif"))[1]
        fonts[key] = {"url": file_url(prj, fp), "cap": _font_metrics(fp)["cap"], "kind": kind}
    from .fontlib import list_fonts
    for f in list_fonts(prj.root):                 # mọi font trong thư viện: ô chữ chọn font riêng được
        fp = prj.root / f["file"]
        fonts.setdefault(f["id"], {"url": file_url(prj, fp), "cap": _font_metrics(fp)["cap"], "kind": f["kind"]})
        fonts[f["id"]].update(registry=True, label=f["label"], vi_missing=f["vi_missing"])
    fills = {}
    for fname in kit.data.get("fills", {}):
        try:
            fills[fname] = fill_css(kit.fill(fname), kit.dir)
        except (ConfigError, ValueError, OSError):
            pass
    styles = {k: {"font": v.get("font"), "size": v.get("size", 60), "weight": v.get("weight", 400),
                  "line_height": v.get("line_height", 1.25), "letter_spacing": v.get("letter_spacing", 0),
                  "uppercase": bool(v.get("uppercase")), "italic": bool(v.get("italic")),
                  "fill": v.get("fill", "gold"), "shadow": v.get("shadow")} for k, v in kit.text_styles.items()}
    bgo = kit.data.get("background", {})
    nen = kit.assets_dir / f"{bgo.get('asset', 'nen')}.png" if bgo.get("asset", "nen") else None
    return {"items": items, "fonts": fonts, "fills": fills, "styles": styles,
            "bg_url": file_url(prj, nen) if nen and nen.exists() else "",
            "bg": bgo.get("color") or (kit.data.get("palette") or ["#1b3a2a"])[0],
            "labels": labels, "design": is_design,
            "backdrop": {a: True for a, v in kit.assets.items() if isinstance(v, dict) and v.get("backdrop")}}


def editor_frame(prj: Project, name: str, shape, border: dict | None, W: float, H: float, pw: int) -> dict:
    """Ảnh khung cho trình chỉnh, đúng như khi xuất: mặt nạ hình dáng + đường viền (data URL)."""
    import base64
    import io
    import numpy as np
    from PIL import Image
    from .layout import Placed
    from .raster import OrnamentRenderer
    from .shapes import IDS as SHAPE_IDS, shape_mask
    if isinstance(shape, str) and shape not in SHAPE_IDS:
        raise ConfigError(f"Hình dáng '{shape}' không có.")
    kit = prj.kit(name)
    s = pw / float(W)
    w, h = max(1, round(W * s)), max(1, round(H * s))
    m = shape_mask(shape, w, h, design=(float(W), float(H)))

    def data_url(im: Image.Image) -> str:
        buf = io.BytesIO()
        im.save(buf, "PNG")
        return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()

    mask = np.zeros((h, w, 4), np.uint8)
    mask[..., 3] = (m * 255 + 0.5).astype(np.uint8)
    out = {"mask": data_url(Image.fromarray(mask, "RGBA")), "border": ""}
    if border and border.get("lines"):
        orn = OrnamentRenderer(kit, w, h, s, None if shape == "chu_nhat" else m)
        out["border"] = data_url(orn._border(Placed("vien", "border", 0, 0, w, h, el=border)))
    return out


def preview_data(prj: Project, name: str, data: dict, shape=None) -> Path:
    """Dựng thử bố cục CHƯA lưu (đang chỉnh) để xem bản thật."""
    import shutil
    import tempfile
    from .config import Layout
    from .export import render_card
    kit = prj.kit(name)
    lay = Layout("_dang_chinh", prj.layouts_dir / "_dang_chinh.json", data)
    out = kit.dir / "_previews" / "_dang_chinh.png"
    out.parent.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="cardkit_ed_") as td:
        render_card(kit, lay, out_dir=Path(td), scale=0.3, pieces=False, minimal=True, shape=shape or None,
                    log=lambda *_: None)
        shutil.copyfile(Path(td) / "ghep.png", out)
    return out


def save_layout(prj: Project, name: str, title: str, data: dict, overwrite: bool) -> str:
    base = slugify(name or title or "bo_cuc_moi")
    if base in LAYOUT_ORDER:
        raise ConfigError("Bố cục có sẵn không ghi đè được – hãy đặt tên mới để lưu thành bố cục riêng.")
    out = prj.layouts_dir / f"{base}.json"
    if out.exists() and not overwrite:
        raise ConfigError(f"Đã có bố cục '{base}'. Đặt tên khác hoặc chọn ghi đè.")
    data = {**data, "title": title or base}
    data.setdefault("canvas", {"w": 1748, "h": 2480})
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return base


def delete_layout(prj: Project, name: str) -> None:
    """Xoá bố cục TỰ LÀM (bố cục có sẵn không xoá được)."""
    if name in LAYOUT_ORDER or slugify(name) != name:
        raise ConfigError("Chỉ xoá được bố cục tự làm.")
    f = prj.layouts_dir / f"{name}.json"
    if not f.exists():
        raise ConfigError(f"Không có bố cục '{name}'.")
    f.unlink()
    for k in prj.kits_dir.glob(f"*/_previews/{name}__*.png"):
        k.unlink(missing_ok=True)


def design_view(prj: Project, name: str) -> dict:
    """Bản thiết kế của mẫu: món cần vẽ (đã vẽ chưa), các thiệp × phương án (bố cục + lỗi bố cục), tin nhắn sửa lỗi."""
    from .design import (PAGE_ROLES, available_fonts, check_layout, fix_message, infer_role, load_design,
                         local_layouts, missing_pages, pages_message, styles_meta)
    kit = prj.kit(name)
    design = load_design(kit) or {}
    have = kit.have_assets()
    items_meta = {i["id"]: i for i in design.get("items", [])}
    for a, v in kit.assets.items():              # mẫu cũ chưa có cờ "nền mờ" trong design.json → lấy từ kit
        if isinstance(v, dict) and a in items_meta and "backdrop" not in items_meta[a]:
            items_meta[a] = {**items_meta[a], "backdrop": v.get("backdrop", False)}
    sm = styles_meta(kit, available_fonts(prj))
    cards, problems = {}, {}
    for c in design.get("cards", []):
        role = c.get("role") or infer_role(c["id"], c["name"])
        cards[c["id"]] = {"id": c["id"], "name": c["name"], "size_label": c.get("size_label", ""), "variants": [],
                          "role": role, "role_label": PAGE_ROLES.get(role, ("",))[0],
                          "page_no": list(PAGE_ROLES).index(role) + 1 if role in PAGE_ROLES else 0}
    for x in local_layouts(kit):
        L = x["data"]
        cid = L.get("card") or "khac"
        card = cards.setdefault(cid, {"id": cid, "name": L.get("card_name") or "Bố cục khác",
                                      "size_label": resolve_size(L["size"])["label"] if L.get("size") else "",
                                      "variants": []})
        probs = check_layout(L, items_meta, sm)
        auto = L.get("_autofix", [])
        if probs:
            problems[L.get("title", x["name"])] = probs
        card["variants"].append({"name": x["name"], "title": L.get("title", x["name"]), "mo_ta": L.get("mo_ta", ""),
                                 "edited": bool(L.get("_edited")), "problems": probs, "autofix": auto, "data": L})
    plan, state = kit.data.get("plan", []), load_state(kit)
    items = [{**i, "drawn": i["id"] in have, "url": file_url(prj, kit.assets_dir / f"{i['id']}.png")}
             for i in design.get("items", [])]
    return {"name": kit.name, "title": kit.data.get("title", kit.name), "request": design.get("request", ""),
            "style": design.get("style", ""), "background": design.get("background", {}),
            "colors": design.get("colors", {}), "items": items,
            "cards": sorted((c for c in cards.values() if c["variants"]), key=lambda c: c.get("page_no") or 99),
            "notes": design.get("notes", []),
            "fix_message": fix_message(problems) if problems else "", "n_problems": sum(map(len, problems.values())),
            "sheets": len(plan), "sheets_done": sum(1 for x in plan if x["id"] in state),
            "drawn": sum(1 for i in items if i["drawn"]), "bg_drawn": "nen" in have,
            "missing_pages": [PAGE_ROLES[r][0] for r in missing_pages(design)] if design.get("cards") else [],
            "pages_message": pages_message(design) if design.get("cards") else ""}


def layout_preview(prj: Project, name: str, layout: str, shape: str) -> Path:
    """Thiệp thu nhỏ của MỘT bố cục + hình dáng với mẫu này (có cache, tự làm mới khi asset đổi)."""
    import tempfile
    from .export import render_card
    kit = prj.kit(name)
    lay = prj.layout_for(kit, layout)
    own = shape in (None, "", "own")
    d = kit.dir / "_previews"
    d.mkdir(exist_ok=True)
    out = d / f"{layout}__{'own' if own else shape}.png"
    newest = max([kit.dir.joinpath("kit.json").stat().st_mtime, lay.path.stat().st_mtime]
                 + [q.stat().st_mtime for q in kit.assets_dir.glob("*.png")])
    if out.exists() and out.stat().st_mtime >= newest:
        return out
    with tempfile.TemporaryDirectory(prefix="cardkit_lp_") as td:
        render_card(kit, lay, out_dir=Path(td), scale=0.22, pieces=False, minimal=True,
                    shape=None if own else shape, log=lambda *_: None)
        import shutil
        shutil.copyfile(Path(td) / "ghep.png", out)     # thư mục tạm có thể khác ổ đĩa (C: → D:) → không dùng replace
    return out


# ---------------------------------------------------------------- Đăng lên Icard
# Phiên Icard chỉ nằm trong bộ nhớ của tiến trình này (cookie JWT); mật khẩu không được lưu.
_ICARD: dict = {"client": None, "log": [], "busy": False}


def icard_session() -> dict:
    from .icard import DEFAULT_SERVER
    c = _ICARD["client"]
    u = (c.user or {}) if c else {}
    return {"logged_in": bool(c and c.user is not None), "server": c.server if c else "",
            "default_server": os.environ.get("ICARD_API", DEFAULT_SERVER),
            "user": {"name": u.get("username") or u.get("email") or "", "role": u.get("role", "")}}


def icard_client():
    from .icard.client import IcardError
    c = _ICARD["client"]
    if c is None or c.user is None:
        raise IcardError("Chưa đăng nhập Icard – hãy đăng nhập trước.", 401)
    return c


def icard_fields(prj: Project, name: str, layouts: list[str]) -> list[dict]:
    """Các ô chữ của những thiệp đã chọn (ô cùng id dùng chung) + màu đặc mặc định trên Icard."""
    from .fills import fill_css
    from .icard.convert import default_mode, solid_color
    from .textlayer import resolve_style
    kit = prj.kit(name)
    out, seen = [], set()
    for lay in layouts:
        for t in prj.layout_for(kit, lay).texts:
            if t["id"] in seen or t.get("hidden"):
                continue
            seen.add(t["id"])
            try:
                f = kit.fill(resolve_style(kit, t).get("fill", "gold"))
                color = solid_color(fill_css(f, kit.dir)) if f.get("type") != "texture" else "#333333"
            except (ConfigError, ValueError, OSError):
                color = "#333333"
            out.append({"id": t["id"], "label": t.get("label", t["id"]), "text": t.get("text", ""),
                        "style": t.get("style", ""), "color": color, "mode": default_mode(t["id"])})
    return out


def icard_kit_info(prj: Project, name: str) -> dict:
    """Lần đăng trước của mẫu (trên server đang đăng nhập, hoặc server mặc định)."""
    from .icard.publish import links, load_state
    kit = prj.kit(name)
    sess = icard_session()
    server = sess["server"] or sess["default_server"]
    st = load_state(kit).get(server, {})
    from .design import PAGE_ROLES
    return {"server": server, "standard_pages": ICARD_PAGES, "standard_roles": list(PAGE_ROLES),
            "template_id": st.get("template_id", ""), "title": st.get("title", ""),
            "pushed_at": st.get("pushed_at", ""), "last": st.get("last"), **links(server, st.get("template_id"))}


def render(prj: Project, name: str, layouts: list[str], texts: dict, khach: str, scale: float,
           size_spec: str = "a5", shape: str | None = None) -> list[dict]:
    from .export import render_card
    kit = prj.kit(name)
    chosen = resolve_size(size_spec) if size_spec else None       # "" = mỗi thiệp đúng khổ đã thiết kế
    tag = slugify(khach) if khach.strip() else time.strftime("%Y%m%d_%H%M")
    results = []
    for lay in layouts:
        layout = prj.layout_for(kit, lay)
        size = chosen or resolve_size(layout.data.get("size") or "a5")
        out = prj.output_dir / kit.name / f"{lay}__{tag}__{slugify(size['id'])}"
        res = render_card(kit, layout, data=texts, out_dir=out, scale=scale, size=size,
                          shape=None if shape in (None, "", "own") else shape, log=lambda *_: None)
        results.append({"layout": lay, "title": layout.data.get("title", lay), "out": str(out),
                        "size": f"{size['label']} · {size['px'][0]}×{size['px'][1]} px",
                        "sheet_url": file_url(prj, out / "sheet.png"), "ghep_url": file_url(prj, out / "ghep.png"),
                        "preview_url": "/f/" + quote(out.resolve().relative_to(prj.root).as_posix()) + "/preview.html",
                        "warnings": res["warnings"], "seconds": res["seconds"]})
    return results


class Handler(BaseHTTPRequestHandler):
    prj: Project

    def log_message(self, fmt, *args):
        pass

    def _send(self, code: int, body: bytes, ctype: str):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code: int = 200):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def _body(self) -> bytes:
        n = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(n) if n else b""

    def _jbody(self) -> dict:
        return json.loads(self._body() or b"{}")

    def _parts(self) -> list[str]:
        return [unquote(x) for x in urlparse(self.path).path.strip("/").split("/") if x]

    def _guard(self, fn):
        from .icard.client import IcardError
        try:
            return fn()
        except ConfigError as e:
            return self._json({"error": str(e)}, 400)
        except IcardError as e:
            return self._json({"error": str(e), "status": e.status}, 401 if e.status == 401 else 400)
        except Exception as e:   # lỗi bất ngờ: báo về giao diện thay vì treo
            traceback.print_exc()
            return self._json({"error": f"{type(e).__name__}: {e}"}, 500)

    def do_GET(self):
        self._guard(self._get)

    def do_POST(self):
        self._guard(self._post)

    def _icard_blocked(self) -> bool:
        """API Icard dùng phiên đăng nhập production → chỉ nhận request từ chính trang bàn làm việc:
        header tuỳ chỉnh (trang lạ không gửi được tới 127.0.0.1 nếu không qua preflight CORS) + đúng Host
        (chặn DNS rebinding)."""
        host = (self.headers.get("Host") or "").rsplit(":", 1)[0]
        if self.headers.get("X-Cardkit") != "1" or host not in ("127.0.0.1", "localhost"):
            self._json({"error": "Yêu cầu không đến từ bàn làm việc."}, 403)
            return True
        return False

    def _icard_get(self, parts):
        prj = self.prj
        if parts == ["api", "icard", "session"]:
            return self._json(icard_session())
        if parts == ["api", "icard", "taxonomy"]:
            return self._json({"taxonomy": icard_client().taxonomy()})
        if parts == ["api", "icard", "progress"]:
            return self._json({"lines": _ICARD["log"][-200:], "busy": _ICARD["busy"]})
        if len(parts) == 4 and parts[2] == "kit":
            return self._json(icard_kit_info(prj, parts[3]))
        return self._send(404, b"not found", "text/plain")

    def _icard_post(self, parts):
        from .icard.client import IcardClient
        from .icard.publish import prepare, publish, write_preview
        prj, b = self.prj, self._jbody()
        if parts == ["api", "icard", "login"]:
            from .icard import normalize_server
            server = normalize_server(b.get("server") or icard_session()["default_server"])
            if not server.startswith(("https://", "http://127.0.0.1", "http://localhost")):
                raise ConfigError("Địa chỉ server Icard phải bắt đầu bằng https://")
            c = IcardClient(server)
            c.login(str(b.get("login", "")).strip(), str(b.get("password", "")))
            _ICARD["client"] = c
            return self._json(icard_session())
        if parts == ["api", "icard", "logout"]:
            if _ICARD["client"]:
                _ICARD["client"].logout()
            _ICARD["client"] = None
            return self._json(icard_session())
        if parts == ["api", "icard", "fields"]:
            return self._json({"fields": icard_fields(prj, b["kit"], b.get("layouts") or [])})
        if parts == ["api", "icard", "preview"]:
            with _lock:
                kit, pages, res = prepare(prj, b["kit"], b.get("layouts") or [], b.get("opts"), b.get("size") or None,
                                          log=lambda *_: None)
                files = write_preview(kit, res)
            n_items = sum(len(p["items"]) for p in res.template_data["pages"])
            return self._json({"pages": [file_url(prj, f) for f in files[:-1]], "thumbnail": file_url(prj, files[-1]),
                               "warnings": res.warnings, "fonts": [f.name for f in res.fonts],
                               "images": len(res.uploads), "items": n_items,
                               "size": f"{res.template_data['width']} × {res.template_data['height']}"})
        if parts == ["api", "icard", "push"]:
            client = icard_client()
            if _ICARD["busy"]:
                raise ConfigError("Đang đăng một mẫu khác – đợi xong đã.")
            _ICARD.update(busy=True, log=[])
            try:
                with _lock:
                    res = publish(prj, client, b["kit"], b.get("layouts") or [], b.get("opts"), b.get("meta") or {},
                                  b.get("size") or None, bool(b.get("design_assets")), log=_ICARD["log"].append)
            except Exception as e:
                _ICARD["log"].append(f"Lỗi: {e}")
                raise
            finally:
                _ICARD["busy"] = False
            return self._json(res)
        return self._send(404, b"not found", "text/plain")

    def _get(self):
        parts, prj = self._parts(), self.prj
        if parts[:2] == ["api", "icard"]:
            return None if self._icard_blocked() else self._icard_get(parts)
        if not parts:
            return self._send(200, HTML.read_bytes(), "text/html; charset=utf-8")
        if parts[0] == "f":
            p = (prj.root / "/".join(parts[1:])).resolve()
            if not p.is_relative_to(prj.root) or not p.is_file():
                return self._send(404, b"not found", "text/plain")
            ctype = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
            if ctype.startswith("text/") or ctype == "application/json":
                ctype += "; charset=utf-8"
            return self._send(200, p.read_bytes(), ctype)
        if parts == ["api", "fonts"]:
            return self._json({"fonts": [{**f, "url": file_url(prj, prj.root / f["file"])} for f in _font_list(prj)]})
        if parts == ["api", "state"]:
            kits = [kit_summary(prj, d.name) for d in sorted(prj.kits_dir.glob("*")) if (d / "kit.json").exists()]
            presets = {k: {**v, "sheets": len(plan_sheets(v["ids"]))} for k, v in PRESETS.items()}
            return self._json({
                "catalog": [{"id": m.id, "label": m.label, "group": m.group, "hint": m.hint} for m in CATALOG],
                "groups": GROUPS, "presets": presets, "kits": kits, "layouts": layouts_info(prj),
                "sizes": [{**z, "px": resolve_size(z["id"])["px"]} for z in SIZES],
                "shapes": SHAPES,
                "fonts": script_fonts(prj), "font_count": len(_font_list(prj))})
        if len(parts) == 3 and parts[:2] == ["api", "kit"]:
            return self._json(kit_detail(prj, parts[2]))
        if len(parts) == 4 and parts[:2] == ["api", "kit"] and parts[3] == "layouts":     # bố cục + món thiếu
            return self._json({"layouts": layouts_info(prj, prj.kit(parts[2]))})
        if len(parts) == 4 and parts[:2] == ["api", "kit"] and parts[3] == "editor":
            return self._json(editor_assets(prj, parts[2]))
        if len(parts) == 3 and parts[:2] == ["api", "layout"]:
            return self._json(load_json(prj.layout(parts[2]).path))
        if len(parts) == 4 and parts[:2] == ["api", "kit"] and parts[3] == "design":
            return self._json(design_view(prj, parts[2]))
        if len(parts) == 5 and parts[:2] == ["api", "kit"] and parts[3] == "layout":      # bố cục riêng hoặc chung
            kit = prj.kit(parts[2])
            lay = prj.layout_for(kit, parts[4])
            return self._json({**load_json(lay.path), "_local": lay.path.parent == kit.layouts_dir})
        return self._send(404, b"not found", "text/plain")

    def _post(self):
        parts, prj = self._parts(), self.prj
        if parts[:2] == ["api", "icard"]:
            return None if self._icard_blocked() else self._icard_post(parts)
        if parts == ["api", "fonts", "upload"]:
            from .fontlib import add_font
            f = add_font(prj.root, unquote(self.headers.get("X-Filename", "font.ttf")), self._body())
            return self._json({"font": f})
        if len(parts) == 3 and parts[:2] == ["api", "fonts"]:
            from .fontlib import update_font
            b = self._jbody()
            return self._json({"font": update_font(prj.root, parts[2], b.get("kind"), b.get("desc"), b.get("label"))})
        if len(parts) == 4 and parts[:2] == ["api", "fonts"] and parts[3] == "delete":
            from .fontlib import delete_font
            delete_font(prj.root, parts[2])
            return self._json({"ok": True})
        if parts == ["api", "design", "prompt"]:
            from .design import available_fonts, design_prompt
            return self._json({"prompt": design_prompt(self._jbody().get("request", ""), available_fonts(prj))})
        if parts == ["api", "design", "import"]:
            from .design import import_design
            b = self._jbody()
            if not str(b.get("text", "")).strip():
                raise ConfigError("Hãy dán câu trả lời của ChatGPT vào ô trước.")
            with _lock:
                kit, notes = import_design(prj, b["text"], b.get("kit") or None, b.get("request", ""))
            return self._json({**design_view(prj, kit.name), "import_notes": notes})
        if len(parts) == 4 and parts[:2] == ["api", "kit"] and parts[3] == "autofix":
            from .design import autofix_kit
            with _lock:
                fixed = autofix_kit(prj, prj.kit(parts[2]))
            return self._json({**design_view(prj, parts[2]), "fixed": fixed})
        if len(parts) == 4 and parts[:2] == ["api", "kit"] and parts[3] == "message":
            from .design import change_message, more_message
            b = self._jbody()
            if b.get("kind") == "more":
                return self._json({"message": more_message(b.get("card", ""), int(b.get("n", 3)))})
            if not str(b.get("text", "")).strip():
                raise ConfigError("Hãy gõ điều muốn sửa trước.")
            return self._json({"message": change_message(b["text"])})
        if len(parts) == 5 and parts[:2] == ["api", "kit"] and parts[3:] == ["layout", "save"]:
            from .design import save_local_layout
            b = self._jbody()
            name = save_local_layout(prj.kit(parts[2]), b.get("name", ""), b["data"], bool(b.get("as_new")))
            return self._json({"name": name})
        if len(parts) == 5 and parts[:2] == ["api", "kit"] and parts[3:] == ["layout", "delete"]:
            from .design import delete_local_layout
            delete_local_layout(prj.kit(parts[2]), self._jbody().get("name", ""))
            return self._json({"ok": True})
        if parts == ["api", "plan"]:                                   # xem trước số ảnh khi chọn món
            b = self._jbody()
            return self._json({"sheets": len(plan_sheets(b.get("ids", [])))})
        if parts == ["api", "kit", "new"]:
            b = self._jbody()
            if not b.get("idea", "").strip():
                raise ConfigError("Hãy viết vài dòng ý tưởng trước.")
            kit = create_kit_from_idea(prj, b["idea"], b.get("ids", []), b.get("title", ""))
            return self._json(kit_detail(prj, kit.name))
        if len(parts) >= 5 and parts[:2] == ["api", "kit"] and parts[3] == "sheet":
            kit = prj.kit(parts[2])
            sid = parts[4]
            with _lock:
                if len(parts) == 6 and parts[5] == "assign":
                    apply_assignment(kit, sid, self._jbody().get("items"))
                else:
                    fname = unquote(self.headers.get("X-Filename", "anh.png"))
                    if Path(fname).suffix.lower() not in IMG_EXT:
                        raise ConfigError("Chỉ nhận ảnh PNG, JPG hoặc WEBP.")
                    process_sheet(kit, sid, self._body(), fname)
                _, sheet = sheet_by_id(kit, sid)
                _ingest_items(kit, sheet["items"])
                kit = prj.kit(parts[2])
                if any(i != "nen" for i in kit.have_assets()):
                    derive_colors(kit)
            return self._json(kit_detail(prj, parts[2]))
        if len(parts) == 5 and parts[:2] == ["api", "kit"] and parts[3] == "item":   # thay riêng 1 món
            kit = prj.kit(parts[2])
            aid = parts[4]
            if aid not in kit.assets:
                raise ConfigError(f"Mẫu '{kit.name}' không có món '{aid}'.")
            ext = Path(unquote(self.headers.get("X-Filename", "a.png"))).suffix.lower() or ".png"
            if ext not in IMG_EXT:
                raise ConfigError("Chỉ nhận ảnh PNG, JPG hoặc WEBP.")
            with _lock:
                for old in kit.raw_dir.glob(f"{aid}.*"):
                    old.unlink()
                kit.raw_dir.mkdir(parents=True, exist_ok=True)
                (kit.raw_dir / f"{aid}{ext}").write_bytes(self._body())
                _ingest_items(kit, [aid])
                derive_colors(prj.kit(parts[2]))
            return self._json(kit_detail(prj, parts[2]))
        if len(parts) == 4 and parts[:2] == ["api", "kit"] and parts[3] == "font":
            kit = prj.kit(parts[2])
            key = self._jbody().get("script", "imperial")
            rel = FONT_FILES.get(key) or next((f["file"] for f in _font_list(prj) if f["id"] == key), None)
            if not rel:
                raise ConfigError("Kiểu chữ không hợp lệ.")
            kit.data.setdefault("fonts", {})["script"] = rel
            (kit.dir / "kit.json").write_text(json.dumps(kit.data, ensure_ascii=False, indent=2), encoding="utf-8")
            return self._json({"ok": True})
        if len(parts) == 4 and parts[:2] == ["api", "kit"] and parts[3] == "preview":
            with _lock:
                ensure_preview(prj, parts[2], force=self._jbody().get("force", False))
            return self._json(kit_summary(prj, parts[2]))
        if len(parts) == 4 and parts[:2] == ["api", "kit"] and parts[3] == "layout_preview":
            b = self._jbody()
            with _lock:
                f = layout_preview(prj, parts[2], b["layout"], b.get("shape") or "own")
            return self._json({"url": file_url(prj, f)})
        if len(parts) == 4 and parts[:2] == ["api", "kit"] and parts[3] == "frame":
            b = self._jbody()
            return self._json(editor_frame(prj, parts[2], b.get("shape") or "chu_nhat", b.get("border"),
                                           float(b.get("w", 1748)), float(b.get("h", 2480)), int(b.get("pw", 480))))
        if len(parts) == 4 and parts[:2] == ["api", "kit"] and parts[3] == "preview_data":
            b = self._jbody()
            with _lock:
                f = preview_data(prj, parts[2], b["data"], b.get("shape"))
            return self._json({"url": file_url(prj, f)})
        if parts == ["api", "layout", "delete"]:
            delete_layout(prj, self._jbody().get("name", ""))
            return self._json({"ok": True})
        if parts == ["api", "layout", "save"]:
            b = self._jbody()
            name = save_layout(prj, b.get("name", ""), b.get("title", ""), b["data"], bool(b.get("overwrite")))
            return self._json({"name": name})
        if parts == ["api", "size"]:                                   # kiểm tra khổ tuỳ chỉnh
            z = resolve_size(self._jbody().get("size", "a5"))
            return self._json({"label": z["label"], "px": z["px"]})
        if parts == ["api", "check"]:
            b = self._jbody()
            kit = prj.kit(b["kit"])
            notes = [f"[{prj.layout(l).data.get('title', l)}] {n}" for l in b.get("layouts", [])
                     for n in asset_notes(kit, prj.layout(l))[1]]
            return self._json({"notes": notes})
        if parts == ["api", "render"]:
            b = self._jbody()
            if not b.get("layouts"):
                raise ConfigError("Chọn ít nhất một loại thiệp.")
            texts = {k: v for k, v in (b.get("texts") or {}).items() if str(v).strip()}
            with _lock:
                res = render(prj, b["kit"], b["layouts"], texts, b.get("khach", ""), float(b.get("scale", 1)),
                             b.get("size", ""), b.get("shape"))
            return self._json({"results": res})
        if parts == ["api", "open"]:
            p = Path(self._jbody().get("path", "")).resolve()
            if not p.is_relative_to(prj.root) or not p.exists():
                raise ConfigError("Đường dẫn không hợp lệ.")
            if hasattr(os, "startfile"):                       # Windows
                os.startfile(p)
            else:                                              # macOS: open · Linux: xdg-open
                import subprocess
                import sys
                subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(p)])
            return self._json({"ok": True})
        return self._send(404, b"not found", "text/plain")


def serve(prj: Project, port: int = 8800, open_browser: bool = True) -> None:
    Handler.prj = prj
    srv = None
    for p in range(port, port + 20):
        try:
            srv = ThreadingHTTPServer(("127.0.0.1", p), Handler)
            break
        except OSError:
            continue
    if srv is None:
        raise ConfigError(f"Không mở được cổng {port}–{port + 19}.")
    url = f"http://127.0.0.1:{srv.server_address[1]}/"
    print(f"Bàn làm việc đang chạy: {url}\n(đóng cửa sổ này để tắt)")
    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
