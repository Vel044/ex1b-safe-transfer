#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
configuration=${BUILD_CONFIGURATION:-release}
swift build --package-path macos --build-system native -c "$configuration" -q
bin_path=$(swift build --package-path macos --build-system native -c "$configuration" --show-bin-path)
app_path="$PWD/build/SFT1 Transfer.app"
mkdir -p "$app_path/Contents/MacOS" "$app_path/Contents/Resources"
cp "$bin_path/SafeTransfer" "$app_path/Contents/MacOS/SafeTransfer"
cp macos/Info.plist "$app_path/Contents/Info.plist"
iconset="$PWD/build/AppIcon.iconset"
mkdir -p "$iconset"
for size in 16 32 128 256 512; do
  sips -z "$size" "$size" assets/brand/sft1-transfer.png --out "$iconset/icon_${size}x${size}.png" >/dev/null
  double_size=$((size * 2))
  sips -z "$double_size" "$double_size" assets/brand/sft1-transfer.png --out "$iconset/icon_${size}x${size}@2x.png" >/dev/null
done
iconutil -c icns "$iconset" -o "$app_path/Contents/Resources/AppIcon.icns"
xattr -cr "$app_path"
if ! codesign --force --sign - --entitlements macos/App.entitlements --timestamp=none "$app_path"; then
  # iCloud File Provider may add FinderInfo while a Desktop bundle is copied.
  xattr -cr "$app_path"
  codesign --force --sign - --entitlements macos/App.entitlements --timestamp=none "$app_path"
fi
codesign --verify --strict "$app_path"
printf '%s\n' "已构建：$app_path"
