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

**The rule.** Fluid edge effect selection, keyed to the target. Later
generalized beyond fluids (the push_18 flying sign): may_harm NEVER points
at an already-hazardous target, whatever the source. Hitting a collapsing
house does not first-harm it; it makes an existing problem worse.

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
the target's state. Mental reframe: the "may" marks capability of the
channel ("CAN harm"), not probability; whether it currently IS harming is
the state's job.

**Deferred decision (2026-06-11):** Sunny tripped on the tense reading twice
(push_12, push_20), which is a signal the model may too. A rename to a
tense-neutral verb (harms) was considered and deferred: it would churn every
GT file, force re-freezing all goldens, and break comparability with the
June baseline metrics, all mid-verification. Revisit at the Stage 1 to
Stage 2 boundary, which is a planned schema version break anyway. Evidence
to gather first: during Stage 1 analysis, count how often the model misuses
may_harm on ongoing-harm scenes (the push_12 / push_20 class). If it trips
where the careful human tripped, that argues for the rename AND is itself a
reportable finding about tense reasoning in VLMs.

**Stage-1 evidence log (model tense errors on ongoing-harm scenes):**
- push_06 (drowning pool), run_20260618T125106: the model attached NO harm
  edge from the water to the drowning child at all — it never modeled the pool
  as a hazard, and emitted a self-referential `person_1 --[threatens|drowning]
  --> person_1` instead. It even used the victim's at-risk state (`drowning`)
  as a `via_state`, i.e. treated the ongoing-harm state as if it were the
  hazard channel. This is a model tripping on the ongoing-harm/tense
  distinction (the `may` framing did not cue it to bind actualized harm from
  the engulfing water to the victim). Argues toward the tense-neutral rename.

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

## 12. Counting houses is causal reasoning in disguise

**The story.** An aerial photo shows forty flooded houses. The rule says:
model a handful of representatives, not all forty. That sounds like
formatting advice. It is not. To compress forty houses into three, the
model must first judge that they are all the SAME situation: water
surrounds each, water escalates each, nothing else. And to know when NOT
to compress, it must spot the exception: the one house among forty that is
collapsing, not just flooded. That one earns its own node.

Grouping by causal sameness, and noticing the one that differs, IS causal
reasoning. A model that lists fifteen identical clones failed to see the
sameness. A model that buries the collapsing house in the crowd failed to
see the difference. Both are reasoning failures wearing a formatting
costume.

Half of this is checkable by machine, with no answer key: clone-counting.
If a graph has six nodes with the same label, same state, and same edges,
the checker flags it (redundant_instancing). The other half, missing the
one different house, needs eyes: the image or the GT comparison.

One exception, found during push_36 (twelve flooded cars, figures signaling
on the roofs): people are COUNTED, not summarized. "About four cars" and
"exactly four cars" lead to the same response; "three people stranded" and
"five people stranded" do not — boats and rescue trips depend on the count.
So every distinguishable person gets a node, and only an uncountable crowd
gets representatives plus a stated estimate.

The threshold (settled at push_39, three rescuer clusters of "4-6 each"):
count individually when the exact number is readable AND total people nodes
stay at six or fewer; otherwise one representative per causal situation with
the count in prose. Six is what fits beside a typical scene's hazards within
the node budget, and beyond six, rescue planning itself thinks in groups and
counts. Either way the number is never lost — it just moves from the node
list into the words.

**The rules.** Representative instancing (~10 nodes), with the people
exception. Checker rules redundant_instancing (people exempt) and
node_budget_exceeded.

**Where it lives.** Both prompts. Tests B10, O13, O14, O15.

---

## 13. The car is never the victim

**The story.** Training captions say "cars trapped in floodwater" all the
time. But a car cannot be a victim. Trace the harm: the water is the source,
the car is a waypoint (it receives harm, turns into a flooded wreck, and
passes danger onward), and the driver inside is the terminal: the harm
stops with him. "Who is the victim?" really asks "where does the causal
chain END?"

So the rule: distress states (trapped, drowning, stranded) belong to living
beings only. A vehicle or structure is intact, a converted hazard (crushed,
flooded), or at-risk by Proximity. The person inside is a separate node
with their own state. One physical object, two nodes, opposite
trajectories: the car can only worsen toward hazard-hood, the person can
only suffer toward distress.

The counterfactual check that shows the roles are real: take the driver out
of the car. Same physical trouble, urgency gone. A model that mourns the
empty car like the occupied one has not understood what the danger was for.
This also encodes the responder's objective function (life first, property
second) into the graph structure itself.

**The rule.** Living beings only (at-risk vocabulary section).

