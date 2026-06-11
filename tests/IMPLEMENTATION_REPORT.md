# CEE+ Test Suite Implementation Report

## Summary

- **Total numbered test cases in spec:** 108 (sections A–M)
- **Implemented as executing pytest tests:** ~60 (across sections A, B, C, D, E, F3, G1–G3, I3, J1–J3)
- **Stubbed (`@pytest.mark.skip` with reason):** ~25 (F1, F2, F4–F7, G4, H1–H3, I1–I2, J4–J8, K1–K9, L1–L8, C12, C21)
- **M-series (test infrastructure):** documentation-only — the existence of this directory IS the implementation.

### First-run outcomes

> **NOTE:** I was unable to actually execute `pytest` inside this session — the
> sandbox blocked Python invocations (`python3 -c`, `python3 -m pytest`,
> `~/miniconda3/envs/clip_dash/bin/python -m pytest`) with a "permission
> denied" error even though `python3 --version` and `ls` worked. The test
> files were validated by close reading + cross-referencing against `main.py`
> symbols, but the outcomes below are PREDICTIONS, not observations. Sunny
> should run:
>
> ```bash
> source ~/miniconda3/etc/profile.d/conda.sh && conda activate clip_dash
> pip install pytest pytest-xdist
> cd /Users/sunny/Documents/CEE+
> pytest -c tests/pytest.ini tests/ -v --tb=short 2>&1 | tail -100
> ```
>
> ...and replace the predictions below with actual numbers.

Predicted outcomes (with confidence levels):

- **HIGH confidence PASS:** A1, A2, A3, A4, A5, A6, A7, A9, A10, A11, A12, A13, B1–B6,
  C1, C5, C9, C14, C16, C17, C19, C20, D1, D2, D3, D4, E1, E2, E3, E4, E5, E6, E7,
  E8, E9, F3, G1, G2, G3, I3, J1, J2, J3
- **EXPECTED FAIL (real spec/code drift, NOT a test bug — see below):**
  - **A8** — `STATE_SYNONYMS` contains `"collapsing": "collapsed"` and `collapsing`
    is ALSO a canonical hazard state (line 268 of main.py). The A8 test
    explicitly asserts no key in `STATE_SYNONYMS` is also a canonical state.
    This is a real WARN-level finding. The docstring on `test_a8` calls this
    out so a future reader sees the intent.
- **UNCERTAIN (depends on actual GT contents):** C2, C3, C4, C6, C7, C8, C10,
  C11, C13, C15, C18, E10. These pass/fail depending on whether the 70
  push_test GTs conform to the contract. If any FAIL, the failure indicates
  a stale GT or a real schema-drift bug — not a test bug.

## Per-section status

| Section | Implemented | Skipped | Notes |
|---|---|---|---|
| A | 13 / 13 | 0 | All schema-vocab tests run. A8 will likely fail (real WARN-level finding). |
| B | 6 / 6 | 0 | Substring-grep tests; spec calls these "partial". |
| C | 19 / 21 | 2 | C12 skipped (HUMAN-only); C21 skipped (schema_version not in main.py). C19/C20 parametrized over a 5-GT sample (not all 70) for runtime. |
| D | 4 / 4 | 0 | Class-priority and stylesheet-vs-legend hex checks. |
| E | 10 / 10 | 0 | Synthetic fixtures hand-built in conftest.py / test file. |
| F | 1 / 7 | 6 | F3 implemented; rest need live Qwen or trust-formula entry point. |
| G | 3 / 4 | 1 | G4 skipped (callback-ID walker too brittle without Dash dev mode). |
| H | 0 / 3 | 3 | H1 needs Dash test client; H2/H3 are HUMAN or skip. |
| I | 1 / 3 | 2 | I3 (memory index) auto; I1/I2 HUMAN. |
| J | 3 / 8 | 5 | J1–J3 structural validators; J4–J7 need Qwen fixtures; J8 HUMAN. |
| K | 0 / 9 | 9 | All need live Qwen + curated fixtures. Each skip names the fixture to capture. |
| L | 0 / 8 | 8 | Intervention pipeline not yet implemented in main.py. |
| M | n/a | n/a | Documentation-only; this directory IS the implementation. |

## Failing tests (real spec/code drift to flag for Sunny)

I did NOT execute, so I cannot give a final list, but here are predicted real
findings the test suite will surface — these are NOT bugs in the tests:

1. **A8 (WARN)** — `STATE_SYNONYMS` has `"collapsing": "collapsed"` while
   `collapsing` is itself a canonical hazard state. Either the synonym entry
   is a leftover from a migration (rule: synonyms should map non-canonical
   words to canonical), or `collapsing` was promoted to canonical without
   removing the legacy synonym mapping. Per the test's own docstring, this
   is reported, not silently allowed.
2. Possibly **C2, C3, C6, C7, C8, C13** on a few GT files — depends on the
   regen state of the 70 push_test files. Sunny mentioned a recent
   image-grounded regen pass; any leftover stale GT will surface here.

## Spec gaps discovered while implementing (NOT silently added)

Per the task constraints, I am reporting these here instead of modifying
TESTS.md. Sunny should decide what to do with each.

