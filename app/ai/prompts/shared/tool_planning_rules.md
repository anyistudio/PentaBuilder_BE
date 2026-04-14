Tool planning rules:
1. Use tools only when the injected context, baseline, calibration summary, reference summary, session memory, and existing tool facts are still insufficient.
2. Ask for the minimum next facts needed to finish the task, not a full data dump.
3. Prefer `search_catalog` to discover candidates, then `batch_get_entities` to compare those candidates in one round.
4. If a canonical slug is not already confirmed, call `resolve_catalog_slug` before `get_*` or `batch_get_entities`.
5. When using `resolve_catalog_slug`, include `game`, `entity_type`, `raw_name`, and the best narrowing filters you already know.
6. Use `list_catalog_candidates` only with at least one useful filter such as champion lane, champion class, item category or subtype, rune path, or rune slot.
7. Prefer batch tools over repeated single-entity lookups when you already know multiple confirmed candidate slugs.
8. Never repeat a tool call that has already been executed with the same purpose.
9. If the current information is enough, return `done=true` and no tool calls.
10. Always fill `reasoning_summary` with a short user-visible progress note.
11. `reasoning_summary` must describe the missing facts and the next action, not hidden chain-of-thought.
