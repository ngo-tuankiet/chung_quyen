#!/bin/bash
# macOS: chạy bằng lệnh  bash chay_web.command  trong Terminal (hoặc nhấp đúp). Lần đầu tự cài vnstock.
cd "$(dirname "$0")" || exit 1
dung() { echo; echo "$1"; read -r -p "Nhấn Enter để đóng..."; exit 1; }

echo "[1/3] Tìm Python 3.10+ và tạo môi trường riêng..."
if [ ! -x .venv/bin/python ]; then
  PY=""
  for p in python3.14 python3.13 python3.12 python3.11 python3.10 python3; do  # Python sẵn có của Apple là 3.9: vnstock không chạy
    command -v "$p" >/dev/null && "$p" -c 'import sys; sys.exit(sys.version_info < (3, 10))' 2>/dev/null && { PY="$p"; break; }
  done
  [ -n "$PY" ] || dung "LỖI: Cần Python 3.10 trở lên. Tải tại https://www.python.org/downloads/ , cài xong chạy lại lệnh này."
  "$PY" -m venv .venv || dung "LỖI: Không tạo được môi trường Python."
fi

echo "[2/3] Cài vnstock theo requirements.txt (lần đầu mất vài phút)..."
.venv/bin/python -m pip install -q --extra-index-url https://vnstocks.com/api/packages -r requirements.txt certifi
.venv/bin/python -m pip show vnstock >/dev/null 2>&1 && .venv/bin/python -c "import certifi" 2>/dev/null \
  || dung "LỖI: Cài vnstock thất bại - chụp màn hình thông báo phía trên gửi người hỗ trợ."
# Python tải từ python.org trên Mac không dùng chứng chỉ của hệ thống -> chỉ cho nó bộ chứng chỉ certifi
export SSL_CERT_FILE="$(.venv/bin/python -m certifi)"

echo "[3/3] Mở giao diện web tại http://localhost:8000 (nhấn Ctrl+C hoặc đóng cửa sổ này để tắt)."
.venv/bin/python web.py
