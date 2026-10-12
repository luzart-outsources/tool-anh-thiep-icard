"""Kế hoạch vẽ cho một mẫu thiệp: gộp món thành TỜ + soạn kịch bản tin nhắn cho MỘT chat ChatGPT.

- Món lớn (khung chữ lồng, hoa văn đầu thiệp) và nền giấy: mỗi món một ảnh – cần nét khi in.
- Dải phân cách (dài, dẹt): tối đa 4 dải một tờ, mỗi dải một hàng – mỗi dải vẫn rộng ~1000px.
- Món cao/nhỏ (góc, nhành, khung nhỏ, hoạ tiết): tối đa 4 món một tờ.
Thứ tự món trên tờ (trên→dưới, trái→phải) chính là thứ tự tool dùng để gán tên khi cắt.
"""
from __future__ import annotations

from .catalog import BY_ID

SHAPE = {"nen": "bg", "khung": "big", "vuong_mien": "big",
         "goc": "tall", "nhanh": "tall", "khung_va": "tall",
         "div_dai": "wide", "div_tren": "wide", "div_hoa": "wide", "div_duoi": "wide",
         "div_tieude": "wide", "div_mini": "wide", "div_cuoi": "wide",
         "hoa_nho": "small", "la_va": "small", "mat_day": "small", "hoa_giua": "small", "hoa_cuoi": "small",
         "vong_hoa": "big", "vom_hoa": "big", "bo_hoa": "big", "day_hoa": "tall"}

VI = {
    "nen": "nền giấy phủ kín toàn bộ ảnh – chỉ có chất giấy và hoạ tiết chìm thật nhạt, không hoa văn nổi, "
           "không viền, không chữ",
    "khung": "khung chữ lồng lớn, đối xứng trái–phải, bên trong ĐỂ TRỐNG hoàn toàn (không chữ, không chữ lồng)",
    "vuong_mien": "hoa văn lớn nằm ngang đặt trên đầu thiệp, đối xứng trái–phải, rộng hơn nhiều so với cao, đáy phẳng",
    "goc": "góc thiệp cho góc TRÊN-TRÁI: hai nhánh hoa văn chạy dọc mép trên và dọc mép trái, tạo hình chữ L",
    "nhanh": "nhành dọc mảnh cho mép TRÁI thiệp, mọc từ dưới lên, cao và hẹp",
    "khung_va": "khung nhỏ dựng đứng, đối xứng, bên trong để trống",
    "div_dai": "dải phân cách DÀI: nét mảnh nằm ngang, hoạ tiết nhỏ ở giữa, đối xứng",
    "div_tren": "dải phân cách NGẮN, gọn, đối xứng",
    "div_hoa": "dải hoa văn cầu kỳ đặt trên tiêu đề: hoạ tiết lớn ở giữa, nét mảnh kéo sang hai bên",
    "div_duoi": "dải phân cách dài vừa, đối xứng",
    "div_tieude": "dải phân cách mảnh dưới tiêu đề lớn, hoạ tiết nhỏ ở giữa",
    "div_mini": "dải phân cách rất ngắn",
    "div_cuoi": "dải phân cách cuối thiệp, hoạ tiết ở giữa, đối xứng",
    "hoa_nho": "hoạ tiết nhỏ đối xứng kiểu fleuron, dùng điểm xuyết",
    "la_va": "nhành lá nhỏ nằm ngang, hướng sang PHẢI",
    "mat_day": "hoạ tiết dọc nhỏ, hướng LÊN, đối xứng",
    "hoa_giua": "hoạ tiết rất nhỏ, đối xứng",
    "hoa_cuoi": "hoa văn kết thúc phía dưới thiệp, đối xứng, rộng hơn cao",
    "vong_hoa": "vòng hoa tròn khép kín, bên trong ĐỂ TRỐNG hoàn toàn để đặt tên, cân đối",
    "vom_hoa": "vòm hoa hình cổng: hoa lá chạy theo nửa trên hình tròn (chữ U úp ngược), bên trong để trống, đối xứng",
    "bo_hoa": "cụm hoa lớn cho góc TRÊN-TRÁI thiệp, toả chéo vào giữa, tự nhiên, bất đối xứng",
    "day_hoa": "dải hoa lá dọc dài cho mép TRÁI thiệp, cao và hẹp",
}

