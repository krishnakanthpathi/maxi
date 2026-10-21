#!/bin/bash
# Install the prebuilt Maxi app and its Python backend without Homebrew or Xcode.
# curl -fsSL https://raw.githubusercontent.com/krishnakanthpathi/maxi/main/scripts/install_macos.sh | bash
set -euo pipefail

release='0.3.0-beta.1'
python_version='0.3.0b1'
uv_version='0.11.32'
release_url="https://github.com/krishnakanthpathi/maxi/releases/download/v${release}"
archive_name="Maxi-${release}-macos-universal.zip"
wheel_name="maxi_ai-${python_version}-py3-none-any.whl"
install_dir="${MAXI_INSTALL_DIR:-$HOME/.maxi}"
apps_dir="${MAXI_APPS_DIR:-$HOME/Applications}"
bin_dir="${MAXI_BIN_DIR:-$HOME/.local/bin}"
app_source=''
configure=1
launch=1

die() { printf 'Maxi: %s\n' "$*" >&2; exit 1; }
while [[ $# -gt 0 ]]; do
    case "$1" in
        --app-source) [[ $# -ge 2 ]] || die '--app-source needs a path'; app_source="$2"; shift 2 ;;
        --no-configure) configure=0; shift ;;
        --no-launch) launch=0; shift ;;
        --help|-h)
            printf '%s\n' 'Install Maxi for macOS 14+ (Apple Silicon and Intel).' \
                '  --app-source PATH  Use a bundled Maxi.app instead of downloading it.' \
                '  --no-configure     Skip the interactive provider wizard.' \
                '  --no-launch        Install without starting the daemon or HUD.' \
                'Existing provider configuration and saved memories are preserved.'
            exit 0 ;;
        *) die "Unknown option: $1" ;;
    esac
