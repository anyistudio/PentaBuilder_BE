Task: Produce the single best ordered full build path and rune setup for the provided match context.

You must:
1. Produce one best ordered build path using canonical item slugs.
2. Produce one best rune setup.
3. Respect already filled slots as locked constraints.
4. Explain the overall build direction briefly.
5. Add short slot notes only for the build steps where explanation adds value.

Important constraints:
- Do not replace a filled slot with another item.
- Choose one best build, not a menu of equal options.
- Keep the plan internally coherent across early, mid, and late steps.
- Use the baseline as the starting reference when it fits, but depart from it if the actual enemy pressure or environment tags clearly justify it.
- Make slot notes useful: mention timing, matchup pressure, or build sequencing, not generic item praise.
- `recommended_build_order` is a purchase sequence, not a static final inventory snapshot.
- For League of Legends PC:
  1. Return exactly 6 item steps.
  2. Do not output a separate enchant step.
- For Wild Rift:
  1. Return exactly 7 steps.
  2. The 7 steps must contain exactly 5 normal items, 1 boots item, and 1 separate enchant item.
  3. The boots step and the enchant step must occupy different positions.
  4. The boots step must come before the enchant step.