ORDER = ["khung", "vuong_mien", "vong_hoa", "vom_hoa", "bo_hoa", "goc", "day_hoa", "nhanh", "khung_va", "hoa_nho", "la_va", "mat_day", "hoa_giua",
         "hoa_cuoi", "div_dai", "div_tren", "div_hoa", "div_duoi", "div_tieude", "div_mini", "div_cuoi", "nen"]


def _chunks(xs, n):
    return [xs[i:i + n] for i in range(0, len(xs), n)]


def plan_sheets(ids: list[str], kinds: dict | None = None, ratios: dict | None = None,
                with_bg: bool = True, bg_ratio: str = "dọc 2:3", start: int = 1) -> list[dict]:
    """Danh sách tờ cần vẽ. Mỗi tờ: id, kind (bg|single|rows|row|grid), items (thứ tự = thứ tự cắt), ratio.

    kinds: dáng của món tự do (big|wide|tall|small) – món trong danh mục chuẩn đã có sẵn dáng.
    ratios: khung ảnh cho món lớn vẽ riêng (vd. "dọc 2:3" cho bó hoa cao).
    """
    kinds = {**SHAPE, **(kinds or {})}
    ids = list(dict.fromkeys(ids))
    if with_bg and "nen" not in ids:
        ids.append("nen")
    ids = sorted(ids, key=lambda i: ORDER.index(i) if i in ORDER else 50)
    big = [i for i in ids if kinds.get(i) == "big"]
    wide = [i for i in ids if kinds.get(i) == "wide"]
    rest = [i for i in ids if kinds.get(i) in ("tall", "small") or (i not in kinds and i != "nen")]
    sheets = [{"kind": "single", "items": [i], "ratio": (ratios or {}).get(i, "ngang 3:2")} for i in big]
    for ch in _chunks(rest, 4):
        sheets.append({"kind": "grid" if len(ch) == 4 else "row", "items": ch, "ratio": "ngang 3:2"})
    for ch in _chunks(wide, 4):
        sheets.append({"kind": "rows", "items": ch, "ratio": "ngang 3:2"})
    if "nen" in ids:
        sheets.append({"kind": "bg", "items": ["nen"], "ratio": bg_ratio})
    for n, sh in enumerate(sheets, start):
        sh["id"] = f"to{n}"
    return sheets


def sheet_title(s: dict, labels: dict | None = None) -> str:
    names = [(labels or {}).get(i) or (BY_ID[i].label if i in BY_ID else i) for i in s["items"]]
    return names[0] if len(names) == 1 else f"Tờ {len(names)} món: " + ", ".join(names)


def _desc(item: str, desc: dict | None) -> str:
    return (desc or {}).get(item) or VI.get(item) or (BY_ID[item].hint if item in BY_ID else item)


def _item_line(k: int, item: str, desc: dict | None = None) -> str:
    return f"{k}) {_desc(item, desc)}"


RULES = """QUY TẮC CHUNG cho mọi ảnh trong cuộc trò chuyện này:
- Mọi ảnh cùng MỘT phong cách, bảng màu, chất liệu và độ chi tiết – như của cùng một nhà thiết kế.
- Mỗi hoa văn đứng riêng, cách nhau thật xa, không chạm nhau, không chạm mép ảnh, lề rộng xung quanh.
- NỀN ẢNH: TRONG SUỐT thật (file PNG có kênh alpha, ngoài hoa văn là trong suốt hoàn toàn). Nếu không xuất
  được nền trong suốt thật thì dùng một màu đặc phẳng duy nhất – xanh dương thuần #0000FF (nếu hoa văn có màu
  xanh dương thì dùng hồng tím thuần #FF00FF). TUYỆT ĐỐI không vẽ ô caro xám-trắng giả làm nền trong suốt.
  Không gradient, không vân, không đổ bóng xuống nền, không để màu nền phản chiếu lên hoa văn. Giữ đúng kiểu
  nền đó cho mọi ảnh sau (riêng ảnh NỀN GIẤY thì không áp dụng).
- Tuyệt đối không có chữ, chữ cái, chữ lồng, số, chữ ký hay watermark.
- Nét sắc, chi tiết rõ, chất lượng in."""


