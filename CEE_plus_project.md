# CEE+ Intern Brief

**Project:** Causal Explanation Engine (CEE+)
**Lead:** Sunny Anjon, U.S. Army Research Laboratory
**Your scope:** the intervention step of Stage 1 (described in Tier 2 below)

This document is meant to stand alone. Read it once end-to-end. You should not need any other file to understand what we are doing and what your work is.

---

## Tier 0 — What CEE+ is, in five minutes

Modern Vision Language Models (VLMs) like Qwen2.5-VL, GPT-4V, LLaVA, and Claude can look at an image, read a caption, and produce confident structured output: detected objects, threats, recommendations, causal reasoning chains. In safety-critical settings (disaster response, intel fusion, military decision support) people are starting to act on those outputs.

The problem: the output **looks** grounded. The model writes "because the house is burning, evacuate the residents." That reads like causal reasoning. But the model has no internal verification that the causal chain it wrote is the chain that actually drove the recommendation. The reasoning is **declarative** (it sounds right) rather than **mechanistic** (it would shift if the underlying scene shifted).

CEE+ is a framework that **measures whether a VLM's recommendations are mechanistically grounded in the model's own causal reasoning, or only declarative**. The core test is intervention: we suppress a hazard in the scene (visually or in the caption) and watch whether the model's reasoning updates accordingly. If the recommendation doesn't change when the cited hazard is removed, the recommendation was not actually grounded in that hazard.

**Why fire disasters as a test domain.** Hazards are visually explicit (fires, floods, collapses), causal chains are tractable (fire spreads, water rises, structures collapse), and recommendation errors are life-critical. The mechanisms we study generalize to other safety-critical decision-support contexts.

**What CEE+ is not.** Not a benchmark or leaderboard. We are not ranking VLMs. We are inspecting whether their reasoning is grounded.

---

## Tier 1 — What is already built

You are joining a project that has working Stage 1 infrastructure, except for the intervention step itself (which is your project). Here is what runs today.

### The pipeline

Given a disaster image and a caption, the system produces a structured JSON response containing:

- **detected_objects** with stable IDs (`house_1`, `car_2`, `person_3`) and states (`burning`, `flooded`, `intact`)
- **threats** (entities whose state is hazard-bearing)
- **recommendations**, each carrying a causal quad `(threat, state, effect, affected_objects)`
- **causal_graph** (Graph A) derived from the recommendations
- An independent **graph_b** (Graph B) the model produces when asked separately for the causal structure
- **graph_consistency** comparing Graph A and Graph B
- **pre_internal_alignment** with about 30 rule-based contract checks
- **pre_intervention_trust** score (0 to 1, with Low / Moderate / High bands)
- **pathologies** detected per scene (described below)

### Three causal pictures

This is the key architectural idea you should understand.

- **Picture 1** comes from the recommendations themselves (what the model would act on)
- **Picture 2** comes from an independent prompt asking for the causal graph directly (what the model believes)
- **Picture 3** is the reference truth (a second AI drafts it, the human author validates)

These three pictures rarely match exactly. The gaps are informative.

### Headline metrics

- **A-fidelity**: do the recommendations match the model's own beliefs (Picture 1 vs Picture 2)?
- **B-coverage**: does the model act on what it believes (Picture 2 vs Picture 1)?
- **Internal alignment**: are the recommendations internally self-consistent (object IDs match across fields, every threat has a recommendation, etc.)?
- **Trust score**: a weighted combination, used to decide whether post-intervention shifts are even interpretable.

On the current 69-scene Qwen2.5-VL batch, A-fidelity median is 0.33 and B-coverage median is 0.11. The model is producing fluent surface reasoning over weak grounding. About half of scenes would route to human review under our trust bands.

### Pathology footprints

For each scene we detect five named output-level signatures consistent with known AI failure modes. Three of these are active in single-run analysis today:

- **Sycophancy**: model gives the asker the answer the question seems to want
- **Rationalized Minimization**: model hedges a real threat into ambiguity
- **Institutional Deference**: model softens findings on weighted entities (hospitals, schools, vulnerable people)

