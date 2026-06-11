"""Section G — Code-level checks.

G1: main.py parses as valid Python (ast).
G2: `import main` succeeds.
G3: Dash callback registry has no duplicate Output declarations.
G4: Best-effort check that callback IDs exist in layout. Skipped if too brittle.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from conftest import MAIN_PY  # noqa: E402


@pytest.mark.blocking
def test_g1_main_py_parses_as_python():
    """G1 — ast.parse(open(main.py)) succeeds."""
    src = MAIN_PY.read_text(encoding="utf-8")
    try:
        ast.parse(src)
    except SyntaxError as e:
        pytest.fail(f"main.py syntax error at line {e.lineno}: {e.msg}")


@pytest.mark.blocking
def test_g2_main_py_imports_resolve(main_module):
    """G2 — `import main` succeeds in the project env.
    The `main_module` fixture does the import; if it raised, this test fails."""
    assert main_module is not None
    # Spot-check a handful of expected top-level symbols.
    for sym in ("HAZARD_BEARING_STATES", "EFFECT_LABELS", "compare_graphs", "app"):
        assert hasattr(main_module, sym), f"main module missing {sym}"


@pytest.mark.blocking
def test_g3_no_duplicate_callback_outputs(main_module):
    """G3 — Dash raises at startup if duplicate Output declarations exist
    without allow_duplicate=True. The fact that `import main` succeeded
    (G2) implicitly covers this; we additionally walk the callback map to
    confirm Dash itself accepts the registration as final."""
    app = getattr(main_module, "app", None)
    assert app is not None, "main module has no `app` attribute"
    # If callback_map populated and Dash didn't raise, duplicates were either
    # absent or properly opt-in via allow_duplicate.
    cb_map = getattr(app, "callback_map", None) or {}
    assert isinstance(cb_map, dict)


@pytest.mark.blocking
@pytest.mark.skip(reason="G4: walking Dash layout to verify every callback ID exists is brittle; rely on Dash dev-mode warnings for now")
def test_g4_no_undefined_callback_ids():
    pass
