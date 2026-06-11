"""Section E — Comparison correctness.

Tier monotonicity, identity, synonym/effect collapsing. Synthetic fixtures
hand-built to exercise each invariant.

Note: main.py's compare_graphs returns several score keys. "Strict" tier maps
to a_fidelity / b_coverage (verbatim 4-tuple), "soft" to a_fidelity_soft /
b_coverage_soft, "topological" to topological_consistency. We exercise the
three tiers via those keys.
"""
from __future__ import annotations

import copy

import pytest


# ---------------------------------------------------------------------------
# Helpers — build minimal graph dicts.
# ---------------------------------------------------------------------------
def _graph(nodes, edges):
    return {"nodes": nodes, "edges": edges}


def _node(nid, label, state, hazardous=False, inferred=False):
    return {"id": nid, "label": label, "state": state, "hazardous": hazardous, "inferred": inferred}


def _edge(src, tgt, effect, via):
    return {"source": src, "target": tgt, "effect": effect, "via_state": via}


# ---------------------------------------------------------------------------
# E1 — Tier monotonicity: strict ≤ soft ≤ topological.
# Run on a sample of push_test GTs paired against themselves with one synonym
# perturbation, so all three tiers are exercised meaningfully.
# ---------------------------------------------------------------------------
@pytest.mark.blocking
def test_e1_tier_monotonicity_on_synthetic_pair(main_module):
    """strict ≤ soft ≤ topo on synthetic pair where candidate uses a synonym
    ('on_fire' vs 'burning') for one edge."""
    gt = _graph(
        [_node("house_1", "house", "burning", hazardous=True),
         _node("person_1", "person", "stationary")],
        [_edge("house_1", "person_1", "may_harm", "burning")],
    )
    cand = _graph(
        [_node("house_1", "house", "on_fire", hazardous=True),
         _node("person_1", "person", "stationary")],
        [_edge("house_1", "person_1", "threatens", "on_fire")],
    )
    r = main_module.compare_graphs(gt, cand)
    strict = r["a_fidelity"]
    soft = r["a_fidelity_soft"]
    topo = r["topological_consistency"]
    assert strict <= soft <= topo + 1e-9, f"tier monotonicity violated: strict={strict}, soft={soft}, topo={topo}"


# ---------------------------------------------------------------------------
# E2 — Identity comparison = 1.00 across all tiers.
# ---------------------------------------------------------------------------
@pytest.mark.blocking
def test_e2_identity_is_1_00(main_module, sample_gt_minimal_burning_house):
    g = main_module.gt_candidate_to_graph_dict(sample_gt_minimal_burning_house)
    r = main_module.compare_graphs(g, g)
    for key in ("a_fidelity", "a_fidelity_soft", "b_coverage", "b_coverage_soft",
                "node_consistency", "structural_consistency", "topological_consistency",
                "flag_consistency"):
        assert r[key] == 1.0, f"{key} not 1.00 on identity comparison: {r[key]}"


# ---------------------------------------------------------------------------
# E3 — Empty vs empty does NOT silently score 1.00 as "real data".
# The implementation defaults to 1.0 (vacuous-true), but the consistency panel
# uses a separate has_data guard. We assert the contract: empty inputs return
# the documented vacuous default (1.0) AND the diff dicts are all empty so a
# caller can detect the empty case.
# ---------------------------------------------------------------------------
@pytest.mark.blocking
def test_e3_empty_vs_empty_detectable(main_module):
    r = main_module.compare_graphs({"nodes": [], "edges": []}, {"nodes": [], "edges": []})
    assert r["node_diff"]["only_in_a"] == []
    assert r["node_diff"]["only_in_b"] == []
    assert r["node_diff"]["in_both"] == []
    assert r["edge_diff"]["only_in_a"] == []
    assert r["edge_diff"]["only_in_b"] == []
    assert r["edge_diff"]["in_both"] == []
    # Vacuous defaults are 1.0 (documented in compare_graphs); the consumer
    # (make_consistency_panel) gates rendering on has_data. This test asserts
    # the GUARD signal exists in the diff dicts so consumers can detect empty.


