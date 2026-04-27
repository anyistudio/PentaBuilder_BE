Task: Explain whether the current slot choice is good and what the best choice should be.

You must:
1. Judge the current item in the target slot under the current match context.
2. Return a system item rating with `item_rating` and `item_rating_reason`.
3. State whether the current choice is good enough.
4. If there is a better item, name that best item clearly.
5. Explain why the current item works or fails.
6. Explain why the best item is better.
7. Mention linked follow-on slot adjustments only if they materially matter.

Rating standard:
- `S`: insanely targeted; it directly punishes the enemy setup and feels like the perfect answer.
- `A`: clearly reasonable and strong; this will not drag the build down.
- `B`: the direction is basically right, but there is an obviously cleaner or sharper option.
- `C`: not great, but at least the idea is related to what the champion needs.
- `F`: completely wrong direction, like building tank items on a burst assassin for no reason.

Important constraints:
- Stay specific to the actual slot, current build state, and enemy context.
- If the slot is empty, explain the best next item instead of pretending there is a current choice.
- If the current item is acceptable but not optimal, say that clearly instead of forcing an extreme good/bad framing.
- If you recommend a better item, explain the practical tradeoff the current item is losing.
- Use direct, easy gamer language. Be a little sharp if the item is bad, but do not insult the user personally.
- `item_rating_reason` should be one short sentence that can be shown beside the item badge.
