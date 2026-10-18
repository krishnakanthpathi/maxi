import concurrent.futures
import threading
import time
from unittest.mock import MagicMock, patch
import numpy as np
import pytest

from app.core.voice_service import MaxiVoiceService


def test_stop_recording_does_not_deadlock_with_audio_callback():
    """
    Reproduces the lock-inversion deadlock between _audio_callback and stop_recording:
    In PortAudio, stream.stop() blocks until any in-flight _audio_callback returns.
    If _audio_callback passes `if not self.is_ptt_recording:` while stop_recording()
    acquires `self.lock` and calls `stream.stop()`, both threads must not deadlock.
    """
    svc = MaxiVoiceService()
    svc.is_ptt_recording = True

    callback_entered = threading.Event()
    stop_called = threading.Event()
    callback_finished = threading.Event()

    class FakePortAudioStream:
        def start(self):
            pass

        def stop(self):
            stop_called.set()
            # PortAudio Pa_StopStream waits for in-flight audio callback to finish
            finished = callback_finished.wait(timeout=1.0)
            if not finished:
                raise RuntimeError("Deadlock: stream.stop() blocked waiting for _audio_callback!")

        def close(self):
            pass

    svc._stream = FakePortAudioStream()

    class SlowCopyChunk:
        def copy(self):
            callback_entered.set()
            # Wait until stop_recording calls stream.stop()
            stop_called.wait(timeout=0.5)
            return np.ones((512, 1), dtype=np.float32) * 0.1

    def simulate_audio_thread():
        svc._audio_callback(SlowCopyChunk(), 512, None, None)
        callback_finished.set()

    t_audio = threading.Thread(target=simulate_audio_thread, daemon=True)
    t_audio.start()

    # Wait until _audio_callback is inside `if not self.is_ptt_recording:`
    callback_entered.wait(timeout=0.5)

    with patch("app.core.voice_service.play_sound"), patch.object(svc, "_process_ptt_recording"):
        t0 = time.monotonic()
        svc.stop_recording()
        elapsed = time.monotonic() - t0

    t_audio.join(timeout=1.0)
    assert callback_finished.is_set(), "Deadlock detected between stop_recording() and _audio_callback()!"
    assert elapsed < 0.8, f"stop_recording blocked for {elapsed:.2f}s"
    assert svc.is_ptt_recording is False
    assert svc._stream is None


def test_rapid_key_release_does_not_drop_stop_and_leave_mic_stuck():
    """
    Reproduces the bug where a key release within 100ms of a previous release event
    sets right_option_pressed = False and then returns early on the 0.10s debounce,
    leaving is_ptt_recording = True and the microphone stuck open forever.
    """
    svc = MaxiVoiceService()
    svc.is_mac = True

    with patch("app.core.voice_service.play_sound"), \
         patch.object(svc, "_open_mic_stream"), \
         patch.object(svc, "_close_mic_stream") as mock_close:

        # Start recording via Right Option press
        fake_right_opt = MagicMock()
        fake_right_opt.vk = 61
        svc._on_press(fake_right_opt)
        assert svc.is_ptt_recording is True

        # Simulate a prior release timestamp just 50ms ago
        svc.last_key_release_time = time.time() - 0.05

        # Now user releases Right Option
        svc._on_release(fake_right_opt)

        # Mic MUST NOT remain stuck recording!
        assert svc.is_ptt_recording is False, "Mic got stuck open because _on_release debounced and returned early!"
        assert mock_close.called


def test_hardware_watchdog_releases_stuck_mic_when_key_up_missed():
    """
    Verifies that if macOS CGEventTap misses a key-up event (e.g., focus switch to Chrome),
    the hardware key-state watchdog automatically stops recording and closes the mic.
    """
    svc = MaxiVoiceService()
    svc._running = True
    svc.is_mac = True

    with patch("app.core.voice_service.play_sound"), \
         patch.object(svc, "_open_mic_stream"), \
         patch.object(svc, "_close_mic_stream") as mock_close, \
         patch.object(svc, "_is_hardware_hotkey_physically_down", return_value=False):

        svc.start_recording()
        assert svc.is_ptt_recording is True

        # Wait ~250ms for the watchdog (150ms settle + 50ms poll)
        time.sleep(0.28)
        assert svc.is_ptt_recording is False, "Hardware watchdog failed to close stuck mic!"
        assert mock_close.called


def test_stop_cancels_active_future_and_closes_mic_immediately():
    """
    Verifies that pressing Ctrl+C (calling voice_service.stop()) cancels any in-flight
    agent command future and closes the microphone stream without hanging.
    """
    svc = MaxiVoiceService()
    svc._running = True
    svc.is_ptt_recording = True
    fake_future = MagicMock(spec=concurrent.futures.Future)
    svc._active_future = fake_future

    with patch.object(svc, "_close_mic_stream") as mock_close:
        svc.stop()

    assert svc._running is False
    assert svc.is_ptt_recording is False
    assert fake_future.cancel.called
    assert mock_close.called
