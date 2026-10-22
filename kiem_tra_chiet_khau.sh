#!/bin/bash
# launchd gọi mỗi 5 phút (cài bằng: bash cai_lich_quet.sh): ghi iNAV các ETF trong phiên vào ket_qua/inav_YYYY-MM-DD.csv,
# báo Discord quỹ dưới NAV đạt ngưỡng (khi đã bật BAT_CANH_BAO_TRONG_PHIEN). Ngoài giờ khớp lệnh: thoát ngay, không gọi mạng.
cd "$(dirname "$0")" || exit 1
export SSL_CERT_FILE="$(.venv/bin/python -m certifi)"  # Python của python.org trên Mac không dùng chứng chỉ hệ thống
exec .venv/bin/python chiet_khau.py --trong-phien "$@"