def sheet_request(s: dict, n: int, total: int, desc: dict | None = None) -> str:
    items = s["items"]
    head = f"ẢNH {n}/{total}"
    ratio = s.get("ratio", "ngang 3:2").upper()
    if s["kind"] == "bg":
        return (f"{head}: NỀN GIẤY cho thiệp, khung {ratio}, {_desc('nen', desc)}. Màu và chất giấy hợp với các "
                "hoa văn ở trên. Riêng ảnh này: phủ kín toàn ảnh, KHÔNG trong suốt, KHÔNG dùng nền màu đặc.")
    if s["kind"] == "single":
        return f"{head}: một hoa văn duy nhất, khung {ratio}, đặt giữa ảnh – {_desc(items[0], desc)}."
    lines = "\n".join(_item_line(k, i, desc) for k, i in enumerate(items, 1))
    if s["kind"] == "rows":
        how = f"{len(items)} dải phân cách khác nhau, MỖI DẢI MỘT HÀNG, xếp từ trên xuống theo đúng thứ tự"
    elif s["kind"] == "grid":
        how = "4 hoa văn riêng biệt xếp lưới 2×2, đọc từ trái sang phải rồi trên xuống dưới, theo đúng thứ tự"
    else:
        how = f"{len(items)} hoa văn riêng biệt xếp MỘT HÀNG NGANG từ trái sang phải, theo đúng thứ tự"
    return (f"{head}: một tờ khung NGANG 3:2 gồm {how}:\n{lines}\n"
            f"Đúng {len(items)} hoa văn, không thêm không bớt, khoảng cách giữa các hoa văn thật rộng.")


def chat_messages(idea: str, sheets: list[dict], desc: dict | None = None, design: bool = False) -> list[str]:
    """Kịch bản cho MỘT chat ChatGPT: tin 1 = phong cách + quy tắc + ảnh 1; các tin sau = từng ảnh.

    design=True: chat đã có bản thiết kế JSON ở trên → tin 1 nối tiếp ("giờ vẽ các hoa văn trong bản thiết kế").
    """
    total = len(sheets)
    idea = idea.strip() or "(chưa nhập ý tưởng)"
    msgs = []
    for n, s in enumerate(sheets, 1):
        req = sheet_request(s, n, total, desc)
        if n == 1 and design:
            msgs.append(f"Tuyệt. Giờ hãy VẼ các hoa văn (items) trong bản thiết kế ở trên. Mình sẽ gửi lần lượt {total} "
                        f"yêu cầu vẽ, mỗi yêu cầu bạn vẽ đúng 1 ảnh.\n\nPHONG CÁCH CHUNG:\n{idea}\n\n{RULES}\n\n"
                        f"Bắt đầu với {req}")
        elif n == 1:
            msgs.append(f"Mình cần bạn vẽ bộ hoa văn cho MỘT mẫu thiệp cưới. Mình sẽ gửi lần lượt {total} yêu cầu "
                        f"vẽ trong cuộc trò chuyện này, mỗi yêu cầu bạn vẽ đúng 1 ảnh.\n\n"
                        f"PHONG CÁCH (ý tưởng của mình):\n{idea}\n\n{RULES}\n\n"
                        f"(Nếu mình có đính kèm thiệp mẫu, hãy theo đúng phong cách của thiệp đó.)\n\n"
                        f"Bắt đầu với {req}")
        else:
            msgs.append(f"{req}\nGiữ đúng phong cách, màu sắc và màu nền như các ảnh trước.")
    return msgs


def redo_message(s: dict, n: int, total: int, problem: str, desc: dict | None = None) -> str:
    return (f"Vẽ lại {sheet_request(s, n, total, desc)}\nLưu ý: {problem}. Giữ đúng phong cách và màu nền như các ảnh trước.")
