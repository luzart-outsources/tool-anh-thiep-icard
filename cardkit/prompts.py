"""Sinh prompt cho từng asset của kit – dùng dán vào ChatGPT (thủ công) hoặc gửi API."""
from __future__ import annotations

from pathlib import Path

from .config import Kit
from .fills import hex_rgb

# (tên gọi cho AI, mã màu) – màu phông để tách nền, chọn tự động xa nhất với màu hoa văn
KEY_COLORS = [("pure magenta", "#FF00FF"), ("chroma-key green", "#00B140"), ("pure blue", "#0000FF"),
              ("cyan", "#00FFFF"), ("pure black", "#000000"), ("pure white", "#FFFFFF"),
              ("neutral mid grey", "#808080")]

ROLES = {
    "background": {"ratio": "dọc 2:3", "api_size": "1024x1536", "tpl": (
        "Full-bleed background texture for a luxury wedding invitation card: {desc}. "
        "Even, soft lighting with a gentle vignette. The texture fills the ENTIRE image edge to edge. "
        "Absolutely NO ornaments, NO border lines, NO frame, NO flowers, NO text, NO objects of any kind. "
        "Portrait orientation.")},
    "corner": {"ratio": "vuông 1:1", "api_size": "1024x1024", "tpl": (
        "A single ornamental CORNER piece designed for the TOP-LEFT corner of a wedding invitation: {desc}. "
        "Its arms extend to the right along the top edge and downward along the left edge, forming an L-shaped "
        "corner. Only this one corner piece. Style: {style}.")},
    "crest": {"ratio": "ngang 3:2", "api_size": "1536x1024", "tpl": (
        "A single ornate monogram crest centerpiece for a wedding invitation: {desc}. "
        "The inside of the frame must be completely EMPTY – no letters, no monogram, no initials, no text. "
        "Perfectly left-right symmetrical. Style: {style}.")},
    "sprig": {"ratio": "dọc 2:3", "api_size": "1024x1536", "tpl": (
        "A single slim vertical decorative sprig for the LEFT side margin of a wedding invitation: {desc}. "
        "Tall and narrow, growing upward. Style: {style}.")},
    "divider": {"ratio": "ngang 3:2", "api_size": "1536x1024", "tpl": (
        "A single thin horizontal decorative text divider for a wedding invitation: {desc}. "
        "Perfectly horizontal and left-right symmetrical, long and slim. Style: {style}.")},
    "ornament": {"ratio": "vuông 1:1", "api_size": "1024x1024", "tpl": (
        "A single decorative ornament for a wedding invitation: {desc}. Style: {style}.")},
    "divider_small": {"ratio": "ngang 3:2", "api_size": "1536x1024", "tpl": (
        "A single SHORT horizontal decorative divider ornament for a wedding invitation: {desc}. "
        "Compact, perfectly left-right symmetrical, much wider than tall. Style: {style}.")},
    "divider_ornate": {"ratio": "ngang 3:2", "api_size": "1536x1024", "tpl": (
        "A single ornate horizontal header divider for a wedding invitation: {desc}. Perfectly left-right "
        "symmetrical, clearly wider than tall, an elaborate centerpiece with slim extensions to both sides. "
        "Style: {style}.")},
    "header": {"ratio": "ngang 3:2", "api_size": "1536x1024", "tpl": (
        "A single wide symmetrical header ornament for the TOP of a wedding invitation: {desc}. Much wider "
        "than tall, perfectly left-right symmetrical, with a flat bottom edge. Style: {style}.")},
    "frame_small": {"ratio": "dọc 2:3", "api_size": "1024x1536", "tpl": (
        "A single small upright decorative frame for a wedding invitation: {desc}. The inside of the frame "
        "must be completely EMPTY – no letters, no text. Perfectly left-right symmetrical. Style: {style}.")},
    "fleuron": {"ratio": "vuông 1:1", "api_size": "1024x1024", "tpl": (
        "A single small decorative fleuron motif for a wedding invitation: {desc}. Compact and perfectly "
        "left-right symmetrical. Style: {style}.")},
    "sprig_small": {"ratio": "ngang 3:2", "api_size": "1536x1024", "tpl": (
        "A single tiny horizontal leafy sprig for a wedding invitation, pointing to the RIGHT: {desc}. "
        "Style: {style}.")},
    "wreath": {"ratio": "vuông 1:1", "api_size": "1024x1024", "tpl": (
        "A single round floral wreath for a wedding invitation: {desc}. A closed ring, the center completely "
        "EMPTY (no text), roughly circular and balanced. Style: {style}.")},
    "arch_floral": {"ratio": "vuông 1:1", "api_size": "1024x1024", "tpl": (
        "A single floral arch for the top of an arch-shaped wedding invitation: {desc}. Flowers and leaves follow "
        "an upside-down U (half-circle) path, the inside EMPTY. Symmetrical. Style: {style}.")},
    "bouquet": {"ratio": "vuông 1:1", "api_size": "1024x1024", "tpl": (
        "A single lush floral bouquet cluster designed for the TOP-LEFT corner of a wedding invitation: {desc}. "
        "It spreads diagonally from the top-left toward the center, asymmetric and natural. Style: {style}.")},
    "garland": {"ratio": "dọc 2:3", "api_size": "1024x1536", "tpl": (
        "A single long vertical floral garland for the LEFT edge of a wedding invitation: {desc}. Tall and narrow, "
        "flowers and leaves along a vertical stem. Style: {style}.")},
    "pendant": {"ratio": "dọc 2:3", "api_size": "1024x1536", "tpl": (
        "A single small vertical pendant finial ornament for a wedding invitation, pointing UP: {desc}. "
        "Narrow, perfectly left-right symmetrical. Style: {style}.")},
}


