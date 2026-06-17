# CEE+ One-Page Summary

**Project:** Causal Explanation Engine (CEE+) · **Lead:** Sunny Anjon, U.S. Army Research Laboratory
**Your role:** build the intervention step (described below). Full detail in `INTERN_BRIEF.md`.

## What CEE+ measures

Modern Vision Language Models (VLMs) produce confident structured output (threats, recommendations, causal reasoning) for safety-critical decisions. The output **looks** grounded but is often only declarative: it sounds right without being mechanistically tied to the scene. CEE+ measures whether a VLM's recommendations are actually grounded in its own causal reasoning, by intervening on the scene and watching whether the reasoning updates.

**Test domain:** fire-disaster scenes. **Model under test:** Qwen2.5-VL via local Ollama. **Not a benchmark:** we are not ranking VLMs, we are inspecting their reasoning.

## What is already built (Stage 1, pre-intervention)

Given a disaster image and caption, the pipeline produces a structured JSON with detected objects, threats, recommendations, two causal graphs (Graph A from recommendations, Graph B independently extracted), an internal alignment score with about 30 contract checks, a Trust score with Low / Moderate / High bands, and per-scene pathology footprints (Sycophancy, Rationalized Minimization, Truth Suppression; two more deferred to Stage 2). A batch report rolls these up across runs. Run it via `python main.py` (Dash UI) or `python run_pipeline.py --image PATH` (headless).

## Your project: the intervention step

This is the actual causal test. Take a baseline analysis, suppress one hazard, rerun the model, compare. If the recommendation doesn't change when the cited hazard is removed, the recommendation was not actually grounded in that hazard.

**Three modalities of suppression.** Build in this order:

1. **Language** — remove the hazard phrase from the caption (easiest, cleanest, start here)
2. **Visual** — inpaint over the hazard region in the image
3. **Joint** — both at once (tests cross-modal grounding)

**Six Δ shift signals to compute** between baseline and counterfactual:

1. Hazard shift (does the suppressed hazard disappear from the threat list?)
2. Causal graph shift (how does Graph A change?)
3. Recommendation shift (do the actions change?)
4. Structural alignment shift (is the new chain still valid?)
5. Semantic alignment shift (does the prose match the new structure?)
6. Cross-modal consistency shift (do visual and language interventions agree?)

These feed into an aggregate CEE+ score with a groundedness band.

**Open design decisions you own:** which inpainting model, mask granularity (bbox vs segmentation), caption-edit method, how to compute graph Δ numerically, how to weight the signals into the score, how to surface results in the UI. Bring options and a recommendation; we discuss before you commit code.

**Rough timeline (12 weeks):** weeks 1–2 read and replicate, 3–5 language suppression end to end, 6–8 visual, 9–10 joint, 11–12 batch integration and short writeup.

## Working style (read once)

- Discuss direction before implementing. Propose options, we talk for 15 minutes, you build.
- Plain language over jargon. The audience includes non-ML readers.
- Honest framing: "footprint consistent with X," not "the model is sycophantic." "Strong hypothesis," not "proven cause."
- Qualitative first, quantitative later. Walk through one scene before computing batch statistics.
- No em-dashes. Colons, semicolons, parentheses, or rephrase.

## First week

1. Read `INTERN_BRIEF.md` end to end (longer companion to this page).
2. Install Ollama, pull `qwen2.5vl:7b`, install requirements, start the local VLM.
3. Run `python run_pipeline.py --image experiments/scene1/2.jpg`. Look at the saved JSON.
4. Run `python main.py`, upload a scene through the UI, click through every panel.
5. Skim `main.py` and identify these five functions: `query_qwen`, `query_qwen_graph_b`, `normalize_result`, `assess_pre_internal_alignment`, `detect_pathologies`. These are the public surface you will be calling.
6. Schedule 30 minutes with Sunny to discuss the brief and align on the first milestone.
