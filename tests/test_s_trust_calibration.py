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
    assert "help aimed the wrong way" in v06["takeaway"]
    # push_61: fabricated hazards on a safe scene → Wasted response (over-firing).
    assert verdict("push_61")["worst_category"] == "wasted_response"
    # push_14: its failures are now bookkeeping (no real impact) or uninterpretable
    # ("unknown impact", out_of_vocabulary_state), so there is NO victim-cost
    # consequence; the unknown garble is flagged, not scored.
    v14 = verdict("push_14")
    assert v14["worst_category"] is None
    # the uninterpretable garble is flagged as unknown-impact in its section
    assert any(p["color"] == "unknown"
               for p in v14["sections"]["Recommendation reasoning"]["pills"])

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
    assert "help aimed the wrong way" in blob   # relatable consequence label


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
def test_s13_failures_by_consequence_saved(main_module):
    """Priority #1: every failure is tagged with its consequence + impact and the
    trust-cap math is exposed, all saved in the JSON (not re-derived on demand)."""
    f = next(iter(FIXDIR.glob("shakedown_push_06_run_*.json")))
    d = json.load(open(f))
    raw = dict(d["structured_response"])
    raw["caption"] = d.get("caption", "")
    norm = main_module.normalize_result(raw)

    # per-failure consequence breakdown in the verdict
    b = norm["consequence_verdict"]["breakdown"]
    assert set(b) == {"failures", "by_category", "total_impact"}
    assert b["failures"], "no tagged failures"
    for item in b["failures"]:
        assert set(item) == {"type", "source", "consequence", "impact"}
        assert item["consequence"] in main_module.CONSEQUENCE_IMPACT
        assert item["impact"] == main_module.consequence_score(item["type"])
    # push_06 carries the misrouted-rescue tag for the victim-as-threat failure
    assert any(i["type"] == "at_risk_entity_used_as_threat" and i["consequence"] == "misrouted_rescue"
               for i in b["failures"])
    assert abs(b["total_impact"] - sum(i["impact"] for i in b["failures"])) < 1e-9

    # trust-cap math exposed in components
    comp = norm["pre_intervention_trust"]["components"]
    for k in ("internal_passratio", "align_consequence_sum", "internal_consequence"):
        assert k in comp, f"trust components missing {k}"


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

    # the four section meaning headers must be persisted too (whole meaning layer)
    sm = norm.get("section_meanings")
    assert sm is not None and set(sm) == {"reasoning", "conformance", "pathology", "accuracy"}
    for name, meaning in sm.items():
        assert "takeaway" in meaning and "pills" in meaning, f"{name} header malformed"

    # the A↔B consistency meaning (verdict + errors + matches) must be persisted
    ab = norm.get("ab_consistency_meaning")
    assert ab is not None and set(ab) >= {"verdict", "errors", "matches"}
    assert "takeaway" in ab["verdict"]


@pytest.mark.blocking
def test_s15_alignment_panel_consequence_first(main_module):
    """The Internal Alignment section surfaces the 3 priorities: a per-section
    consequence verdict (#2), each failure tagged by victim consequence (#1), and
    a spurious flag on spurious-grounding failures (#3)."""
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

    # push_02: section trust sentence + relatable consequence labels + failure phrases
    al02 = _load()["push_02"]["pre_internal_alignment"]
    blob02 = " ".join(text(main_module.make_pre_internal_alignment_panel(al02), []))
    assert "What this section means for trust" in blob02         # #2 section verdict header
    assert "trust this section's output" in blob02 or "trustworthy" in blob02  # trust sentence
    assert any(lbl in blob02 for lbl in ("danger under-treated", "effort on a non-threat"))  # #1
    assert any(ph in blob02 for ph in ("broken hazard link", "targets nothing real", "undetected victim"))  # failure phrase

    # core/spurious is NOT shown per-error in this section (it's scene-level)
    assert "spurious" not in blob02

    # the reasoning section header surfaces the subsection higher-level meaning
    # (labeled trust sentence + pills), replacing the old self-incoherent line
    hdr = " ".join(text(main_module.make_reasoning_section_meaning(al02), []))
    assert "Internal alignment" in hdr
    assert "checks pass" in hdr                              # trust sentence
    assert any(lbl in hdr for lbl in ("danger under-treated", "effort on a non-threat"))
    assert "self-incoherent" not in hdr.lower()             # old framing gone


