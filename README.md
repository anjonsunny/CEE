# CEE+ — Causal Explanation Engine for VLMs

CEE+ tests whether a Vision Language Model's recommendations are mechanistically anchored to scene evidence or only declaratively coherent with it. It is a working evaluation framework for safety critical decision support, focused on fire disaster scenarios as a controlled proxy domain.

The core claim: a baseline VLM can produce coherent threat identification, recommendations, and structured reasoning, but that reasoning often remains *declarative* rather than *mechanistically verified*. CEE+ exposes the causal structure explicitly via intervention based transparency, and detects a recurring set of model honesty pathologies.

---

## What it does

For every scene, CEE+ builds three views of the model's reasoning and scores agreement across them.

| View | Source |
|---|---|
| 1. Recommendations | What the model would act on |
| 2. Stated beliefs | A separate causal graph prompt asking what the model believes |
| 3. Reference truth | A human validated ground truth scene |

Then it computes:

| Metric | Question it answers |
|---|---|
| **A fidelity** | Do recommendations match the model's stated beliefs? |
| **B coverage** | Do the model's beliefs surface in what it recommends? |
| **Internal alignment** | Is the brief self consistent on its own terms? |
| **Trust Score** | Combined operational score with Low / Moderate / High bands |

## Intervention based grounding

Causal grounding is verified by intervention. Suppress a hazard in the scene (visual inpainting, caption redaction, or both) and re-run the pipeline. Six shift signals measure what changed:

1. Hazard shift
2. Causal graph shift
3. Recommendation shift
4. Structural alignment shift
5. Semantic alignment shift
6. Cross modal consistency shift

If a recommendation does not change after the hazard it cited is removed, that recommendation was never anchored in the hazard. It was anchored in priors or in surface phrasing.

## Pathology framework

CEE+ detects five named model honesty pathologies. Each has a cross metric signature and an inferred ML mechanism cause.

| Pathology | What it does |
|---|---|
| Sycophancy | Gives the asker the answer they seem to want; does not push back on the framing. |
| Rationalized Minimization | Stacks defensible qualifiers until a real threat reads as ambiguous. |
| Truth Suppression for Peace | Softens findings that would create social or diplomatic friction. |
| Tribal Mirroring | Shades the same facts toward each audience's preferred framing. |
| Safety Theater | Refusal training as surface filter; reframed requests bypass it. |

The framework operates as a behavior level lie detector that requires no access to model internals.

## Schema innovations

- **Hazard as state grounding.** Hazards are encoded as states on entities (`fire_on_house_1`, not `burning_house`) so a specific mechanism can be suppressed.
- **Four part causal links.** Every causal claim is written as `(source, state, effect, target)` so the exact mechanism is suppressible.
- **Ground truth corpus.** 89 human validated reference scenes anchor the evaluation.

## Headline findings

69 scene Qwen2.5-VL batch (May 2026):

- A fidelity median: **0.33**
- B coverage median: **0.11**
- Internal alignment median: **0.87**
- 48 percent of scenes route to human review under the Trust Score

Briefs read coherent on top of broken reasoning. The model is producing unjustified confidence.

---

## Setup

```bash
brew install ollama
ollama serve
ollama pull qwen2.5vl:7b

conda activate clip_dash
pip install -r requirements.txt

export QWEN_API_URL="http://localhost:11434/v1/chat/completions"
export QWEN_MODEL_NAME="qwen2.5vl:7b"
python main.py
```

## Project layout

- `main.py` — Dash web app calling Qwen2.5-VL via Ollama
- `experiments/` — test scenes
- `GROUND_TRUTH_PROTOCOL.md` — schema rules and validation conventions
- `CEE_plus_discussion_notes.md` — failure taxonomy and worked examples

## Stage roadmap

- **Stage 1 (operational):** pre-intervention pipeline plus single suppression intervention with six shift signals
- **Stage 1 extension (next):** symptom to pathology to ML mechanism mapping in batch reports
- **Stage 2 (in development):** multi suppression comparative analysis, mechanism probing prompt suites
- **Stage 3 (planned 2027):** progressive counterfactual reasoning, comparative model studies

## Publication

Assessing the Causal Reliability of AI-Generated Emergency Explanations: An Intervention-Based Evaluation Framework. *HCI International* 2026 (forthcoming; Springer LNAI vol. 16744).

---

## Acknowledgment

Research was sponsored by the Army Research Laboratory and was accomplished under Cooperative Agreement Number W911NF-25-2-0116. The views and conclusions contained in this document are those of the authors and should not be interpreted as representing the official policies, either expressed or implied, of the Army Research Laboratory or the U.S. Government. The U.S. Government is authorized to reproduce and distribute reprints for Government purposes notwithstanding any copyright notation herein.
