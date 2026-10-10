import unittest
from unittest.mock import MagicMock, patch
import numpy as np

from app.config import settings
from app.core.wake_word import parse_wake_word, format_prefixed_prompt
from app.core.voice_service import MaxiVoiceService


class TestWakeWordParsing(unittest.TestCase):
    def setUp(self):
        self.wake_words = ["hey maxi", "hey siri", "hi maxi", "hi siri", "hey max", "maxi", "siri"]

    def test_direct_prefix_match(self):
        res = parse_wake_word("Hey Maxi, open Safari", self.wake_words)
        self.assertIsNotNone(res)
        ww, cmd = res
        self.assertEqual(ww, "hey maxi")
        self.assertEqual(cmd, "open Safari")

    def test_punctuation_in_wake_phrase(self):
        res = parse_wake_word("Hey, Maxi! What time is it?", self.wake_words)
        self.assertIsNotNone(res)
        ww, cmd = res
        self.assertEqual(ww, "hey maxi")
        self.assertEqual(cmd, "What time is it?")

    def test_hey_siri_match(self):
        res = parse_wake_word("Hey Siri, turn up the volume", self.wake_words)
        self.assertIsNotNone(res)
        ww, cmd = res
        self.assertEqual(ww, "hey siri")
        self.assertEqual(cmd, "turn up the volume")

    def test_standalone_wake_word(self):
        res = parse_wake_word("Hey Maxi", self.wake_words)
        self.assertIsNotNone(res)
        ww, cmd = res
        self.assertEqual(ww, "hey maxi")
        self.assertEqual(cmd, "")

    def test_single_word_maxi(self):
        res = parse_wake_word("Maxi, how much battery is left?", self.wake_words)
        self.assertIsNotNone(res)
        ww, cmd = res
        self.assertEqual(ww, "maxi")
        self.assertEqual(cmd, "how much battery is left?")

    def test_trailing_wake_word(self):
        res = parse_wake_word("Could you please lock the screen, Maxi?", self.wake_words)
        self.assertIsNotNone(res)
        ww, cmd = res
        self.assertEqual(ww, "maxi")
        self.assertEqual(cmd, "Could you please lock the screen")

    def test_non_wake_speech_ignored(self):
        res = parse_wake_word("The quick brown fox jumps over the lazy dog", self.wake_words)
        self.assertIsNone(res)

    def test_empty_or_whitespace(self):
        self.assertIsNone(parse_wake_word("", self.wake_words))
        self.assertIsNone(parse_wake_word("   ", self.wake_words))
        self.assertIsNone(parse_wake_word("...", self.wake_words))


class TestPromptPrefixing(unittest.TestCase):
    def test_prefix_standard_command(self):
        result = format_prefixed_prompt("open Safari")
        self.assertEqual(result, "Hey Maxi, open Safari")

    def test_prefix_preserves_existing_hey_maxi(self):
        result = format_prefixed_prompt("Hey Maxi, open Safari")
        self.assertEqual(result, "Hey Maxi, open Safari")

    def test_prefix_converts_hey_siri(self):
        result = format_prefixed_prompt("Hey Siri, turn off Bluetooth")
        self.assertEqual(result, "Hey Maxi, turn off Bluetooth")

    def test_prefix_converts_siri(self):
        result = format_prefixed_prompt("Siri, what is the temperature?")
        self.assertEqual(result, "Hey Maxi, what is the temperature?")

    def test_prefix_converts_maxi(self):
        result = format_prefixed_prompt("Maxi, list active applications")
        self.assertEqual(result, "Hey Maxi, list active applications")

    def test_empty_command_returns_prefix_only(self):
        result = format_prefixed_prompt("")
        self.assertEqual(result, "Hey Maxi")


class TestVoiceServiceWakeWorkflow(unittest.TestCase):
    def setUp(self):
        self.service = MaxiVoiceService()

    @patch.object(MaxiVoiceService, "_transcribe")
    @patch.object(MaxiVoiceService, "_dispatch_command")
    @patch.object(MaxiVoiceService, "_broadcast")
    def test_process_wake_utterance_with_command(self, mock_broadcast, mock_dispatch, mock_transcribe):
        mock_transcribe.return_value = "Hey Maxi, open Google Chrome"
        dummy_chunk = [np.zeros(16000, dtype=np.float32)]

        self.service._process_wake_utterance(dummy_chunk)

        mock_dispatch.assert_called_once()
        args, kwargs = mock_dispatch.call_args
        dispatched_prompt = args[0]
        self.assertEqual(dispatched_prompt, "Hey Maxi, open Google Chrome")
        self.assertEqual(kwargs.get("source"), "voice:wake_word")

    @patch.object(MaxiVoiceService, "_transcribe")
    @patch.object(MaxiVoiceService, "_dispatch_command")
    @patch.object(MaxiVoiceService, "_broadcast")
    def test_process_wake_utterance_hey_siri_mapped_to_hey_maxi(self, mock_broadcast, mock_dispatch, mock_transcribe):
        mock_transcribe.return_value = "Hey Siri, show my notifications"
        dummy_chunk = [np.zeros(16000, dtype=np.float32)]

        self.service._process_wake_utterance(dummy_chunk)

        mock_dispatch.assert_called_once()
        args, kwargs = mock_dispatch.call_args
        dispatched_prompt = args[0]
        self.assertEqual(dispatched_prompt, "Hey Maxi, show my notifications")

    @patch.object(MaxiVoiceService, "_transcribe")
    @patch.object(MaxiVoiceService, "_dispatch_command")
    def test_process_non_wake_utterance_does_not_dispatch(self, mock_dispatch, mock_transcribe):
        mock_transcribe.return_value = "We need to buy some milk and eggs tomorrow"
        dummy_chunk = [np.zeros(16000, dtype=np.float32)]

        self.service._process_wake_utterance(dummy_chunk)

        mock_dispatch.assert_not_called()

    @patch.object(MaxiVoiceService, "_transcribe")
    @patch.object(MaxiVoiceService, "_dispatch_command")
    def test_two_stage_wake_word_workflow(self, mock_dispatch, mock_transcribe):
        dummy_chunk = [np.zeros(16000, dtype=np.float32)]

        # Step 1: User says only "Hey Maxi"
        mock_transcribe.return_value = "Hey Maxi"
        self.service._process_wake_utterance(dummy_chunk)

        # Should enter pending command state, but not dispatch yet
        self.assertTrue(self.service._wake_pending_command)
        mock_dispatch.assert_not_called()

        # Step 2: User says follow-up command
        mock_transcribe.return_value = "What is the date today?"
        self.service._process_wake_utterance(dummy_chunk)

        self.assertFalse(self.service._wake_pending_command)
        mock_dispatch.assert_called_once()
        args, kwargs = mock_dispatch.call_args
        dispatched_prompt = args[0]
        self.assertEqual(dispatched_prompt, "What is the date today?")


if __name__ == "__main__":
    unittest.main()
