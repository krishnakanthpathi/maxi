import time
import unittest
from unittest.mock import patch, MagicMock
from app.config import settings
from app.core.tts import (
    clean_text_for_tts,
    resolve_siri_voice,
    TTSService,
)
from app.core.config_manager import KEY_ALIASES, get_current_config


class TestTTSSanitizer(unittest.TestCase):
    def test_strips_urls_and_trailing_colon(self):
        raw = "Your favorite theme song is available here: https://www.youtube.com/watch?v=b-HvWLU2Va4&list=RDb-HvWLU2Va4"
        cleaned = clean_text_for_tts(raw)
        self.assertEqual(cleaned, "Your favorite theme song is available here.")
        self.assertNotIn("http", cleaned)

    def test_strips_markdown_and_emojis(self):
        raw = "⚡ **Playing** your *favorite* song via `safari` now! 🎙️"
        cleaned = clean_text_for_tts(raw)
        self.assertEqual(cleaned, "Playing your favorite song via safari now!")

    def test_converts_markdown_links_to_labels(self):
        raw = "Opened [YouTube Music](https://music.youtube.com) in Safari."
        cleaned = clean_text_for_tts(raw)
        self.assertEqual(cleaned, "Opened YouTube Music in Safari.")

    def test_strips_fenced_code_blocks(self):
        raw = "Done.\n```python\nprint('hello')\n```\nAll set."
        cleaned = clean_text_for_tts(raw)
        self.assertEqual(cleaned, "Done. All set.")


class TestSiriVoiceResolution(unittest.TestCase):
    def test_voice_aliases(self):
        self.assertEqual(resolve_siri_voice("siri"), "Tara")
        self.assertEqual(resolve_siri_voice("siri-in"), "Tara")
        self.assertEqual(resolve_siri_voice("siri-us"), "Samantha")
        self.assertEqual(resolve_siri_voice("siri-uk"), "Daniel")
        self.assertEqual(resolve_siri_voice("siri-au"), "Karen")
        self.assertEqual(resolve_siri_voice("CustomVoice"), "CustomVoice")


class TestTTSServiceExecution(unittest.TestCase):
    @patch("subprocess.Popen")
    def test_speak_invokes_macos_say_with_siri_voice(self, mock_popen):
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.wait.return_value = 0
        mock_popen.return_value = mock_proc

        svc = TTSService()
        events = []
        svc.set_broadcast_callback(lambda ev: events.append(ev))

        orig_enable = settings.enable_tts
        try:
            settings.enable_tts = True
            spoken = svc.speak("Playing **your** song: https://youtube.com/watch?v=1", voice="siri", rate=195, block=True)
            self.assertEqual(spoken, "Playing your song.")
            mock_popen.assert_called_once()
            cmd = mock_popen.call_args[0][0]
            self.assertEqual(cmd, ["say", "-v", "Tara", "-r", "195", "Playing your song."])
            self.assertTrue(any(e.get("event") == "tts_start" for e in events))
            self.assertTrue(any(e.get("event") == "tts_stop" for e in events))
            # Cooldown should be active right after speech finishes
            self.assertTrue(svc.is_active_or_cooldown())
        finally:
            settings.enable_tts = orig_enable

    def test_stop_terminates_active_process(self):
        svc = TTSService()
        mock_proc = MagicMock()
        svc._proc = mock_proc
        svc._is_speaking = True

        svc.stop()
        mock_proc.terminate.assert_called_once()
        self.assertFalse(svc.is_speaking)
        self.assertTrue(svc.is_active_or_cooldown())

    def test_config_aliases_for_tts(self):
        self.assertEqual(KEY_ALIASES.get("tts"), "ENABLE_TTS")
        self.assertEqual(KEY_ALIASES.get("tts-voice"), "TTS_VOICE")
        self.assertEqual(KEY_ALIASES.get("siri-voice"), "TTS_VOICE")
        self.assertEqual(KEY_ALIASES.get("tts-rate"), "TTS_RATE")
        cfg = get_current_config()
        self.assertIn("enable_tts", cfg)
        self.assertIn("tts_voice", cfg)
        self.assertIn("tts_rate", cfg)


if __name__ == "__main__":
    unittest.main()
