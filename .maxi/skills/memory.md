# LMEM Memory
Retrieves and maintains persistent user memories, workstation configurations, project setups, credentials, and preferences using LightMem (`lmem`).

## Guidelines
- Whenever you need to recall past context, user facts, project setups, credentials, or preferences, use LMEM memory to recall the verified facts before answering.
- Use `lmem recall "<query>" --global --multi-hop` to fetch verified ground-truth memories.
- Formulate concise, focused keyword queries (e.g. "HP workstation specs", "Groq rate limits", "project location").
- Always use recalled facts directly in your answers with zero speculation or hallucination.

## Memory Persistence
- NEVER store arbitrary memories automatically.
- ALWAYS ask the user for explicit confirmation before persisting any memory.
- Connect concepts intentionally via explicit relationships (`[[wikilinks]]`, `lmem link`). Do not use autolink.
