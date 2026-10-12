"""Vẽ theo tờ trong 1 chat: kế hoạch tờ, kịch bản tin nhắn, cắt tờ, tự đo màu."""
import shutil
from pathlib import Path

import cv2
import numpy as np
import pytest
from PIL import Image

from cardkit.catalog import PRESETS
from cardkit.config import Project
from cardkit.plan import chat_messages, plan_sheets
from cardkit.sheets import process_sheet, reading_order, slice_rgba

ROOT = Path(__file__).resolve().parents[1]


def test_plan_groups_items_into_few_sheets():
    sheets = plan_sheets(PRESETS["tieu_chuan"]["ids"])
    kinds = [s["kind"] for s in sheets]
    assert len(sheets) == 5 and kinds[0] == "single" and kinds[-1] == "bg"     # 10 món → 5 ảnh
    covered = [i for s in sheets for i in s["items"]]
    assert sorted(covered) == sorted(set(PRESETS["tieu_chuan"]["ids"]))     # mỗi món đúng 1 lần
    assert all(len(s["items"]) <= 4 for s in sheets)
    full = plan_sheets(PRESETS["day_du"]["ids"])
    assert len(full) < len(PRESETS["day_du"]["ids"])                        # gộp thật


def test_chat_script_one_message_per_sheet():
    sheets = plan_sheets(PRESETS["toi_gian"]["ids"])
    msgs = chat_messages("Vàng kem, hoa mẫu đơn", sheets)
    assert len(msgs) == len(sheets)
    assert "Vàng kem, hoa mẫu đơn" in msgs[0] and "#0000FF" in msgs[0] and "ẢNH 1/" in msgs[0]
    assert all("Vàng kem" not in m for m in msgs[1:])                       # tin sau ngắn, dựa vào ngữ cảnh chat


def test_chat_rules_ask_transparent_first_then_solid_fallback():
    msg = chat_messages("x", plan_sheets(PRESETS["toi_gian"]["ids"]))[0]
    t, solid = msg.index("TRONG SUỐT"), msg.index("#0000FF")
    assert t < solid and "caro" in msg                                     # ưu tiên trong suốt, màu đặc chỉ là dự phòng


def test_single_item_prompt_asks_transparent_with_solid_fallback():
    from cardkit.config import Kit
    from cardkit.prompts import build_prompt
    kit = Kit("k", Path("."), Path("."), {"style": "gold", "ornament_colors": ["#c9a24b"],
                                         "assets": {"goc": {"desc": "a corner"}}})
    p = build_prompt(kit, "goc", "manual")
    assert p.index("transparent") < p.index("#") and "checkerboard" in p


def test_reading_order_rows_then_left_to_right():
    boxes = [(600, 50, 100, 80), (50, 60, 100, 70), (50, 400, 100, 80), (600, 420, 100, 60)]
    assert reading_order(boxes) == [1, 0, 2, 3]


def _sheet_img(shapes, key=(0, 0, 255), size=(1536, 1024)):
    W, H = size
    img = np.zeros((H, W, 3), np.uint8)
    img[:] = key
    for kind, (x, y, w, h) in shapes:
        if kind == "divider":   # nét dài + hoạ tiết giữa TÁCH RỜI nhau – phải được ghép thành 1 món
            cv2.line(img, (x, y + h // 2), (x + w // 2 - 40, y + h // 2), (200, 160, 70), 4, cv2.LINE_AA)
            cv2.line(img, (x + w // 2 + 40, y + h // 2), (x + w, y + h // 2), (200, 160, 70), 4, cv2.LINE_AA)
            cv2.circle(img, (x + w // 2, y + h // 2), 22, (230, 200, 120), -1, cv2.LINE_AA)
        else:
            cv2.ellipse(img, (x + w // 2, y + h // 2), (w // 2, h // 2), 0, 0, 360, (200, 160, 70), 10, cv2.LINE_AA)
    return img


def test_slice_stacked_dividers_merges_split_parts_in_order():
    shapes = [("divider", (150, 80 + 230 * r, 1200, 60)) for r in range(4)]
    from cardkit.keying import remove_background
    rgba = remove_background(_sheet_img(shapes)).rgba
    res = slice_rgba(rgba, 4)
    assert res.status == "ok" and len(res.pieces) == 4
    ys = [p.bbox[1] for p in res.pieces]
    assert ys == sorted(ys)                                                  # trên → dưới
    assert all(p.bbox[2] > 1100 for p in res.pieces)                         # nét + hoạ tiết giữa đã ghép


def test_slice_reports_missing_items():
    from cardkit.keying import remove_background
    rgba = remove_background(_sheet_img([("ring", (100, 200, 400, 500)), ("ring", (900, 200, 400, 500))])).rgba
    res = slice_rgba(rgba, 3)
    assert res.status == "thieu" and len(res.pieces) == 2


@pytest.fixture()
def project(tmp_path):
    shutil.copytree(ROOT / "fonts", tmp_path / "fonts")
    shutil.copytree(ROOT / "layouts", tmp_path / "layouts")
    (tmp_path / "kits").mkdir()
    return Project(tmp_path)


def test_new_kit_process_sheet_and_derive_colors(project):
    from cardkit.ingest import ingest
    from cardkit.kitgen import create_kit_from_idea, derive_colors
    kit = create_kit_from_idea(project, "Vàng kem sang trọng, hoa mẫu đơn", PRESETS["toi_gian"]["ids"], "Vàng mẫu đơn")
    assert kit.name == "vang_mau_don" and kit.data["plan"]
    row = next(s for s in kit.data["plan"] if s["kind"] in ("row", "grid"))
    shapes = [("ring", (80 + 380 * k, 250, 300, 500)) for k in range(len(row["items"]))]
    ok, buf = cv2.imencode(".png", _sheet_img(shapes)[..., ::-1])
    st = process_sheet(kit, row["id"], buf.tobytes(), "ChatGPT Image.png")
    assert st["status"] == "ok" and [p["item"] for p in st["pieces"]] == row["items"]
    for it in row["items"]:
        assert (kit.raw_dir / f"{it}.png").exists()
    ingest(kit, log=lambda *_: None)
    kit = project.kit(kit.name)
    c = derive_colors(kit)
    dark, mid, light = c["text"]
    lum = lambda h: sum(w * int(h[i:i + 2], 16) for w, i in zip((.299, .587, .114), (1, 3, 5)))
    assert lum(dark) < lum(mid) < lum(light)
    assert project.kit(kit.name).data["colors_from_images"] is True
