"""
Willow-inspired Personal Glossary & Whisper Vocabulary Conditioning (`app/core/glossary.py`).
Provides:
1. Custom vocabulary terms (e.g. 'Maxi', 'LightMem', 'Memanto', 'Krishnakanth', 'spyui.online')
   injected into Whisper's `prompt` parameter to prevent phonetic misspellings.
2. Deterministic post-transcription replacements for common STT mishearings (e.g. 'Hey Siri' -> 'Maxi').
"""

import json
import logging
import re
from pathlib import Path
from typing import Dict, List, Optional, Any

logger = logging.getLogger("maxi.glossary")

DEFAULT_VOCABULARY: List[str] = [
    "Maxi",
    "LightMem",
    "lmem",
    "Memanto",
    "Krishnakanth",
    "Antigravity",
    "FastMCP",
    "Obsidian",
    "Willow",
    "spyui.online",
    "spyui.com",
    "Groq",
    "Ollama",
    "Gemma",
]

DEFAULT_REPLACEMENTS: Dict[str, str] = {
    "light mem": "LightMem",
    "lightman": "LightMem",
    "spy ui": "spyui",
}


class GlossaryManager:
    """Manages ~/.maxi/glossary.json for Whisper STT prompt conditioning and term replacements."""

    def __init__(self, glossary_path: Optional[Path] = None):
        self.glossary_path = glossary_path or (Path.home() / ".maxi" / "glossary.json")
        self.vocabulary: List[str] = list(DEFAULT_VOCABULARY)
        self.replacements: Dict[str, str] = dict(DEFAULT_REPLACEMENTS)
        self.load()

    def load(self):
        if not self.glossary_path.exists():
            self.save()
            return
        try:
            data = json.loads(self.glossary_path.read_text(encoding="utf-8"))
            vocab = data.get("vocabulary")
            repl = data.get("replacements")
            if isinstance(vocab, list):
                merged = list(dict.fromkeys(vocab + DEFAULT_VOCABULARY))
                self.vocabulary = merged
            if isinstance(repl, dict):
                merged_repl = dict(DEFAULT_REPLACEMENTS)
                merged_repl.update({str(k): str(v) for k, v in repl.items()})
                self.replacements = merged_repl
        except Exception as e:
            logger.warning(f"Could not read glossary from {self.glossary_path}: {e}")

    def save(self):
        try:
            self.glossary_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "vocabulary": self.vocabulary,
                "replacements": self.replacements,
            }
            self.glossary_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception as e:
            logger.warning(f"Could not save glossary to {self.glossary_path}: {e}")

    def add_term(self, term: str, replacement: Optional[str] = None) -> Dict[str, Any]:
        clean = term.strip()
        if not clean:
            return self.to_dict()
        if replacement:
            rep_clean = replacement.strip()
            self.replacements[clean.lower()] = rep_clean
            if "://" not in rep_clean and rep_clean not in self.vocabulary:
                self.vocabulary.append(rep_clean)
        else:
            if clean not in self.vocabulary:
                self.vocabulary.append(clean)
        self.save()
        return self.to_dict()

    def add_replacement(self, term: str, replacement: str) -> Dict[str, Any]:
        return self.add_term(term, replacement=replacement)

    def remove_term(self, term: str) -> bool:
        clean = term.strip()
        before_len = len(self.vocabulary)
        self.vocabulary = [v for v in self.vocabulary if v.lower() != clean.lower()]
        removed_vocab = len(self.vocabulary) < before_len
        removed_repl = self.replacements.pop(clean.lower(), None) is not None
        self.save()
        return removed_vocab or removed_repl

    def remove_replacement(self, term: str) -> bool:
        clean = term.strip().lower()
        removed = self.replacements.pop(clean, None) is not None
        if removed:
            self.save()
        return removed

    def list_all(self) -> Dict[str, Any]:
        return self.to_dict()

    def build_whisper_prompt(
        self,
        extra_terms: Optional[List[str]] = None,
        context_nouns: Optional[List[str]] = None,
    ) -> str:
        """
        Builds a concise Whisper conditioning prompt (<320 chars) combining personal
        glossary vocabulary and active window proper nouns.
        """
        terms = list(self.vocabulary)
        for pool in (extra_terms, context_nouns):
            if pool:
                for t in pool:
                    if t and t not in terms:
                        terms.append(t)
        vocab_str = ", ".join(terms[:32])
        return f"Voice command or dictation. Vocabulary: {vocab_str}."[:320]

    def apply_replacements(self, transcript: str) -> str:
        """Applies case-insensitive word-boundary replacements from the user's glossary."""
        if not transcript or not self.replacements:
            return transcript
        out = transcript
        for wrong, right in self.replacements.items():
            if not wrong:
                continue
            pattern = re.compile(rf"\b{re.escape(wrong)}\b", re.IGNORECASE)
            out = pattern.sub(right, out)
        return out

    def to_dict(self) -> Dict[str, Any]:
        return {
            "path": str(self.glossary_path),
            "vocabulary": self.vocabulary,
            "terms": self.vocabulary,
            "replacements": self.replacements,
        }


glossary_manager = GlossaryManager()
