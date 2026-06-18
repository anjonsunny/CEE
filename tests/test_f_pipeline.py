"""Section F — Pipeline integration.

Most F tests need a live Qwen runtime; they're marked needs_qwen and skipped
by default. F3 (consistency scores compute without error) is testable on
hand-built inputs and is implemented.
"""
from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# F1, F2 — Need live Qwen.
# ---------------------------------------------------------------------------
@pytest.mark.blocking
@pytest.mark.needs_qwen
@pytest.mark.skip(reason="F1: requires a live Qwen run on a sample scene; rerun manually after the next pipeline pass")
def test_f1_qwen_output_conforms_to_gt_schema():
    pass


@pytest.mark.blocking
@pytest.mark.needs_qwen
@pytest.mark.skip(reason="F2: requires a live Graph B run; capture fixture under tests/fixtures/sample_qwen_outputs/ then unskip")
def test_f2_graph_b_internally_consistent():
    pass


# ---------------------------------------------------------------------------
# F3 — Consistency scores compute without error on hand-built inputs.
# ---------------------------------------------------------------------------
@pytest.mark.blocking
def test_f3_consistency_scores_well_formed(main_module):
    """For any A vs B comparison, numeric scores ∈ [0, 1] and diff lists are
    well-formed (lists of dicts / strings)."""
    graph_a = {
        "nodes": [
            {"id": "house_1", "label": "house", "state": "burning", "hazardous": True},
            {"id": "person_1", "label": "person", "state": "stationary", "hazardous": False},
        ],
        "edges": [
            {"source": "house_1", "target": "person_1", "effect": "may_harm", "via_state": "burning"},
        ],
    }
    graph_b = {
        "nodes": [
            {"id": "house_1", "label": "house", "state": "burning", "hazardous": True},
            {"id": "person_1", "label": "person", "state": "stationary", "hazardous": False},
        ],
        "edges": [
            {"source": "house_1", "target": "person_1", "effect": "threatens", "via_state": "burning"},
        ],
    }
    r = main_module.compare_graphs(graph_a, graph_b)
    for key in ("a_fidelity", "b_coverage", "a_fidelity_soft", "b_coverage_soft",
                "structural_consistency", "topological_consistency",
                "node_consistency", "flag_consistency"):
        v = r[key]
        assert 0.0 <= v <= 1.0, f"{key}={v} outside [0,1]"
    assert isinstance(r["node_diff"]["only_in_a"], list)
    assert isinstance(r["edge_diff"]["only_in_a"], list)