1. **C12 has no automatable form** — "distance rule semantics" requires image
   inspection. Spec correctly marks it HUMAN; just noting that the test exists
   as a `@pytest.mark.skip(...)` stub so it's visible in reports.
2. **C21 spec is correct but inactive** — the spec already notes "Currently a
   planned addition, not active." Stubbed accordingly.
3. **E3 — empty vs empty semantics** — TESTS.md says "yields a vacuous-perfect
   status, not 1.00. The current implementation does this correctly via a
   guard." In `compare_graphs`, the function itself DOES return 1.0 (vacuous
   default); the "guard" is in `make_consistency_panel` (the consumer), which
   inspects `has_data`. My E3 test asserts the diff-dicts-are-empty signal that
   the consumer uses — not that `compare_graphs` itself flags vacuous. This is
   a faithful interpretation but worth confirming with Sunny.
4. **E5/E10 partial** — the spec describes effect-pair collapsing as soft-tier
   behaviour. The main.py impl is consistent. E10 ("synonym diff preserves
   original form") in the spec implies the diff carries both raw and canonical
   forms ("GT used the more specific word"). The current `compare_graphs`
   `edge_diff` returns the raw edge dicts (preserving via_state strings), but
   does NOT attach a separate `canonical_via_state` field. My test asserts the
   weaker version (raw form preserved); the spec's stronger reading (BOTH
   forms recorded) is unmet.
5. **F4 trust score** — the spec asserts "Trust score = documented formula
   over (a_fidelity, b_coverage, internal_alignment, pathology penalties)."
   Could not locate a single canonical `trust_score()` entry point in main.py;
   the closest is `compute_pre_intervention_report` / `compute_ground_truth_report`,
   which appear to compute composite scores inline. Test skipped pending
   confirmation of the entry point.
6. **G4 callback-ID layout walker** — requires walking the Dash layout tree
   and cross-checking every Input/State/Output id. The TESTS.md status says
   "partial". I skipped with explicit reason; could be implemented with a
   recursive layout walker + collecting `id` attributes — ~50 lines of work.
7. **H1 save callback** — would benefit from a small Dash test client harness
   that imports `app.callback_map` and looks up the save handler by output
   ID. Skipped with that reason.
8. **K-series fixtures** — each test names the exact scene + expected output;
   capture protocol is in `tests/fixtures/README.md`. Each skip is one
   `pip install` and one Qwen run away from being unstubbed.
9. **L-series** — the intervention pipeline doesn't exist in main.py at all
   (`grep -n "suppression\|intervention" main.py` yields scattered text in
   prompts only). Stubbed wholesale with the single reason
   "pipeline not yet implemented". When the L code lands, these unstub
   one-for-one.

## Confirmed I did NOT touch

- `main.py` (read-only)
- Any file under `exports/ground_truth/` (read-only)
- `TESTS.md` (read-only; gaps reported above instead)
- Prompt strings, schema rules, cytoscape stylesheet (read-only)

## How to run

```bash
# Activate env + install deps (one-time)
source ~/miniconda3/etc/profile.d/conda.sh && conda activate clip_dash
pip install pytest pytest-xdist

# Run blocking gate
pytest -c tests/pytest.ini tests/ -m blocking -n auto --tb=short

# Run advisory set
pytest -c tests/pytest.ini tests/ -m warn -n auto --tb=short

# Everything not HUMAN
pytest -c tests/pytest.ini tests/ -m "not human" -v --tb=short

# Single test for debugging
pytest -c tests/pytest.ini tests/test_a_schema_consistency.py::test_a1_hazard_states_match_main_prompt -v
```

## Files produced

- `tests/pytest.ini` — marker definitions + collection settings
- `tests/conftest.py` — shared fixtures: main_module, main_source, main_prompt,
  graph_b_prompt, push_test_gt_paths, sample GTs
- `tests/test_a_schema_consistency.py` — A1–A13 (13 tests)
- `tests/test_b_prompt_consistency.py` — B1–B6 (6 tests)
- `tests/test_c_gt_conformance.py` — C1–C20 parametrized over 70 GTs + C21 skip
- `tests/test_d_cytoscape_rendering.py` — D1–D4 (5 tests after D2 split)
- `tests/test_e_comparison.py` — E1–E10 (10 tests)
- `tests/test_f_pipeline.py` — F3 active + F1/F2/F4–F7 skipped
- `tests/test_g_codebase.py` — G1–G3 + G4 skipped
- `tests/test_h_ui_workflow.py` — all skipped
- `tests/test_i_documentation.py` — I3 active + I1/I2 skipped
- `tests/test_j_layer2_recommendations.py` — J1–J3 active + J4–J8 skipped
- `tests/test_k_behavioral.py` — all skipped with fixture-capture instructions
- `tests/test_l_counterfactual.py` — all skipped pending pipeline
- `tests/fixtures/sample_gts/`, `tests/fixtures/sample_qwen_outputs/` — empty dirs ready to receive captures
- `tests/fixtures/README.md` — fixture conventions
- `tests/README.md` — how to run + what's runnable
- `.github/workflows/tests.yml` — CI template (blocking + warn jobs)