@pytest.mark.blocking
def test_s17_meaning_cards(main_module):
    """Meaning hierarchies render as cards (count + weight, colored by consequence),
    using meaning-card-* classes distinct from the neutral gb-trust cards."""
    m = main_module

    def classes(n, acc):
        cn = getattr(n, "className", None)
        if cn:
            acc.append(cn)
        ch = getattr(n, "children", None)
        if isinstance(ch, (list, tuple)):
            for c in ch:
                classes(c, acc)
        elif ch is not None and not isinstance(ch, str):
            classes(ch, acc)
        return acc

    def text(n, acc):
        if isinstance(n, str):
            acc.append(n)
            return acc
        ch = getattr(n, "children", None)
        if isinstance(ch, str):
            acc.append(ch)
        elif isinstance(ch, (list, tuple)):
            for c in ch:
                text(c, acc)
        elif ch is not None:
            text(ch, acc)
        return acc

    sv = m.consequence_verdict_for(["invalid_graph_edge", "at_risk_missing_detected_object",
                                    "duplicate_recommendation_quad"])
    cards = m.render_meaning_cards({**sv, "takeaway": "summary line here"})  # returns a list
    cls, parts = [], []
    for el in cards:
        classes(el, cls)
        text(el, parts)
    blob = " ".join(parts)
    assert any("meaning-card-row" in c for c in cls)
    assert any(c.startswith("meaning-card meaning-card-") for c in cls)  # colored cards
    assert not any("gb-trust" in c for c in cls)                        # NOT the Graph B class
    assert "×1" in blob                                                  # count shown
    assert "0.6" in blob                                                 # weight shown
    assert "summary line here" in blob                                   # summary line


