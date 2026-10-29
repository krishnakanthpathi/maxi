#!/usr/bin/env bash
# Build the unsigned macOS HUD companion; the Python daemon installs separately.
set -euo pipefail
repo_root="$(cd "$(dirname "$0")/.." && pwd)"
release_name="0.3.0-beta.1"
if [[ "$(uname -s)" != Darwin ]]; then
    echo 'The macOS companion must be packaged on macOS.' >&2
    exit 1
fi
swift build -c release --package-path "$repo_root/frontends/macos"
bin_dir="$(swift build -c release --package-path "$repo_root/frontends/macos" --show-bin-path)"
arch="$(uname -m)"
stage_dir="$(mktemp -d "${TMPDIR:-/tmp}/maxi-release.XXXXXX")"
trap 'rm -rf "$stage_dir"' EXIT
app_dir="$stage_dir/Maxi.app/Contents"
mkdir -p "$app_dir/MacOS" "$app_dir/Resources" "$repo_root/dist"
cp "$bin_dir/MaxiHUD" "$app_dir/MacOS/MaxiHUD"
cp -R "$repo_root/frontends/macos/Sources/MaxiHUD/Resources/Renderer" "$app_dir/Resources/Renderer"
python3 - "$app_dir/Info.plist" <<'PY'
import plistlib, sys
from pathlib import Path
info = {
    'CFBundleDisplayName': 'Maxi', 'CFBundleName': 'Maxi',
    'CFBundleExecutable': 'MaxiHUD', 'CFBundleIdentifier': 'com.maxi.hud',
    'CFBundlePackageType': 'APPL', 'CFBundleShortVersionString': '0.3.0',
    'CFBundleVersion': '9', 'LSMinimumSystemVersion': '14.0',
    'LSUIElement': True, 'NSHighResolutionCapable': True,
}
with Path(sys.argv[1]).open('wb') as target:
    plistlib.dump(info, target)
PY
cp "$repo_root/releases/v${release_name}.md" "$stage_dir/INSTALL.md"
cp "$repo_root/LICENSE" "$stage_dir/LICENSE"
ditto -c -k --keepParent "$stage_dir/Maxi.app" "$repo_root/dist/MaxiHUD-${release_name}-macos-${arch}.zip"
# Include installation notes next to the app without exposing build or user data.
(cd "$stage_dir" && zip -q "$repo_root/dist/MaxiHUD-${release_name}-macos-${arch}.zip" INSTALL.md LICENSE)
echo "Packaged $repo_root/dist/MaxiHUD-${release_name}-macos-${arch}.zip"
