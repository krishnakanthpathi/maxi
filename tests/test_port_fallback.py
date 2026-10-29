"""Tests for port fallback and port discovery mechanisms."""
import socket
from pathlib import Path
from unittest.mock import MagicMock
import pytest
from app import cli


def test_resolve_listen_port_fallback():
    # Bind a socket to a free ephemeral port to simulate port collision
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        occupied_port = s.getsockname()[1]

        # resolve_listen_port should detect collision and return next port
        next_port = cli.resolve_listen_port(occupied_port, host="127.0.0.1")
        assert next_port != occupied_port
        assert next_port >= occupied_port + 1


def test_get_active_port_from_port_file(monkeypatch, tmp_path):
    port_file = tmp_path / "daemon.port"
    monkeypatch.setattr(cli, "PORT_FILE", port_file)
    port_file.write_text("4849\n")

    assert cli.get_active_port() == 4849


def test_backend_health_finds_fallback_port(monkeypatch, tmp_path):
    port_file = tmp_path / "daemon.port"
    monkeypatch.setattr(cli, "PORT_FILE", port_file)
    port_file.write_text("4849")

    response = MagicMock(status_code=200)
    response.json.return_value = {"status": "ok", "service": "Maxi Agent Daemon"}

    def fake_get(url, **kwargs):
        if ":4849/" in url:
            return response
        raise cli.httpx.ConnectError("Connection refused")

    monkeypatch.setattr(cli.httpx, "get", fake_get)
    health = cli.backend_health()
    assert health is not None
    assert health["status"] == "ok"
    assert health["active_port"] == 4849
