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
9. For each enemy champion, estimate tower push speed as net percent of that champion's current target objective per minute.
10. For the user's champion, estimate tower push speed as net percent of the user's current target objective per minute.
11. Keep the summary short and focused on the biggest current item-spike and stat-profile signals.
12. Write user-facing text in direct, easy-to-understand gamer language.
13. For the user's build-facing comments, focus first on the user's latest owned item:
    - judge whether that newest completed/current item actually fits the current enemy profile, timing, and game mode;
    - if it is not ideal, name the concrete problem, such as wrong damage profile, too greedy, no survivability, poor penetration timing, delayed core spike, or low tower value;
    - recommend one better item direction by item name when there is a clearer alternative.

Important constraints:
- If `aram` is present in the environment tags, the assumed match duration must be 15 minutes.
- Otherwise, the assumed match duration must be 30 minutes.
- Keep every kill-frequency estimate within the assumed match duration. Use larger values when kill pressure is low.
- The 0-10 base-stat values are relative rankings across all champions in the current game, not exact raw game numbers.
- Make the user's and enemy's stat profiles comparable: if one side has clearly stronger current items for a stat, reflect that difference in the 0-10 values.
- Let high health/armor/magic_resist lower incoming kill pressure, and let high physical_attack/magic_attack/penetration raise outgoing kill pressure.
- Treat tower pressure as practical net tower progress, not raw turret DPS. Start from the champion's tower-hitting profile, but then adjust for whether their current items and stat profile let them actually stand near the wave and hit the tower.
- Let tower pressure follow the current damage profile and item spikes; basic attack speed, sustained physical/AP damage, spellblade effects, ranged uptime, waveclear, and minion access usually matter more than one-shot burst.
- Before writing any tower_push_percent_per_minute, compare the user's current strength against the relevant enemy strength. If a champion's build is wrong, too greedy, too squishy, behind on damage/penetration, or likely to get killed/forced off wave, reduce their tower push even if their kit could hit towers quickly in a vacuum.
- Conversely, if a champion has a clear combat/item advantage, strong survivability, good waveclear, or can safely zone the opponent, raise their practical tower pressure because they get more uncontested tower windows.
- Explicitly account for push obstacles: dying before the wave crashes, being chunked out, lacking minions, losing side-lane control, poor waveclear, weak dueling into the visible enemy, or needing to respect enemy engage/CC.
- Do not estimate tower pressure as if this were a pure 1v1 tower-hitting test. Assume a normal balanced 5v5 match: the visible champions are the focal matchup for this analysis, while the other eight players are present and broadly competent unless the provided context says otherwise.
- Assume teammates on both sides are roughly evenly matched and not making major mistakes. Do not invent a solo-lane duel, isolated custom game, or permanent 1v1 split unless the environment explicitly says so.
- Ground every estimate first in the champion's current owned items and item spikes, then connect those items to champion kit, range, crowd control, burst pattern, sustained DPS, survivability, mobility, rune effects, and the current game mode.
- In every reason field, explicitly mention the most relevant current item(s), completed spike(s), or important missing item breakpoint when that is what changes the estimate.
- In the user's `own_tower_push_reason` and each `own_kill_frequency_vs_enemies[*].reason`, make the latest owned item the main talking point whenever the user has at least one owned item.
- If that latest owned item is good, say why it fits and what it unlocks now. If it is shaky, say what is wrong with it and name a more suitable item direction.
- If the user has no owned item yet, talk about the first-item direction that would solve the current matchup instead of giving a limitation disclaimer.
- For `summary`, `status_evaluation`, `reason`, `kill_reason`, `tower_push_reason`, use wording that sounds like a teammate quickly explaining the game state in voice chat.
- Prefer short punchy sentences over formal analysis. Say the main point directly first.
- Mildly sharp or playful roast is allowed when it clarifies the logic, for example "伤害够了，但身板还是纸" or "这件装一出，对面脆皮就别太装".
- Do not insult the user personally, do not use hate speech, and do not turn the answer into empty trash talk.
- Avoid academic phrasing such as "综合来看", "在当前语境下", "具备一定能力", or "需要注意的是" unless it is truly the clearest wording.
- Each `status_evaluation` must explain which concrete sources caused the strongest base-stat advantages or weaknesses:
  - champion baseline identity or kit profile, such as a naturally tanky champion, AP burst mage, AD assassin, marksman, or low-defense enchanter;
  - current state, such as completed/owned item count, gold state, rune effects, game mode, K/D pressure, tower target, or pre-first-core timing;
  - specific current owned items and their relevant bonuses.
- Do not write a generic playstyle summary in `status_evaluation`. Tie the evaluation to the actual 0-10 stat differences.
- When a stat gap is mostly item-driven, name the item and the affected stat, for example that one item meaningfully raises magic_attack, armor, penetration, or health.
- When a stat gap is mostly champion-driven, say that the advantage comes mainly from the champion's natural profile rather than current items.
- For the user's `status_evaluation`, compare against the most relevant enemy profile or enemy average. For each enemy `status_evaluation`, compare against the user's current profile.
- Do not say or imply that the analysis is blocked because current owned items, runes, or exact build progress are missing.
- If a side has no current owned-item information, treat it as not having completed the first core item yet, and analyze from that pre-first-core state.
- If rune information is absent, assume the champion is using a standard default rune page for that champion and mode.
- When information is missing, continue the analysis directly from the known champion, mode, tower target, and visible state instead of adding a limitation disclaimer.
