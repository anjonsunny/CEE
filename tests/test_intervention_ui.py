"""Hermetic tests for the Intervention tab UI panels in main.py (built incrementally
by the agentic UI workflow). These assert the rendered Dash component tree carries the
right content for the pipeline's edge cases — the visual layout is verified separately
via the screenshot-in-loop, but the data-wiring is locked here."""
import pytest


def _flatten_text(node) -> str:
    """Recursively collect all string content from a Dash component tree."""
    acc: list[str] = []

    def walk(n):
        if n is None:
            return
        if isinstance(n, str):
            acc.append(n)
            return
        if isinstance(n, (list, tuple)):
            for c in n:
                walk(c)
            return
        walk(getattr(n, "children", None))

    walk(node)
    return " ".join(acc)


@pytest.mark.blocking
def test_candidates_panel_dedups_and_badges_once(main_module):
    """Part 1: when should_be_core == declared_core_a == declared_core_b (declarations
    agree), the hazard is shown ONCE with all source badges and exactly ONE
    SHOULD-BE-CORE badge; the control renders as its own row."""
    m = main_module
    core = {"object_id": "building_1", "state": "collapsed", "label": "building",
            "hazard_class": "discrete_source", "sources": ["A", "B", "GT"],
            "ranks": {"A": 1, "B": 1, "GT": 1}, "is_should_be_core": True}
    control = {"object_id": "debris_1", "state": "exposed", "label": "debris",
               "sources": ["B"], "ranks": {"B": 2}, "is_should_be_core": False}
    candidates = {"candidates": [core, control], "should_be_core": core,
                  "declared_core_a": core, "declared_core_b": core, "control": control,
                  "gt_core_unobserved": None}
    txt = _flatten_text(m.make_candidates_panel(candidates, {"score": 0.85, "level": "moderate"}))
    assert txt.count("SHOULD-BE-CORE") == 1          # badge on the core only, not repeated
    assert "building_1" in txt and "debris_1" in txt  # core + control both shown
    assert "moderate" in txt                          # trust context present


@pytest.mark.blocking
def test_intervention_candidates_callback_placeholder_is_safe(main_module):
    """Part 1 wiring: the live callback (render_intervention_candidates) degrades to a
    safe Div on the placeholder result (no crash, no exception escaping the try/except).
    The populated path is covered by the harness/screenshot loop against saved runs."""
    m = main_module
    out = m.render_intervention_candidates(m.PLACEHOLDER_RESULT, None)
    assert out is not None and out.__class__.__name__ == "Div"


@pytest.mark.blocking
def test_candidates_panel_gt_core_unobserved_and_no_control(main_module):
    """Part 1 edge: should_be_core None + gt_core_unobserved set -> amber 'never
    perceived' row and NO should-be-core badge; control None -> no-control note."""
    m = main_module
    declared_b = {"object_id": "person_1", "state": "drowning", "label": "person",
                  "sources": ["B"], "ranks": {"B": 1}, "is_should_be_core": False}
    candidates = {"candidates": [declared_b], "should_be_core": None,
                  "declared_core_a": None, "declared_core_b": declared_b, "control": None,
                  "gt_core_unobserved": {"object_id": "water_1", "state": "engulfing", "label": "water"}}
    txt = _flatten_text(m.make_candidates_panel(candidates, {"score": 0.05, "level": "low"}))
    assert "SHOULD-BE-CORE" not in txt
    assert "never perceived" in txt.lower() and "water" in txt.lower()
    assert "no independent control" in txt.lower()
