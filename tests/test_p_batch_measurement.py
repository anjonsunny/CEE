"""Section P — Batch-level measurement.

The per-scene instruments (M7 conformance, close-pair swaps) get summed
across a batch inside compute_ground_truth_report. These tests build a tiny
synthetic batch on disk (two runs + one verified GT) and check the tallies.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from conftest import main_module  # noqa: E402, F401


def _write_run(batch_dir: Path, run_id: str, sr: dict) -> None:
    d = batch_dir / run_id
    d.mkdir(parents=True)
    (d / "structured_response.json").write_text(json.dumps({"structured_response": sr}))


def _node(nid, label, state, hazardous=False):
    return {"id": nid, "label": label, "state": state, "hazardous": hazardous, "inferred": False}


def _edge(src, tgt, effect, via):
    return {"source": src, "target": tgt, "effect": effect, "via_state": via}


@pytest.fixture
def synthetic_batch(tmp_path):
    batch = tmp_path / "batch"
    verified = tmp_path / "verified"
    verified.mkdir()

    # Run 1: dirty — graph A has the label-triad lie (water may_harm flooded house).
    _write_run(batch, "run_001", {
        "image_filename": "img1.jpg",
        "causal_graph": {
            "nodes": [_node("water_1", "water", "rising", True),
                      _node("house_1", "house", "flooded", True)],
            "edges": [_edge("water_1", "house_1", "may_harm", "rising")],
        },
        "graph_b": {"nodes": [], "edges": []},
    })

    # Run 2: clean conformance, but uses `threatens` where the GT says
    # `may_harm` (a close-pair vocabulary swap; person target keeps it legal).
    clean_nodes = [_node("fire_1", "fire", "spreading", True),
                   _node("person_1", "person", "stationary")]
    _write_run(batch, "run_002", {
        "image_filename": "img2.jpg",
        "causal_graph": {
            "nodes": clean_nodes,
            "edges": [_edge("fire_1", "person_1", "threatens", "spreading")],
        },
        "graph_b": {"nodes": [], "edges": []},
    })

    # Verified GT for img2 only.
    (verified / "img2.jpg.gt.json").write_text(json.dumps({
        "image_filename": "img2.jpg",
        "nodes": clean_nodes,
        "edges": [_edge("fire_1", "person_1", "may_harm", "spreading")],
    }))
    return batch, verified


# P1 — batch conformance tally counts rules across all runs, GT or not.
@pytest.mark.blocking
def test_p1_batch_conformance_tally(main_module, synthetic_batch):
    batch, verified = synthetic_batch
    report = main_module.compute_ground_truth_report(str(verified), str(batch))
    brc = report["batch_rule_conformance"]
    assert brc["n_scenes"] == 2
    assert brc["clean_scenes"] == 1
    assert brc["by_rule"]["may_harm_hazardous_target"] == {"violations": 1, "scenes": 1}
    assert brc["total_violations"] >= 1
    assert brc["worst_scenes"][0]["image_filename"] == "img1.jpg"


# P2 — close-pair swap totals: the threatens/may_harm substitution is counted
# for the matched pair, on the right graph side.
@pytest.mark.blocking
def test_p2_close_pair_swap_totals(main_module, synthetic_batch):
    batch, verified = synthetic_batch
    report = main_module.compute_ground_truth_report(str(verified), str(batch))
    totals = report["close_pair_swap_totals"]
    assert totals["graph_a"].get("may_harm~threatens") == 1, totals
    assert not totals["graph_b"], "graph B is empty; no swaps expected"


# P3 — the swap counter itself: strict matches are never counted as swaps.
@pytest.mark.blocking
def test_p3_strict_match_not_a_swap(main_module):
    nodes = [_node("fire_1", "fire", "spreading", True),
             _node("person_1", "person", "stationary")]
    g = {"nodes": nodes, "edges": [_edge("fire_1", "person_1", "may_harm", "spreading")]}
    assert main_module.count_close_pair_swaps(g, g) == {}


# P4 — the batch-native report (no GT anywhere) carries the conformance
# tally; it must not depend on Test 1 or a verified folder.
@pytest.mark.blocking
def test_p4_conformance_in_batch_native_report(main_module):
    runs = [{
        "image_filename": "img1.jpg",
        "run_id": "run_001",
        "disaster_scenario": "Yes",
        "causal_graph": {
            "nodes": [_node("water_1", "water", "rising", True),
                      _node("house_1", "house", "flooded", True)],
            "edges": [_edge("water_1", "house_1", "may_harm", "rising")],
        },
        "graph_b": {"nodes": [], "edges": []},
    }]
    report = main_module.compute_pre_intervention_report(runs)
    brc = report["batch_rule_conformance"]
    assert brc["n_scenes"] == 1
    assert brc["by_rule"]["may_harm_hazardous_target"]["violations"] == 1
    # And the markdown renderer shows the section.
    md = main_module.render_report_markdown(report, [], "synthetic")
    assert "Rule conformance" in md
    assert "may_harm_hazardous_target" in md


# P5 — Graph B validity (β) rollup: the per-scene discount aggregates across the
# batch (median β, weak-β count, Test 1 availability).
@pytest.mark.blocking
def test_p5_graph_b_validity_rollup(main_module):
    def _run(rid, beta, conf, threats, test1, score, swt):
        comps = {
            "b_validity_beta": beta,
            "b_conformance_validity": conf,
            "b_threats_coherence": threats,
            "b_test1_accuracy": test1,
            "score_with_test1": swt,
        }
        return {
            "image_filename": f"{rid}.jpg",
            "run_id": rid,
            "disaster_scenario": "Yes",
            "causal_graph": {"nodes": [_node("water_1", "water", "rising", True)],
                             "edges": [_edge("water_1", "water_1", "worsens", "rising")]},
            "graph_b": {"nodes": [], "edges": []},
            "pre_intervention_trust": {"level": "moderate", "score": score, "components": comps},
        }

    runs = [
        _run("run_clean", 1.0, 1.0, 1.0, -1.0, 0.86, 0.86),   # clean B, no GT
        _run("run_weak", 0.30, 0.0, 0.60, 0.40, 0.72, 0.78),  # weak B, has GT, companion differs
    ]
    report = main_module.compute_pre_intervention_report(runs)
    gbv = report["graph_b_validity_rollup"]
    assert gbv["n_with_beta"] == 2
    assert gbv["low_beta_count"] == 1
    assert gbv["low_beta_runs"][0]["run_id"] == "run_weak"
    assert gbv["n_with_gt"] == 1           # only run_weak had Test 1
    assert gbv["companion_differs_count"] == 1
    assert abs(gbv["beta_median"] - 0.65) < 1e-9  # median(1.0, 0.30)

    md = main_module.render_report_markdown(report, [], "synthetic")
    assert "Graph B validity" in md
    assert "run_weak" in md
