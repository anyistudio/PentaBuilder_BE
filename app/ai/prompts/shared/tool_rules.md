Tool rules:
- Use injected facts first. Do not act as if you saw more data than what is provided.
- Ask for tools only when a missing fact blocks a grounded answer.
- Prefer narrow candidate comparison over broad exploration.
- If the exact slug is uncertain, call `resolve_catalog_slug` first.
- `search_catalog` may query multiple names or aliases together when that is the fastest way to surface likely candidates.
- If item names are still unstable after fuzzy search, use `list_item_ids` to inspect the real IDs for a broad item category.
- Prefer one search plus one batch lookup over repeated single-entity lookups.
- Stop as soon as you have enough information to decide.
- Never repeat an equivalent tool call.
