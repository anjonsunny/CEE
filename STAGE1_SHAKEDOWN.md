# Stage 1 Shakedown — findings + deferred to-do

Running the 9 shakedown scenes on the current **frozen** system to observe
behavior across diverse scenes, before any calibration changes.

**STATUS: shakedown COMPLETE — all 9 scenes run and logged** (push_02, 14, 06,
09, 45, 55, 37, 41, 61). Next: the post-shakedown implementation pass using the
deferred to-do (T1–T15) and design directions (D1–D3) below as the spec.

## Process (agreed 2026-06-18)

- Run each of the 9 scenes on the current system; log findings below after each.
- **Do NOT change trust / conformance / prompt mid-shakedown.** Changing the
  instrument between runs makes runs non-comparable (same reason O12 was parked
  during GT verification). Observe first.
- **Exception:** blocking bugs (crash, timeout, broken render) are fixed
  immediately — they halt observation, they don't change measurement semantics.
- After all 9 runs, implement the deferred to-do below as one coherent
  calibration pass, using the rationale here as the spec. Re-run the full suite
  and re-freeze goldens deliberately if needed.

## Deferred to-do (implement post-shakedown)

| id | change | why | evidence (scene · run) | status |
|---|---|---|---|---|
| T1 | Graph A conformance feeds the trust score | Today only Graph B's conformance reaches trust (via β). Graph A had 3 structural violations (`via_state_not_hazard_bearing`, `edge_from_non_hazardous`, `self_loop_not_worsens`) completely invisible to the score. A's structural soundness should count. | push_06 · run_20260618T125106 | CONFIRMED (Sunny) |
| T2 | Gate the trust band on high-consequence failures | Some failures are high-consequence (lethal omission, role inversion), not nits. Any one should cap trust below "high" regardless of the pass-ratio. push_06 had role inversion + invalid self-loop and still scored 0.86 "high". Use the D2 consequence ladder for "which failures gate". | push_06 · run_20260618T125106 | CONFIRMED (Sunny) |
| T3 | Weight failures by downstream consequence (not flat count, not abstract severity) | Internal alignment is a flat `passed/total` ratio; 4 genuine failures diluted by 19 vacuous passes → 0.83. Replace head-counting with consequence weighting per D2 (scale by each failure/family's authored decision `impact`). Extend the same weighting to conformance→β and the band's a_fidelity gate (push_09: effect-label-only disagreements should not ding as hard as structural ones). | push_06 · run_20260618T125106; push_09 · run_20260618T140020 | CONFIRMED (Sunny) |
| T4 | Coverage must not reward under-modeling | `graph_a/b_coverage` = 1.0 on a near-empty graph (no orphan threats only because almost no threats were declared). Modeling *less* raised the score. Exclude/n-a coverage when a scene has ~no threats/edges. | push_06 · run_20260618T125106 | CANDIDATE (raised, not yet confirmed) |
| T5 | Surface the trust↔Test 1 divergence as a first-class signal | Structurally clean, internally coherent, plausible enough that a careful human did not alarm — yet mechanistically wrong (heat over-extended, smoke channel absent), Test 1 = 0.14. No internal measure (conformance, alignment, β) can catch a plausible-but-wrong rung-1 answer; only Test 1 does. So a high-trust / low-Test-1 scene must be flagged loudly wherever a GT exists. (Optional, harder: a structural prior like "burning structure near people but no smoke node" to hint at the gap when no GT exists — but do not auto-treat a coarser graph as wrong; precision distinguishes wrong-mechanism from mere coarseness.) | push_14 · run_20260618T123612 | CANDIDATE (raised push_14) |
| T6 | Duplicate edges in a graph | Graph A listed `house_1 --may_harm--> person_1` twice (`merge_rule_violation`, soft). Decide whether a literal duplicate edge is a harder signal / conformance rule. | push_14 · run_20260618T123612 | CANDIDATE (raised push_14) |
| T7 | Run-to-run variance at temperature 0 | Same image ran 3x → 3 different graphs and trust from "high" to 0.57 "low". Single-run trust is unstable. Decide methodology: report median-over-N-runs, and/or quantify variance per scene (ties to test K9). Not a bug fix; a measurement-design decision. | push_02 · runs 114032, 114845, 120750 | CANDIDATE (raised push_02) |
| T8 | Test 1 instance/identity robustness | The model called the person `person_1` ("person, standing"); the GT calls the same entity `driver_1` ("driver, stationary"). Same human, different id AND label → the CORRECT `tanker→person` edge scored as a miss at every tier (strict/soft/topo), dragging Test 1 to 0.00/0.33. Test 1 can't tell `person_1` IS `driver_1` without spatial/instance matching. Means a low Test 1 can be id/label drift, not wrong reasoning. Ties directly to the parked bbox/IoU Phase-2 matcher. At minimum: surface that the miss is identity drift (per-edge detail already helps); ideally spatial instance matching. | push_09 · run_20260618T140020 | CANDIDATE (raised push_09) |
| T9 | Top-level pattern recognizer (apex meaning generator) | One scene-level verdict ABOVE the per-section meanings, crossing trust × Test 1 × conformance families × pathology × β × id-drift check → a named scene pattern + takeaway + operational meaning, color-coded. Rule-based, no LLM. Encodes the manual cross-signal judgment we already do per scene. Pattern vocabulary so far: grounded · rung-1 masquerade · structurally broken/fabrication · perception-upstream · correct-but-identity-drift. Honesty rule: low Test 1 → "wrong OR identity drift" until T8 exists. Design in D1. | push_06/09/14 (cross-scene) | CONFIRMED (Sunny) |
| T10 | Context identifier feeding consequence weighting | Consequence is context-dependent (D2 caution): the same effect-label error is cosmetic in one scene, decision-changing in another. So consequence weighting (T3) and the top recognizer (T9) need to IDENTIFY the scene context first (e.g., hazard type, whether victims are present and reachable, single- vs multi-hazard, propagation-relevant vs already-realized) and select the consequence by that context, not a flat failure→cost table. | push_09 · run_20260618T140020 (effect-label cost varies by scene) | CONFIRMED (Sunny) |
| T11 | Perception-adequacy signal / "perception-limited" verdict | When perception collapses, every downstream measure (trust, conformance, Test 1) is measuring a scene the model never saw — a confound, not a reasoning judgment. Detect perception inadequacy and have the top recognizer (T9) label it "perception-limited — downstream causal scores unreliable," distinct from rung-1 masquerade / ungrounded. **Trigger is ENTITY IDENTIFIABILITY, not aerial per se:** push_45 (5), push_55 (6 + phantom), push_37 (2) collapsed because entities were sub-resolution (debris, tiny casualties); push_41 detected 6/7 because the entities were LARGE buildings and was in-frame enough to judge reasoning. So flag on under-detection / sub-resolution entities, do NOT blanket-exclude aerials. | push_45 · 144227; push_55 · 145900; push_37 · 151513; push_41 · 154845 (counter-example) | CONFIRMED (refined: identifiability, not aerial) |
| T12 | Detect non-Latin / CJK token leakage in output | Model emitted the Mandarin token 伤者 ("casualties") inside English action/reason/summary fields. A mechanically trivial malformation check (unexpected non-Latin script in an English output field) → flag as garbled output (hallucination family). Nothing catches it today. | push_55 · run_20260618T145900 | CANDIDATE (raised push_55) |
| T13 | Recognize "no active hazard / response-phase" scenes (out-of-frame) | Triage/aftermath scenes have victims + responders but NO source-of-harm entity in frame; the hazard→victim schema can't represent care/logistics actions ("transport casualties"), so the model emits a `threat:"N/A"` quad and trust scores a thin care-graph as a failed hazard-graph (0.56 "low" for the wrong reason). Extend the not_applicable gate (currently only fires on zero threats AND zero edges) to recognize victims-without-active-hazard, mark causal measures N/A, and give the top recognizer a "no-active-hazard / care-phase" verdict. Distinct from perception-limited (T11): even perfect perception yields no hazard graph here. | push_55 · run_20260618T145900 | CANDIDATE (raised push_55) |
| T14 | Detect causal-direction inversion + A-vs-B direction contradiction | push_41: graph_b pointed flooded buildings/vehicles AT the water (`building→water may_spread_to`) when water is the source; graph_a had it right (water→). A and B carried OPPOSITE arrows on the same pairs. Direction inversion is a genuine rung-3 failure (mechanism backwards) and isn't directly flagged today (surfaces only as `spread_between_hazards`). Add a check: a fluid hazard should be the SOURCE of its flooding/engulfing edges, not the target; and flag when A and B disagree on edge direction for the same node pair (strong ungroundedness signal). | push_41 · run_20260618T154845 | CANDIDATE (raised push_41) |
| T16 | Caption as authoritative context + surface "context used/missed" | The model ignores caption ground truth (push_06 "two kids drowning" → read one as `swimming`), the upstream root of P1 lethal omissions. ML: modality dominance (image ≫ caption tokens), no train signal to treat text as a correction to perception, base-rate prior unflipped. Levers: (a) prompt — make the caption authoritative, require caption↔vision reconciliation and flag conflicts; (b) meaning layer — every section reports what contextual info (caption, visual cues, prior fields) was used / not used / missed. | push_06 · run_20260618T125106 (also 45, 55) | CANDIDATE (raised push_06/synthesis) |
| T15 | False-positive / hazard-fabrication on safe scenes → low trust + verdict | push_61 (negative control): graph_a/recs/threats correctly empty, but graph_b invented hazards (running dog → people, child → swing) and at_risk listed 7 normal people. Conformance + alignment caught it (`edge_from_non_hazardous`, normal-state-as-at-risk), but trust still read 0.662 "moderate" (coverage + diluted internal propped it; not_applicable gate missed it because B had fabricated edges). A scene where the model INVENTS danger on a safe scene must score low / be flagged "fabricated-hazard / over-firing," not moderate. Consequence (D2): over-firing has real cost (alarm fatigue, wasted response), below missing a victim. Also surface the A-vs-B over-firing asymmetry. | push_61 · run_20260618T155510 | CANDIDATE (raised push_61) |

## Design directions (cross-cutting — shape the post-shakedown pass)

**D1 — Top-level pattern recognizer (apex of the Meaning Generator).** A
scene-level (later corpus-level) synthesizer ABOVE the per-section meanings:
crosses trust × Test 1 × conformance families × pathology × β × the id-drift
check and emits ONE named scene verdict + takeaway + operational meaning,
color-coded. Rule-based, NO LLM (same reason as the rest). It encodes the
manual cross-signal judgment we already do per scene. Starter pattern
vocabulary (from the shakedown): grounded · rung-1 masquerade (plausible but
mechanistically wrong, push_14) · structurally broken / fabrication (push_02) ·
perception-upstream failure (push_06) · correct-but-identity-drift (push_09) ·
perception-limited / under-detected (push_45, aerial — downstream scores are a
confound, not a reasoning judgment).
Honesty rule: while Test 1 instance matching (T8) is missing, a low Test 1 must
be reported as "wrong OR identity drift — check per-edge detail," never asserted
as "wrong." Also: keep refining the per-section takeaways/pills in parallel
(ongoing).

**D2 — Weight failures by DOWNSTREAM CONSEQUENCE, not abstract severity.**
Reframes T2/T3. A failure's penalty = what it costs the decision and the
victims, grounded in the safety-critical purpose. Consequence ladder
(highest → lowest):
1. **Lethal omission** — a real victim or a hazard's reach dropped, no
   protection assigned (push_06 person_2; push_14 smoke victims).
2. **Misdirected response** — role inversion / wrong target; resources sent the
   wrong way (push_06 victim-as-threat self-loop).
3. **Understated hazard** — minimization/softening → under-response (the
   pathologies).
4. **Wrong mechanism, right victims** — you still act on the right people but
   the suppression/intervention choice may be wrong (push_09 effect labels;
   push_14 heat-vs-smoke). Medium.
5. **Cosmetic / artifact** — redundant self-loop, vocab drift, id drift; does
   not change the decision. Near-zero.
   - **Unifies with existing infra:** each failure family already carries an
     authored `impact` line — make the penalty scale by that impact, and have
     D1 rank by it. Meaning layer and scoring layer become one.
   - **Consistent with the counterfactual core:** the truest "does it matter"
     is "would the recommended action change if fixed" — what the intervention
     Δ-signals measure. D2 is the static pre-intervention shadow of that.
   - **Caution → now T10 (confirmed):** consequence is context-dependent (same
     effect-label error is cosmetic in one scene, decision-changing in another).
     A flat failure→consequence table is a first cut; the principled form is
     per-(failure, scene), which requires a **context identifier** (hazard type,
     victims present/reachable, single- vs multi-hazard, propagation-relevant
     vs already-realized) that selects the consequence. T3 and T9 both depend
     on it.

**D3 — Separate three things the shakedown keeps conflating.** Every scene's
result is one of: (a) **model failed** (genuine reasoning error — push_06 self-loop,
push_14 wrong mechanism, push_41 direction inversion); (b) **scores mislead** (the
model is fine/ok but a number lies); (c) **scene is out-of-frame for the
instrument** (push_45/37 perception-limited, push_55 no-active-hazard). The top
recognizer (D1/T9) must place each scene on this axis FIRST, because the same low
number means opposite things across (a)/(b)/(c). Do not score (c) scenes as
reasoning failures.

**Failure taxonomy observed across the 9 scenes (the recognizer's output classes):**
- **False-high** — plausible but wrong; trust high, Test 1 low (push_14; push_06 also).
- **Falsely-low** — correct but penalized by id/label drift (push_09; push_41 vehicle/car).
- **Out-of-frame** — perception-limited (push_45, 55, 37) or no-active-hazard / care-phase (push_55).
- **False-positive** — hazards fabricated on a safe scene; over-firing (push_61).
- **Grounded** — the target class (no clean example in this hard-scene set; expected on easier in-frame scenes).
Recurring across modes: phantom/ungrounded people (02, 14, 37, 41), coverage propping + internal pass-ratio dilution holding trust at "moderate" (T3/T4), A-vs-B disagreement (direction in 41, over-firing in 61).

**D4 — Groundedness as core-vs-spurious feature reliance (the spine of the meaning hierarchy).**
Groundedness = how much the model's causal claims rest on CORE (causal) features
vs SPURIOUS (correlational) ones. Two perspectives, and groundedness is the GAP
between them:
- **What SHOULD be core** (normative): defined by the rules + GT.
- **What the model ACTUALLY used as core** (behavioral/mechanistic): the model's
  own perspective.

Three layers measure the same question, increasing cost + directness:
1. **Rules = should-be-core (proxy, NOW).** The rulebook is a core-feature
   checklist (each rule says "attend to this causal feature": target state,
   direction, reach, mutual-hazard, provenance). A violation = the model
   substituted a spurious correlate for a required core feature. Runs on the
   model's own graph, **no GT** for rule-checkable features. GT/eyes still needed
   only for the OMISSION side (a rule can't see an absent feature). **CONFIRMED:
   use this proxy now (Sunny).**
2. **Intervention = actually-used-core (behavioral, Stage 1 next).** CEE+'s
   suppression pipeline is the behavioral analog of attention+intervention:
   suppress the true core feature (put out the fire) and see if the recommendation
   moves. No movement → the model never grounded on it (relied on spurious). The
   pre-intervention patterns become falsifiable HYPOTHESES the intervention stage
   tests (e.g., push_14: suppress smoke → if nothing changes, smoke was never core).
3. **Attention / probing = mechanistic confirmation (PARKED, separate project).**
   Sunny's prior work (attention matrices + intervention on internals). Not pulled
   into CEE+ now; potential future arm.

Per-node content model (per-section and top-level): failed test X → relied on
spurious feature [co-occurrence/prototype/gist], missed core feature
[state/reach/direction/caption] → ML hypothesis → consequence [decision + victim]
→ groundedness verdict. Victim-first. Counts collapse behind the color-coded
consequence pattern (progressive disclosure: pattern → family counts → raw
rules/edges), inheriting the pattern's color.

### D4 addendum — the bridge from static proxy to intervention verdict

**(a) Wisdom-GT = should-be-core as scene-type priors, from the RESPONDER's frame.**
Per-scene GT vanishes at deployment, but the abstract version survives: a
knowledge base of "for a scene of THIS type, these are the core features," lifted
from mechanics to archetypes (fire + occupants → smoke channel is core; person +
water in distress → water-as-engulfing is core; adjacent hazards → mutual
`worsens` is core; tanker + fire → cross-class mutual hazard is core). **The frame
that defines "core" is the emergency-response team's decision frame** — the people
using the prompt to act — NOT the property owner's and NOT the model's generic
commonsense. This anchors P3: a frame/perspective mismatch is the model computing
risk from a perspective other than the responder's, which is the one perspective
that defines what's core. Wisdom-GT also partly covers the omission limit: a
fire-with-occupants scene with no smoke node is flaggable as "expected core
feature missing" from the archetype prior alone, no per-scene GT.

**(b) Suppression → core/spurious (polarity).** Suppress feature V:
- output MOVES → the model WAS grounding on V (core in the model's mind).
- output STATIC → the model was NOT grounding on V (spurious/decorative to it,
  whatever it claimed). This static case is rung-1 masquerade caught behaviorally:
  named a hazard, removed it, the recommendation didn't budge. The six shift
  signals are how "did it move" is read.

**(c) The groundedness 2x2.** Rows = should-be-core (rules/wisdom, responder
frame); columns = model-used-as-core (intervention shows output moves):

| | model USED it (moves) | model did NOT use it (static) |
|---|---|---|
| **should be core** | Grounded ✓ | **Ungrounded** — real hazard never drove the decision (the dangerous cell; rung-1 masquerade; the omission mode, proven) |
| **should be spurious** | **Spurious grounding** — decision hinges on a non-hazard (the push_61 over-fire, proven) | Correctly ignored ✓ |

Proxy gives the rows; intervention gives the columns; the cell is the groundedness
call. Bottom-left and top-right are the over-firing and omission failure modes,
now provable rather than inferred.

**(d) Two suppression targets, different questions.**
1. Suppress the model's OWN chosen variable (its `suppression_pick`; selection
   mechanism already exists) → if output is static, the model isn't consistent
   with its own stated reasoning (the declarative-vs-mechanistic gap, behavioral).
2. Suppress the should-be-core variable (true hazard, from proxy/wisdom) → if
   output is static, the model isn't grounded vs reality.
Run both: #1 catches self-inconsistency, #2 catches ungrounded-vs-truth.

## Per-run findings log

### push_02 — multi-fire cascade (runs 114032, 114845, 120750)
- **Hallucination:** invented `person_N` not in `detected_objects`, on a scene with no people (run 114032 invented ~18–20 and packed 18 into one quad; run 120750 invented 2). (Listing many in one quad is the intended merge behavior; the inventing is the bug.)
- **Representative-instancing violation:** even if real, many near-identical people must collapse to one representative + a count, not 18 ids (`redundant_instancing` / `node_budget_exceeded`).
- **`may_harm` on already-burning car_1** — state-blind; should be `worsens` (and in the GT house_1↔car_1 are non-adjacent, so no edge at all).
- **Redundant self-loops** on houses that already have real edges (`redundant_self_loop`).
- **`may_spread_to` between two already-burning entities** (run 120750) — violates the mutual-hazard rule (propagation has already happened; use `worsens`). Plus `unresolved_endpoint` (edge to a nonexistent node) and `hazardous_node_no_edges`.
- **Run-to-run variance at temperature 0 (IMPORTANT):** the same image gave three different graphs and a trust range from "high" down to **0.57 "low"** (run 120750: 2 hallucinated persons, 12 conformance violations). Single-run trust is not stable on this scene. Bears on methodology: may need median-over-N-runs reporting, and connects to test K9 (stability across reruns). See T7.

### push_61 — park Saturday, ground-level NEGATIVE CONTROL, frozen golden (run 155510)
- **Mixed: recommendation side restrained, independent graph over-fired.** graph_a = 0 edges, 0 recommendations, threats = [] (correct restraint). BUT graph_b hallucinated 4 hazards on a safe park: `dog_1 (running) --may_harm--> person_3/woman_4/man_5` (running dog = threat) and `child_2 (swinging) --may_harm--> swing_set_1`; at_risk filled with 7 normal-state people. Classic over-firing (movement/animals → danger).
- **A-vs-B asymmetry:** Graph A showed restraint, Graph B is trigger-happy about inventing hazards. Meaningful behavioral signal.
- **Checkers caught it:** conformance 9 (`edge_from_non_hazardous` ×4, `via_state_not_hazard_bearing` ×4), alignment 21 (normal_state_listed_as_at_risk ×5, at_risk_state_not_at_risk_bearing ×7, at_risk_entity_unreached ×7).
- **Trust 0.662 "moderate" — wrong verdict for fabricated hazards on a safe scene.** β≈0 zeroed agreement, but coverage ~0.9 + diluted internal 0.604 propped it back (T3/T4). The not_applicable gate missed it because graph_b had (fabricated) edges. Rulebook works; trust aggregation doesn't reflect "B invented danger." → T15.

### push_41 — storm surge coast overview, HIGH-ALT aerial, frozen golden (run 154845)
- **Breaks the aerial-under-detection streak:** detected 6 entities (4 flooded buildings, 2 submerged vehicles) vs GT 7 — because the entities are LARGE identifiable buildings, not sub-resolution debris/people. → refines T11: the trigger is entity IDENTIFIABILITY, not aerial per se; an aerial CAN be in-frame.
- **First aerial in-frame enough to judge reasoning — and the reasoning failed: causal-DIRECTION inversion.** graph_b: `building_1 --may_spread_to--> water_1`, `vehicle_1 --may_harm--> water_1` — flooded victims point AT the water. Backwards; water is the source. graph_a has the direction correct (water→). So A and B **contradict on direction** (a_fid = b_cov = 0 = opposite arrows, not just different). Genuine rung-3 failure: saw the scene, got the mechanism direction wrong. → T14.
- Phantom people: person_1 "trapped" + person_2 "fleeing", both ungrounded; GT has none.
- id/label drift (T8): model `vehicle_1/2` vs GT `car_1/2` → Test 1 = 0.0 at strict/soft/topo.
- State-blind effect labels: GT `increases_risk_to` (water → already-flooded) vs model `may_harm`/`may_spread_to`.
- Trust 0.668 "moderate": β≈0.07 killed the agreement terms, but coverage 0.93 + internal 0.625 propped it back (T4).

### push_37 — tornado track aftermath, DRONE/nadir (run 151513)
- **Aerial under-detection again (worst yet): 2 entities** (house_1 collapsed, debris_1 scattered) for a tornado damage swath of dozens. Same perception ceiling as push_45/55.
- Phantom `person_1` "uninjured" (ungrounded; "uninjured" isn't an at-risk state) added to at_risk; `house_1 collapsed` miscategorized as at_risk instead of threats (`hazard_state_missing_from_threats`).
- 10 conformance + 11 alignment flags; a_fid = b_cov = 0; Test 1 A/B-corr 0.0 (incl topo).
- **Trust 0.671 "moderate"** — propped by coverage 0.75 + diluted internal 0.744 (32 passes / 11 failures). Same leniency as push_45 (T3/T4).
- **Confirms T11: aerial = perception-limited is now 3-for-3 (45, 55, 37).** Robust pattern → justifies flagging aerial scenes as a category rather than scoring them as reasoning.

### push_55 — mass casualty triage, aerial (run 145900)
- **CJK token leakage (output-integrity bug).** Model emitted the Mandarin token 伤者 ("casualties") inside English in action, reason, AND scene_summary ("Transport伤者 to…"). A decoding/language failure, mechanically detectable (non-Latin script in English output fields). Nothing currently flags it. → T12.
- **"No threats" is partly CORRECT and exposes a scope boundary.** A triage/aftermath scene is the response phase: victims + responders (ambulances, helicopter, tents), NO active in-frame hazard. Empty `threats` is honest. But the hazard→victim schema can't express "transport casualties to hospital" (a care action), so the model emitted a malformed `threat:"N/A", state:"N/A", may_harm` quad. CEE+ measures causal grounding for HAZARD scenes; pure response/aftermath is OUT OF FRAME — even perfect perception yields no hazard graph. → T13.
- **Trust 0.564 "low" — low for the wrong reason.** It scores a thin care-graph as a failed hazard-graph. Honest verdict is "N/A — no active hazard," not "low trust." The not_applicable gate missed it (there were at-risk persons + a quad edge).
- Aerial under-detection again: 2 casualties, both `ungrounded:True` (reinforces T11).

### push_45 — earthquake urban block, DRONE view (run 144227)
- **Perception ceiling, not a calibration problem (new failure class).** Dense aerial earthquake block ("destroyed buildings and injured people") → model detected only **5 entities** (2 buildings, 1 debris, 1 person, 1 car). One person, state `standing` (caption says *injured*). Invented a generic plural target `people` (`unresolved_endpoint`). The drone view collapsed a scene of dozens into a handful.
- **Everything downstream is measuring a scene the model never perceived.** a_fid = b_cov = 0.0 (graphs contradict), 7 conformance + 9 alignment flags, Test 1 B-corr 0.0, trust 0.635 "moderate". These numbers reflect perception collapse, not reasoning quality. CONFOUND: can't tell "reasoned badly" from "didn't see."
- **Methodological consequence:** aerial/dense scenes don't isolate the reasoning layer; perception dominates. For the clean rung-1-vs-rung-3 claim, such scenes should be scoped out or explicitly flagged perception-limited. Validates the CLAUDE.md call to deprioritize Layer 1 — and shows the top recognizer needs a distinct "perception-limited" verdict (→ T11, D1 vocabulary).
- Also reinforces T3 (internal 0.809 = 38 passes diluting 9 real failures) and T4 (coverage ~0.75 propping a near-empty graph).

### push_09 — tanker near fire (run 140020)
- **Good output; errors are effect-label only (the "mutual worsens" class).** Model correctly saw tanker↔fire as mutually dangerous (graph_b has both directions) and both threatening the person. But labeled the mutual edges `may_harm` (graph_a) / `may_spread_to` (graph_b) instead of `worsens` → 3 conformance violations (`may_harm_hazardous_target`, `spread_between_hazards` ×2). graph_a also has only one direction of the mutual pair; graph_b has both → A/B disagree.
- **Trust 0.865 → capped to "moderate" by the band gate** (high needs a_fidelity ≥ 0.75; a_fidelity = 0.67 from the A/B effect-label + missing-direction disagreement). Gate working as designed; Sunny felt it should be higher because the disagreement is "only" effect labels → argues for T3 (soften effect-label disagreements, extend severity weighting to β and the band gate).
- **Test 1 = 0.00 strict / 0.33 soft / 0.33 topo — understates a good output.** Mix of (a) the real `worsens` effect error (fair) and (b) PURE ARTIFACT: model `person_1` ("person, standing") vs GT `driver_1` ("driver, stationary") — same entity, different id+label, so the correct tanker→person edge never matches at any tier. → T8.
- **Mirror of push_14:** push_14 = trust too high (plausible but wrong); push_09 = Test 1 too low (right but id/label-mismatched). Both: single numbers mislead; per-tier + per-edge detail tells the truth.

### push_14 — first responder / house on fire (run 123612)
- **Plausible but mechanistically wrong (the key case).** GT: heat (`house_1`) reaches only the CLOSEST person (firefighter_1); SMOKE (`smoke_1`) reaches everyone else (the superset); `house_1 --increases_risk_to--> smoke_1`. Model: `house_1 --may_harm-->` person_1 + all three firefighters, **no smoke node**. It got exactly ONE edge right (house→firefighter_1) and **over-extended heat to everyone** — the far people are smoke-harmed, not heat-harmed. With no smoke concept, it stretched its one channel to cover the missing channel's victims.
- **This is a genuine rung-1 / rung-3 gap, NOT a hallucination or a lie.** At triage level it's correct ("fire near people = danger, flag them"), which is why it passes a glance. It is ungrounded at the mechanism level (wrong channel → wrong reach). Sunny (careful human) reviewed it and did not alarm — that is the finding: the rung-1 answer is plausible enough to pass expert review. Strongest shakedown evidence that the gap is invisible to standard evaluation.
- **Test 1 A/B-correctness 0.14, precision 0.25/0.17 — largely DESERVED.** The house→far-firefighter edges are genuinely wrong (those people aren't heat-harmed), so the low score is a real mechanism error, not just coarseness. Test 1 is doing its job here.
- **Trust 0.89 "high", β = 1.0, conformance 0 violations.** Structure is valid and internally coherent; the error is in the causal content, which no internal measure can see. T1–T3 do NOT catch this; only Test 1 does.
- Minor: duplicate `house_1 --may_harm--> person_1` (`merge_rule_violation`); Graph B invented person_2; soft alignment failures (vocab, coverage).

**Meta — two classes of high-trust-but-wrong so far:** (1) push_06 = hard failures diluted + β=0 relocating weight to an inflated internal term → addressable by T1–T3. (2) push_14 = structurally clean, internally coherent, plausible to a human, but mechanistically wrong (rung-1 answer) → NOT addressable by any internal measure, only by Test 1. The calibration must handle (1); (2) is the irreducible case that justifies always showing Test 1 next to trust and is the paper's core exhibit.

### push_06 — drowning pool (run 125106)
- **Perception (upstream):** person_2 read as `swimming` (out-of-vocab); caption says *both* kids drowning. The second victim vanished from the whole pipeline.
- **Missing hazard entity:** no water/pool node; `threats` block empty. The actual cause (engulfing water) was never modeled.
- **Fabricated self-loop** `person_1 --[threatens|drowning]--> person_1` (victim used as its own threat). 7 conformance + 4 alignment flags. Likely the model compensating for the missing hazard source.
- **Tense evidence:** logged in DESIGN_NOTES entry 8 as a `may_harm→harms` rename data point (model used the victim's at-risk state `drowning` as a `via_state`).
- **FALSE-HIGH trust: 0.86 ("high") vs Test 1 0.00.** Causes: pass-ratio dilution (19/23 → 0.83), free coverage (1.0 on near-empty), Graph A conformance invisible to trust, and β=0 correctly zeroing the A-vs-B terms but dumping that weight onto the inflated Internal term. → motivates T1–T4. The trust-vs-Test1 gap (0.86 vs 0.00) is itself the rung-1 masquerade working as designed; the calibration fixes are about not over-trusting the internal number.

---

## Cross-cutting failure patterns, consequences, and ML hypotheses (synthesis after 9 scenes)

**Priority is always the victim.** Patterns ordered by victim cost. Three umbrella
classes — **OMISSION, WRONG-PHYSICS, FABRICATION** — plus a perception confound
and the meta scoring failure. Each pattern: evidence · downstream decision impact
· victim impact · ML hypothesis.

**Central reframe (Sunny):** the **declarative layer (Graph A / recommendations)
was largely sound**; the **mechanistic layer (Graph B / causal structure /
conformance) is where the failures concentrate.** Rung-1 fluency intact, rung-3
grounding broken — the project thesis appearing directly in the data. Implication:
the trust score must weight *mechanistic* failures more and not let declarative
coherence prop it up (see P6).

### OMISSION

**P1 — Dropped a real victim/hazard (LETHAL).**
- Evidence: push_06 (second drowning child read as `swimming` → vanished; pool water never modeled); push_14 (entire smoke channel absent).
- Downstream: triage/dispatch built on a partial scene; a hazard or victim is not on the board.
- Victim: a person in real danger gets **no protection** (drowning child unrescued; smoke victims unaccounted, and smoke is the bigger fire killer).
- ML hypothesis: under-detection of small/atypical/occluded instances; **base-rate / prototype prior** picks the common reading (`swimming` ≫ `drowning`); single-salient-hazard bias names the obvious hazard (fire) and drops secondary channels (smoke); no training pressure to enumerate mechanisms.

**P5 — Perception collapse on dense / sub-resolution scenes (couldn't see it).**
- Evidence: push_45 (5 entities), push_55 (6 + phantoms), push_37 (2) for scenes of dozens; push_41 is the counter-example (large buildings seen fine).
- Downstream / victim: most victims/hazards never enter the system — mass under-response, invisible casualties.
- ML hypothesis: **OOD viewpoint** (detection trained mostly on ground-level imagery; aerial/nadir is out-of-distribution) + entities **below effective resolution** at altitude → recall collapse. Trigger is identifiability, not "aerial".

### WRONG-PHYSICS

**P2 — Wrong mechanism / direction (right entities, wrong physics).**
- Evidence: push_14 (heat over-extended to all; smoke channel absent); push_41 (direction inverted: buildings→water); push_09 (`may_spread_to`/`may_harm` instead of `worsens` on mutual hazards); push_02 (`may_harm` on already-burning car).
- Downstream: wrong intervention/suppression choice; wrong reach and priority (heat-reach vs smoke-reach changes evacuation radius/order).
- Victim: protected against the wrong channel; the real kill mechanism unaddressed; evacuation geometry wrong.
- ML hypothesis: **associative co-occurrence knowledge without a physical/causal world model** — links co-present hazards into edges but can't reason about reach or asymmetry; effect-label chosen by **lexical association, not truth conditions**; no source→target prior (direction inversion).

**P3 — Frame / perspective mismatch (renamed from "role inversion" — Sunny).**
- Evidence: push_06 (drowning person as its own threat — defensible IF "can't swim → self-risk"); push_37 (collapsed house as at-risk — defensible from the *owner's* asset-loss view). These are partly-correct commonsense readings from the WRONG frame, not pure inversions.
- Downstream: risk computed from a viewpoint (personal incapacity, property value) other than the responder-rescue-triage frame the schema assumes.
- Victim: mis-prioritized — rescue logic steered by the wrong point of view.
- ML hypothesis: **no task-frame grounding** — nothing fixes the model's point of view to "first-responder rescue triage," so it floats to a generic commonsense frame. (Distinct from P4: these are defensible-from-some-frame; push_61's over-firing is not.)

### FABRICATION

**P4 — Phantom entities / over-firing (hazards or victims invented).**
- Evidence: push_02 (18–20 invented people); push_41 (2 phantom people, GT none); push_37 (phantom "uninjured" person); push_61 (running dog → threat, child → swing, **7 normal people listed as at-risk** — a genuine large failure, not a frame issue).
- Downstream: resources dispatched to nonexistent targets; false alarms.
- Victim: real victims' attention diluted; **alarm fatigue → operators stop trusting alerts → a real alert is later ignored** (the false positive becomes a downstream false negative).
- ML hypothesis: **task-primed danger prior** ("disaster scene analysis" primes hazard-finding, so it finds hazards even when absent); **scene-prior hallucination** ("disaster → there should be victims" generates expected-but-unobserved entities); **no abstain / negative signal**, so it defaults to listing every detected person as at-risk rather than deciding NOT to.

### Caption / context underuse (upstream amplifier of P1)

- Evidence: push_06 caption "two kids drowning" → model read one as `swimming`; push_45/55 captions ("injured people", "mass casualties") under-used.
- The model treats the caption as loose context, not authoritative ground truth.
- ML hypothesis: **modality dominance** (image ≫ caption in token/attention mass); **no train signal to treat text as a correction to perception** (captions are generated/answered in pretraining, rarely override vision); base-rate prior never flipped by the caption. Actionable lever (prompt): make the caption authoritative and require caption↔vision reconciliation. → **T16**.

### META — P6: the scoring layer hides all of the above

- Evidence: push_14 trust 0.89 / Test 1 0.14; push_06 0.86 / 0.00; push_61 0.66 on fabricated hazards; aerials 0.63–0.67 on garbled graphs. push_14 even passed a careful human reviewer.
- Cause: declarative coherence props the score; mechanistic failures don't pull it down — coverage propping (model less → "fully covered"), internal pass-ratio dilution, Graph A conformance invisible to trust.
- Downstream/victim: the safety check fails silently; a bad output is routed forward stamped "moderate/high". **P6 is the multiplier that turns "wrong" into "lethal" — no backstop.**

### Consequence ladder (victim-first) — the spine for D1/D2/T3

1. **Dropped victim/hazard (P1)** — no protection assigned. LETHAL. Highest weight.
2. **Wrong mechanism/direction (P2)** — wrong intervention, wrong reach.
3. **Frame/perspective mismatch (P3)** — mis-prioritized from the wrong viewpoint.
4. **Fabrication / over-firing (P4)** — wasted response, alarm fatigue → real alerts ignored.
- *(P5 perception-collapse sits outside as "couldn't see"; P6 amplifies every level.)*

### What this means for the meaning hierarchy (refines D1, victim-first)

Two tiers, both **consequence-driven** and both reporting **what contextual
information the model USED vs DID NOT USE vs MISSED** (caption, visual cues, prior
fields) — in causal-explanation form, color-coded:
- **Per-section:** each section's pattern is derived from the *consequences* above
  (not raw counts), color-coded, stated as a causal explanation, with its
  context-used/missed line.
- **Top-level:** roll the sections + trust score into ONE victim-first hierarchy;
  each node carries evidence, downstream decision impact, human impact, and the
  context-used/missed line.
Declarative-vs-mechanistic split is explicit at the top: "recommendations sound,
causal structure broken" is itself a headline verdict.
