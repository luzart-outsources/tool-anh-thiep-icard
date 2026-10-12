"""Font cardkit → font trên Icard.

Icard nạp mỗi font bằng MỘT @font-face (tên = Font.name, một file) và vẽ chữ bằng Canvas 2D, nên:
  - font biến thiên được tách thành bản tĩnh đúng độ đậm ô chữ dùng (nếu không trình duyệt hiện độ đậm
    mặc định của file);
  - tính năng OpenType mà kiểu chữ bật (vd. số thẳng hàng lining-nums) được "đóng băng" vào bảng cmap,
    vì Canvas không bật được font-variant-numeric.
Bản xem trước giả lập Icard dùng đúng file font này → khớp thứ Icard vẽ ra.
"""
from __future__ import annotations

import io
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

NUMERIC_TAGS = {"lining-nums": "lnum", "oldstyle-nums": "onum", "tabular-nums": "tnum", "proportional-nums": "pnum"}
TAG_LABEL = {"lnum": "Lining", "onum": "Oldstyle", "tnum": "Tabular", "pnum": "Proportional"}


@dataclass(frozen=True)
class FontNeed:
    """Một font mà mẫu cần có trên Icard."""
    path: Path
    weight: int
    name: str                      # Font.name trên Icard = fontFamily của ô chữ
    category: str                  # Wedding | Uppercase | Vietnamese | General
    features: tuple = ()           # tính năng OpenType đóng băng vào file (vd. ("lnum",))


@lru_cache(maxsize=64)
def font_meta(path: Path) -> dict:
    from fontTools.ttLib import TTFont
    f = TTFont(path, lazy=True)
    name = f["name"]
    upm = f["head"].unitsPerEm
    hhea = f["hhea"]
    axes = {a.axisTag: (a.minValue, a.defaultValue, a.maxValue) for a in f["fvar"].axes} if "fvar" in f else {}
    family = name.getDebugName(16) or name.getDebugName(1) or path.stem
    gsub = {fr.FeatureTag for fr in f["GSUB"].table.FeatureList.FeatureRecord} if "GSUB" in f else set()
    return {"family": family, "axes": axes, "weight_class": f["OS/2"].usWeightClass if "OS/2" in f else 400,
            "ascent": hhea.ascent / upm, "descent": abs(hhea.descent) / upm, "gsub": gsub}


def features_for(path: Path, numeric: str | None) -> tuple:
    """Tính năng cần đóng băng cho ô chữ (theo font-variant-numeric của kiểu chữ) mà font thật sự có."""
    have = font_meta(Path(path))["gsub"]
    return tuple(t for t in (NUMERIC_TAGS.get(v) for v in str(numeric or "").split()) if t and t in have)


def _clamp_weight(meta: dict, weight: int) -> int:
    lo, _, hi = meta["axes"]["wght"]
    return int(round(min(max(weight, lo), hi)))


def icard_font_name(path: Path, weight: int, features: tuple = ()) -> str:
    """Tên ổn định trên Icard: "<họ>[ <độ đậm>][ Lining]" – độ đậm chỉ ghi với font biến thiên."""
    meta = font_meta(Path(path))
    name = meta["family"]
    if "wght" in meta["axes"]:
        name += f" {_clamp_weight(meta, int(weight))}"
    return " ".join([name] + [TAG_LABEL.get(t, t) for t in features])


def css_weight(path: Path, weight: int) -> str:
    """fontWeight cho ô chữ Icard: bản tĩnh đã đúng độ đậm → 'normal'; font tĩnh mảnh được dựng đậm → 'bold'."""
    meta = font_meta(Path(path))
    if "wght" in meta["axes"]:
        return "normal"
    return "bold" if int(weight) >= 600 and meta["weight_class"] < 600 else "normal"


def _freeze(font, tags: tuple) -> None:
    """Áp các phép thay glyph đơn (GSUB loại 1) của `tags` thẳng vào cmap."""
    gsub = font["GSUB"].table
    mapping = {}
    for fr in gsub.FeatureList.FeatureRecord:
        if fr.FeatureTag not in tags:
            continue
        for li in fr.Feature.LookupListIndex:
            lk = gsub.LookupList.Lookup[li]
            for st in lk.SubTable:
                typ = lk.LookupType
                if typ == 7:                                    # lookup mở rộng
                    typ, st = st.ExtensionLookupType, st.ExtSubTable
                if typ == 1:
                    mapping.update(st.mapping)
    for t in font["cmap"].tables:
        if t.isUnicode():
            for cp, g in list(t.cmap.items()):
                if g in mapping:
                    t.cmap[cp] = mapping[g]


@lru_cache(maxsize=16)
def static_font_bytes(path: Path, weight: int, features: tuple = ()) -> bytes:
    """File font đăng lên Icard: font biến thiên → bản tĩnh ở độ đậm đã chọn (trục khác giữ mặc định);
    tính năng `features` đóng băng vào cmap."""
    path = Path(path)
    meta = font_meta(path)
    if not meta["axes"] and not features:
        return path.read_bytes()
    from fontTools.ttLib import TTFont
    font = TTFont(path)
    if meta["axes"]:
        from fontTools.varLib.instancer import instantiateVariableFont
        loc = {tag: default for tag, (_, default, _) in meta["axes"].items()}
        if "wght" in loc:
            loc["wght"] = _clamp_weight(meta, int(weight))
        font = instantiateVariableFont(font, loc, updateFontNames=False)
    if features:
        _freeze(font, tuple(features))
    buf = io.BytesIO()
    font.save(buf)
    return buf.getvalue()


def need_bytes(need: FontNeed) -> bytes:
    return static_font_bytes(Path(need.path), int(need.weight), tuple(need.features))


def icard_category(kind: str | None) -> str:
    """Nhóm font của cardkit (script/serif/sans/deco) → danh mục font Icard."""
    return "Wedding" if kind == "script" else "Vietnamese"