@pytest.mark.blocking
def test_s26_computation_correctness(main_module):
    """CORRECTNESS (not just invariants): each core computation produces the
    hand-verified output for a known input. compare_graphs diff, conformance-rule
    firing, the consequence cap, and the trust formula end-to-end."""
    m = main_module

    # --- A↔B diff: known A vs B ---
    A = {"nodes": [{"id": "h1", "hazardous": True, "state": "burning"}, {"id": "p1"}],
         "edges": [{"source": "h1", "via_state": "burning", "effect": "may_harm", "target": "p1"}]}
    B = {"nodes": [{"id": "h1", "hazardous": True, "state": "burning"}, {"id": "c1"},
                   {"id": "h2", "hazardous": True, "state": "burning"}],
         "edges": [{"source": "h1", "via_state": "burning", "effect": "may_harm", "target": "c1"},
                   {"source": "h1", "via_state": "burning", "effect": "may_spread_to", "target": "h2"}]}
    gc = m.compare_graphs(A, B)
    assert len(gc["edge_diff"]["only_in_a"]) == 1 and len(gc["edge_diff"]["only_in_b"]) == 2
    assert len(gc["edge_diff"]["in_both"]) == 0
    assert gc["a_fidelity"] == 0.0 and gc["b_coverage"] == 0.0       # 0/1, 0/2
    assert sorted(gc["node_diff"]["only_in_b"]) == ["c1", "h2"]

    # --- conformance rules: clean graph = 0 violations; known violations fire ---
    clean = {"nodes": [{"id": "h1", "hazardous": True, "state": "burning"},
                       {"id": "h2", "hazardous": True, "state": "burning"},
                       {"id": "p1", "at_risk": True, "state": "injured", "label": "person"},
                       {"id": "p2", "at_risk": True, "state": "injured", "label": "person"}],
             "edges": [{"source": "h1", "via_state": "burning", "effect": "may_harm", "target": "p1"},
                       {"source": "h2", "via_state": "burning", "effect": "may_harm", "target": "p2"}],
             "threat_reasoning_coverage": 1.0}
    assert m.check_graph_rule_conformance(clean, "graph_a") == []
    bad = {"nodes": [{"id": "h1", "hazardous": True, "state": "burning"},
                     {"id": "x1", "hazardous": False, "state": "intact"}],
           "edges": [{"source": "x1", "via_state": "intact", "effect": "may_harm", "target": "h1"}]}
    bad_rules = {v["rule"] for v in m.check_graph_rule_conformance(bad, "graph_a")}
    assert "hazardous_node_no_edges" in bad_rules        # h1 declared hazard, no outgoing edge
    assert "edge_from_non_hazardous" in bad_rules        # edge from x1 (not hazardous)

    # --- consequence cap (T3): internal = min(passratio, 1 - min(0.9, Σ/2)) ---
    sigma = m.consequence_score("at_risk_entity_used_as_threat") + m.consequence_score("invalid_graph_edge")
    assert abs(sigma - 1.5) < 1e-9
    assert abs((1 - min(0.9, sigma / 2.0)) - 0.25) < 1e-9

    # --- trust FORMULA end-to-end: clean scene => 1.0, one misroute => 0.82 ---
    cons = {"a_fidelity": 1.0, "b_coverage": 1.0, "structural_consistency": 1.0,
            "topological_consistency": 1.0, "node_consistency": 1.0, "flag_consistency": 1.0,
            "effect_disagreements": [], "a_fidelity_soft": 1.0, "b_coverage_soft": 1.0,
            "effect_label_gap_a": 0.0, "effect_label_gap_b": 0.0}
    thr = [{"object_id": "h1"}, {"object_id": "h2"}]
    t = m.assess_pre_intervention_trust({"score": 1.0, "failures": [], "passed_checks": 10, "failed_checks": 0},
                                        cons, clean, clean, threats=thr, gt_validation=None)
    assert t["components"]["a_conformance_validity"] == 1.0 and t["components"]["b_validity_beta"] == 1.0
    assert abs(t["score"] - 1.0) < 1e-6                  # 0.4*1 + 0.2 + 0.2 + 0.2
    t2 = m.assess_pre_intervention_trust(
        {"score": 1.0, "failures": [{"type": "at_risk_entity_used_as_threat"}], "passed_checks": 9, "failed_checks": 1},
        cons, clean, clean, threats=thr, gt_validation=None)
    assert abs(t2["components"]["internal_alignment"] - 0.55) < 1e-6   # capped by Σ=0.9
    assert abs(t2["score"] - 0.82) < 1e-6                # 0.4*0.55 + 0.6

    # --- detect_pathologies firing thresholds ---
    fired = m.detect_pathologies({"a_fidelity": 0.1, "b_coverage": 0.05}, [], {"nodes": [], "edges": []},
                                 {"level": "low"}).get("active_keys") or []
    assert "sycophancy" in fired and "rationalized_minimization" in fired
    assert not (m.detect_pathologies({"a_fidelity": 0.9, "b_coverage": 0.9}, [], {"nodes": [], "edges": []},
                                     {"level": "high"}).get("active_keys") or [])


@pytest.mark.blocking
def test_s27_batch_aggregation_correctness(main_module):
    """CORRECTNESS of batch aggregation: every rollup count/rate equals an
    independent recompute from the per-run data (no drift between single + batch)."""
    m = main_module
    runs = []
    for sr in _load().values():
        r = m.normalize_result(dict(sr))
        r["disaster_scenario"] = "Yes"
        runs.append(r)
    rep = m.compute_pre_intervention_report(runs)

    # batch rule conformance == per-run violation sum; family + by_rule reconcile
    brc = rep["batch_rule_conformance"]
    ind_total = sum(len(r.get("rule_conformance", {}).get("violations", [])) for r in runs)
    assert brc["total_violations"] == ind_total
    assert sum(e["violations"] for e in rep["family_rollup"]["families"]) == brc["total_violations"]
    assert sum(v["violations"] for v in brc["by_rule"].values()) == brc["total_violations"]

    # pathology counts == independent
    pr = {e["key"]: e["fired"] for e in rep["pathology_rollup"]["summary"]}
    for k in ("sycophancy", "rationalized_minimization"):
        ind = sum(1 for r in runs if k in (r.get("pathologies", {}).get("active_keys") or []))
        assert pr.get(k, 0) == ind

    # worst-consequence distribution == independent per-run worst
    from collections import Counter
    ind_worst = Counter(m.compute_trust_synthesis(r)["worst_category"]
                        for r in runs if m.compute_trust_synthesis(r)["worst_category"])
    assert rep["consequence_rollup"]["worst_distribution"] == \
        dict(sorted(ind_worst.items(), key=lambda kv: -m.CONSEQUENCE_IMPACT.get(kv[0], 0)))


