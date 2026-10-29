"""
Unit tests for the 6 Willow Voice v2.6.2 architectural subsystems integrated into Maxi:
1. WarmTranscriptionConnection (persistent HTTP keepalive client)
2. FocusedInputCapture + AXUIHelpers (context_capture.py)
3. DefaultGlossaryRepository (glossary.py)
4. PrivateDucker (audio_ducker.py)
5. RecordingHotkeyController (double-tap hands-free lock, Esc cancel, 5-band audio levels)
6. SmartInsertions + PasteboardReadReceipt (text_injector.py & Dictate fast-path)
"""

from pathlib import Path
from unittest.mock import MagicMock, patch
import numpy as np
from fastapi.testclient import TestClient

from app.core.context_capture import CapturedContext
from app.core.glossary import GlossaryManager
from app.core.audio_ducker import AudioDucker
from app.core.text_injector import TextInjector, inject_text_at_cursor
from app.core.voice_service import MaxiVoiceService, compute_audio_levels


# ─────────────────────────────────────────────────────────────
# 1. FocusedContextCapturer & CapturedContext Tests
# ─────────────────────────────────────────────────────────────

def test_captured_context_prompt_block_and_proper_nouns():
    ctx = CapturedContext(
        app_name="Cursor",
        bundle_id="com.todesktop.230313mzl4w4u92",
        window_title="voice_service.py — Maxi — LangGraph",
        url="",
        selected_text="def _process_ptt_recording(self, chunks):",
        captured_at=1234567890.0,
    )
    block = ctx.to_prompt_block()
    assert "<active_context>" in block
    assert "Frontmost App: Cursor (com.todesktop.230313mzl4w4u92)" in block
    assert "Window Title: voice_service.py — Maxi — LangGraph" in block
    assert "_process_ptt_recording" in block

    nouns = ctx.extract_proper_nouns()
    assert "Cursor" in nouns
    assert "Maxi" in nouns
    assert "LangGraph" in nouns


def test_captured_context_empty():
    ctx = CapturedContext()
    assert ctx.is_empty() is True
    assert ctx.to_prompt_block() == ""
    assert ctx.extract_proper_nouns() == []


# ─────────────────────────────────────────────────────────────
# 2. GlossaryManager Tests
# ─────────────────────────────────────────────────────────────

def test_glossary_manager_crud_and_replacements(tmp_path: Path):
    gfile = tmp_path / "glossary.json"
    gm = GlossaryManager(glossary_path=gfile)

    gm.add_term("FastAPI")
    gm.add_term("PyObjC")
    gm.add_replacement("my github", "https://github.com/krishnakanth")
    gm.add_replacement("willow hud", "MaxiHUD")

    data = gm.list_all()
    assert "FastAPI" in data["terms"]
    assert "PyObjC" in data["terms"]
    assert data["replacements"]["my github"] == "https://github.com/krishnakanth"

    prompt = gm.build_whisper_prompt(context_nouns=["MaxiDaemon", "LangGraph"])
    assert "FastAPI" in prompt
    assert "PyObjC" in prompt
    assert "MaxiDaemon" in prompt

    # Case-insensitive whole-phrase replacement
    raw = "Please open My GitHub and check the Willow HUD code"
    replaced = gm.apply_replacements(raw)
    assert replaced == "Please open https://github.com/krishnakanth and check the MaxiHUD code"

    assert gm.remove_term(" fastAPI ") is True
    assert gm.remove_replacement("MY GITHUB") is True
    assert "FastAPI" not in gm.list_all()["terms"]


# ─────────────────────────────────────────────────────────────
# 3. AudioDucker Tests
# ─────────────────────────────────────────────────────────────

def test_audio_ducker_ducks_and_restores():
    ducker = AudioDucker(duck_level=15)
    with patch.object(ducker, "_get_macos_output_volume", return_value=65), \
         patch.object(ducker, "_set_macos_output_volume") as mock_set, \
         patch("app.core.audio_ducker.settings.auto_duck_audio", True), \
         patch("sys.platform", "darwin"):
        ducker.duck()
        assert ducker.is_ducked is True
        mock_set.assert_called_once_with(15)

        mock_set.reset_mock()
        ducker.unduck()
        assert ducker.is_ducked is False
        mock_set.assert_called_once_with(65)


