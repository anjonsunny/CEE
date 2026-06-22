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


@pytest.mark.blocking
def test_s5_consequence_weighting(main_module):
    """T3 — internal is capped by the consequence-weighted penalty, so a
    high-consequence failure tanks it and cosmetic-only failures don't."""
    runs = _load()
    # push_06: a victim treated as a threat = Misrouted rescue (0.9) → out of high, hard drop.
    p06 = _recompute(main_module, runs["push_06"])
    assert p06["level"] != "high" and p06["score"] < 0.5, f"push_06 {p06['score']:.2f}"
    types = {f.get("type") for f in runs["push_06"]["pre_internal_alignment"].get("failures", [])}
    assert "at_risk_entity_used_as_threat" in types
    # push_14: only cosmetic alignment failures → consequence cap does NOT bite → stays high.
    assert _recompute(main_module, runs["push_14"])["level"] == "high"
    # push_09: no consequence-bearing alignment failures → moderate (unchanged).
    assert _recompute(main_module, runs["push_09"])["level"] == "moderate"


@pytest.mark.blocking
def test_s6_consequence_model_integrity(main_module):
    """Every mapped error resolves to a known impact; key orderings hold."""
    for err, cat in main_module.CONSEQUENCE_CATEGORY.items():
        assert cat in main_module.CONSEQUENCE_IMPACT, f"{err} -> {cat} not an impact category"
    for cat, imp in main_module.CONSEQUENCE_IMPACT.items():
        assert 0.0 <= imp <= 1.0
    # spot-check the victim-cost ordering
    assert main_module.consequence_score("at_risk_state_missing_from_at_risk_block") == 1.0  # missed rescue
    assert main_module.consequence_score("at_risk_entity_used_as_threat") == 0.9              # misrouted
    assert main_module.consequence_score("may_harm_hazardous_target") == 0.6                  # under-response
    assert main_module.consequence_score("normal_state_listed_as_at_risk") == 0.3            # wasted
    assert main_module.consequence_score("merge_rule_violation") == 0.0                       # no effect
    # unknown error defaults to no_effect
    assert main_module.consequence_score("not_a_real_error") == 0.0


@pytest.mark.blocking
def test_s7_consequence_verdict(main_module):
    """T9a — top-level verdict surfaces the WORST consequence, victim-first."""
    runs = _load()

    def verdict(scene):
        sr = runs[scene]
        return main_module.generate_consequence_verdict(
            sr.get("pre_internal_alignment", {}), sr.get("rule_conformance", {}))

    # push_06: a victim treated as a threat → Misrouted rescue, red.
    v06 = verdict("push_06")
    assert v06["worst_category"] == "misrouted_rescue"
    assert v06["pills"][0]["color"] == "red"
    assert "Misrouted rescue" in v06["takeaway"]
    # push_61: fabricated hazards on a safe scene → Wasted response (over-firing).
    assert verdict("push_61")["worst_category"] == "wasted_response"
    # push_14: only cosmetic failures → Slowed response (the omission is invisible here, → T5).
    assert verdict("push_14")["worst_category"] == "slowed_response"

    # Clean input → green "no victim-cost failures".
    clean = main_module.generate_consequence_verdict({"failures": []}, {"violations": []})
    assert clean["worst_category"] is None
    assert clean["pills"][0]["color"] == "green"

    # Color thresholds.
    assert main_module.consequence_color(1.0) == "red"
    assert main_module.consequence_color(0.6) == "orange"
    assert main_module.consequence_color(0.3) == "amber"
    assert main_module.consequence_color(0.1) == "grey"
