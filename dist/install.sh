#!/bin/bash
# Install the Maxi backend and platform app/binary with a single command.
# curl -fsSL https://raw.githubusercontent.com/krishnakanthpathi/maxi/main/scripts/install.sh | bash
set -euo pipefail

release='0.3.0-beta.1'
python_version='0.3.0b1'
uv_version='0.11.32'
release_url="https://github.com/krishnakanthpathi/maxi/releases/download/v${release}"
raw_dist_url="https://raw.githubusercontent.com/krishnakanthpathi/maxi/main/dist"
archive_name="Maxi-${release}-macos-universal.zip"
wheel_name="maxi_ai-${python_version}-py3-none-any.whl"
install_dir="${MAXI_INSTALL_DIR:-$HOME/.maxi}"
apps_dir="${MAXI_APPS_DIR:-$HOME/Applications}"
bin_dir="${MAXI_BIN_DIR:-$HOME/.local/bin}"
app_source=''
binary_source=''
wheel_source=''
configure=1
launch=1
open_hud=1
delete_old_data=1

die() { printf 'Maxi: %s\n' "$*" >&2; exit 1; }

while [[ $# -gt 0 ]]; do
    case "$1" in
        --app-source) [[ $# -ge 2 ]] || die '--app-source needs a path'; app_source="$2"; shift 2 ;;
        --binary-source) [[ $# -ge 2 ]] || die '--binary-source needs a path'; binary_source="$2"; shift 2 ;;
        --wheel-source) [[ $# -ge 2 ]] || die '--wheel-source needs a path'; wheel_source="$2"; shift 2 ;;
        --no-configure) configure=0; shift ;;
        --no-launch) launch=0; shift ;;
        --no-hud) open_hud=0; shift ;;
        --keep-data) delete_old_data=0; shift ;;
        --help|-h)
            printf '%s\n' 'Install Maxi for macOS (14+) and Linux.' \
                '  --app-source PATH     Use a local Maxi.app on macOS.' \
                '  --binary-source PATH  Use a local GUI/HUD binary.' \
                '  --wheel-source PATH   Use a local wheel and adjacent SHA256SUMS manifest.' \
                '  --no-configure        Skip the interactive provider wizard.' \
                '  --no-launch           Install without starting the daemon or HUD.' \
                '  --no-hud              Start and verify the backend without opening the HUD.' \
                '  --keep-data           Keep previous temporary data, caches, and session history.' \
                'By default, previous runtime cache, stale locks, and old history are deleted on install.'
            exit 0 ;;
        *) die "Unknown option: $1" ;;
    esac
done

OS="$(uname -s)"
case "$OS" in
    Darwin)
        case "$(uname -m)" in arm64|x86_64) ;; *) die 'Unsupported Mac architecture.' ;; esac
        os_major="$(sw_vers -productVersion | cut -d. -f1)"
        [[ "$os_major" -ge 14 ]] || die 'Maxi needs macOS 14 or later.'
        ;;
    Linux)
        case "$(uname -m)" in x86_64|aarch64|arm64) ;; *) die 'Unsupported Linux architecture.' ;; esac
        ;;
    *)
        die "Unsupported platform: $OS. Maxi supports macOS and Linux."
        ;;
esac

