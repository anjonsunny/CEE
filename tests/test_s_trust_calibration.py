"""Section S — Stage-1 trust-calibration acceptance.

Validated against the 9 captured shakedown runs (real model output, not
fabricated dicts), so each calibration change is proven to move the trust
verdict the RIGHT way on the scene that motivated it.

Phase 1 = T1 (Graph A conformance scales the Internal term, floored at 0.5) +
T4 (coverage excluded + folded into Internal on near-empty graphs).
"""
from __future__ import annotations

import glob
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from conftest import main_module  # noqa: E402, F401

FIXDIR = Path(__file__).resolve().parent / "fixtures" / "run_outputs"


def _scene_of(p: str) -> str:
    return Path(p).name.split("shakedown_")[1].split("_run")[0]


def _load() -> dict:
    out = {}
    for f in glob.glob(str(FIXDIR / "shakedown_*.json")):
        out[_scene_of(f)] = json.load(open(f))["structured_response"]
    return out


def _recompute(main_module, sr):
    return main_module.assess_pre_intervention_trust(
        sr.get("pre_internal_alignment", {}),
        sr.get("graph_consistency", {}),
        sr.get("causal_graph", {}),
        sr.get("graph_b", {}),
        threats=sr.get("threats", []),
        gt_validation=sr.get("gt_validation", {}),
    )


@pytest.mark.blocking
def test_s1_shakedown_fixtures_present(main_module):
    scenes = set(_load())
    for s in ("push_02", "push_06", "push_09", "push_14", "push_37",
              "push_41", "push_45", "push_55", "push_61"):
        assert s in scenes, f"missing shakedown fixture {s}"


@pytest.mark.blocking
def test_s2_calibration_only_tightens(main_module):
    """T1+T4 must never RAISE trust vs the captured (pre-calibration) score."""
    for scene, sr in _load().items():
        old = float(sr.get("pre_intervention_trust", {}).get("score", 0.0) or 0.0)
        new = _recompute(main_module, sr)["score"]
        assert new <= old + 1e-9, f"{scene}: trust ROSE {old:.2f} -> {new:.2f}"


@pytest.mark.blocking
def test_s3_a_conformance_validity_floored(main_module):
    """T1 penalty is floored at 0.5 — a fully-broken A never zeroes Internal."""
    for scene, sr in _load().items():
        v = _recompute(main_module, sr)["components"]["a_conformance_validity"]
        assert 0.5 - 1e-9 <= v <= 1.0 + 1e-9, f"{scene}: a_validity {v} out of [0.5,1]"


@pytest.mark.blocking
def test_s4_phase1_targets(main_module):
    runs = _load()
    # push_06: A's recommendation graph is structurally broken (self-loop) → out of "high".
    p06 = _recompute(main_module, runs["push_06"])
    assert p06["level"] != "high" and p06["score"] < 0.85, f"push_06 {p06['score']:.2f}/{p06['level']}"
    # push_09: a good scene with only an effect-label slip → stays moderate (not over-penalized).
    p09 = _recompute(main_module, runs["push_09"])
    assert p09["level"] == "moderate", f"push_09 {p09['level']}"
    # push_14: clean structure, omission failure → A is rule-clean so the spine leaves it
    # (its false-high is addressed later by T5, not Phase 1).
    p14 = _recompute(main_module, runs["push_14"])
    assert p14["components"]["a_conformance_validity"] == 1.0
    # push_61: fabricated hazards on a safe scene → already drops to "low" under T1/T4.
    p61 = _recompute(main_module, runs["push_61"])
    assert p61["level"] == "low", f"push_61 {p61['level']}"
