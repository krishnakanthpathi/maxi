#!/usr/bin/env python3
"""
Imports or regenerates the LightMem (LMEM) memory skill into .maxi/skills/memory.md.
Adheres strictly to global memory management guidelines:
- Always use the lightmem CLI (`lmem recall`, `lmem answer`, `lmem remember`, `lmem link`).
- Explicit confirmation required before persisting any memory.
- Multi-hop traversal enabled (`--multi-hop`).
- No autolink.
"""

import sys
from pathlib import Path

SKILL_CONTENT = """# Persistent Memory (LightMem)
Retrieves and manages persistent user memories, personal workstation facts, hardware configurations, project locations, and preferences across sessions using the `lmem` CLI and database (`~/.lightmem/memories.db`).

## Retrieval Guidelines
- Whenever the user asks about personal configurations, workstation specs, IP addresses, credentials, project locations, rate limits, past architectural decisions, or preferences:
  - Call the `lmem_recall` tool or run `lmem recall "<query>" --global --multi-hop` to fetch verified ground-truth memories.
  - Formulate concise, focused keyword queries (e.g. "HP workstation specs", "Groq rate limits", "Telugu TTS location").
  - Use retrieved facts directly in your answers with zero speculation.

## Memory Persistence Rules (Strict)
- **NEVER** persist arbitrary facts or learnings automatically.
- **ALWAYS** ask the user for explicit confirmation before saving any memory (e.g. "Would you like me to remember that your favorite font is JetBrains Mono?").
- When confirmed, use `lmem remember "<memory>" -t <type> --title "<title>" --tags "<tag1>,<tag2>"`.
- Connect related concepts intentionally using `[[wikilinks]]` or `lmem link`. Do not use `autolink`.
"""


def import_skill():
    root_dir = Path(__file__).resolve().parent.parent
    skills_dir = root_dir / ".maxi" / "skills"
    skills_dir.mkdir(parents=True, exist_ok=True)

    target_file = skills_dir / "memory.md"
    target_file.write_text(SKILL_CONTENT.strip() + "\n", encoding="utf-8")
    print(f"✅ Successfully wrote LightMem skill to {target_file}")


if __name__ == "__main__":
    import_skill()
