#!/bin/zsh
set -eu
cd "$(dirname "$0")/.."
if [[ ! -x macos/build/WiFiRSSIHelper.app/Contents/MacOS/RSSIHelper ]]; then
  zsh macos/build.sh
fi
python3 -c 'import sys; assert sys.version_info >= (3, 11), "Python 3.11+ diperlukan"'
echo "Mac harus terhubung ke hotspot Windows 2.4 GHz."
read "SSID?Nama hotspot Windows (SSID): "
read "SERVER?IP hotspot Windows [192.168.137.1]: "
SERVER=${SERVER:-192.168.137.1}
open -n "$PWD/macos/build/WiFiRSSIHelper.app" --args --output "$PWD/macos/build/rssi.json"
echo "Izinkan Location Services di jendela helper dan Local Network untuk Python/Terminal jika diminta."
python3 -m wifi_lab.companion --ssid "$SSID" --server "$SERVER" --rssi-file "$PWD/macos/build/rssi.json"