**Where it lives.** Both prompts. Tests C28, O17. Checker rule
distress_state_on_non_living. Born from Sunny's push_34 question.

---

## 14. Three words for people in trouble

**The story.** A man stranded on a car roof in floodwater used to
canonicalize to "fleeing". Sunny caught the absurdity: stranded means you
CANNOT move; fleeing means you ARE moving, fast. Near-opposites were sharing
one word because the vocabulary only had one non-medical distress state, and
everything got stuffed into it.

So the one overloaded family became three, each implying a different rescue:

- `fleeing`: in active flight (escaping, running_away). Rescue: clear the
  path, guide them.
- `trapped`: cannot move; circumstance holds them (stuck, stranded, clinging,
  struggling). Rescue: extraction — boat, ladder, dig.
- `cowering`: could move, but a direct threat pins them in place (crouching,
  ducking, hiding, surrendering). Rescue: neutralize the threat first.

The split also fixed a fairness trap of our own making: the model can only
pick from the canonical list, so for stranded people its least-wrong option
was literally "fleeing". We were forcing the mislabel, then ready to grade
it. And because GT files store the annotator's raw word (stranded, crouching)
while only the mapping underneath changed, not one GT file needed editing.

**The rule.** Three at-risk behavioral families (at-risk vocabulary section).

**Where it lives.** Both prompts. AT_RISK_STATES + STATE_SYNONYMS in main.py.
Tests A3, E12. Born from Sunny's push_36 objection.

---

## 15. Numbers don't mean anything until you group the mistakes

**The story.** A result screen says "5 conformance violations." That number
is noise. Five of WHAT? A reader cannot act on a count. But if you sort those
five into "three of them are the model misreading what an entity is, two are
it misreading who is in danger," now the screen says something: it tells you
HOW the model failed to think, not just that it failed. The Meaning Generator
turns raw rule-breaks into that one sentence.

**The rule.** Every conformance rule is assigned to exactly one of five
**cognitive failure families**. A family is a kind of blindness, plus an
authored meaning (what shortcoming the breaks reveal) and an authored decision
impact (what it costs an operator). The families:

| Family (plain label) | Rules in it | The shortcoming it reveals |
|---|---|---|
| **Misreads what an entity is** (`state_blind`) | may_harm_hazardous_target, distress_state_on_non_living, fluid_wrong_effect_for_person, hazardous_and_at_risk | Picks effects/states by surface association instead of checking what each entity currently is. Mislabels already-damaged things as freshly threatened, confuses victims with objects: misdirects triage. |
| **Misreads who is in danger** (`reach_blind`) | smoke_superset_violation, uncoupled_obstruction | Flags by presence, not geometry: never reasons about who is actually in a hazard's reach. Misses people downwind, raises false-alarm edges: alert fatigue. |
| **Misreads how entities connect** (`structure_blind`) | one_way_worsens, spread_between_hazards | Cannot track direction or mutual feeding between hazards: treats co-located hazards as one blob. Can't tell which intervention helps: recommends the wrong suppression. |
| **Cannot summarize** (`compression_blind`) | redundant_instancing, node_budget_exceeded | Lists what it sees instead of grouping by causal sameness. Floods the operator on large scenes, can't summarize a mass-casualty field. |
| **Hallucination / garbled structure** (`hallucination`) | effect_not_in_vocabulary, unresolved_endpoint, via_state_mismatch, via_state_not_hazard_bearing, edge_from_non_hazardous, self_loop_not_worsens, redundant_self_loop, hazard_flag_state_mismatch, hazardous_node_no_edges | Structurally invalid output: edges to entities that don't exist, invented vocabulary, self-inconsistent fields. Signatures of fabrication: the graph can't be taken at face value. |

The meaning is **authored into the family, not computed by a model.** This is
deliberate and it is the same methodological stance as the rest of CEE+: an
LLM interpreting our own measurements would reintroduce the exact rung-1
ungrounded-fluency problem we are studying. The interpretation has to be
engineered into the rule design so it is auditable. Deterministic in, same
sentence out, every time.

The same family idea drives two more surfaces: the conformance panel
**color-codes** each violation by its family color (red for hallucination or
multi-break families, amber otherwise), and the section header shows a
takeaway sentence plus family pills with hover popups. Pathology footprints
get the parallel treatment (cascade pills with arrows). The shared goal:
findings communicated fast, with WHY and SO-WHAT attached, never a bare count.