Two are reserved for Stage 2 because they need paired-prompt runs to detect:

- **Tribal Mirroring**: same scene, different audience framings, different briefs
- **Safety Theater**: refusal training is a surface filter that reframing bypasses

Each pathology has a hypothesis about the ML training mechanism that causes it (RLHF reward shape, prompt conditioning, safety tuning over-reach, etc.). These are strong hypotheses drawn from published interpretability literature, not direct proof.

### Code orientation

- `main.py` is the Dash web app and the analysis engine. About 10,000 lines. Big but organized by section.
- `run_pipeline.py` is a headless CLI that runs the full pipeline on a single image, no browser needed. Useful for batch experiments and remote use.
- `exports/runs/` holds prior run outputs, one folder per run, each containing the image, caption, prompt, and structured response JSON.
- `experiments/scene1/` through `scene6/` hold test images.

To run the system yourself:

```bash
# Install dependencies
pip install -r requirements.txt

# Start the local VLM (Qwen2.5-VL via Ollama)
brew install ollama
ollama serve
ollama pull qwen2.5vl:7b

# Configure
export QWEN_API_URL="http://localhost:11434/v1/chat/completions"
export QWEN_MODEL_NAME="qwen2.5vl:7b"

# Option A: web UI
python main.py
# open http://localhost:8050

# Option B: headless on one image
python run_pipeline.py --image experiments/scene1/2.jpg
```

The first run takes a couple of minutes (image encoding + two VLM calls). Output goes to `exports/runs/run_<timestamp>/`.

---

## Tier 2 — Your project: the intervention step

This is the work. Read carefully.

### What "intervention" means in CEE+

So far, everything described above is **pre-intervention**. We characterize the model's baseline output for a scene. We measure how internally coherent it is. We flag pathology footprints. None of this proves causal grounding. A model that always says the same plausible thing about every fire scene would look fine on A-fidelity, B-coverage, and internal alignment, but that doesn't mean it actually reasoned about the specific scene.

The intervention step is the actual causal test. The logic:

1. Take a baseline scene. The model produces its analysis.
2. **Suppress one hazard from the scene.** Remove it from the image (visually inpaint over it) or from the caption (redact the phrase) or both.
3. Run the model again on the modified scene. The model produces a new analysis.
4. Compare the new analysis to the original. Did it shift in the way we would expect if the model's reasoning was actually grounded in that hazard?

If the model claimed `house_1` was at risk because of `fire_1`, and we suppress `fire_1`, the recommendation about `house_1` should disappear or change. If it doesn't, the recommendation was not grounded in `fire_1`.

### Three modalities of suppression

You will build all three. Suggested order in the next subsection.

**Language suppression.** Edit the caption to remove the hazard phrase. If the caption is "A house is on fire next to a car," language-suppress fire by changing the caption to "A house is next to a car." The image is unchanged.

**Visual suppression.** Modify the image to remove the visual hazard. Inpaint over the fire region with what should plausibly be there instead (an intact house wall, sky). The caption is unchanged.

**Joint suppression.** Both at once. Tests whether the model is using cross-modal grounding or relying on a single modality.

Each modality probes a different failure mode. A model that updates correctly on language but not visual suppression is reading the caption and ignoring the image. A model that updates on both individually but disagrees on joint suppression has cross-modal coherence issues.

### The six Δ shift signals

After running the model on the suppressed scene, compute these six signals as differences between baseline and counterfactual:

1. **Hazard shift.** Did the model still flag the suppressed hazard as a threat? A grounded model should drop it.
2. **Causal graph shift.** How much did Graph A (recommendation-derived) change? Edges added, removed, rewired? A grounded model should drop edges whose `via_state` was the suppressed hazard state.
3. **Recommendation shift.** Did the actions change? Are recommendations that previously cited the suppressed hazard either dropped or rewritten?
4. **Structural alignment shift.** Does the post-intervention output still follow a valid causal chain (hazard → action via suppression variable)?
5. **Semantic alignment shift.** Are the new reasoning chains semantically coherent with the new recommendations?
6. **Cross-modal consistency shift.** When visual and language interventions are applied separately, do they produce consistent shifts? Disagreement here is a cross-modal grounding failure.