def test_audio_ducker_skips_when_already_quiet():
    ducker = AudioDucker(duck_level=20)
    with patch.object(ducker, "_get_macos_output_volume", return_value=10), \
         patch.object(ducker, "_set_macos_output_volume") as mock_set, \
         patch("sys.platform", "darwin"):
        ducker.duck()
        assert ducker.is_ducked is False
        mock_set.assert_not_called()


# ─────────────────────────────────────────────────────────────
# 4. TextInjector & Clipboard Preservation Tests
# ─────────────────────────────────────────────────────────────

def test_text_injector_preserves_clipboard():
    injector = TextInjector()
    mock_proc = MagicMock()
    mock_proc.returncode = 0
    with patch.object(injector, "_get_clipboard", return_value="ORIGINAL_CLIPBOARD"), \
         patch.object(injector, "_set_clipboard") as mock_write, \
         patch("subprocess.run", return_value=mock_proc), \
         patch("time.sleep"), \
         patch("sys.platform", "darwin"):
        ok = injector.inject_text("Hello from Maxi", preserve_clipboard=True)
        assert ok is True
        calls = [c.args[0] for c in mock_write.call_args_list]
        assert calls[0] == "Hello from Maxi"
        assert calls[-1] == "ORIGINAL_CLIPBOARD"


def test_inject_text_at_cursor_tool():
    with patch("app.core.text_injector.text_injector.inject_text", return_value=True) as mock_inj:
        res = inject_text_at_cursor.invoke({"text": "inserted snippet"})
        mock_inj.assert_called_once_with("inserted snippet", restore_clipboard=True)
        assert "Successfully inserted" in res


# ─────────────────────────────────────────────────────────────
# 5. 5-Band AudioLevels, Double-Tap Lock, Esc Cancel & Dictate Fast-Path
# ─────────────────────────────────────────────────────────────

def test_compute_audio_levels_five_bands():
    silent = np.zeros((512, 1), dtype=np.float32)
    levels_silent = compute_audio_levels(silent)
    assert len(levels_silent) == 5
    assert all(0.0 <= x <= 0.12 for x in levels_silent)

    t = np.linspace(0, 0.032, 512, dtype=np.float32)
    sine = (0.5 * np.sin(2 * np.pi * 440 * t)).reshape(-1, 1)
    levels_loud = compute_audio_levels(sine)
    assert len(levels_loud) == 5
    assert any(x > 0.25 for x in levels_loud)


def test_double_tap_hands_free_lock_and_escape_cancel():
    svc = MaxiVoiceService()
    svc.is_mac = True
    fake_opt_key = MagicMock()
    fake_opt_key.vk = 61  # Right Option
    fake_esc_key = MagicMock()
    fake_esc_key.vk = 53  # Escape

    with patch.object(svc, "_open_mic_stream"), \
         patch.object(svc, "_close_mic_stream"), \
         patch.object(svc, "_capture_context_background"), \
         patch.object(svc, "_broadcast"), \
         patch("app.core.voice_service.play_sound"), \
         patch("app.core.voice_service.audio_ducker"):

        # 1st tap: press and quick release (<0.30s)
        svc._on_press(fake_opt_key)
        assert svc.is_ptt_recording is True
        assert svc.is_hands_free_locked is False

        svc._on_release(fake_opt_key)
        assert svc.is_ptt_recording is False
        assert svc.last_short_tap_time > 0

        # Wait >80ms debounce but <380ms double-tap window
        svc.last_key_press_time -= 0.15
        svc._on_press(fake_opt_key)
        assert svc.is_ptt_recording is True
        assert svc.is_hands_free_locked is True

        # Duplicate _on_press while key is still held down must NOT stop hands-free recording
        svc.last_key_press_time -= 0.15
        svc._on_press(fake_opt_key)
        assert svc.is_ptt_recording is True
        assert svc.is_hands_free_locked is True

        # Releasing key in hands-free lock mode does NOT stop recording!
        svc._on_release(fake_opt_key)
        assert svc.is_ptt_recording is True
        assert svc.is_hands_free_locked is True

        # Pressing Esc cancels recording immediately
        svc._on_press(fake_esc_key)
        assert svc.is_ptt_recording is False
        assert svc.is_hands_free_locked is False
        assert svc.ptt_audio_buffer == []

        # Pressing Right Command (vk=54) must NEVER trigger Push-to-Talk
        fake_right_cmd = MagicMock()
        fake_right_cmd.vk = 54
        svc._on_press(fake_right_cmd)
        assert svc.is_ptt_recording is False


