"""Đăng một mẫu thiệp lên Icard: dựng các trang → chuyển → up ảnh & font → tạo hoặc cập nhật mẫu.

Trạng thái lưu ở kits/<mẫu>/icard.json, tách theo server:
  {"<server>": {"template_id", "title", "pushed_at", "uploads": {"@img:<sha1>": url},
                "fonts": [tên…], "design_assets": {món: id}, "last": {lựa chọn lần đăng trước}}}
→ đăng lại = cập nhật đúng mẫu cũ, ảnh không đổi thì không up lại (Icard không dọn ảnh thừa trên R2).
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

from ..config import ConfigError, Kit, Project
from .client import UPLOAD_CHUNK, IcardClient, IcardError
from .convert import IMG, Options, Page, Result, build, fill_urls
from .fonts import need_bytes

STATE = "icard.json"
WEB = {"adminapi.icards.com.vn": ("https://admin.icards.com.vn", "https://icards.com.vn")}


# ------------------------------------------------------------------ trạng thái

def load_state(kit: Kit) -> dict:
    p = kit.dir / STATE
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    except (OSError, ValueError):
        return {}


def save_state(kit: Kit, st: dict) -> None:
    p = kit.dir / STATE
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(st, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(p)


def server_state(all_st: dict, server: str) -> dict:
    st = all_st.setdefault(server, {})
    st.setdefault("uploads", {})
    st.setdefault("fonts", [])
    st.setdefault("design_assets", {})
    return st


def links(server: str, tid: str | None) -> dict:
    host = re.sub(r"^https?://", "", server).split("/")[0]
    admin, public = WEB.get(host, (None, None))
    if not tid or not admin:
        return {"admin_url": "", "public_url": ""}
    return {"admin_url": f"{admin}/dashboard/templates/design/{tid}", "public_url": f"{public}/invitation/{tid}"}


# ------------------------------------------------------------------ dựng các trang

def page_title(layout_data: dict, name: str) -> str:
    card, title = layout_data.get("card_name"), layout_data.get("title") or name
    return f"{card} – {title}" if card and card != title else title


def render_pages(prj: Project, kit: Kit, layouts: list[str], size_spec: str | None = None, log=print) -> list[Page]:
    """Dựng các thiệp làm trang (cùng một khổ), có cache: chỉ dựng lại khi mẫu / bố cục / hoa văn đổi."""
    from ..export import render_card
    from ..kitgen import slugify
    from ..sizes import resolve_size
    if not layouts:
        raise ConfigError("Chọn ít nhất một thiệp làm trang.")
    lays = [prj.layout_for(kit, n) for n in layouts]
    w0, h0 = lays[0].size                       # không chọn khổ → đúng khổ thiết kế của trang 1
    size = resolve_size(size_spec or lays[0].data.get("size") or f"{w0}x{h0}px")
    newest = max([(kit.dir / "kit.json").stat().st_mtime]
                 + [q.stat().st_mtime for q in kit.assets_dir.glob("*.png")])
    pages = []
    for i, lay in enumerate(lays, 1):
        out = kit.dir / "_icard" / f"{lay.name}__{slugify(size['id'])}"
        man = out / "manifest.json"
        fresh = man.exists() and man.stat().st_mtime >= max(newest, lay.path.stat().st_mtime)
        if not fresh:
            log(f"Dựng trang {i}/{len(lays)}: {page_title(lay.data, lay.name)} …")
            render_card(kit, lay, out_dir=out, size=size, log=lambda *_: None)
        pages.append(Page(out, page_title(lay.data, lay.name)))
    return pages


def prepare(prj: Project, kit_name: str, layouts: list[str], opts: dict | None, size_spec: str | None = None,
            log=print) -> tuple[Kit, list[Page], Result]:
    kit = prj.kit(kit_name)
    o = Options.from_dict({"theme_color": (kit.data.get("palette") or ["#ffffff"])[0], **(opts or {})})
    pages = render_pages(prj, kit, layouts, size_spec, log)
    return kit, pages, build(pages, o, kit.data.get("title", kit.name))


# ------------------------------------------------------------------ đăng

def _check_meta(meta: dict) -> dict:
    m = {k: str(meta.get(k) or "").strip() for k in ("title", "category", "group", "type", "description")}
    miss = [lbl for k, lbl in (("title", "tiêu đề"), ("category", "danh mục"), ("group", "nhóm"), ("type", "loại"))
            if not m[k]]
    if miss:
        raise ConfigError("Thiếu " + ", ".join(miss) + " của mẫu trên Icard.")
    m["isActive"] = bool(meta.get("is_active"))
    return m


def publish(prj: Project, client: IcardClient, kit_name: str, layouts: list[str], opts: dict | None,
            meta: dict, size_spec: str | None = None, design_assets: bool = False, log=print) -> dict:
    m = _check_meta(meta)
    if client.role and client.role not in ("admin", "designer"):
        raise IcardError(f"Tài khoản Icard có quyền '{client.role}' – cần quyền admin hoặc designer để đăng mẫu.")
    kit, pages, res = prepare(prj, kit_name, layouts, opts, size_spec, log)
    all_st = load_state(kit)
    st = server_state(all_st, client.server)

    # 1) Ảnh: chỉ up ảnh chưa có (theo hash), lưu trạng thái sau mỗi đợt
    todo = [k for k in res.uploads if k not in st["uploads"]]
    log(f"Up {len(todo)} ảnh lên Icard" + (f" (bỏ qua {len(res.uploads) - len(todo)} ảnh đã up)" if len(todo) < len(res.uploads) else "") + " …")
    for i in range(0, len(todo), UPLOAD_CHUNK):
        part = todo[i:i + UPLOAD_CHUNK]
        files = {f"img{n}": (k[len(IMG):len(IMG) + 12] + ".png", res.uploads[k], "image/png") for n, k in enumerate(part)}
        urls = client.upload_batch(files)
        for n, k in enumerate(part):
            st["uploads"][k] = urls[f"img{n}"]
        save_state(kit, all_st)
        log(f"  đã up {min(i + UPLOAD_CHUNK, len(todo))}/{len(todo)} ảnh")

    # 2) Font: đăng font mẫu dùng mà Icard chưa có (trùng tên = dùng font sẵn có)
    have = {str(f.get("name", "")).casefold() for f in client.fonts()}
    created = []
    for need in res.fonts:
        if need.name.casefold() in have:
            continue
        log(f"Đăng font '{need.name}' …")
        try:
            client.create_font(need.name, need.category, need_bytes(need), re.sub(r"\W+", "-", need.name) + ".ttf")
            created.append(need.name)
        except IcardError as e:
            if e.status != 409:                      # 409 = vừa có người đăng cùng tên → dùng luôn
                raise
        have.add(need.name.casefold())
    st["fonts"] = sorted(set(st["fonts"]) | {f.name for f in res.fonts})

    # 3) Mẫu thiệp: cập nhật mẫu cũ (nếu còn trên Icard) hoặc tạo mới
    td = fill_urls(res.template_data, st["uploads"])
    fields = {**m, "templateData": td}
    tid = st.get("template_id")
    cur = client.get_template(tid) if tid else None
    if cur is not None:
        if not m["isActive"]:            # không tích "Hiển thị ngay" → giữ trạng thái đang có (có thể đã duyệt trên Icard)
            fields["isActive"] = str(cur.get("isActive", False)).lower() == "true"
        log("Cập nhật mẫu thiệp trên Icard …")
        doc = client.update_template(tid, fields, res.thumbnail)
        action = "update"
    else:
        log("Tạo mẫu thiệp mới trên Icard …")
        try:
            doc = client.create_template(fields, res.thumbnail)
        except IcardError as e:
            if e.status == 409:
                raise IcardError(f"Icard đã có mẫu trùng tiêu đề '{m['title']}' (Icard tạo đường dẫn bằng cách bỏ "
                                 "dấu, nên hai tiêu đề chỉ khác dấu cũng bị trùng) – hãy đổi tiêu đề.", 409) from None
            raise
        tid = str(doc.get("_id") or doc.get("id") or "")
        if not tid:
            raise IcardError("Icard không trả về mã mẫu vừa tạo.")
        action = "create"
    st.update(template_id=tid, title=m["title"], slug=doc.get("slug", ""), pushed_at=time.strftime("%Y-%m-%d %H:%M"),
              last={"layouts": layouts, "opts": opts or {}, "size": size_spec or "",
                    "meta": {**meta, "is_active": m["isActive"]}, "design_assets": design_assets})
    save_state(kit, all_st)

    # 4) Hoa văn rời vào thư viện tài nguyên của Icard (tuỳ chọn, cần quyền admin)
    assets_done = []
    if design_assets:
        from ..catalog import BY_ID
        for aid, a in kit.assets.items():
            f = kit.assets_dir / f"{aid}.png"
            if aid == "nen" or aid in st["design_assets"] or not f.exists():
                continue
            label = (a.get("label") if isinstance(a, dict) else None) or (BY_ID[aid].label if aid in BY_ID else aid)
            log(f"Đăng hoa văn '{label}' vào thư viện Icard …")
            d = client.create_design_asset(f"{kit.data.get('title', kit.name)} · {label}", "component",
                                           kit.data.get("title", kit.name), f.read_bytes())
            st["design_assets"][aid] = str(d.get("_id") or d.get("id") or "")
            assets_done.append(label)
            save_state(kit, all_st)
    log("Xong.")
    return {"action": action, "template_id": tid, **links(client.server, tid), "active": bool(fields["isActive"]),
            "uploaded": len(todo),
            "skipped": len(res.uploads) - len(todo), "fonts_created": created, "design_assets": assets_done,
            "warnings": res.warnings, "pages": len(pages)}


def write_preview(kit: Kit, res: Result) -> list[Path]:
    """Lưu ảnh giả lập Icard (từng trang + thumbnail) để xem trước trong bàn làm việc."""
    d = kit.dir / "_icard" / "_xem_truoc"
    d.mkdir(parents=True, exist_ok=True)
    for old in d.glob("*.png"):
        old.unlink()
    out = []
    for i, im in enumerate(res.previews, 1):
        p = d / f"trang_{i}.png"
        im.convert("RGB").save(p)
        out.append(p)
    p = d / "thumbnail.webp"
    p.write_bytes(res.thumbnail)
    out.append(p)
    return out
