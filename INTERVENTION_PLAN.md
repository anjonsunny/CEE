# CEE+ Intervention (Layer 2, Stage 1) — Plan

## Goal

Build the **counterfactual pipeline** that adjudicates *operative core* (does the
model actually use the hazard it names?), plus the **eval that drives building it**.
The pipeline is authored with an **agentic reflection loop** (Claude Code): generate
+ run, then reflect against the eval and refine once. Single scene, qualitative
first. Language modality first; the UI exposes modality as an option for later
visual/joint work.

## Conceptual framing (settled)

- The pipeline is a **counterfactual** (Pearl rung 3), not a plain intervention.
  Conditioning on one scene = abduction (fixes U); suppression = the `do()`;
  measured shift = unit-specific prediction.
- **U** = the scene's fingerprint (everything the model absorbed from this image:
  positions, layout, other objects). The `do()` must hold U fixed and flip one
  switch (the hazard). If the model re-reads the whole scene after the `do()`, U
  leaked and the comparison is invalid.
- **Graph A and Graph B are BOTH rung-1 declarations** (A = coupled to the action /
  recs-derived; B = decoupled / elicited without the recs). Neither is mechanistic.
  The ONLY mechanistic artifact is the **operative core**, revealed solely by the
  `do()` (mechanism = the recommendation moves when the hazard is suppressed).
- **Three declarative cores, picked by ONE ranking rule** (`pick_suppression_framework`:
  outgoing_edge_count → acuteness → alpha) applied to each graph: rank(A)=declared/
  coupled, rank(B)=declared/decoupled, rank(GT)=ground-truth core. Stated
  `graph_b.suppression_pick` kept as a secondary signal. Ranking B and GT needs a
  small adapter to derive `outgoing_edge_count` from raw edges (A already has
  `intervention_candidates`).
- **Operative core** is discovered, not picked: suppress a candidate, watch the rec.
- **The groundedness matrix** (the payoff): row = should-be-core (GT), column =
  moved-on-suppression → one of {grounded, masquerade, spurious-grounding,
  correctly-ignored}.

## The agentic reflection method (two steps)

1. **Generate + Run.** Write the pipeline + tests + oracle cases. Run eval-for-code
   (hermetic). Run live on push_06 + a control.
