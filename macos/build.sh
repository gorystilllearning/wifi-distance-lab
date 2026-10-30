#!/bin/zsh
set -eu
cd "$(dirname "$0")/.."
APP="$PWD/macos/build/WiFiRSSIHelper.app"
mkdir -p "$APP/Contents/MacOS"
cp macos/Info.plist "$APP/Contents/Info.plist"
xcrun swiftc -O -swift-version 5 -target arm64-apple-macosx13.0 \
  macos/RSSIHelper.swift -o "$APP/Contents/MacOS/RSSIHelper" \
  -framework AppKit -framework CoreWLAN -framework CoreLocation
codesign --force --sign - "$APP"
echo "Built $APP. Jalankan jalankan.command untuk meminta izin dan menerima data."
