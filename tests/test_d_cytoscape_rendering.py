"""Section D — Cytoscape rendering.

graph_to_cytoscape_elements assigns node/edge classes used for visual encoding.
Tests construct minimal hand-built graphs to verify class assignment.
"""
from __future__ import annotations

import re

import pytest


VALID_NODE_CLASSES = {
    "inferred", "orphan-threat", "threat",
    "at-risk-distress", "at-risk-proximity",
    "bystander", "unresolved",
}
VALID_EDGE_CLASSES = {"harm", "propagate", "structural", "invalid", ""}


# ---------------------------------------------------------------------------
# D1 — Every node gets exactly one class.
# ---------------------------------------------------------------------------
@pytest.mark.blocking
def test_d1_every_node_gets_exactly_one_class(main_module):
    graph = {
        "nodes": [
            {"id": "house_1", "label": "house", "state": "burning", "hazardous": True},
            {"id": "person_1", "label": "person", "state": "stationary", "hazardous": False},
            {"id": "victim_1", "label": "person", "state": "drowning", "hazardous": False},
            {"id": "presumed_child_in_pool_1", "label": "child", "state": "drowning",
             "hazardous": False, "inferred": True},
            {"id": "lonely_threat_1", "label": "rock", "state": "burning", "hazardous": True},
            {"id": "bystander_1", "label": "tree", "state": "intact", "hazardous": False},
        ],
        "edges": [
            {"source": "house_1", "target": "person_1", "effect": "may_harm", "via_state": "burning"},
        ],
    }
    elements = main_module.graph_to_cytoscape_elements(graph)
    node_elements = [e for e in elements if "source" not in e["data"]]
    for ne in node_elements:
        cls = ne["classes"]
        # exactly one class — i.e., a single token from the valid set.
        tokens = cls.split()
        assert len(tokens) == 1, f"Node {ne['data']['id']} has {len(tokens)} classes: {cls!r}"
        assert tokens[0] in VALID_NODE_CLASSES, (
            f"Node {ne['data']['id']} has unexpected class {tokens[0]!r}"
        )


# ---------------------------------------------------------------------------
# D2 — Class assignment priority.
# Priority: inferred > orphan-threat > threat > at-risk-distress >
#           at-risk-proximity > bystander
# ---------------------------------------------------------------------------
@pytest.mark.blocking
def test_d2_class_priority_inferred_beats_all(main_module):
    """An inferred node that ALSO matches at-risk Distress conditions still
    classes as `inferred` (highest priority)."""
    graph = {
        "nodes": [
            {"id": "presumed_child_in_pool_1", "label": "child", "state": "drowning",
             "hazardous": False, "inferred": True, "at_risk": True},
        ],
        "edges": [],
    }
    elements = main_module.graph_to_cytoscape_elements(graph)
    assert elements[0]["classes"] == "inferred"


@pytest.mark.blocking
def test_d2_orphan_threat_beats_threat(main_module):
    """Hazardous + zero outgoing edges = orphan-threat (not threat)."""
    graph = {
        "nodes": [
            {"id": "house_1", "label": "house", "state": "burning", "hazardous": True},
        ],
        "edges": [],  # no outgoing
    }
    elements = main_module.graph_to_cytoscape_elements(graph)
    assert elements[0]["classes"] == "orphan-threat"


@pytest.mark.blocking
def test_d2_at_risk_distress_beats_at_risk_proximity(main_module):
    """A drowning person (Distress) with incoming hazard edge classes as
    Distress, NOT Proximity. This is the canonical priority test from TESTS.md."""
    graph = {
        "nodes": [
            {"id": "water_1", "label": "water", "state": "engulfing", "hazardous": True},
            {"id": "person_1", "label": "person", "state": "drowning", "hazardous": False, "at_risk": True},
        ],
        "edges": [
            {"source": "water_1", "target": "person_1", "effect": "may_harm", "via_state": "engulfing"},
        ],
    }
    elements = main_module.graph_to_cytoscape_elements(graph)
    person = next(e for e in elements if e["data"].get("id") == "person_1")
    assert person["classes"] == "at-risk-distress"


@pytest.mark.blocking
def test_d2_threat_beats_at_risk_proximity(main_module):
    """A hazardous node with outgoing edge classes as `threat`, even if
    it has incoming edges (which would otherwise mark it Proximity)."""
    graph = {
        "nodes": [
            {"id": "fire_1", "label": "fire", "state": "spreading", "hazardous": True},
            {"id": "house_1", "label": "house", "state": "burning", "hazardous": True},
        ],
        "edges": [
            {"source": "fire_1", "target": "house_1", "effect": "may_spread_to", "via_state": "spreading"},
            {"source": "house_1", "target": "house_1", "effect": "worsens", "via_state": "burning"},
        ],
    }
    elements = main_module.graph_to_cytoscape_elements(graph)
    house = next(e for e in elements if e["data"].get("id") == "house_1")
    assert house["classes"] == "threat"


# ---------------------------------------------------------------------------
# D3 — Every edge gets a class in {harm, propagate, structural, invalid}.
# ---------------------------------------------------------------------------
@pytest.mark.blocking
def test_d3_edge_class_mapping(main_module):
    cases = [
        ("may_harm", "harm"),
        ("threatens", "harm"),
        ("may_spread_to", "propagate"),
        ("increases_risk_to", "propagate"),
        ("worsens", "propagate"),
        ("blocks_access_to", "structural"),
        ("isolates", "structural"),
        ("exposes", "structural"),
    ]
    for effect, expected_class in cases:
        graph = {
            "nodes": [
                {"id": "a_1", "label": "a", "state": "burning", "hazardous": True},
                {"id": "b_1", "label": "b", "state": "intact", "hazardous": False},
            ],
            "edges": [
                {"source": "a_1", "target": "b_1", "effect": effect, "via_state": "burning"},
            ],
        }
        elements = main_module.graph_to_cytoscape_elements(graph)
        edge_el = next(e for e in elements if "source" in e["data"])
        assert edge_el["classes"] == expected_class, (
            f"effect={effect!r}: expected class {expected_class!r}, got {edge_el['classes']!r}"
        )


