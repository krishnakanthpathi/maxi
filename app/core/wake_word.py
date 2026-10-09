"""
Maxi Wake Word Detection and Prompt Prefixing Engine
Supports hands-free keyword spotting ("Hey Maxi", "Hey Siri", "Maxi", "Siri")
with automated prompt prefixing ("Hey Maxi, <command>") and two-stage conversational wake.
"""

import re
from typing import List, Optional, Tuple

DEFAULT_WAKE_WORDS = [
    "hey maxi",
    "hey siri",
    "hi maxi",
    "hi siri",
    "hey max",
    "maxi",
    "siri",
]


def clean_command(text: str) -> str:
    """Cleans command string by stripping leading separators and whitespace while preserving terminal punctuation."""
    t = text.strip(" \t\n\r\"'`")
    t = re.sub(r"^[\s,.:;!?-]+", "", t).strip()
    return t


def parse_wake_word(
    transcript: str,
    wake_words: Optional[List[str]] = None,
) -> Optional[Tuple[str, str]]:
    """
    Parses a transcript to detect if it contains an authorized wake word.
    
    Returns:
        (matched_wake_word, command_text) if a wake word is found.
        None if no wake word is present.
    """
    if not transcript or not transcript.strip():
        return None

    words_to_check = wake_words or DEFAULT_WAKE_WORDS
    sorted_candidates = sorted(words_to_check, key=lambda w: len(w.strip()), reverse=True)

    for cand in sorted_candidates:
        clean_cand = cand.strip().lower()
        if not clean_cand:
            continue

        parts = [re.escape(p) for p in clean_cand.split()]
        pattern = r"\b" + r"[\s,.:;!?-]+".join(parts) + r"\b"

        match = re.search(pattern, transcript, re.IGNORECASE)
        if match:
            # Extract text before and after the wake word match
            before = transcript[: match.start()].strip(" \t\n\r\"'`").rstrip(" ,.:;!?-")
            after = transcript[match.end() :].strip(" \t\n\r\"'`")
            after = re.sub(r"^[\s,.:;!?-]+", "", after).strip()

            command = after if after else before
            return clean_cand, command

    return None


def format_prefixed_prompt(command: str, prefix_phrase: str = "Hey Maxi") -> str:
    """
    Guarantees the prompt dispatched to the agent is cleanly prefixed with 'Hey Maxi, '.
    """
    cmd = clean_command(command)
    if not cmd:
        return prefix_phrase

    # Check if already starts with 'Hey Maxi' or 'Maxi'
    if re.match(r"^hey\s+maxi\b", cmd, re.IGNORECASE):
        rest = re.sub(r"^hey\s+maxi[\s,.:;!?-]*", "", cmd, flags=re.IGNORECASE).strip()
        return f"{prefix_phrase}, {rest}" if rest else prefix_phrase

    if re.match(r"^maxi\b", cmd, re.IGNORECASE):
        rest = re.sub(r"^maxi[\s,.:;!?-]*", "", cmd, flags=re.IGNORECASE).strip()
        return f"{prefix_phrase}, {rest}" if rest else prefix_phrase

    # Replace any leftover 'Hey Siri' or 'Siri' prefix with 'Hey Maxi'
    if re.match(r"^hey\s+siri\b", cmd, re.IGNORECASE):
        rest = re.sub(r"^hey\s+siri[\s,.:;!?-]*", "", cmd, flags=re.IGNORECASE).strip()
        return f"{prefix_phrase}, {rest}" if rest else prefix_phrase

    if re.match(r"^siri\b", cmd, re.IGNORECASE):
        rest = re.sub(r"^siri[\s,.:;!?-]*", "", cmd, flags=re.IGNORECASE).strip()
        return f"{prefix_phrase}, {rest}" if rest else prefix_phrase

    return f"{prefix_phrase}, {cmd}"
