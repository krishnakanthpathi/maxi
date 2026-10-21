import asyncio
import threading
from unittest.mock import MagicMock

import numpy as np
import pytest

from app.config import settings
from app.core.agent import agent
from app.core.voice_service import MaxiVoiceService


@pytest.fixture
def service(monkeypatch):
    svc = MaxiVoiceService()
    for name in ("_broadcast", "_open_mic_stream", "_close_mic_stream", "_capture_context_background"):
        monkeypatch.setattr(svc, name, MagicMock())
    for name in ("play_sound", "audio_ducker", "tts_service"):
        monkeypatch.setattr(f"app.core.voice_service.{name}", MagicMock())
    monkeypatch.setattr(settings, "enable_tts", False)
    return svc


@pytest.fixture
def event_loop_thread():
    loop = asyncio.new_event_loop()
    ready = threading.Event()
    loop.call_soon(ready.set)
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    thread.start()
    assert ready.wait(2)
    try:
        yield loop
    finally:
        async def cleanup():
            tasks = [task for task in asyncio.all_tasks() if task is not asyncio.current_task()]
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

        asyncio.run_coroutine_threadsafe(cleanup(), loop).result(timeout=2)
        loop.call_soon_threadsafe(loop.stop)
        thread.join(timeout=2)
        loop.close()


@pytest.mark.parametrize("transcript", ["Send the old command", "Dictate: old text"])
def test_cancelled_stt_stays_cancelled_after_new_recording(service, monkeypatch, transcript):
    entered = threading.Event()
    release = threading.Event()

    def delayed_transcribe(*args, **kwargs):
        entered.set()
        assert release.wait(2)
        return transcript

    dispatch = MagicMock()
    inject = MagicMock()
    monkeypatch.setattr(service, "_transcribe", delayed_transcribe)
    monkeypatch.setattr(service, "_dispatch_command", dispatch)
    monkeypatch.setattr("app.core.voice_service.text_injector.inject_text", inject)
    chunks = [np.full((8000, 1), 0.1, dtype=np.float32)]
    worker = threading.Thread(target=service._process_ptt_recording, args=(chunks,), daemon=True)
    worker.start()
    try:
        assert entered.wait(2)
        service.abort_current_command()
        service.start_recording()
        service._broadcast.reset_mock()
    finally:
        release.set()
        worker.join(timeout=2)
    assert not worker.is_alive()
    dispatch.assert_not_called()
    inject.assert_not_called()
    # An old worker must also leave the new recording's HUD alone.
    service._broadcast.assert_not_called()
    assert service.is_ptt_recording

    monkeypatch.setattr(service, "_transcribe", lambda *args, **kwargs: "Run the new command")
    service._process_ptt_recording(chunks)
    dispatch.assert_called_once()
    assert dispatch.call_args.args[0] == "Run the new command"


def test_cancelled_recording_cannot_start_a_delayed_worker(service, monkeypatch):
    service.is_ptt_recording = True
    service.ptt_audio_buffer = [np.full((8000, 1), 0.1, dtype=np.float32)]
    pending = []

    class DelayedThread:
        def __init__(self, target, args=(), **kwargs):
            self.target = target
            self.args = args

        def start(self):
            pending.append((self.target, self.args))

    with monkeypatch.context() as patcher:
        patcher.setattr("app.core.voice_service.threading.Thread", DelayedThread)
        service.stop_recording()
    service.abort_current_command()
    service.start_recording()
    transcribe = MagicMock()
    monkeypatch.setattr(service, "_transcribe", transcribe)
    for target, args in pending:
        target(*args)
    transcribe.assert_not_called()


@pytest.mark.parametrize("use_daemon_loop", [False, True])
def test_timeout_cancels_underlying_agent(service, monkeypatch, event_loop_thread, use_daemon_loop):
    cancelled = threading.Event()
    completed = threading.Event()

    async def slow_agent(**kwargs):
        try:
            await asyncio.sleep(60)
            completed.set()
            return {"output": "Too late", "tools_used": []}
        except asyncio.CancelledError:
            cancelled.set()
            raise

    monkeypatch.setattr(agent, "run", slow_agent)
    monkeypatch.setattr(settings, "agent_timeout_seconds", 0.1)
    if use_daemon_loop:
        service._loop = event_loop_thread
        service._running = True
    service._dispatch_command("test timeout")
    assert cancelled.wait(2)
    assert not completed.is_set()
    assert service._active_future is None
    assert not service._active_futures
    events = [call.args[0] for call in service._broadcast.call_args_list]
    assert any(event.get("event") == "voice_result" and "timed out" in event["output"] for event in events)


def test_finishing_old_dispatch_does_not_untrack_new_command(service, monkeypatch, event_loop_thread):
    service._loop = event_loop_thread
    service._running = True
    entered = {name: threading.Event() for name in ("first", "second")}
    cancelled = threading.Event()
    finish_first = asyncio.Event()

    async def fake_agent(prompt, **kwargs):
        entered[prompt].set()
        if prompt == "first":
            await finish_first.wait()
            return {"output": "First finished", "tools_used": []}
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise

    monkeypatch.setattr(agent, "run", fake_agent)
    workers = []
    try:
        for name in ("first", "second"):
            worker = threading.Thread(target=service._dispatch_command, args=(name,), daemon=True)
            worker.start()
            workers.append(worker)
            assert entered[name].wait(2)
        event_loop_thread.call_soon_threadsafe(finish_first.set)
        workers[0].join(timeout=2)
        assert not workers[0].is_alive()
        assert service._active_future is not None
        assert service._is_dispatching
        service.abort_current_command()
        assert cancelled.wait(2)
        workers[1].join(timeout=2)
        assert not workers[1].is_alive()
        assert not service._active_futures
    finally:
        service.abort_current_command()
        for worker in workers:
            worker.join(timeout=2)


def test_cancel_before_speech_does_not_start_old_response(service, monkeypatch):
    async def fake_agent(**kwargs):
        return {"output": "Old response", "tools_used": []}

    tts = MagicMock()
    monkeypatch.setattr(agent, "run", fake_agent)
    monkeypatch.setattr(settings, "enable_tts", True)
    monkeypatch.setattr("app.core.voice_service.tts_service", tts)

    def cancel_at_result(event):
        if event.get("event") == "voice_result":
            service.abort_current_command()
            service.start_recording()

    service._broadcast.side_effect = cancel_at_result
    service._dispatch_command("old command")
    tts.speak.assert_not_called()