def role_of(kit: Kit, name: str) -> str:
    from .catalog import BY_ID
    a = kit.assets.get(name, {})
    if a.get("kind") == "background" or name == "nen":
        return "background"
    return a.get("role") or (BY_ID[name].role if name in BY_ID else "ornament")

COMMON = ("Isolated object centered in the image with generous empty margins on all sides – nothing touches "
          "the image edges. High detail, crisp fine lines, print quality. No text, no letters, no watermark, "
          "no signature.")
FLAT_BG = ("Output a PNG with a truly transparent background (real alpha channel, everything outside the object fully "
           "transparent). If you cannot produce real transparency, place it instead on a perfectly flat, uniform, "
           "solid {key_name} background ({key_hex}) – one single flat color. Never draw a fake grey-and-white "
           "checkerboard pattern. No gradient, no texture, no vignette, no drop shadow, no ground shadow, "
           "no reflection, no frame.")
TRANSPARENT_BG = "Transparent background. No drop shadow, no ground shadow."


def pick_key_color(kit: Kit) -> tuple[str, str]:
    forced = kit.data.get("key_color", "auto")
    if forced and forced != "auto":
        for name, hx in KEY_COLORS:
            if hx.lower() == forced.lower():
                return name, hx
        return "solid", forced
    colors = kit.data.get("ornament_colors") or kit.data.get("palette") or []
    if not colors:
        return KEY_COLORS[0]
    cols = [hex_rgb(c) for c in colors]

    def min_dist(hx):
        k = hex_rgb(hx)
        return min(sum((a - b) ** 2 for a, b in zip(k, c)) ** 0.5 for c in cols)
    return max(KEY_COLORS, key=lambda kc: min_dist(kc[1]))


def build_prompt(kit: Kit, name: str, mode: str = "manual") -> str:
    a = kit.assets.get(name, {})
    role = role_of(kit, name)
    tpl = ROLES.get(role, ROLES["ornament"])["tpl"]
    style = kit.data.get("style", "")
    desc = a.get("desc", name)
    if role == "background":
        desc = a.get("desc") or kit.data.get("background_desc", "textured paper")
        return tpl.format(desc=desc)
    body = tpl.format(desc=desc, style=style) + " " + COMMON
    if mode == "api":
        return body + " " + TRANSPARENT_BG
    key_name, key_hex = pick_key_color(kit)
    return body + " " + FLAT_BG.format(key_name=key_name, key_hex=key_hex)


def write_prompts(kit: Kit) -> Path:
    key_name, key_hex = pick_key_color(kit)
    lines = [f"# Prompt tạo asset – kit `{kit.name}`", "",
             f"**Phong cách chung:** {kit.data.get('style', '(chưa khai báo)')}", "",
             "## Cách làm (thủ công với ChatGPT)", "",
             "1. **Mỗi asset một cuộc chat MỚI.** Không bảo AI \"sửa lại\" – hỏng thì mở chat mới, dán lại đúng prompt.",
             "2. Nếu có thiệp mẫu đã ưng, **đính kèm ảnh mẫu** và thêm câu: "
             "*\"Match the ornament style, colors and level of detail of the attached reference image.\"*",
             f"3. Asset hoa văn được yêu cầu vẽ trên **nền trong suốt thật**; không được thì **nền màu đặc "
             f"{key_name} ({key_hex})** – màu này được chọn tự động sao cho xa nhất với màu hoa văn của kit. "
             "Kiểu nào công cụ cũng lọc lại một lần nữa (tách nền, dọn hạt lấm tấm, khử viền ám màu).",
             "4. Tải ảnh về, **đặt tên đúng** như cột *Lưu thành* rồi bỏ vào thư mục `raw/` của kit.",
             f"5. Chạy: `python -m cardkit ingest {kit.name}` → xem `ingest_report.md` và `assets/_qc/`.",
             "",
             "> Nếu ChatGPT trả về ảnh có **ô caro xám-trắng**, đó là caro *vẽ giả*, không phải trong suốt. "
             "Công cụ vẫn cố tách, nhưng tốt nhất là yêu cầu lại (nền trong suốt thật hoặc màu đặc).",
             "", "## Danh sách asset", ""]
    if kit.data.get("reference_prompt"):
        lines += ["### Ảnh tham chiếu phong cách (làm TRƯỚC, 1 lần)", "",
                  "Vẽ 1 thiệp mẫu hoàn chỉnh – chỉ dùng làm chuẩn phong cách, đính kèm khi vẽ từng món bên dưới.",
                  "- Khung ảnh: **dọc 2:3**", "", "```text", kit.data["reference_prompt"], "```", ""]
    for name, a in kit.assets.items():
        role = role_of(kit, name)
        info = ROLES.get(role, ROLES["ornament"])
        lines += [f"### `{name}` – {a.get('label', role)}", "",
                  f"- Lưu thành: `kits/{kit.name}/raw/{name}.png`",
                  f"- Khung ảnh nên chọn: **{info['ratio']}**",
                  "", "```text", build_prompt(kit, name, "manual"), "```", ""]
    p = kit.dir / "PROMPTS.md"
    p.write_text("\n".join(lines), encoding="utf-8")
    return p