[[ "$EUID" -ne 0 ]] || die 'Run this as your normal user, without sudo.'
for directory in "$install_dir" "$bin_dir"; do
    [[ "$directory" == /* ]] || die "Installation paths must be absolute: $directory"
done
if [[ "$OS" == "Darwin" ]]; then
    [[ "$apps_dir" == /* ]] || die "Installation paths must be absolute: $apps_dir"
fi

work_dir="$(mktemp -d "${TMPDIR:-/tmp}/maxi-install.XXXXXX")"
trap 'rm -rf "$work_dir"' EXIT

fetch() { curl --fail --location --silent --show-error --retry 3 --connect-timeout 20 --output "$2" "$1"; }

verify() {
    local path="$1" manifest="$2" name expected actual
    name="$(basename "$path")"
    expected="$(awk -v name="$name" '$2 == name { print $1 }' "$manifest")"
    [[ "$expected" =~ ^[a-fA-F0-9]{64}$ ]] || die "No unique checksum for $name"
    if command -v sha256sum >/dev/null 2>&1; then
        actual="$(sha256sum "$path" | awk '{print $1}')"
    elif command -v shasum >/dev/null 2>&1; then
        actual="$(shasum -a 256 "$path" | awk '{print $1}')"
    else
        die "Neither sha256sum nor shasum is available to verify downloads."
    fi
    [[ "$actual" == "$expected" ]] || die "Checksum mismatch for $name. This artifact was not installed."
}

printf '\n∑ Maxi · %s installer\n\n' "$OS"

# 1. Download or verify Python backend wheel
if [[ -n "$wheel_source" ]]; then
    [[ "$(basename "$wheel_source")" == "$wheel_name" ]] || die "Expected $wheel_name"
    wheel_source="$(cd "$(dirname "$wheel_source")" && pwd -P)/$wheel_name"
    wheel="$wheel_source"
    verify "$wheel" "$(dirname "$wheel")/SHA256SUMS"
else
    printf 'Downloading the Python backend wheel…\n'
    if fetch "$raw_dist_url/SHA256SUMS" "$work_dir/SHA256SUMS" 2>/dev/null && fetch "$raw_dist_url/$wheel_name" "$work_dir/$wheel_name" 2>/dev/null; then
        wheel="$work_dir/$wheel_name"
        verify "$wheel" "$work_dir/SHA256SUMS"
    else
        fetch "$release_url/SHA256SUMS" "$work_dir/SHA256SUMS"
        fetch "$release_url/$wheel_name" "$work_dir/$wheel_name"
        wheel="$work_dir/$wheel_name"
        verify "$wheel" "$work_dir/SHA256SUMS"
    fi
fi

mkdir -p "$install_dir" "$bin_dir"
chmod 700 "$install_dir"
if [[ "$OS" == "Darwin" ]]; then
    mkdir -p "$apps_dir"
fi

# Stop any running Maxi daemon before proceeding
if [[ -f "$install_dir/daemon.pid" ]]; then
    old_pid="$(cat "$install_dir/daemon.pid" 2>/dev/null || true)"
    if [[ -n "$old_pid" ]] && kill -0 "$old_pid" 2>/dev/null; then
        printf 'Stopping existing Maxi daemon (PID %s)…\n' "$old_pid"
        kill "$old_pid" 2>/dev/null || true
        for _ in 1 2 3; do
            if ! kill -0 "$old_pid" 2>/dev/null; then break; fi
            sleep 0.5
        done
        if kill -0 "$old_pid" 2>/dev/null; then
            kill -9 "$old_pid" 2>/dev/null || true
        fi
    fi
fi
if [[ "$OS" == "Linux" ]] && command -v systemctl >/dev/null 2>&1; then
    systemctl --user stop maxi 2>/dev/null || true
fi

# Clean previous runtime data and cache on curl install
if [[ "$delete_old_data" -eq 1 ]]; then
    printf 'Cleaning previous runtime data, cache, and temporary files…\n'
    rm -rf "$install_dir/cache" "$install_dir/tmp" "$install_dir/history.jsonl" "$install_dir"/*.sock 2>/dev/null || true
    rm -f "$install_dir/daemon.pid" "$install_dir/daemon.port" "$install_dir/hud.pid" "$install_dir/daemon.log" 2>/dev/null || true
fi

# 2. Setup standalone uv & managed Python 3.12 (no root / sudo required)
uv_bin="$install_dir/tools/uv"
if [[ ! -x "$uv_bin" ]]; then
    printf 'Setting up Maxi’s Python installer…\n'
    fetch "https://astral.sh/uv/${uv_version}/install.sh" "$work_dir/uv-install.sh"
    UV_UNMANAGED_INSTALL="$install_dir/tools" sh "$work_dir/uv-install.sh"
fi
export UV_PYTHON_INSTALL_DIR="$install_dir/python"
export UV_CACHE_DIR="$install_dir/cache/uv"
export UV_PYTHON_DOWNLOADS=automatic
export UV_NO_CONFIG=1
venv="$install_dir/venv"
if [[ ! -x "$venv/bin/python" ]]; then
    if [[ -e "$venv" ]]; then
        printf 'Removing incomplete virtual environment at %s…\n' "$venv"
        rm -rf "$venv"
    fi
    printf 'Preparing Python 3.12 (downloaded automatically if needed)…\n'
    "$uv_bin" venv --managed-python --python 3.12 --seed "$venv"
fi
"$venv/bin/python" -c 'import sys; assert sys.version_info >= (3, 10), "Python 3.10+ is required"'

# 3. Audio dependency check for Linux
if [[ "$OS" == "Linux" ]]; then
    if ! command -v ldconfig >/dev/null 2>&1 || ! ldconfig -p 2>/dev/null | grep -q "libportaudio"; then
        printf 'Checking audio libraries for voice push-to-talk…\n'
        if command -v apt-get >/dev/null 2>&1 && command -v sudo >/dev/null 2>&1 && sudo -n true 2>/dev/null; then
            sudo apt-get update -qq && sudo apt-get install -y -qq libasound2-dev portaudio19-dev 2>/dev/null || true
        elif command -v pacman >/dev/null 2>&1 && command -v sudo >/dev/null 2>&1 && sudo -n true 2>/dev/null; then
            sudo pacman -S --noconfirm portaudio alsa-lib 2>/dev/null || true
        elif command -v dnf >/dev/null 2>&1 && command -v sudo >/dev/null 2>&1 && sudo -n true 2>/dev/null; then
            sudo dnf install -y portaudio-devel alsa-lib-devel 2>/dev/null || true
        fi
    fi
fi

# 4. Install backend wheel
printf 'Installing the backend and voice dependencies…\n'
if ! "$uv_bin" pip install --python "$venv/bin/python" --only-binary :all: --reinstall-package maxi-ai "${wheel}[voice]"; then
    printf 'Voice extras failed to install. Installing core package…\n'
    "$uv_bin" pip install --python "$venv/bin/python" --only-binary :all: --reinstall-package maxi-ai "${wheel}"
fi
"$venv/bin/python" -m app.cli --version

# 5. Platform-specific Binary Installation (if condition)
target_app=""
if [[ "$OS" == "Darwin" ]]; then
    # macOS Binary (Maxi.app)
    if [[ -z "$app_source" && -n "$binary_source" ]]; then
        app_source="$binary_source"
    fi
    if [[ -z "$app_source" ]]; then
        printf 'Downloading the compiled app…\n'
        fetch "$release_url/$archive_name" "$work_dir/$archive_name"
        if [[ ! -f "$work_dir/SHA256SUMS" ]]; then
            fetch "$release_url/SHA256SUMS" "$work_dir/SHA256SUMS"
        fi
        verify "$work_dir/$archive_name" "$work_dir/SHA256SUMS"
        ditto -x -k "$work_dir/$archive_name" "$work_dir/unpacked"
        app_source="$work_dir/unpacked/Maxi.app"
    fi
    [[ -d "$app_source/Contents/Resources" ]] || die 'The Maxi.app bundle is missing.'
    app_source="$(cd "$app_source" && pwd -P)"
    resources="$app_source/Contents/Resources"

    target_app="$apps_dir/Maxi.app"
    if [[ "$app_source" == '/Applications/Maxi.app' ]]; then target_app="$app_source"; fi
    if [[ "$app_source" != "$target_app" ]]; then
        [[ ! -L "$target_app" ]] || die "Refusing to replace a symlink at $target_app"
        new_app="$apps_dir/.Maxi-install-$$.app"
        ditto "$app_source" "$new_app"
        "$venv/bin/python" - "$target_app" "$app_source" <<'PY'
import os, signal, subprocess, sys, time
from pathlib import Path
executables = {
    str(Path(app) / 'Contents/MacOS' / name)
    for app in sys.argv[1:] for name in ('MaxiHUD', 'MaxiLauncher')
}
try:
    processes = subprocess.check_output(['/bin/ps', '-axo', 'pid=,comm='], text=True)
except Exception:
    processes = ""
stopped = []
for line in processes.splitlines():
    fields = line.strip().split(None, 1)
    if len(fields) != 2 or fields[1] not in executables:
        continue
    pid = int(fields[0])
    try:
        os.kill(pid, signal.SIGTERM)
        stopped.append(pid)
    except ProcessLookupError:
        pass
deadline = time.monotonic() + 3
for pid in stopped:
    while True:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            break
        if time.monotonic() >= deadline:
            raise SystemExit('Please quit Maxi and run the installer again.')
        time.sleep(0.05)
PY
        backup_app="$apps_dir/.Maxi-previous-$$.app"
        if [[ -e "$target_app" ]]; then mv "$target_app" "$backup_app"; fi
        if ! mv "$new_app" "$target_app"; then
            [[ ! -e "$backup_app" ]] || mv "$backup_app" "$target_app"
            die 'Could not install Maxi.app.'
        fi
        [[ ! -e "$backup_app" ]] || rm -rf "$backup_app"
    fi
    printf 'Installed macOS app: %s\n' "$target_app"

elif [[ "$OS" == "Linux" ]]; then
    # Linux Binary Installation (if condition)
    if [[ -n "${binary_source:-}" && -f "$binary_source" ]]; then
        printf 'Installing Linux binary from %s…\n' "$binary_source"
        mkdir -p "$bin_dir"
        if [[ -e "$bin_dir/maxi-gui" ]]; then
            printf 'Replacing existing binary at %s/maxi-gui…\n' "$bin_dir"
            rm -f "$bin_dir/maxi-gui"
        fi
        install -m 755 "$binary_source" "$bin_dir/maxi-gui"
        printf 'Installed Linux binary: %s/maxi-gui\n' "$bin_dir"
    else
        printf 'Linux environment: running in backend daemon mode (GUI companion placeholder ready).\n'
    fi

    # Configure Linux systemd user service
    service_path="${HOME}/.config/systemd/user/maxi.service"
    mkdir -p "$(dirname "$service_path")"
    cat <<EOF > "$service_path"
[Unit]
Description=Maxi Background AI Agent Daemon
After=network.target sound.target

[Service]
ExecStart=${venv}/bin/maxi run
Restart=always
RestartSec=3

[Install]
WantedBy=default.target
EOF
    printf 'Configured Linux systemd service at %s\n' "$service_path"
fi

# 6. Setup Configuration
fresh_config=0
if [[ ! -f "$install_dir/.env" ]]; then
    if [[ "$OS" == "Darwin" && -f "${resources:-}/default.env" ]]; then
        cp "$resources/default.env" "$install_dir/.env"
    else
        cat <<'EOF' > "$install_dir/.env"
# ∑ Maxi — copy to ~/.maxi/.env and configure your providers.
HOST=127.0.0.1
PORT=4848
DEBUG=false

# Start a compatible server and install this model before using Maxi.
OPENAI_BASE_URL=http://localhost:11434/v1
OPENAI_API_KEY=ollama
OPENAI_MODEL=gemma4:31b-cloud

# Whisper-compatible speech transcription. Set a real provider key for voice.
VOICE_BASE_URL=https://api.groq.com/openai/v1
VOICE_API_KEY=
VOICE_MODEL=whisper-large-v3-turbo
ENABLE_VOICE_HOTKEY=true
VOICE_HOTKEY=auto

# Speech synthesis
ENABLE_TTS=true
TTS_PROVIDER=siri
TTS_VOICE=Tara
TTS_BASE_URL=http://127.0.0.1:8880/v1
AGENT_TIMEOUT_SECONDS=90
EOF
    fi
    chmod 600 "$install_dir/.env"
    fresh_config=1
else
    # Update existing configuration: ensure default model is gemma4:31b-cloud
    if grep -q "^OPENAI_MODEL=" "$install_dir/.env"; then
        sed -i.bak -E 's/^OPENAI_MODEL=.*/OPENAI_MODEL=gemma4:31b-cloud/' "$install_dir/.env" 2>/dev/null || true
        rm -f "$install_dir/.env.bak"
    else
        echo 'OPENAI_MODEL=gemma4:31b-cloud' >> "$install_dir/.env"
    fi
fi

if [[ ! -f "$install_dir/mcp_config.json" ]]; then
    printf '{"mcpServers":{}}\n' > "$install_dir/mcp_config.json"
fi

# 7. Symlink CLI
ln -sfn "$venv/bin/maxi" "$bin_dir/maxi"

# Ensure ~/.local/bin is permanently in shell config
for rc in "${HOME}/.bashrc" "${HOME}/.zshrc"; do
    if [ -f "$rc" ] && ! grep -q '\.local/bin' "$rc" 2>/dev/null; then
        echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$rc"
    fi
done

printf '\nCLI: %s\n' "$bin_dir/maxi"
if [[ "$delete_old_data" -eq 1 ]]; then
    printf 'Old cache and temporary session data cleared. Configuration updated.\n'
else
    printf 'Existing configuration, chats, and saved memories were preserved.\n'
fi

# 8. Interactive Configuration Wizard
if [[ "$configure" -eq 1 && "$fresh_config" -eq 1 ]]; then
    if ( : < /dev/tty ) 2>/dev/null; then
        printf '\nConfigure your model and voice provider:\n'
        "$venv/bin/python" -m app.cli config wizard < /dev/tty
    else
        printf '\nRun this in a terminal to configure your providers:\n  %q config wizard\n' "$bin_dir/maxi"
        launch=0
    fi
fi

# 9. Launch Daemon
if [[ "$launch" -eq 1 ]]; then
    printf '\nStarting the Python backend…\n'
    backend_action=start
    if [[ -f "$install_dir/daemon.pid" ]]; then backend_action=restart; fi
    (cd "$install_dir" && "$venv/bin/python" -m app.cli "$backend_action")
    if [[ "$OS" == "Darwin" && "$open_hud" -eq 1 && -n "$target_app" && -d "$target_app" ]]; then
        printf '\nOpening the Maxi HUD…\n'
        open "$target_app"
    fi
fi

if [[ "$OS" == "Darwin" ]]; then
    printf '\nIf macOS blocks this unsigned beta, review Maxi in Privacy & Security.\n'
    printf 'Allow Microphone and Accessibility/Input Monitoring when requested.\n'
    printf 'Hotkey: Hold Right Option to speak.\n'
else
    printf '\nHotkey: Hold Control + Space to speak.\n'
    printf 'To enable at boot: systemctl --user enable --now maxi\n'
fi
printf 'Start the configured model server before sending a request.\n'
