#!/bin/bash
# Cài lịch quét tự động 15:15 thứ Hai–Sáu bằng launchd (máy ngủ lúc 15:15 thì chạy bù khi thức dậy).
#   bash cai_lich_quet.sh        -> cài / cài lại
#   bash cai_lich_quet.sh go     -> gỡ lịch
cd "$(dirname "$0")" || exit 1
NHAN="vn.cw-scanner.quet"
PLIST="$HOME/Library/LaunchAgents/$NHAN.plist"
launchctl bootout "gui/$(id -u)/$NHAN" 2>/dev/null  # gỡ bản cũ (nếu có) trước khi cài lại
if [ "$1" = "go" ]; then
  rm -f "$PLIST" && echo "Đã gỡ lịch quét tự động."
  exit 0
fi
NGAY=""
for thu in 1 2 3 4 5; do
  NGAY="$NGAY<dict><key>Weekday</key><integer>$thu</integer><key>Hour</key><integer>15</integer><key>Minute</key><integer>15</integer></dict>"
done
mkdir -p "$HOME/Library/LaunchAgents"
cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$NHAN</string>
  <key>ProgramArguments</key><array><string>/bin/bash</string><string>$PWD/chay_quet_tu_dong.sh</string></array>
  <key>StartCalendarInterval</key><array>$NGAY</array>
  <key>StandardOutPath</key><string>$PWD/log.txt</string>
  <key>StandardErrorPath</key><string>$PWD/log.txt</string>
</dict></plist>
EOF
plutil -lint "$PLIST" >/dev/null || { echo "LỖI: file lịch không hợp lệ: $PLIST"; exit 1; }
launchctl bootstrap "gui/$(id -u)" "$PLIST" && echo "Đã cài lịch quét 15:15 thứ Hai–Sáu ($PLIST). Nhật ký: $PWD/log.txt"
