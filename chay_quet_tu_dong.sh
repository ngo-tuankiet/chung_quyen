#!/bin/bash
# launchd gọi file này 15:15 thứ Hai–Sáu (cài bằng: bash cai_lich_quet.sh). Quét CW rồi sao lưu ket_qua/; nhật ký nằm trong log.txt.
cd "$(dirname "$0")" || exit 1
echo "===== $(date '+%Y-%m-%d %H:%M:%S') ====="
# Python tải từ python.org trên Mac không dùng chứng chỉ của hệ thống -> chỉ cho nó bộ chứng chỉ certifi (giống chay_web.command)
export SSL_CERT_FILE="$(.venv/bin/python -m certifi)"
.venv/bin/python cw_scanner.py
ma_loi=$?
# Sao lưu cả khi quét lỗi (giữ bản các ngày trước). Không dùng --delete: không bao giờ xóa bản sao lưu cũ.
# Không đặt trong ~/Documents, ~/Downloads, ~/Desktop: macOS chặn tác vụ chạy nền đọc/ghi các thư mục đó ("Operation not permitted")
SAO_LUU="$HOME/cw_scanner_sao_luu"
mkdir -p "$SAO_LUU" && rsync -a ket_qua/ "$SAO_LUU/" && cp -p cw_da_biet.txt "$SAO_LUU/" 2>/dev/null
echo "Sao lưu vào $SAO_LUU: mã thoát rsync $?; mã thoát lần quét $ma_loi"
exit $ma_loi
