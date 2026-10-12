"""Danh mục MÓN hoa văn chuẩn – khách tick món muốn làm, hoặc chọn nhanh một gói.

Mỗi món: mã (dùng trong layout), nhãn tiếng Việt, vai trò (quyết định khung prompt),
nhóm hiển thị, và chuỗi món THAY THẾ khi bộ không có món đó – chỉ thay giữa các món
cùng dáng (dải phân cách ↔ dải phân cách, hoa nhỏ ↔ hoa nhỏ). Không có món thay thì
phần tử đó được bỏ qua khi ghép.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Mon:
    id: str
    label: str
    role: str
    group: str
    hint: str
    fallback: tuple = field(default_factory=tuple)


GROUPS = {"bat_buoc": "Bắt buộc", "co_ban": "Cơ bản", "them": "Thêm", "chi_tiet": "Chi tiết nhỏ"}

CATALOG: list[Mon] = [
    Mon("nen", "Nền giấy", "background", "bat_buoc", "phủ kín thiệp, không hoa văn, không chữ"),
    Mon("goc", "Góc thiệp", "corner", "co_ban", "vẽ 1 góc trên-trái, tool tự lật ra 4 góc"),
    Mon("khung", "Khung chữ lồng (bìa)", "crest", "co_ban", "khung lớn, rỗng giữa để đặt chữ lồng"),
    Mon("div_dai", "Dải phân cách dài", "divider", "co_ban", "nét dài mảnh, hoạ tiết nhỏ ở giữa"),
    Mon("hoa_nho", "Hoa văn nhỏ", "fleuron", "co_ban", "hoạ tiết nhỏ dùng điểm xuyết nhiều chỗ",
        ("hoa_giua", "mat_day", "hoa_cuoi")),
    Mon("nhanh", "Nhành lá cạnh thiệp", "sprig", "them", "nhành dọc mép trái, tool lật sang phải"),
    Mon("div_tren", "Dải phân cách ngắn", "divider_small", "them", "ngắn, gọn", ("div_dai",)),
    Mon("vuong_mien", "Hoa văn đầu thiệp (ngang)", "header", "them", "dải hoa văn lớn trên cùng thiệp"),
    Mon("div_hoa", "Dải hoa văn đầu cột", "divider_ornate", "them", "dải trang trí cầu kỳ trên tiêu đề cột",
        ("div_dai",)),
    Mon("khung_va", "Khung nhỏ chữ 'và'", "frame_small", "them", "khung nhỏ dựng đứng, rỗng giữa"),
    Mon("hoa_cuoi", "Hoa văn cuối thiệp", "ornament", "them", "kết thúc phía dưới thiệp", ("hoa_nho",)),
    Mon("la_va", "Nhành lá nhỏ cạnh chữ 'và'", "sprig_small", "chi_tiet", "nhành nhỏ nằm ngang", ("hoa_nho",)),
    Mon("div_duoi", "Dải phân cách vừa", "divider", "chi_tiet", "dài vừa", ("div_dai", "div_tren")),
    Mon("div_tieude", "Dải phân cách tiêu đề", "divider_ornate", "chi_tiet", "trên/dưới tiêu đề lớn",
        ("div_hoa", "div_dai")),
    Mon("div_mini", "Dải phân cách mini", "divider_small", "chi_tiet", "rất ngắn", ("div_tren", "div_dai")),
    Mon("div_cuoi", "Dải phân cách cuối", "divider_ornate", "chi_tiet", "phía dưới hai tên",
        ("div_hoa", "div_dai")),
    Mon("mat_day", "Mặt dây đầu trục", "pendant", "chi_tiet", "hoạ tiết dọc nhỏ ở đầu trục giữa", ("hoa_nho",)),
    Mon("hoa_giua", "Hoa nhỏ giữa hai tên", "fleuron", "chi_tiet", "hoạ tiết rất nhỏ", ("hoa_nho",)),
    Mon("vong_hoa", "Vòng hoa quanh tên", "wreath", "them", "vòng hoa tròn, rỗng giữa để đặt tên"),
    Mon("vom_hoa", "Vòm hoa", "arch_floral", "them", "hoa lá chạy theo đường vòm cổng", ("vuong_mien",)),
    Mon("bo_hoa", "Bó hoa góc", "bouquet", "them", "cụm hoa lớn toả chéo từ góc trên-trái", ("goc",)),
    Mon("day_hoa", "Dải hoa dọc", "garland", "them", "dải hoa lá dài cho mép trái, tool lật sang phải", ("nhanh",)),
]

BY_ID: dict[str, Mon] = {m.id: m for m in CATALOG}

PRESETS: dict[str, dict] = {
    "toi_gian": {"label": "Tối giản (5 món)", "ids": ["nen", "goc", "khung", "div_dai", "hoa_nho"]},
    "tieu_chuan": {"label": "Tiêu chuẩn (10 món)",
                   "ids": ["nen", "goc", "khung", "div_dai", "hoa_nho", "nhanh", "div_tren", "vuong_mien",
                           "div_hoa", "khung_va"]},
    "day_du": {"label": f"Đầy đủ ({len(CATALOG)} món)", "ids": [m.id for m in CATALOG]},
}


def resolve(asset: str, have: set[str], aliases: dict | None = None) -> str | None:
    """Món thực sự dùng cho `asset` khi bộ chỉ có các món `have` (None = bỏ qua phần tử)."""
    if asset in have:
        return asset
    chain = list((aliases or {}).get(asset, [])) if isinstance((aliases or {}).get(asset), list) \
        else ([aliases[asset]] if aliases and asset in aliases else [])
    chain += list(BY_ID[asset].fallback) if asset in BY_ID else []
    seen = {asset}
    while chain:
        cand = chain.pop(0)
        if cand in seen:
            continue
        seen.add(cand)
        if cand in have:
            return cand
        if cand in BY_ID:
            chain += list(BY_ID[cand].fallback)
    return None