@pytest.mark.blocking
def test_d3_invalid_edge_marked(main_module):
    """Edges with valid=False get the `invalid` class appended."""
    graph = {
        "nodes": [
            {"id": "a_1", "label": "a", "state": "burning", "hazardous": True},
            {"id": "b_1", "label": "b", "state": "intact", "hazardous": False},
        ],
        "edges": [
            {"source": "a_1", "target": "b_1", "effect": "may_harm",
             "via_state": "burning", "valid": False},
        ],
    }
    elements = main_module.graph_to_cytoscape_elements(graph)
    edge_el = next(e for e in elements if "source" in e["data"])
    assert "invalid" in edge_el["classes"].split()


# ---------------------------------------------------------------------------
# D4 — Legend hex colors match stylesheet.
# ---------------------------------------------------------------------------
@pytest.mark.blocking
def test_d4_legend_colors_match_stylesheet(main_module):
    """The hex codes used in _graph_legend swatches must exactly match the
    corresponding border-color (nodes) or line-color (edges) declarations in
    CYTOSCAPE_STYLESHEET."""
    stylesheet = main_module.CYTOSCAPE_STYLESHEET
    # Build a {selector_class: color} map from the stylesheet for both nodes and edges.
    node_border: dict[str, str] = {}
    edge_line: dict[str, str] = {}
    for rule in stylesheet:
        sel = rule.get("selector", "")
        st = rule.get("style", {}) or {}
        # `node.threat`, `node.orphan-threat`, etc.
        m = re.match(r"node\.([a-z-]+)$", sel)
        if m:
            color = st.get("border-color")
            if color:
                node_border[m.group(1)] = color.lower()
            continue
        m = re.match(r"edge\.([a-z-]+)$", sel)
        if m:
            color = st.get("line-color")
            if color:
                edge_line[m.group(1)] = color.lower()

    # Walk the legend source for the hex codes we feed into _legend_node_swatch
    # and _legend_edge_swatch. Use the raw main.py source so we don't have to
    # render Dash components.
    src = (main_module.__file__ and
           open(main_module.__file__, "r", encoding="utf-8").read()) or ""
    # Locate the _graph_legend function body.
    legend_start = src.find("def _graph_legend")
    legend_end = src.find("\ndef ", legend_start + 1)
    legend_src = src[legend_start:legend_end]

    expected_node_pairs = {
        "threat": "#dc2626",
        "orphan-threat": "#dc2626",
        "at-risk-distress": "#0369a1",
        "at-risk-proximity": "#7dd3fc",
        "bystander": "#94a3b8",
        "inferred": "#8b5cf6",
        "unresolved": "#737373",
    }
    for cls, expected_hex in expected_node_pairs.items():
        assert node_border.get(cls) == expected_hex.lower(), (
            f"Stylesheet node.{cls} border-color != {expected_hex} (got {node_border.get(cls)!r})"
        )
        # Legend should use the same hex literal.
        assert expected_hex in legend_src.lower(), (
            f"_graph_legend source does not use {expected_hex} for {cls}"
        )

    expected_edge_pairs = {
        "harm": "#dc2626",
        "propagate": "#ea580c",
        "structural": "#0ea5e9",
        "invalid": "#a3a3a3",
    }
    for cls, expected_hex in expected_edge_pairs.items():
        assert edge_line.get(cls) == expected_hex.lower(), (
            f"Stylesheet edge.{cls} line-color != {expected_hex} (got {edge_line.get(cls)!r})"
        )
        assert expected_hex in legend_src.lower(), (
            f"_graph_legend source does not use {expected_hex} for edge.{cls}"
        )


# ---------------------------------------------------------------------------
# D5 — Synonym states classify as Distress (push_20 episode: clinging person
# rendered as Proximity because the classifier checked the raw word against
# the canonical Distress list).
# ---------------------------------------------------------------------------
@pytest.mark.blocking
def test_d5_synonym_state_classifies_as_distress(main_module):
    graph = {
        "nodes": [
            {"id": "water_1", "label": "water", "state": "engulfing", "hazardous": True, "inferred": False},
            {"id": "person_1", "label": "person", "state": "clinging", "hazardous": False, "inferred": False},
            {"id": "person_2", "label": "person", "state": "crouching", "hazardous": False, "inferred": False},
            {"id": "person_3", "label": "person", "state": "stationary", "hazardous": False, "inferred": False},
        ],
        "edges": [
            {"source": "water_1", "target": "person_1", "effect": "may_harm", "via_state": "engulfing"},
            {"source": "water_1", "target": "person_3", "effect": "isolates", "via_state": "engulfing"},
        ],
    }
    elements = main_module.graph_to_cytoscape_elements(graph)
    classes = {e["data"]["id"]: e.get("classes") for e in elements if "source" not in e.get("data", {})}
    assert classes["person_1"] == "at-risk-distress", "clinging (synonym of fleeing) must render as Distress"
    assert classes["person_2"] == "at-risk-distress", "crouching (synonym of fleeing) must render as Distress"
    assert classes["person_3"] == "at-risk-proximity", "stationary with incoming edge stays Proximity"
    # And the label must keep the raw annotator word, not the canonical.
    labels = {e["data"]["id"]: e["data"]["label"] for e in elements if "source" not in e.get("data", {})}
    assert "clinging" in labels["person_1"]
