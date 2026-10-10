import os
import re
import logging
from typing import Dict, List, Optional, Set
from pathlib import Path
from pydantic import BaseModel
from app.config import settings

logger = logging.getLogger("maxi.skills")


class Skill(BaseModel):
    name: str
    description: str
    instructions: str
    file_path: str
    enabled: bool = True
    keywords: Set[str] = set()


class SkillRegistry:
    """Scans the skills/ folder for markdown files and dynamically matches/injects skills."""

    def __init__(self):
        self._skills: Dict[str, Skill] = {}
        self.reload()

    def reload(self):
        """Scans the configured skills directory and loads all *.md skill files."""
        self._skills.clear()
        skills_dir = settings.get_skills_dir()

        if not skills_dir.exists() or not skills_dir.is_dir():
            logger.warning(f"Skills directory '{skills_dir}' does not exist.")
            return

        for md_file in skills_dir.glob("*.md"):
            if md_file.name.lower().startswith("readme"):
                continue

            try:
                content = md_file.read_text(encoding="utf-8").strip()
                name = md_file.stem.lower()

                # Extract description from first heading or first line
                lines = [line.strip() for line in content.splitlines() if line.strip()]
                description = f"Skill {name}"
                if lines:
                    first_line = lines[0]
                    if first_line.startswith("#"):
                        description = first_line.lstrip("#").strip()
                    elif len(lines) > 1 and lines[1].startswith("#"):
                        description = lines[1].lstrip("#").strip()

                # Generate simple keyword set for matching (stem + heading words)
                raw_keywords = set(re.findall(r"\w+", f"{name} {description}".lower()))
                # Also extract explicitly declared triggers/keywords if present in markdown
                # e.g., <!-- triggers: ... --> or Triggers: ... or Keywords: ...
                for line in lines:
                    trigger_match = re.search(r"(?:<!--\s*(?:triggers|keywords):|^(?:triggers|keywords):)\s*(.*?)(?:-->|$)", line, re.IGNORECASE)
                    if trigger_match:
                        raw_keywords.update(re.findall(r"\w+", trigger_match.group(1).lower()))

                # Filter out short or trivial words
                keywords = {kw for kw in raw_keywords if len(kw) > 2}

                skill = Skill(
                    name=name,
                    description=description,
                    instructions=content,
                    file_path=str(md_file),
                    enabled=True,
                    keywords=keywords
                )
                self._skills[name] = skill
                logger.info(f"Loaded markdown skill '{name}' ({description}) from {md_file.name}")

            except Exception as e:
                logger.error(f"Failed to read skill file {md_file}: {e}")

        logger.info(f"Loaded {len(self._skills)} total markdown skills from {skills_dir}")

    def list_skills(self) -> List[Skill]:
        return list(self._skills.values())

    def get(self, name: str) -> Optional[Skill]:
        return self._skills.get(name.lower())

    def find_relevant_skills(self, prompt: str, source: str = "text") -> List[Skill]:
        """Finds skills matching prompt keywords, skill names, or execution context."""
        prompt_lower = prompt.lower()
        prompt_words = set(re.findall(r"\w+", prompt_lower))
        matched: List[Skill] = []

        # If input came from voice, always activate voice_interaction
        if source.startswith("voice") and "voice_interaction" in self._skills:
            matched.append(self._skills["voice_interaction"])

        # Proactive memory domain triggers: preferences, favorites, identity, habits
        memory_patterns = [
            r"\bfavorite\b", r"\bfavourite\b", r"\bprefer(?:ence|ences)?\b",
            r"\bremember\b", r"\brecall\b", r"\bmemory\b", r"\blmem\b",
            r"\bwho is\b", r"\bwhat is my\b", r"\bwhat's my\b", r"\bdo i (?:like|have|prefer)\b",
            r"\bmy (?:song|music|movie|routine|friend|family|habit|email|password|key|token|nickname)\b"
        ]
        if "memory" in self._skills and self._skills["memory"].enabled:
            if any(re.search(pat, prompt_lower) for pat in memory_patterns):
                matched.append(self._skills["memory"])

        for name, skill in self._skills.items():
            if not skill.enabled or skill in matched:
                continue

            # Exact skill name mentioned or keywords overlap
            if name in prompt_lower or bool(skill.keywords.intersection(prompt_words)):
                matched.append(skill)

        # If no specific skill matched, default to all enabled general skills
        if not matched:
            matched = [s for s in self._skills.values() if s.enabled]

        return matched

    def compile_instructions_for_prompt(self, prompt: str, source: str = "text") -> str:
        """Dynamically compiles instructions for skills relevant to the current prompt."""
        relevant_skills = self.find_relevant_skills(prompt, source)
        if not relevant_skills:
            return ""

        compiled = [
            f"### Active Skill: {s.name}\n{s.instructions}"
            for s in relevant_skills
        ]
        return "\n\n".join(compiled)


skill_registry = SkillRegistry()
