#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
swift build --package-path macos --build-system native -c release -q
bin_path=$(swift build --package-path macos --build-system native -c release --show-bin-path)
app_path="$PWD/build/安传.app"
mkdir -p "$app_path/Contents/MacOS" "$app_path/Contents/Resources"
cp "$bin_path/SafeTransfer" "$app_path/Contents/MacOS/SafeTransfer"
cp macos/Info.plist "$app_path/Contents/Info.plist"
codesign --force --sign - --entitlements macos/App.entitlements --timestamp=none "$app_path"
codesign --verify --strict "$app_path"
printf '%s\n' "已构建：$app_path"
