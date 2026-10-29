"""Protect the memory integration from stale binaries and misleading success."""
import os
from pathlib import Path
import subprocess
from unittest.mock import patch

import pytest

from app.core import lmem_tools


def test_active_environment_takes_precedence_over_fallback_install(monkeypatch, tmp_path):
    active = tmp_path / 'active'
    home = tmp_path / 'home'
    stale = home / '.local/bin'
    for directory, version in ((active, 'current'), (stale, 'stale')):
        directory.mkdir(parents=True)
        executable = directory / 'lmem'
        executable.write_text(f'#!/bin/sh\nprintf {version}')
        executable.chmod(0o755)
    monkeypatch.setattr(Path, 'home', lambda: home)
    monkeypatch.setenv('PATH', str(active))
    monkeypatch.delenv('MAXI_LMEM_BIN', raising=False)
    assert lmem_tools._run_lmem(['--version']) == 'current'


def test_explicit_binary_override_is_used(monkeypatch):
    monkeypatch.setenv('MAXI_LMEM_BIN', '/custom/lmem')
    with patch('app.core.lmem_tools.subprocess.run', return_value=subprocess.CompletedProcess([], 0, 'ok', '')) as run:
        assert lmem_tools._run_lmem(['stats']) == 'ok'
    assert run.call_args.args[0][0] == '/custom/lmem'


def test_schema_error_in_stderr_is_not_hidden_by_stdout():
    result = subprocess.CompletedProcess([], 1, 'Initializing storage', 'Database schema is newer than this version of LightMem')
    with patch('app.core.lmem_tools.subprocess.run', return_value=result):
        output = lmem_tools.lmem_remember.invoke({'content': 'Test memory'})
    assert output.startswith('Error:')
    assert 'Upgrade' in output and 'do not downgrade or recreate' in output
    assert 'schema is newer' in output


@pytest.mark.parametrize('stdout,stderr', [('', ''), ('Ready', 'write failed')])
def test_nonzero_exit_always_reports_failure(stdout, stderr):
    with patch('app.core.lmem_tools.subprocess.run', return_value=subprocess.CompletedProcess([], 2, stdout, stderr)):
        assert lmem_tools._run_lmem(['remember', 'Test memory']).startswith('Error:')


def test_empty_output_does_not_confirm_a_save():
    with patch('app.core.lmem_tools.subprocess.run', return_value=subprocess.CompletedProcess([], 0, '', '')):
        assert 'without confirming' in lmem_tools._run_lmem(['remember', 'Test memory'])


@pytest.mark.parametrize('failure', [FileNotFoundError(), subprocess.TimeoutExpired(['lmem'], 12)])
def test_missing_or_slow_cli_reports_an_error(failure):
    with patch('app.core.lmem_tools.subprocess.run', side_effect=failure):
        assert lmem_tools._run_lmem(['remember', 'Test memory']).startswith('Error:')