@pytest.mark.blocking
def test_s25_single_batch_consistency(main_module):
    """Sweep regression-lock: single↔batch parity + batch rollup invariants.
    The batch report and the single-run card share compute_trust_synthesis, so
    per-run synthesis must match; rollup rates/sums must be coherent; the batch
    worker must persist caption like analyze_scene."""
    import inspect
    m = main_module
    runs = []
    for sr in _load().values():
        r = m.normalize_result(dict(sr))
        r["disaster_scenario"] = "Yes"
        runs.append(r)
    rep = m.compute_pre_intervention_report(runs)
    cr = rep["consequence_rollup"]

    # rollup invariants
    assert len(cr["per_run"]) == len(runs)
    for k in ("core_missed_rate", "spurious_rate", "gt_corroborated_rate"):
        assert 0.0 <= cr[k] <= 1.0, f"{k} out of range"
    n_with = sum(1 for p in cr["per_run"] if p["worst_category"])
    assert sum(cr["worst_distribution"].values()) == n_with
    assert sum(cr["convergence_distribution"].values()) == n_with

    # single↔batch: the batch per-run row IS compute_trust_synthesis (shared with
    # the single-run card via make_top_trust_synthesis)
    for run, row in zip(runs, cr["per_run"]):
        s = m.compute_trust_synthesis(run)
        assert s["worst_category"] == row["worst_category"]
        assert s["n_convergence"] == row["n_convergence"]
        assert bool(s["gt_corroborates"]) == bool(row["gt_corroborates"])

    # ML layer coverage: every scorable consequence + every pathology mapped
    victim = {c for c, i in m.CONSEQUENCE_IMPACT.items() if i > 0 and c != "unknown"}
    assert victim <= set(m.CONSEQUENCE_ML_HYPOTHESIS)
    assert set(m.PATHOLOGY_REGISTRY) <= set(m.PATHOLOGY_MITIGATION)

    # parity: the batch worker persists caption inside the run (analyze_scene does)
    assert 'result["caption"]' in inspect.getsource(m._process_one_image)


@pytest.mark.blocking
def test_s24_batch_groundedness_card(main_module):
    """The batch top card: groundedness profile + standout + ML hypotheses and
    candidate mitigations (incl. the alignment-track lever)."""
    m = main_module

    def text(n, acc):
        if isinstance(n, str):
            acc.append(n)
            return acc
        ch = getattr(n, "children", None)
        if isinstance(ch, str):
            acc.append(ch)
        elif isinstance(ch, (list, tuple)):
            for c in ch:
                text(c, acc)
        elif ch is not None:
            text(ch, acc)
        return acc

    runs = []
    for sr in _load().values():
        r = dict(sr)
        r["disaster_scenario"] = "Yes"
        runs.append(r)
    rep = m.compute_pre_intervention_report(runs)
    blob = " ".join(text(m.make_batch_groundedness_card(rep), []))
    assert "How grounded is the model?" in blob
    assert "danger under-treated" in blob                 # standout consequence
    assert "Top drivers:" in blob
    assert "Likely ML cause:" in blob and "Candidate fix:" in blob   # ML hypothesis + mitigation
    assert "shift signals as reward" in blob              # the alignment-track lever
    # every consequence category + pathology has an ML hypothesis/mitigation entry
    for cat in m.CONSEQUENCE_ML_HYPOTHESIS.values():
        assert cat["hypothesis"] and cat["mitigation"]
    for k in m.PATHOLOGY_REGISTRY:
        assert k in m.PATHOLOGY_MITIGATION


