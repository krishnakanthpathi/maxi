#!/bin/bash
# Build the universal app + online bootstrap DMG. No private runtime is bundled.
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
version='0.3.0-beta.1'
wheel="$root/dist/maxi_ai-0.3.0b1-py3-none-any.whl"
[[ "$(uname -s)" == Darwin ]] || { echo 'Build on macOS.' >&2; exit 1; }
[[ -f "$wheel" ]] || { echo 'Build the release wheel with uv build first.' >&2; exit 1; }
stage="$(mktemp -d "${TMPDIR:-/tmp}/maxi-installer.XXXXXX")"
mount_point=''
cleanup() {
    if [[ -n "$mount_point" ]]; then hdiutil detach "$mount_point" -quiet || true; fi
    rm -rf "$stage"
}
trap cleanup EXIT
app="$stage/volume/Maxi.app"
contents="$app/Contents"
resources="$contents/Resources"
mkdir -p "$contents/MacOS" "$resources" "$root/dist"

swift build -c release --package-path "$root/frontends/macos" --arch arm64 --arch x86_64
binary_dir="$(swift build -c release --package-path "$root/frontends/macos" --arch arm64 --arch x86_64 --show-bin-path)"
cp "$binary_dir/MaxiHUD" "$contents/MacOS/MaxiHUD"
for arch in arm64 x86_64; do
    swiftc -O -target "${arch}-apple-macosx14.0" "$root/scripts/macos/Launcher.swift" -o "$stage/launcher-$arch"
done
lipo -create "$stage/launcher-arm64" "$stage/launcher-x86_64" -output "$contents/MacOS/MaxiLauncher"
swift "$root/scripts/macos/make_icon.swift" "$stage/Maxi.iconset"
iconutil -c icns "$stage/Maxi.iconset" -o "$resources/Maxi.icns"
cp "$wheel" "$resources/"
(cd "$resources" && shasum -a 256 "$(basename "$wheel")" > BACKEND-SHA256SUMS)
cp "$root/.env.example" "$resources/default.env"
cp "$root/scripts/install_macos.sh" "$resources/install_macos.sh"
cp "$root/scripts/macos/Install Maxi.command" "$resources/Install Maxi.command"
cp "$root/LICENSE" "$resources/LICENSE"
chmod +x "$resources/install_macos.sh" "$resources/Install Maxi.command"
python3 - "$contents/Info.plist" <<'PY'
import plistlib, sys
info = {
    'CFBundleDisplayName': 'Maxi', 'CFBundleName': 'Maxi',
    'CFBundleExecutable': 'MaxiLauncher', 'CFBundleIdentifier': 'com.maxi.hud',
    'CFBundlePackageType': 'APPL', 'CFBundleShortVersionString': '0.3.0',
    'CFBundleVersion': '2', 'LSMinimumSystemVersion': '14.0',
    'CFBundleIconFile': 'Maxi.icns', 'LSUIElement': True,
    'NSHighResolutionCapable': True,
    'NSMicrophoneUsageDescription': 'Maxi records your voice while you use the voice shortcut.',
}
with open(sys.argv[1], 'wb') as target:
    plistlib.dump(info, target)
PY
codesign --force --sign - "$contents/MacOS/MaxiHUD"
codesign --force --sign - "$app"
codesign --verify --deep --strict "$app"
ditto -c -k --keepParent "$app" "$root/dist/Maxi-${version}-macos-universal.zip"
cp "$root/scripts/install_macos.sh" "$root/dist/install-macos.sh"

# Both the application and mounted disk have the summation icon.
cp "$resources/Maxi.icns" "$stage/volume/.VolumeIcon.icns"
ln -s /Applications "$stage/volume/Applications"
cat > "$stage/volume/READ ME.txt" <<'EOF'
∑ Maxi — macOS 14+ · Apple Silicon and Intel

Drag Maxi to Applications, then open it.
On first launch, Terminal opens the setup wizard. Setup installs a private
Python runtime if needed and installs the bundled Python backend with voice.
Internet access is required for this first setup. No Homebrew or Xcode needed.
After setup, Maxi starts its daemon and opens the native HUD automatically.
Existing configuration and saved memories are preserved.

This beta is not Developer ID signed or notarized. If macOS blocks it, review
Maxi in System Settings > Privacy & Security. Grant Microphone and the
appropriate Accessibility/Input Monitoring permissions when requested.

Your model runtime and speech provider must be configured separately.
EOF
hdiutil create -quiet -fs HFS+ -volname Maxi -srcfolder "$stage/volume" -format UDRW "$stage/Maxi-rw.dmg"
mount_point="$stage/mounted"
hdiutil attach -quiet -nobrowse -mountpoint "$mount_point" "$stage/Maxi-rw.dmg"
SetFile -a C "$mount_point"
hdiutil detach -quiet "$mount_point"
mount_point=''
hdiutil convert -quiet -ov "$stage/Maxi-rw.dmg" -format UDZO -o "$root/dist/Maxi-${version}-macos-universal.dmg"
echo "Packaged Maxi-${version}-macos-universal.dmg and .zip"
