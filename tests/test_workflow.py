"""Quy trình prompt mẹ → ChatGPT → nạp JSON → bộ mới; và bộ thiếu món vẫn ghép được."""
import json
import shutil
from pathlib import Path

import pytest

from cardkit.catalog import BY_ID, PRESETS, resolve
from cardkit.config import ConfigError, Project, asset_notes
from cardkit.kitgen import create_kit, parse_ai_reply, slugify
from cardkit.prompts import build_prompt, master_prompt

ROOT = Path(__file__).resolve().parents[1]

AI_REPLY = """Dưới đây là bộ prompt cho bạn:

```json
{
  "ten_bo": "Vàng mẫu đơn",
  "tieu_de": "Vàng kem – mẫu đơn",
  "style": "luxury cream and antique gold, baroque filigree with peony flowers, embossed gold foil",
  "background_desc": "warm cream textured cotton paper with a faint tone-on-tone damask",
  "palette": ["#f3e6c4", "#c9a24b", "#8a6a2c"],
  "ornament_colors": ["#c9a24b", "#e8d49a", "#f5ecd2"],
  "text_colors": ["#7a5a22", "#b08a45", "#e2c58a"],
  "script_font": "pinyon",
  "reference_prompt": "A complete portrait wedding invitation ...",
  "assets": {
    "goc": "baroque gold scroll corner with two cream peonies",
    "khung": "oval baroque gold frame crowned by a peony",
    "div_dai": "thin gold line with a tiny peony bud in the middle",
    "hoa_nho": "a small gold peony bud fleuron",
  },
}
```
Chúc bạn thành công!"""


def test_resolve_uses_same_shape_fallbacks_only():
    have = {"div_dai", "hoa_nho", "goc"}
    assert resolve("div_cuoi", have) == "div_dai"          # div_cuoi → div_hoa → div_dai
    assert resolve("mat_day", have) == "hoa_nho"
    assert resolve("khung_va", have) is None                # khung nhỏ: không có món cùng dáng → bỏ qua
    assert resolve("goc", have) == "goc"
    assert resolve("x", have, {"x": ["goc"]}) == "goc"      # alias riêng của kit


def test_presets_only_reference_catalog_ids():
    for p in PRESETS.values():
        assert "nen" in p["ids"] and all(i in BY_ID for i in p["ids"])


def test_master_prompt_lists_selected_items_and_json_schema():
    t = master_prompt("Vàng kem, hoa mẫu đơn", ["nen", "goc", "khung_va"])
    assert '"goc"' in t and '"khung_va"' in t and '"nhanh"' not in t
    assert "Vàng kem, hoa mẫu đơn" in t and '"reference_prompt"' in t and "TIẾNG ANH" in t


def test_parse_ai_reply_tolerates_fences_text_and_trailing_commas():
    d = parse_ai_reply(AI_REPLY)
    assert d["ten_bo"] == "Vàng mẫu đơn" and len(d["assets"]) == 4
    with pytest.raises(ConfigError):
        parse_ai_reply("ChatGPT trả lời mà không có JSON")


def test_slugify_vietnamese():
    assert slugify("Vàng mẫu đơn – Đỏ") == "vang_mau_don_do"


@pytest.fixture()
def project(tmp_path):
    shutil.copytree(ROOT / "fonts", tmp_path / "fonts")
    shutil.copytree(ROOT / "layouts", tmp_path / "layouts")
    (tmp_path / "kits").mkdir()
    return Project(tmp_path)


def test_create_kit_from_ai_reply(project):
    kit, notes = create_kit(project, AI_REPLY)
    assert kit.name == "vang_mau_don"
    d = kit.data
    assert set(d["assets"]) == {"nen", "goc", "khung", "div_dai", "hoa_nho"}
    assert d["assets"]["goc"]["role"] == "corner" and "peonies" in d["assets"]["goc"]["desc"]
    assert d["fonts"]["script"].endswith("PinyonScript-Regular.ttf")
    assert d["ornament_shadow"]["opacity"] < 0.3                # nền kem sáng → bóng nhẹ
    prompt = build_prompt(kit, "goc")
    assert "TOP-LEFT" in prompt and "peonies" in prompt and "solid" in prompt   # khung kỹ thuật do tool thêm
    assert (kit.dir / "PROMPTS.md").exists() and (kit.dir / "ai_reply.txt").exists()
    kit2, notes2 = create_kit(project, AI_REPLY)                # trùng tên → không ghi đè
    assert kit2.name == "vang_mau_don_2" and any("vang_mau_don_2" in n for n in notes2)


def test_layout_with_missing_items_substitutes_or_skips(project):
    kit, _ = create_kit(project, AI_REPLY)
    from PIL import Image
    for a in ("goc", "khung", "div_dai", "hoa_nho"):
        Image.new("RGBA", (40, 20), (200, 160, 70, 255)).save(kit.assets_dir / f"{a}.png")
    orn, notes = asset_notes(kit, project.layout("gia_dinh"))
    used = {e["asset"] for e in orn if e.get("type", "asset") == "asset"}
    assert used <= {"goc", "khung", "div_dai", "hoa_nho"}
    assert any("dùng 'div_dai' thay" in n for n in notes)
    assert any("khung_va" in n and "bỏ qua" in n for n in notes)