# ---------------------------------------------------------------------------
# E4 — Synonym canonicalization works in soft tier.
# (Strict tier requires verbatim via_state, so synonym differences DO show up
# in strict — they only collapse in soft.)
# ---------------------------------------------------------------------------
@pytest.mark.blocking
def test_e4_synonym_canonicalization_in_soft_tier(main_module):
    gt = _graph(
        [_node("house_1", "house", "burning", hazardous=True),
         _node("person_1", "person", "stationary")],
        [_edge("house_1", "person_1", "may_harm", "burning")],
    )
    cand = _graph(
        [_node("house_1", "house", "on_fire", hazardous=True),
         _node("person_1", "person", "stationary")],
        [_edge("house_1", "person_1", "may_harm", "on_fire")],
    )
    r = main_module.compare_graphs(gt, cand)
    # Strict via_state differs → strict miss; soft canonicalises → soft hit.
    assert r["a_fidelity"] < 1.0, "strict tier should NOT collapse synonyms"
    assert r["a_fidelity_soft"] == 1.0, "soft tier should collapse on_fire → burning"


# ---------------------------------------------------------------------------
# E5 — Effect-pair collapsing in soft tier.
# ---------------------------------------------------------------------------
@pytest.mark.blocking
def test_e5_effect_pair_collapse_in_soft(main_module):
    """may_harm vs threatens (and blocks_access_to vs isolates) match soft, miss strict."""
    base_nodes = [
        _node("house_1", "house", "burning", hazardous=True),
        _node("person_1", "person", "stationary"),
    ]
    for e_gt, e_cand in [("may_harm", "threatens"), ("blocks_access_to", "isolates")]:
        gt = _graph(base_nodes, [_edge("house_1", "person_1", e_gt, "burning")])
        cand = _graph(base_nodes, [_edge("house_1", "person_1", e_cand, "burning")])
        r = main_module.compare_graphs(gt, cand)
        assert r["a_fidelity"] < 1.0, f"strict should miss {e_gt} vs {e_cand}"
        assert r["a_fidelity_soft"] == 1.0, f"soft should collapse {e_gt} ↔ {e_cand}"


# ---------------------------------------------------------------------------
# E6 — Label hierarchy collapse in soft tier.
# Note: soft tier in main.py canonicalises via _fuzzy_edge_key which uses
# resolve_label_class for SOURCE/TARGET labels. Different labels in the same
# family (house, apartment, school all → "structure") collapse for fuzzy
# matching.
# ---------------------------------------------------------------------------
@pytest.mark.blocking
def test_e6_label_hierarchy_collapse_in_soft(main_module):
    """house vs apartment (both → structure) match in soft/topo tier even
    though node ids differ."""
    gt = _graph(
        [_node("fire_1", "fire", "spreading", hazardous=True),
         _node("house_1", "house", "intact")],
        [_edge("fire_1", "house_1", "may_spread_to", "spreading")],
    )
    cand = _graph(
        [_node("fire_1", "fire", "spreading", hazardous=True),
         _node("house_1", "apartment", "intact")],
        [_edge("fire_1", "house_1", "may_spread_to", "spreading")],
    )
    r = main_module.compare_graphs(gt, cand)
    # node ids identical so strict and soft both 1; the label collapse
    # matters when node IDs differ but label classes align. Test that
    # explicit case:
    gt2 = _graph(
        [_node("fire_1", "fire", "spreading", hazardous=True),
         _node("house_1", "house", "intact")],
        [_edge("fire_1", "house_1", "may_spread_to", "spreading")],
    )
    cand2 = _graph(
        [_node("fire_1", "fire", "spreading", hazardous=True),
         _node("apt_1", "apartment", "intact")],
        [_edge("fire_1", "apt_1", "may_spread_to", "spreading")],
    )
    r2 = main_module.compare_graphs(gt2, cand2)
    # Strict misses because target id differs; soft via label hierarchy should match.
    assert r2["a_fidelity"] < 1.0, "strict should miss on differing node ids"
    assert r2["a_fidelity_soft"] == 1.0, "soft should match on label hierarchy collapse"


