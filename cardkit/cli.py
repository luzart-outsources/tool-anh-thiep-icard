"""Dòng lệnh: python -m cardkit <lệnh> …"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

from .config import ConfigError, Project, validate


def _utf8_console():
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def cmd_init(prj: Project, a):
    d = prj.kits_dir / a.kit
    if (d / "kit.json").exists():
        raise ConfigError(f"Kit '{a.kit}' đã tồn tại.")
    tpl = prj.kits_dir / (a.from_kit or "xanh_lily") / "kit.json"
    (d / "raw").mkdir(parents=True, exist_ok=True)
    (d / "assets").mkdir(exist_ok=True)
    data = json.loads(tpl.read_text(encoding="utf-8")) if tpl.exists() else {}
    data["name"] = a.kit
    data["title"] = a.kit
    (d / "kit.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Đã tạo kits/{a.kit}/ (sao chép cấu hình từ '{tpl.parent.name}'). Sửa kit.json: style, palette, assets.")


def cmd_prompts(prj: Project, a):
    from .prompts import pick_key_color, write_prompts
    kit = prj.kit(a.kit)
    p = write_prompts(kit)
    name, hx = pick_key_color(kit)
    print(f"Đã ghi {p.relative_to(prj.root)}  ({len(kit.assets)} asset, màu phông tách nền: {name} {hx})")


def cmd_generate(prj: Project, a):
    from .generate import generate
    kit = prj.kit(a.kit)
    done = generate(kit, a.assets or None, model=a.model, quality=a.quality, overwrite=a.overwrite)
    print(f"Xong: {len(done)} ảnh mới trong raw/. Tiếp theo: python -m cardkit ingest {a.kit}")


def cmd_extract(prj: Project, a):
    from .extract import key_card, run_spec, write_candidates
    kit = prj.kit(a.kit)
    if a.spec:
        run_spec(Path(a.spec), kit.raw_dir, prj.root, prj.layouts_dir, a.overwrite_layout)
        print(f"Xong. Tiếp theo: python -m cardkit ingest {a.kit}")
        return
    if not a.image:
        raise ConfigError("Cần đường dẫn ảnh thiệp (hoặc --spec).")
    src = Path(a.image)
    print(f"Tách nền {src.name} và đánh số các cụm …")
    sheet, spec = write_candidates(key_card(src), src, kit.dir / "extract")
    print(f"→ {sheet.relative_to(prj.root)}\n→ {spec.relative_to(prj.root)}\n"
          "Mở ảnh đánh số, sửa spec (tên, keep=true, erase…), rồi chạy lại với --spec <file spec>.")


def cmd_ingest(prj: Project, a):
    from .ingest import ingest
    kit = prj.kit(a.kit)
    items = ingest(kit, a.assets or None, force=a.force, upscale_to=a.upscale_to)
    icon = {"ok": "✓", "warn": "⚠", "error": "✗", "skip": "·"}
    for it in items:
        size = f"{it.size[0]}×{it.size[1]}" if it.size[0] else ""
        print(f"  {icon[it.status]} {it.name:<16} {size:>11}  {'; '.join(it.notes)}")
    n_err = sum(it.status == "error" for it in items)
    print(f"Báo cáo: kits/{a.kit}/ingest_report.md · ảnh QC: kits/{a.kit}/assets/_qc/")
    if n_err:
        sys.exit(1)


def cmd_check(prj: Project, a):
    kit, layout = prj.kit(a.kit), prj.layout(a.layout)
    errs = validate(kit, layout)
    if errs:
        print("Có lỗi:\n  - " + "\n  - ".join(errs))
        sys.exit(1)
    print(f"OK: kit '{kit.name}' + layout '{layout.name}' hợp lệ.")


def cmd_render(prj: Project, a):
    from .export import load_data, render_card
    kit, layout = prj.kit(a.kit), prj.layout(a.layout)
    data_path = Path(a.data) if a.data else None
    suffix = f"__{data_path.stem}" if data_path else ""
    out = Path(a.out) if a.out else prj.output_dir / kit.name / f"{layout.name}{suffix}"
    print(f"Render {kit.name} × {layout.name}{' × ' + data_path.name if data_path else ''} (scale {a.scale}) …")
    from .sizes import resolve_size
    size = resolve_size(a.size) if a.size else None
    res = render_card(kit, layout, data=load_data(data_path), out_dir=out, scale=a.scale, pieces=not a.no_pieces,
                      debug=a.debug, size=size, shape=a.shape)
    for w in res["warnings"]:
        print(f"  ⚠ {w}")
    print(f"Xong trong {res['seconds']}s → {out.relative_to(prj.root) if out.is_relative_to(prj.root) else out}")
    print("  01_nen.png · 02_hoa_van.png · 03_text.png · ghep.png · sheet.png · manifest.json · preview.html"
          + (f" · pieces/ ({res['pieces']} mảnh)" if not a.no_pieces else ""))


def cmd_studio(prj: Project, a):
    from .studio import serve
    serve(prj, port=a.port, open_browser=not a.no_browser)


def cmd_master(prj: Project, a):
    from .catalog import BY_ID, PRESETS
    from .prompts import master_prompt
    ids = [i.strip() for i in a.mon.split(",")] if a.mon else PRESETS[a.goi]["ids"]
    bad = [i for i in ids if i not in BY_ID]
    if bad:
        raise ConfigError(f"Không có món: {', '.join(bad)}. Các món: {', '.join(BY_ID)}")
    out = Path(a.out)
    out.write_text(master_prompt(a.y_tuong, ids), encoding="utf-8")
    print(f"Đã ghi prompt mẹ ({len(ids)} món) → {out}. Dán nội dung file vào một chat mới trên ChatGPT.")


def cmd_import(prj: Project, a):
    from .kitgen import create_kit
    kit, notes = create_kit(prj, Path(a.file).read_text(encoding="utf-8"), overwrite=a.overwrite)
    for n in notes:
        print(f"  · {n}")
    print(f"Đã tạo bộ '{kit.name}' ({len(kit.assets)} món) → kits/{kit.name}/PROMPTS.md")


def cmd_demo(prj: Project, a):
    """Chạy trọn quy trình trên bộ mẫu: extract → ingest → render 2 loại thiệp × 2 khách."""
    from .export import load_data, render_card
    from .extract import run_spec
    from .ingest import ingest
    t = time.time()
    kit = prj.kit("xanh_lily")
    specs = [kit.dir / "extract" / f for f in ("1_spec.json", "2_spec.json")]
    if not a.skip_extract:
        for sp in specs:
            print(f"[extract] {sp.name}")
            run_spec(sp, kit.raw_dir, prj.root, prj.layouts_dir, overwrite_layout=False)
    print("[ingest]")
    for it in ingest(kit, force=not a.skip_extract, log=lambda *_: None):
        print(f"  {it.status:<5} {it.name:<16} {it.size[0]}×{it.size[1]}  {'; '.join(it.notes)}")
    datas = [None] + sorted((prj.root / "data").glob("*.json"))
    for lay in ("bia", "gia_dinh"):
        if not (prj.layouts_dir / f"{lay}.json").exists():
            continue
        for dp in datas:
            out = prj.output_dir / kit.name / (lay + (f"__{dp.stem}" if dp else ""))
            print(f"[render] {lay}{' × ' + dp.name if dp else ''}")
            res = render_card(kit, prj.layout(lay), data=load_data(dp), out_dir=out, log=lambda *_: None)
            for w in res["warnings"]:
                print(f"  ⚠ {w}")
    print(f"Demo xong trong {time.time() - t:.0f}s → output/{kit.name}/")


def _icard_opts(a) -> dict:
    texts = {}
    for mode, ids in (("guest", a.guest), ("lock", a.lock), ("drop", a.drop)):
        for i in filter(None, (x.strip() for x in (ids or "").split(","))):
            texts[i] = {"mode": mode}
    return {"ornaments": a.orn, "texts": texts, "logical_w": a.width}


def cmd_icard(prj: Project, a):
    """Đăng mẫu lên Icard (push) hoặc chỉ dựng bản xem trước giả lập Icard (preview)."""
    from .icard.publish import prepare, publish, write_preview
    from .studio import ICARD_PAGES
    pages = [p.strip() for p in a.pages.split(",") if p.strip()] if a.pages else ICARD_PAGES
    if a.action == "preview":
        kit, _, res = prepare(prj, a.kit, pages, _icard_opts(a), a.size, log=print)
        for f in write_preview(kit, res):
            print(f"  {f}")
        for w in res.warnings:
            print(f"  ⚠ {w}")
        print(f"Font cần có trên Icard: {', '.join(f.name for f in res.fonts) or '(không)'} · {len(res.uploads)} ảnh")
        return
    import getpass
    import os
    from .icard import DEFAULT_SERVER
    from .icard.client import IcardClient
    c = IcardClient(a.server or os.environ.get("ICARD_API", DEFAULT_SERVER))
    user = a.user or input("Tài khoản Icard: ")
    c.login(user, os.environ.get("ICARD_PASSWORD") or getpass.getpass("Mật khẩu Icard (không hiện khi gõ): "))
    print(f"Đã đăng nhập {c.server} – quyền {c.role or '?'}")
    meta = {"title": a.title or prj.kit(a.kit).data.get("title", a.kit), "category": a.category, "group": a.group,
            "type": a.type, "description": a.description or "", "is_active": a.active}
    r = publish(prj, c, a.kit, pages, _icard_opts(a), meta, a.size, a.assets, log=lambda m: print("  " + m))
    print(("Đã tạo" if r["action"] == "create" else "Đã cập nhật") + f" mẫu {r['template_id']} "
          f"({'hiển thị' if a.active else 'nháp'}) · up {r['uploaded']} ảnh, bỏ qua {r['skipped']}")
    if r["admin_url"]:
        print(f"Editor admin: {r['admin_url']}")
    for w in r["warnings"]:
        print(f"  ⚠ {w}")


def main(argv=None):
    _utf8_console()
    ap = argparse.ArgumentParser(prog="python -m cardkit",
                                 description="Dựng thiệp theo layer: asset → bố cục → PNG từng layer.")
    ap.add_argument("--root", default=".", help="thư mục dự án (mặc định: thư mục hiện tại)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("init", help="tạo kit mới (bộ asset cho một phong cách thiệp)")
    p.add_argument("kit")
    p.add_argument("--from-kit", help="sao chép cấu hình từ kit này (mặc định xanh_lily)")
    p.set_defaults(fn=cmd_init)

    p = sub.add_parser("prompts", help="sinh PROMPTS.md: prompt cho từng asset để dán vào ChatGPT")
    p.add_argument("kit")
    p.set_defaults(fn=cmd_prompts)

    p = sub.add_parser("generate", help="tạo asset qua OpenAI API (cần OPENAI_API_KEY)")
    p.add_argument("kit")
    p.add_argument("assets", nargs="*")
    p.add_argument("--model", default="gpt-image-1")
    p.add_argument("--quality", default="high", choices=["low", "medium", "high", "auto"])
    p.add_argument("--overwrite", action="store_true")
    p.set_defaults(fn=cmd_generate)

    p = sub.add_parser("extract", help="rút asset từ một thiệp phẳng có sẵn")
    p.add_argument("kit")
    p.add_argument("image", nargs="?")
    p.add_argument("--spec", help="file spec đã chỉnh (JSON)")
    p.add_argument("--overwrite-layout", action="store_true")
    p.set_defaults(fn=cmd_extract)

    p = sub.add_parser("ingest", help="raw/ → assets/: tách nền, cắt sát, kiểm tra")
    p.add_argument("kit")
    p.add_argument("assets", nargs="*")
    p.add_argument("--force", action="store_true", help="xử lý lại cả asset không đổi")
    p.add_argument("--upscale-to", type=int, default=0,
                   help="phóng to bằng Real-ESRGAN nếu cạnh dài < N px (cần tools/realesrgan-ncnn-vulkan)")
    p.set_defaults(fn=cmd_ingest)

    p = sub.add_parser("check", help="kiểm tra kit + layout")
    p.add_argument("kit")
    p.add_argument("layout")
    p.set_defaults(fn=cmd_check)

    p = sub.add_parser("render", help="xuất bộ PNG layer + mảnh + manifest")
    p.add_argument("kit")
    p.add_argument("layout")
    p.add_argument("--data", help="JSON nội dung chữ của khách (thay chữ mẫu)")
    p.add_argument("--out", help="thư mục xuất (mặc định output/<kit>/<layout>)")
    p.add_argument("--scale", type=float, default=1.0, help="hệ số kích thước (0.5 = nhẹ cho web)")
    p.add_argument("--no-pieces", action="store_true", help="không xuất từng mảnh")
    p.add_argument("--debug", action="store_true", help="giữ trang HTML dựng chữ trong _build/ để soi lỗi")
    p.add_argument("--shape", help="hình dáng: chu_nhat | bo_goc | vom | goc_lom | oval | rang_cua | cat_goc")
    p.add_argument("--size", help="khổ thiệp: a5 | 15x21 | 13x18 | 12x18 | 10x15 | phone | 11.5x17 (cm) | 720x1280px")
    p.set_defaults(fn=cmd_render)

    p = sub.add_parser("studio", help="mở BÀN LÀM VIỆC (giao diện web cục bộ, không cần gõ lệnh)")
    p.add_argument("--port", type=int, default=8800)
    p.add_argument("--no-browser", action="store_true")
    p.set_defaults(fn=cmd_studio)

    p = sub.add_parser("master-prompt", help="ghi PROMPT MẸ ra file để dán vào ChatGPT")
    p.add_argument("y_tuong", nargs="?", default="", help="ý tưởng phong cách (tiếng Việt)")
    p.add_argument("--goi", default="tieu_chuan", choices=["toi_gian", "tieu_chuan", "day_du"])
    p.add_argument("--mon", help="tự chọn món, cách nhau dấu phẩy (vd. goc,khung,div_dai)")
    p.add_argument("--out", default="PROMPT_ME.txt")
    p.set_defaults(fn=cmd_master)

    p = sub.add_parser("import-brief", help="nạp câu trả lời ChatGPT (file .txt) → tạo bộ mới")
    p.add_argument("file")
    p.add_argument("--overwrite", action="store_true")
    p.set_defaults(fn=cmd_import)

    p = sub.add_parser("demo", help="chạy trọn quy trình trên bộ mẫu xanh_lily")
    p.add_argument("--skip-extract", action="store_true")
    p.set_defaults(fn=cmd_demo)

    p = sub.add_parser("icard", help="đăng mẫu thiệp lên Icard (push) / xem trước giả lập Icard (preview)")
    p.add_argument("action", choices=["push", "preview"])
    p.add_argument("kit")
    p.add_argument("--pages", help="các bố cục làm trang, theo thứ tự (mặc định bộ 4 trang chuẩn Icard: "
                                   "bia,gia_dinh,thiep_moi,cam_on)")
    p.add_argument("--size", help="khổ chung của các trang (mặc định: khổ thiết kế của trang 1)")
    p.add_argument("--orn", default="merge", choices=["merge", "layers"],
                   help="hoa văn: merge = gộp vào nền · layers = mỗi món một ảnh rời")
    p.add_argument("--guest", help="ô chữ là TÊN KHÁCH MỜI (Icard tự điền tên từng khách; ô 'khach' mặc định đã là)")
    p.add_argument("--lock", help="ô chữ KHOÁ (in vào thiệp, giữ ánh kim), cách nhau dấu phẩy")
    p.add_argument("--drop", help="ô chữ BỎ (không đưa lên), cách nhau dấu phẩy")
    p.add_argument("--width", type=int, default=454, help="bề rộng khung trang trên Icard (px, mẫu có sẵn của Icard: 454)")
    p.add_argument("--title", help="tiêu đề mẫu (mặc định: tên mẫu)")
    p.add_argument("--category", help="danh mục (cấp 1, vd. 'Thiệp Mời')")
    p.add_argument("--group", help="nhóm (cấp 2, vd. 'Thiệp Cưới')")
    p.add_argument("--type", help="loại (cấp 3, vd. 'Cổ Điển')")
    p.add_argument("--description")
    p.add_argument("--active", action="store_true", help="hiển thị ngay (mặc định: đăng nháp)")
    p.add_argument("--assets", action="store_true", help="đăng cả từng món hoa văn vào thư viện tài nguyên Icard")
    p.add_argument("--server", help="API Icard (mặc định https://adminapi.icards.com.vn/api/v1 hoặc $ICARD_API)")
    p.add_argument("--user", help="tài khoản Icard (mật khẩu: hỏi khi chạy, hoặc $ICARD_PASSWORD)")
    p.set_defaults(fn=cmd_icard)

    a = ap.parse_args(argv)
    prj = Project(Path(a.root).resolve())
    from .icard.client import IcardError
    try:
        a.fn(prj, a)
    except (ConfigError, IcardError) as e:
        print(f"Lỗi: {e}", file=sys.stderr)
        sys.exit(2)
