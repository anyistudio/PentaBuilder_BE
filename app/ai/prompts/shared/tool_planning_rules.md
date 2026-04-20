Tool planning rules:
1. Return only the next minimal round, not a full research plan.
2. Prefer one high-value call. Use two only when they are clearly complementary.
3. Prefer `search_catalog` to discover candidates, then `batch_get_entities` to compare confirmed candidates.
4. Use `list_catalog_candidates` only with a meaningful filter.
5. If you know a raw Chinese or English item/rune name but not the exact slug, prefer `resolve_catalog_slug`.
6. If name resolution is still shaky for items, use `list_item_ids` with a broad category such as `physical`, `magic`, `boots`, or `enchant`.
7. When using one `search_catalog` query for multiple names, keep the query tightly scoped to the same entity type.
8. Fill `reasoning_summary` with a short user-visible progress note about the missing facts and the next action.
9. If the current context and tool facts are already enough, return `done=true` with no tool calls.
10. Return exactly one top-level JSON object. Never concatenate multiple JSON objects.
11. Use the schema field names exactly: `reasoning_summary`, `tool_calls`, `done`, and within each tool call use `tool_name` and `arguments`.
12. Never use alias keys such as `tool` or `args`, and never include final-answer fields during tool planning.
13. For `search_catalog`, `entity_type` must be exactly one of `champion`, `item`, or `rune`. Never use pseudo-types such as `mixed`.
14. For `list_catalog_candidates`, always provide an explicit `entity_type` and at least one real filter inside `arguments`.
