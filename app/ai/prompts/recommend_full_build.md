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
- `recommended_build_order` is a purchase sequence, not a final six-slot inventory snapshot.
- Return 6 steps for a normal path with no separate enchant step.
- You may return 7 steps only when the build path includes both:
  1. one boots item, and
  2. one separate enchant item.
- If both boots and enchant appear, they must occupy separate steps and the boots step must come first.
- Never output an enchant step without a boots step in the same build path.