You will compute each as a numeric Δ plus a structured comparison (what specifically changed). The numeric Δ goes into the final CEE+ score; the structured comparison is what makes the result interpretable.

### Where this plugs in

The pipeline today stops at the pre-intervention pass. Your work adds a second pass:

```
existing:  image + caption -> Graph A, Graph B, alignment, trust, pathologies   (DONE)
your work: select hazard -> suppress -> rerun -> compute Δ signals -> CEE+ score
```

You can run the suppressed scene through the same `query_qwen` and `query_qwen_graph_b` functions that the pre-intervention pass already uses. The two heavy questions are: (a) which hazard to suppress, and (b) how to actually do the suppression.

For (a), the pipeline already produces a `framework_suppression_picks` field that ranks suppressible (threat, state) pairs. Start there. The framework's pick is the most causally central hazard in Graph A. You may also want to compare with `graph_b.suppression_pick` (the model's own pick). Disagreement between the two is itself a signal.

For (b), see "Open design decisions" below.

### Suggested ordering

I would lean strongly toward **language suppression first**, then visual, then joint. Reasons:

- Language suppression is text editing. You can mechanically remove the hazard phrase from the caption. Cleanest test, no model-of-a-model dependencies.
- Visual suppression requires an image inpainting model (Stable Diffusion inpainting, LaMa, or similar). That adds a second model to the system and brings artifacts that can confound your Δ signal. Worth doing, but do not start there.
- Joint suppression depends on both being clean.

A reasonable internal milestone schedule, assuming roughly 12 weeks:

- Weeks 1 to 2: read this document, run the pipeline, replicate the existing analysis on three or four scenes by yourself. Get comfortable with the JSON schema and the Dash UI.
- Weeks 3 to 5: language suppression end-to-end on a single scene. Include all six Δ signals. Surface the result in the UI under a new "Post-Intervention" card.
- Weeks 6 to 8: visual suppression on the same scene. Compare the two modalities. Document differences.
- Weeks 9 to 10: joint suppression. Run the full three-modality test on five or six scenes. Write up qualitative findings.
- Weeks 11 to 12: write a short report and integrate into the batch pipeline so we can run intervention across the whole 69-scene corpus.

You will probably renegotiate this schedule by week 4. That's fine. Tell Sunny when something is taking longer than expected.

### Open design decisions you should make

These are not decided. Bring options and a recommendation. We will discuss before you commit code.

1. **Visual inpainting model.** Stable Diffusion inpainting via diffusers is the obvious choice. LaMa is lighter and faster. Both have failure modes. Pick one based on inpainting quality on fire/flood scenes specifically, not on generic benchmarks.

2. **Inpainting mask granularity.** Bounding box of the threat, or pixel-level segmentation? Bounding box is easier; segmentation gives a cleaner suppression but requires a segmentation model in the pipeline.

3. **Caption-edit method.** Pattern match the hazard phrase and delete it, or rewrite the caption from scratch using a small text model? Pattern matching is brittle but transparent. Rewriting is more robust but adds another model.

4. **Δ-signal numerics.** Each signal needs a 0-to-1 number. How do you compute graph difference? Set difference on edges? Edit distance? Something more semantic? Pick something that has a clear interpretation, not just whatever metric is easiest to compute.

5. **Aggregate CEE+ score.** Weighted combination of the six signals into a single 0-to-1 score, plus a groundedness band (Low / Moderate / High) analogous to the trust score. The weighting is yours to propose.

6. **What to surface in the UI.** A new tab? A second column next to pre-intervention? A side-by-side diff view? Think about what an operator (an Army analyst reading the brief) would actually want to see.

For each of these, the deliverable is a short writeup (one to two pages) of the options, your recommendation, and the trade-offs.

### What success looks like

By the end of your project we should be able to:

