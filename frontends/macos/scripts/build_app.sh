#!/bin/bash
set -e

# ==============================================================================
# Maxi macOS Native Bundle Packager
# Compiles MaxiHUD via Swift Package Manager and packages into Maxi.app
# ==============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PACKAGE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
BUILD_DIR="${PACKAGE_ROOT}/.build"
DIST_DIR="${PACKAGE_ROOT}/dist"
APP_BUNDLE="${DIST_DIR}/Maxi.app"

echo "⚡ Building MaxiHUD Release binary..."
cd "${PACKAGE_ROOT}"
swift build -c release

# Find the release binary
RELEASE_BIN=$(find "${BUILD_DIR}" -type f -name MaxiHUD -perm +111 | grep -E "release|Release" | head -n 1)

if [ -z "${RELEASE_BIN}" ]; then
    echo "⚠️ Release binary not found, using debug binary fallback..."
    RELEASE_BIN=$(find "${BUILD_DIR}" -type f -name MaxiHUD -perm +111 | head -n 1)
fi

if [ -z "${RELEASE_BIN}" ]; then
    echo "❌ Failed to locate compiled MaxiHUD binary."
    exit 1
fi

echo "📦 Packaging into ${APP_BUNDLE}..."
rm -rf "${APP_BUNDLE}"
mkdir -p "${APP_BUNDLE}/Contents/MacOS"
mkdir -p "${APP_BUNDLE}/Contents/Resources"

# Copy binary
cp "${RELEASE_BIN}" "${APP_BUNDLE}/Contents/MacOS/MaxiHUD"
chmod +x "${APP_BUNDLE}/Contents/MacOS/MaxiHUD"

# Copy Info.plist
cp "${PACKAGE_ROOT}/Resources/Info.plist" "${APP_BUNDLE}/Contents/Info.plist"

# Copy icon if available
if [ -f "${PACKAGE_ROOT}/Resources/AppIcon.icns" ]; then
    cp "${PACKAGE_ROOT}/Resources/AppIcon.icns" "${APP_BUNDLE}/Contents/Resources/AppIcon.icns"
fi

echo "✅ Successfully built: ${APP_BUNDLE}"
echo "🚀 To run:"
echo "   open \"${APP_BUNDLE}\""
