Task: Produce the single best ordered build continuation for the provided match context.

You must:
1. Produce one best ordered build array using canonical item slugs.
2. Keep `recommended_runes` empty for now: `primary=[]`, `secondary=[]`.
3. Do not spend tool calls on rune discovery or rune comparison for this workflow.
4. Explain the overall build direction briefly.
5. Keep the plan coherent across early, mid, and late steps.
6. Add short slot notes only for the steps where timing, matchup pressure, or sequencing really matters.
7. Respect the requested recommendation span:
   - if `recommendation_count` is omitted/null, fill every remaining empty step
   - if `recommendation_count` is a number `N`, fill only the next `N` empty steps and leave later empty steps as `null`

Important constraints:
- Respect already filled slots as locked constraints.
- Do not replace a filled slot with another item.
- Choose one best build, not a menu of equal options.
- Use the baseline as the starting reference when it fits, but depart from it if the actual enemy pressure or environment tags clearly justify it.
- Make slot notes useful. Do not add generic item praise or filler.
- `recommended_build_order` is a purchase sequence aligned to the game's full slot count, not a static final inventory snapshot.
- Treat `recommended_runes` as a temporary placeholder field only. Leave it empty even if rune information is available.
- When the recommendation span is limited, prioritize the earliest realistic next purchases and keep later empty steps as `null`.