**Where it lives.** `FAILURE_FAMILIES` and the `RULE_TO_FAMILY` inverse map in
main.py; `generate_conformance_meaning` builds the takeaway; the colored panel
is `make_rule_conformance_panel`. Test Q1 enforces that every conformance rule
actually used in the code sits in exactly one family (total coverage, no
overlap), so a new rule cannot be added without giving it a meaning. The rest
of the Q-series tests the generator logic; the R-series (data-contract) tests
it against real captured run output so field-name drift can't slip through.

The same family framing is rolled up across a batch by `compute_family_rollup`
(carried in the report as `family_rollup`, rendered in the markdown export and
the report panel, tested by P6): which kind of blindness dominates the corpus,
in how many scenes, and what it costs a decision-maker. So the "what the breaks
MEAN" reading exists at both the single-scene and corpus levels.

---

## 16. Don't trust a ruler you haven't checked is straight

**The story.** Two of the trust score's terms ask "does the model's recommendation graph (A) agree with the model's own independent causal graph (B)?" That only means something if B is itself sound. If B is garbage (edges pointing at entities that don't exist, invented effect words, a hazard it never listed as a threat), then "A agrees with B" tells you nothing, and "A disagrees with B" might just mean A was right and B was broken. We were measuring A against a ruler without checking the ruler was straight.

**The rule.** Before the A-vs-B agreement terms count, discount them by how trustworthy B is. β (beta) = the average of B's validity signals: its own rule-conformance (is it structurally well-formed?), B-vs-threats coherence (do B's own hazards match the threats the model declared?), and, when a human-verified answer key exists for the scene, B's Test 1 accuracy (mean of B's recall and precision against that key). Each ranges 0 to 1. The agreement terms (A-fidelity, B-coverage) get multiplied by β; the weight that frees up moves onto the one signal that's always valid, the recommendation graph's internal alignment. A clean and accurate B leaves β = 1 and nothing changes; a broken or factually-wrong B quietly stops lending A unearned trust.

The subtle part: a trust score's whole job is to work when you do NOT have the answer key, because at deployment there isn't one. If β used Test 1, the score you compute on a verified scene would be made by a different formula than the score a live scene gets, and any band you calibrate would be calibrated on the wrong ruler. That is train/deploy skew. So the card shows TWO totals:

- **Total (deployment)** is the headline. β = mean(conformance validity, threats coherence). No answer key. This is what a live scene would score, and it drives the band.
- **Total (with B Test 1)** is a companion shown only on verified scenes. β also folds in B's accuracy vs the answer key, so agreeing with a factually-wrong B counts for less. Because the weight it removes from agreement-with-B lands on Graph A's own coherence, this number can sit either side of the headline.

Either way Test 1 is never a standalone term, so the gap the project exists to show is preserved: a model fluent and self-coherent (high internal alignment, the bulk of the weight) can still read as wrong against reality (low Test 1), because Test 1 never inflates the headline directly.

**Where it lives.** `_graph_b_validity` and `assess_pre_intervention_trust` in main.py; the breakdown panel shows β and where the freed weight went. Test F4 checks both the clean-B reproduction of the old formula and the malformed-B discount. This is the resolution of parked decision O12.

---

## The reasoning map: which rule forces which act of looking

Every rule in the prompts quietly demands one act of reasoning. This table
is the index. Column three says which machine check catches a failure, and
"eyes" means only the image or GT comparison can catch it.

| Rule | The reasoning it forces | Caught by |
|---|---|---|
| Fluid effect triad | Check what each target IS (victim? hazard? still safe?) | checker: fluid_may_harm_hazardous_target, fluid_wrong_effect_for_person |
| Distance thresholds | Check where each person STANDS relative to each hazard | eyes (C12-class) |
| Position, not role | Ignore uniforms; judge geometry | eyes; uniform-responder flag C25 hints |
| Mutual-hazard rule | Judge whether two hazards feed EACH OTHER or share one cause | checker: spread_between_hazards, one_way_worsens |
| Fluid provenance | Notice what produces what (fire makes the smoke) | checker: smoke_superset_violation; C22 on GTs |
| Independent harm channels | Keep heat and smoke as separate dangers with separate reach | checker: smoke_superset_violation, partially |
| Obstruction coupling | Ask: does this blockage actually matter to anyone in danger? | checker: uncoupled_obstruction; direction needs eyes |
| Occupancy rubric | Weigh evidence before inventing a person | eyes (count inferred nodes vs cues) |
| Representative instancing | Group by causal sameness; spot the exception | checker: redundant_instancing (over); eyes (under) |
| collapsing vs collapsed | Read motion evidence from a still image | eyes |
| may_harm tense | Read harm-in-progress from the target's state | checker: structural consistency of state + edge |
| Living beings only | Trace the harm chain to its terminal: who absorbs vs what transmits | checker: distress_state_on_non_living |

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