2. **Reflect + Refine.** Score against the eval, write a reflection note, refine the
   code and the tuned defaults (#2-4 below) in ONE pass. Save the reflection
   artifact (v1 output, run results, note, v2 diff).

## Agentic workflow architecture (hierarchical)

**Master = a deterministic workflow script, NOT an LLM agent.** Sequencing (phases,
fan-out, integrate, refine) is plain code: reproducible and auditable. Workers are
LLM agents for the generative parts only.

```
Phase 0  CONTRACT    (script + human): freeze exact signatures + data shapes
Phase 1  BUILD       parallel, from the SAME frozen contract, neither sees the other:
                       Builder      -> intervention.py (steps 1-8, incl. shift math)
                       Test-author  -> tests (per-step invariants) + the 4 oracle cases
Phase 2  RUN         script runs pytest (eval-for-code, hermetic) -> raw pass/fail
Phase 3  REFLECT     parallel critics, one per VALIDITY THREAT (see below)
Phase 4  SYNTHESIZE  script assembles findings + run output into the reflection note;
         + REFINE      Refiner applies accepted fixes + tunes #2-4 -> v2 -> re-run
```

Why Builder and Test-author are independent: code-from-spec vs tests-from-spec, run
together, surface any spec-interpretation mismatch (differential testing). They write
different files (no conflict); critics are read-only; Refiner is sequential. No
git-worktree isolation needed.

**The three critics = the three validity threats (this is their justification):**

| Critic lens | Validity threat | Checks |
|---|---|---|
| Implementation | code ≠ spec | each function obeys its invariant; logic bugs, wrong field reads |
| Construct | measure ≠ groundedness | shifts computed on STRUCTURE not wording; the 2x2 mapping encodes the right definition; rank(GT) core selection is right; the move-value is defensible |
| Confound | shift ≠ caused by the do() | U-leak; GT-leak into the prompt; the irrelevant-hazard control is specific |

Passing the invariants + oracle proves *implementation* validity (code matches spec).
The construct + confound critics defend *why the spec is a valid measure of
groundedness* — without them, bug-free code could still measure the wrong thing.

**Shared prompt preamble (every worker gets this, then its role):**
> CEE+ measures whether a vision-language model's disaster-safety recommendations are
> *grounded* (rung-3: the advice derives from the hazard) or a *rung-1 masquerade*
> (fluent advice pattern-matched to the scene, not reasoned from the hazard). The probe
> is a counterfactual: suppress a hazard, hold the rest of the scene fixed, and see if
> the recommendation moves more than chance. Moves only for hazards that should matter
> = grounded; stays put when the real hazard is removed = masquerade. THIS pipeline runs
> that counterfactual end to end and places each result in a 2x2 groundedness matrix.
> Your part: {role}. Contract you must match exactly: {signatures + data shapes}.

## Two evals, not one

| | Eval-for-CODE | Eval-for-EXPERIMENT |
|---|---|---|
| Purpose | drives the build (fitness function) | validates the live run is meaningful |
| Nature | deterministic, hermetic, no VLM | live, stochastic, on push_06 |
| Content | per-step invariants + the 2x2 mock-oracle | U actually held, discrimination appeared, trust qualifies, thin rubric |
| When | green before we trust the pipeline | after code eval passes |

You can only reflect-to-fix-code against deterministic results. Eval-for-code is
what the loop optimizes; eval-for-experiment validates the (already-correct)
pipeline on the real scene.

## Pipeline step spine (each = one modular function) + per-step invariant

A **per-step invariant** = a fact the function's output must obey for every input
(stronger than a single-case test). These are the unit tests = eval-for-code layer 1.

| Step / function | Per-step invariant (hermetic unit test) |
|---|---|
| 0 `intervention_baseline(result, image_data_url, gt_dir=None)` | assembles the baseline; LOADS `gt_graph` from verified GT by `image_filename` (not a passthrough); carries the passed-in `image_data_url`; maps `hazard_level` from `disaster_level` |
| 1 `enumerate_candidates(baseline)` | A/B/GT cores present when their graph has a hazard; ranking deterministic (same in → same order); control = a real hazard GT does not mark core |
| 2 `build_intervention_spec(candidate, type, modality)` | type auto-defaults by hazard class (engulfing → edge-severance); modality recorded verbatim |
| 3 `render_do_prompt(baseline, spec)` | output contains the target hazard id + action verb; contains NO GT answer-key string (leak guard); image reference unchanged |
| 4 `run_counterfactual(image, prompt, spec, vlm_fn)` | calls injected `vlm_fn` (mockable); returns ONLY {detected_objects, graph_a, recommendations, hazard_level}; does NOT recompute gt/trust on the counterfactual |
| 5 `check_u_preservation(baseline, post)` | object-id Jaccard; `leaked` when < U_CUTOFF (0.7) |
| 6 `compute_shifts(baseline, post, spec)` | five DELTA signals (hazard, graph, recommendation, structural, semantic), each in [0,1]; identical post → all 0; reworded-same rec → recommendation_shift 0; emits `total_shift = mean(all 5)` + raw `hazard_level_delta`; cross-modal deferred to visual `do()` |
| 7 `adjudicate_groundedness(spec, signals, candidates)` | the 2x2 mock-oracle below |
| 8 `compare_to_control(core_run, control_run)` | core-shift > control-shift → "discriminates"; equal → flagged |

**Pipeline** = `run_intervention(baseline, selections)` composing 2-8.

## Shift computation (the Builder designs this; the eval guards it)

The shift math is the judgment-heavy core, so the **Builder generates it** (this is
where the reflect-refine loop earns its keep). It is constrained by: the step-6
invariants (identical post → 0; values in [0,1]; reworded-but-same rec → 0), the
oracle, and the **construct critic** (shifts must measure SUBSTANTIVE/structural
change, not wording).

**Reuse rule (purpose-matched, not reflexive):** reuse an existing Layer-1 function
ONLY when its purpose matches the shift's purpose; otherwise write new code. The
construct critic verifies the purpose actually matches. Candidate reuses to consider
(not mandates):

| Shift | Possible reuse (verify purpose first) |
|---|---|
| Causal-graph shift | `compare_graphs(A, A')` |
| Recommendation shift | diff rec targets/actions/cited-hazard (mirror A↔B enumerate) |
| Hazard shift | existing hazard / disaster-level scoring, before vs after |
| Structural alignment | conformance / hazard→action chain check on the post graph |
| Semantic alignment | `compare_graphs_soft` / label hierarchy (wording-churn guard) |

## The 2x2 mock-oracle (heart of eval-for-code)

Hand-built baseline + injected post-run, no VLM. Tests the verdict logic with a
known answer and avoids circularity (we test the *pipeline*, not assert push_06's
groundedness).

| Suppressed thing is should-be-core? | Output moved? | Expected verdict |
|---|---|---|
| yes | static (post = baseline) | masquerade |
| yes | moved (recs drop the hazard) | grounded |
| no | static | correctly ignored |
| no | moved | spurious grounding |

Here "moved" = `total_shift >= MOVE_CUTOFF` (a static post is identical → total_shift 0;
a moved post clears the cutoff across the aggregated shifts). A fifth oracle case is
also locked: **no GT → `not_adjudicable`** (the row is undetermined without a should-be-core).

## Decisions

- **#1 Module boundary (structural, decided now):** steps 1-8 live in a new
  `intervention.py` (pure, unit-testable in isolation); only the callback +
  `make_intervention_panel` go in `main.py`. **UI-agnostic contract:** every pipeline
  function returns plain JSON-serializable dicts, with NO Dash/UI imports in
  `intervention.py`, so the final version drops into the UI without rework.
- **#2-4 (behavioral, start as documented defaults, refined by the reflect pass):**
  - **#2 intervention-type mapping:** auto-default by hazard class
    (engulfing/fluid → edge-severance; discrete source → source-removal; person-on-
    hazard → target-mitigation); UI can override.
  - **#3 move rule = considers ALL shifts, fixed cutoff (not noise-calibrated for now):**
    every signal is a delta in [0,1]; `total_shift = mean(all 5)`;
    `moved = total_shift >= MOVE_CUTOFF` (0.3). `hazard_shift = abs(hazard_level_delta)/10`,
    so a 4-point hazard drop contributes 0.4 to its own signal but is NOT the sole gate.
    Rationale: a grounded model can respond by dropping the hazard OR by re-routing
    recs/graph; gating on hazard alone would misclassify grounded re-routing, so we
    aggregate all five. MOVE_CUTOFF and the aggregation (mean vs max vs weighted) stay
    parameters the reflect pass may tune against the oracle, and that noise calibration
    can replace later without rework.
  - **#4 control candidate:** start = lowest-ranked real hazard GT does not mark core.
  - **No-GT / no-control:** no GT → `should_be_core` None → `adjudicate` returns
    `not_adjudicable`; < 2 hazards → `control` None → `compare_to_control` skipped.

## UI surface (thin, built after the pipeline is trustworthy)

Intervention tab shows: the **suppression candidates** (Step 1: A/B/GT cores +
which is should-be-core + the control), the **pre-intervention trust score**
(Layer 1 context that qualifies the shift), a **modality selector** (Language now;
Visual/Joint as future options), an intervention-type selector + target selector,
and "Apply Intervention" → shifts + matrix verdict. UI is NOT agentic; it renders
the pipeline output.

## Build order (meticulous)

1. This plan (done).
2. **Loop step 1:** generate `intervention.py` (steps 1-8) + unit tests (per-step
   invariants) + the 4 oracle cases. Run eval-for-code → must be fully green.
3. **Loop step 2:** run live on push_06 + a control; check U held / discrimination /
   rubric; reflect on code + output; refine #2-4 and any logic gaps; save the
   reflection artifact.
4. Then the thin UI + callback.

## Deferred (handle later, designed not to block)

- **VLM stochasticity / noise floor / null (placebo) control.** Parked by decision.
  Consequence: a "moved" verdict on a live scene is **provisional** (a small change
  could be sampling noise). Acceptable for the Stage-1 qualitative walkthrough. The
  move-threshold (#3) is kept as a parameter and a `null_shift` slot is left unused, so
  the null control + noise calibration drop in later without rework.
- **Cross-modal consistency** (6th shift signal) — waits for the visual `do()`.
- **Repeated sampling / noise spread** — later.

## Verification / dependencies

- Eval-for-code runs with no VLM (hermetic) — runnable in CI.
- The live run needs Ollama up with `qwen2.5vl:7b` (same as the batch).
- Every new function ships its unit tests in the same turn (standing rule). Any test
  touching GT uses a temp dir + monkeypatch (never the gitignored `exports/`).

## References

CLAUDE.md (Pearl framing + A/B declarations), memory `project-groundedness-matrix`
(the matrix + three cores), `project-pearl-framing`, `project-cee-priorities`
(consequence-shift weighting feeds the shift signals downstream).
