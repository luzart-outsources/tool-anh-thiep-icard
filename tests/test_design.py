"""Bản thiết kế linh động: AI quyết số thiệp, khổ, hình dáng, món, bố cục – tool đọc, tự sửa, báo lỗi, dựng."""
import json
import shutil
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageDraw

from cardkit.config import ConfigError, Project
from cardkit.design import (available_fonts, build_plan, check_layout, design_prompt, import_design, local_layouts,
                            normalize_design, save_local_layout, styles_meta)

ROOT = Path(__file__).resolve().parents[1]
REPLY = (ROOT / "tests" / "fixtures" / "design_reply_cuc.txt").read_text(encoding="utf-8")


@pytest.fixture()
def prj(tmp_path):
    shutil.copytree(ROOT / "fonts", tmp_path / "fonts")
    (tmp_path / "layouts").mkdir()
    (tmp_path / "kits").mkdir()
    return Project(tmp_path)


def test_prompt_lists_fonts_shapes_and_request(prj):
    p = design_prompt("Thiệp hồng pastel, hình trái tim", available_fonts(prj))
    assert "Thiệp hồng pastel, hình trái tim" in p and '"imperial"' in p and '"cormorant"' in p
    assert '"trai_tim"' in p and '"cards"' in p and "rộng 1000 đơn vị" in p


def test_prompt_requires_at_least_four_pages(prj):
    p = design_prompt("thiệp mời 15x21, 3 phương án", available_fonts(prj))
    assert "ÍT NHẤT 4 THIỆP" in p and '"role"' in p and '"cam_on"' in p and '"gia_dinh"' in p


def test_cards_get_page_roles_in_order_and_missing_pages_reported(prj):
    from cardkit.design import infer_role, missing_pages, pages_message, variant_layout
    assert infer_role("bia_thiep_moi", "Bìa thiệp mời") == "bia"
    assert infer_role("thank_you", "Thank you") == "cam_on" and infer_role("x", "Lời cảm ơn") == "cam_on"
    assert infer_role("gd", "Thông tin hai gia đình") == "gia_dinh"
    assert infer_role("thiep_moi", "Thiệp mời") == "thiep_moi" and infer_role("banner", "Banner web") == "khac"
    var = [{"items": [{"item": "a", "x": 500, "y": 500, "w": 100, "h": 100}], "texts": []}]
    raw = {"title": "x", "items": [{"id": "a", "shape": "small"}],
           "cards": [{"id": c, "name": n, "size": "15x21cm", "variants": var}
                     for c, n in (("banner", "Banner"), ("thiep_moi", "Thiệp mời"), ("cam_on", "Cảm ơn"), ("x", "Bìa"))]}
    d, _ = normalize_design(raw, available_fonts(prj))
    assert [c["role"] for c in d["cards"]] == ["bia", "thiep_moi", "cam_on", "khac"]   # xếp đúng thứ tự trang
    assert missing_pages(d) == ["gia_dinh"] and variant_layout(d, d["cards"][0], 0)["role"] == "bia"
    msg = pages_message(d)
    assert "Thông tin hai gia đình" in msg and "15x21" in msg and "```json" in msg and "Bìa" not in msg.split("THIẾU")[1][:60]
    raw["cards"][0]["role"] = "gia_dinh"                                          # role AI khai báo được tôn trọng
    d, _ = normalize_design(raw, available_fonts(prj))
    assert missing_pages(d) == [] and pages_message(d) == ""


def test_studio_reports_missing_pages_for_old_style_design(prj):
    """Bản thiết kế chỉ có thiệp mời + thiệp phụ → bàn làm việc báo thiếu 3 trang và soạn sẵn tin nhắn thêm trang."""
    from cardkit.studio import design_view, layouts_info
    kit, _ = import_design(prj, REPLY)
    dv = design_view(prj, kit.name)
    assert dv["missing_pages"] == ["Bìa", "Thông tin hai gia đình", "Cảm ơn"]
    assert "role \"bia\"" in dv["pages_message"] and "role \"cam_on\"" in dv["pages_message"]
    assert dv["cards"][0]["role"] == "thiep_moi" and dv["cards"][0]["role_label"] == "Thiệp mời"
    assert dv["cards"][0]["page_no"] == 3 and all(c["page_no"] == 0 for c in dv["cards"][1:])   # số trang theo vai trò
    roles = {L["card"]: L["role"] for L in layouts_info(prj, kit) if L["local"]}
    assert list(roles.values())[0] == "thiep_moi" and set(roles.values()) <= {"thiep_moi", "khac"}


