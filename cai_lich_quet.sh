#!/bin/bash
# Cài 4 lịch chạy nền bằng launchd (máy ngủ đúng giờ thì chạy bù khi thức dậy):
#   - vn.cw-scanner.quet      : 14:00 thứ Hai–Sáu quét CW, kiểm tra danh mục, sao lưu (chay_quet_tu_dong.sh)
#   - vn.cw-scanner.danh-muc  : mỗi 5 phút kiểm tra danh mục, gửi Discord khi có cảnh báo mới (kiem_tra_danh_muc.sh)
#   - vn.cw-scanner.etf       : 9:40 thứ Hai–Sáu báo cáo ETF lên Discord (chay_etf_tu_dong.sh)
#   - vn.cw-scanner.chiet-khau: mỗi 5 phút ghi iNAV ETF trong phiên, báo quỹ dưới NAV (kiem_tra_chiet_khau.sh)
#   bash cai_lich_quet.sh        -> cài / cài lại
#   bash cai_lich_quet.sh go     -> gỡ cả bốn
cd "$(dirname "$0")" || exit 1
mkdir -p "$HOME/Library/LaunchAgents"

cai() {  # cai <nhãn> <script> <khối lịch trong plist>
  local plist="$HOME/Library/LaunchAgents/$1.plist"
  launchctl bootout "gui/$(id -u)/$1" 2>/dev/null  # gỡ bản cũ (nếu có) trước khi cài lại
  if [ "$GO" = 1 ]; then rm -f "$plist"; echo "Đã gỡ $1."; return; fi
  cat > "$plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$1</string>
  <key>ProgramArguments</key><array><string>/bin/bash</string><string>$PWD/$2</string></array>
  $3
  <key>StandardOutPath</key><string>$PWD/log.txt</string>
  <key>StandardErrorPath</key><string>$PWD/log.txt</string>
</dict></plist>
EOF
  plutil -lint "$plist" >/dev/null || { echo "LỖI: file lịch không hợp lệ: $plist"; exit 1; }
  launchctl bootstrap "gui/$(id -u)" "$plist" && echo "Đã cài $1 ($plist)"
}

GO=0; [ "$1" = "go" ] && GO=1
thu_2_6() {  # thu_2_6 <giờ> <phút> -> khối lịch: giờ đó thứ Hai–Sáu
  local ngay=""
  for thu in 1 2 3 4 5; do
    ngay="$ngay<dict><key>Weekday</key><integer>$thu</integer><key>Hour</key><integer>$1</integer><key>Minute</key><integer>$2</integer></dict>"
  done
  echo "<key>StartCalendarInterval</key><array>$ngay</array>"
}
cai vn.cw-scanner.quet chay_quet_tu_dong.sh "$(thu_2_6 14 0)"
cai vn.cw-scanner.etf chay_etf_tu_dong.sh "$(thu_2_6 9 40)"
cai vn.cw-scanner.danh-muc kiem_tra_danh_muc.sh "<key>StartInterval</key><integer>300</integer>"
cai vn.cw-scanner.chiet-khau kiem_tra_chiet_khau.sh "<key>StartInterval</key><integer>300</integer>"
[ "$GO" = 1 ] || echo "Nhật ký: $PWD/log.txt"
