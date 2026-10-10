import unittest
from app.config import Settings
from app.core.config_manager import get_current_config, KEY_ALIASES


class TestConfiguration(unittest.TestCase):
    def test_wake_word_removed(self):
        s = Settings()
        self.assertFalse(hasattr(s, "enable_wake_word"))
        self.assertFalse(hasattr(s, "wake_words"))
        self.assertFalse(hasattr(s, "wake_word_auto_prefix"))
        self.assertIsNone(KEY_ALIASES.get("wake-word"))
        cfg = get_current_config()
        self.assertNotIn("enable_wake_word", cfg)

    def test_agent_timeout_key_aliases(self):
        s = Settings()
        self.assertEqual(s.agent_timeout_seconds, 90.0)
        self.assertEqual(KEY_ALIASES.get("agent-timeout"), "AGENT_TIMEOUT_SECONDS")
        self.assertEqual(KEY_ALIASES.get("agent_timeout"), "AGENT_TIMEOUT_SECONDS")
        cfg = get_current_config()
        self.assertIn("agent_timeout_seconds", cfg)
        self.assertEqual(cfg["agent_timeout_seconds"], 90.0)


if __name__ == "__main__":
    unittest.main()