SCRIPT_FONTS = {"imperial": "cổ điển thanh lịch, chữ hoa uốn lượn", "pinyon": "mảnh, bay bổng, nghiêng nhiều",
                "greatvibes": "đậm, tròn, hiện đại"}


def master_prompt(brief: str, ids: list[str]) -> str:
    """PROMPT MẸ: dán vào ChatGPT (chế độ chữ) → nhận về 1 khối JSON để nạp vào tool."""
    from .catalog import BY_ID
    ids = [i for i in ids if i != "nen"]
    mon = "\n".join(f'- "{i}": {BY_ID[i].label} – {BY_ID[i].hint}' if i in BY_ID else f'- "{i}"' for i in ids)
    fonts = "\n".join(f'  - "{k}": {v}' for k, v in SCRIPT_FONTS.items())
    example = ",\n    ".join(f'"{i}": "..."' for i in ids)
    brief = brief.strip() or "(điền ý tưởng: tông màu, hoa/hoạ tiết chính, cảm giác – sang trọng, cổ điển, hiện đại…)"
    return f"""Bạn là giám đốc nghệ thuật chuyên thiết kế thiệp cưới cao cấp.

NHIỆM VỤ: từ Ý TƯỞNG bên dưới, xây dựng MỘT phong cách thống nhất cho cả bộ thiệp, rồi viết mô tả cho từng MÓN hoa văn. Mỗi món sẽ được một AI vẽ ảnh vẽ RIÊNG LẺ, sau đó ghép lại bằng phần mềm.

Ý TƯỞNG:
<<<
{brief}
>>>

CÁC MÓN CẦN MÔ TẢ (giữ nguyên mã trong ngoặc kép):
{mon}

YÊU CẦU:
1. Mọi món cùng một phong cách, bảng màu, chất liệu và độ chi tiết – nhìn như của cùng một nhà thiết kế.
2. Mô tả bằng TIẾNG ANH, mỗi món 1–3 câu, chỉ tả CHÍNH món đó: hình dáng, hoạ tiết, hoa lá, chất liệu, màu.
   KHÔNG nhắc tới nền, khung ảnh, bố cục thiệp, chữ – phần mềm tự thêm các yêu cầu kỹ thuật.
3. Tuyệt đối không có chữ, chữ cái, chữ lồng (monogram) trong bất kỳ món nào.
4. "style": 1–2 câu tiếng Anh về phong cách chung (kỹ thuật vẽ, chất liệu như foil/emboss/watercolor, độ chi tiết).
5. "background_desc": 1 câu tiếng Anh tả nền giấy (màu, chất giấy, hoạ tiết chìm nếu có) – không hoa văn nổi.
6. "palette": 3–5 mã màu HEX của thiệp, màu NỀN đứng đầu. "ornament_colors": 3–5 mã HEX của hoa văn.
7. "text_colors": đúng 3 mã HEX cho chữ: [tối, chính, sáng] – dùng làm hiệu ứng ánh kim/màu chữ.
8. "script_font": chọn 1 kiểu chữ viết tay hợp phong cách:
{fonts}
9. "reference_prompt": prompt tiếng Anh vẽ MỘT thiệp mẫu hoàn chỉnh (khổ dọc 2:3) đúng phong cách này, có đủ các món trên – dùng làm ảnh tham chiếu phong cách.
10. "ten_bo": tên ngắn không dấu, chữ thường, nối bằng gạch dưới (vd. "vang_mau_don"). "tieu_de": tên tiếng Việt có dấu.

CHỈ TRẢ VỀ DUY NHẤT một khối JSON đúng mẫu sau, không giải thích gì thêm:
{{
  "ten_bo": "...",
  "tieu_de": "...",
  "style": "...",
  "background_desc": "...",
  "palette": ["#......", "#......", "#......"],
  "ornament_colors": ["#......", "#......", "#......"],
  "text_colors": ["#......", "#......", "#......"],
  "script_font": "imperial",
  "reference_prompt": "...",
  "assets": {{
    {example}
  }}
}}
"""
