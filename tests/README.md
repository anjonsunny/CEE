# CEE+ Test Suite

Pytest implementation of the consistency contract described in `/TESTS.md`.

## Quick start

```bash
source ~/miniconda3/etc/profile.d/conda.sh && conda activate clip_dash
pip install pytest pytest-xdist
cd /Users/sunny/Documents/CEE+
pytest tests/ -v
```

Run with `-c tests/pytest.ini` if pytest doesn't discover the config:

```bash
pytest -c tests/pytest.ini tests/ -v
```

## What runs and when

Tests use three severity markers (every test gets exactly one):

| Marker | Meaning | CI behaviour |
|---|---|---|
| `blocking` | Must pass before merge | Gate |
| `warn` | Should pass | Non-blocking; commented on PR |
| `human` | Manual judgement required | Skipped automatically |

Run subsets:

```bash
pytest tests/ -m blocking           # gating set
pytest tests/ -m warn               # advisory set
pytest tests/ -m "not human"        # everything automatable
pytest tests/ -m "needs_qwen"       # currently all skipped
```

## What's currently runnable

- **A1–A13** — schema vocabulary consistency. Pure structural.
- **B1–B6** — prompt rule consistency. Substring greps (partial, by design).
- **C1–C20** — GT file conformance, parametrized over the 70 push_test GTs.
  - C12 (distance rule semantics) is HUMAN; skipped.
  - C21 (schema_version) is skipped — the field is a planned addition per TESTS.md.
- **D1–D4** — Cytoscape rendering. Hand-built minimal graphs.
- **E1–E10** — Comparison tier monotonicity, identity, synonym / effect / label collapsing.
- **F3** — Consistency score well-formedness. Rest of F-series needs live Qwen → skipped.
- **G1–G3** — Code-level: `ast.parse`, `import main`, callback registry. G4 skipped.
- **I3** — Memory index integrity.
- **J1–J3** — Recommendation block structural validators. J4–J7 need Qwen fixtures; J8 HUMAN.

## What's stubbed (skipped with reason)

- **F1, F2, F5, F6, F7, K1–K9** — need live Qwen output. Each skip message names
  the fixture file you'd capture under `tests/fixtures/sample_qwen_outputs/`.
- **H1–H3** — UI workflow; needs Dash test client setup or are HUMAN.
- **I1, I2** — HUMAN documentation review.
- **J4–J8** — Need captured Qwen fixtures or are HUMAN.
- **L1–L8** — Intervention pipeline doesn't exist in main.py yet (Stage 1 paper is baseline).

## Adding fixtures

See `fixtures/README.md` for the fixture conventions. Two locations:

- `fixtures/sample_gts/` — minimal hand-built GTs for E-series synthetic tests.
- `fixtures/sample_qwen_outputs/` — captured Qwen runs (one JSON per scene), used to
  unstub J4–J7 and K-series.

## Conventions

- Tests are **read-only** against `main.py` and against all files under
  `exports/ground_truth/`. They inspect; they never modify.
- Tests **do not modify** `TESTS.md`. If you find a spec gap while running,
  record it in `IMPLEMENTATION_REPORT.md` so Sunny can decide whether to add it.
- M-series ("test infrastructure") is documentation-only — the existence of
  this directory IS the M-series implementation.

## Running with CI

A template GitHub Actions workflow is at `/.github/workflows/tests.yml`. It
runs only the `blocking` marker set on every push/PR. If you don't actually
use GitHub Actions, treat the YAML as documentation of which commands gate
merges.

## Interpreting results

Per-test outcome format follows TESTS.md §"Test outcome format":

```
SCHEMA.A1: PASS
SCHEMA.A8: FAIL — collapsing is both a canonical and a synonym key
GT.C13: PASS (70/70 files)
```

Pytest's default output is close to this. Use `-v` for one line per test;
use `--tb=short` to see the first assertion line on each failure.

## Spec gaps discovered during implementation

See `IMPLEMENTATION_REPORT.md` for the full list.
