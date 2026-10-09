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


if __name__ == "__main__":
    unittest.main()