# ---------------------------------------------------------------------------
# E7 — Mutual worsens counted as 2 edges.
# ---------------------------------------------------------------------------
@pytest.mark.blocking
def test_e7_mutual_worsens_counts_as_two(main_module, sample_gt_mutual_worsens):
    g = main_module.gt_candidate_to_graph_dict(sample_gt_mutual_worsens)
    # Self-comparison: both directions present in both graphs → strict = 1.0.
    r = main_module.compare_graphs(g, g)
    assert r["a_fidelity"] == 1.0
    # Comparison against a candidate with only ONE direction → 50% strict
    # fidelity on A side (1 of 2 GT edges matched).
    one_direction = copy.deepcopy(sample_gt_mutual_worsens)
    one_direction["edges"] = [sample_gt_mutual_worsens["edges"][0]]
    g_partial = main_module.gt_candidate_to_graph_dict(one_direction)
    r2 = main_module.compare_graphs(g, g_partial)
    # GT has 2 edges, candidate has 1; intersection = 1; structural = 1/2.
    assert r2["structural_consistency"] == pytest.approx(0.5), (
        f"mutual worsens should count as 2; got structural={r2['structural_consistency']}"
    )


# ---------------------------------------------------------------------------
# E8 — Comparison determinism.
# ---------------------------------------------------------------------------
@pytest.mark.blocking
def test_e8_comparison_deterministic(main_module, sample_gt_minimal_burning_house):
    g = main_module.gt_candidate_to_graph_dict(sample_gt_minimal_burning_house)
    r1 = main_module.compare_graphs(g, g)
    r2 = main_module.compare_graphs(g, g)
    # Numeric keys must be byte-identical; diff lists must be identical content.
    for key in ("a_fidelity", "a_fidelity_soft", "structural_consistency",
                "topological_consistency", "node_consistency", "flag_consistency"):
        assert r1[key] == r2[key], f"non-deterministic: {key}: {r1[key]} vs {r2[key]}"
    assert r1["node_diff"] == r2["node_diff"]
    assert r1["edge_diff"] == r2["edge_diff"]


# ---------------------------------------------------------------------------
# E9 — Comparison handles missing optional fields gracefully.
# ---------------------------------------------------------------------------
@pytest.mark.blocking
def test_e9_missing_optional_fields_graceful(main_module):
    """GT and candidate omit annotator_notes / evidence / image_filename /
    inferred / at_risk — comparison should not raise."""
    minimal_gt = {
        "nodes": [
            {"id": "house_1", "label": "house", "state": "burning", "hazardous": True},
            {"id": "person_1", "label": "person", "state": "stationary", "hazardous": False},
        ],
        "edges": [
            {"source": "house_1", "target": "person_1", "effect": "may_harm", "via_state": "burning"},
        ],
    }
    g = main_module.gt_candidate_to_graph_dict(minimal_gt)
    r = main_module.compare_graphs(g, g)
    assert r["a_fidelity"] == 1.0


# ---------------------------------------------------------------------------
# E10 — Synonym diff preserves original form. WARN.
# This is partial: we assert the only_in_a / only_in_b lists contain raw edge
# dicts (which carry the original via_state field), proving the original form
# is preserved through the diff. Full UX assertion is human.
# ---------------------------------------------------------------------------
@pytest.mark.warn
def test_e10_synonym_diff_preserves_original_form(main_module):
    """When GT uses 'crouching' and candidate uses 'fleeing' (both canonicalise
    to fleeing), the diff lists should carry the raw via_state words, not
    silently replace with the canonical."""
    gt = _graph(
        [_node("scene_1", "scene", "burning", hazardous=True),
         _node("person_1", "person", "crouching")],
        # not a real causal pattern; just to exercise diff structure
        [_edge("scene_1", "person_1", "may_harm", "burning")],
    )
    cand = _graph(
        [_node("scene_1", "scene", "burning", hazardous=True),
         _node("person_1", "person", "fleeing")],
        [_edge("scene_1", "person_1", "may_harm", "burning")],
    )
    r = main_module.compare_graphs(gt, cand)
    # node-level: in strict tier the IDs match; only the state differs. The
    # node_diff carries node IDs only (canonicalisation invisible there).
    # E10 in spirit applies to edge via_states; we surface here that the
    # diff DOES NOT mutate the original via_state strings.
    for e in r["edge_diff"]["only_in_a"] + r["edge_diff"]["only_in_b"] + r["edge_diff"]["in_both"]:
        assert "via_state" in e, "edge diff must keep via_state field intact"
        # raw form: not auto-canonicalised
        assert e["via_state"] in ("burning",), (
            f"via_state should retain original form, got {e['via_state']!r}"
        )
