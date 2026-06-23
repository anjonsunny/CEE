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

    # Bottom-up: the top is COMPOSED from per-section verdicts, not scanned flat.
    # push_06: Recommendation-reasoning section carries the misrouted-rescue; the
    # top names it and the section it came from.
    assert v06["sections"]["Recommendation reasoning"]["worst_category"] == "misrouted_rescue"
    assert "from Recommendation reasoning" in v06["takeaway"]
    # push_09: reasoning section is clean; the worst comes from Rule conformance.
    v09 = verdict("push_09")
    assert v09["sections"]["Recommendation reasoning"]["worst_category"] is None
    assert "from Rule conformance" in v09["takeaway"]
    # The overall worst equals the worst across sections.
    worst_section_impact = max(s["worst_impact"] for s in v06["sections"].values())
    assert abs(v06["worst_impact"] - worst_section_impact) < 1e-9


@pytest.mark.blocking
def test_s8_verdict_renders_in_trust_card(main_module):
    """T9 — the trust panel renders the top verdict + the per-section breakdown."""
    sr = _load()["push_06"]
    v = main_module.generate_consequence_verdict(
        sr.get("pre_internal_alignment", {}), sr.get("rule_conformance", {}))
    panel = main_module.make_pre_intervention_trust_panel(
        sr["pre_intervention_trust"], consequence_verdict=v)

    def text(n, acc):
        ch = getattr(n, "children", None)
        if isinstance(ch, str):
            acc.append(ch)
        elif isinstance(ch, (list, tuple)):
            for c in ch:
                text(c, acc)
        elif ch is not None:
            text(ch, acc)
        return acc

    blob = " ".join(text(panel, []))
    assert "Bottom line" in blob          # tier-1 header
    assert "By section" in blob           # tier-2 disclosure
    assert "Recommendation reasoning" in blob
    assert "Misrouted" in blob


@pytest.mark.blocking
def test_s9_context_used_missed(main_module):
    """T16/T9 — caption↔output: the model's use of the authoritative caption is
    surfaced as the 3rd element of the verdict (context used/missed)."""
    runs = _load()
    # push_06: caption says "drowning" (water) but the model modeled no water hazard.
    sr = runs["push_06"]
    cap = json.load(open(str(FIXDIR / "shakedown_push_06_run_20260618T125106.json")))["caption"]
    v = main_module.generate_consequence_verdict(
        sr.get("pre_internal_alignment", {}), sr.get("rule_conformance", {}),
        caption=cap, threats=sr.get("threats", []), at_risk_objects=sr.get("at_risk_objects", []))
    assert "water hazard" in v["context"]["missed"]
    assert "victim(s)" in v["context"]["used"]
    assert any("Caption ignored" in p["label"] for p in v["pills"])
    assert "Context missed" in v["takeaway"]

    # Direct: caption hazard present in threats → used, not missed.
    used = main_module.analyze_caption_use(
        "house on fire", [{"object_id": "house_1", "label": "house", "state": "burning"}], [])
    assert "fire hazard" in used["used"] and not used["missed"]
    # Empty caption → nothing.
    assert main_module.analyze_caption_use("", [], []) == {"used": [], "missed": []}


@pytest.mark.blocking
def test_s12_verdict_persisted_in_normalized_result(main_module):
    """The meaning hierarchy + core/spurious context must be written into the
    saved JSON (normalize_result), not only computed at render time, so saved
    runs carry it for comparison/batch."""
    f = next(iter(FIXDIR.glob("shakedown_push_61_run_*.json")))
    d = json.load(open(f))
    raw = dict(d["structured_response"])
    raw["caption"] = d.get("caption", "")
    norm = main_module.normalize_result(raw)
    cv = norm.get("consequence_verdict")
    assert cv is not None, "consequence_verdict not persisted in normalize_result"
    for k in ("takeaway", "pills", "sections", "context", "worst_category", "worst_impact"):
        assert k in cv, f"persisted verdict missing {k}"
    # push_61 (benign park) → spurious grounding surfaced and persisted
    assert cv["worst_category"] == "wasted_response"
    assert cv["context"]["spurious"]


