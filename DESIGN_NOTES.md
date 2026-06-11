# CEE+ Design Notes

Plain-language explanations of WHY the rules are the way they are. One entry
per idea. Each entry: an easy example first, then the rule, then where it
lives. Read this to rebuild the mental picture after time away.

Standing rule: every new schema rule gets an entry here, in the same turn it
is added. Simple words. If an idea is significant, saying it simply will not
diminish it.

---

## 1. The lie detector in the labels

**The story.** One flood scene. The same water touches three things. It
touches a drowning man: label `may_harm` (it is hurting him). It touches an
already-flooded house: label `increases_risk_to` (the house is already a
problem; the water makes the problem worse). It touches a dry house next
door: label `may_spread_to` (nothing happened yet, but it is about to).

Same water. Same touching. Three labels. The right label depends on what the
target IS right now. So to label correctly, the model must actually look at
each target. A lazy model that learned "water + house = harm" from thousands
of flood photos will write `may_harm` everywhere and get caught.

**The rule.** Fluid edge effect selection, keyed to the target.

**Where it lives.** Both prompts (fluid edge effect selection paragraph).
Test C27 checks our GT files. The runtime conformance checker (M7,
built 2026-06-10) runs the same check on the model's live answers.

---

## 2. Fire and smoke are two different dangers

**The story.** A house burns at night. A firefighter stands on the porch.
The homeowner sits on the lawn far back. The fire's heat can only hurt the
firefighter at the door. The smoke drifts everywhere and can hurt both. Now
imagine two rescues: spray water on the fire, and the heat stops at once but
leftover smoke still hangs in the air. Or vent the smoke, and the air clears
but the fire still burns. Two different actions, two different results.

If we mashed fire and smoke into one blob called "the fire," we could never
tell those two actions apart. A model that mashes them together will give
the same answer for both rescues, and that is exactly the kind of shallow
thinking CEE+ wants to catch.

**The rules.** Independent harm channels (each hazard gets its own edges,
judged separately). Fluid provenance (an edge from the fire to the smoke
saying the fire feeds it, so removing the fire removes the smoke).

**Where it lives.** Both prompts. Tests B7, B8, C22, C23.

---

## 3. Distance is measured in building heights, not meters

**The story.** A photo cannot tell you "the man is 12 meters from the
house." But it can tell you "the man is about one house-height away." So all
our distance rules use the building itself as the ruler.

Heat can hurt you within about one building-height of the flames. Falling
walls can reach about 1.5 building-heights (this is the real perimeter fire
departments use, called the collapse zone). A debris pile that already fell
can only hurt someone touching it or standing on it. Smoke reaches wherever
you can see the plume.

So the reach order, tightest to widest: debris < heat < collapse < smoke.

**The rules.** Reach thresholds. Plus: judge by POSITION, never by job. A
firefighter far from the house is just as safe as a bystander at the same
spot. Uniforms do not change physics. (We added that line after I myself
gave every firefighter a heat edge just for being firefighters.)

**Where it lives.** Both prompts (distance rule block). Test B1. Human
judgment during verification for the actual positions.

---

## 4. A calm pool can be a hazard, but only when someone is drowning in it

**The story.** A swimming pool on a normal day is harmless. The same pool
with a drowning child in it is the most dangerous thing in the scene. The
water did not change. The situation did. We needed a word for "this
substance is dangerous because it is wrapped around a victim," so we added
the state `engulfing`.

Important detail: you do not fix this by draining the pool. You fix it by
pulling the child out. That is, you cut the connection between hazard and
victim instead of removing the hazard. This matters later for the
intervention stage.

**The rules.** `engulfing` (only when a medium physically contains a victim
in distress) and `hazardous_in_context` (last resort when no word fits).

**Where it lives.** Both prompts. Test B4. Golden scene push_06.

---

## 5. Two burning houses feed each other

**The story.** House A and house B stand side by side, both on fire. Saying
"A's fire may spread to B" is silly: B is already burning. What is really
happening is they are making each other worse, heat and embers flying both
ways. So they get a `worsens` arrow in BOTH directions.

This also works across types: a brush fire next to a leaking fuel tanker.
The fire can ignite the fuel, and the fuel feeds the fire. Both directions.

One exception: two houses flooded by the same water are NOT feeding each
other. The water did it to both. The arrows come from the water.

**The rules.** Mutual-hazard rule, with the shared-cause exception.

**Where it lives.** Both prompts. Tests B2, C10, C11. Golden scenes push_02
and push_09.

---

## 6. Blocked paths only matter when someone needs the path

