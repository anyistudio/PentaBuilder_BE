Task: Estimate the current kill pressure and tower pressure from the user's setup and the enemy setup.

You must:
1. Use the injected current builds, runes, tower targets, and detailed parameter appendix.
2. First estimate each involved champion's current base-stat profile on a 0-10 relative scale.
3. Include health, physical_attack, magic_attack, armor, magic_resist, armor_penetration, and magic_penetration.
4. Estimate those 0-10 values from both champion baseline identity and current owned item/rune bonuses.
5. Add one short status_evaluation for the user's champion and for every enemy champion.
6. Then use those estimated base stats as an explicit input for kill cadence and tower pressure.
7. For each enemy champion, estimate how often they can kill the user's champion, expressed as minutes per kill.
8. For the user's champion, estimate how often they can kill each enemy champion, expressed as minutes per kill.
9. For each enemy champion, estimate tower push speed as percent of that champion's current target objective per minute.
10. For the user's champion, estimate tower push speed as percent of the user's current target objective per minute.
11. Keep the summary short and focused on the biggest current item-spike and stat-profile signals.

Important constraints:
- If `aram` is present in the environment tags, the assumed match duration must be 15 minutes.
- Otherwise, the assumed match duration must be 30 minutes.
- Keep every kill-frequency estimate within the assumed match duration. Use larger values when kill pressure is low.
- The 0-10 base-stat values are relative rankings across all champions in the current game, not exact raw game numbers.
- Make the user's and enemy's stat profiles comparable: if one side has clearly stronger current items for a stat, reflect that difference in the 0-10 values.
- Let high health/armor/magic_resist lower incoming kill pressure, and let high physical_attack/magic_attack/penetration raise outgoing kill pressure.
- Let tower pressure follow the current damage profile and item spikes; basic attack and sustained damage usually matter more than one-shot burst.
- Ground every estimate first in the champion's current owned items and item spikes, then connect those items to champion kit, range, crowd control, burst pattern, sustained DPS, survivability, mobility, rune effects, and the current game mode.
- In every reason field, explicitly mention the most relevant current item(s), completed spike(s), or important missing item breakpoint when that is what changes the estimate.
- Do not say or imply that the analysis is blocked because current owned items, runes, or exact build progress are missing.
- If a side has no current owned-item information, treat it as not having completed the first core item yet, and analyze from that pre-first-core state.
- If rune information is absent, assume the champion is using a standard default rune page for that champion and mode.
- When information is missing, continue the analysis directly from the known champion, mode, tower target, and visible state instead of adding a limitation disclaimer.