def test_normalize_fixes_common_ai_mistakes(prj):
    from cardkit.kitgen import extract_json
    d, notes = normalize_design(extract_json(REPLY), available_fonts(prj))      # có chú thích //, dấu phẩy thừa
    assert d["styles"]["ten"]["font"] == "imperial" and "chu" in d["styles"]     # "Imperial Script", "Chu" → id chuẩn
    assert [c["size"] for c in d["cards"]] == ["15x21", "15x15", "1920x1080px"]
    assert [c["canvas"]["h"] for c in d["cards"]] == [1400.0, 1000.0, 562.5]
    assert d["cards"][1]["shape"]["label"] == "Trái tim" and d["cards"][1]["shape"]["path"].startswith("M500")
    assert any("la_xanh" in n for n in notes)                                    # món không khai báo → bỏ, có ghi chú
    tim2 = d["cards"][1]["variants"][1]
    assert [e["item"] for e in tim2["items"]] == ["nhanh_la"] and tim2["items"][0]["rotate"] == -20
    # toạ độ theo % → quy đổi; hình "heart" → tự sinh đường cắt; đường SVG hỏng → chữ nhật + ghi chú
    raw = {"title": "x", "items": [{"id": "a", "shape": "small"}], "fonts": {"t": {"font": "không có"}},
           "cards": [{"id": "c", "size": "10x10cm", "shape": "heart", "variants": [
               {"items": [{"item": "a", "x": 50, "y": 50, "w": 20, "h": 20}],
                "texts": [{"id": "ten", "style": "t", "text": "A", "x": 50, "y": 80, "w": 60, "size": 5}]}]},
               {"id": "d", "size": "A6", "shape": {"path": "M0 0 L5 0 Z"}, "variants": [{"texts": []}]}]}
    d2, n2 = normalize_design(raw, available_fonts(prj))
    v = d2["cards"][0]["variants"][0]
    assert v["items"][0]["x"] == 500 and v["texts"][0]["size"] == 50 and v["texts"][0]["w"] == 600
    assert d2["cards"][0]["shape"]["label"] == "Trái tim"
    assert d2["cards"][1]["shape"] == "chu_nhat" and d2["cards"][1]["size"] == "10.5x14.8"
    assert any("%" in n for n in n2) and any("đường SVG" in n or "phủ" in n for n in n2)
    with pytest.raises(ConfigError):
        normalize_design({"title": "rỗng", "cards": []}, available_fonts(prj))


def test_check_layout_flags_real_problems_only(prj):
    meta = {"hoa": {"name": "Hoa", "hollow": False}, "vong": {"name": "Vòng", "hollow": True}}
    sm = {"s": {"kind": "serif", "uppercase": False, "size": 40}}
    heart = {"path": "M500 940 C 220 760 40 560 60 330 C 80 140 260 60 390 90 C 450 105 490 150 500 200 "
                     "C 510 150 550 105 610 90 C 740 60 920 140 940 330 C 960 560 780 760 500 940 Z"}
    L = {"canvas": {"w": 1000, "h": 1000}, "shape": heart,
         "ornaments": [{"asset": "hoa", "x": 500, "y": 600, "w": 300, "h": 300},
                       {"asset": "vong", "x": 500, "y": 400, "w": 400, "h": 400}],
         "texts": [{"id": "a", "label": "Góc", "style": "s", "text": "Chữ ở góc", "cx": 120, "cy": 80, "w": 200, "size": 40},
                   {"id": "b", "label": "Giữa hoa", "style": "s", "text": "Tên", "cx": 500, "cy": 600, "w": 300, "size": 40},
                   {"id": "c", "label": "Trong vòng", "style": "s", "text": "Tên", "cx": 500, "cy": 400, "w": 300, "size": 40},
                   {"id": "d", "label": "Đè", "style": "s", "text": "Tên khác", "cx": 505, "cy": 410, "w": 300, "size": 40},
                   {"id": "e", "label": "Nhỏ", "style": "s", "text": "x", "cx": 500, "cy": 700, "w": 300, "size": 9}]}
    probs = " | ".join(check_layout(L, meta, sm))
    assert "'Góc' tràn ra ngoài hình dáng" in probs
    assert "'Giữa hoa' nằm đè lên giữa món 'Hoa'" in probs
    assert "Trong vòng' nằm đè" not in probs                                     # món rỗng giữa: chữ bên trong là đúng ý
    assert "'Trong vòng' đè lên chữ 'Đè'" in probs and "'Nhỏ' quá nhỏ" in probs


