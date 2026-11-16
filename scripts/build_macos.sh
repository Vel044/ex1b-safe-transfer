#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
configuration=${BUILD_CONFIGURATION:-release}
swift build --package-path macos --build-system native -c "$configuration" -q
bin_path=$(swift build --package-path macos --build-system native -c "$configuration" --show-bin-path)
app_path="$PWD/build/安传.app"
mkdir -p "$app_path/Contents/MacOS" "$app_path/Contents/Resources"
cp "$bin_path/SafeTransfer" "$app_path/Contents/MacOS/SafeTransfer"
cp macos/Info.plist "$app_path/Contents/Info.plist"
xattr -cr "$app_path"
if ! codesign --force --sign - --entitlements macos/App.entitlements --timestamp=none "$app_path"; then
  # iCloud File Provider may add FinderInfo while a Desktop bundle is copied.
  xattr -cr "$app_path"
  codesign --force --sign - --entitlements macos/App.entitlements --timestamp=none "$app_path"
fi
codesign --verify --strict "$app_path"
printf '%s\n' "已构建：$app_path"
