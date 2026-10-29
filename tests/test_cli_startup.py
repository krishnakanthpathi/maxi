"""A live process is not proof that the API used by the HUD is ready."""
from argparse import Namespace
from unittest.mock import MagicMock

import pytest

from app import cli


@pytest.fixture
def startup(monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "PID_FILE", tmp_path / "daemon.pid")
    monkeypatch.setattr(cli, "get_pid", lambda: None)
    monkeypatch.setattr(cli.time, "sleep", lambda _: None)
    process = MagicMock(pid=1234)
    process.poll.return_value = None
    spawn = MagicMock(return_value=process)
    monkeypatch.setattr(cli.subprocess, "Popen", spawn)
    return process, spawn


def test_start_waits_for_own_api_not_just_live_process(startup, monkeypatch):
    process, spawn = startup
    health = MagicMock(side_effect=[None, None, {"pid": 999}, {"pid": process.pid}])
    monkeypatch.setattr(cli, "backend_health", health)
    cli.cmd_start(Namespace(timeout=1))
    assert health.call_count == 4
    process.terminate.assert_not_called()
    assert spawn.call_args.args[0][0] == cli.sys.executable
    assert spawn.call_args.kwargs["stdin"] == cli.subprocess.DEVNULL
    assert spawn.call_args.kwargs["cwd"] == str(cli.PID_FILE.parent)


@pytest.mark.parametrize("alive", [True, False])
def test_start_failure_is_nonzero_and_cleans_up_owned_child(startup, monkeypatch, alive):
    process, _ = startup
    process.poll.return_value = None if alive else 1
    monkeypatch.setattr(cli, "backend_health", lambda: None)
    cli.PID_FILE.write_text(str(process.pid))
    with pytest.raises(SystemExit, match="did not become healthy"):
        cli.cmd_start(Namespace(timeout=0.001))
    assert not cli.PID_FILE.exists()
    assert process.terminate.called == alive


def test_healthy_existing_backend_is_reused(startup, monkeypatch):
    _, spawn = startup
    monkeypatch.setattr(cli, "backend_health", lambda: {"pid": 99})
    cli.cmd_start(Namespace(timeout=1))
    spawn.assert_not_called()


def test_start_with_restart_forces_stop_and_spawn(startup, monkeypatch):
    process, spawn = startup
    stop_called = []
    monkeypatch.setattr(cli, "cmd_stop", lambda _: stop_called.append(True))
    monkeypatch.setattr(cli, "backend_health", MagicMock(side_effect=[None, {"pid": process.pid}]))
    cli.cmd_start(Namespace(timeout=1, restart=True))
    assert len(stop_called) == 1
    spawn.assert_called_once()



def test_live_pid_without_api_is_not_reported_as_success(startup, monkeypatch):
    _, spawn = startup
    monkeypatch.setattr(cli, "get_pid", lambda: 99)
    monkeypatch.setattr(cli, "backend_health", lambda: None)
    with pytest.raises(SystemExit, match="API is unavailable"):
        cli.cmd_start(Namespace(timeout=1))
    spawn.assert_not_called()


@pytest.mark.parametrize("payload", [{"status": "ok", "service": "other"}, [], "ok"])
def test_health_rejects_unrelated_service(monkeypatch, payload):
    response = MagicMock()
    response.json.return_value = payload
    monkeypatch.setattr(cli.httpx, "get", lambda *a, **kw: response)
    assert cli.backend_health() is None
