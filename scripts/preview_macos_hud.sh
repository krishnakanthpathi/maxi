#!/bin/bash
# Render the actual native HUD with synthetic content and no backend requests.
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
output="${1:-$root/frontends/macos/dist/preview}"
work="$(mktemp -d "${TMPDIR:-/tmp}/maxi-hud-preview.XXXXXX")"
trap 'rm -rf "$work"' EXIT
swiftc -D MAXI_HUD_TESTING -parse-as-library "$root"/frontends/macos/Sources/MaxiHUD/*.swift \
    "$root/tests/macos_hud/HUDPreview.swift" -o "$work/HUDPreview"
"$work/HUDPreview" "$output"
