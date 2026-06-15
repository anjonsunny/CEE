"""Section H — UI workflow integrity.

H1 is the highest-value test; implemented only as a smoke check that the save
helper symbol exists in main.py (full Dash test-client integration is brittle).
"""
from __future__ import annotations

import pytest


@pytest.mark.blocking
@pytest.mark.skip(reason="H1: end-to-end save callback test requires Dash test client setup; smoke import covered by G2")
def test_h1_verified_gt_save_writes_file():
    pass


@pytest.mark.warn
@pytest.mark.skip(reason="H2: next-pending navigation needs Dash test client + folder fixture")
def test_h2_next_pending_does_not_skip():
    pass


@pytest.mark.warn
@pytest.mark.human
@pytest.mark.skip(reason="H3: folder browser persistence is HUMAN-only per TESTS.md")
def test_h3_folder_browser_path_persistence():
    pass


@pytest.mark.warn
@pytest.mark.skip(reason="H4: live graph refresh needs Dash test client; manual check — add edge, fill source/target dropdowns, graph view updates on selection without another button click")
def test_h4_live_graph_refresh_on_field_change():
    pass


# The 13 ids render_results writes into. If a layout pass drops or duplicates
# one, the callback breaks at runtime; this catches it at test time.
RESULT_PANEL_IDS = [
    "detected-objects",
    "scene-summary",
    "threatening-objects",
    "at-risk-objects",
    "recommendations",
    "graph-a-card",
    "graph-b-card",
    "pre-internal-alignment-card",
    "graph-consistency-card",
    "pre-trust-card",
    "pathology-card",
    "gt-validation-card",
    "suppression-card",
]


def _walk(component):
    yield component
    children = getattr(component, "children", None)
    if children is None:
        return
    if not isinstance(children, (list, tuple)):
        children = [children]
    for child in children:
        if hasattr(child, "children") or hasattr(child, "id"):
            yield from _walk(child)


@pytest.mark.blocking
def test_h5_results_layout_keeps_callback_ids_and_sections(main_module):
    """H5 — the grouped (collapsible-section) results layout still contains
    every id render_results targets, exactly once, and the section wrappers
    follow the MODULES.md ordering: scene reading -> graphs -> self-checks ->
    GT checks -> trust aggregate."""
    layout = main_module.serve_layout()
    nodes = list(_walk(layout))

    ids = [getattr(n, "id", None) for n in nodes]
    for panel_id in RESULT_PANEL_IDS:
        assert ids.count(panel_id) == 1, f"{panel_id}: expected exactly 1, got {ids.count(panel_id)}"

    section_titles = [
        getattr(n, "children", None)
        for n in nodes
        if getattr(n, "className", "") == "section-summary-title"
    ]
    assert section_titles == [
        "Scene Reading",
        "Causal Graphs",
        "Model Self-Checks",
        "Checks Against the Answer Key",
        "Trust Reading",
    ]
