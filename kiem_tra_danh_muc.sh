#!/bin/bash
# launchd gọi mỗi 15 phút (cài bằng: bash cai_lich_quet.sh). Ngoài giờ khớp lệnh hoặc không có vị thế: danh_muc.py thoát ngay, không gọi mạng.
# Chỉ in ra (vào log.txt) khi gửi cảnh báo hoặc có lỗi.
cd "$(dirname "$0")" || exit 1
export SSL_CERT_FILE="$(.venv/bin/python -m certifi)"  # Python của python.org trên Mac không dùng chứng chỉ hệ thống
exec .venv/bin/python danh_muc.py "$@"
