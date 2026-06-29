# CEE+ —  Causal Explanation Engine

## Project Overview

CEE+ measures the **causal groundedness** of Vision-Language Models (VLMs) by testing whether the model identifies true causal factors, updates reasoning structure after intervention, and adapts recommendations accordingly.

The core contribution claim: a baseline VLM can produce coherent threat identification, recommendations, and structured reasoning, but that reasoning remains *declarative* rather than *mechanistically verified*. CEE+ exposes causal structure explicitly via intervention-based transparency for safety-critical decision support.

## Codebase

- `main.py` — Dash web app calling Qwen2.5-VL via Ollama (OpenAI-compatible endpoint), returns structured JSON with detected_objects, threats_and_risks, recommendations, structured_reasoning triples, expected_consequence, remaining_risk, and follow-up actions.
- `experiments/scene1..6` — test scenes (disaster images + captions)
- `exports/` — prior run outputs
- `idea.txt` — full project vision document (Stages 1–3, pipeline, signals, architecture)
- `CEE_plus_discussion_notes.md` — detailed discussion notes covering failure taxonomy, worked examples, and prompt revision plan
- `requirements.txt` — dash, requests, Pillow

## Local Setup

```bash
# Ollama for local VLM inference
brew install ollama
ollama serve
ollama pull qwen2.5vl:7b

# Python environment
conda activate clip_dash
pip install -r requirements.txt

# Run
export QWEN_API_URL="http://localhost:11434/v1/chat/completions"
export QWEN_MODEL_NAME="qwen2.5vl:7b"
python main.py
```

## CEE+ Pipeline (Stage 1 — Single Suppression)

1. **Baseline Analysis** — image + caption → detected entities, state grounding (e.g. `fire_on_house_1`), hazard score, recommendations, causal graph, suppression variable
2. **Single Suppression Intervention** — suppress a hazardous state node (visual, language, or joint)
3. **Post-Intervention Analysis** — recompute hazard score, recommendations, causal graph
4. **Compute Shift Signals** — hazard shift, causal graph shift, recommendation shift, structural alignment, semantic alignment, cross-modal consistency
5. **Aggregate Score + Explanation** — CEE+ score, groundedness level, signal-level explanation

## Six Core Signals

1. **Hazard Shift** — does perceived risk change after intervention?
2. **Causal Graph Shift** — does the model update its reasoning structure? (edge/node changes, suppression variable consistency)
3. **Recommendation Shift** — do suggested actions change? (added/removed/unchanged)
4. **Structural Alignment** — does reasoning follow a valid causal chain? (hazard → action via suppression variable)
5. **Semantic Alignment** — are reasoning and actions semantically consistent?
6. **Cross-Modal Consistency** — do visual and language interventions agree?

## Failure-Mode Taxonomy (Three Layers)