def test_dictate_fast_path_skips_llm():
    svc = MaxiVoiceService()
    fake_chunks = [np.ones((int(16000 * 0.5), 1), dtype=np.float32) * 0.1]

    with patch.object(svc, "_transcribe", return_value="Dictate: Hello world from fast path"), \
         patch.object(svc, "_broadcast"), \
         patch.object(svc, "_dispatch_command") as mock_dispatch, \
         patch("app.core.voice_service.play_sound"), \
         patch("app.core.voice_service.text_injector.inject_text", return_value=True) as mock_inject:
        svc._process_ptt_recording(fake_chunks, captured_ctx=None)
        mock_inject.assert_called_once_with("Hello world from fast path", restore_clipboard=True)
        mock_dispatch.assert_not_called()


# ─────────────────────────────────────────────────────────────
# 6. REST API Endpoints (/api/glossary, /api/context, /api/inject)
# ─────────────────────────────────────────────────────────────

def test_willow_api_routes(tmp_path: Path):
    from app.main import app
    client = TestClient(app)

    temp_glossary = GlossaryManager(glossary_path=tmp_path / "api_glossary.json")
    with patch("app.core.glossary.glossary_manager", temp_glossary):
        r1 = client.post("/api/glossary", json={"term": "PyObjC"})
        assert r1.status_code == 200
        assert "PyObjC" in r1.json()["glossary"]["terms"]

        r2 = client.post("/api/glossary", json={"term": "maxi repo", "replacement": "https://github.com/maxi"})
        assert r2.status_code == 200
        assert r2.json()["glossary"]["replacements"]["maxi repo"] == "https://github.com/maxi"

        r3 = client.get("/api/glossary")
        assert r3.status_code == 200
        assert "PyObjC" in r3.json()["terms"]

        r4 = client.delete("/api/glossary", params={"term": "PyObjC"})
        assert r4.status_code == 200
        assert "PyObjC" not in r4.json()["glossary"]["terms"]

    with patch("app.core.text_injector.text_injector.inject_text", return_value=True):
        r_inj = client.post("/api/inject", json={"text": "test injection", "preserve_clipboard": True})
        assert r_inj.status_code == 200
        assert r_inj.json()["status"] == "injected"


def test_voice_toggle_and_control_api_routes():
    from app.main import app
    from app.core.voice_service import voice_service

    client = TestClient(app)

    with patch.object(voice_service, "start_recording") as mock_start, \
         patch.object(voice_service, "stop_recording") as mock_stop:
        # 1. Start voice
        r_start = client.post("/api/voice/start?locked=true")
        assert r_start.status_code == 200
        assert r_start.json() == {"status": "recording", "locked": True}
        mock_start.assert_called_with(locked=True)

        # 2. Stop voice
        r_stop = client.post("/api/voice/stop")
        assert r_stop.status_code == 200
        assert r_stop.json() == {"status": "processing"}
        mock_stop.assert_called_once()

        # 3. Toggle voice when idle -> starts
        voice_service.is_ptt_recording = False
        r_toggle1 = client.post("/api/voice/toggle")
        assert r_toggle1.status_code == 200
        assert r_toggle1.json() == {"status": "recording"}

        # 4. Toggle voice when recording -> stops
        voice_service.is_ptt_recording = True
        r_toggle2 = client.post("/api/voice/toggle")
        assert r_toggle2.status_code == 200
        assert r_toggle2.json() == {"status": "processing"}
        voice_service.is_ptt_recording = False



