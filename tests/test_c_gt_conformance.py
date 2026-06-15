"""Section C — GT file conformance.

Every GT file in `exports/ground_truth/candidates/push_test/` is parametrized
through each invariant. These tests are READ-ONLY against GT files.

C12 (distance rule semantics) and C21 (schema_version) are spec gaps for
auto-testing; both are skipped with explicit reasons.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

# conftest.py is auto-loaded by pytest; importing from it directly works
# because the tests/ directory is on sys.path during test collection.
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from conftest import all_push_test_gts, GT_PUSH_TEST  # noqa: E402


# A tiny helper: re-load each GT inside the test (cheap; <10ms total) so
# parametrize ids stay file-name-based and failures point at the file.
def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


# Pattern for C15: object ids.
OBJECT_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]*_\d+$")
INFERRED_ID_PATTERN = re.compile(r"^presumed_[a-z0-9_]+_in_[a-z][a-z0-9]*_\d+$")


# ---------------------------------------------------------------------------
# C1 — JSON syntactic validity.
# ---------------------------------------------------------------------------
@pytest.mark.blocking
@pytest.mark.parametrize("path", list(all_push_test_gts()))
def test_c1_json_syntactic_validity(path: Path):
    """C1 — every *.gt.json parses as valid JSON."""
    try:
        json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        pytest.fail(f"{path.name}: invalid JSON ({e})")


# ---------------------------------------------------------------------------
# C2 — All node states ∈ vocabulary ∪ synonyms ∪ {undetermined}.
# ---------------------------------------------------------------------------
@pytest.mark.blocking
@pytest.mark.parametrize("path", list(all_push_test_gts()))
def test_c2_node_states_in_vocabulary(path: Path, main_module):
    gt = _load(path)
    allowed = (
        main_module.HAZARD_BEARING_STATES
        | main_module.AT_RISK_STATES
        | main_module.NORMAL_STATES
        | set(main_module.STATE_SYNONYMS.keys())
        | {"undetermined"}
    )
    bad: list[tuple[str, str]] = []
    for n in gt.get("nodes") or []:
        st = str(n.get("state", "")).strip().lower()
        if st and st not in allowed:
            bad.append((str(n.get("id", "")), st))
    assert not bad, f"{path.name}: nodes with non-vocab states: {bad}"


# ---------------------------------------------------------------------------
# C3 — Hazardous flag matches state class.
# ---------------------------------------------------------------------------
@pytest.mark.blocking
@pytest.mark.parametrize("path", list(all_push_test_gts()))
def test_c3_hazardous_flag_matches_state_class(path: Path, main_module):
    gt = _load(path)
    mismatches: list[dict[str, Any]] = []
    for n in gt.get("nodes") or []:
        state = main_module.canonicalize_state(str(n.get("state", "")).strip())
        haz_actual = bool(n.get("hazardous", False))
        haz_expected = state in main_module.HAZARD_BEARING_STATES
        if haz_actual != haz_expected:
            mismatches.append({
                "id": n.get("id"),
                "state": n.get("state"),
                "canonical": state,
                "hazardous_actual": haz_actual,
                "hazardous_expected": haz_expected,
            })
    assert not mismatches, f"{path.name}: hazardous flag mismatches: {mismatches}"


# ---------------------------------------------------------------------------
# C4 — At-risk vs hazardous mutually exclusive.
# ---------------------------------------------------------------------------
@pytest.mark.blocking
@pytest.mark.parametrize("path", list(all_push_test_gts()))
def test_c4_at_risk_hazardous_mutually_exclusive(path: Path, main_module):
    gt = _load(path)
    bad: list[str] = []
    for n in gt.get("nodes") or []:
        state = main_module.canonicalize_state(str(n.get("state", "")).strip())
        if bool(n.get("hazardous", False)) and state in main_module.AT_RISK_STATES:
            bad.append(f"{n.get('id')} (state={state}, hazardous=True)")
    assert not bad, f"{path.name}: at-risk-AND-hazardous nodes: {bad}"


# ---------------------------------------------------------------------------
# C5 — Every edge's effect ∈ EFFECT_LABELS.
# ---------------------------------------------------------------------------
@pytest.mark.blocking
@pytest.mark.parametrize("path", list(all_push_test_gts()))
def test_c5_edge_effects_in_vocabulary(path: Path, main_module):
    gt = _load(path)
    bad: list[dict[str, Any]] = []
    for e in gt.get("edges") or []:
        eff = str(e.get("effect", "")).strip()
        if eff not in main_module.EFFECT_LABELS:
            bad.append({"source": e.get("source"), "target": e.get("target"), "effect": eff})
    assert not bad, f"{path.name}: bad effects: {bad}"


# ---------------------------------------------------------------------------
# C6 — Every edge's via_state == source node's state (canonicalized).
# ---------------------------------------------------------------------------
@pytest.mark.blocking
@pytest.mark.parametrize("path", list(all_push_test_gts()))
def test_c6_via_state_matches_source_state(path: Path, main_module):
    gt = _load(path)
    nodes_by_id = {str(n.get("id", "")): n for n in gt.get("nodes") or []}
    bad: list[dict[str, Any]] = []
    for e in gt.get("edges") or []:
        src_id = str(e.get("source", "")).strip()
        via = main_module.canonicalize_state(str(e.get("via_state", "")).strip())
        src_node = nodes_by_id.get(src_id)
        if src_node is None:
            continue  # C14 catches this
        src_state = main_module.canonicalize_state(str(src_node.get("state", "")).strip())
        if via != src_state:
            bad.append({"source": src_id, "via_state": via, "source_state": src_state})
    assert not bad, f"{path.name}: via_state != source state: {bad}"


# ---------------------------------------------------------------------------
# C7 — Every edge's via_state is hazard-bearing.
# ---------------------------------------------------------------------------
@pytest.mark.blocking
@pytest.mark.parametrize("path", list(all_push_test_gts()))
def test_c7_via_state_hazard_bearing(path: Path, main_module):
    gt = _load(path)
    bad: list[dict[str, Any]] = []
    for e in gt.get("edges") or []:
        via = main_module.canonicalize_state(str(e.get("via_state", "")).strip())
        if via and via not in main_module.HAZARD_BEARING_STATES:
            bad.append({"source": e.get("source"), "target": e.get("target"), "via_state": via})
    assert not bad, f"{path.name}: non-hazard via_states: {bad}"


# ---------------------------------------------------------------------------
# C8 — Every edge's source is a hazardous node.
# ---------------------------------------------------------------------------
@pytest.mark.blocking
@pytest.mark.parametrize("path", list(all_push_test_gts()))
def test_c8_edge_source_is_hazardous(path: Path):
    gt = _load(path)
    nodes_by_id = {str(n.get("id", "")): n for n in gt.get("nodes") or []}
    bad: list[str] = []
    for e in gt.get("edges") or []:
        src_id = str(e.get("source", "")).strip()
        src_node = nodes_by_id.get(src_id)
        if src_node is None:
            continue  # C14 catches this
        if not bool(src_node.get("hazardous", False)):
            bad.append(src_id)
    assert not bad, f"{path.name}: non-hazardous edge sources: {bad}"


# ---------------------------------------------------------------------------
# C9 — Self-loops only use effect=worsens.
# ---------------------------------------------------------------------------
@pytest.mark.blocking
@pytest.mark.parametrize("path", list(all_push_test_gts()))
def test_c9_self_loops_only_worsens(path: Path):
    gt = _load(path)
    bad: list[dict[str, Any]] = []
    for e in gt.get("edges") or []:
        src = str(e.get("source", "")).strip()
        tgt = str(e.get("target", "")).strip()
        if src and src == tgt:
            eff = str(e.get("effect", "")).strip()
            if eff != "worsens":
                bad.append({"node": src, "effect": eff})
    assert not bad, f"{path.name}: self-loops with non-worsens effect: {bad}"


# ---------------------------------------------------------------------------
# C10 — Mutual-hazard symmetry. WARN-level: asymmetric edges can be legit.
# ---------------------------------------------------------------------------
@pytest.mark.warn
@pytest.mark.parametrize("path", list(all_push_test_gts()))
def test_c10_mutual_worsens_symmetry(path: Path):
    gt = _load(path)
    edges = gt.get("edges") or []
    worsens_pairs: set[tuple[str, str]] = set()
    for e in edges:
        if str(e.get("effect", "")).strip() == "worsens":
            src = str(e.get("source", "")).strip()
            tgt = str(e.get("target", "")).strip()
            if src and tgt and src != tgt:
                worsens_pairs.add((src, tgt))
    asymmetric: list[tuple[str, str]] = []
    for a, b in worsens_pairs:
        if (b, a) not in worsens_pairs:
            asymmetric.append((a, b))
    assert not asymmetric, (
        f"{path.name}: inter-entity `worsens` without reverse "
        f"(should be `increases_risk_to` if truly asymmetric): {asymmetric}"
    )


# ---------------------------------------------------------------------------
# C11 — Shared-cause exception correctness. WARN; needs per-scene inspection.
# Auto check we CAN do: when multiple hazardous nodes share the same state and
# also each have an incoming edge from a fluid-ish node, they should NOT also
# have mutual worsens between them. This is a partial heuristic.
# ---------------------------------------------------------------------------
@pytest.mark.warn
@pytest.mark.parametrize("path", list(all_push_test_gts()))
def test_c11_shared_cause_exception_heuristic(path: Path):
    gt = _load(path)
    edges = gt.get("edges") or []
    nodes = {str(n.get("id", "")): n for n in gt.get("nodes") or []}
    # Find pairs of hazardous nodes that share the SAME state AND both have
    # an incoming edge from the same source.
    # Exclude self-loops from incoming-source map — they are intrinsic
    # deterioration, not external feeding. Also exclude the very edges that
    # form the (a, b) mutual pair we are about to test against, so a mutual
    # worsens pair doesn't falsely appear to share itself as a source.
    incoming_by_target: dict[str, set[str]] = {}
    for e in edges:
        src, tgt = str(e.get("source", "")), str(e.get("target", ""))
        if src and tgt and src != tgt:
            incoming_by_target.setdefault(tgt, set()).add(src)
    worsens_pairs: set[tuple[str, str]] = set()
    for e in edges:
        if str(e.get("effect", "")).strip() == "worsens":
            s, t = str(e.get("source", "")), str(e.get("target", ""))
            if s != t:
                worsens_pairs.add((s, t))
    bad: list[str] = []
    haz_ids = [nid for nid, n in nodes.items() if n.get("hazardous")]
    for i in range(len(haz_ids)):
        for j in range(i + 1, len(haz_ids)):
            a, b = haz_ids[i], haz_ids[j]
            sa = str(nodes[a].get("state", "")).strip().lower()
            sb = str(nodes[b].get("state", "")).strip().lower()
            if sa != sb:
                continue
            shared_sources = incoming_by_target.get(a, set()) & incoming_by_target.get(b, set())
            # Exclude a and b themselves — a mutual worsens between a↔b would
            # otherwise count a as b's "source" and vice versa.
            shared_sources = shared_sources - {a, b}
            # Exclude shared sources that are themselves in MUTUAL worsens
            # with BOTH a and b — that's a dense mutual-hazard graph (all
            # peers feeding each other), not a fluid-source-with-victims
            # pattern. The shared-cause exception only catches the latter.
            shared_sources = {
                s for s in shared_sources
                if not (
                    (s, a) in worsens_pairs and (a, s) in worsens_pairs
                    and (s, b) in worsens_pairs and (b, s) in worsens_pairs
                )
            }
            if shared_sources and ((a, b) in worsens_pairs or (b, a) in worsens_pairs):
                bad.append(
                    f"shared-cause violation: {a},{b} share state {sa} and "
                    f"source(s) {sorted(shared_sources)} yet have mutual worsens"
                )
    assert not bad, f"{path.name}: {bad}"


# ---------------------------------------------------------------------------
# C12 — Distance/contiguity semantics. HUMAN-only: skip.
# ---------------------------------------------------------------------------
@pytest.mark.human
@pytest.mark.skip(reason="C12 distance-rule semantics requires image inspection — manual only per TESTS.md")
def test_c12_distance_rule_semantics():
    pass


# ---------------------------------------------------------------------------
# C13 — Every hazardous node has at least one edge.
# ---------------------------------------------------------------------------
@pytest.mark.blocking
@pytest.mark.parametrize("path", list(all_push_test_gts()))
def test_c13_hazardous_node_has_edge(path: Path):
    gt = _load(path)
    edges = gt.get("edges") or []
    touched: set[str] = set()
    for e in edges:
        s, t = str(e.get("source", "")), str(e.get("target", ""))
        if s:
            touched.add(s)
        if t:
            touched.add(t)
    orphans = [
        str(n.get("id", ""))
        for n in (gt.get("nodes") or [])
        if n.get("hazardous") and str(n.get("id", "")) not in touched
    ]
    assert not orphans, f"{path.name}: hazardous nodes with zero edges: {orphans}"


# ---------------------------------------------------------------------------
# C14 — All edge endpoints resolve.
# ---------------------------------------------------------------------------
@pytest.mark.blocking
@pytest.mark.parametrize("path", list(all_push_test_gts()))
def test_c14_edge_endpoints_resolve(path: Path):
    gt = _load(path)
    node_ids = {str(n.get("id", "")) for n in gt.get("nodes") or []}
    dangling: list[tuple[str, str]] = []
    for e in gt.get("edges") or []:
        for key in ("source", "target"):
            v = str(e.get(key, "")).strip()
            if v and v not in node_ids:
                dangling.append((key, v))
    assert not dangling, f"{path.name}: dangling edge endpoints: {dangling}"


# ---------------------------------------------------------------------------
# C15 — Object ids follow label_N form. WARN-level (inferred entity exception).
# ---------------------------------------------------------------------------
@pytest.mark.warn
@pytest.mark.parametrize("path", list(all_push_test_gts()))
def test_c15_object_id_form(path: Path):
    gt = _load(path)
    bad: list[str] = []
    for n in gt.get("nodes") or []:
        nid = str(n.get("id", "")).strip()
        inferred = bool(n.get("inferred", False))
        if inferred:
            if not INFERRED_ID_PATTERN.match(nid):
                bad.append(f"inferred id wrong form: {nid}")
        else:
            if not OBJECT_ID_PATTERN.match(nid):
                bad.append(f"non-inferred id wrong form: {nid}")
    assert not bad, f"{path.name}: {bad}"


# ---------------------------------------------------------------------------
# C16 — Image file exists for every GT file.
# ---------------------------------------------------------------------------
@pytest.mark.blocking
@pytest.mark.parametrize("path", list(all_push_test_gts()))
def test_c16_image_file_exists(path: Path):
    gt = _load(path)
    img = gt.get("image_filename")
    assert img, f"{path.name}: missing image_filename"
    # Look first in same folder; otherwise in standard image dirs.
    candidate_dirs = [path.parent, path.parent.parent.parent.parent / "experiments"]
    for d in candidate_dirs:
        if (d / img).is_file():
            return
    # Fall back to walking the project root subset.
    project_root = Path(__file__).resolve().parent.parent
    for sub in ("exports", "experiments"):
        for found in (project_root / sub).rglob(img):
            if found.is_file():
                return
    pytest.fail(f"{path.name}: image '{img}' not found in expected directories")


# ---------------------------------------------------------------------------
# C17 — image_filename matches GT's basename.
# ---------------------------------------------------------------------------
@pytest.mark.blocking
@pytest.mark.parametrize("path", list(all_push_test_gts()))
def test_c17_image_filename_matches_basename(path: Path):
    gt = _load(path)
    img = str(gt.get("image_filename", "")).strip()
    # GT filename is `<image>.gt.json`. Strip `.gt.json` to get expected image.
    expected = path.name[:-len(".gt.json")]
    assert img == expected, (
        f"{path.name}: image_filename={img!r} doesn't match file basename {expected!r}"
    )


# ---------------------------------------------------------------------------
# C18 — Inferred entity discipline. WARN.
# ---------------------------------------------------------------------------
@pytest.mark.warn
@pytest.mark.parametrize("path", list(all_push_test_gts()))
def test_c18_inferred_entity_discipline(path: Path):
    gt = _load(path)
    nodes = gt.get("nodes") or []
    inferred_nodes = [n for n in nodes if n.get("inferred")]
    visible_count = len(nodes) - len(inferred_nodes)
    # (a) id form already covered by C15.
    # (b) heuristic ceiling: inferred <= max(2, 2 * visible)
    if visible_count > 0:
        assert len(inferred_nodes) <= max(2, 2 * visible_count), (
            f"{path.name}: {len(inferred_nodes)} inferred vs {visible_count} visible — "
            "exceeds 2x heuristic"
        )


# ---------------------------------------------------------------------------
# C19, C20 — Edge / node ordering does not affect comparison.
# Test against a SAMPLE of GTs to keep runtime sane (not all 70).
# ---------------------------------------------------------------------------
def _sample_gts(n: int = 5) -> list[Path]:
    paths = sorted(GT_PUSH_TEST.glob("*.gt.json"))
    return paths[:n] if paths else []


@pytest.mark.blocking
@pytest.mark.parametrize("path", _sample_gts())
def test_c19_edge_ordering_invariant(path: Path, main_module):
    """C19 — shuffling the `edges` list does not change comparison scores."""
    import random
    gt = _load(path)
    graph_orig = main_module.gt_candidate_to_graph_dict(gt)
    edges = list(graph_orig.get("edges") or [])
    if len(edges) < 2:
        pytest.skip(f"{path.name}: <2 edges — ordering test trivial")
    shuffled = list(edges)
    random.Random(42).shuffle(shuffled)
    graph_shuf = {"nodes": graph_orig["nodes"], "edges": shuffled}
    # Compare graph_orig vs itself, and graph_orig vs graph_shuf.
    # Soft and topological scores must remain identical.
    res_id = main_module.compare_graphs(graph_orig, graph_orig)
    res_shuf = main_module.compare_graphs(graph_orig, graph_shuf)
    for key in ("structural_consistency", "topological_consistency", "node_consistency", "a_fidelity_soft"):
        assert abs(res_id[key] - res_shuf[key]) < 1e-9, (
            f"{path.name}: edge-order changed {key}: {res_id[key]} vs {res_shuf[key]}"
        )


@pytest.mark.blocking
@pytest.mark.parametrize("path", _sample_gts())
def test_c20_node_ordering_invariant(path: Path, main_module):
    """C20 — shuffling the `nodes` list does not change comparison scores."""
    import random
    gt = _load(path)
    graph_orig = main_module.gt_candidate_to_graph_dict(gt)
    nodes = list(graph_orig.get("nodes") or [])
    if len(nodes) < 2:
        pytest.skip(f"{path.name}: <2 nodes — ordering test trivial")
    shuffled = list(nodes)
    random.Random(42).shuffle(shuffled)
    graph_shuf = {"nodes": shuffled, "edges": graph_orig["edges"]}
    res_id = main_module.compare_graphs(graph_orig, graph_orig)
    res_shuf = main_module.compare_graphs(graph_orig, graph_shuf)
    for key in ("structural_consistency", "topological_consistency", "node_consistency", "a_fidelity_soft"):
        assert abs(res_id[key] - res_shuf[key]) < 1e-9, (
            f"{path.name}: node-order changed {key}: {res_id[key]} vs {res_shuf[key]}"
        )


# ---------------------------------------------------------------------------
# C21 — schema_version field present and matches main.SCHEMA_VERSION.
# After any schema-rule change, bump SCHEMA_VERSION in main.py — this test
# then fails on every GT stamped with the old version, which is the signal
# to re-verify those files (catches the "verified copy predates the rule
# change" staleness, e.g. the push_02 provenance episode).
# ---------------------------------------------------------------------------
@pytest.mark.blocking
@pytest.mark.parametrize("path", list(all_push_test_gts()))
def test_c21_schema_version_current(path: Path, main_module):
    gt = _load(path)
    version = gt.get("schema_version")
    assert version is not None, (
        f"{path.name}: missing schema_version field — stamp it with "
        f"main.SCHEMA_VERSION ({main_module.SCHEMA_VERSION})"
    )
    assert version == main_module.SCHEMA_VERSION, (
        f"{path.name}: schema_version {version!r} != current "
        f"{main_module.SCHEMA_VERSION!r} — this GT was annotated under older "
        f"rules and needs re-verification"
    )


# ---------------------------------------------------------------------------
# C22 — Fluid provenance heuristic: smoke/dust must be connected to a visible
# producer when one exists in the scene. WARN — off-frame-producer cases are
# valid exceptions a human adjudicates.
# ---------------------------------------------------------------------------
SMOKE_PRODUCER_STATES = {"burning", "spreading", "collapsing"}
DUST_PRODUCER_STATES = {"collapsing", "collapsed", "fallen"}
CHEMICAL_PRODUCER_STATES = {"leaking", "fallen", "crushed"}


@pytest.mark.warn
@pytest.mark.parametrize("path", list(all_push_test_gts()))
def test_c22_fluid_provenance_heuristic(path: Path):
    gt = _load(path)
    nodes = {str(n.get("id", "")): n for n in gt.get("nodes") or []}
    edges = gt.get("edges") or []
    bad: list[str] = []
    for nid, n in nodes.items():
        if not n.get("hazardous"):
            continue
        label = str(n.get("label", "")).strip().lower()
        if label == "smoke":
            producer_states = SMOKE_PRODUCER_STATES
        elif label == "dust":
            producer_states = DUST_PRODUCER_STATES
        elif label in ("chemical", "gas"):
            producer_states = CHEMICAL_PRODUCER_STATES
        else:
            continue
        producers = [
            pid for pid, p in nodes.items()
            if pid != nid and p.get("hazardous")
            and str(p.get("label", "")).strip().lower() not in ("smoke", "dust")
            and str(p.get("state", "")).strip().lower() in producer_states
        ]
        if not producers:
            continue  # no visible producer in scene — fluid may stand alone
        has_provenance = any(
            str(e.get("target", "")) == nid
            and str(e.get("source", "")) in producers
            and str(e.get("effect", "")).strip() == "increases_risk_to"
            for e in edges
        )
        if not has_provenance:
            bad.append(
                f"{nid} ({label}) has visible producer(s) {producers} but no "
                f"incoming increases_risk_to provenance edge"
            )
    assert not bad, f"{path.name}: {bad}"


# ---------------------------------------------------------------------------
# C23 — Smoke-reach superset heuristic: targets harmed by a smoke-producing
# entity should be a subset of the targets harmed by its smoke. WARN — rare
# wind geometries are legitimate exceptions a human adjudicates.
# ---------------------------------------------------------------------------
HARM_LIKE_EFFECTS = {"may_harm", "threatens"}
PERSONISH_LABELS = {
    "person", "man", "woman", "child", "firefighter", "officer", "rescuer",
    "homeowner", "driver", "worker", "resident", "responder", "victim",
    "bystander", "paramedic", "clerk", "customer", "family",
    "infant", "baby", "teenager", "boy", "girl", "patient", "nurse",
    "doctor", "medic", "farmer", "shopkeeper", "vendor",
    "dog", "cow", "horse", "animal", "bull",
}


@pytest.mark.warn
@pytest.mark.parametrize("path", list(all_push_test_gts()))
def test_c23_smoke_reach_superset(path: Path):
    gt = _load(path)
    nodes = {str(n.get("id", "")): n for n in gt.get("nodes") or []}
    edges = gt.get("edges") or []

    def harm_targets(src_id: str) -> set[str]:
        return {
            str(e.get("target", "")) for e in edges
            if str(e.get("source", "")) == src_id
            and str(e.get("effect", "")).strip() in HARM_LIKE_EFFECTS
            and str(nodes.get(str(e.get("target", "")), {}).get("label", "")).lower()
            in PERSONISH_LABELS
        }

    bad: list[str] = []
    for e in edges:
        if str(e.get("effect", "")).strip() != "increases_risk_to":
            continue
        tgt = str(e.get("target", ""))
        src = str(e.get("source", ""))
        if str(nodes.get(tgt, {}).get("label", "")).lower() != "smoke":
            continue
        producer_reach = harm_targets(src)
        smoke_reach = harm_targets(tgt)
        skipped = producer_reach - smoke_reach
        if skipped:
            bad.append(
                f"producer {src} harms {sorted(skipped)} but its smoke {tgt} "
                f"does not — heat reaching targets the smoke skips is a red flag"
            )
    assert not bad, f"{path.name}: {bad}"


# ---------------------------------------------------------------------------
# C24 — Edge-less person in an active-smoke scene. Complements C23: catches a
# person with NO edges at all in a scene where smoke harms others (likely an
# overlooked target, not a deliberate out-of-reach call). WARN — genuinely
# distant bystanders are valid exceptions a human adjudicates.
# ---------------------------------------------------------------------------
@pytest.mark.warn
@pytest.mark.parametrize("path", list(all_push_test_gts()))
def test_c24_edgeless_person_in_smoke_scene(path: Path):
    gt = _load(path)
    nodes = {str(n.get("id", "")): n for n in gt.get("nodes") or []}
    edges = gt.get("edges") or []
    fluid_ids = [
        nid for nid, n in nodes.items()
        if str(n.get("label", "")).lower() in ("smoke", "dust") and n.get("hazardous")
    ]
    if not fluid_ids:
        return
    smoke_harms_someone = any(
        str(e.get("source", "")) in fluid_ids
        and str(e.get("effect", "")).strip() in HARM_LIKE_EFFECTS
        for e in edges
    )
    if not smoke_harms_someone:
        return
    targets_with_any_edge = {str(e.get("target", "")) for e in edges}
    orphans = [
        nid for nid, n in nodes.items()
        if str(n.get("label", "")).lower() in PERSONISH_LABELS
        and nid not in targets_with_any_edge
    ]
    assert not orphans, (
        f"{path.name}: active smoke harms people in this scene, but these "
        f"person-like nodes have no incoming edges at all — verify they are "
        f"genuinely out of every hazard's reach: {orphans}"
    )


# ---------------------------------------------------------------------------
# C25 — Uniform responder-edge assignment flag. WARN — uniform harm edges
# from one hazard to ALL (≥3) responders is the signature of role-based
# annotation; position-based assignment usually yields a mix. Scenes where a
# human verified the uniform assignment as position-correct go in the
# allowlist below WITH a verdict comment.
# ---------------------------------------------------------------------------
RESPONDER_LABELS = {"firefighter", "officer", "rescuer", "paramedic", "responder", "medic"}

# scene-file basename → verdict. PENDING = awaiting human image verification.
C25_ALLOWLIST = {
    "push_34_apartment_collapse_rescue.jpg.gt.json": "VERIFIED 2026-06-11: rescuer_1..4 are representatives of the on-pile crew; uniform building+debris edges are position-correct for that group; street-level personnel deliberately not instanced.",
    "push_40_collapse_search_grid.jpg.gt.json": "PENDING human verification — search-grid rescuers vs perimeter",
    "push_53_wildland_jumping_line.jpg.gt.json": "PENDING human verification — all 4 crew within flame reach?",
}


@pytest.mark.warn
@pytest.mark.parametrize("path", list(all_push_test_gts()))
def test_c25_uniform_responder_edges(path: Path):
    if path.name in C25_ALLOWLIST:
        pytest.skip(f"C25 allowlist: {C25_ALLOWLIST[path.name]}")
    gt = _load(path)
    nodes = {str(n.get("id", "")): n for n in gt.get("nodes") or []}
    edges = gt.get("edges") or []
    responders = [
        nid for nid, n in nodes.items()
        if str(n.get("label", "")).strip().lower() in RESPONDER_LABELS
    ]
    if len(responders) < 3:
        return
    fluidish = {"smoke", "dust", "water", "gas", "chemical", "mud"}
    bad: list[str] = []
    by_source: dict[str, set[str]] = {}
    for e in edges:
        if str(e.get("effect", "")).strip() not in HARM_LIKE_EFFECTS:
            continue
        src, tgt = str(e.get("source", "")), str(e.get("target", ""))
        if str(nodes.get(src, {}).get("label", "")).lower() in fluidish:
            continue  # fluids legitimately reach everyone in the plume
        if tgt in responders:
            by_source.setdefault(src, set()).add(tgt)
    for src, hit in by_source.items():
        if set(responders) <= hit:
            bad.append(
                f"{src} harms ALL {len(responders)} responders uniformly — "
                f"role-bias signature; verify each responder's position in the "
                f"image, then either fix the edges or add this scene to "
                f"C25_ALLOWLIST with a verdict comment"
            )
    assert not bad, f"{path.name}: {bad}"


# ---------------------------------------------------------------------------
# C26 — Obstruction coupling check. WARN — blocks_access_to/isolates to a
# person requires coupling (otherwise endangered) or entrapment (source is
# an active fluid surrounding them). Uncoupled obstruction edges from static
# sources are scene furniture, not safety edges.
# ---------------------------------------------------------------------------
ACTIVE_FLUID_STATES = {"rising", "spreading", "engulfing", "seeping", "billowing", "leaking"}
FLUID_SOURCE_LABELS = {"water", "mud", "smoke", "dust", "gas", "chemical"}


@pytest.mark.warn
@pytest.mark.parametrize("path", list(all_push_test_gts()))
def test_c26_obstruction_coupling(path: Path, main_module):
    gt = _load(path)
    nodes = {str(n.get("id", "")): n for n in gt.get("nodes") or []}
    edges = gt.get("edges") or []
    harm_targets = {
        str(e.get("target", "")) for e in edges
        if str(e.get("effect", "")).strip() in HARM_LIKE_EFFECTS
    }
    bad: list[str] = []
    for e in edges:
        if str(e.get("effect", "")).strip() not in ("blocks_access_to", "isolates"):
            continue
        tgt_id = str(e.get("target", ""))
        tgt = nodes.get(tgt_id, {})
        if str(tgt.get("label", "")).strip().lower() not in PERSONISH_LABELS:
            continue  # obstruction edges to roads/resources are out of scope here
        state = main_module.canonicalize_state(str(tgt.get("state", "")).strip())
        coupled = state in main_module.AT_RISK_STATES or tgt_id in harm_targets
        src = nodes.get(str(e.get("source", "")), {})
        entrapment = (
            str(src.get("label", "")).strip().lower() in FLUID_SOURCE_LABELS
            and str(src.get("state", "")).strip().lower() in ACTIVE_FLUID_STATES
        )
        if not (coupled or entrapment):
            bad.append(
                f"{e.get('source')} --{e.get('effect')}--> {tgt_id}: person is "
                f"neither coupled (no Distress state, no incoming harm edge) nor "
                f"entrapped (source is not an active fluid) — scene-furniture edge"
            )
    assert not bad, f"{path.name}: {bad}"


# ---------------------------------------------------------------------------
# C27 — Fluid-to-hazardous effect labeling. may_harm's truth condition says
# the target "does not itself become a hazard"; an already-hazardous target
# (flooded house, crushed car) therefore cannot receive may_harm from the
# fluid that inundated it. The continuing escalation is increases_risk_to.
# ---------------------------------------------------------------------------
C27_FLUID_LABELS = {"water", "mud", "smoke", "dust", "gas", "chemical"}


@pytest.mark.blocking
@pytest.mark.parametrize("path", list(all_push_test_gts()))
def test_c27_may_harm_never_targets_hazardous(path: Path, main_module):
    gt = _load(path)
    nodes = {str(n.get("id", "")): n for n in gt.get("nodes") or []}
    bad: list[str] = []
    for e in gt.get("edges") or []:
        if str(e.get("effect", "")).strip() != "may_harm":
            continue
        if str(e.get("source", "")) == str(e.get("target", "")):
            continue
        tgt = nodes.get(str(e.get("target", "")), {})
        tgt_state = main_module.canonicalize_state(str(tgt.get("state", "")).strip())
        if tgt.get("hazardous") and tgt_state in main_module.HAZARD_BEARING_STATES:
            bad.append(
                f"{e.get('source')} --may_harm--> {e.get('target')} ({tgt_state}): "
                f"target is already hazardous; use increases_risk_to"
            )
    assert not bad, f"{path.name}: {bad}"


# ---------------------------------------------------------------------------
# C28 — Distress states on living beings only. A GT must never put an
# at-risk state (including synonyms: trapped, stranded, clinging...) on a
# vehicle or structure; the person inside is a separate entity.
# ---------------------------------------------------------------------------
@pytest.mark.blocking
@pytest.mark.parametrize("path", list(all_push_test_gts()))
def test_c28_distress_states_living_only(path: Path, main_module):
    gt = _load(path)
    bad: list[str] = []
    for n in gt.get("nodes") or []:
        canon = main_module.canonicalize_state(str(n.get("state", "")).strip())
        label = str(n.get("label", "")).strip().lower()
        if canon in main_module.AT_RISK_STATES and label not in PERSONISH_LABELS:
            bad.append(f"{n.get('id')} ({label}) state={n.get('state')}")
    assert not bad, f"{path.name}: distress states on non-living entities: {bad}"


# ---------------------------------------------------------------------------
# C29 — bbox sanity (Phase 1). Boxes are optional; when present they must be
# normalized [x1,y1,x2,y2] with 0<=x1<x2<=1, 0<=y1<y2<=1. Same for every
# member box in a representative's "represents" list.
# ---------------------------------------------------------------------------
def _bbox_ok(b) -> bool:
    try:
        x1, y1, x2, y2 = [float(v) for v in b]
    except Exception:
        return False
    return 0.0 <= x1 < x2 <= 1.0 and 0.0 <= y1 < y2 <= 1.0


@pytest.mark.blocking
@pytest.mark.parametrize("path", list(all_push_test_gts()))
def test_c29_bbox_sanity(path: Path):
    gt = _load(path)
    bad: list[str] = []
    for n in gt.get("nodes") or []:
        if "bbox" in n and not _bbox_ok(n["bbox"]):
            bad.append(f"{n.get('id')}: bad bbox {n['bbox']}")
        for i, m in enumerate(n.get("represents") or []):
            if not _bbox_ok(m):
                bad.append(f"{n.get('id')}: bad represents[{i}] {m}")
    assert not bad, f"{path.name}: {bad}"


# ---------------------------------------------------------------------------
# C30 — Minimal self-loop rule in GT files: a worsens self-loop may exist
# only on a node with no other edges.
# ---------------------------------------------------------------------------
@pytest.mark.blocking
@pytest.mark.parametrize("path", list(all_push_test_gts()))
def test_c30_minimal_self_loop(path: Path):
    gt = _load(path)
    edges = gt.get("edges") or []
    connected = {x for e in edges for x in (str(e.get("source", "")), str(e.get("target", "")))
                 if str(e.get("source", "")) != str(e.get("target", ""))}
    bad = [str(e.get("source", "")) for e in edges
           if str(e.get("source", "")) == str(e.get("target", "")) and str(e.get("source", "")) in connected]
    assert not bad, f"{path.name}: redundant self-loops on {bad}"
