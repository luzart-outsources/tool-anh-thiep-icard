"""Đọc & kiểm tra kit.json (bộ asset + phong cách) và layout (bố cục một loại thiệp)."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


class ConfigError(ValueError):
    pass


def load_json(path: Path) -> dict:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ConfigError(f"Không tìm thấy file: {path}") from None
    except json.JSONDecodeError as e:
        raise ConfigError(f"Lỗi cú pháp JSON trong {Path(path).name}, dòng {e.lineno} cột {e.colno}: {e.msg}") from None


@dataclass
class Project:
    root: Path

    @property
    def kits_dir(self) -> Path:
        return self.root / "kits"

    @property
    def layouts_dir(self) -> Path:
        return self.root / "layouts"

    @property
    def output_dir(self) -> Path:
        return self.root / "output"

    def kit(self, name: str) -> "Kit":
        d = self.kits_dir / name
        if not (d / "kit.json").exists():
            have = ", ".join(sorted(p.name for p in self.kits_dir.glob("*") if (p / "kit.json").exists())) or "(chưa có)"
            raise ConfigError(f"Không có kit '{name}'. Các kit hiện có: {have}")
        return Kit(name, d, self.root, load_json(d / "kit.json"))

    def layout(self, name: str) -> "Layout":
        p = Path(name)
        if not p.suffix:
            p = self.layouts_dir / f"{name}.json"
        elif not p.is_absolute() and not p.exists():
            p = self.layouts_dir / p.name
        if not p.exists():
            have = ", ".join(sorted(q.stem for q in self.layouts_dir.glob("*.json"))) or "(chưa có)"
            raise ConfigError(f"Không có layout '{name}'. Các layout hiện có: {have}")
        return Layout(p.stem, p, load_json(p))

    def layout_for(self, kit: "Kit", name: str) -> "Layout":
        """Bố cục riêng của mẫu (thiệp do bản thiết kế tạo, kits/<mẫu>/layouts/) trước, rồi thư viện chung."""
        p = kit.layouts_dir / f"{name}.json"
        if p.exists():
            return Layout(name, p, load_json(p))
        return self.layout(name)


@dataclass
class Kit:
    name: str
    dir: Path
    root: Path
    data: dict

    @property
    def raw_dir(self) -> Path:
        return self.dir / "raw"

    @property
    def assets_dir(self) -> Path:
        return self.dir / "assets"

    @property
    def layouts_dir(self) -> Path:
        return self.dir / "layouts"

    @property
    def assets(self) -> dict:
        return self.data.get("assets", {})

    @property
    def fills(self) -> dict:
        return self.data.get("fills", {})

    @property
    def text_styles(self) -> dict:
        return self.data.get("text_styles", {})

    def have_assets(self) -> set[str]:
        return {p.stem for p in self.assets_dir.glob("*.png")} if self.assets_dir.exists() else set()

    def resolve_asset(self, name: str) -> str | None:
        """Món thực dùng cho `name`: chính nó, hoặc món thay thế cùng dáng; None = bỏ qua."""
        from .catalog import resolve
        return resolve(name, self.have_assets(), self.data.get("alias"))

    def asset_path(self, name: str) -> Path:
        p = self.assets_dir / f"{name}.png"
        if not p.exists():
            hint = " (đã có ảnh trong raw/ – hãy chạy lệnh ingest)" if any(self.raw_dir.glob(f"{name}.*")) else ""
            raise ConfigError(f"Kit '{self.name}' chưa có asset '{name}'{hint}.")
        return p

    def font_path(self, key: str) -> Path:
        fonts = self.data.get("fonts", {})
        if key not in fonts:                       # ô chữ chọn font riêng (id trong thư viện font)
            from .fontlib import font_file
            p = font_file(self.root, key)
            if p is None:
                raise ConfigError(f"Kit '{self.name}' chưa khai báo font '{key}' trong mục \"fonts\".")
            return p
        p = Path(fonts[key])
        p = p if p.is_absolute() else self.root / p
        if not p.exists():
            raise ConfigError(f"Không tìm thấy file font: {p}")
        return p

    def resolve(self, rel: str) -> Path:
        p = Path(rel)
        if p.is_absolute():
            return p
        return (self.dir / p) if (self.dir / p).exists() else self.root / p

    def fill(self, name_or_spec):
        if isinstance(name_or_spec, dict):
            return name_or_spec
        if isinstance(name_or_spec, str) and name_or_spec.startswith("#"):
            return {"type": "color", "color": name_or_spec}
        if name_or_spec not in self.fills:
            raise ConfigError(f"Kit '{self.name}' không có kiểu tô (fill) '{name_or_spec}'.")
        spec = self.fills[name_or_spec]
        return {"type": "color", "color": spec} if isinstance(spec, str) else spec


@dataclass
class Layout:
    name: str
    path: Path
    data: dict

    @property
    def size(self) -> tuple[int, int]:
        c = self.data.get("canvas", {})
        return int(c.get("w", 1748)), int(c.get("h", 2480))

    @property
    def ornaments(self) -> list:
        return self.data.get("ornaments", [])

    @property
    def texts(self) -> list:
        return self.data.get("texts", [])


ANCHORS = {"tl": (0, 0), "tc": (.5, 0), "tr": (1, 0), "cl": (0, .5), "c": (.5, .5),
           "cr": (1, .5), "bl": (0, 1), "bc": (.5, 1), "br": (1, 1)}


def validate(kit: Kit, layout: Layout) -> list[str]:
    """Trả về danh sách lỗi dễ hiểu (rỗng = hợp lệ)."""
    errs = []
    ids = set()
    for i, el in enumerate(layout.ornaments):
        where = f"ornaments[{i}]" + (f" ('{el['id']}')" if "id" in el else "")
        t = el.get("type", "asset")
        if t not in ("asset", "rule", "border"):
            errs.append(f"{where}: type '{t}' không hợp lệ (asset | rule | border).")
            continue
        if t == "asset":
            if "asset" not in el:
                errs.append(f"{where}: thiếu 'asset'.")
            # Bộ thiếu món KHÔNG phải lỗi: khi ghép sẽ dùng món thay thế hoặc bỏ qua (xem asset_notes).
            if not ("w" in el or "h" in el):
                errs.append(f"{where}: cần 'w' hoặc 'h' (kích thước hiển thị).")
            if el.get("anchor", "c") not in ANCHORS:
                errs.append(f"{where}: anchor '{el.get('anchor')}' không hợp lệ ({', '.join(ANCHORS)}).")
        if t in ("rule", "border"):
            try:
                kit.fill(el.get("fill", "gold"))
            except ConfigError as e:
                errs.append(f"{where}: {e}")
        if "id" in el:
            if el["id"] in ids:
                errs.append(f"{where}: id '{el['id']}' bị trùng.")
            ids.add(el["id"])
    for i, tx in enumerate(layout.texts):
        where = f"texts[{i}]" + (f" ('{tx['id']}')" if "id" in tx else "")
        if "id" not in tx:
            errs.append(f"{where}: thiếu 'id'.")
        style = tx.get("style")
        if style not in kit.text_styles:
            errs.append(f"{where}: kit không có text_style '{style}'.")
        for k in ("cx", "cy", "w"):
            if k not in tx:
                errs.append(f"{where}: thiếu '{k}'.")
    for name, st in kit.text_styles.items():
        try:
            kit.font_path(st.get("font", ""))
            kit.fill(st.get("fill", "gold"))
        except ConfigError as e:
            errs.append(f"text_styles.{name}: {e}")
    return errs


def asset_notes(kit: Kit, layout: Layout) -> tuple[list[dict], list[str]]:
    """Danh sách ornaments đã thay món (cho bộ thiếu món) + ghi chú dễ hiểu."""
    out, notes, seen = [], [], set()
    for el in layout.ornaments:
        if el.get("type", "asset") != "asset" or "asset" not in el:
            out.append(el)
            continue
        real = kit.resolve_asset(el["asset"])
        key = (el["asset"], real)
        if real is None:
            if key not in seen:
                notes.append(f"Mẫu '{kit.name}' không có món '{el['asset']}' (cũng không có món thay) → bỏ qua.")
            seen.add(key)
            continue
        if real != el["asset"]:
            if key not in seen:
                notes.append(f"Mẫu '{kit.name}' không có món '{el['asset']}' → dùng '{real}' thay.")
            seen.add(key)
            el = {**el, "asset": real, "id": el.get("id") or el["asset"]}
        out.append(el)
    return out, notes