@pytest.mark.blocking
def test_s23_batch_consequence_rollup(main_module):
    """Batch report aggregates the single-run synthesis: worst-consequence
    distribution, convergence distribution, GT-corroboration rate, top drivers."""
    m = main_module
    runs = []
    for sr in _load().values():
        r = dict(sr)
        r["disaster_scenario"] = "Yes"
        runs.append(r)
    rep = m.compute_pre_intervention_report(runs)
    cr = rep.get("consequence_rollup")
    assert cr is not None, "batch report missing consequence_rollup"
    assert set(cr) >= {"worst_distribution", "core_missed_rate", "spurious_rate",
                       "gt_corroborated_rate", "convergence_distribution", "top_drivers", "per_run"}
    # the shakedown set is dominated by under-treated danger
    assert cr["worst_distribution"].get("under_response", 0) >= 5
    # convergence distribution includes full 4-of-4 corroboration on some scenes
    assert cr["convergence_distribution"].get(4, 0) >= 1
    # GT corroboration is a 0..1 rate; top drivers ranked by count
    assert 0.0 <= cr["gt_corroborated_rate"] <= 1.0
    assert cr["top_drivers"] and cr["top_drivers"][0][1] >= cr["top_drivers"][-1][1]
    assert len(cr["per_run"]) == len(runs)


@pytest.mark.blocking
def test_s22_top_trust_synthesis(main_module):
    """Top card synthesis: worst-wins headline, convergence by count (incl. GT
    flag), pathology surfaced separately, trust-level treatment."""
    m = main_module

    def text(n, acc):
        if isinstance(n, str):
            acc.append(n)
            return acc
        ch = getattr(n, "children", None)
        if isinstance(ch, str):
            acc.append(ch)
        elif isinstance(ch, (list, tuple)):
            for c in ch:
                text(c, acc)
        elif ch is not None:
            text(ch, acc)
        return acc

    f = next(iter(FIXDIR.glob("shakedown_push_09_run_*.json")))
    raw = dict(json.load(open(f))["structured_response"])
    raw["caption"] = "A tanker is leaking oil and might explode because of the fire nearby"
    norm = main_module.normalize_result(raw)
    blob = " ".join(text(m.make_top_trust_synthesis(norm), []))
    # per-section chips
    assert "A↔B consistency:" in blob and "Accuracy (Test 1):" in blob
    # convergence count + worst-wins + GT flag
    assert "independent checks" in blob and "converge on" in blob
    assert "danger under-treated" in blob
    # trust treatment from the level
    assert "Baseline trust is" in blob

    # synthetic: pathology surfaced separately, not in the convergence count
    norm2 = dict(norm)
    norm2["pathologies"] = {"active_keys": ["rationalized_minimization"],
                            "headline_cascade_key": "rationalized_minimization",
                            "details": {"rationalized_minimization": {"fired": True, "signature": "x"}}}
    blob2 = " ".join(text(m.make_top_trust_synthesis(norm2), []))
    assert "It also shows Rationalized Minimization" in blob2


