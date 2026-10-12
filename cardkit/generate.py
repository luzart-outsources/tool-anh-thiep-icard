"""Tạo asset tự động qua OpenAI Images API (giai đoạn 2 của cách làm kết hợp).

Ghi thẳng vào raw/ – các bước sau (ingest, render) giữ nguyên.
Cần biến môi trường OPENAI_API_KEY. Asset hoa văn xin nền trong suốt thật (background=transparent).
"""
from __future__ import annotations

import base64
import os
import time

from .config import ConfigError, Kit
from .prompts import ROLES, build_prompt, role_of

API_URL = "https://api.openai.com/v1/images/generations"


def generate(kit: Kit, names: list[str] | None = None, model: str = "gpt-image-1", quality: str = "high",
             overwrite: bool = False, log=print) -> list[str]:
    import requests

    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        raise ConfigError("Chưa có OPENAI_API_KEY. PowerShell: $env:OPENAI_API_KEY = \"sk-...\"")
    names = names or list(kit.assets)
    kit.raw_dir.mkdir(parents=True, exist_ok=True)
    done = []
    for name in names:
        if name not in kit.assets:
            log(f"  ! '{name}' không có trong kit.json – bỏ qua")
            continue
        out = kit.raw_dir / f"{name}.png"
        if out.exists() and not overwrite:
            log(f"  ⏭ {name}: đã có raw/{name}.png (thêm --overwrite để tạo lại)")
            continue
        a = kit.assets[name]
        is_bg = role_of(kit, name) == "background"
        role = role_of(kit, name)
        body = {"model": model, "prompt": build_prompt(kit, name, "api"), "n": 1,
                "size": ROLES.get(role, ROLES["ornament"])["api_size"], "quality": quality,
                "background": "opaque" if is_bg else "transparent", "output_format": "png"}
        log(f"  … {name} ({body['size']}, {quality})")
        t = time.time()
        r = requests.post(API_URL, headers={"Authorization": f"Bearer {key}"}, json=body, timeout=600)
        if r.status_code != 200:
            try:
                msg = r.json().get("error", {}).get("message", r.text)
            except ValueError:
                msg = r.text
            log(f"  ✗ {name}: HTTP {r.status_code} – {msg[:300]}")
            continue
        out.write_bytes(base64.b64decode(r.json()["data"][0]["b64_json"]))
        log(f"  ✓ {name} → raw/{name}.png ({time.time() - t:.0f}s)")
        done.append(name)
    return done