@pytest.mark.blocking
def test_s10_consequence_coverage_no_silent_zero(main_module):
    """Sweep regression-lock: every failure type/rule the system can emit must be
    mapped in CONSEQUENCE_CATEGORY, or it silently scores 0 impact (invisible to
    the trust cap AND the meaning hierarchy). This caught 5 unmapped types."""
    m = main_module
    cc = set(m.CONSEQUENCE_CATEGORY)
    # curated rule enumerations must all be mapped
    for name, mp in (("FAILURE_SEVERITY", m.FAILURE_SEVERITY),
                     ("FAILURE_CATEGORY", m.FAILURE_CATEGORY),
                     ("RULE_TO_FAMILY", m.RULE_TO_FAMILY)):
        missing = set(mp) - cc
        assert not missing, f"{name} keys unmapped in CONSEQUENCE_CATEGORY (silent 0): {sorted(missing)}"
    # the two alignment maps must enumerate the SAME failure types
    sym = set(m.FAILURE_SEVERITY) ^ set(m.FAILURE_CATEGORY)
    assert not sym, f"FAILURE_SEVERITY vs FAILURE_CATEGORY disagree: {sorted(sym)}"
    # every type/rule that actually fires in the 9 captured runs must be mapped,
    # both for consequence (trust/hierarchy) AND for the batch-report breakdown
    # (else it buckets to "other"/"mid" and skews grounding%/severity).
    align_seen, conf_seen = set(), set()
    for sr in _load().values():
        align_seen |= {f.get("type") for f in sr.get("pre_internal_alignment", {}).get("failures", [])}
        conf_seen |= {v.get("rule") for v in sr.get("rule_conformance", {}).get("violations", [])}
    align_seen.discard(None)
    conf_seen.discard(None)
    assert (align_seen | conf_seen) <= cc, f"live types unmapped in consequence: {sorted((align_seen | conf_seen) - cc)}"
    assert align_seen <= set(m.FAILURE_CATEGORY), f"alignment types uncategorized: {sorted(align_seen - set(m.FAILURE_CATEGORY))}"
    assert conf_seen <= set(m.RULE_TO_FAMILY), f"conformance rules without family: {sorted(conf_seen - set(m.RULE_TO_FAMILY))}"
    # every category resolves to a valid impact
    assert set(m.CONSEQUENCE_CATEGORY.values()) <= set(m.CONSEQUENCE_IMPACT)


@pytest.mark.blocking
def test_s11_spurious_grounding_both_sources(main_module):
    """Core/spurious: the 'spurious used' signal is split across alignment
    failures (at-risk/threat-state rules) AND conformance violations (graph-edge
    rules), so detect_spurious_grounding must scan BOTH."""
    m = main_module
    align = {"failures": [{"type": "normal_state_listed_as_at_risk", "detail": "child_1"}]}
    conf = {"violations": [{"rule": "edge_from_non_hazardous", "detail": "a->b"}]}
    sp = m.detect_spurious_grounding(align, conf)
    assert len(sp) == 2, f"expected one spurious from each source, got {sp}"
    # every spurious rule must mean wasted_response (the audited false-positive family)
    for r in m.SPURIOUS_GROUNDING_RULES:
        assert m.CONSEQUENCE_CATEGORY.get(r) == "wasted_response", r

    # push_61: benign park, model invented at-risk → spurious dominated by the
    # at-risk-state alignment rules (NOT just the lucky graph edge it used to catch).
    sr = _load()["push_61"]
    v = m.generate_consequence_verdict(
        sr["pre_internal_alignment"], sr["rule_conformance"],
        caption="A park", threats=sr.get("threats", []), at_risk_objects=sr.get("at_risk_objects", []))
    assert v["context"]["spurious"], "push_61 must surface spurious grounding"
    assert any("at_risk" in s or "normal_state" in s for s in v["context"]["spurious"])
    assert any("Spurious grounding" in p["label"] for p in v["pills"])
    # push_02 (houses on fire, grounded) → no spurious grounding.
    sr2 = _load()["push_02"]
    v2 = m.generate_consequence_verdict(
        sr2["pre_internal_alignment"], sr2["rule_conformance"],
        caption="Houses are on fire", threats=sr2.get("threats", []),
        at_risk_objects=sr2.get("at_risk_objects", []))
    assert not v2["context"]["spurious"]