@pytest.mark.blocking
def test_s21_accuracy_vs_gt(main_module):
    """Accuracy / Test 1: reuse the diff machinery, NEW consequences vs GT (truth).
    missed → under-treated, fabricated → non-threat (confirmed, NOT unknown);
    matched → correct (green)."""
    m = main_module
    gv = {"available": True, "b_correctness": 0.5, "b_precision": 0.6,
          "b_edge_diff": {
              "missed": [  # 3 missed edges, but only TWO distinct hazards (car_1, house_1)
                  {"source": "car_1", "target": "smoke_1", "effect": "increases_risk_to", "via_state": "burning"},
                  {"source": "car_1", "target": "house_2", "effect": "worsens", "via_state": "burning"},
                  {"source": "house_1", "target": "house_2", "effect": "worsens", "via_state": "burning"}],  # wrong-effect pair
              "spurious": [
                  {"source": "tanker_1", "target": "person_1", "effect": "may_harm", "via_state": "leaking"},
                  {"source": "house_1", "target": "house_2", "effect": "may_spread_to", "via_state": "burning"}],  # wrong-effect pair
              "matched": [{"source": "fire_1", "target": "house_1", "effect": "may_harm", "via_state": "burning"}],
          }}
    acc = m.enumerate_gt_accuracy(gv)
    types = [e["type"] for e in acc["errors"]]
    # house_1→house_2 in both missed and spurious → ONE wrong-effect, not missed+fabricated
    assert types.count("gt_wrong_effect") == 1
    assert m.consequence_score("gt_wrong_effect") == 0.1
    # the two car_1 missed edges collapse to ONE missed danger (dedup by hazard)
    assert types.count("gt_missed_danger") == 1
    missed = next(e for e in acc["errors"] if e["type"] == "gt_missed_danger")
    assert missed["hazard"] == "car_1" and "2 link(s)" in missed["detail"]
    # tanker_1 fabrication survives as its own hazard
    assert types.count("gt_fabricated_hazard") == 1
    # GT is truth → confirmed consequences, NOT unknown
    assert m.consequence_score("gt_missed_danger") == 0.6          # under-treated
    assert m.consequence_score("gt_fabricated_hazard") == 0.3      # non-threat
    assert not m.is_unknown_impact("gt_fabricated_hazard")         # confirmed, not unknown
    assert any(x["kind"] == "gt_correct" for x in acc["matches"])

    meaning = m.make_accuracy_meaning(gv)
    assert meaning["verdict"]["worst_category"] == "under_response"
    assert "missed" in meaning["verdict"]["takeaway"] and "fabricated" in meaning["verdict"]["takeaway"]
    # no verified GT → graceful
    assert m.make_accuracy_meaning({"available": False})["verdict"]["worst_category"] is None


@pytest.mark.blocking
def test_s20_pathology_observation_format(main_module):
    """Pathology section uses its own observation format (not victim-cost): each
    pathology has a possible_impact + affected_entity; the top card surfaces
    pathology + impact + affected entity + ML causal driver."""
    m = main_module

    def text(n, acc):
        if isinstance(n, str):
            acc.append(n)
            return acc
        ch = getattr(n, "children", None)
        if isinstance(ch, str):
            acc.append(ch)
        elif isinstance(ch, (list, tuple)):
            for c in ch:
                text(c, acc)
        elif ch is not None:
            text(ch, acc)
        return acc

    # every registered pathology has the two observation fields
    for k in m.PATHOLOGY_REGISTRY:
        assert k in m.PATHOLOGY_CONSEQUENCE, f"{k} missing observation consequence"
        assert m.PATHOLOGY_CONSEQUENCE[k]["possible_impact"]
        assert m.PATHOLOGY_CONSEQUENCE[k]["affected_entity"]

    path = {"active_keys": ["rationalized_minimization"],
            "headline_cascade_key": "rationalized_minimization",
            "details": {"rationalized_minimization": {"fired": True, "signature": "B-coverage 0.05 (< 0.2)"}}}
    top = " ".join(text(m.make_pathology_section_meaning(path), []))
    assert "Rationalized Minimization fired" in top
    assert "under-responded to" in top          # possible impact
    assert "affects" in top                       # affected entity
    assert "Likely cause:" in top                 # ML causal driver

    panel = " ".join(text(m.make_pathology_panel(path), []))
    for label in ("Why it surfaced", "Possible impact", "Affected entity", "Possible ML cause"):
        assert label in panel, f"pathology card missing '{label}'"

    # clean state
    clean = " ".join(text(m.make_pathology_section_meaning({"active_keys": []}), []))
    assert "No bias patterns fired" in clean