- Pick any disaster scene from `experiments/`
- Run the full pre-intervention plus intervention pipeline in one command
- See six numeric Δ shift signals
- See a structured diff of what changed
- See a final CEE+ score with a groundedness band
- Run this in batch across many scenes and aggregate the results into the existing batch report

The bar is **not** that the score is perfectly calibrated. It is that the pipeline is honest, the Δ signals are interpretable, and the result tells us whether the model's reasoning was actually grounded in the suppressed hazard.

---

## Tier 3 — What your work enables

If we know that a VLM's reasoning is or is not grounded under intervention, we can start making honest claims about safety-critical use. Some examples of what becomes possible:

- **Per-scene flagging.** A live brief reaches an analyst. CEE+ has already run it through baseline plus intervention. If the brief looks coherent but its reasoning collapses under suppression, the brief is flagged "looks confident, not grounded — verify before acting."
- **Cross-model comparison.** Same scenes, four different VLMs (Qwen, LLaVA, GPT-4V, Claude). Which models are reasoning, which are pattern-matching? Stage 3.
- **Mechanism probing.** If Sycophancy footprints survive language suppression of the leading framing, the pathology is not just framing-driven. If they disappear, it was framing all along.

You will be co-authoring this. The intervention step is the largest single piece of unbuilt work in the project.

---

## Tier 4 — The horizon, for context

You do not need to act on any of this. It is here so you know where the work fits.

- **Stage 2 (in development).** Multi-suppression (more than one hazard at a time), mechanism-probing prompt suites, reframe-and-bypass tests for Safety Theater. Your intervention pipeline will be the foundation.
- **Stage 3 (planned for 2027).** Progressive counterfactual reasoning chains (action → consequence → new state → new decision) and comparative model studies. Multiple VLMs on the same scenes.
- **Stage 4 (potential, beyond 2027).** Mechanistic interpretability work on open-weight VLMs. Activation logging, probing classifiers, attention-head ablation. Possibly with external collaborators.

---

## Working style notes (read once)

The lead's preferences on how we work together:

- **Discuss direction before implementing.** When you are about to make a non-trivial design decision, propose options first. We can talk through trade-offs in 15 minutes. Saves days.
- **Plain language over jargon.** The audience for this work includes senior Army readers and other non-ML researchers. Cascades and explanations should be readable without an ML degree.
- **Honest framing.** We say "footprint consistent with X" not "the model is sycophantic." We say "strong hypothesis" not "proven cause." Overclaiming costs credibility.
- **Qualitative first, quantitative later.** Walk through one scene end-to-end before computing aggregate statistics across many. The single-scene narrative makes the quantitative result interpretable.
- **No em-dashes.** Use colons, semicolons, parentheses, or rephrase. This is a personal preference but consistent.
- **Distinguish non-negotiables from additive improvements.** When proposing changes, be explicit about which is which.

---

## Files and entry points

Everything you need to know about the codebase, in priority order:

- `INTERN_BRIEF.md` (this file). Start here. You are here.
- `main.py`. The full pipeline. Read top-down: the file is organized by section. Section comments tell you what each block does.
- `run_pipeline.py`. The headless CLI. Read this once to understand how the pipeline composes.
- `exports/runs/` has real run outputs. Open one of the `structured_response.json` files and read through. The JSON shape is the contract you will be working with.
- `requirements.txt` for dependencies.

You do not need to read every line of `main.py` before starting. Skim the section headers, then read the specific functions you will be calling: `query_qwen`, `query_qwen_graph_b`, `normalize_result`, `assess_pre_internal_alignment`, `assess_pre_intervention_trust`, `detect_pathologies`. Those are the public surface.

---

## What to do this week

1. Read this document end-to-end. Twice.
2. Set up the local environment (Ollama, conda, requirements).
3. Run the pipeline on three scenes from `experiments/scene1/`. Look at the JSON outputs and the Dash UI.
4. Read `main.py` between lines that handle the recommendations and the causal graph construction. Get a feel for the data shape.
5. Schedule a 30-minute conversation with Sunny to discuss the brief, ask questions, and align on the first internal milestone.

Welcome to CEE+.
