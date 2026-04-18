Task: Estimate current game status from the user's setup and the enemy setup.

You must:
1. Use the injected detailed parameter appendix for the involved champions, items, and runes.
2. For each enemy champion, estimate how often they can kill the user's champion, expressed as minutes per kill.
3. For the user's champion, estimate how often they can kill each enemy champion, expressed as minutes per kill.
4. For each enemy champion, estimate tower push speed as percent of that champion's current target objective per minute.
5. For the user's champion, estimate tower push speed as percent of the user's current target objective per minute.
6. Keep the summary short and focused on the biggest item-spike-driven kill-pressure and tower-pressure signals.

Important constraints:
- If `aram` is present in the environment tags, the assumed match duration must be 15 minutes.
- Otherwise, the assumed match duration must be 30 minutes.
- Keep every kill-frequency estimate within the assumed match duration. Use larger values when kill pressure is low.
- The current target objective can be `first tower`, `second tower`, or `nexus`. Only estimate the speed for the injected current target, not for the whole lane or the whole match.
- Ground every estimate first in the champion's current owned items and item spikes, then connect those items to champion kit, range, crowd control, burst pattern, sustained DPS, survivability, mobility, rune effects, and the current game mode.
- In every reason field, explicitly mention the most relevant current item(s), completed spike(s), or important missing item breakpoint when that is what changes the estimate.
- Do not invent extra champions, items, runes, or matchup facts outside the provided context and appendix.