# ---------------------------------------------------------------------------
# F4 — Trust score: Graph B validity (beta) discounts the A-vs-B agreement
# terms. beta == 1 (clean B) reproduces the prior formula; a malformed B shifts
# weight onto Graph A's own internal coherence.
# ---------------------------------------------------------------------------
@pytest.mark.blocking
def test_f4_trust_b_validity_discount(main_module):
    alignment = {"score": 0.90, "passed_checks": 10, "failed_checks": 0, "failures": []}
    consistency = {
        "a_fidelity": 0.80, "b_coverage": 0.70,
        "a_fidelity_soft": 0.80, "b_coverage_soft": 0.70,
        "topological_consistency": 0.90, "structural_consistency": 0.90,
        "node_consistency": 1.0, "flag_consistency": 1.0,
    }
    # Graph A has an edge (avoids the no-threats short-circuit) and full coverage.
    graph_a = {
        "nodes": [{"id": "house_1", "label": "house", "state": "burning", "hazardous": True}],
        "edges": [{"source": "house_1", "target": "house_1", "effect": "worsens", "via_state": "burning"}],
        "threat_reasoning_coverage": 1.0,
    }

    # Clean B (empty → no violations, no hazard/threat mismatch): beta == 1.0,
    # score reproduces 0.40*Internal + 0.20*Afid + 0.20*Bcov + 0.20*Coverage.
    clean = main_module.assess_pre_intervention_trust(
        alignment, consistency, graph_a, {"threat_reasoning_coverage": 1.0}, threats=[])
    assert abs(clean["components"]["b_validity_beta"] - 1.0) < 1e-9
    expected = 0.40 * 0.90 + 0.20 * 0.80 + 0.20 * 0.70 + 0.20 * 1.0
    assert abs(clean["score"] - expected) < 1e-9, f"{clean['score']} != {expected}"

    # Malformed B: edge to a nonexistent node (structural violation) AND a
    # hazardous node with no matching threat → beta drives toward 0, the
    # agreement terms are zeroed, weight moves onto Internal.
    bad_b = {
        "nodes": [{"id": "fire_1", "label": "fire", "state": "burning", "hazardous": True}],
        "edges": [{"source": "fire_1", "target": "ghost_9", "effect": "may_harm", "via_state": "burning"}],
        "threat_reasoning_coverage": 1.0,
    }
    bad = main_module.assess_pre_intervention_trust(
        alignment, consistency, graph_a, bad_b, threats=[])
    beta = bad["components"]["b_validity_beta"]
    assert beta < 0.5, f"expected discounted beta, got {beta}"
    # With beta≈0: score == (0.40 + 0.40)*Internal + 0.20*Coverage, agreement zeroed.
    w_internal = 0.40 + (1.0 - beta) * 0.40
    expected_bad = w_internal * 0.90 + beta * 0.20 * 0.80 + beta * 0.20 * 0.70 + 0.20 * 1.0
    assert abs(bad["score"] - expected_bad) < 1e-9
    # The discount is surfaced to the operator.
    assert any("Graph B validity" in q for q in bad["qualifiers"])

    # Test 1 (B vs verified GT) also discounts beta when available. A clean,
    # threat-coherent B that nonetheless disagrees with the reference is a worse
    # yardstick. Threat coherence kept at 1.0 (B's hazard matches the threat) so
    # only the low Test 1 score moves beta below 1.
    gv_low = {"available": True, "b_correctness_soft": 0.20, "b_precision_soft": 0.20}
    coherent_b = {
        "nodes": [{"id": "house_1", "label": "house", "state": "burning", "hazardous": True}],
        "edges": [{"source": "house_1", "target": "house_1", "effect": "worsens", "via_state": "burning"}],
        "threat_reasoning_coverage": 1.0,
    }
    threats = [{"object_id": "house_1"}]
    with_t1 = main_module.assess_pre_intervention_trust(
        alignment, consistency, graph_a, coherent_b, threats=threats, gt_validation=gv_low)
    comp = with_t1["components"]
    assert comp["b_test1_accuracy"] == 0.20
    # Headline (deployment) beta excludes Test 1: mean(conformance 1.0, threats 1.0) = 1.0.
    assert abs(comp["b_validity_beta"] - 1.0) < 1e-9
    # Verified beta folds Test 1 in: mean(1.0, 1.0, 0.20).
    assert abs(comp["b_validity_beta_verified"] - (1.0 + 1.0 + 0.20) / 3.0) < 1e-9
    # KEY PROPERTY: Test 1 does NOT move the headline score (no answer-key leak);
    # it only changes the companion score_with_test1.
    headline_clean_b = main_module.assess_pre_intervention_trust(
        alignment, consistency, graph_a, coherent_b, threats=threats, gt_validation=None)["score"]
    assert abs(with_t1["score"] - headline_clean_b) < 1e-9
    assert with_t1["score"] != with_t1["components"]["score_with_test1"]

    # No GT → Test 1 omitted (not penalized): deployment == verified, companion == headline.
    no_gt = main_module.assess_pre_intervention_trust(
        alignment, consistency, graph_a, coherent_b, threats=threats, gt_validation=None)
    assert no_gt["components"]["b_test1_accuracy"] == -1.0
    assert abs(no_gt["components"]["b_validity_beta"] - 1.0) < 1e-9
    assert abs(no_gt["components"]["score_with_test1"] - no_gt["score"]) < 1e-9


