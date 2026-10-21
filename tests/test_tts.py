import time
import unittest
from unittest.mock import patch, MagicMock
from app.config import settings
from app.core.tts import (
    clean_text_for_tts,
    extract_speech_and_display_text,
    is_kokoro_voice,
    resolve_siri_voice,
    translate_expressive_annotations,
    TTSService,
)
from app.core.config_manager import KEY_ALIASES, get_current_config


class TestTTSSanitizer(unittest.TestCase):
    def test_numbered_instructions_keep_the_actual_instructions(self):
        raw = "1. Open Settings.\n2) Select Privacy and Security."
        self.assertEqual(clean_text_for_tts(raw), "Open Settings. Select Privacy and Security.")

    def test_plain_response_preserves_followup_sentence(self):
        self.assertEqual(
            clean_text_for_tts("Done. Your files are in Downloads."),
            "Done. Your files are in Downloads.",
        )

    def test_explicit_summary_excludes_visual_card(self):
        for raw in (
            "<speech>Done. The file is saved.</speech>\n\n**Report**\n- Saved report.md",
            "Spoken: Done. The file is saved.\n\n**Report**\n- Saved report.md",
        ):
            self.assertEqual(clean_text_for_tts(raw), "Done. The file is saved.")
            self.assertEqual(
                extract_speech_and_display_text(raw)[1], "**Report**\n- Saved report.md",
            )

    def test_fallback_still_limits_long_responses(self):
        raw = "The report is ready. " * 30
        cleaned = clean_text_for_tts(raw)
        self.assertTrue(cleaned.startswith("The report is ready."))
        self.assertLessEqual(len(cleaned), 241)

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

    def test_expressive_annotations_for_kokoro_and_siri(self):
        raw = "Oh, I got it! [laugh] [hmm] Let's check that [pause] right now."
        cleaned = clean_text_for_tts(raw, preserve_annotations=True)
        kokoro_out = translate_expressive_annotations(cleaned, for_kokoro=True)
        self.assertIn("Oh, I got it! [pause:0.15s]", kokoro_out)
        self.assertIn("[Haha](/həhˈɑː/)!", kokoro_out)
        self.assertIn("[Hmm](/hˈmː/)...", kokoro_out)
        self.assertIn("[pause:0.3s]", kokoro_out)

        siri_out = translate_expressive_annotations(cleaned, for_kokoro=False)
        self.assertNotIn("[pause", siri_out)
        self.assertNotIn("[laugh]", siri_out)
        self.assertIn("Haha!", siri_out)
        self.assertIn("Hmm...", siri_out)


class TestSiriVoiceResolution(unittest.TestCase):
    def test_voice_aliases(self):
        self.assertEqual(resolve_siri_voice("siri"), "Tara")
        self.assertEqual(resolve_siri_voice("siri-in"), "Tara")
        self.assertEqual(resolve_siri_voice("siri-us"), "Samantha")
        self.assertEqual(resolve_siri_voice("siri-uk"), "Daniel")
        self.assertEqual(resolve_siri_voice("siri-au"), "Karen")
        self.assertEqual(resolve_siri_voice("kokoro"), "af_heart")
        self.assertEqual(resolve_siri_voice("cucuru"), "af_heart")
        self.assertEqual(resolve_siri_voice("bella"), "af_bella")
        self.assertEqual(resolve_siri_voice("CustomVoice"), "CustomVoice")
        self.assertTrue(is_kokoro_voice("af_heart"))
        self.assertTrue(is_kokoro_voice("af_heart(2)+af_bella(1)"))
        self.assertFalse(is_kokoro_voice("Tara"))


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

    @patch("subprocess.Popen")
    def test_speak_invokes_kokoro_stream_worker(self, mock_popen):
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.wait.return_value = 0
        mock_popen.return_value = mock_proc

        svc = TTSService()
        orig_enable = settings.enable_tts
        try:
            settings.enable_tts = True
            spoken = svc.speak("Oh, I got it! [laugh] All set.", voice="kokoro", rate=190, block=True)
            self.assertEqual(spoken, "Oh, I got it! [laugh] All set.")
            mock_popen.assert_called_once()
            cmd = mock_popen.call_args[0][0]
            self.assertEqual(cmd[4], "af_heart")
            self.assertIn("[Haha](/həhˈɑː/)!", cmd[6])
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
        self.assertEqual(KEY_ALIASES.get("tts-url"), "TTS_BASE_URL")
        cfg = get_current_config()
        self.assertIn("enable_tts", cfg)
        self.assertIn("tts_voice", cfg)
        self.assertIn("tts_rate", cfg)


if __name__ == "__main__":
    unittest.main()
