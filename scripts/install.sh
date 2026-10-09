#!/usr/bin/env bash
#
# Maxi Universal Cross-Platform Installer ⚡
# Usage: curl -fsSL https://raw.githubusercontent.com/krishnakanthpathi/maxi/main/scripts/install.sh | bash
#
set -euo pipefail

# Visual styling
BOLD="\033[1m"
GREEN="\033[32m"
CYAN="\033[36m"
YELLOW="\033[33m"
RED="\033[31m"
RESET="\033[0m"

echo -e "${CYAN}${BOLD}"
echo "  __  __              _ "
echo " |  \/  | __ ___  __ (_)"
echo " | |\/| |/ _\` \ \/ / | |"
echo " | |  | | (_| |>  <  | |"
echo " |_|  |_|\__,_/_/\_\ |_|"
echo -e "${RESET}"
echo -e "${BOLD}⚡ Maxi Universal Workstation Daemon Installer${RESET}"
echo ""

# 1. OS & Architecture Detection
OS="$(uname -s)"
ARCH="$(uname -m)"
echo -e "🔍 Detected Platform: ${GREEN}${OS} (${ARCH})${RESET}"

# 2. Python Environment Check
PYTHON_BIN=""
for cmd in python3.12 python3.11 python3.10 python3 python; do
    if command -v "$cmd" >/dev/null 2>&1; then
        PY_VER="$($cmd -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
        PY_MAJOR="$(echo "$PY_VER" | cut -d. -f1)"
        PY_MINOR="$(echo "$PY_VER" | cut -d. -f2)"
        if [ "$PY_MAJOR" -ge 3 ] && [ "$PY_MINOR" -ge 10 ]; then
            PYTHON_BIN="$cmd"
            echo -e "🐍 Found Python: ${GREEN}$($cmd --version)${RESET} (${cmd})"
            break
        fi
    fi
done

if [ -z "$PYTHON_BIN" ]; then
    echo -e "${RED}❌ Python 3.10+ is required but was not found on your system.${RESET}"
    if [ "$OS" = "Darwin" ]; then
        echo -e "👉 Install via Homebrew: ${CYAN}brew install python@3.12${RESET}"
    else
        echo -e "👉 Install via APT: ${CYAN}sudo apt install -y python3 python3-pip python3-venv${RESET}"
    fi
    exit 1
fi

# 3. OS-Specific Audio Dependencies (Linux)
INSTALL_EXTRAS="[voice]"
if [ "$OS" = "Linux" ]; then
    if ! command -v ldconfig >/dev/null 2>&1 || ! ldconfig -p | grep -q "libportaudio"; then
        echo -e "${YELLOW}⚠️  PortAudio not found. Installing Linux audio libraries...${RESET}"
        if command -v apt-get >/dev/null 2>&1; then
            sudo apt-get update -qq && sudo apt-get install -y -qq libasound2-dev portaudio19-dev || true
        elif command -v pacman >/dev/null 2>&1; then
            sudo pacman -S --noconfirm portaudio alsa-lib || true
        elif command -v dnf >/dev/null 2>&1; then
            sudo dnf install -y portaudio-devel alsa-lib-devel || true
        else
            echo -e "${YELLOW}ℹ️  Could not auto-install portaudio headers. Defaulting to core backend.${RESET}"
            INSTALL_EXTRAS=""
        fi
    fi
fi

# 4. Target Directory & Virtual Environment
INSTALL_DIR="${HOME}/.maxi"
VENV_DIR="${INSTALL_DIR}/venv"
mkdir -p "${INSTALL_DIR}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
GIT_REPO_URL="https://github.com/krishnakanthpathi/maxi.git"
SRC_DIR="${INSTALL_DIR}/src"

# If running via curl on a fresh system without local repo, clone from GitHub
if [ ! -f "${REPO_ROOT}/pyproject.toml" ]; then
    echo -e "🌐 Fetching latest Maxi source from GitHub..."
    if [ -d "${SRC_DIR}/.git" ]; then
        git -C "${SRC_DIR}" pull --quiet || true
    else
        git clone --quiet "${GIT_REPO_URL}" "${SRC_DIR}"
    fi
    SOURCE_PATH="${SRC_DIR}"
else
    SOURCE_PATH="${REPO_ROOT}"
fi

