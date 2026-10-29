#!/usr/bin/env bash
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
work="$(mktemp -d "${TMPDIR:-/tmp}/maxi-markdown-checks.XXXXXX")"
trap 'rm -rf "$work"' EXIT
swiftc -D MAXI_HUD_TESTING -parse-as-library "$root"/frontends/macos/Sources/MaxiHUD/*.swift \
    "$root/tests/macos_hud/MarkdownChecks.swift" -o "$work/MarkdownChecks"
"$work/MarkdownChecks"
