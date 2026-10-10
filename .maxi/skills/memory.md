# LMEM Memory
Retrieves and maintains persistent user memories, workstation configurations, project setups, credentials, and preferences using LightMem (`lmem`).

<!-- triggers: favorite, favourite, prefer, preference, preferences, remember, recall, memory, lmem, song, movie, music, routine, habit, friend, family, secret, nickname, who is, what is my -->

## Guidelines
- Whenever the user asks about personal preferences, favorite items (e.g. "my favorite song", "my favorite movie", "my routine"), friends, habits, or past context, you MUST ALWAYS query LMEM memory FIRST using `lmem_recall` or `lmem_answer` before taking any other action.
- NEVER search public search engines or hallucinate answers for user-specific personal preferences without checking memory first.
- Use `lmem_recall(query="...")` to perform semantic recall across memories with multi-hop context (e.g. query="favorite song", query="daily routine").
- Use `lmem_answer(question="...")` for direct factual answers to questions about the user (e.g. question="what is my favorite song?").
- Always use recalled facts directly in your actions and answers with zero speculation.

## Memory Persistence
- NEVER store arbitrary memories automatically.
- ALWAYS ask the user for explicit confirmation before persisting any memory.
- Once confirmed by the user, use `lmem_remember(content="...")` to persist the fact.
- Connect concepts intentionally via explicit relationships (`[[wikilinks]]`, `lmem link`). Do not use autolink.