**The story.** A fallen tree across a trail on a calm day blocks nothing
that matters. The same fallen tree blocking the only exit of a burning store
is life-threatening. Blocking matters in two situations only: the person is
in danger and the blockage traps them or blocks their rescuers (coupled), or
the blocking thing itself strands them, like floodwater surrounding a family
on a roof (entrapment).

Direction matters too. In one scene, debris blocked a couple's path TOWARD a
burning building. That protects them, it does not endanger them. No edge.

**The rules.** Obstruction coupling rule.

**Where it lives.** Both prompts. Tests B9, C26.

---

## 7. No phantom people

**The story.** An aerial photo shows forty flooded houses. Should we assume
a person inside every one? No. That invents forty phantom victims. But a
house fire at 2 AM with a car in the driveway? Someone is probably asleep
inside, and the model should say so.

The difference is evidence. Fast disasters (night fire, explosion, collapse)
trap people because there was no warning. Slow disasters (hurricane, flood
with days of warnings) mean people mostly left. Night raises the odds people
are home. A visible hand at a window settles it.

When the evidence is not strong enough, the worry does not vanish; it moves
into the recommendations: "search the flooded homes." Doctrine in the
to-do list, not phantoms in the graph.

**The rules.** Occupancy cue rubric (strong, moderate, and veto cues).
Representative instancing (model a handful of representative houses, about
ten nodes max, and say "dozens more like these" in prose).

**Where it lives.** Both prompts (inferred-entity policy). Tests B10, B11.

---

## 8. "May harm" covers right-now harm too

**The story.** Water is drowning a man right now, but the label `may_harm`
sounds like the future. Do we need a new label like `harming`? No. Look at
the man's state: `drowning`. The state already says the harm is happening.
The edge says the channel, the state says the tense. Adding a second place
to store the same fact just creates two places that can disagree.

**The rule.** may_harm's definition covers ongoing harm; read the tense from
the target's state.

**Where it lives.** Both prompts (may_harm bullet). Test B12.

---

## 9. Every GT file carries a version stamp

**The story.** Sunny verified a scene on Monday. On Tuesday we improved a
rule. His Monday verification silently became outdated, and nothing told
him. Now every GT file carries the schema version it was checked under.
Change the rules, bump the version, and every outdated file raises its hand
automatically.

**The rule.** `schema_version` field, stamped on every save.

**Where it lives.** main.py constant SCHEMA_VERSION, save function, test C21.

---

## 10. Golden scenes: fifteen frozen anchors

**The story.** We kept improving GT files with automated sweeps, and twice a
sweep introduced errors into scenes that were already correct. So we picked
fifteen scenes, each the best example of one rule, and froze them like
museum pieces. If anything changes a frozen scene, even one character, a
test fails until a human deliberately re-approves it.

**Where it lives.** tests/fixtures/golden_scenes/ (catalog, hashes, freeze
script). Tests N1, N2, N3.

---

## 11. The two-column result

**The story.** When Stage 1 runs, every scene gets two grades. Column one:
how many rules did the model break in its answer (the shallow check, no
intervention needed). Column two: when we changed the world, did its answer
change the right way (the deep check).

Four kinds of model fall out of this table. Breaks rules and fails to
update: simply bad. Breaks rules but updates well: rare, probably noise.
Follows rules and updates well: genuinely grounded, the good case. And the
interesting one: follows every rule but fails to update. That model looked
at the scene carefully and still cannot imagine change. It is a well-behaved
guesser, and it is exactly what the paper is about, because no ordinary
evaluation would ever catch it.

**Where it lives.** Column one: the rule conformance checker in main.py
(built, shown in the UI next to internal alignment, surface-only). Column
two: the Stage 1 intervention pipeline (not built).

---

## The big picture: what all these rules are for

Think of CEE+ as a school exam for vision models, in three parts.

1. **The rulebook (the prompts).** The exam instructions. They force the
   model to look at the image: check what each target is, check where each
   person stands, check what feeds what. Every rule is a small lie detector,
   because following it requires looking, and breaking it reveals guessing.

2. **The answer key (your verified GTs).** The same rules, applied by a
   careful human. The test suite (1700+ checks) grades the answer key
   itself, so we trust it.

3. **The final exam (Stage 1 intervention, not built yet).** Change the
   world (put the fire out) and see if the model's answers change the right
   way. Rules cannot test this part; only intervention can.

Rule-breaking in the model's own output (its quads, its Graph A) is
meaningful BEFORE any intervention: each violation is evidence the model
pattern-matched instead of looked. That is a cheap, early reading of causal
groundedness. But passing the rulebook is not enough to prove grounding,
because a model could follow every rule and still fail to update when the
world changes. That is why the intervention stage exists.