def test_import_creates_kit_layouts_and_update_keeps_drawn_work(prj):
    kit, notes = import_design(prj, REPLY, request="cúc trắng")
    assert kit.data["design"] and kit.data["request"] == "cúc trắng" and kit.data["auto_fills"] == []
    assert [x["name"] for x in local_layouts(kit)] == ["thiep_moi__1", "thiep_moi__2", "thiep_moi__3",
                                                     "thiep_tim__1", "thiep_tim__2", "banner_web__1", "banner_web__2"]
    L = json.loads((kit.layouts_dir / "banner_web__1.json").read_text(encoding="utf-8"))
    assert L["size"] == "1920x1080px" and L["photos"][0]["shape"] == "oval" and L["texts"][0]["group"] == "ten"
    plan = kit.data["plan"]
    assert [s["items"] for s in plan] == [["cum_cuc"], ["vong_cuc"], ["nhanh_la", "bong_cuc"], ["day_cuc"], ["nen"]]
    # đã vẽ tờ 1 + chỉnh tay 1 phương án → AI trả bản thiết kế mới (thêm món, đổi bố cục) không làm mất việc đã làm
    (kit.dir / "_sheets.json").write_text(json.dumps({"to1": {"status": "ok", "pieces": []}}), encoding="utf-8")
    edited = {**L, "texts": L["texts"][:1]}
    save_local_layout(kit, "banner_web__1", edited, as_new=False)
    new_reply = REPLY.replace('{"id": "bong_cuc", "name": "Bông cúc nhỏ"',
                              '{"id": "la_moi", "name": "Lá mới", "shape": "small", "draw": "a leaf"},\n'
                              '    {"id": "bong_cuc", "name": "Bông cúc nhỏ"')
    kit2, notes2 = import_design(prj, new_reply, kit_name=kit.name)
    plan2 = kit2.data["plan"]
    assert plan2[0] == plan[0]                                                   # tờ đã vẽ giữ nguyên (cùng id)
    assert any("la_moi" in s["items"] for s in plan2[1:]) and all(s["id"] != "to1" for s in plan2[1:])
    assert any("đã chỉnh tay" in n for n in notes2)
    kept = json.loads((kit2.layouts_dir / "banner_web__1.json").read_text(encoding="utf-8"))
    assert kept["_edited"] and len(kept["texts"]) == 1
    assert kit2.data["request"] == "cúc trắng"                                   # giữ yêu cầu gốc khi cập nhật
    new = save_local_layout(kit2, "", edited, as_new=True)
    assert new == "banner_web__3"


def test_build_plan_draws_big_usage_alone():
    design = {"background": {"draw": ""}, "cards": [{"canvas": {"w": 1000, "h": 1000}, "variants": [
        {"items": [{"item": "a", "w": 500, "h": 900}, {"item": "b", "w": 100, "h": 100}, {"item": "c", "w": 950, "h": 120}]}]}],
              "items": [{"id": "a", "shape": "small"}, {"id": "b", "shape": "small"}, {"id": "c", "shape": "wide"}]}
    plan = build_plan(design, None, set())
    assert plan[0]["items"] == ["a"] and plan[0]["ratio"] == "dọc 2:3"           # dùng rất to → vẽ riêng, khung dọc
    assert {"c"} in [set(s["items"]) for s in plan if s["kind"] == "single"]    # dải ngang dài gần hết thiệp → riêng
    assert not any(s["kind"] == "bg" for s in plan)                              # nền chỉ là màu → không vẽ ảnh nền


def _fake_assets(kit):
    kit.assets_dir.mkdir(exist_ok=True)
    for i, aid in enumerate(a for a in kit.assets if a != "nen"):
        im = Image.new("RGBA", (300, 200), (0, 0, 0, 0))
        ImageDraw.Draw(im).ellipse((20, 20, 280, 180), fill=(120 + i * 20, 160, 110, 255))
        im.save(kit.assets_dir / f"{aid}.png")


