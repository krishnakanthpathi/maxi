"""Exercise the installer in isolated directories, without touching the host setup."""
import hashlib
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "scripts/install_macos.sh"
WHEEL = "maxi_ai-0.3.0b1-py3-none-any.whl"


def executable(path, body):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/bash\nset -eu\n" + body)
    path.chmod(0o755)


def setup(tmp_path):
    # Spaces in a home/app path must survive every installer invocation.
    prefix = tmp_path / "user data"
    apps = tmp_path / "My Apps"
    bins = tmp_path / "local bin"
    tools = tmp_path / "test-tools"
    source = tmp_path / "Mounted Disk/Maxi.app"
    resources = source / "Contents/Resources"
    resources.mkdir(parents=True)
    wheel = resources / WHEEL
    wheel.write_bytes(b"test wheel bytes")
    (resources / "BACKEND-SHA256SUMS").write_text(f"{hashlib.sha256(wheel.read_bytes()).hexdigest()}  {WHEEL}\n")
    (resources / "default.env").write_text("OPENAI_MODEL=test-default\n")
    executable(tools / "uname", 'case "$1" in -s) echo Darwin;; -m) echo arm64;; esac\n')
    executable(tools / "sw_vers", 'echo 14.0\n')
    executable(tools / "ditto", '/bin/cp -R "$1" "$2"\n')
    executable(tools / "open", 'echo UNEXPECTED_LAUNCH >&2; exit 99\n')
    executable(prefix / "tools/uv", '''
echo "$*" >> "$MAXI_INSTALL_DIR/uv.calls"
if [[ "$1" == venv ]]; then
    venv="${@: -1}"
    mkdir -p "$venv/bin"
    cat > "$venv/bin/python" <<'STUB'
#!/bin/bash
echo "$*" >> "$MAXI_INSTALL_DIR/python.calls"
if [[ "${MAXI_TEST_FAIL_READY:-0}" == 1 && "$#" == 2 && "$1" == - ]]; then exit 2; fi
if [[ "$*" == '-m app.cli start' ]]; then printf '%s' "$PWD" > "$MAXI_INSTALL_DIR/start.cwd"; fi
if [[ "$*" == *--version* ]]; then echo 'maxi 0.3.0b1'; fi
STUB
    chmod +x "$venv/bin/python"
    cp "$venv/bin/python" "$venv/bin/maxi"
fi
''')
    env = dict(os.environ, MAXI_INSTALL_DIR=str(prefix), MAXI_APPS_DIR=str(apps),
               MAXI_BIN_DIR=str(bins), PATH=f"{tools}:{os.environ['PATH']}")
    return prefix, apps, bins, source, env


def run(source, env, *options, launch=False):
    return subprocess.run(["/bin/bash", str(INSTALLER), "--app-source", str(source),
                           "--no-configure", *options, *([] if launch else ["--no-launch"])], env=env,
                          capture_output=True, text=True, timeout=20)


def test_fresh_install_without_python_installs_app_and_voice(tmp_path):
    prefix, apps, bins, source, env = setup(tmp_path)
    result = run(source, env)
    assert result.returncode == 0, result.stdout + result.stderr
    assert (apps / "Maxi.app/Contents/Resources" / WHEEL).is_file()
    assert (bins / "maxi").resolve() == prefix / "venv/bin/maxi"
    calls = (prefix / "uv.calls").read_text()
    assert "venv --managed-python --python 3.12 --seed" in calls
    assert "--only-binary :all:" in calls and "[voice]" in calls
    assert "maxi 0.3.0b1" in result.stdout
    assert '-m app.cli start' not in (prefix / 'python.calls').read_text()


def test_reinstall_preserves_config_memories_and_existing_runtime(tmp_path):
    prefix, apps, bins, source, env = setup(tmp_path)
    assert run(source, env).returncode == 0
    (prefix / ".env").write_text("OPENAI_MODEL=keep-this\n")
    (prefix / "mcp_config.json").write_text('{"mcpServers":{"keep":{}}}')
    (prefix / "memories.db").write_bytes(b"keep my memories")
    (prefix / "uv.calls").write_text("")
    result = run(source, env)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "venv " not in (prefix / "uv.calls").read_text()
    assert (prefix / ".env").read_text() == "OPENAI_MODEL=keep-this\n"
    assert "keep" in (prefix / "mcp_config.json").read_text()
    assert (prefix / "memories.db").read_bytes() == b"keep my memories"
    assert not list(apps.glob(".Maxi-*.app"))


def test_bad_checksum_stops_before_install_or_config_change(tmp_path):
    prefix, apps, bins, source, env = setup(tmp_path)
    (source / "Contents/Resources" / WHEEL).write_bytes(b"corrupted")
    result = run(source, env)
    assert result.returncode != 0 and "Checksum mismatch" in result.stderr
    assert not (prefix / "uv.calls").exists()
    assert not (prefix / ".env").exists()
    assert not apps.exists()


def test_unsupported_os_stops_before_install(tmp_path):
    prefix, apps, bins, source, env = setup(tmp_path)
    tools = Path(env["PATH"].split(":")[0])
    executable(tools / "sw_vers", 'echo 13.7\n')
    result = run(source, env)
    assert result.returncode != 0 and "macOS 14" in result.stderr
    assert not (prefix / "uv.calls").exists()


def test_install_starts_and_checks_backend_before_opening_hud(tmp_path):
    prefix, apps, bins, source, env = setup(tmp_path)
    tools = Path(env['PATH'].split(':')[0])
    executable(tools / 'open', 'echo open >> "$MAXI_INSTALL_DIR/python.calls"\n')
    result = run(source, env, launch=True)
    assert result.returncode == 0, result.stdout + result.stderr
    calls = (prefix / 'python.calls').read_text().splitlines()
    assert calls.index('-m app.cli start') < calls.index(f'- {prefix}/daemon.log') < calls.index('open')
    assert (prefix / 'start.cwd').read_text() == str(prefix)


def test_install_does_not_open_hud_when_backend_is_unhealthy(tmp_path):
    prefix, apps, bins, source, env = setup(tmp_path)
    env['MAXI_TEST_FAIL_READY'] = '1'
    result = run(source, env, launch=True)
    assert result.returncode != 0
    assert '-m app.cli start' in (prefix / 'python.calls').read_text()
    assert 'UNEXPECTED_LAUNCH' not in result.stderr
    assert 'Opening the Maxi HUD' not in result.stdout


def test_no_hud_starts_backend_without_opening_gui(tmp_path):
    prefix, apps, bins, source, env = setup(tmp_path)
    result = run(source, env, '--no-hud', launch=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert '-m app.cli start' in (prefix / 'python.calls').read_text()
    assert 'UNEXPECTED_LAUNCH' not in result.stderr
