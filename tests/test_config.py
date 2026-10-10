import unittest
from app.config import Settings
from app.core.config_manager import get_current_config, save_config, KEY_ALIASES


class TestWakeWordConfiguration(unittest.TestCase):
    def test_settings_default_wake_words(self):
        s = Settings()
        self.assertTrue(s.enable_wake_word)
        self.assertTrue(s.wake_word_auto_prefix)
        wake_list = s.get_wake_words_list()
        self.assertIn("hey maxi", wake_list)
        self.assertIn("hey siri", wake_list)
        self.assertIn("maxi", wake_list)

    def test_key_aliases_wake_word(self):
        self.assertEqual(KEY_ALIASES.get("wake-word"), "ENABLE_WAKE_WORD")
        self.assertEqual(KEY_ALIASES.get("wake_word"), "ENABLE_WAKE_WORD")
        self.assertEqual(KEY_ALIASES.get("wake-words"), "VOICE_WAKE_WORDS")
        self.assertEqual(KEY_ALIASES.get("wake-prefix"), "WAKE_WORD_AUTO_PREFIX")

    def test_get_current_config_includes_wake_keys(self):
        cfg = get_current_config()
        self.assertIn("enable_wake_word", cfg)
        self.assertIn("wake_words", cfg)
        self.assertIn("wake_word_auto_prefix", cfg)

    def test_settings_conversational_thresholds(self):
        s = Settings()
        self.assertEqual(s.wake_word_silence_duration, 1.8)
        self.assertEqual(s.wake_word_energy_threshold, 0.008)
        self.assertEqual(s.wake_word_max_duration, 45.0)
        self.assertEqual(s.agent_timeout_seconds, 90.0)

    def test_agent_timeout_key_aliases(self):
        self.assertEqual(KEY_ALIASES.get("agent-timeout"), "AGENT_TIMEOUT_SECONDS")
        self.assertEqual(KEY_ALIASES.get("agent_timeout"), "AGENT_TIMEOUT_SECONDS")
        cfg = get_current_config()
        self.assertIn("agent_timeout_seconds", cfg)
        self.assertEqual(cfg["agent_timeout_seconds"], 90.0)


if __name__ == "__main__":
    unittest.main()
