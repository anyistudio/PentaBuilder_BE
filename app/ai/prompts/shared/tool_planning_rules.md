Tool planning rules:
1. Use tools only when the injected context, baseline, calibration summary, reference summary, session memory, and existing tool facts are still insufficient.
2. Ask for the minimum next facts needed to finish the task, not a full data dump.
3. Prefer `search_catalog` to discover candidates, then `batch_get_entities` to compare those candidates in one round.
4. Prefer batch tools over repeated single-entity lookups when you already know multiple candidate slugs.
5. Never repeat a tool call that has already been executed with the same purpose.
6. If the current information is enough, return `done=true` and no tool calls.
