"""Install the real wheel outside the checkout and exercise its HTTP/WS lifecycle."""
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import zipfile

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(not shutil.which("uv"), reason="Wheel integration requires uv")
def test_wheel_backend_runs_without_source_or_frontend(tmp_path):
    dist = tmp_path / "dist"
    subprocess.run(["uv", "build", "--wheel", "--out-dir", str(dist), str(ROOT)], check=True, capture_output=True)
    wheel = next(dist.glob("*.whl"))
    with zipfile.ZipFile(wheel) as archive:
        assert not any(name.startswith("frontends/") or name.endswith(".swift") for name in archive.namelist())
        assert "app/sounds/minimal_wake.mp3" in archive.namelist()
    venv = tmp_path / "runtime"
    subprocess.run(["uv", "venv", "--python", sys.executable, str(venv)], check=True, capture_output=True)
    python = venv / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    subprocess.run(["uv", "pip", "install", "--python", str(python), str(wheel)], check=True, capture_output=True)
    isolated_home = tmp_path / "user"
    isolated_home.mkdir()
    config = isolated_home / ".maxi"
    config.mkdir()
    (config / "mcp_config.json").write_text('{"mcpServers":{}}')
    (config / "skills").mkdir()
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    env = dict(os.environ, HOME=str(isolated_home), USERPROFILE=str(isolated_home),
               ENABLE_VOICE_HOTKEY="false", ENABLE_TTS="false", DEBUG="false", HOST="127.0.0.1", PORT=str(port),
               MAXI_MCP_CONFIG=str(config / "mcp_config.json"), MAXI_SKILLS_DIR=str(config / "skills"))
    env.pop("PYTHONPATH", None)

    def cli(*args, check=True):
        result = subprocess.run([str(python), "-m", "app.cli", *args], cwd=tmp_path, env=env,
                                capture_output=True, text=True, timeout=45)
        if check:
            log = (config / "daemon.log").read_text() if (config / "daemon.log").exists() else ""
            assert result.returncode == 0, result.stdout + result.stderr + log
        return result

    try:
        assert "0.3.0b1" in cli("--version").stdout
        assert "healthy" in cli("start").stdout
        assert cli("start", "--for-hud", check=False).returncode != 0
        first_pid = (config / "daemon.pid").read_text()
        assert cli("run", check=False).returncode != 0
        assert (config / "daemon.pid").read_text() == first_pid
        assert "already healthy" in cli("start").stdout
        assert (config / "daemon.pid").read_text() == first_pid
        # Check precisely the routes consumed by Swift, using only the installed runtime.
        probe = '''
import asyncio, json, sys, httpx
from websockets.asyncio.client import connect
import app
assert 'site-packages' in app.__file__, app.__file__
base = 'http://127.0.0.1:' + sys.argv[1]
with httpx.Client(base_url=base, trust_env=False) as client:
    health = client.get('/api/health').json()
    assert health['status'] == 'ok' and health['pid'] == int(sys.argv[2])
    for path in ('/api/config', '/api/tts', '/api/mcp/tools'):
        assert client.get(path).status_code == 200, path
    assert client.post('/api/context/clear').json()['status'] == 'cleared'
    assert client.post('/api/voice/cancel').json()['status'] == 'cancelled'
    assert client.post('/api/tts/stop').json()['status'] == 'stopped'
    assert client.post('/api/config', json={'model': 'wheel-smoke-test'}).json()['status'] == 'updated'
    assert client.post('/api/reload').json()['status'] == 'reloaded'
async def ws():
    async with connect('ws://127.0.0.1:' + sys.argv[1] + '/ws') as socket:
        await (await socket.ping())
asyncio.run(ws())
'''
        result = subprocess.run([str(python), "-c", probe, str(port), first_pid], cwd=tmp_path, env=env,
                                capture_output=True, text=True, timeout=20)
        assert result.returncode == 0, result.stdout + result.stderr
        cli("stop")
        assert not (config / "daemon.pid").exists()
        assert "healthy" in cli("start").stdout
        assert (config / "daemon.pid").read_text() != first_pid
    finally:
        cli("stop", check=False)
