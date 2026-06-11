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
# F4 — Trust score aggregation.
# Skipped unless we locate a trust_score formula entry point.
# ---------------------------------------------------------------------------
@pytest.mark.blocking
@pytest.mark.skip(reason="F4: trust score aggregation formula entry point not yet stable; revisit after report-builder refactor")
def test_f4_trust_score_formula():
    pass


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