@pytest.mark.blocking
def test_s19_conformance_panel_and_driver(main_module):
    """Rule Conformance is consequence-first (verdict card + violation→consequence
    rows), and the top-level explanation names the dominant driver + total cost."""
    m = main_module

    def text(n, acc):
        if isinstance(n, str):
            acc.append(n)
            return acc
        ch = getattr(n, "children", None)
        if isinstance(ch, str):
            acc.append(ch)
        elif isinstance(ch, (list, tuple)):
            for c in ch:
                text(c, acc)
        elif ch is not None:
            text(ch, acc)
        return acc

    rc = {"violations": [
        {"rule": "hazardous_node_no_edges", "graph": "graph_b", "detail": "house_1 has no edges"},
        {"rule": "hazardous_node_no_edges", "graph": "graph_b", "detail": "house_2 has no edges"},
        {"rule": "hazardous_node_no_edges", "graph": "graph_b", "detail": "house_3 has no edges"},
        {"rule": "edge_from_non_hazardous", "graph": "graph_b", "detail": "car_1 -> x"},
        {"rule": "via_state_mismatch", "graph": "graph_a", "detail": "weird via"},
    ]}
    # dominant driver = the most common type within the worst consequence
    meaning = m.make_conformance_meaning(rc)
    sv = meaning["verdict"]
    assert sv["worst_category"] == "under_response"
    assert sv["driver_phrase"] == "idle hazard (no effects)" and sv["driver_count"] == 3
    assert "driven mostly by 'idle hazard (no effects)' (3×)" in sv["takeaway"]
    assert "total victim cost" in sv["takeaway"]

    blob = " ".join(text(m.make_rule_conformance_panel(rc), []))
    assert "What this section means for trust" in blob          # verdict card
    assert "Each violation and what it costs" in blob           # rows
    assert "idle hazard (no effects)" in blob                   # failure phrase surfaced
    assert "unknown impact" in blob                             # via_state_mismatch → unknown
    assert "failure famil" not in blob                          # old family framing gone


@pytest.mark.blocking
def test_s18_ab_consistency_consequences(main_module):
    """A↔B consistency: asymmetric mapping (B-side miss → under-treated, A-side
    unconfirmed → unknown), effect-disagreement dedupe, and grounded matches."""
    m = main_module
    gc = {
        "edge_diff": {
            "only_in_a": [{"source": "house_1", "via_state": "burning", "effect": "may_harm", "target": "person_1"},
                          # this pair is also an effect disagreement → must dedupe to NOT count here
                          {"source": "house_2", "via_state": "burning", "effect": "may_harm", "target": "car_1"}],
            "only_in_b": [{"source": "house_1", "via_state": "burning", "effect": "may_harm", "target": "car_1"},
                          {"source": "house_2", "via_state": "burning", "effect": "may_spread_to", "target": "car_1"}],
            "in_both": [{"source": "house_1", "via_state": "burning", "effect": "may_harm", "target": "house_2"}],
        },
        "effect_disagreements": [{"source": "house_2", "target": "car_1",
                                  "graph_a_effects": ["may_harm"], "graph_b_effects": ["may_spread_to"]}],
        "flag_agreement": [{"id": "house_1", "graph_a": True, "graph_b": True, "agree": True},
                           {"id": "car_1", "graph_a": False, "graph_b": True, "agree": False}],
    }
    ab = m.enumerate_ab_consistency(gc)
    types = [e["type"] for e in ab["errors"]]
    # house_2→car_1 appears as effect-disputed ONCE, not as only_in_a AND only_in_b
    assert types.count("ab_effect_disputed") == 1
    assert "ab_edge_unconfirmed" in types          # only_in_a house_1→person_1 (B genuinely lacks)
    assert "ab_edge_unaddressed" in types          # only_in_b house_1→car_1
    assert "ab_flag_unaddressed" in types          # car_1: B hazard, A not
    # consequences
    assert m.consequence_score("ab_edge_unaddressed") == 0.6   # under-treated
    assert m.is_unknown_impact("ab_edge_unconfirmed")          # unknown
    assert m.is_unknown_impact("ab_effect_disputed")
    # matches: grounded edge + agreed hazard
    assert any(x["kind"] == "grounded_edge" for x in ab["matches"])
    assert any(x["kind"] == "agreed_hazard" for x in ab["matches"])
    # subsection meaning + verdict
    meaning = m.make_ab_section_meaning(gc)
    assert meaning["verdict"]["worst_category"] == "under_response"
    assert "agree" in meaning["verdict"]["takeaway"]


