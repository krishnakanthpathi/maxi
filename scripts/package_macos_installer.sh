#!/bin/bash
# Build the universal app + online bootstrap DMG. No private runtime is bundled.
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
version='0.3.0-beta.1'
[[ "$(uname -s)" == Darwin ]] || { echo 'Build on macOS.' >&2; exit 1; }
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
swift "$root/scripts/macos/make_icon.swift" "$stage/Maxi.iconset"
iconutil -c icns "$stage/Maxi.iconset" -o "$resources/Maxi.icns"
cp "$root/.env.example" "$resources/default.env"
cp "$root/scripts/install_macos.sh" "$resources/install_macos.sh"
# A website deployment can host the matching wheel and app independently of GitHub.
python3 - "$resources/install_macos.sh" "${MAXI_RELEASE_URL:-}" <<'PY'
from pathlib import Path
import re, sys
if sys.argv[2]:
    assert re.fullmatch(r'https://[A-Za-z0-9./_-]+', sys.argv[2]), 'Use an HTTPS release URL without shell metacharacters'
    script = Path(sys.argv[1])
    script.write_text('\n'.join(
        f'release_url="{sys.argv[2].rstrip("/")}"' if line.startswith('release_url=') else line
        for line in script.read_text().splitlines()
    ) + '\n')
PY
cp "$root/scripts/macos/Install Maxi.command" "$resources/Install Maxi.command"
cp "$root/LICENSE" "$resources/LICENSE"
cp -R "$root/frontends/macos/Sources/MaxiHUD/Resources/Renderer" "$resources/Renderer"
chmod +x "$resources/install_macos.sh" "$resources/Install Maxi.command"
python3 - "$contents/Info.plist" <<'PY'
import plistlib, sys
info = {
    'CFBundleDisplayName': 'Maxi', 'CFBundleName': 'Maxi',
    'CFBundleExecutable': 'MaxiHUD', 'CFBundleIdentifier': 'com.maxi.hud',
    'CFBundlePackageType': 'APPL', 'CFBundleShortVersionString': '0.3.0',
    'CFBundleVersion': '9', 'LSMinimumSystemVersion': '14.0',
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
ditto -c -k --keepParent "$app" "$stage/Maxi.zip"
mv -f "$stage/Maxi.zip" "$root/dist/Maxi-${version}-macos-universal.zip"
cp "$resources/install_macos.sh" "$root/dist/install-macos.sh"

# Both the application and mounted disk have the summation icon.
cp "$resources/Maxi.icns" "$stage/volume/.VolumeIcon.icns"
ln -s /Applications "$stage/volume/Applications"
cat > "$stage/volume/READ ME.txt" <<'EOF'
∑ Maxi — macOS 14+ · Apple Silicon and Intel

Drag Maxi to Applications, then open it.
On first launch, Terminal opens the setup wizard. Setup installs a private
Python runtime if needed and downloads and installs the separate backend wheel with voice.
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
