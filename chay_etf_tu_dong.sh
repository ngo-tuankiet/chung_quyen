#!/bin/bash
# launchd gọi file này 15:30 thứ Hai–Sáu (cài bằng: bash cai_lich_quet.sh): báo cáo ETF lên Discord; nhật ký trong log.txt.
cd "$(dirname "$0")" || exit 1
echo "===== ETF $(date '+%Y-%m-%d %H:%M:%S') ====="
export SSL_CERT_FILE="$(.venv/bin/python -m certifi)"  # Python của python.org trên Mac không dùng chứng chỉ hệ thống
# Ngày nghỉ lễ / Tết (bảng giá vẫn ghi phiên trước): không gửi gì. Không kiểm tra được (mất mạng) thì vẫn chạy.
.venv/bin/python -c "import sys, cw_scanner; sys.exit(0 if cw_scanner.la_ngay_giao_dich() else 3)"
if [ $? = 3 ]; then
  echo "Hôm nay không có phiên giao dịch (nghỉ lễ): bỏ qua báo cáo ETF."
  exit 0
fi
# Lỗi (vd máy chủ vnstock không phản hồi) thì thử lại tối đa 2 lần, cách nhau 5 phút; vẫn lỗi thì báo lỗi lên Discord
TAM=$(mktemp)
for LAN in 1 2 3; do
  .venv/bin/python etf.py >"$TAM" 2>&1
  ma_loi=$?
  cat "$TAM"
  [ "$ma_loi" = 0 ] && break
  [ "$LAN" -lt 3 ] && { echo "Báo cáo ETF lỗi (lần $LAN/3), thử lại sau 5 phút..."; sleep 300; }
done
if [ "$ma_loi" != 0 ]; then  # lý do: dòng "...Error: ..." cuối của traceback (như chay_quet_tu_dong.sh)
  QUET_LOI="$(grep -E '(Error|Exception)(:|$)' "$TAM" | tail -1)"
  [ -n "$QUET_LOI" ] || QUET_LOI="$(grep -v '^[[:space:]]*$' "$TAM" | tail -1)"
  QUET_LOI="$QUET_LOI" .venv/bin/python etf.py --bao-loi
fi
rm -f "$TAM"
exit $ma_loi
