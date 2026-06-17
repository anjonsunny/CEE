"""Section R — Meaning Generator data contract.

The Q-series tests build dicts from ASSUMED field names, so they pass even
when a generator reads the wrong key (that is how the pathology/alignment/
consistency drift slipped through). These tests run the generators against
REAL captured run outputs and assert the result is CONSISTENT with the raw
data, using expectations derived by reading the JSON, not by trusting the
generator's own field access.

As Sunny shares more run outputs, drop each structured_response.json into
tests/fixtures/run_outputs/ and add a fixture+expectations block here. More
real shapes = more drift caught.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from conftest import main_module  # noqa: E402, F401

RUN_DIR = Path(__file__).resolve().parent / "fixtures" / "run_outputs"
RUNS = sorted(RUN_DIR.glob("*.json"))


def _sr(path: Path) -> dict:
    d = json.loads(path.read_text())
    return d.get("structured_response", d)


def _pill_colors(meaning) -> list:
    return [p.get("color") for p in (meaning or {}).get("pills", [])]


# A generator must never return the grey "couldn't read it" pill when the
# corresponding raw data is actually present. This single invariant catches
# field-name drift across every section and every run.
@pytest.mark.blocking
@pytest.mark.parametrize("run", RUNS, ids=[p.stem for p in RUNS])
def test_r1_no_grey_when_data_present(run, main_module):
    sr = _sr(run)
    problems = []

    # Pathology: if active_keys present, pills must reflect them (not "No bias").
    path = sr.get("pathologies") or {}
    active = path.get("active_keys") or [k for k, v in (path.get("details") or {}).items()
                                         if isinstance(v, dict) and v.get("fired")]
    pm = main_module.generate_pathology_meaning(path)
    if active:
        labels = " ".join(p["label"] for p in pm["pills"]).lower()
        if "no bias" in labels or all(p["color"] == "green" for p in pm["pills"]):
            problems.append(f"pathology: {len(active)} fired but header reads clean")

    # Alignment: if failed_checks > 0, must not read self-consistent/green.
    al = sr.get("pre_internal_alignment") or {}
    if int(al.get("failed_checks", 0) or 0) > 0:
        am = main_module.generate_alignment_meaning(al)
        if all(p["color"] == "green" for p in am["pills"]):
            problems.append(f"alignment: {al.get('failed_checks')} failed checks but header reads consistent")

    # Consistency: if a topological score exists, must not read n/a/grey.
    gc = sr.get("graph_consistency") or {}
    if "topological_consistency" in gc:
        cm = main_module.generate_consistency_meaning(gc)
        if "grey" in _pill_colors(cm):
            problems.append("consistency: score present but header reads n/a")

    # Accuracy: if gt_validation available with a topo score, must not read No-GT/grey.
    gt = sr.get("gt_validation") or {}
    if gt.get("available") and "b_correctness_topo" in gt:
        accm = main_module.generate_accuracy_meaning(gt, sr.get("rule_conformance") or {})
        if "grey" in _pill_colors(accm):
            problems.append("accuracy: GT present with score but header reads No-GT")

    assert not problems, f"{run.name}: {problems}"


# Spot-check the known run: push_02 had Sycophancy + Rationalized Minimization,
# 7 failed alignment checks, topo consistency 0.0, accuracy ~0.17.
@pytest.mark.blocking
def test_r2_push02_known_expectations(main_module):
    f = RUN_DIR / "push_02_run_20260617T162103.json"
    if not f.exists():
        pytest.skip("push_02 reference run not present")
    sr = _sr(f)
    pm = main_module.generate_pathology_meaning(sr["pathologies"])
    labels = {p["label"] for p in pm["pills"]}
    assert {"Sycophancy", "Rationalized Minimization"} <= labels
    assert all(p["color"] == "red" for p in pm["pills"])

    am = main_module.generate_alignment_meaning(sr["pre_internal_alignment"])
    assert "self-incoherent" in am["takeaway"].lower()
    assert "7" in am["pills"][0]["label"]

    cm = main_module.generate_consistency_meaning(sr["graph_consistency"])
    assert cm["pills"][0]["color"] == "red"  # topo 0.0

    accm = main_module.generate_accuracy_meaning(sr["gt_validation"], sr["rule_conformance"])
    assert accm["pills"][0]["color"] == "red"  # 0.167
    assert "n/a" not in accm["pills"][0]["label"].lower() and "no gt" not in accm["pills"][0]["label"].lower()