def test_render_design_cards_with_own_size_shape_photo_rotation(prj):
    pytest.importorskip("playwright")
    from cardkit.export import render_card
    kit, _ = import_design(prj, REPLY)
    _fake_assets(kit)
    kit = prj.kit(kit.name)
    out = prj.root / "out"
    try:
        render_card(kit, prj.layout_for(kit, "thiep_tim__1"), out_dir=out / "tim", scale=0.2, log=lambda *_: None)
    except Exception as e:
        if "Chromium" in str(e):
            pytest.skip(str(e))
        raise
    g = np.asarray(Image.open(out / "tim" / "ghep.png"))
    assert g.shape[:2] == (354, 354) and g[3, 3, 3] == 0 and g[177, 177, 3] == 255   # vuông 15cm, ngoài hình tim trong suốt
    render_card(kit, prj.layout_for(kit, "banner_web__1"), out_dir=out / "banner", scale=0.25, log=lambda *_: None)
    m = json.loads((out / "banner" / "manifest.json").read_text(encoding="utf-8"))
    assert m["canvas"] == {"w": 480, "h": 270} and m["photos"][0]["id"] == "anh_cuoi"
    mask = np.asarray(Image.open(out / "banner" / m["photos"][0]["file"]))
    x, y, w, h = m["photos"][0]["bbox"]
    assert mask[y + h // 2, x + w // 2, 3] == 255 and mask[y + 2, x + 2, 3] == 0        # ô oval: góc ô ngoài hình
    render_card(kit, prj.layout_for(kit, "thiep_moi__3"), out_dir=out / "moi3", scale=0.2, log=lambda *_: None)
    m3 = json.loads((out / "moi3" / "manifest.json").read_text(encoding="utf-8"))
    rot = {p["id"]: p.get("rotate") for p in m3["pieces"]}
    assert rot["bong_cuc_l"] == 15 and rot["bong_cuc_r"] == -15                   # bản đối xứng xoay ngược chiều


def test_styles_meta_kinds(prj):
    kit, _ = import_design(prj, REPLY)
    sm = styles_meta(kit, available_fonts(prj))
    assert sm["ten"]["kind"] == "script" and sm["chu"]["uppercase"] and sm["chu"]["kind"] == "serif"


def test_real_chatgpt_reply_no_false_alarms_and_readable_gold(prj):
    """Câu trả lời ChatGPT thật (navy + vàng, nền ngà): mảng màu nước / chấm sao là lớp nền chủ ý → không báo lỗi;
    chỉ còn lỗi thật; dải chữ vàng được hạ độ sáng để đọc được trên nền ngà."""
    from cardkit.kitgen import _lum
    reply = (ROOT / "tests" / "fixtures" / "design_reply_navy_chatgpt.txt").read_text(encoding="utf-8")
    kit, notes = import_design(prj, reply)
    assert {a for a, v in kit.assets.items() if v.get("backdrop")} == {"watercolor_navy_corner", "gold_dot_stars",
                                                                        "navy_ribbon_wash"}
    meta = {a: {"name": v["label"], "hollow": v["hollow"], "backdrop": v["backdrop"]} for a, v in kit.assets.items() if a != "nen"}
    sm = styles_meta(kit, available_fonts(prj))
    probs = {x["name"]: check_layout(x["data"], meta, sm) for x in local_layouts(kit)}
    assert sum(map(len, probs.values())) == 3
    assert any("tràn ra ngoài hình dáng" in p for p in probs["thiep_trai_tim__1"])
    assert any("đè lên chữ" in p for p in probs["thiep_cam_on__1"])
    assert all(_lum(c) <= _lum("#F8F5EF") - 50 for c, _ in kit.data["fills"]["gold"]["stops"])         and _lum(kit.data["fills"]["gold"]["stops"][2][0]) <= _lum("#F8F5EF") - 65


def test_autofix_clears_real_problems_and_duplicate_import_reuses_kit(prj):
    from cardkit.design import autofix_kit, layout_problems
    reply = (ROOT / "tests" / "fixtures" / "design_reply_navy_chatgpt.txt").read_text(encoding="utf-8")
    kit, _ = import_design(prj, reply)
    fixed = autofix_kit(prj, kit)
    assert len(fixed) == 3 and all(f["actions"] and not f["left"] for f in fixed)
    meta = {a: {"name": v["label"], "hollow": v.get("hollow"), "backdrop": v.get("backdrop")} for a, v in kit.assets.items()}
    sm = styles_meta(kit, available_fonts(prj))
    assert all(not layout_problems(x["data"], meta, sm) for x in local_layouts(kit))
    tim = json.loads((kit.layouts_dir / "thiep_trai_tim__1.json").read_text(encoding="utf-8"))
    hgd = next(t for t in tim["texts"] if t["id"] == "hai_gia_dinh")
    assert hgd["w"] < 620 and hgd["cy"] == 800 and tim["_autofix"]          # thu hẹp cho vừa trong hình tim
    hoa = json.loads((kit.layouts_dir / "thiep_moi__3.json").read_text(encoding="utf-8"))
    assert any(o.get("asset") == "gold_flower_corner" and o.get("opacity") == 0.35 for o in hoa["ornaments"])
    # dán lại đúng câu trả lời đó → mở lại mẫu cũ, không tạo mẫu trùng
    kit2, notes = import_design(prj, reply)
    assert kit2.name == kit.name and any("không tạo mẫu trùng" in n for n in notes)
    assert len([d for d in prj.kits_dir.iterdir() if d.is_dir()]) == 1
