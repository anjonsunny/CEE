"""Section J — Recommendation block conformance (Layer 2 rules).

J1–J3 are testable as structural validators on hand-built recommendation
dicts. J4–J7 need either fixtures or live Qwen output. J8 is HUMAN.
"""
from __future__ import annotations

import pytest


def _scene(detected_objects, recommendations):
    return {"detected_objects": detected_objects, "recommendations": recommendations}


# ---------------------------------------------------------------------------
# J1 — Reason / triple coverage.
# ---------------------------------------------------------------------------
@pytest.mark.blocking
def test_j1_reason_triple_coverage_passes_on_well_formed():
    """J1 (structural validator) — every object_id mentioned in reason
    appears in related_object_ids AND in the triple; every object_id in
    the triple appears in reason.

    We implement the validator inline (it's what the spec requires of any
    consumer of Qwen output). Test passes on a clean fixture and fails on
    a broken one.
    """
    rec_good = {
        "threat": "house_1",
        "affected_objects": ["person_1"],
        "related_object_ids": ["house_1", "person_1"],
        "reason": "Because house_1 is burning, it may_harm person_1.",
    }

    def coverage_ok(rec):
        text = rec.get("reason", "")
        triple_ids = {rec.get("threat", "")} | set(rec.get("affected_objects") or [])
        triple_ids.discard("")
        # Use simple word-boundary check for object IDs:
        import re
        mentioned = set(re.findall(r"[a-z][a-z0-9_]*_\d+", text))
        related = set(rec.get("related_object_ids") or [])
        # every triple id appears in reason
        for tid in triple_ids:
            if tid not in mentioned:
                return False
        # every mentioned id appears in related and in triple
        for mid in mentioned:
            if mid not in related or mid not in triple_ids:
                return False
        return True

    assert coverage_ok(rec_good), "well-formed rec should pass J1"

    rec_bad = {
        "threat": "house_1",
        "affected_objects": ["person_1"],
        "related_object_ids": ["house_1"],  # missing person_1
        "reason": "Because house_1 is burning, it may_harm person_1.",
    }
    assert not coverage_ok(rec_bad), "rec missing person_1 in related_object_ids should fail J1"


# ---------------------------------------------------------------------------
# J2 — affected_objects ⊆ detected_objects.
# ---------------------------------------------------------------------------
@pytest.mark.blocking
def test_j2_affected_objects_references_declared_entities():
    scene_good = _scene(
        detected_objects=[{"object_id": "house_1"}, {"object_id": "person_1"}],
        recommendations=[{"threat": "house_1", "affected_objects": ["person_1"]}],
    )
    declared = {o["object_id"] for o in scene_good["detected_objects"]}
    for rec in scene_good["recommendations"]:
        for aid in rec.get("affected_objects") or []:
            assert aid in declared

    scene_bad = _scene(
        detected_objects=[{"object_id": "house_1"}],
        recommendations=[{"threat": "house_1", "affected_objects": ["ghost_1"]}],
    )
    declared = {o["object_id"] for o in scene_bad["detected_objects"]}
    bad_refs = [
        aid for rec in scene_bad["recommendations"]
        for aid in (rec.get("affected_objects") or [])
        if aid not in declared
    ]
    assert bad_refs == ["ghost_1"]


# ---------------------------------------------------------------------------
# J3 — threat slot references a hazardous entity.
# ---------------------------------------------------------------------------
@pytest.mark.blocking
def test_j3_threat_references_hazardous_entity(main_module):
    scene = _scene(
        detected_objects=[
            {"object_id": "house_1", "state": "burning"},
            {"object_id": "person_1", "state": "stationary"},
        ],
        recommendations=[{"threat": "house_1", "affected_objects": ["person_1"]}],
    )
    by_id = {o["object_id"]: o for o in scene["detected_objects"]}
    for rec in scene["recommendations"]:
        threat = rec.get("threat", "")
        state = by_id.get(threat, {}).get("state", "")
        assert state in main_module.HAZARD_BEARING_STATES, (
            f"threat={threat} has state {state!r} which isn't hazard-bearing"
        )

    bad_scene = _scene(
        detected_objects=[{"object_id": "person_1", "state": "stationary"}],
        recommendations=[{"threat": "person_1", "affected_objects": []}],
    )
    by_id = {o["object_id"]: o for o in bad_scene["detected_objects"]}
    for rec in bad_scene["recommendations"]:
        state = by_id.get(rec["threat"], {}).get("state", "")
        assert state not in main_module.HAZARD_BEARING_STATES, (
            "validator should reject non-hazardous threat slot"
        )


# ---------------------------------------------------------------------------
# J4–J8: need captured Qwen output fixtures.
# ---------------------------------------------------------------------------
@pytest.mark.blocking
@pytest.mark.needs_fixtures
@pytest.mark.skip(reason="J4: needs captured Qwen output to assert self-targeting recs absent. Capture push_test scene outputs to tests/fixtures/sample_qwen_outputs/ then unskip.")
def test_j4_no_self_targeting_with_harm_effects():
    pass


@pytest.mark.blocking
@pytest.mark.needs_fixtures
@pytest.mark.skip(reason="J5: needs Qwen output (at_risk_objects + recommendations). Capture fixture and unskip.")
def test_j5_every_at_risk_appears_in_recommendations():
    pass


@pytest.mark.blocking
@pytest.mark.needs_fixtures
@pytest.mark.skip(reason="J6: needs Qwen output (recommendation quad + graph). Capture and unskip.")
def test_j6_recommendation_triple_consistency():
    pass


@pytest.mark.warn
@pytest.mark.needs_fixtures
@pytest.mark.skip(reason="J7: needs Qwen output to inspect duplicates. Capture and unskip.")
def test_j7_no_duplicate_recommendations():
    pass


@pytest.mark.human
@pytest.mark.skip(reason="J8: recommendation priority ordering is HUMAN-only per TESTS.md")
def test_j8_recommendation_rank_ordering():
    pass
