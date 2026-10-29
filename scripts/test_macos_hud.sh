#!/usr/bin/env bash
# Run native HUD regression checks against an isolated local WebSocket peer.
set -euo pipefail
repo_root="$(cd "$(dirname "$0")/.." && pwd)"
check_dir="$(mktemp -d "${TMPDIR:-/tmp}/maxi-hud-checks.XXXXXX")"
trap 'rm -rf "$check_dir"' EXIT
sources=()
for source in "$repo_root"/frontends/macos/Sources/MaxiHUD/*.swift; do
    sources+=("$source")
done
swiftc -D MAXI_HUD_TESTING -parse-as-library "${sources[@]}" \
    "$repo_root/tests/macos_hud/HUDRecoveryChecks.swift" \
    "$repo_root/tests/macos_hud/AutoHideChecks.swift" -o "$check_dir/HUDRecoveryChecks"
"$check_dir/HUDRecoveryChecks"
