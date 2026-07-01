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
def test_candidates_panel_all_three_picks_agree(main_module):
    """Redesign: when the algorithm pick, the VLM pick, and the GT pick all name the
    same hazard, the panel reads 'All three agree'. Every distinct candidate hazard
    renders as a chip (deduped by object_id), and no internal jargon leaks (no
    'control', no 'should-be-core', no 'A#1')."""
    m = main_module
    core = {"object_id": "building_1", "state": "collapsed", "label": "building",
            "hazard_class": "discrete_source", "sources": ["A", "B", "GT"],
            "ranks": {"A": 1, "B": 1, "GT": 1}, "is_should_be_core": True}
    other = {"object_id": "debris_1", "state": "exposed", "label": "debris",
             "sources": ["B"], "ranks": {"B": 2}, "is_should_be_core": False}
    candidates = {"candidates": [core, other], "should_be_core": core,
                  "declared_core_a": core, "declared_core_b": core, "control": other,
                  "gt_core_unobserved": None}
    detected = [
        {"object_id": "building_1", "label": "building", "state": "collapsed", "bbox": [0, 0, 10, 10]},
        {"object_id": "debris_1", "label": "debris", "state": "exposed", "bbox": [5, 5, 15, 15]},
    ]
    framework_picks = [{"rank": 1, "threat": "building_1", "state": "collapsed"}]
    vlm_pick = {"threat": "building_1", "state": "collapsed", "reason": "most severe"}
    panel = m.make_candidates_panel(candidates, {"score": 0.85, "level": "moderate"},
                                    detected, None, framework_picks, vlm_pick)
    txt = _flatten_text(panel)
    assert "all three agree" in txt.lower()           # agreement line
    assert "moderate" in txt                           # trust context present
    assert "building" in txt and "debris" in txt       # both candidate hazards shown as chips
    # no internal experiment jargon in the user-facing panel
    low = txt.lower()
    assert "should-be-core" not in low and "control" not in low and "a#1" not in low


@pytest.mark.blocking
def test_intervention_candidates_callback_placeholder_is_safe(main_module):
    """Part 1 wiring: the live callback (render_intervention_candidates) degrades to a
    safe Div on the placeholder result (no crash, no exception escaping the try/except).
    The populated path is covered by the harness/screenshot loop against saved runs."""
    m = main_module
    out = m.render_intervention_candidates(m.PLACEHOLDER_RESULT, None)
    assert out is not None and out.__class__.__name__ == "Div"


@pytest.mark.blocking
def test_candidates_panel_gt_core_unobserved(main_module):
    """Redesign edge: should_be_core None + gt_core_unobserved set -> the GT pick reads
    'the model never perceived the ground-truth core: <label>'. Low trust reads
    'provisional'. Still no internal jargon (no 'should-be-core', no 'control')."""
    m = main_module
    declared_b = {"object_id": "person_1", "state": "drowning", "label": "person",
                  "sources": ["B"], "ranks": {"B": 1}, "is_should_be_core": False}
    candidates = {"candidates": [declared_b], "should_be_core": None,
                  "declared_core_a": None, "declared_core_b": declared_b, "control": None,
                  "gt_core_unobserved": {"object_id": "water_1", "state": "engulfing", "label": "water"}}
    detected = [{"object_id": "person_1", "label": "person", "state": "drowning", "bbox": [1, 2, 3, 4]}]
    vlm_pick = {"threat": "person_1", "state": "drowning", "reason": "immediate"}
    txt = _flatten_text(m.make_candidates_panel(
        candidates, {"score": 0.05, "level": "low"}, detected, None, [], vlm_pick))
    low = txt.lower()
    assert "never perceived the ground-truth core" in low and "water" in low
    assert "provisional" in low                        # low-trust qualifier
    assert "should-be-core" not in low and "control" not in low
