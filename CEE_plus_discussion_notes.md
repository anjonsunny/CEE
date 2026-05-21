# CEE+ — Discussion Notes and Plan

Date: 2026-04-13

These notes capture the discussion between Sunny and Claude about the CEE+
project, specifically the motivation-building phase (evaluating where a
multi-modal VLM baseline goes wrong) and the prompt-refinement step that
precedes it.

## 1. Project framing (recap of idea.txt)

CEE+ (Controlled Causal Evaluation Engine) measures the causal groundedness
of a VLM by testing whether the model:

- identifies the true causal factors
- updates its reasoning structure after intervention
- adapts its recommendations accordingly

The core pipeline is: baseline analysis → single suppression intervention →
post-intervention analysis → compute shift signals (hazard, graph,
recommendation, structural alignment, semantic alignment, cross-modal
consistency) → aggregate score + explanation.

The contribution claim is that a baseline VLM can produce coherent threat
identification, recommendations, and structured reasoning, but that reasoning
remains *declarative* rather than *mechanistically verified*. CEE+ exposes
the causal structure explicitly and enables intervention-based transparency
for safety-critical decision support.

## 2. Baseline and code setup

- `main.py` is a Dash app that calls Qwen2.5-VL via Ollama's OpenAI-compatible
  endpoint and returns a structured JSON with detected_objects,
  threats_and_risks, recommendations, structured_reasoning triples,
  expected_consequence, remaining_risk, and follow-up actions.
- `experiments/scene1..6` hold test scenes; `exports/` holds prior runs.
- The current prompt (lines 15–75 of main.py) has 24 rules defining each
  field but very few rules governing cross-field consistency.

## 3. Failure-mode taxonomy (three layers)

The failure-mode analysis is organized into three layers, each motivating a
different CEE+ signal:

- **Layer 1 — Perception failures.** Missed objects, hallucinations, wrong
  state attribution. Traditional VLM errors. Motivates state-grounded nodes
  in the causal graph.
- **Layer 2 — Reasoning-coherence failures.** Output looks structured but
  the structure is cosmetic — cross-field inconsistencies visible from the
  JSON alone. Motivates needing a graph (not just triples) and needing
  self-consistent reasoning.
- **Layer 3 — Causal / counterfactual failures.** Reasoning isn't anchored
  to the hazards it names; intervention reveals the decoupling. This is the
  core CEE+ territory.

### Decisions made

- Deprioritize Layer 1 for now.
- Focus on Layer 2 and Layer 3.
- Do qualitative / illustrative analysis first; quantitative later.
- Single-scene walkthroughs preferred over scattered examples (cleaner
  narrative, stronger paper).

## 4. Layer 2 — the four patterns we are focusing on

1. **Broken grounding links.** `related_object_ids` points to ids not in
   `threats_and_risks`; `structured_reasoning.hazard` names an entity not in
   detected_objects. The triple looks valid but doesn't anchor to the scene.
2. **Reason / structured_reasoning drift.** Natural-language `reason`
   describes one hazard mechanism; the triple encodes a different one.
   Reason and triple are generated in parallel rather than one being a
   faithful compression of the other.
3. **Effect-label misuse.** The fixed effect vocabulary (threatens,
   may_spread_to, blocks_access_to, isolates, exposes, may_harm,
   increases_risk_to, worsens) gets used generically — usually defaulting
   to `threatens` — when a more specific label is available and applicable.
4. **Suppression-variable ambiguity.** Multiple threats with overlapping
   reasons and no indication which is driving `disaster_level`. This is the
   bridge to Layer 3 and is **deferred** from Layer 2 analysis; it will be
   analyzed through intervention instead.

### Framing choice

Patterns 1 and 2 are *self-consistency* failures; pattern 3 is an
*expressiveness* failure of the vocabulary; pattern 4 is an expressiveness
failure of the output format itself. Framing all of these as "declarative
outputs, no matter how well-formed, cannot carry causal content" unifies
them and makes the transition to Layer 3 cleaner than framing them as "the
model is sloppy."

## 5. Worked example — three recommendations on a burning-house scene

The user shared three recommendations from a run (burning house + car +
person scene). The observed inconsistencies were:

**Broken grounding links**

- `related_object_ids` shows "House (threat), House (threat), Car (threat)"
  — House duplicated, suggesting unstable or non-unique object_ids.
- Rec 2 `affected_entity = residents` — "residents" is not a detected
  object; only a single `person` was detected. Plural category invented.
- Rec 3 `affected_entity = structures` — plural, ungrounded; only one house
  detected.
- The Car is cited in `related_object_ids` of all three recs but never
  appears in any `hazard` field.

**Reason / structured_reasoning drift**

- Rec 1 reason: "The burning house **and car** are immediate threats."
  Triple: `hazard = burning_house` only — the car disappears between surface
  language and the structured representation.
- Rec 2 reason mentions "the person and other residents"; triple's
  affected_entity is "residents" only — the grounded entity (person) drops
  out, only the ungrounded plural remains.
- Rec 1 `expected_consequence`: "The fire is contained and the person is
  safe" — but the action is *contact emergency services*. Containment is
  Rec 3's job. The consequence of Rec 1 is actually the consequence of
  Rec 3.

**Effect-label misuse**

- All three recs use `effect = threatens`, the generic default.
- Rec 3 is explicitly about containing spread — `may_spread_to` is the
  natural label.
- Three different affected_entities (person / residents / structures) link
  to the same hazard via the same generic effect. If the effect were doing
  real work we would expect `may_harm`, `isolates`/`exposes`, and
  `may_spread_to` respectively.

**Fifth pattern noticed — residual-hazard templating**

