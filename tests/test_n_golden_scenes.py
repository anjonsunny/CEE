"""Section N — Golden scenes (frozen regression anchors).

Frozen, human-verified copies of canonical rule-exemplar scenes live under
tests/fixtures/golden_scenes/ (see CATALOG.md there). These tests make frozen
goldens tamper-evident: any change to a frozen GT fails N2 until deliberately
re-frozen via freeze_golden.py --force.

While the manifest is empty (no scenes frozen yet), N2/N3 skip.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from conftest import main_module  # noqa: E402, F401  (fixture)

GOLDEN_DIR = Path(__file__).resolve().parent / "fixtures" / "golden_scenes"
MANIFEST_PATH = GOLDEN_DIR / "MANIFEST.json"
CATALOG_PATH = GOLDEN_DIR / "CATALOG.md"


def _manifest() -> dict:
    if not MANIFEST_PATH.exists():
        return {}
    return json.loads(MANIFEST_PATH.read_text())


def _manifest_items() -> list[tuple[str, dict]]:
    return sorted(_manifest().items())


# ---------------------------------------------------------------------------
# N1 — Catalog / manifest coherence.
# ---------------------------------------------------------------------------
@pytest.mark.blocking
def test_n1_catalog_manifest_coherence():
    assert CATALOG_PATH.exists(), "CATALOG.md missing from golden_scenes/"
    assert MANIFEST_PATH.exists(), "MANIFEST.json missing from golden_scenes/"
    catalog_text = CATALOG_PATH.read_text(encoding="utf-8")
    problems: list[str] = []
    for key, entry in _manifest_items():
        scene_stem = key.split(".")[0]  # push_NN_name
        if scene_stem not in catalog_text:
            problems.append(f"manifest entry {key} not listed in CATALOG.md")
        if not (GOLDEN_DIR / key).exists():
            problems.append(f"frozen GT file missing on disk: {key}")
        image = entry.get("image", "")
        if image and not (GOLDEN_DIR / image).exists():
            problems.append(f"frozen image missing on disk: {image}")
    assert not problems, problems


# ---------------------------------------------------------------------------
# N2 — Frozen GT hash integrity.
# ---------------------------------------------------------------------------
@pytest.mark.blocking
@pytest.mark.parametrize(
    "key,entry",
    _manifest_items() or [pytest.param(None, None, marks=pytest.mark.skip(
        reason="N2: no golden scenes frozen yet — freeze verified scenes with freeze_golden.py"))],
)
def test_n2_frozen_gt_hash_integrity(key, entry):
    path = GOLDEN_DIR / key
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    assert actual == entry["gt_sha256"], (
        f"{key}: frozen golden GT has changed (sha256 mismatch). If this "
        f"change is deliberate, re-verify the scene in the UI and re-freeze "
        f"with freeze_golden.py --force."
    )


# ---------------------------------------------------------------------------
# N3 — Frozen goldens pass core schema invariants.
# ---------------------------------------------------------------------------
@pytest.mark.blocking
@pytest.mark.parametrize(
    "key,entry",
    _manifest_items() or [pytest.param(None, None, marks=pytest.mark.skip(
        reason="N3: no golden scenes frozen yet"))],
)
def test_n3_frozen_goldens_pass_core_invariants(key, entry, main_module):
    gt = json.loads((GOLDEN_DIR / key).read_text(encoding="utf-8"))
    nodes = {str(n.get("id", "")): n for n in gt.get("nodes") or []}
    edges = gt.get("edges") or []
    allowed_states = (
        main_module.HAZARD_BEARING_STATES
        | main_module.AT_RISK_STATES
        | main_module.NORMAL_STATES
        | set(main_module.STATE_SYNONYMS.keys())
        | {"undetermined"}
    )
    problems: list[str] = []
    for nid, n in nodes.items():
        st = str(n.get("state", "")).strip().lower()
        if st and st not in allowed_states:
            problems.append(f"node {nid}: non-vocab state {st}")
    touched: set[str] = set()
    for e in edges:
        src, tgt = str(e.get("source", "")), str(e.get("target", ""))
        eff = str(e.get("effect", "")).strip()
        via = main_module.canonicalize_state(str(e.get("via_state", "")).strip())
        touched.update((src, tgt))
        if eff not in main_module.EFFECT_LABELS:
            problems.append(f"edge {src}->{tgt}: bad effect {eff}")
        if src not in nodes or tgt not in nodes:
            problems.append(f"edge {src}->{tgt}: unresolved endpoint")
            continue
        src_state = main_module.canonicalize_state(str(nodes[src].get("state", "")).strip())
        if via != src_state:
            problems.append(f"edge {src}->{tgt}: via_state {via} != source state {src_state}")
        if via and via not in main_module.HAZARD_BEARING_STATES:
            problems.append(f"edge {src}->{tgt}: via_state {via} not hazard-bearing")
    for nid, n in nodes.items():
        if n.get("hazardous") and nid not in touched:
            problems.append(f"hazardous node {nid} has zero edges")
    assert not problems, f"{key}: {problems}"


# ---------------------------------------------------------------------------
# N4 — Behavioral fixtures reference golden hashes. Placeholder.
# ---------------------------------------------------------------------------
@pytest.mark.warn
@pytest.mark.skip(reason="N4: K-series behavioral fixture capture has not started; once Qwen outputs are captured against goldens, assert each fixture records the golden's sha256")
def test_n4_behavioral_fixtures_reference_golden_hashes():
    pass