# Sync default configs from source
if [ -f "${SOURCE_PATH}/.env" ] && [ ! -f "${INSTALL_DIR}/.env" ]; then
    cp "${SOURCE_PATH}/.env" "${INSTALL_DIR}/.env"
    echo -e "🔑 Synced environment keys to ${CYAN}${INSTALL_DIR}/.env${RESET}"
elif [ -f "${SOURCE_PATH}/.env.example" ] && [ ! -f "${INSTALL_DIR}/.env" ]; then
    cp "${SOURCE_PATH}/.env.example" "${INSTALL_DIR}/.env"
    echo -e "🔑 Initialized default config at ${CYAN}${INSTALL_DIR}/.env${RESET}"
fi

if [ -d "${SOURCE_PATH}/.maxi" ]; then
    cp -r "${SOURCE_PATH}/.maxi/"* "${INSTALL_DIR}/" 2>/dev/null || true
fi

echo -e "📦 Setting up isolated environment at ${CYAN}${VENV_DIR}${RESET}..."
if command -v uv >/dev/null 2>&1; then
    echo -e "⚡ Using uv for high-speed package management..."
    uv venv --python "$PYTHON_BIN" "${VENV_DIR}"
    echo -e "🔧 Installing Maxi package..."
    uv pip install -e "${SOURCE_PATH}${INSTALL_EXTRAS}" --python "${VENV_DIR}"
else
    "$PYTHON_BIN" -m venv "${VENV_DIR}"
    VENV_PIP="${VENV_DIR}/bin/pip"
    "${VENV_PIP}" install --upgrade --quiet pip setuptools wheel
    echo -e "🔧 Installing Maxi package..."
    "${VENV_PIP}" install --quiet -e "${SOURCE_PATH}${INSTALL_EXTRAS}"
fi

VENV_MAXI="${VENV_DIR}/bin/maxi"

# 6. Global Symlink
BIN_DIR="${HOME}/.local/bin"
mkdir -p "${BIN_DIR}"
ln -sf "${VENV_MAXI}" "${BIN_DIR}/maxi"
echo -e "🔗 Linked CLI to ${GREEN}${BIN_DIR}/maxi${RESET}"

# 7. System Background Service Setup
if [ "$OS" = "Darwin" ]; then
    # macOS launchd plist
    PLIST_PATH="${HOME}/Library/LaunchAgents/com.maxi.daemon.plist"
    mkdir -p "$(dirname "$PLIST_PATH")"
    cat <<EOF > "$PLIST_PATH"
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.maxi.daemon</string>
    <key>ProgramArguments</key>
    <array>
        <string>${VENV_MAXI}</string>
        <string>run</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>${INSTALL_DIR}/daemon.log</string>
    <key>StandardErrorPath</key>
    <string>${INSTALL_DIR}/daemon.log</string>
</dict>
</plist>
EOF
    echo -e "🚀 Configured macOS LaunchAgent at ${CYAN}${PLIST_PATH}${RESET}"
    echo -e "   To enable at boot: ${CYAN}launchctl load -w ${PLIST_PATH}${RESET}"

elif [ "$OS" = "Linux" ]; then
    # Linux systemd user service
    SERVICE_PATH="${HOME}/.config/systemd/user/maxi.service"
    mkdir -p "$(dirname "$SERVICE_PATH")"
    cat <<EOF > "$SERVICE_PATH"
[Unit]
Description=Maxi Background AI Agent Daemon
After=network.target sound.target

[Service]
ExecStart=${VENV_MAXI} run
Restart=always
RestartSec=3

[Install]
WantedBy=default.target
EOF
    echo -e "🚀 Configured Linux systemd service at ${CYAN}${SERVICE_PATH}${RESET}"
    echo -e "   To enable at boot: ${CYAN}systemctl --user enable --now maxi${RESET}"
fi

echo ""
echo -e "${GREEN}${BOLD}🎉 Maxi successfully installed!${RESET}"
echo ""
echo -e "Commands:"
echo -e "  • Start daemon:   ${CYAN}maxi start${RESET}"
echo -e "  • Open Web HUD:   ${CYAN}maxi hud${RESET}"
echo -e "  • Check status:   ${CYAN}maxi status${RESET}"
echo -e "  • Stop daemon:    ${CYAN}maxi stop${RESET}"
echo ""
echo -e "Hotkey:"
if [ "$OS" = "Darwin" ]; then
    echo -e "  • Tap or hold ${BOLD}Right Option${RESET} to speak."
else
    echo -e "  • Tap or hold ${BOLD}Control + Space${RESET} to speak."
fi
echo ""
