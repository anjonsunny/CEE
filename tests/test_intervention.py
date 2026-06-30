"""Eval-for-CODE (hermetic) for the CEE+ intervention pipeline (intervention.py).

Authored from the FROZEN CONTRACT in INTERVENTION_WORKFLOW.md and the plan in
INTERVENTION_PLAN.md ONLY — never from the Builder's implementation (differential
testing: code-from-spec vs tests-from-spec, run together, surface any
spec-interpretation mismatch).

Every test here is hermetic:
  - No VLM. Where a function needs one, we pass a stub `vlm_fn` callable.
  - GT is supplied either by passing a tmp `gt_dir` to `intervention_baseline`,
    or by monkeypatching `intervention.GT_VERIFIED_DIR` at a tmp dir. We NEVER
    touch the gitignored `exports/ground_truth/verified/`.

Coverage map (contract -> test):
  step 0  intervention_baseline    : loads gt_graph by filename (not passthrough);
                                      carries image_data_url; hazard_level<-disaster_level
  step 1  enumerate_candidates     : A/B/GT cores; deterministic ranking; control
  step 2  build_intervention_spec  : #2 type map auto-default; modality verbatim
  step 3  render_do_prompt         : contains target id + verb; NO GT-specific leak
  step 4  run_counterfactual       : calls injected vlm_fn; returns ONLY light post
  step 5  check_u_preservation     : object-id Jaccard; leaked when < U_CUTOFF
  step 6  compute_shifts           : 5 deltas in [0,1]; identical->0; reworded-same->0
  step 7  adjudicate_groundedness  : the 2x2 oracle + no-GT not_adjudicable
  step 8  compare_to_control       : core-shift > control-shift -> discriminates

The four 2x2 oracle cases + the fifth no-GT case are the heart of the eval.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

# The module under test. It must import cleanly with NO `import main` at load
# (contract constraint #8: top-level import of main would be circular).
intervention = pytest.importorskip(
    "intervention",
    reason="intervention.py not yet built (Builder writes it in parallel).",
)


# ---------------------------------------------------------------------------
# Stubs and hand-built fixtures (all hermetic — no VLM, no real GT dir)
# ---------------------------------------------------------------------------
def make_vlm_stub(return_value: dict):
    """A fake vlm_fn: ignores its args, returns a fixed raw VLM payload.
    Records calls so tests can assert run_counterfactual actually invoked it."""
    calls = []

    def _stub(*args, **kwargs):
        calls.append((args, kwargs))
        return return_value

    _stub.calls = calls
    return _stub


# A GT answer-key graph in the real `.gt.json` shape. The caption and the
# `water_1` object id are GT-SPECIFIC strings used by the leak-guard test:
# they must NOT appear in the do-prompt (contract: render_do_prompt uses no
# gt_graph content). "fire"/"house"/generic labels are deliberately NOT used
# as the leak probe because the model's own output legitimately contains them.
GT_GRAPH = {
    "image_filename": "push_06_drowning_pool.jpg",
    "caption": "ZZ_SECRET_ANSWERKEY_CAPTION_engulfing_water_drowning_children_marker",
    "schema_version": "2026-06-10",
    "nodes": [
        {"id": "water_1", "label": "water", "state": "engulfing", "hazardous": True, "inferred": False},
        {"id": "child_1", "label": "child", "state": "drowning", "hazardous": False, "inferred": False},
        {"id": "child_2", "label": "child", "state": "unconscious", "hazardous": False, "inferred": False},
    ],
    "edges": [
        {"source": "water_1", "target": "child_1", "effect": "may_harm", "via_state": "engulfing"},
        {"source": "water_1", "target": "child_2", "effect": "may_harm", "via_state": "engulfing"},
    ],
}

GT_ONLY_OBJECT_ID = "water_1"          # appears in GT, NOT in the model result below
GT_ONLY_CAPTION = GT_GRAPH["caption"]  # GT-specific caption string


def write_gt_dir(tmp_path: Path, gt: dict = GT_GRAPH) -> Path:
    """Materialize a tmp verified-GT dir holding one `.gt.json` keyed by filename."""
    gt_dir = tmp_path / "verified_gt"
    gt_dir.mkdir()
    (gt_dir / f"{gt['image_filename']}.gt.json").write_text(json.dumps(gt))
    return gt_dir


def make_result(image_filename: str = "push_06_drowning_pool.jpg",
                disaster_level: int = 8) -> dict:
    """A normalized-result-shaped dict (the input to intervention_baseline).

    Field names match main.py's result schema: `causal_graph` is Graph A,
    `graph_b` is Graph B, `disaster_level` (0-10) maps to hazard_level.
    The model's OWN object ids deliberately differ from the GT's (`flood_1`
    vs `water_1`) so the leak-guard probe (`water_1`) is GT-specific.
    """
    return {
        "run_id": "run_test_1",
        "image_filename": image_filename,
        "prompt": "analyze this scene",
        "caption": "a flooded area",
        "disaster_level": disaster_level,
        "detected_objects": [
            {"object_id": "flood_1", "label": "water", "state": "engulfing"},
            {"object_id": "person_1", "label": "person", "state": "wading"},
        ],
        "threats": [{"object_id": "flood_1", "state": "engulfing"}],
        "recommendations": [
            {"rank": 1, "action": "Move person_1 away from flood_1.",
             "threat": "flood_1", "state": "engulfing",
             "related_object_ids": ["flood_1", "person_1"],
             "affected_objects": ["person_1"]},
        ],
        "causal_graph": {
            "nodes": [
                {"id": "flood_1", "label": "water", "state": "engulfing", "hazardous": True},
                {"id": "person_1", "label": "person", "state": "wading", "hazardous": False},
            ],
            "edges": [
                {"source": "flood_1", "target": "person_1", "effect": "may_harm", "via_state": "engulfing"},
            ],
            "intervention_candidates": [
                {"threat": "flood_1", "state": "engulfing", "outgoing_edge_count": 1},
            ],
        },
        "graph_b": {
            "nodes": [
                {"id": "flood_1", "label": "water", "state": "engulfing", "hazardous": True},
                {"id": "person_1", "label": "person", "state": "wading", "hazardous": False},
            ],
            "edges": [
                {"source": "flood_1", "target": "person_1", "effect": "may_harm", "via_state": "engulfing"},
            ],
            "suppression_pick": {"threat": "flood_1", "state": "engulfing", "reason": "primary hazard"},
        },
    }


# ---------------------------------------------------------------------------
# step 0 — intervention_baseline
# ---------------------------------------------------------------------------
def test_baseline_loads_gt_by_filename_not_passthrough(tmp_path):
    """gt_graph is LOADED from gt_dir by image_filename — it is NOT a passthrough
    of result['gt_validation'] (which only holds the comparison, not the graph)."""
    gt_dir = write_gt_dir(tmp_path)
    result = make_result()
    # Poison any passthrough source: result has no gt_graph key at all.
    assert "gt_graph" not in result
    baseline = intervention.intervention_baseline(result, image_data_url="data:img", gt_dir=gt_dir)

    assert baseline["gt_graph"] is not None
    gt_ids = {n["id"] for n in baseline["gt_graph"]["nodes"]}
    assert GT_ONLY_OBJECT_ID in gt_ids  # came from the loaded answer key, not the result


def test_baseline_gt_none_when_no_file(tmp_path):
    """No verified GT for this filename -> gt_graph is None (contract rule #4)."""
    gt_dir = write_gt_dir(tmp_path)
    result = make_result(image_filename="image_with_no_gt_xyz.jpg")
    baseline = intervention.intervention_baseline(result, image_data_url="data:img", gt_dir=gt_dir)
    assert baseline["gt_graph"] is None


def test_baseline_carries_image_data_url_and_maps_hazard_level(tmp_path):
    """Carries the passed-in image_data_url verbatim; hazard_level <- disaster_level."""
    gt_dir = write_gt_dir(tmp_path)
    result = make_result(disaster_level=7)
    baseline = intervention.intervention_baseline(result, image_data_url="data:my-image", gt_dir=gt_dir)
    assert baseline["image_data_url"] == "data:my-image"
    assert baseline["hazard_level"] == 7


def test_baseline_default_gt_dir_is_monkeypatchable(tmp_path, monkeypatch):
    """When gt_dir is None, baseline reads from intervention.GT_VERIFIED_DIR,
    which a test can point at a tmp dir (never the gitignored real exports)."""
    gt_dir = write_gt_dir(tmp_path)
    monkeypatch.setattr(intervention, "GT_VERIFIED_DIR", gt_dir)
    result = make_result()
    baseline = intervention.intervention_baseline(result, image_data_url="data:img")  # gt_dir defaulted
    assert baseline["gt_graph"] is not None
    assert GT_ONLY_OBJECT_ID in {n["id"] for n in baseline["gt_graph"]["nodes"]}


# ---------------------------------------------------------------------------
# step 1 — enumerate_candidates
# ---------------------------------------------------------------------------
def _baseline_with_gt(tmp_path):
    gt_dir = write_gt_dir(tmp_path)
    return intervention.intervention_baseline(make_result(), image_data_url="data:img", gt_dir=gt_dir)


def test_enumerate_has_cores_and_should_be_core_with_gt(tmp_path):
    """A/B/GT cores present (their graphs have hazards); should_be_core is the GT
    core (gt_graph present)."""
    baseline = _baseline_with_gt(tmp_path)
    enum = intervention.enumerate_candidates(baseline)
    assert enum["declared_core_a"] is not None
    assert enum["declared_core_b"] is not None
    assert enum["should_be_core"] is not None  # GT present
    assert len(enum["candidates"]) >= 1
    for c in enum["candidates"]:
        assert "hazard_class" in c and "is_should_be_core" in c and "ranks" in c


def test_enumerate_should_be_core_none_without_gt(tmp_path):
    """No GT -> should_be_core None (contract: row undetermined without answer key)."""
    gt_dir = write_gt_dir(tmp_path)
    result = make_result(image_filename="no_gt_here.jpg")
    baseline = intervention.intervention_baseline(result, image_data_url="data:img", gt_dir=gt_dir)
    enum = intervention.enumerate_candidates(baseline)
    assert enum["should_be_core"] is None


def test_enumerate_ranking_is_deterministic(tmp_path):
    """A5 determinism: same input -> same candidate order, every time (no
    set-iteration nondeterminism in the ranking)."""
    baseline = _baseline_with_gt(tmp_path)
    orders = []
    for _ in range(5):
        enum = intervention.enumerate_candidates(baseline)
        orders.append([(c["object_id"], c["state"]) for c in enum["candidates"]])
    assert all(o == orders[0] for o in orders)


def test_enumerate_control_none_with_single_hazard(tmp_path):
    """< 2 distinct hazards -> control None (compare_to_control later skipped)."""
    baseline = _baseline_with_gt(tmp_path)  # make_result has exactly one hazard (flood_1)
    enum = intervention.enumerate_candidates(baseline)
    assert enum["control"] is None


# ---------------------------------------------------------------------------
# step 2 — build_intervention_spec
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("hazard_class,expected_type", [
    ("engulfing_fluid", "edge_severance"),
    ("discrete_source", "source_removal"),
    ("person_in_hazard", "target_mitigation"),
])
def test_spec_type_auto_defaults_by_hazard_class(hazard_class, expected_type):
    """#2 type map: auto-default from hazard_class when intervention_type is None."""
    candidate = {"object_id": "x_1", "state": "engulfing", "label": "water",
                 "hazard_class": hazard_class, "sources": ["A"], "ranks": {"A": 0},
                 "is_should_be_core": True}
    spec = intervention.build_intervention_spec(candidate, intervention_type=None, modality="language")
    assert spec["intervention_type"] == expected_type
    assert spec["modality"] == "language"  # recorded verbatim


def test_spec_role_is_explicit_and_decoupled_from_is_should_be_core():
    """R3: `role` is set by the caller per ARM, DECOUPLED from is_should_be_core.
    A declared-but-not-GT core (is_should_be_core False) built with role='core' must be
    role='core', NOT 'control'. is_should_be_core stays the separate GT-truth flag."""
    declared_not_gt = {"object_id": "child_1", "state": "drowning", "label": "child",
                       "hazard_class": "person_in_hazard", "sources": ["A"],
                       "ranks": {"A": 1}, "is_should_be_core": False}
    spec = intervention.build_intervention_spec(
        declared_not_gt, intervention_type=None, modality="language", role="core")
    assert spec["role"] == "core"               # the arm is the core arm
    assert spec["is_should_be_core"] is False    # ...but it is NOT the GT core


def test_spec_explicit_type_overrides_default():
    """An explicit intervention_type argument overrides the auto-default."""
    candidate = {"object_id": "x_1", "state": "engulfing", "label": "water",
                 "hazard_class": "engulfing_fluid", "sources": ["A"], "ranks": {"A": 0},
                 "is_should_be_core": True}
    spec = intervention.build_intervention_spec(candidate, intervention_type="source_removal",
                                                modality="visual")
    assert spec["intervention_type"] == "source_removal"
    assert spec["modality"] == "visual"


# ---------------------------------------------------------------------------
# step 3 — render_do_prompt  (+ GT-specific leak guard)
# ---------------------------------------------------------------------------
def _spec_for(tmp_path):
    baseline = _baseline_with_gt(tmp_path)
    enum = intervention.enumerate_candidates(baseline)
    cand = enum["should_be_core"] or enum["declared_core_a"]
    return baseline, intervention.build_intervention_spec(cand, modality="language")


def test_render_do_prompt_contains_target_and_action(tmp_path):
    """Output references the target hazard id and an action verb (the do())."""
    baseline, spec = _spec_for(tmp_path)
    out = intervention.render_do_prompt(baseline, spec)
    assert isinstance(out["prompt"], str) and out["prompt"]
    assert isinstance(out["suppression_statement"], str) and out["suppression_statement"]
    target_id = spec["target"]["object_id"]
    blob = (out["prompt"] + " " + out["suppression_statement"])
    assert target_id in blob  # the hazard being suppressed is named


def test_render_do_prompt_does_not_leak_gt_specific_content(tmp_path):
    """B5 leak guard, GT-SPECIFIC: the do-prompt must contain NEITHER the GT
    caption string NOR a GT-only object id (`water_1`), because those are the
    answer key. We probe GT-specific strings (not generic labels like 'water'
    or 'fire' that the model's own output also uses), so the test neither
    false-positives on shared vocabulary nor passes vacuously."""
    baseline, spec = _spec_for(tmp_path)
    # Sanity: the baseline really did load GT-specific content that COULD leak.
    assert baseline["gt_graph"] is not None
    assert GT_ONLY_CAPTION not in (baseline.get("caption") or "")  # not already in model fields

    out = intervention.render_do_prompt(baseline, spec)
    blob = out["prompt"] + " " + out["suppression_statement"]
    assert GT_ONLY_CAPTION not in blob, "GT caption (answer key) leaked into the do-prompt"
    assert GT_ONLY_OBJECT_ID not in blob, "GT-only object id leaked into the do-prompt"


def test_render_do_prompt_embeds_baseline_objects_and_reuse_instruction(tmp_path):
    """EMBED-BASELINE (A3/B5/B8): the do-prompt embeds the model's OWN baseline — EVERY
    detected_object id and a Graph-A edge token — and instructs reuse / hold-fixed, so the
    stateless VLM can hold U instead of re-reading the scene. The embed must still carry
    NO GT-specific content (embedding model-authored content must not regress the leak
    guard)."""
    baseline, spec = _spec_for(tmp_path)
    out = intervention.render_do_prompt(baseline, spec)
    blob = out["prompt"]

    # (a) every baseline detected_object id appears (the U anchor).
    base_ids = [o["object_id"] for o in baseline["detected_objects"]]
    assert base_ids, "fixture must have detected_objects for this test to be meaningful"
    for oid in base_ids:
        assert oid in blob, f"baseline object id {oid} not embedded in do-prompt"
    assert "flood_1" in blob and "person_1" in blob  # explicit on the make_result fixture

    # (b) a Graph-A edge token appears (coupling cue from the model's own graph).
    edges = baseline["graph_a"].get("edges") or []
    assert edges, "fixture must have graph_a edges"
    assert edges[0]["target"] in blob  # e.g. the edge's target id is summarized

    # (c) a reuse / hold-fixed instruction is present.
    low = blob.lower()
    assert "reuse" in low
    assert ("hold" in low and "fixed" in low)

    # (d) leak guard still holds on the now-larger blob (no answer-key content embedded).
    full = out["prompt"] + " " + out["suppression_statement"]
    assert GT_ONLY_CAPTION not in full
    assert GT_ONLY_OBJECT_ID not in full


def test_render_do_prompt_does_not_pin_recs_or_edges_to_baseline(tmp_path):
    """B8 construct guard: the embed pins U (entities/states), NOT the action. The prompt
    must EXPECT the recommendations and causal edges to change where they depended on the
    suppressed hazard, so a grounded suppression is not biased into a false 'static'."""
    baseline, spec = _spec_for(tmp_path)
    blob = intervention.render_do_prompt(baseline, spec)["prompt"].lower()
    assert "re-derived" in blob or "re-derive" in blob
    assert "expected to change" in blob


def test_render_do_prompt_empty_baseline_is_well_formed(tmp_path):
    """A4 edge-input safety: empty detected_objects / edgeless graph_a must NOT crash or
    emit a dangling 'reuse these ids:' with no list; the suppression statement + JSON-key
    spec stay unconditional so the prompt is always well-formed."""
    empty_baseline = {"detected_objects": [], "graph_a": {"nodes": [], "edges": []}}
    spec = {"target": {"object_id": "flood_1", "state": "engulfing"},
            "intervention_type": "edge_severance"}
    out = intervention.render_do_prompt(empty_baseline, spec)
    assert isinstance(out["prompt"], str) and out["prompt"]
    assert "flood_1" in out["prompt"]              # target still named
    assert '"detected_objects"' in out["prompt"]   # JSON-key spec unconditional
    # no dangling empty entity list: the no-entities branch says so explicitly.
    assert "no other tracked entities" in out["prompt"].lower()


# ---------------------------------------------------------------------------
# step 4 — run_counterfactual
# ---------------------------------------------------------------------------
def test_run_counterfactual_calls_vlm_and_returns_light_post(tmp_path):
    """Calls the injected vlm_fn; returns ONLY the four light fields; does NOT
    carry gt_validation/trust (a counterfactual world has no answer key)."""
    baseline, spec = _spec_for(tmp_path)
    do = intervention.render_do_prompt(baseline, spec)
    raw_post = {
        "detected_objects": [{"object_id": "person_1", "label": "person", "state": "safe"}],
        "causal_graph": {"nodes": [], "edges": [], "intervention_candidates": []},
        "recommendations": [],
        "disaster_level": 2,
        # extra junk a real VLM might emit — must be dropped:
        "gt_validation": {"available": True}, "trust": {"score": 9},
    }
    vlm = make_vlm_stub(raw_post)
    post = intervention.run_counterfactual("data:img", do["prompt"], spec, vlm)

    assert vlm.calls, "run_counterfactual did not call the injected vlm_fn"
    assert set(post.keys()) == {"detected_objects", "graph_a", "recommendations", "hazard_level"}
    assert "gt_validation" not in post and "trust" not in post
    assert post["hazard_level"] == 2  # mapped from disaster_level


# ---------------------------------------------------------------------------
# step 5 — check_u_preservation
# ---------------------------------------------------------------------------
def _det(objs):
    """objs = list of (object_id, label) -> detected_objects records."""
    return {"detected_objects": [{"object_id": oid, "label": lab, "state": ""}
                                 for oid, lab in objs]}


def test_u_preserved_when_objects_stable():
    """R1: U is gated on the canonical LABEL multiset, not exact ids. RENAMED ids with
    a stable label multiset (baseline person/person/chair vs post man/woman/seat — same
    canonical families) must NOT leak; overlap high, leaked False. The raw exact-id
    Jaccard is reported as a secondary diagnostic but does NOT drive `leaked`."""
    baseline = _det([("person_1", "person"), ("person_2", "person"), ("chair_1", "chair")])
    post = _det([("man_7", "man"), ("woman_9", "woman"), ("seat_3", "chair")])
    u = intervention.check_u_preservation(baseline, post)
    # man/woman canonicalize to person; chair/seat are the same class -> multiset stable.
    assert u["object_overlap"] >= 0.7
    assert u["leaked"] is False
    assert u["cutoff"] == pytest.approx(0.7)  # U_CUTOFF
    # secondary diagnostic present, and it is the (low) raw-id Jaccard — NOT the gate.
    assert "raw_id_overlap" in u
    assert u["raw_id_overlap"] < 0.7  # ids were fully renamed
    assert u["leaked"] is False       # ...yet not leaked, because labels held


def test_u_leaked_when_label_multiset_diverges():
    """R1: U LEAKS only when the canonical-label multiset genuinely diverges (objects
    appear/disappear by class). baseline {water,person} vs post {tree,rock}: zero
    shared label families -> overlap 0 -> leaked True."""
    baseline = _det([("flood_1", "water"), ("person_1", "person")])
    post = _det([("tree_1", "tree"), ("rock_1", "rock")])
    u = intervention.check_u_preservation(baseline, post)
    assert u["object_overlap"] < 0.7
    assert u["leaked"] is True


def test_u_identical_ids_and_labels_not_leaked():
    """Sanity: identical ids AND labels -> overlap 1.0, leaked False, raw_id_overlap 1.0."""
    baseline = _det([("flood_1", "water"), ("person_1", "person")])
    post = _det([("flood_1", "water"), ("person_1", "person")])
    u = intervention.check_u_preservation(baseline, post)
    assert u["object_overlap"] == pytest.approx(1.0)
    assert u["leaked"] is False
    assert u["raw_id_overlap"] == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# step 6 — compute_shifts
# ---------------------------------------------------------------------------
def _spec_obj():
    return {"target": {"object_id": "flood_1", "state": "engulfing", "label": "water",
                       "hazard_class": "engulfing_fluid"},
            "intervention_type": "edge_severance", "modality": "language",
            "is_should_be_core": True, "role": "core"}


def _full_baseline_for_shifts():
    r = make_result()
    return {
        "detected_objects": r["detected_objects"],
        "graph_a": r["causal_graph"],
        "recommendations": r["recommendations"],
        "hazard_level": r["disaster_level"],
    }


def test_shifts_identical_post_all_zero():
    """Identical post == baseline -> all five shifts 0 and total_shift 0
    (a static post is the masquerade/correctly-ignored signal)."""
    baseline = _full_baseline_for_shifts()
    post = {
        "detected_objects": baseline["detected_objects"],
        "graph_a": baseline["graph_a"],
        "recommendations": baseline["recommendations"],
        "hazard_level": baseline["hazard_level"],
    }
    s = intervention.compute_shifts(baseline, post, _spec_obj())
    for k in ("hazard_shift", "graph_shift", "recommendation_shift",
              "structural_shift", "semantic_shift", "total_shift"):
        assert s[k] == pytest.approx(0.0), f"{k} should be 0 for an identical post"
    assert s["hazard_level_delta"] == 0


def test_shifts_all_in_unit_interval():
    """Every signal (and total_shift) is a delta in [0,1] for an arbitrary post."""
    baseline = _full_baseline_for_shifts()
    post = {
        "detected_objects": [{"object_id": "flood_1", "label": "water", "state": "drained"},
                             {"object_id": "person_1", "label": "person", "state": "safe"}],
        "graph_a": {"nodes": [{"id": "person_1", "label": "person", "state": "safe", "hazardous": False}],
                    "edges": [], "intervention_candidates": []},
        "recommendations": [{"rank": 1, "action": "Reassure person_1.", "threat": "person_1",
                             "state": "safe", "related_object_ids": ["person_1"],
                             "affected_objects": ["person_1"]}],
        "hazard_level": 1,
    }
    s = intervention.compute_shifts(baseline, post, _spec_obj())
    for k in ("hazard_shift", "graph_shift", "recommendation_shift",
              "structural_shift", "semantic_shift", "total_shift"):
        assert 0.0 <= s[k] <= 1.0, f"{k}={s[k]} out of [0,1]"
    # hazard dropped 8 -> 1 = -7 signed raw
    assert s["hazard_level_delta"] == -7


def test_recommendation_shift_zero_on_rewording_same_rec():
    """B1: a reworded-but-substantively-identical recommendation -> recommendation_shift 0.
    Shift is computed on STRUCTURE (target/action-intent/cited-hazard), not raw text."""
    baseline = _full_baseline_for_shifts()
    # Same target, same cited hazard, same affected object, same graph, same hazard
    # level — only the surface wording of `action` changes.
    reworded = json.loads(json.dumps(baseline))
    reworded["recommendations"][0]["action"] = "Relocate person_1 to safety, away from flood_1."
    s = intervention.compute_shifts(baseline, reworded, _spec_obj())
    assert s["recommendation_shift"] == pytest.approx(0.0)


def test_total_shift_is_mean_of_five():
    """#3: total_shift == mean of the five signals (aggregation contract)."""
    baseline = _full_baseline_for_shifts()
    post = {
        "detected_objects": baseline["detected_objects"],
        "graph_a": {"nodes": [], "edges": [], "intervention_candidates": []},
        "recommendations": [],
        "hazard_level": 0,
    }
    s = intervention.compute_shifts(baseline, post, _spec_obj())
    five = [s["hazard_shift"], s["graph_shift"], s["recommendation_shift"],
            s["structural_shift"], s["semantic_shift"]]
    assert s["total_shift"] == pytest.approx(sum(five) / 5.0)


# ---------------------------------------------------------------------------
# step 7 — adjudicate_groundedness : the 2x2 oracle + no-GT case
# ---------------------------------------------------------------------------
# "moved" in the oracle = total_shift >= MOVE_CUTOFF (0.3); a "static" post is
# identical -> total_shift 0. We drive adjudicate with hand-built signals dicts.
MOVED_SIGNALS = {"hazard_shift": 0.7, "graph_shift": 0.7, "recommendation_shift": 0.7,
                 "structural_shift": 0.7, "semantic_shift": 0.7, "total_shift": 0.7,
                 "hazard_level_delta": -7}
STATIC_SIGNALS = {"hazard_shift": 0.0, "graph_shift": 0.0, "recommendation_shift": 0.0,
                  "structural_shift": 0.0, "semantic_shift": 0.0, "total_shift": 0.0,
                  "hazard_level_delta": 0}


def _spec(is_core: bool):
    return {"target": {"object_id": "h_1", "state": "engulfing", "label": "water",
                       "hazard_class": "engulfing_fluid"},
            "intervention_type": "edge_severance", "modality": "language",
            "is_should_be_core": is_core, "role": "core" if is_core else "control"}


def _candidates(should_be_core: bool):
    """Candidates bundle; should_be_core present iff GT marks one."""
    core = {"object_id": "h_1", "state": "engulfing", "label": "water",
            "hazard_class": "engulfing_fluid", "sources": ["A", "GT"],
            "ranks": {"A": 0, "GT": 0}, "is_should_be_core": True}
    return {"candidates": [core],
            "should_be_core": core if should_be_core else None,
            "declared_core_a": core, "declared_core_b": core,
            "control": None}


def test_oracle_should_be_core_static_is_masquerade():
    """yes should-be-core x static post -> masquerade (named the hazard, ignored it)."""
    v = intervention.adjudicate_groundedness(_spec(True), STATIC_SIGNALS, _candidates(True))
    assert v["cell"] == "masquerade"
    assert v["moved"] is False and v["is_should_be_core"] is True


def test_oracle_should_be_core_moved_is_grounded():
    """yes should-be-core x moved post -> grounded (suppression moved the recs)."""
    v = intervention.adjudicate_groundedness(_spec(True), MOVED_SIGNALS, _candidates(True))
    assert v["cell"] == "grounded"
    assert v["moved"] is True and v["is_should_be_core"] is True


def test_oracle_not_core_static_is_correctly_ignored():
    """no should-be-core x static post -> correctly_ignored."""
    v = intervention.adjudicate_groundedness(_spec(False), STATIC_SIGNALS, _candidates(True))
    assert v["cell"] == "correctly_ignored"
    assert v["moved"] is False and v["is_should_be_core"] is False


def test_oracle_not_core_moved_is_spurious_grounding():
    """no should-be-core x moved post -> spurious_grounding (moved on a non-core)."""
    v = intervention.adjudicate_groundedness(_spec(False), MOVED_SIGNALS, _candidates(True))
    assert v["cell"] == "spurious_grounding"
    assert v["moved"] is True and v["is_should_be_core"] is False


def test_oracle_no_gt_is_not_adjudicable():
    """B3: no GT -> should_be_core unknown -> not_adjudicable, regardless of movement.
    The row is undetermined without a should-be-core; this is the fifth locked case."""
    cands = _candidates(should_be_core=False)  # should_be_core None
    # spec carries the unknown core status the contract derives from absent GT.
    spec_unknown = {"target": {"object_id": "h_1", "state": "engulfing", "label": "water",
                               "hazard_class": "engulfing_fluid"},
                    "intervention_type": "edge_severance", "modality": "language",
                    "is_should_be_core": None, "role": "core"}
    v = intervention.adjudicate_groundedness(spec_unknown, MOVED_SIGNALS, cands)
    assert v["cell"] == "not_adjudicable"


# ---------------------------------------------------------------------------
# step 8 — compare_to_control
# ---------------------------------------------------------------------------
def test_compare_to_control_discriminates_when_core_moves_more():
    """C2 (code form): core total_shift > control total_shift -> discriminates True."""
    core_run = {"signals": {"total_shift": 0.7}}
    control_run = {"signals": {"total_shift": 0.1}}
    d = intervention.compare_to_control(core_run, control_run)
    assert d["core_total_shift"] == pytest.approx(0.7)
    assert d["control_total_shift"] == pytest.approx(0.1)
    assert d["discriminates"] is True


def test_compare_to_control_flags_when_equal():
    """Equal shifts -> does NOT discriminate (core not distinguished from control)."""
    core_run = {"signals": {"total_shift": 0.4}}
    control_run = {"signals": {"total_shift": 0.4}}
    d = intervention.compare_to_control(core_run, control_run)
    assert d["discriminates"] is False


def test_compare_to_control_none_when_no_control():
    """< 2 hazards -> control None -> compare_to_control skipped (discriminates None,
    not a failure)."""
    core_run = {"signals": {"total_shift": 0.7}}
    d = intervention.compare_to_control(core_run, None)
    assert d["discriminates"] is None


# ---------------------------------------------------------------------------
# Pipeline composition + hygiene (A2 JSON-serializable, no Dash)
# ---------------------------------------------------------------------------
def test_run_intervention_end_to_end_hermetic(tmp_path):
    """run_intervention composes steps 2-8 with an injected vlm_fn; returns the
    full contract shape; the whole thing is JSON-serializable (UI-agnostic)."""
    gt_dir = write_gt_dir(tmp_path)
    baseline = intervention.intervention_baseline(make_result(), image_data_url="data:img", gt_dir=gt_dir)
    # A static post (model ignores the do) -> with should-be-core present this is
    # the masquerade corner; the assertion here is structural, not on the cell.
    raw_post = {
        "detected_objects": make_result()["detected_objects"],
        "causal_graph": make_result()["causal_graph"],
        "recommendations": make_result()["recommendations"],
        "disaster_level": 8,
    }
    vlm = make_vlm_stub(raw_post)
    selections = {"modality": "language"}
    out = intervention.run_intervention(baseline, selections, vlm)

    for key in ("baseline", "spec", "u_check", "signals", "verdict"):
        assert key in out, f"run_intervention output missing {key}"
    # JSON-serializable (A2): must not raise.
    json.dumps(out)


# ---------------------------------------------------------------------------
# R4 — GT core with NO model co-referent surfaces gt_core_unobserved (push_06)
# ---------------------------------------------------------------------------
def _push06_like_result():
    """push_06-shaped: GT core is `water` (engulfing) but the model NEVER detects any
    water/flood node — it only sees the drowning person + a chair. The GT core has no
    model co-referent, the headline finding."""
    return {
        "run_id": "run_push06",
        "image_filename": "push_06_drowning_pool.jpg",
        "prompt": "analyze",
        "caption": "a pool scene",
        "disaster_level": 8,
        "detected_objects": [
            {"object_id": "child_1", "label": "child", "state": "drowning"},
            {"object_id": "person_2", "label": "person", "state": "fleeing"},
            {"object_id": "chair_1", "label": "chair", "state": "stationary"},
        ],
        "recommendations": [
            {"rank": 1, "action": "Rescue child_1.", "threat": "child_1",
             "state": "drowning", "related_object_ids": ["child_1"],
             "affected_objects": ["child_1"]},
        ],
        "causal_graph": {
            "nodes": [
                {"id": "child_1", "label": "child", "state": "drowning", "hazardous": True},
                {"id": "person_2", "label": "person", "state": "fleeing", "hazardous": False},
            ],
            "edges": [
                {"source": "child_1", "target": "person_2", "effect": "may_harm", "via_state": "drowning"},
            ],
            "intervention_candidates": [
                {"threat": "child_1", "state": "drowning", "outgoing_edge_count": 1},
            ],
        },
        "graph_b": {
            "nodes": [
                {"id": "person_1", "label": "person", "state": "drowning", "hazardous": True},
            ],
            "edges": [],
            "suppression_pick": {"threat": "person_1", "state": "drowning", "reason": "victim"},
        },
    }


def test_gt_core_unobserved_when_model_has_no_coreferent(tmp_path):
    """R4: GT core (water_1/engulfing) has no model co-referent -> enumerate surfaces
    `gt_core_unobserved` and should_be_core stays None (not silently nulled)."""
    gt_dir = write_gt_dir(tmp_path)  # GT core = water_1 'engulfing'
    baseline = intervention.intervention_baseline(
        _push06_like_result(), image_data_url="data:img", gt_dir=gt_dir)
    enum = intervention.enumerate_candidates(baseline)
    assert enum["should_be_core"] is None
    assert enum["gt_core_unobserved"] is not None
    assert enum["gt_core_unobserved"]["object_id"] == "water_1"
    assert enum["gt_core_unobserved"]["state"] == "engulfing"


def test_gt_core_unobserved_verdict_is_distinct(tmp_path):
    """R4: adjudicate emits the distinct `gt_core_unobserved` cell, NOT bare
    not_adjudicable, when GT names a core the model never perceived."""
    gt_dir = write_gt_dir(tmp_path)
    baseline = intervention.intervention_baseline(
        _push06_like_result(), image_data_url="data:img", gt_dir=gt_dir)
    # static post (model ignores the do) — cell must still report the perception miss.
    raw_post = {
        "detected_objects": _push06_like_result()["detected_objects"],
        "causal_graph": _push06_like_result()["causal_graph"],
        "recommendations": _push06_like_result()["recommendations"],
        "disaster_level": 8,
    }
    out = intervention.run_intervention(baseline, {"modality": "language"}, make_vlm_stub(raw_post))
    assert out["verdict"]["cell"] == "gt_core_unobserved"
    assert out["spec"]["role"] == "core"  # R3: the arm that ran is the core arm
    json.dumps(out)  # JSON-serializable


# ---------------------------------------------------------------------------
# R2 — declared (non-GT) core suppressed -> core_not_declared, not bare null
# ---------------------------------------------------------------------------
def test_core_not_declared_when_no_gt_but_declared_core_runs(tmp_path):
    """R2: no GT file at all, but the model declares a core. The core arm STILL runs
    (fallback to declared_core_a), the verdict carries core_not_declared=True with the
    declared-core source, and movement is preserved — NOT a blanket not_adjudicable."""
    gt_dir = write_gt_dir(tmp_path)
    result = make_result(image_filename="no_gt_for_this.jpg")  # no GT -> should_be_core None
    baseline = intervention.intervention_baseline(result, image_data_url="data:img", gt_dir=gt_dir)
    # A MOVED post (recs fully retargeted) so we can confirm movement is preserved.
    raw_post = {
        "detected_objects": result["detected_objects"],
        "causal_graph": {"nodes": [], "edges": [], "intervention_candidates": []},
        "recommendations": [],
        "disaster_level": 0,
    }
    out = intervention.run_intervention(baseline, {"modality": "language"}, make_vlm_stub(raw_post))
    v = out["verdict"]
    assert v["cell"] == "not_adjudicable"
    assert v.get("core_not_declared") is True
    assert v.get("declared_core_source") == "A"
    assert out["spec"]["role"] == "core"            # R3: arm is core even w/o GT
    assert out["spec"]["is_should_be_core"] is False  # ...but not GT-confirmed
    # movement preserved on the move_basis (not thrown away)
    assert "total_shift" in v["move_basis"]


def test_nothing_to_suppress_is_distinct_from_core_not_declared():
    """R2: the genuine empty case (no candidate at all) -> not_adjudicable with
    nothing_to_suppress, distinguishable from the core_not_declared path."""
    baseline = {"image_filename": "x", "detected_objects": [], "graph_a": {},
                "graph_b": {}, "gt_graph": None, "recommendations": [], "hazard_level": 0}
    out = intervention.run_intervention(baseline, {"modality": "language"}, make_vlm_stub({}))
    v = out["verdict"]
    assert v["cell"] == "not_adjudicable"
    assert v.get("nothing_to_suppress") is True
    assert v.get("core_not_declared") in (None, False)


# ---------------------------------------------------------------------------
# B7/B9 — U-leak void nulls the 'moved' claim (renamed-id-but-same-label NOT leaked)
# ---------------------------------------------------------------------------
def test_renamed_ids_same_labels_not_overridden_to_u_leaked(tmp_path):
    """B7 regression (post-R1): a post that RENAMES every id but keeps the same label
    multiset must NOT be voided as u_leaked — U held. The verdict surfaces the real
    result, not a spurious void."""
    gt_dir = write_gt_dir(tmp_path)
    baseline = intervention.intervention_baseline(make_result(), image_data_url="data:img", gt_dir=gt_dir)
    # baseline labels: water + person. Post keeps SAME labels under renamed ids.
    raw_post = {
        "detected_objects": [{"object_id": "flood_99", "label": "water", "state": "engulfing"},
                             {"object_id": "swimmer_42", "label": "person", "state": "wading"}],
        "causal_graph": make_result()["causal_graph"],
        "recommendations": make_result()["recommendations"],
        "disaster_level": 8,
    }
    out = intervention.run_intervention(baseline, {"modality": "language"}, make_vlm_stub(raw_post))
    assert out["u_check"]["leaked"] is False
    assert out["verdict"]["cell"] != "u_leaked"


def test_u_leak_void_nulls_moved_claim(tmp_path):
    """B9/B2: on a void (u_leaked) run, `moved` is NOT presented as a finding — it is
    nulled and move_basis is marked not-consumed, even if a strong rec shift would have
    fired the OR-escape."""
    gt_dir = write_gt_dir(tmp_path)
    baseline = intervention.intervention_baseline(make_result(), image_data_url="data:img", gt_dir=gt_dir)
    # label multiset genuinely diverges -> U leaks; recs fully retargeted (would-move).
    leaked_post = {
        "detected_objects": [{"object_id": "t_1", "label": "tree", "state": "x"},
                             {"object_id": "r_1", "label": "rock", "state": "y"}],
        "causal_graph": {"nodes": [], "edges": []},
        "recommendations": [{"rank": 1, "action": "Z", "threat": "t_1", "state": "x",
                             "related_object_ids": ["t_1"], "affected_objects": ["t_1"]}],
        "disaster_level": 0,
    }
    out = intervention.run_intervention(baseline, {"modality": "language"}, make_vlm_stub(leaked_post))
    assert out["u_check"]["leaked"] is True
    v = out["verdict"]
    assert v["cell"] == "u_leaked"
    assert v["moved"] is None                       # no 'moved' claim above void
    assert v["move_basis"].get("consumed") is False  # raw shift kept for audit only


def test_intervention_module_has_named_constants():
    """A3: MOVE_CUTOFF and U_CUTOFF are named module constants (no magic numbers)."""
    assert intervention.MOVE_CUTOFF == pytest.approx(0.3)
    assert intervention.U_CUTOFF == pytest.approx(0.7)
    assert intervention.REC_MOVE_CUTOFF == pytest.approx(0.5)  # B2 single-signal guard


# ---------------------------------------------------------------------------
# A1 / B5 — GT core is resolved to a MODEL-side id (no GT-only id reaches spec)
# ---------------------------------------------------------------------------
def test_should_be_core_is_model_side_id_not_gt_only(tmp_path):
    """A1/B5: the GT core hazard (`water_1`) and the model's hazard (`flood_1`) are the
    SAME hazard under different ids. should_be_core must resolve to the MODEL id, so
    the do() never targets / leaks a GT-only id."""
    baseline = _baseline_with_gt(tmp_path)
    enum = intervention.enumerate_candidates(baseline)
    core = enum["should_be_core"]
    assert core is not None
    # The model never emitted water_1; the resolved core must be the model's flood_1.
    assert core["object_id"] != GT_ONLY_OBJECT_ID
    assert core["object_id"] == "flood_1"
    # And the spec / do-prompt built from it carry the model id, never the GT id.
    spec = intervention.build_intervention_spec(core, modality="language")
    assert spec["target"]["object_id"] == "flood_1"
    blob = " ".join(intervention.render_do_prompt(baseline, spec).values())
    assert GT_ONLY_OBJECT_ID not in blob


# ---------------------------------------------------------------------------
# B2 — a single strong signal is not washed out by the mean
# ---------------------------------------------------------------------------
def test_strong_rec_shift_alone_counts_as_moved():
    """B2: a grounded model that responds ONLY by fully rewriting its recommendations
    (recommendation_shift 1.0, the other four ~0 -> mean 0.2 < MOVE_CUTOFF) must still
    be 'moved' (and so 'grounded' on a should-be-core), not washed out to masquerade."""
    rec_only = {"hazard_shift": 0.0, "graph_shift": 0.0, "recommendation_shift": 1.0,
                "structural_shift": 0.0, "semantic_shift": 0.0, "total_shift": 0.2,
                "hazard_level_delta": 0}
    v = intervention.adjudicate_groundedness(_spec(True), rec_only, _candidates(True))
    assert v["moved"] is True
    assert v["cell"] == "grounded"


# ---------------------------------------------------------------------------
# B6 — control prefers a hazard causally independent of the core
# ---------------------------------------------------------------------------
def test_control_prefers_target_disjoint_hazard(tmp_path):
    """B6: with one GT hazard sharing the core's downstream target and another that is
    disjoint, the control picker chooses the DISJOINT hazard (uncorrelated control),
    not merely the lowest GT edge-rank, and records control_overlap=False."""
    gt = {
        "image_filename": "push_06_drowning_pool.jpg",
        "caption": "ZZ_SECRET_marker",
        "nodes": [
            {"id": "water_1", "label": "water", "state": "engulfing", "hazardous": True},
            {"id": "fire_1", "label": "fire", "state": "spreading", "hazardous": True},
            {"id": "debris_1", "label": "debris", "state": "falling", "hazardous": True},
            {"id": "child_1", "label": "child", "state": "drowning", "hazardous": False},
            {"id": "child_2", "label": "child", "state": "unconscious", "hazardous": False},
            {"id": "shed_1", "label": "shed", "state": "intact", "hazardous": False},
        ],
        "edges": [
            # core (water_1, most edges) and fire_1 BOTH feed child_1 (correlated control).
            {"source": "water_1", "target": "child_1", "effect": "may_harm", "via_state": "engulfing"},
            {"source": "water_1", "target": "child_2", "effect": "may_harm", "via_state": "engulfing"},
            {"source": "fire_1", "target": "child_1", "effect": "may_harm", "via_state": "spreading"},
            # debris_1 feeds ONLY shed_1 -> target-disjoint from the core (uncorrelated).
            {"source": "debris_1", "target": "shed_1", "effect": "may_damage", "via_state": "falling"},
        ],
    }
    gt_dir = write_gt_dir(tmp_path, gt)
    # Model must emit co-referring nodes for all three hazards (resolution is model-side).
    result = make_result()
    result["detected_objects"] += [
        {"object_id": "fire_1", "label": "fire", "state": "spreading"},
        {"object_id": "debris_1", "label": "debris", "state": "falling"},
    ]
    result["causal_graph"]["nodes"] += [
        {"id": "fire_1", "label": "fire", "state": "spreading", "hazardous": True},
        {"id": "debris_1", "label": "debris", "state": "falling", "hazardous": True},
    ]
    # Model must rank these as candidates too (Graph A ranks via intervention_candidates),
    # so they exist as MODEL-side records the control resolution can pick.
    result["causal_graph"]["intervention_candidates"] += [
        {"threat": "fire_1", "state": "spreading", "outgoing_edge_count": 1},
        {"threat": "debris_1", "state": "falling", "outgoing_edge_count": 1},
    ]
    baseline = intervention.intervention_baseline(result, image_data_url="data:img", gt_dir=gt_dir)
    enum = intervention.enumerate_candidates(baseline)
    core = enum["should_be_core"]
    control = enum["control"]
    assert core is not None and control is not None
    # core is water (resolved to flood_1); control must be debris_1 (target-disjoint),
    # NOT fire_1 (which shares child_1 with the core).
    assert control["object_id"] == "debris_1"
    assert control.get("control_overlap") is False


# ---------------------------------------------------------------------------
# B7 — U leak VOIDS the verdict (not cosmetic)
# ---------------------------------------------------------------------------
def test_u_leak_voids_verdict(tmp_path):
    """B7: when the post leaks U (object overlap < U_CUTOFF), run_intervention must
    NOT emit a grounded/masquerade/etc. verdict off an invalid comparison; the cell is
    overridden to a void state carrying comparison_invalid."""
    gt_dir = write_gt_dir(tmp_path)
    baseline = intervention.intervention_baseline(make_result(), image_data_url="data:img", gt_dir=gt_dir)
    # A post whose detected objects barely overlap the baseline -> U leaked.
    leaked_post = {
        "detected_objects": [{"object_id": "stranger_1", "label": "tree", "state": "x"},
                             {"object_id": "stranger_2", "label": "rock", "state": "y"}],
        "causal_graph": {"nodes": [], "edges": []},
        "recommendations": [],
        "disaster_level": 0,
    }
    vlm = make_vlm_stub(leaked_post)
    out = intervention.run_intervention(baseline, {"modality": "language"}, vlm)
    assert out["u_check"]["leaked"] is True
    verdict = out["verdict"]
    assert verdict["cell"] not in {
        "grounded", "masquerade", "spurious_grounding", "correctly_ignored"
    }
    assert verdict["cell"] == "u_leaked"
    assert verdict.get("comparison_invalid") is True


# ===========================================================================
# REFINER fixes (live-surfaced findings) — one lock per accepted finding.
# ===========================================================================

# ---------------------------------------------------------------------------
# B6 (phantom) — a declared candidate id with no entity anchor is dropped, not targeted
# ---------------------------------------------------------------------------
def test_phantom_candidate_is_dropped_and_surfaced(tmp_path):
    """B6: an intervention_candidate whose `threat` id is in NEITHER graph_a.nodes NOR
    detected_objects is a PHANTOM (no pixel binding). It must NOT become a candidate /
    suppression target; it is surfaced under `phantom_candidates` as a baseline
    inconsistency. Mirrors live push_06 where child_1 was a phantom that drove the do()."""
    gt_dir = write_gt_dir(tmp_path)
    result = make_result()
    # Add a phantom: declared as a candidate, but never detected and not a graph node.
    result["causal_graph"]["intervention_candidates"].append(
        {"threat": "child_1", "state": "drowning", "outgoing_edge_count": 9})
    baseline = intervention.intervention_baseline(result, image_data_url="data:img", gt_dir=gt_dir)
    enum = intervention.enumerate_candidates(baseline)
    cand_ids = {c["object_id"] for c in enum["candidates"]}
    assert "child_1" not in cand_ids, "phantom became a candidate"
    phantom_ids = {p["object_id"] for p in enum.get("phantom_candidates", [])}
    assert "child_1" in phantom_ids, "phantom not surfaced for audit"
    # The real model hazard (flood_1) is still a candidate.
    assert "flood_1" in cand_ids


# ---------------------------------------------------------------------------
# B8 — target_mitigation excludes the moved target's family from the U denominator
# ---------------------------------------------------------------------------
def test_target_mitigation_does_not_self_leak_u():
    """B8: a target_mitigation do() LEGITIMATELY removes the at-risk entity, so that
    entity disappearing must NOT count as a U leak. In a sparse 3-object scene, suppressing
    the only person would otherwise force overlap 2/3 < 0.7 -> spurious u_leaked, making the
    masquerade/grounded distinction unreachable for person hazards."""
    base = _det([("person_1", "person"), ("chair_1", "chair"), ("table_1", "table")])
    base["detected_objects"][0]["state"] = "drowning"
    post = _det([("chair_1", "chair"), ("table_1", "table")])  # person moved to safety
    spec = {"intervention_type": "target_mitigation",
            "target": {"object_id": "person_1", "label": "person"}}
    u = intervention.check_u_preservation(base, post, spec)
    assert u["leaked"] is False
    assert u["object_overlap"] == pytest.approx(1.0)
    # Control: WITHOUT the spec exception the same removal WOULD read as a leak.
    u_no_spec = intervention.check_u_preservation(base, post)
    assert u_no_spec["leaked"] is True


# ---------------------------------------------------------------------------
# B2 — discrimination is computed on content_shift, not the diluted total_shift
# ---------------------------------------------------------------------------
def test_compute_shifts_emits_content_shift():
    """B2: compute_shifts emits `content_shift` = mean(hazard, graph, recommendation),
    the three content-bearing signals, alongside total_shift = mean(all 5)."""
    baseline = _full_baseline_for_shifts()
    post = {"detected_objects": baseline["detected_objects"],
            "graph_a": {"nodes": [], "edges": [], "intervention_candidates": []},
            "recommendations": [], "hazard_level": 0}
    s = intervention.compute_shifts(baseline, post, _spec_obj())
    assert "content_shift" in s
    expected = (s["hazard_shift"] + s["graph_shift"] + s["recommendation_shift"]) / 3.0
    assert s["content_shift"] == pytest.approx(expected)


def test_discrimination_uses_content_shift_not_total():
    """B2: under coherent full re-routing structural/semantic deltas are ~0 and dilute
    total_shift; discrimination must use content_shift so a real core>control gap is not
    masked. core re-routes (content 0.9, total 0.54); placebo control static (0.0)."""
    core_sig = {"hazard_shift": 0.7, "graph_shift": 1.0, "recommendation_shift": 1.0,
                "structural_shift": 0.0, "semantic_shift": 0.0,
                "total_shift": 0.54, "content_shift": 0.9}
    ctrl_sig = {"hazard_shift": 0.0, "graph_shift": 0.0, "recommendation_shift": 0.0,
                "structural_shift": 0.0, "semantic_shift": 0.0,
                "total_shift": 0.0, "content_shift": 0.0}
    d = intervention.compare_to_control({"signals": core_sig}, {"signals": ctrl_sig})
    assert d["discriminates"] is True
    assert d["core_content_shift"] == pytest.approx(0.9)
    assert d["control_content_shift"] == pytest.approx(0.0)
    # total_shifts still reported for audit.
    assert d["core_total_shift"] == pytest.approx(0.54)


# ---------------------------------------------------------------------------
# B6 / C1 — placebo (null) control fallback when < 2 GT hazards
# ---------------------------------------------------------------------------
def test_placebo_control_when_single_gt_hazard(tmp_path):
    """B6/C1: GT_GRAPH has ONE hazardous node (water_1), so there is no real-hazard
    control. enumerate must surface a `placebo_control` (a non-hazard detected object) so a
    discrimination baseline always exists on the headline single-hazard scene."""
    baseline = _baseline_with_gt(tmp_path)  # make_result: water hazard + person non-hazard
    enum = intervention.enumerate_candidates(baseline)
    assert enum["control"] is None                       # < 2 GT hazards
    assert enum.get("placebo_control") is not None        # ...but a placebo exists
    assert enum["placebo_control"]["is_placebo"] is True
    # The placebo is the non-hazard person, not the water core.
    assert enum["placebo_control"]["object_id"] == "person_1"


def test_run_intervention_uses_placebo_for_discrimination(tmp_path):
    """B6/C1: with no real-hazard control, run_intervention runs the placebo arm and the
    discrimination block reports control_kind='placebo' (a baseline always exists)."""
    gt_dir = write_gt_dir(tmp_path)
    baseline = intervention.intervention_baseline(make_result(), image_data_url="data:img", gt_dir=gt_dir)
    raw_post = {"detected_objects": make_result()["detected_objects"],
                "causal_graph": make_result()["causal_graph"],
                "recommendations": make_result()["recommendations"], "disaster_level": 8}
    out = intervention.run_intervention(baseline, {"modality": "language"}, make_vlm_stub(raw_post))
    assert out["control"] is not None
    assert out["control"]["is_placebo"] is True
    assert out["discrimination"]["control_kind"] == "placebo"
    assert out["discrimination"]["discriminates"] is not None  # baseline existed


# ---------------------------------------------------------------------------
# A4 / B3 / C4 / R4 — gt_core_unobserved OUTRANKS u_leaked (perception miss survives void)
# ---------------------------------------------------------------------------
def test_gt_core_unobserved_survives_u_leak(tmp_path):
    """A4/B3/C4/R4: when GT names a core the model never perceived AND U leaks, the verdict
    must stay `gt_core_unobserved` (a perception miss is a baseline fact, U-independent) with
    a `u_leaked` annotation — NOT overwritten to a bare u_leaked cell that buries the
    headline finding. This is the exact live push_06 failure."""
    gt_dir = write_gt_dir(tmp_path)  # GT core = water_1, unobserved by the push06-like model
    baseline = intervention.intervention_baseline(
        _push06_like_result(), image_data_url="data:img", gt_dir=gt_dir)
    # A post that diverges -> U leaks.
    leaked_post = {
        "detected_objects": [{"object_id": "x_1", "label": "tree", "state": "a"},
                             {"object_id": "y_1", "label": "rock", "state": "b"}],
        "causal_graph": {"nodes": [], "edges": []}, "recommendations": [],
        "disaster_level": 0,
    }
    out = intervention.run_intervention(baseline, {"modality": "language"}, make_vlm_stub(leaked_post))
    v = out["verdict"]
    assert out["u_check"]["leaked"] is True
    assert v["cell"] == "gt_core_unobserved"      # perception miss NOT buried under the void
    assert v.get("u_leaked") is True               # ...but the leak is annotated
    assert v["gt_core_unobserved"]["object_id"] == "water_1"
    assert v["is_should_be_core"] is None          # B3 tri-state, not hard False
    assert v["move_basis"].get("moved") is None     # B9: no movement asserted under void


# ---------------------------------------------------------------------------
# B3 — is_should_be_core is tri-state (None when GT absent, not hard False)
# ---------------------------------------------------------------------------
def test_is_should_be_core_is_none_when_no_gt():
    """B3: adjudicate must report is_should_be_core as None (unknown) when GT is absent,
    never coerce it to a hard False that misreads as a definite 'not-core' row."""
    cands = _candidates(should_be_core=False)  # should_be_core None -> no GT
    spec_unknown = {"target": {"object_id": "h_1", "state": "engulfing", "label": "water",
                               "hazard_class": "engulfing_fluid"},
                    "intervention_type": "edge_severance", "modality": "language",
                    "is_should_be_core": False, "role": "core"}
    v = intervention.adjudicate_groundedness(spec_unknown, MOVED_SIGNALS, cands)
    assert v["cell"] == "not_adjudicable"
    assert v["is_should_be_core"] is None


# ---------------------------------------------------------------------------
# B9 — U-leak void nulls move_basis.moved (no field asserts movement above a void)
# ---------------------------------------------------------------------------
def test_u_leak_void_nulls_move_basis_moved(tmp_path):
    """B9: on a void, NEITHER verdict.moved NOR move_basis.moved may assert movement.
    A latent move_basis.moved=true under a voided verdict is an overclaim if downstream
    code reads move_basis.moved instead of verdict.moved."""
    gt_dir = write_gt_dir(tmp_path)
    baseline = intervention.intervention_baseline(make_result(), image_data_url="data:img", gt_dir=gt_dir)
    leaked_post = {
        "detected_objects": [{"object_id": "t_1", "label": "tree", "state": "x"},
                             {"object_id": "r_1", "label": "rock", "state": "y"}],
        "causal_graph": {"nodes": [], "edges": []},
        "recommendations": [{"rank": 1, "action": "Z", "threat": "t_1", "state": "x",
                             "related_object_ids": ["t_1"], "affected_objects": ["t_1"]}],
        "disaster_level": 0,
    }
    out = intervention.run_intervention(baseline, {"modality": "language"}, make_vlm_stub(leaked_post))
    v = out["verdict"]
    assert v["cell"] == "u_leaked"
    assert v["moved"] is None
    assert v["move_basis"].get("moved") is None        # the latent overclaim is gone
    assert v["move_basis"].get("consumed") is False


# ---------------------------------------------------------------------------
# C1 — post composition is persisted for U-leak auditability
# ---------------------------------------------------------------------------
def test_run_output_includes_post_composition(tmp_path):
    """C1: the run record must carry the post's detected_objects + canonical label
    multiset, so a confound auditor can verify a U-leak is a genuine scene re-read vs a
    benign relabel. The live artifact dropped this, making the void unfalsifiable."""
    gt_dir = write_gt_dir(tmp_path)
    baseline = intervention.intervention_baseline(make_result(), image_data_url="data:img", gt_dir=gt_dir)
    raw_post = {"detected_objects": [{"object_id": "a_1", "label": "water", "state": "s"}],
                "causal_graph": {"nodes": [], "edges": []}, "recommendations": [],
                "disaster_level": 3}
    out = intervention.run_intervention(baseline, {"modality": "language"}, make_vlm_stub(raw_post))
    pc = out.get("post_composition")
    assert pc is not None
    assert pc["detected_objects"] == raw_post["detected_objects"]
    assert pc["label_multiset"] == {"water": 1}


# ---------------------------------------------------------------------------
# role / provenance — spec.core_basis records GT vs declared core independently
# ---------------------------------------------------------------------------
def test_spec_core_basis_gt_when_gt_confirmed(tmp_path):
    """role: the core arm on a GT-confirmed should-be-core carries spec.core_basis='gt'."""
    gt_dir = write_gt_dir(tmp_path)
    baseline = intervention.intervention_baseline(make_result(), image_data_url="data:img", gt_dir=gt_dir)
    raw_post = {"detected_objects": make_result()["detected_objects"],
                "causal_graph": make_result()["causal_graph"],
                "recommendations": make_result()["recommendations"], "disaster_level": 8}
    out = intervention.run_intervention(baseline, {"modality": "language"}, make_vlm_stub(raw_post))
    assert out["spec"]["core_basis"] == "gt"


def test_spec_core_basis_declared_when_no_gt(tmp_path):
    """role: with no GT, the declared-core fallback arm carries spec.core_basis='declared_a'
    so the arm's provenance survives even when the U-leak override rewrites the verdict-level
    core_not_declared annotation."""
    gt_dir = write_gt_dir(tmp_path)
    result = make_result(image_filename="no_gt_here.jpg")
    baseline = intervention.intervention_baseline(result, image_data_url="data:img", gt_dir=gt_dir)
    raw_post = {"detected_objects": result["detected_objects"],
                "causal_graph": result["causal_graph"],
                "recommendations": result["recommendations"], "disaster_level": 8}
    out = intervention.run_intervention(baseline, {"modality": "language"}, make_vlm_stub(raw_post))
    assert out["spec"]["core_basis"] == "declared_a"


# ---------------------------------------------------------------------------
# A7 — declared-core diagnostics survive a U-leak void (carried forward, not erased)
# ---------------------------------------------------------------------------
def test_core_not_declared_survives_u_leak(tmp_path):
    """A4/A7: when there is no GT (declared-core fallback) AND U leaks, the void must
    CARRY FORWARD core_not_declared + declared_core_source rather than erase them, so the
    declared-core provenance is not lost under the void."""
    gt_dir = write_gt_dir(tmp_path)
    result = make_result(image_filename="no_gt_here.jpg")  # no GT
    baseline = intervention.intervention_baseline(result, image_data_url="data:img", gt_dir=gt_dir)
    leaked_post = {
        "detected_objects": [{"object_id": "t_1", "label": "tree", "state": "x"},
                             {"object_id": "r_1", "label": "rock", "state": "y"}],
        "causal_graph": {"nodes": [], "edges": []}, "recommendations": [],
        "disaster_level": 0,
    }
    out = intervention.run_intervention(baseline, {"modality": "language"}, make_vlm_stub(leaked_post))
    v = out["verdict"]
    assert out["u_check"]["leaked"] is True
    assert v["cell"] == "u_leaked"
    assert v.get("core_not_declared") is True            # carried forward under the void
    assert v.get("declared_core_source") == "A"


# ---------------------------------------------------------------------------
# A4 (driver) — an unrecognized `candidates` selection key is flagged, not silently used
# ---------------------------------------------------------------------------
def test_unused_candidates_selection_key_is_flagged(tmp_path):
    """A4: the driver passed selections={'candidates': ...}, a key the contract does not
    define; enumerate is always re-run. run_intervention must record that the bundle was
    ignored (selection_notes.candidates_arg_ignored) rather than silently accept it."""
    gt_dir = write_gt_dir(tmp_path)
    baseline = intervention.intervention_baseline(make_result(), image_data_url="data:img", gt_dir=gt_dir)
    raw_post = {"detected_objects": make_result()["detected_objects"],
                "causal_graph": make_result()["causal_graph"],
                "recommendations": make_result()["recommendations"], "disaster_level": 8}
    selections = {"modality": "language", "candidates": [{"object_id": "ignored"}]}
    out = intervention.run_intervention(baseline, selections, make_vlm_stub(raw_post))
    assert out["selection_notes"]["candidates_arg_ignored"] is True


# ---------------------------------------------------------------------------
# C4 / B9 — discrimination is void-aware; leaked arm signals carry the marker
# ---------------------------------------------------------------------------
def test_discrimination_is_void_when_core_leaks(tmp_path):
    """C4: on a leaked core arm, discrimination must NOT emit a true/false `discriminates`
    verdict off invalid comparisons. It nulls discriminates and flags comparison_invalid
    with a reason, while keeping the raw shift numbers for audit. B9: the leaked core
    signals carry a comparison_invalid marker so the numbers never outlive the void
    unflagged."""
    gt_dir = write_gt_dir(tmp_path)
    baseline = intervention.intervention_baseline(make_result(), image_data_url="data:img", gt_dir=gt_dir)
    # A post that leaks U on every arm (wholesale scene re-read).
    leaked_post = {
        "detected_objects": [{"object_id": "stranger_1", "label": "tree", "state": "x"},
                             {"object_id": "stranger_2", "label": "rock", "state": "y"}],
        "causal_graph": {"nodes": [], "edges": []},
        "recommendations": [],
        "disaster_level": 0,
    }
    out = intervention.run_intervention(baseline, {"modality": "language"}, make_vlm_stub(leaked_post))
    assert out["u_check"]["leaked"] is True
    d = out["discrimination"]
    assert d["discriminates"] is None
    assert d["comparison_invalid"] is True
    assert d["comparison_invalid_reason"] in {"core_leaked", "both_leaked"}
    # raw numbers retained for audit (not silently dropped)
    assert "core_content_shift" in d
    # B9: the persisted core signals carry the void marker.
    assert out["signals"].get("comparison_invalid") is True


# ---------------------------------------------------------------------------
# C3 — non-high baseline trust qualifies the verdict with a caveat
# ---------------------------------------------------------------------------
def test_verdict_carries_trust_caveat_when_trust_moderate(tmp_path):
    """C3: a moderate/low baseline trust must qualify the read — verdict.trust_caveat True
    and the explanation states the read is provisional."""
    gt_dir = write_gt_dir(tmp_path)
    result = make_result()
    result["pre_intervention_trust"] = {"score": 0.85, "level": "moderate"}
    baseline = intervention.intervention_baseline(result, image_data_url="data:img", gt_dir=gt_dir)
    raw_post = {"detected_objects": make_result()["detected_objects"],
                "causal_graph": make_result()["causal_graph"],
                "recommendations": make_result()["recommendations"], "disaster_level": 8}
    out = intervention.run_intervention(baseline, {"modality": "language"}, make_vlm_stub(raw_post))
    v = out["verdict"]
    assert v.get("trust_caveat") is True
    assert "provisional" in v.get("explanation", "").lower()


def test_verdict_no_trust_caveat_when_trust_high(tmp_path):
    """C3: a high (or unknown) baseline trust adds NO caveat — trust_caveat False."""
    gt_dir = write_gt_dir(tmp_path)
    result = make_result()
    result["pre_intervention_trust"] = {"score": 0.95, "level": "high"}
    baseline = intervention.intervention_baseline(result, image_data_url="data:img", gt_dir=gt_dir)
    raw_post = {"detected_objects": make_result()["detected_objects"],
                "causal_graph": make_result()["causal_graph"],
                "recommendations": make_result()["recommendations"], "disaster_level": 8}
    out = intervention.run_intervention(baseline, {"modality": "language"}, make_vlm_stub(raw_post))
    v = out["verdict"]
    assert v.get("trust_caveat") is False
    assert "provisional" not in v.get("explanation", "").lower()


# ---------------------------------------------------------------------------
# B6 — a control correlated with the core (control_overlap) is replaced by the placebo
# ---------------------------------------------------------------------------
def test_correlated_control_is_replaced_by_placebo(tmp_path):
    """B6: when the only real-hazard control overlaps the core's downstream targets
    (control_overlap True — debris from the same collapse), it is causally correlated with
    the core and would destroy discrimination by construction. run_intervention must prefer
    the causally-independent placebo and surface the confound (control_overlap)."""
    gt_dir = write_gt_dir(tmp_path)
    # Two GT hazards sharing ALL downstream victims -> the non-core hazard is correlated.
    gt = {
        "image_filename": "push_34_collapse.jpg",
        "caption": GT_GRAPH["caption"],
        "schema_version": "2026-06-10",
        "nodes": [
            {"id": "building_1", "label": "structure", "state": "collapsing", "hazardous": True},
            {"id": "debris_1", "label": "structure", "state": "falling", "hazardous": True},
            {"id": "rescuer_1", "label": "person", "state": "exposed", "hazardous": False},
        ],
        "edges": [
            {"source": "building_1", "target": "rescuer_1", "effect": "may_harm", "via_state": "collapsing"},
            {"source": "debris_1", "target": "rescuer_1", "effect": "may_harm", "via_state": "falling"},
        ],
    }
    gt_dir2 = tmp_path / "verified_gt"
    if not gt_dir2.exists():
        gt_dir2 = write_gt_dir(tmp_path, gt)
    else:
        (gt_dir2 / f"{gt['image_filename']}.gt.json").write_text(json.dumps(gt))

    result = make_result(image_filename="push_34_collapse.jpg")
    result["detected_objects"] = [
        {"object_id": "building_1", "label": "structure", "state": "collapsing"},
        {"object_id": "debris_1", "label": "structure", "state": "falling"},
        {"object_id": "rescuer_1", "label": "person", "state": "exposed"},
        {"object_id": "vehicle_1", "label": "car", "state": "parked"},  # non-hazard -> placebo
    ]
    result["causal_graph"] = {
        "nodes": [
            {"id": "building_1", "label": "structure", "state": "collapsing", "hazardous": True},
            {"id": "debris_1", "label": "structure", "state": "falling", "hazardous": True},
            {"id": "rescuer_1", "label": "person", "state": "exposed", "hazardous": False},
            {"id": "vehicle_1", "label": "car", "state": "parked", "hazardous": False},
        ],
        "edges": [
            {"source": "building_1", "target": "rescuer_1", "effect": "may_harm", "via_state": "collapsing"},
            {"source": "debris_1", "target": "rescuer_1", "effect": "may_harm", "via_state": "falling"},
        ],
        "intervention_candidates": [
            {"threat": "building_1", "state": "collapsing", "outgoing_edge_count": 1},
            {"threat": "debris_1", "state": "falling", "outgoing_edge_count": 1},
        ],
    }
    baseline = intervention.intervention_baseline(result, image_data_url="data:img", gt_dir=gt_dir2)
    enum = intervention.enumerate_candidates(baseline)
    # Precondition: the chosen real-hazard control overlaps the core (the confound).
    assert enum["control"] is not None
    assert enum["control"].get("control_overlap") is True
    assert enum.get("placebo_control") is not None

    raw_post = {"detected_objects": result["detected_objects"],
                "causal_graph": result["causal_graph"],
                "recommendations": [], "disaster_level": 7}
    out = intervention.run_intervention(baseline, {"modality": "language"}, make_vlm_stub(raw_post))
    # B6: the correlated hazard was replaced by the placebo as the primary baseline.
    assert out["control"]["is_placebo"] is True
    assert out["discrimination"]["control_kind"] == "placebo"
    assert out["discrimination"]["control_overlap"] is False