- **Layer 1 — Perception failures.** Missed objects, hallucinations, wrong state attribution. *Deprioritized for now.*
- **Layer 2 — Reasoning-coherence failures.** Cross-field inconsistencies visible from JSON alone. Focus area.
  - Pattern 1: Broken grounding links (ids don't match across fields)
  - Pattern 2: Reason / structured_reasoning drift (natural language says one thing, triple encodes another)
  - Pattern 3: Effect-label misuse (generic `threatens` when specific label applies)
  - Pattern 4: Suppression-variable ambiguity (*deferred to Layer 3*)
- **Layer 3 — Causal/counterfactual failures.** Intervention reveals reasoning isn't anchored to named hazards. Core CEE+ territory.

## Current Phase & Next Steps

**Current focus:** Layer 2 prompt revision + Layer 3 (core CEE+). Qualitative analysis first, quantitative later. Single-scene walkthroughs preferred.

**Immediate next step:** Revise `main.py` prompt focusing on three non-negotiables:
1. **Stable object_ids** — `label_N` form (`house_1`, `car_1`, `person_1`), used verbatim everywhere
2. **Hazard-as-state** — `fire_on_house_1` not `burning_house`, makes prompt CEE+-ready for suppression
3. **Reason/triple coverage** — every object_id in reason text must appear in `related_object_ids` and triple

**Second pass (deferred):** Effect-vocabulary tightening with truth conditions, terminal self-check block.

## Research Stages

CEE+ positions itself on **Pearl's Ladder of Causation**. Rung 1 = association (what modern VLMs do well — fluent, coherent, retrieval over high-probability templates). Rung 3 = counterfactual (unit-specific "what would have happened if?" — three-step: abduction → action → prediction). The core claim: VLM safety recommendations are coherent on rung 1 but ungrounded on rung 3, and the gap is invisible to standard evaluation because rung-1 output looks like rung-3 reasoning. CEE+ is the probe that surfaces the gap.

**The CEE+ pipeline is a counterfactual pipeline, not an intervention pipeline.** Conditioning on a specific scene = implicit abduction (VLM scene grounding fixes U); suppression = action (the do() step); measured shifts = unit-specific prediction. The "intervention type" (source-removal / edge-severance / target-mitigation) is the *shape* of the do() inside each counterfactual query.

**Graph A and Graph B are BOTH rung-1 declarations — neither is mechanistic.** A declarative artifact is anything the model emits (or a deterministic function of it): a static assertion, not a tested dependency. By that criterion Graph A, Graph B, the framework pick (a ranking of A), and `graph_b.suppression_pick` are ALL declarative. The honest distinction is *coupling to the action*, not declarative-vs-mechanistic: **Graph A = declaration coupled to the action** (derived from the recs); **Graph B = declaration decoupled from the action** (elicited independently, without the recs). Calling B "mechanistic" is wrong and self-undermining (it would grant rung-3 status to a static emitted graph, the exact masquerade we exist to expose). The ONLY mechanistic artifact in the pipeline is the **operative core**, which does not exist until the do(): mechanism = the recommendation moves when the hazard is suppressed. Pre-intervention A-vs-B is therefore a *consistency check between two declarations*, qualified by GT — it is fine and useful as that, but it is not a rung-3 signal.

### Two orthogonal axes

**Axis A — Suppression structure (depth of the counterfactual):**
- **Stage 1 (current paper):** Single suppression — one rule-based do() per scene. Establishes the rung-1 vs rung-3 measurement methodology and the six shift signals.
- **Stage 2 (next paper):** Multi suppression — multiple candidate do()s in the same scene, comparative analysis. Tests whether the model distinguishes competing hazards rather than collapsing them to a single dominant pattern.
- **Stage 3 (future):** Progressive suppression — chained nested counterfactuals (action → consequence → new state → new decision). The canonical rung-3 query form; catches rung-1 masquerade that survives flat queries but breaks on chained reasoning.

**Axis B — Probe generation (who picks the counterfactual):**
- **Rule-based** — schema enumerates candidates deterministically. Reproducible, audit-able. Used throughout Stages 1–3 above.
- **Adversarial LLM-generated** — separate model produces novel out-of-template counterfactuals. Addresses the concern that a sophisticated rung-1 model could pattern-match the rule-based query shape. Layered on top once the depth axis is established (Stage 4+).

### Alignment track (downstream, parallel)

The six shift signals are differentiable enough to serve as reward shaping or preference labels. Once Stage 2 or 3 signals are validated, a parallel track uses them to fine-tune VLMs toward causally honest behavior — not just measure the gap but close it. Methodological stance: CEE+ does not adjudicate whether the underlying mechanism is "real" causal reasoning or sophisticated mimicry; it claims only that a model passing CEE+ counterfactual consistency probes behaves indistinguishably from one that reasons causally on the query class, which is the standard a deployment context can audit. See memory files `project-pearl-framing` and `project-cee-alignment-ambition`.

### Recommended path

Stage 1 → Stage 2 (multi, rule-based) → Stage 3 (progressive, rule-based) → Stage 4 (adversarial layered on top). Alignment program spins off once Stage 2+ signals exist. Extending the depth axis before introducing the generator dependency keeps each stage methodologically defensible without adding a probe-quality confound.

## Working Style Preferences

- Sunny prefers collaborative research dialogue over being handed finished output — discuss direction before implementing
- Distinguishes non-negotiables from additive improvements
- Comfortable with design-tension discussion
- Qualitative/illustrative analysis first, quantitative later
- Single-scene walkthroughs for cleaner narrative

## Design Tensions to Keep in Mind

- **Prompting strength vs. evaluation validity:** A heavily engineered prompt raises "are we evaluating the VLM or the prompt?" — give the baseline its best shot so remaining failures are unambiguously the model's. State this methodologically in the paper.
- **Constraint vs. reasoning freedom:** Hazard-as-state and stable ids constrain format, not reasoning itself.



For full project state, read PROJECT_STATE.md
