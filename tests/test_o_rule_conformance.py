"""Section O — Rule conformance checker (module M7).

The checker runs the schema rulebook against the MODEL'S graphs, no GT
needed. These tests feed it hand-built graphs that each break exactly one
rule, plus a clean graph that breaks none.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from conftest import main_module  # noqa: E402, F401


def _node(nid, label, state, hazardous=False):
    return {"id": nid, "label": label, "state": state, "hazardous": hazardous, "inferred": False}


def _edge(src, tgt, effect, via):
    return {"source": src, "target": tgt, "effect": effect, "via_state": via}


def _rules_of(main_module, graph):
    return {v["rule"] for v in main_module.check_graph_rule_conformance(graph, "test")}


# O1 — clean graph: zero violations.
@pytest.mark.blocking
def test_o1_clean_graph_no_violations(main_module):
    graph = {
        "nodes": [
            _node("fire_1", "fire", "spreading", True),
            _node("smoke_1", "smoke", "billowing", True),
            _node("house_1", "house", "intact"),
            _node("person_1", "person", "stationary"),
        ],
        "edges": [
            _edge("fire_1", "house_1", "may_spread_to", "spreading"),
            _edge("fire_1", "smoke_1", "increases_risk_to", "spreading"),
            _edge("smoke_1", "person_1", "may_harm", "billowing"),
        ],
    }
    assert main_module.check_graph_rule_conformance(graph, "test") == []


# O2 — empty graph (negative control): zero violations.
@pytest.mark.blocking
def test_o2_empty_graph_clean(main_module):
    assert main_module.check_graph_rule_conformance({"nodes": [], "edges": []}, "t") == []


# O3 — the label triad lie: fluid may_harm an already-hazardous target.
@pytest.mark.blocking
def test_o3_fluid_may_harm_hazardous_target(main_module):
    graph = {
        "nodes": [
            _node("water_1", "water", "rising", True),
            _node("house_1", "house", "flooded", True),
        ],
        "edges": [_edge("water_1", "house_1", "may_harm", "rising")],
    }
    assert "fluid_may_harm_hazardous_target" in _rules_of(main_module, graph)


# O4 — fluid uses a non-victim effect on a person.
@pytest.mark.blocking
def test_o4_fluid_wrong_effect_for_person(main_module):
    graph = {
        "nodes": [
            _node("water_1", "water", "rising", True),
            _node("person_1", "person", "stationary"),
        ],
        "edges": [_edge("water_1", "person_1", "increases_risk_to", "rising")],
    }
    assert "fluid_wrong_effect_for_person" in _rules_of(main_module, graph)


# O5 — may_spread_to between two already-hazardous entities.
@pytest.mark.blocking
def test_o5_spread_between_hazards(main_module):
    graph = {
        "nodes": [
            _node("house_1", "house", "burning", True),
            _node("house_2", "house", "burning", True),
        ],
        "edges": [
            _edge("house_1", "house_2", "may_spread_to", "burning"),
            _edge("house_1", "house_1", "worsens", "burning"),
            _edge("house_2", "house_2", "worsens", "burning"),
        ],
    }
    assert "spread_between_hazards" in _rules_of(main_module, graph)


# O6 — one-way worsens between distinct entities.
@pytest.mark.blocking
def test_o6_one_way_worsens(main_module):
    graph = {
        "nodes": [
            _node("fire_1", "fire", "spreading", True),
            _node("tanker_1", "tanker", "leaking", True),
        ],
        "edges": [
            _edge("fire_1", "tanker_1", "worsens", "spreading"),
            _edge("tanker_1", "tanker_1", "worsens", "leaking"),
        ],
    }
    assert "one_way_worsens" in _rules_of(main_module, graph)


# O7 — uncoupled obstruction edge to a person.
@pytest.mark.blocking
def test_o7_uncoupled_obstruction(main_module):
    graph = {
        "nodes": [
            _node("tree_1", "tree", "fallen", True),
            _node("person_1", "person", "stationary"),
        ],
        "edges": [
            _edge("tree_1", "person_1", "blocks_access_to", "fallen"),
            _edge("tree_1", "tree_1", "worsens", "fallen"),
        ],
    }
    assert "uncoupled_obstruction" in _rules_of(main_module, graph)


# O8 — entrapment pattern is NOT flagged (water isolates rooftop family).
@pytest.mark.blocking
def test_o8_entrapment_isolates_allowed(main_module):
    graph = {
        "nodes": [
            _node("water_1", "water", "rising", True),
            _node("man_1", "man", "stationary"),
        ],
        "edges": [_edge("water_1", "man_1", "isolates", "rising")],
    }
    assert "uncoupled_obstruction" not in _rules_of(main_module, graph)


# O9 — smoke-superset violation.
@pytest.mark.blocking
def test_o9_smoke_superset(main_module):
    graph = {
        "nodes": [
            _node("house_1", "house", "burning", True),
            _node("smoke_1", "smoke", "billowing", True),
            _node("person_1", "person", "stationary"),
        ],
        "edges": [
            _edge("house_1", "person_1", "may_harm", "burning"),
            _edge("house_1", "smoke_1", "increases_risk_to", "burning"),
            _edge("smoke_1", "smoke_1", "worsens", "billowing"),
        ],
    }
    assert "smoke_superset_violation" in _rules_of(main_module, graph)


# O10 — structural basics: self-loop effect, orphan hazard, via mismatch,
# non-hazardous source, bad effect, unresolved endpoint.
@pytest.mark.blocking
def test_o10_structural_basics(main_module):
    graph = {
        "nodes": [
            _node("fire_1", "fire", "spreading", True),
            _node("car_1", "car", "burning", True),  # orphan hazard
            _node("person_1", "person", "stationary"),
        ],
        "edges": [
            _edge("fire_1", "fire_1", "may_harm", "spreading"),       # self-loop not worsens
            _edge("fire_1", "person_1", "may_harm", "burning"),       # via mismatch
            _edge("person_1", "fire_1", "may_harm", "stationary"),    # non-hazardous source + via not hazard-bearing
            _edge("fire_1", "ghost_9", "may_harm", "spreading"),      # unresolved
            _edge("fire_1", "person_1", "zaps", "spreading"),         # bad effect
        ],
    }
    rules = _rules_of(main_module, graph)
    for expected in (
        "self_loop_not_worsens", "via_state_mismatch", "edge_from_non_hazardous",
        "unresolved_endpoint", "effect_not_in_vocabulary", "hazardous_node_no_edges",
    ):
        assert expected in rules, f"missing {expected}; got {rules}"


# O11 — aggregate wrapper counts both graphs.
@pytest.mark.blocking
def test_o11_aggregate_counts(main_module):
    bad = {
        "nodes": [
            _node("water_1", "water", "rising", True),
            _node("house_1", "house", "flooded", True),
        ],
        "edges": [_edge("water_1", "house_1", "may_harm", "rising")],
    }
    rc = main_module.compute_rule_conformance(bad, bad)
    assert rc["n_violations"] == 2  # one per graph
    assert rc["by_rule"].get("fluid_may_harm_hazardous_target") == 2