`remaining_risk` is near-identical across all three recs ("the fire may
spread to other structures and vehicles…"). Rec 3 (containment) specifically
addresses spread, so its remaining_risk should *not* be "fire may spread."
The model uses `remaining_risk` as a template slot, not as a per-action
causal update. This is particularly damaging because `remaining_risk` is
the field supposed to demonstrate reasoning about action consequences.

## 6. Prompt improvement — direction

### Diagnosis of why the current prompt failed

- The 24 existing rules describe *what each field contains* but not *how
  fields must relate to each other*. All the failures above are cross-field.
- `recommendations: array of 3 objects` forces exactly three — drives
  templated padding when the scene has only one real causal logic.
- `object_id` is free-form; nothing enforces uniqueness or stable reuse.

### Principles for the revised prompt

1. Shift rules from per-field to relational (cross-field consistency).
2. Reduce mandatory cardinality — allow 1–4 recommendations based on
   distinct causal logics.
3. Make object identity load-bearing — unique stable ids used in every
   reference. Turns many semantic checks into string-equality checks.
4. Couple `expected_consequence` and `remaining_risk` to the *specific
   action*, not the overall scenario.
5. Give the effect vocabulary real work — short disambiguating definitions
   with truth conditions, plus a "choose the most specific applicable label"
   meta-rule.
6. Add a terminal self-check block — cross-field verification the model
   performs before returning. Keep it to 4–5 checks.

### Specific leverage points (for discussion → implementation)

- **Stable object_ids** of the form `label_N` (`house_1`, `house_2`,
  `car_1`, `person_1`). Used verbatim in threats_and_risks,
  related_object_ids, hazard, affected_entity. Labels are for humans; ids
  are for linkage.
- **Grounded affected_entity** — must be either an object_id in
  detected_objects, or a plural/abstract category with a required
  `grounding_ids` sub-list naming the specific detected ids it abstracts.
- **Hazard as state, not object** — `hazard` becomes a state expression
  like `fire_on_house_1`, not `burning_house`. Matches idea.txt line 173
  and makes the prompt CEE+ ready because suppression later operates on
  states.
- **Reason/triple coverage** — every object_id in the reason text must
  appear in `related_object_ids` and in the triple's `hazard` or
  `affected_entity`. Multiple distinct hazards → multiple recommendations,
  not one compressed triple.
- **Variable recommendation count** — 1–4, one per distinct causal logic.
  No two recommendations with identical hazard/effect/affected_entity
  triples.
- **Effect-label definitions with truth conditions** — one line each:
  - `threatens` — direct proximate danger, contact or imminent contact
  - `may_spread_to` — hazard may propagate via physical contiguity
  - `blocks_access_to` — physical obstruction prevents reaching
  - `isolates` — cuts off from escape or resources
  - `exposes` — protective barrier removed
  - `may_harm` — potential harm without proximate contact
  - `increases_risk_to` — enabling factor
  - `worsens` — escalates an already-present danger
  - Meta-rule: `threatens` only when no more specific label applies.
- **Action-coupled consequence fields**:
  - `expected_consequence` — immediate result of *this specific action*
    assuming success, not downstream effects of other actions.
  - `remaining_risk` — must reference at least one object_id or hazard
    state the action did not address. Identical remaining_risks across
    recommendations are disallowed.
- **Terminal self-check block** — before returning, verify: (1) every
  referenced object_id exists in detected_objects; (2) every threat/risk
  named in any reason appears in that rec's related_object_ids and triple;
  (3) each effect is the most specific applicable choice; (4) each
  expected_consequence describes its own action's result; (5) no two
  recommendations share remaining_risk.

### Design tensions noted

- **Prompting strength vs. evaluation validity.** A heavily engineered
  prompt raises the question: are we evaluating the VLM or the prompt?
  Stance: give the baseline its best shot so remaining failures are
  unambiguously the model's — state this methodologically in the paper.
- **Constraint vs. reasoning freedom.** Hazard-as-state and stable ids
  constrain the *format* the reasoning lives in, not the reasoning itself.
  Acceptable. Keep the self-check block short to avoid templated
  self-verification text.

### Non-negotiables vs. additive

- Non-negotiable (do first): stable object_ids, hazard-as-state,
  reason/triple coverage.
- Additive (second pass): effect-vocabulary tightening, terminal self-check.
- Free and cheap: variable recommendation count.

## 7. What we want to do next

1. Move to a fresh project folder.
2. Revise the prompt in `main.py` focusing first on the three
   non-negotiables (stable object_ids, hazard-as-state, reason/triple
   coverage). Leave effect-vocabulary tightening and the self-check block
   for a second pass.
3. Rerun the baseline on a few scenes from `experiments/` with the revised
   prompt.
4. Collect illustrative Layer 2 failure examples (patterns 1, 2, 3) from
   the revised-prompt outputs — these are the "even with a strong prompt,
   the model still…" examples that motivate CEE+.
5. Defer suppression-variable ambiguity (pattern 4) to the Layer 3 /
   intervention phase where it belongs.
6. Qualitative first, quantitative later.
7. Future ablation: test graph-conditioned recommendation generation. Question:
   if we force explicit causal structure first (`scene -> causal graph ->
   recommendations + quads`), do recommendations become more grounded? Keep
   this separate from the main CEE+ pipeline, because the current goal is to
   evaluate whether direct VLM recommendations preserve causal structure rather
   than repair them by conditioning on an explicit graph.

## 8. Open items to resolve before implementation

- Decide on the exact object_id format once we see a scene with multiple
  instances of the same category.
- Decide whether `affected_entity` abstractions require a `grounding_ids`
  list or whether we simply forbid plurals the first pass.
- Confirm whether the terminal self-check is part of pass 1 or pass 2 —
  currently noted as additive but it may be worth trying early because it
  is cheap.
