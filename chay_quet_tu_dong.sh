#!/bin/bash
# launchd gọi file này 14:00 thứ Hai–Sáu (cài bằng: bash cai_lich_quet.sh). Quét CW rồi sao lưu ket_qua/; nhật ký nằm trong log.txt.
cd "$(dirname "$0")" || exit 1
echo "===== $(date '+%Y-%m-%d %H:%M:%S') ====="
# Python tải từ python.org trên Mac không dùng chứng chỉ của hệ thống -> chỉ cho nó bộ chứng chỉ certifi (giống chay_web.command)
export SSL_CERT_FILE="$(.venv/bin/python -m certifi)"
# Ngày nghỉ lễ / Tết (bảng giá vẫn ghi phiên trước): không quét, không gửi báo cáo. Không kiểm tra được (mất mạng) thì vẫn quét.
.venv/bin/python -c "import sys, cw_scanner; sys.exit(0 if cw_scanner.la_ngay_giao_dich() else 3)"
if [ $? = 3 ]; then
  echo "Hôm nay không có phiên giao dịch (nghỉ lễ): bỏ qua quét và báo cáo."
  exit 0
fi
# Quét; lỗi (vd máy chủ vnstock không phản hồi) thì thử lại tối đa 2 lần, cách nhau 5 phút
TAM=$(mktemp)
for LAN in 1 2 3; do
  .venv/bin/python cw_scanner.py >"$TAM" 2>&1
  ma_loi=$?
  cat "$TAM"
  [ "$ma_loi" = 0 ] && break
  [ "$LAN" -lt 3 ] && { echo "Quét lỗi (lần $LAN/3), thử lại sau 5 phút..."; sleep 300; }
done
QUET_LOI=""
if [ "$ma_loi" != 0 ]; then  # lý do đưa vào báo cáo: dòng "...Error: ..." cuối của traceback (vnstock còn in thêm dòng sau nó)
  QUET_LOI="$(grep -E '(Error|Exception)(:|$)' "$TAM" | tail -1)"
  [ -n "$QUET_LOI" ] || QUET_LOI="$(grep -v '^[[:space:]]*$' "$TAM" | tail -1)"
fi
rm -f "$TAM"
.venv/bin/python danh_muc.py --luon  # cảnh báo danh mục vừa xuất hiện -> Discord
QUET_LOI="$QUET_LOI" .venv/bin/python danh_muc.py --bao-cao  # báo cáo tổng hợp ngày -> Discord (ghi rõ nếu quét lỗi)
# Sao lưu cả khi quét lỗi (giữ bản các ngày trước). Không dùng --delete: không bao giờ xóa bản sao lưu cũ.
# Không đặt trong ~/Documents, ~/Downloads, ~/Desktop: macOS chặn tác vụ chạy nền đọc/ghi các thư mục đó ("Operation not permitted")
SAO_LUU="$HOME/cw_scanner_sao_luu"
mkdir -p "$SAO_LUU" && rsync -a ket_qua/ "$SAO_LUU/" && cp -p cw_da_biet.txt "$SAO_LUU/" 2>/dev/null
ma_sao_luu=$?
if [ -f danh_muc.csv ]; then  # mỗi ngày 1 bản: sửa/xóa nhầm vẫn lấy lại được
  cp -p danh_muc.csv "$SAO_LUU/danh_muc_$(date +%Y-%m-%d).csv" || ma_sao_luu=1
fi
echo "Sao lưu vào $SAO_LUU: mã thoát sao lưu $ma_sao_luu; mã thoát lần quét $ma_loi"
exit $ma_loi
