# Test Fixtures

## `sample_gts/`

Hand-authored minimal GT JSON files used by the E-series synthetic comparison
tests (instead of the 70 push_test GTs which are already covered by C-series).

Two sample GTs are provided **inline as pytest fixtures** in `conftest.py`
(`sample_gt_minimal_burning_house`, `sample_gt_mutual_worsens`). Add a new GT
file here when a test case is too large to inline, or when it represents a
fundamental edge case (mutual hazard, engulfing, distance rule, etc.) worth
keeping as a standalone artefact.

## `sample_qwen_outputs/`

Captured Qwen pipeline outputs (one JSON per scene), used to validate J4–J7
and K-series without needing a live Qwen runtime in CI.

Capture protocol:

1. Run the pipeline on the target scene (e.g. `push_06_drowning_pool.jpg`).
2. Save the structured pipeline output as
   `tests/fixtures/sample_qwen_outputs/<scene_basename>.json`.
3. Unskip the corresponding test in `test_k_behavioral.py` /
   `test_j_layer2_recommendations.py`.
4. Tag the fixture with the prompt version it was produced under once C21
   (schema_version) lands; until then, note the date in a sibling `.meta.json`.

## `pathology_cases/` (planned)

Positive and negative examples per pathology detector (Sycophancy,
Rationalized Minimization, Truth Suppression, Tribal Mirroring,
Safety Theater). Used by K7. Not yet populated.

## `intervention_pairs/` (planned)

(baseline_graph, counterfactual_graph) pairs with known expected shift
signals. Used by L5. Not yet populated; depends on the intervention pipeline
landing in main.py first.