@pytest.mark.blocking
def test_s16_consequence_phrases_and_unknown_class(main_module):
    """The relatable consequence phrases, the brief failure phrases, and the new
    'unknown impact' class (uninterpretable garble: flagged, not a victim cost)."""
    m = main_module
    # relatable consequence labels
    assert m.CONSEQUENCE_LABEL["under_response"] == "danger under-treated"
    assert m.CONSEQUENCE_LABEL["wasted_response"] == "effort on a non-threat"
    assert m.CONSEQUENCE_LABEL["unknown"] == "unknown impact"
    # failure phrase + consequence phrase helpers
    assert m.failure_phrase("invalid_graph_edge") == "broken hazard link"
    assert m.consequence_phrase("invalid_graph_edge") == "danger under-treated"
    assert m.failure_phrase("never_seen_type") == "never seen type"  # fallback

    # reclassification: uninterpretable garble → unknown (0.0, flagged, not scored)
    for t in ("invalid_effect_label", "via_state_mismatch", "out_of_vocabulary_state",
              "self_loop_not_worsens"):
        assert m.is_unknown_impact(t), t
        assert m.consequence_score(t) == 0.0          # no victim cost asserted
    # understood-redundancy → no real impact (NOT unknown)
    for t in ("redundant_instancing", "node_budget_exceeded"):
        assert m.CONSEQUENCE_CATEGORY[t] == "no_effect"
        assert not m.is_unknown_impact(t)
    # responder-facing clutter stays slowed
    assert m.CONSEQUENCE_CATEGORY["duplicate_recommendation_quad"] == "slowed_response"

    # unknown is flagged in a section verdict but never the "worst"
    sv = m.consequence_verdict_for(["invalid_effect_label", "via_state_mismatch"])
    assert sv["worst_category"] is None
    assert any(p["color"] == "unknown" for p in sv["pills"])

    # section trust sentence scales with the worst consequence + names the driver
    s_hi = m.section_trust_sentence(10, 20, {"worst_category": "misrouted_rescue", "worst_impact": 0.9,
                                             "driver_phrase": "victim treated as threat", "driver_count": 2,
                                             "total_cost": 1.8})
    s_mid = m.section_trust_sentence(10, 20, {"worst_category": "under_response", "worst_impact": 0.6})
    s_clean = m.section_trust_sentence(20, 20, {"worst_category": None, "worst_impact": 0.0})
    assert "do not trust" in s_hi
    assert "driven mostly by 'victim treated as threat' (2×)" in s_hi   # dominant driver
    assert "total victim cost" in s_hi
    assert "with care" in s_mid
    assert "trustworthy" in s_clean


@pytest.mark.blocking
def test_s14_trust_contribution_bar(main_module):
    """The trust card's contribution bar: the 4 additive blocks sum to the score,
    and the bar/legend shows the zero-contributors too (pathology etc.)."""
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

    for scene in ("push_06", "push_61", "push_14"):
        sr = _load()[scene]
        tr = _recompute(main_module, sr)
        c = tr["components"]
        ci = c["internal_effective"] * c["effective_internal_weight"]
        we = c["effective_agreement_weight"] / 2.0
        cov = 0.0 if c["coverage_excluded"] else (c["graph_a_coverage"] + c["graph_b_coverage"]) / 2.0 * 0.20
        total = ci + c["a_fidelity"] * we + c["b_edge_coverage"] * we + cov
        assert abs(total - tr["score"]) < 1e-6, f"{scene}: contributions {total} != score {tr['score']}"

    panel = main_module.make_pre_intervention_trust_panel(_recompute(main_module, _load()["push_06"]))
    blob = " ".join(text(panel, []))
    assert "What fed the trust score" in blob
    # zero-contributors are shown explicitly, not omitted
    for z in ("Pathologies", "GT / Test 1", "Suppression picks"):
        assert z in blob, f"zero-contributor {z} not shown in contribution bar"
    assert "0.000" in blob


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