done
[[ "$(uname -s)" == Darwin ]] || die 'This installer is for macOS. See the docs for Linux/Windows.'
case "$(uname -m)" in arm64|x86_64) ;; *) die 'Unsupported Mac architecture.' ;; esac
os_major="$(sw_vers -productVersion | cut -d. -f1)"
[[ "$os_major" -ge 14 ]] || die 'Maxi needs macOS 14 or later.'
[[ "$EUID" -ne 0 ]] || die 'Run this as your normal user, without sudo.'
for directory in "$install_dir" "$apps_dir" "$bin_dir"; do
    [[ "$directory" == /* ]] || die "Installation paths must be absolute: $directory"
done

work_dir="$(mktemp -d "${TMPDIR:-/tmp}/maxi-install.XXXXXX")"
trap 'rm -rf "$work_dir"' EXIT
fetch() { curl --fail --location --silent --show-error --retry 3 --connect-timeout 20 --output "$2" "$1"; }
verify() {
    local path="$1" manifest="$2" name expected actual
    name="$(basename "$path")"
    expected="$(awk -v name="$name" '$2 == name { print $1 }' "$manifest")"
    [[ "$expected" =~ ^[a-fA-F0-9]{64}$ ]] || die "No unique checksum for $name"
    actual="$(shasum -a 256 "$path" | awk '{print $1}')"
    [[ "$actual" == "$expected" ]] || die "Checksum mismatch for $name. Nothing was installed."
}

printf '\n∑ Maxi · macOS installer\n\n'
if [[ -z "$app_source" ]]; then
    printf 'Downloading the compiled app…\n'
    fetch "$release_url/$archive_name" "$work_dir/$archive_name"
    fetch "$release_url/SHA256SUMS" "$work_dir/SHA256SUMS"
    verify "$work_dir/$archive_name" "$work_dir/SHA256SUMS"
    ditto -x -k "$work_dir/$archive_name" "$work_dir/unpacked"
    app_source="$work_dir/unpacked/Maxi.app"
fi
[[ -d "$app_source/Contents/Resources" ]] || die 'The Maxi.app bundle is missing.'
app_source="$(cd "$app_source" && pwd -P)"
resources="$app_source/Contents/Resources"
wheel="$resources/$wheel_name"
[[ -f "$wheel" && -f "$resources/BACKEND-SHA256SUMS" ]] || die 'The bundled backend is missing.'
verify "$wheel" "$resources/BACKEND-SHA256SUMS"

mkdir -p "$install_dir" "$apps_dir" "$bin_dir"
chmod 700 "$install_dir"

# uv is a native executable: bootstrapping it does not require Python.
# Keep tools and any downloaded Python private to Maxi, without editing profiles.
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
    [[ ! -e "$venv" ]] || die "An incomplete environment exists at $venv. Move it aside and retry."
    printf 'Preparing Python 3.12 (downloaded automatically if needed)…\n'
    "$uv_bin" venv --managed-python --python 3.12 --seed "$venv"
fi
"$venv/bin/python" -c 'import sys; assert sys.version_info >= (3, 10), "Python 3.10+ is required"'
printf 'Installing the backend and voice dependencies…\n'
"$uv_bin" pip install --python "$venv/bin/python" --only-binary :all: "${wheel}[voice]"
"$venv/bin/python" -m app.cli --version
"$venv/bin/python" -c 'from importlib.util import find_spec; assert all(find_spec(m) for m in ("sounddevice", "pynput", "numpy")), "Voice dependencies are missing"'

fresh_config=0
if [[ ! -f "$install_dir/.env" ]]; then
    cp "$resources/default.env" "$install_dir/.env"
    chmod 600 "$install_dir/.env"
    fresh_config=1
fi
if [[ ! -f "$install_dir/mcp_config.json" ]]; then
    printf '{"mcpServers":{}}\n' > "$install_dir/mcp_config.json"
fi

target_app="$apps_dir/Maxi.app"
# A user who already dragged the app into Applications can keep that copy.
if [[ "$app_source" == '/Applications/Maxi.app' ]]; then target_app="$app_source"; fi
if [[ "$app_source" != "$target_app" ]]; then
    [[ ! -L "$target_app" ]] || die "Refusing to replace a symlink at $target_app"
    new_app="$apps_dir/.Maxi-install-$$.app"
    ditto "$app_source" "$new_app"
    # Opening an already-running old bundle can leave its old, hidden HUD alive.
    # Stop only GUI processes from the exact app copies being replaced; keep
    # the daemon, recording state, and conversation running independently.
    "$venv/bin/python" - "$target_app" "$app_source" <<'PY'
import os, signal, subprocess, sys, time
from pathlib import Path
executables = {
    str(Path(app) / 'Contents/MacOS' / name)
    for app in sys.argv[1:] for name in ('MaxiHUD', 'MaxiLauncher')
}
processes = subprocess.check_output(['/bin/ps', '-axo', 'pid=,comm='], text=True)
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
ln -sfn "$venv/bin/maxi" "$bin_dir/maxi"

printf '\nInstalled app: %s\nCLI: %s\n' "$target_app" "$bin_dir/maxi"
printf 'Existing configuration, chats, and saved memories were preserved.\n'
if [[ "$configure" -eq 1 && "$fresh_config" -eq 1 ]]; then
    if ( : < /dev/tty ) 2>/dev/null; then
        printf '\nConfigure your model and voice provider:\n'
        "$venv/bin/python" -m app.cli config wizard < /dev/tty
    else
        printf '\nRun this in a terminal to configure your providers:\n  %q config wizard\n' "$bin_dir/maxi"
        launch=0
    fi
fi
if [[ "$launch" -eq 1 ]]; then
    printf '\nOpening Maxi (the app starts the daemon automatically)…\n'
    open "$target_app"
fi
printf '\nIf macOS blocks this unsigned beta, review Maxi in Privacy & Security.\n'
printf 'Allow Microphone and Accessibility/Input Monitoring when requested.\n'
printf 'Start the configured model server before sending a request.\n'
