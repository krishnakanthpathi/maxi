"""Exercise the universal installer scripts/install.sh across platforms."""
import hashlib
import os
from pathlib import Path
import subprocess
import pytest

ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "scripts/install.sh"
WHEEL = "maxi_ai-0.3.0b1-py3-none-any.whl"


def executable(path, body):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/bash\nset -eu\n" + body)
    path.chmod(0o755)


def setup_env(tmp_path, platform="Linux"):
    prefix = tmp_path / "user data"
    apps = tmp_path / "My Apps"
    bins = tmp_path / "local bin"
    tools = tmp_path / "test-tools"
    home = tmp_path / "fake-home"
    home.mkdir(parents=True, exist_ok=True)
    
    wheel = tmp_path / "release wheels" / WHEEL
    wheel.parent.mkdir(parents=True, exist_ok=True)
    wheel.write_bytes(b"test wheel bytes")
    (wheel.parent / "SHA256SUMS").write_text(f"{hashlib.sha256(wheel.read_bytes()).hexdigest()}  {WHEEL}\n")

    source = tmp_path / "Mounted Disk/Maxi.app"
    resources = source / "Contents/Resources"
    resources.mkdir(parents=True)
    (resources / "default.env").write_text("OPENAI_MODEL=gemma2:31b-cloud\n")

    if platform == "Darwin":
        executable(tools / "uname", 'case "$1" in -s) echo Darwin;; -m) echo arm64;; esac\n')
        executable(tools / "sw_vers", 'echo 14.0\n')
    else:
        executable(tools / "uname", 'case "$1" in -s) echo Linux;; -m) echo x86_64;; esac\n')
        executable(tools / "ldconfig", 'exit 0\n')

    executable(tools / "ditto", 'echo app-copy >> "$MAXI_INSTALL_DIR/uv.calls"; /bin/cp -R "$1" "$2"\n')
    executable(tools / "open", 'echo UNEXPECTED_LAUNCH >&2; exit 99\n')

    executable(prefix / "tools/uv", '''
echo "$*" >> "$MAXI_INSTALL_DIR/uv.calls"
if [[ "$1" == venv ]]; then
    venv="${@: -1}"
    mkdir -p "$venv/bin"
    cat > "$venv/bin/python" <<'STUB'
#!/bin/bash
echo "$*" >> "$MAXI_INSTALL_DIR/python.calls"
if [[ "$*" == *--version* ]]; then echo 'maxi 0.3.0b1'; fi
STUB
    chmod +x "$venv/bin/python"
    cp "$venv/bin/python" "$venv/bin/maxi"
fi
''')

    env = dict(
        os.environ,
        HOME=str(home),
        MAXI_INSTALL_DIR=str(prefix),
        MAXI_APPS_DIR=str(apps),
        MAXI_BIN_DIR=str(bins),
        MAXI_TEST_WHEEL=str(wheel),
        PATH=f"{tools}:{os.environ['PATH']}",
    )
    return prefix, apps, bins, source, home, env


def test_universal_installer_linux(tmp_path):
    prefix, apps, bins, source, home, env = setup_env(tmp_path, platform="Linux")

    proc = subprocess.run(
        [
            "/bin/bash",
            str(INSTALLER),
            "--wheel-source",
            env["MAXI_TEST_WHEEL"],
            "--no-configure",
            "--no-launch",
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert proc.returncode == 0, f"Installer failed:\nstdout: {proc.stdout}\nstderr: {proc.stderr}"
    assert "Linux installer" in proc.stdout
    assert "CLI:" in proc.stdout

    # Check symlink
    assert (bins / "maxi").is_symlink()

    # Check systemd user service created
    service_file = home / ".config/systemd/user/maxi.service"
    assert service_file.exists()
    content = service_file.read_text()
    assert "ExecStart=" in content
    assert "maxi run" in content

    # Check default .env created with gemma2:31b-cloud
    env_file = prefix / ".env"
    assert env_file.exists()
    assert "gemma2:31b-cloud" in env_file.read_text()


def test_universal_installer_linux_custom_binary(tmp_path):
    prefix, apps, bins, source, home, env = setup_env(tmp_path, platform="Linux")
    fake_gui = tmp_path / "my-maxi-gui"
    fake_gui.write_text("#!/bin/bash\necho gui\n")
    fake_gui.chmod(0o755)

    proc = subprocess.run(
        [
            "/bin/bash",
            str(INSTALLER),
            "--wheel-source",
            env["MAXI_TEST_WHEEL"],
            "--binary-source",
            str(fake_gui),
            "--no-configure",
            "--no-launch",
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert proc.returncode == 0
    assert (bins / "maxi-gui").exists()


def test_universal_installer_macos(tmp_path):
    prefix, apps, bins, source, home, env = setup_env(tmp_path, platform="Darwin")

    proc = subprocess.run(
        [
            "/bin/bash",
            str(INSTALLER),
            "--wheel-source",
            env["MAXI_TEST_WHEEL"],
            "--app-source",
            str(source),
            "--no-configure",
            "--no-launch",
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert proc.returncode == 0, f"Installer failed:\nstdout: {proc.stdout}\nstderr: {proc.stderr}"
    assert "Darwin installer" in proc.stdout
    assert (apps / "Maxi.app").exists()
    assert (bins / "maxi").is_symlink()