# F8 — Graph B trust lives in its own panel (NOT the trust card). The panel
# surfaces conformance validity, threats coherence, optional Test 1, and β.
@pytest.mark.blocking
def test_f8_graph_b_trust_panel(main_module):
    def text_blobs(node):
        out = []
        ch = getattr(node, "children", None)
        if isinstance(ch, str):
            out.append(ch)
        elif isinstance(ch, (list, tuple)):
            for c in ch:
                out.extend(text_blobs(c))
        elif ch is not None:
            out.extend(text_blobs(ch))
        return out

    # No components → empty state.
    empty = main_module.make_graph_b_trust_panel({"components": {}})
    assert "Run analysis" in " ".join(text_blobs(empty))

    # B with violations on every edge → conformance validity 0 shown, β shown.
    trust = {
        "components": {
            "b_conformance_validity": 0.0,
            "b_threats_coherence": 1.0,
            "b_test1_accuracy": 0.40,
            "b_validity_beta": 0.50,
            "b_validity_beta_verified": (0.0 + 1.0 + 0.40) / 3.0,
        }
    }
    panel = main_module.make_graph_b_trust_panel(trust)
    blob = " ".join(text_blobs(panel))
    assert "Conformance validity" in blob and "0.00" in blob
    assert "β = 0.50" in blob
    assert "Test 1" in blob  # only shown because b_test1_accuracy >= 0

    # Collapsible detail: the receipts behind each score, color-coded by type.
    def classes(node):
        out = []
        c = getattr(node, "className", None)
        if isinstance(c, str):
            out.append(c)
        ch = getattr(node, "children", None)
        if isinstance(ch, (list, tuple)):
            for x in ch:
                out.extend(classes(x))
        elif ch is not None and not isinstance(ch, str):
            out.extend(classes(ch))
        return out

    detailed = main_module.make_graph_b_trust_panel(
        trust,
        rule_conformance={"violations": [
            {"rule": "may_harm_hazardous_target", "graph": "graph_b", "detail": "house_1 may_harm car_1 (already burning)"},
            {"rule": "redundant_self_loop", "graph": "graph_a", "detail": "ignore me, graph_a"},
        ]},
        graph_b={"nodes": [{"id": "house_1", "state": "burning", "hazardous": True},
                           {"id": "smoke_1", "state": "billowing", "hazardous": True}]},
        threats=[{"object_id": "house_1"}],  # smoke_1 hazardous in B but not declared → warn
        gt_validation={
            "available": True,
            "b_edge_diff": {
                "spurious": [{"source": "house_1", "effect": "may_harm", "via_state": "burning", "target": "car_1"}],
                "missed": [{"source": "house_2", "effect": "worsens", "via_state": "burning", "target": "house_3"}],
                "matched": [{"source": "house_1", "effect": "worsens", "via_state": "burning", "target": "house_2"}],
            },
        },
    )
    dblob = " ".join(text_blobs(detailed))
    dcls = classes(detailed)
    # Only the graph_b violation is listed, not the graph_a one.
    assert "may_harm_hazardous_target" in dblob
    assert "ignore me" not in dblob
    # Threats mismatch surfaced (smoke_1 hazardous in B, not a declared threat).
    assert "smoke_1" in dblob
    # GT edge mismatches surfaced.
    assert "spurious" in dblob and "missed" in dblob
    # Color-coded classes present for all three severities.
    allcls = " ".join(dcls)
    assert "gb-detail-bad" in allcls and "gb-detail-warn" in allcls and "gb-detail-ok" in allcls


# F9 — single-run and batch trust are consistent: EVERY call to
# assess_pre_intervention_trust passes both threats= and gt_validation=, so all
# three pipeline paths (normalize_result, the UI analysis path, the batch worker)
# compute identical trust + Graph B validity. Guards against a new call site
# silently dropping an arg.
@pytest.mark.blocking
def test_f9_trust_call_sites_pass_threats_and_gt(main_module):
    import re
    from pathlib import Path
    src = Path(main_module.__file__).read_text()

    calls = []
    needle = "assess_pre_intervention_trust("
    for m in re.finditer(re.escape(needle), src):
        start = m.start()
        # Skip the function definition itself.
        if src[max(0, start - 4):start].rstrip().endswith("def"):
            continue
        # Capture the balanced-paren argument block.
        i = m.end()
        depth = 1
        while i < len(src) and depth:
            if src[i] == "(":
                depth += 1
            elif src[i] == ")":
                depth -= 1
            i += 1
        calls.append(src[m.start():i])

    assert len(calls) >= 3, f"expected >=3 call sites, found {len(calls)}"
    for c in calls:
        assert "threats=" in c, f"call site missing threats=: {c[:80]}"
        assert "gt_validation=" in c, f"call site missing gt_validation=: {c[:80]}"


# ---------------------------------------------------------------------------
# F5–F7 — Need pipeline runtime.
# ---------------------------------------------------------------------------
@pytest.mark.blocking
@pytest.mark.needs_qwen
@pytest.mark.skip(reason="F5: requires prompt schema_version constant (C21 dependency) AND live Qwen output")
def test_f5_qwen_output_matches_prompt_version():
    pass


@pytest.mark.blocking
@pytest.mark.needs_qwen
@pytest.mark.skip(reason="F6: end-to-end smoke; capture full-run fixture or enable RUN_QWEN=1")
def test_f6_end_to_end_smoke():
    pass


@pytest.mark.blocking
@pytest.mark.needs_qwen
@pytest.mark.skip(reason="F7: depends on F1 Qwen capture + Section J implementation")
def test_f7_pipeline_passes_all_j_rules():
    pass
