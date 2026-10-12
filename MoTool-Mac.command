#!/bin/bash
# Bấm đúp để mở Bàn làm việc thiệp trên macOS. Cửa sổ Terminal này phải để mở trong lúc dùng tool.
# Không bấm đúp được (báo không có quyền)? Mở Terminal, gõ:  bash ~/ThiepTool/MoTool-Mac.command
{ cd "$(dirname "$0")" && exec /bin/bash "./release/app/run.sh" "$@"; exit; }
