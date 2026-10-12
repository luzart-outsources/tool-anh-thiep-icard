"""Sinh thư viện bố cục (layouts/*.json) – chạy lại được bất cứ lúc nào.

Khung thiết kế A5 1748×2480; mọi khổ khác được giãn tự động khi xuất.
Bìa và Gia đình (dựng từ thiệp mẫu) chỉ được bổ sung thông tin hình dáng, không bị ghi đè.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CX = 874
RECT = ["chu_nhat", "bo_goc", "goc_lom", "cat_goc", "rang_cua"]
ALL = RECT + ["vom", "oval"]


def asset(id_, a, x, y, w, h, anchor="c", **kw):
    return {"id": id_, "asset": a, "x": x, "y": y, "w": w, "h": h, "anchor": anchor, **kw}


def border(lines, fill="gold_line"):
    return {"id": "vien", "type": "border", "fill": fill, "lines": [{"inset": i, "width": w} for i, w in lines]}


def text(id_, label, style, txt, cy, w, size, **kw):
    return {"id": id_, "label": label, "style": style, "text": txt, "cx": kw.pop("cx", CX), "cy": cy, "w": w,
            "size": size, **kw}


def names(top, gap, size, w=1150, va_size=110):
    return [text("ten_1", "Tên chú rể", "script", "Gia Minh", top, w, size, group="ten"),
            text("va", "Chữ nối ('và')", "script", "và", top + gap, 220, va_size),
            text("ten_2", "Tên cô dâu", "script", "Ái Ngọc", top + 2 * gap, w, size, group="ten")]


GOC4 = asset("goc", "goc", 63, 70, 313.4, 500.8, "tl", mirror="xy")
GOC_DUOI = asset("goc_duoi", "goc", 63, 2410, 313.4, 500.8, "bl", flip="v", mirror="x")
VIEN3 = border([(32.3, 5), (55.6, 4), (82.1, 3)])

LAYOUTS = {
    "vom_hoa": {
        "title": "Vòm hoa", "mo_ta": "Thiệp hình vòm, hoa lá chạy theo đường vòm, tên ở giữa",
        "shapes": ["vom", "chu_nhat", "bo_goc", "goc_lom"], "shape_default": "vom", "key_items": ["vom_hoa"],
        "ornaments": [border([(34, 5), (58, 3)]),
                      asset("vom_hoa", "vom_hoa", CX, 560, 1500, 900),
                      GOC_DUOI,
                      asset("div_tren", "div_tren", CX, 1175, 440, 52),
                      asset("div_dai", "div_dai", CX, 1925, 620, 70),
                      asset("hoa_cuoi", "hoa_cuoi", CX, 2300, 280, 110)],
        "texts": [text("tieu_de", "Tiêu đề bìa", "caps", "THIỆP THÀNH HÔN", 1090, 1000, 80),
                  *names(1390, 175, 250),
                  text("loi_moi", "Lời báo tin", "caps_wide", "TRÂN TRỌNG BÁO TIN LỄ THÀNH HÔN", 2040, 1050, 38),
                  text("ngay", "Ngày cưới", "caps_wide", "15 . 12 . 2026", 2170, 700, 64)]},
    "toi_gian": {
        "title": "Tối giản", "mo_ta": "Ít hoa văn, nhiều khoảng trống, chữ là điểm nhấn",
        "shapes": ALL, "shape_default": "chu_nhat", "key_items": ["hoa_nho"],
        "ornaments": [border([(70, 3)]),
                      asset("hoa_tren", "hoa_nho", CX, 430, 230, 230),
                      asset("div_tren", "div_tren", CX, 820, 420, 50),
                      asset("div_duoi", "div_tren", CX, 1720, 420, 50, flip="v"),
                      asset("hoa_duoi", "hoa_nho", CX, 2140, 170, 170, flip="v")],
        "texts": [text("tieu_de", "Tiêu đề bìa", "caps_wide", "THIỆP THÀNH HÔN", 700, 1000, 56),
                  *names(1090, 185, 270),
                  text("loi_moi", "Lời báo tin", "caps_wide", "TRÂN TRỌNG BÁO TIN LỄ THÀNH HÔN", 1840, 1050, 36),
                  text("ngay", "Ngày cưới", "caps_wide", "15 . 12 . 2026", 1975, 700, 62)]},
    "goc_cheo": {
        "title": "Hoa góc chéo", "mo_ta": "Bất đối xứng: hoa ở góc trên-trái và dưới-phải",
        "shapes": RECT + ["oval"], "shape_default": "chu_nhat", "key_items": ["bo_hoa"],
        "ornaments": [border([(40, 3), (56, 2)]),
                      asset("hoa_tl", "bo_hoa", 0, 0, 960, 960, "tl"),
                      asset("hoa_br", "bo_hoa", 1748, 2480, 960, 960, "br", flip="hv"),
                      asset("div_tren", "div_tren", CX, 1130, 440, 52),
                      asset("div_dai", "div_dai", CX, 1840, 600, 66)],
        "texts": [text("tieu_de", "Tiêu đề bìa", "caps", "THIỆP THÀNH HÔN", 1040, 1000, 76),
                  *names(1300, 170, 240, w=1000),
                  text("loi_moi", "Lời báo tin", "caps_wide", "TRÂN TRỌNG BÁO TIN LỄ THÀNH HÔN", 1950, 1000, 36),
                  text("ngay", "Ngày cưới", "caps_wide", "15 . 12 . 2026", 2075, 650, 60)]},
    "hai_ben": {
        "title": "Hoa hai bên", "mo_ta": "Dải hoa chạy dọc hai mép, nội dung ở giữa",
        "shapes": RECT, "shape_default": "bo_goc", "key_items": ["day_hoa"],
        "ornaments": [border([(34, 4), (52, 2)]),
                      asset("day_hoa", "day_hoa", 70, 1240, 330, 1900, "cl", mirror="x"),
                      asset("hoa_tren", "hoa_nho", CX, 380, 200, 200),
                      asset("div_tren", "div_tren", CX, 735, 400, 50),
                      asset("div_dai", "div_dai", CX, 1600, 560, 64),
                      asset("hoa_cuoi", "hoa_cuoi", CX, 2110, 300, 120)],
        "texts": [text("tieu_de", "Tiêu đề bìa", "caps", "THIỆP THÀNH HÔN", 625, 900, 74),
                  *names(1000, 175, 235, w=900),
                  text("loi_moi", "Lời báo tin", "caps_wide", "TRÂN TRỌNG BÁO TIN LỄ THÀNH HÔN", 1720, 900, 34),
                  text("ngay", "Ngày cưới", "caps_wide", "15 . 12 . 2026", 1855, 600, 58)]},
    "vong_hoa": {
        "title": "Vòng hoa quanh tên", "mo_ta": "Tên cô dâu chú rể nằm trong vòng hoa tròn",
        "shapes": ALL, "shape_default": "oval", "key_items": ["vong_hoa"],
        "ornaments": [border([(40, 4), (60, 2)]),
                      asset("vong_hoa", "vong_hoa", CX, 1250, 1380, 1380),
                      asset("div_tren", "div_tren", CX, 455, 420, 50),
                      asset("div_duoi", "div_tren", CX, 2010, 420, 50, flip="v")],
        "texts": [text("tieu_de", "Tiêu đề bìa", "caps", "THIỆP THÀNH HÔN", 365, 900, 70),
                  text("ten_1", "Tên chú rể", "script", "Gia Minh", 1130, 760, 200, group="ten"),
                  text("va", "Chữ nối ('và')", "script", "và", 1265, 200, 96),
                  text("ten_2", "Tên cô dâu", "script", "Ái Ngọc", 1400, 760, 200, group="ten"),
                  text("loi_moi", "Lời báo tin", "caps_wide", "TRÂN TRỌNG BÁO TIN LỄ THÀNH HÔN", 2110, 1000, 36),
                  text("ngay", "Ngày cưới", "caps_wide", "15 . 12 . 2026", 2230, 650, 58)]},
    "thiep_moi": {
        "title": "Thiệp mời", "mo_ta": "Mời khách: tên khách, giờ, ngày, địa điểm (theo thiệp mẫu 3)",
        "shapes": RECT, "shape_default": "chu_nhat", "key_items": ["vuong_mien"],
        "ornaments": [VIEN3, GOC4,
                      asset("vuong_mien", "vuong_mien", CX, 265, 800, 330),
                      asset("div_1", "div_tren", CX, 590, 400, 46),
                      asset("div_2", "div_tren", CX, 735, 400, 46),
                      asset("la_va", "la_va", 735, 1219, 90, 43, mirror="x"),
                      asset("div_3", "div_dai", CX, 1555, 560, 64),
                      asset("div_4", "div_tren", CX, 1795, 400, 46),
                      asset("div_5", "div_tren", CX, 2045, 400, 46),
                      asset("hoa_cuoi", "hoa_cuoi", CX, 2320, 260, 100)],
        "texts": [text("kinh_moi", "Lời mời", "caps_wide", "TRÂN TRỌNG KÍNH MỜI", 514, 1000, 46),
                  text("khach", "Tên khách mời", "body", "Ông/Bà: ......................................", 660, 1150, 64),
                  text("toi_du", "Câu dẫn", "body", "Tới dự lễ thành hôn của", 812, 1000, 62, italic=True),
                  *names(1030, 185, 240, w=1100),
                  text("gio", "Giờ", "body", "Vào lúc: 11 giờ 00", 1640, 1000, 64),
                  text("ngay_day_du", "Ngày (đầy đủ)", "body", "Thứ Bảy, ngày 26 tháng 12 năm 2026", 1724, 1150, 60),
                  text("dia_diem", "Địa điểm", "body", "Tại: Trung tâm Hội nghị Golden Palace", 1880, 1200, 62),
                  text("dia_chi", "Địa chỉ", "body", "125 Nguyễn Huệ, Quận 1, TP. Hồ Chí Minh", 1958, 1200, 56),
                  text("loi_cuoi", "Lời cuối", "body",
                       "Sự hiện diện của Quý khách là\nniềm vinh hạnh cho gia đình chúng tôi", 2160, 1150, 54,
                       italic=True)]},
    "cam_on": {
        "title": "Cảm ơn", "mo_ta": "Trang cuối bộ thiệp online: lời cảm ơn khách, tên hai bạn, With love",
        "shapes": RECT, "shape_default": "chu_nhat", "key_items": ["goc"],
        "ornaments": [VIEN3, GOC4,
                      asset("vuong_mien", "vuong_mien", CX, 300, 760, 320),
                      asset("div_tieude", "div_tieude", CX, 960, 760, 64),
                      asset("div_tren", "div_tren", CX, 1440, 400, 46),
                      asset("hoa_giua", "hoa_giua", CX, 1660, 80, 110),
                      asset("div_dai", "div_dai", CX, 1890, 560, 64),
                      asset("hoa_cuoi", "hoa_cuoi", CX, 2290, 280, 110)],
        "texts": [text("cam_on", "Tiêu đề cảm ơn", "caps", "THANK YOU", 790, 1300, 170),
                  text("loi_cam_on", "Lời cảm ơn", "body",
                       "Chân thành cảm ơn Quý khách\nđã dành thời gian quý báu\nđến chung vui cùng gia đình chúng tôi",
                       1200, 1250, 62, italic=True),
                  text("ten_1", "Tên chú rể", "script", "Gia Minh", 1660, 560, 160, cx=CX - 380, align="right",
                       group="ten"),
                  text("ten_2", "Tên cô dâu", "script", "Ái Ngọc", 1660, 560, 160, cx=CX + 380, align="left",
                       group="ten"),
                  text("with_love", "Lời kết", "caps_wide", "WITH LOVE", 2030, 700, 44)]},
}

EXTRA = {"bia": {"title": "Khung chữ lồng", "mo_ta": "Khung chữ lồng lớn phía trên, tên ở giữa (theo thiệp mẫu 1)",
                 "shapes": RECT, "shape_default": "chu_nhat", "key_items": ["khung"]},
         "gia_dinh": {"title": "Thông tin hai gia đình", "mo_ta": "Bố mẹ, địa chỉ hai bên nhà trai – nhà gái (theo thiệp mẫu 2)",
                      "shapes": RECT, "shape_default": "chu_nhat", "key_items": ["vuong_mien", "khung_va"]}}

if __name__ == "__main__":
    out = ROOT / "layouts"
    for name, d in LAYOUTS.items():
        d = {"title": d["title"], "mo_ta": d["mo_ta"], "canvas": {"w": 1748, "h": 2480}, **{k: v for k, v in d.items() if k not in ("title", "mo_ta")}}
        (out / f"{name}.json").write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
        print("ghi", name)
    for name, extra in EXTRA.items():
        p = out / f"{name}.json"
        d = json.loads(p.read_text(encoding="utf-8"))
        d.update(extra)
        p.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
        print("cập nhật", name)
