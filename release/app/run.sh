#!/bin/bash
# Bàn làm việc thiệp – khởi động trên macOS (gọi từ "MoTool-Mac.command" trong repo git,
# hoặc "Mở Tool (Mac).command" trong gói zip).
# Lần đầu: tải bộ chạy uv → Python 3.12 + thư viện vào ~/Library/Application Support/ThiepTool (không đụng hệ thống).
# Dữ liệu của khách: ~/Documents/ThiepTool – nằm ngoài thư mục tool nên cập nhật bản mới không mất gì.
# Tương thích bash 3.2 (bash mặc định của macOS).
# Toàn bộ nằm trong main(): bash đọc hết hàm rồi mới chạy → "git pull" đổi chính file này giữa chừng vẫn an toàn.

main() {
  local HERE ROOT RT DATA UV PY REQ STAMP OLD NEW
  HERE="$(cd "$(dirname "$0")" && pwd)"
  if [ -d "$HERE/../../cardkit" ]; then        # repo git: <repo>/release/app/run.sh
    ROOT="$(cd "$HERE/../.." && pwd)"
  else                                          # gói zip: ThiepTool/app/run.sh (cardkit nằm cạnh)
    ROOT="$HERE"
  fi
  REQ="$HERE/requirements-app.txt"
  if [ "$(uname)" = "Darwin" ]; then
    RT="$HOME/Library/Application Support/ThiepTool"
  else
    RT="${XDG_DATA_HOME:-$HOME/.local/share}/ThiepTool"
  fi
  DATA="$HOME/Documents/ThiepTool"
  UV="$RT/uv/uv"
  PY="$RT/venv/bin/python"
  export UV_PYTHON_INSTALL_DIR="$RT/python" UV_CACHE_DIR="$RT/cache" PLAYWRIGHT_BROWSERS_PATH="$RT/browsers"
  if [ -n "$THIEPTOOL_PRINT_PATHS" ]; then      # dùng khi kiểm thử: chỉ in đường dẫn
    printf '%s\n%s\n' "$ROOT" "$REQ"
    return 0
  fi

  clear 2>/dev/null
  printf '\n  ✦ BÀN LÀM VIỆC THIỆP\n  ────────────────────\n'

  # Bản cài bằng git: tự lấy bản mới (không hỏi mật khẩu, lỗi mạng thì bỏ qua)
  if [ -d "$ROOT/.git" ] && command -v git >/dev/null 2>&1; then
    printf '  Đang kiểm tra bản mới…\n'
    OLD="$(git -C "$ROOT" rev-parse HEAD 2>/dev/null)"
    if GIT_TERMINAL_PROMPT=0 git -C "$ROOT" -c http.lowSpeedLimit=1000 -c http.lowSpeedTime=20 \
         pull --ff-only --quiet >/dev/null 2>&1; then
      NEW="$(git -C "$ROOT" rev-parse HEAD 2>/dev/null)"
      [ "$OLD" != "$NEW" ] && printf '  ✓ Đã cập nhật lên bản mới.\n'
    else
      printf '  (Chưa lấy được bản mới – vẫn mở bản đang có.)\n'
    fi
    chmod +x "$ROOT/MoTool-Mac.command" 2>/dev/null    # tải zip từ web có thể mất quyền chạy
  fi

  mkdir -p "$RT" "$DATA" || fail "Không tạo được thư mục $RT"

  if [ ! -x "$UV" ]; then
    printf '  Lần đầu mở trên máy này: đang tải bộ chạy (cần mạng, khoảng 3–5 phút)…\n'
    command -v curl >/dev/null 2>&1 || fail "Máy thiếu lệnh curl."
    curl -LsSf https://astral.sh/uv/install.sh | env UV_UNMANAGED_INSTALL="$RT/uv" sh >/dev/null 2>&1 \
      || fail "Không tải được bộ chạy – kiểm tra mạng rồi mở lại."
    [ -x "$UV" ] || fail "Tải bộ chạy chưa xong – kiểm tra mạng rồi mở lại."
  fi

  STAMP="$RT/venv/.ok-$(cksum < "$REQ" | cut -d' ' -f1)"
  if [ ! -x "$PY" ] || [ ! -f "$STAMP" ]; then
    printf '  Đang cài thư viện (chỉ lần đầu hoặc khi có bản mới)…\n'
    "$UV" venv --quiet --allow-existing --python 3.12 "$RT/venv" || fail "Không cài được Python."
    "$UV" pip install --quiet --python "$PY" -r "$REQ" || fail "Không cài được thư viện – kiểm tra mạng rồi mở lại."
    rm -f "$RT"/venv/.ok-*
    touch "$STAMP"
  fi

  cd "$ROOT" || fail "Không mở được thư mục tool."
  "$PY" -m cardkit.launch --data "$DATA" "$@" || fail "Tool dừng vì lỗi."
}

fail() {
  printf '\n  ✗ %s\n\n  Chụp màn hình cửa sổ này gửi người bán tool để được hỗ trợ.\n  Bấm Enter để đóng.\n' "$1"
  read -r _
  exit 1
}

main "$@"
exit $?
