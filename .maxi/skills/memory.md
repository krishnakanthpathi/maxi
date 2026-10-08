# Persistent Memory (LightMem)
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
