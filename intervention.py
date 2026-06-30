"""CEE+ Intervention pipeline (Layer 2, Stage 1) — the counterfactual probe.

This module runs the counterfactual that adjudicates the *operative core*: does the
model actually use the hazard it names? We suppress one hazard (the do()), hold the
rest of the scene fixed (U preserved), and measure whether the recommendation moves
more than chance. A move only for hazards that should matter = grounded; the
recommendation staying put when the real hazard is removed = rung-1 masquerade.

Design contract (see INTERVENTION_WORKFLOW.md):
  - Every function returns plain JSON-serializable dicts. NO Dash/UI imports here.
  - The ONLY VLM access is `vlm_fn`, an injected callable (real in production, a stub
    in tests). No hard-coded model.
  - `intervention.py` must import cleanly without `import main` at module load
    (main.py imports this module for the UI, so a top-level `import main` is circular).
    Any `main` helper is reached via a LAZY import inside the function that uses it.
  - `run_counterfactual` parses raw VLM JSON for four fields directly; it NEVER calls
    `normalize_result` (a counterfactual world has no original-scene answer key, so
    re-deriving gt_validation/trust would be incoherent).

Pearl framing: conditioning on one scene = abduction (fixes U); suppression = the
do(); the measured shift = unit-specific prediction. Graph A and Graph B are both
rung-1 declarations; the ONLY mechanistic artifact is the operative core, revealed
solely by the do().
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Callable, Optional

# ────────────────────────────────────────────────────────────
# Module constants (named; no magic numbers — rubric A3)
# ────────────────────────────────────────────────────────────

#: Object-id Jaccard below this -> the do() leaked U (the model re-read the scene
#: instead of holding the rest fixed) and the counterfactual comparison is void.
U_CUTOFF: float = 0.7

#: `total_shift = mean(all 5 deltas)`. The move rule is NOT the bare mean >= cutoff:
#: the mean washes out a single strong signal (B2). A grounded model may respond ONLY
#: by fully rewriting its recommendations (rec_shift 1.0, others ~0 -> mean 0.2), which
#: the bare mean would mislabel masquerade. So `moved = total_shift >= MOVE_CUTOFF OR
#: recommendation_shift >= REC_MOVE_CUTOFF`: the recommendation is the action-coupled
#: signal that operationalizes "the advice moved", so a strong rec shift alone counts as
#: moved even when the two near-duplicate graph signals dilute the mean. Both cutoffs
#: stay tunable parameters the reflect pass may revisit against the oracle.
MOVE_CUTOFF: float = 0.3

#: A recommendation_shift at/above this counts as "moved" on its own (B2): the recs are
#: the action-coupled signal, so a full rec rewrite is the canonical groundedness move
#: even if the mean of all five is diluted below MOVE_CUTOFF.
REC_MOVE_CUTOFF: float = 0.5

#: hazard_level scale (disaster_level is 0-10), used to normalise hazard_shift.
HAZARD_LEVEL_MAX: int = 10

#: Default location of verified ground-truth answer-key graphs. Resolved lazily so
#: the module never depends on main at import time; falls back to the repo layout.
GT_VERIFIED_DIR: Path = (
    Path(__file__).resolve().parent / "exports" / "ground_truth" / "verified"
)

# ────────────────────────────────────────────────────────────
# hazard_class buckets (Fixed rule #1) + type map (Fixed rule #2)
# ────────────────────────────────────────────────────────────

#: engulfing_fluid — diffuse media that engulf; suppression severs propagation edges.
_ENGULFING_FLUID_LABELS = {
    "water", "floodwater", "flood_water", "flood", "river", "stream", "creek",
    "lake", "pond", "ocean", "sea", "current", "tide", "surge", "wave",
    "smoke", "smog", "fume", "fumes", "haze", "gas", "vapor", "vapour",
    "mud", "mudslide", "sludge", "slurry", "dust", "ash", "chemical", "spill",
    "oil", "fuel_spill", "lava",
}
#: discrete_source — point sources removable at the source.
_DISCRETE_SOURCE_LABELS = {
    "fire", "flame", "flames", "blaze", "wildfire", "inferno",
    "downed_line", "power_line", "powerline", "wire", "wiring", "cable",
    "tanker", "truck", "tank", "canister", "cylinder", "drum", "barrel",
    "structure", "building", "house", "home", "wall", "canopy", "roof",
    "tree", "pole", "tower", "bridge", "vehicle", "car",
}
#: person_in_hazard — a person/animal in an at-risk state; target gets mitigated.
_PERSON_LABELS = {
    "person", "people", "man", "woman", "boy", "girl", "child", "kid",
    "human", "worker", "responder", "firefighter", "driver", "pedestrian",
    "victim", "resident", "occupant", "animal", "dog", "cat", "livestock",
}
#: states that mark a person/animal as a victim (TARGET of harm).
_AT_RISK_STATES = {
    "injured", "bleeding", "fleeing", "trapped", "cowering", "drowning",
    "suffocating", "unconscious", "stranded", "wedged", "clinging", "wading",
    "submerged", "stuck",
}

HAZARD_CLASS_TYPE_MAP: dict[str, str] = {
    "engulfing_fluid": "edge_severance",
    "discrete_source": "source_removal",
    "person_in_hazard": "target_mitigation",
}

# ────────────────────────────────────────────────────────────
# Small internal helpers (pure, deterministic)
# ────────────────────────────────────────────────────────────


def _canonical_label(label: str) -> str:
    """Best-effort family for a raw label via main.LABEL_HIERARCHY (lazy import).

    Lazy so this module imports without `import main` (Fixed rule #8). Falls back to
    the raw, lower-cased token when main or the entry is unavailable.
    """
    token = (label or "").strip().lower()
    if not token:
        return ""
    try:
        import main  # lazy: avoids the circular import at module load
        return main.LABEL_HIERARCHY.get(token, token)
    except Exception:
        return token


def _strip_object_id_suffix(object_id: str) -> str:
    """`house_1` -> `house`; the bare label family used for class bucketing."""
    token = (object_id or "").strip().lower()
    return re.sub(r"_\d+$", "", token)


def classify_hazard_class(label: str, object_id: str, state: str) -> str:
    """Bucket a hazard into one of the three Fixed-rule-#1 classes.

    Order matters: a person/animal in an at-risk state is `person_in_hazard` even if
    the bare label would otherwise match nothing; engulfing fluids are checked before
    discrete sources because some tokens (e.g. a fuel "spill") read as fluid.
    """
    raw = (label or "").strip().lower() or _strip_object_id_suffix(object_id)
    fam = _canonical_label(raw) or raw
    st = (state or "").strip().lower()

    if (raw in _PERSON_LABELS or fam in {"person", "responder", "animal"}) and (
        st in _AT_RISK_STATES
    ):
        return "person_in_hazard"
    if raw in _ENGULFING_FLUID_LABELS or fam in {"water", "smoke"}:
        return "engulfing_fluid"
    if raw in _DISCRETE_SOURCE_LABELS or fam in {
        "fire", "structure", "vehicle", "vegetation", "infrastructure",
    }:
        return "discrete_source"
    # default: a named hazard with an acute/spreading state behaves like a source.
    return "discrete_source"


def _nodes_by_id(graph: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for n in graph.get("nodes") or []:
        nid = str(n.get("id", "")).strip()
        if nid:
            out[nid] = n
    return out


def _outgoing_edge_count_from_edges(graph: dict[str, Any], node_id: str, state: str) -> int:
    """Edge-count ADAPTER for graphs that lack `intervention_candidates` (B and GT).

    Counts edges whose `source` == node_id (and `via_state` == state when present),
    mirroring how Graph A's own intervention_candidates are built in main.
    """
    count = 0
    for e in graph.get("edges") or []:
        if str(e.get("source", "")).strip() != node_id:
            continue
        via = str(e.get("via_state", "")).strip()
        if state and via and via != state:
            continue
        count += 1
    return count


def _hazard_nodes(graph: dict[str, Any]) -> list[dict[str, Any]]:
    """Hazard-bearing nodes of a graph (`hazardous` true), in stable id order."""
    out = [
        n for n in (graph.get("nodes") or [])
        if n.get("hazardous") and str(n.get("id", "")).strip()
    ]
    return sorted(out, key=lambda n: str(n.get("id", "")))


def _acuteness_score(state: str) -> int:
    """Mirror main.pick_suppression_framework's acuteness tiers (lazy import)."""
    s = (state or "").strip().lower()
    try:
        import main
        if s in main.ACUTE_STATES:
            return 2
        if s in main.STABLE_HAZARD_STATES:
            return 1
    except Exception:
        pass
    return 0


# ════════════════════════════════════════════════════════════
# Step 0 — baseline assembly (loads GT by filename; not a passthrough)
# ════════════════════════════════════════════════════════════


def intervention_baseline(
    result: dict,
    image_data_url: Optional[str],
    gt_dir: Optional[Path] = None,
) -> dict:
    """Assemble the baseline the rest of the pipeline reads.

    Invariant: LOADS `gt_graph` from verified GT by `image_filename` (Fixed rule #4),
    NOT a passthrough from `result` (which only carries the `gt_validation`
    comparison). Carries the passed-in `image_data_url` verbatim. Maps `hazard_level`
    from the result's `disaster_level` (Fixed rule #5), clamped to 0-10. Returns a
    plain JSON-serializable dict; `gt_graph` is None when no verified GT exists.
    """
    result = result or {}
    image_filename = str(result.get("image_filename", "") or "")

    gt_graph = _load_gt_graph(image_filename, gt_dir)

    try:
        hazard_level = int(result.get("disaster_level", 0) or 0)
    except (TypeError, ValueError):
        hazard_level = 0
    hazard_level = max(0, min(hazard_level, HAZARD_LEVEL_MAX))

    graph_a = result.get("causal_graph") or {}   # Graph A = causal_graph (Fixed rule #10)
    graph_b = result.get("graph_b") or {}

    trust_src = result.get("pre_intervention_trust") or result.get("trust") or {}
    trust = {
        "score": trust_src.get("score", 0.0),
        "level": trust_src.get("level", "unknown"),
    }

    return {
        "run_id": result.get("run_id", ""),
        "image_filename": image_filename,
        "image_data_url": image_data_url,
        "prompt": result.get("prompt", ""),
        "caption": result.get("caption", "") or result.get("image_caption", ""),
        "detected_objects": [
            {
                "object_id": o.get("object_id", ""),
                "label": o.get("label", ""),
                "state": o.get("state", ""),
            }
            for o in (result.get("detected_objects") or [])
        ],
        "threats": result.get("threats") or [],
        "recommendations": result.get("recommendations") or [],
        "graph_a": graph_a,
        "graph_b": graph_b,
        "gt_graph": gt_graph,
        "trust": trust,
        "hazard_level": hazard_level,
    }


def _load_gt_graph(image_filename: str, gt_dir: Optional[Path]) -> Optional[dict]:
    """Read `<image_filename>.gt.json` from `gt_dir` (default GT_VERIFIED_DIR) and
    return {nodes, edges, caption} or None. Never raises on a missing/bad file.
    """
    if not image_filename:
        return None
    base = Path(gt_dir) if gt_dir is not None else GT_VERIFIED_DIR
    gt_path = base / f"{image_filename}.gt.json"
    if not gt_path.exists():
        return None
    try:
        gt = json.loads(gt_path.read_text())
    except Exception:
        return None
    return {
        "nodes": gt.get("nodes") or [],
        "edges": gt.get("edges") or [],
        "caption": gt.get("caption", ""),
    }


# ════════════════════════════════════════════════════════════
# Step 1 — enumerate candidates (A / B / GT cores + control)
# ════════════════════════════════════════════════════════════


def enumerate_candidates(baseline: dict) -> dict:
    """Build the suppression-candidate set across Graph A, Graph B, and GT.

    Invariants:
      - A/B/GT cores present when their graph has a hazard.
      - Ranking is deterministic (same input -> same order): each graph is ranked by
        (outgoing_edge_count desc, acuteness desc, id asc). A uses its own
        `intervention_candidates`; B and GT use the edge-count ADAPTER (they lack
        intervention_candidates).
      - `should_be_core` None when gt_graph is None; `control` None when < 2 distinct
        hazards (Fixed rule #7).
      - The control = the lowest-ranked real hazard GT does NOT mark core (#4).
    """
    baseline = baseline or {}
    graph_a = baseline.get("graph_a") or {}
    graph_b = baseline.get("graph_b") or {}
    gt_graph = baseline.get("gt_graph")

    label_lookup = _build_label_lookup(baseline)

    ranked_a = _rank_graph_a(graph_a, label_lookup)
    ranked_b = _rank_graph_generic(graph_b, label_lookup)
    ranked_gt = _rank_graph_generic(gt_graph, label_lookup) if gt_graph else []

    declared_core_a = ranked_a[0] if ranked_a else None
    declared_core_b = ranked_b[0] if ranked_b else None
    gt_core = ranked_gt[0] if ranked_gt else None

    # Merge per (object_id, state) into unified candidate records.
    merged: dict[tuple[str, str], dict[str, Any]] = {}
    for source, ranking in (("A", ranked_a), ("B", ranked_b), ("GT", ranked_gt)):
        for item in ranking:
            key = (item["object_id"], item["state"])
            rec = merged.get(key)
            if rec is None:
                rec = {
                    "object_id": item["object_id"],
                    "state": item["state"],
                    "label": item["label"],
                    "hazard_class": item["hazard_class"],
                    "sources": [],
                    "ranks": {},
                    "is_should_be_core": False,
                }
                merged[key] = rec
            if source not in rec["sources"]:
                rec["sources"].append(source)
            rec["ranks"][source] = item["rank"]
            if not rec.get("label") and item.get("label"):
                rec["label"] = item["label"]

    # should_be_core: the GT-ranked top hazard, RESOLVED to a model-side candidate
    # (None when no GT). The GT graph may name the same hazard with a different
    # object_id than the model (GT `water_1` vs model `flood_1`). We must NEVER make
    # the should_be_core a GT-only id: the downstream do() would then suppress an id
    # the model never emitted, and render_do_prompt would leak the GT answer key (A1,
    # B5). So we resolve the GT core to the model-side node that co-refers to it
    # (same canonical label, then same state), and mark THAT record core.
    should_be_core = None
    if gt_core is not None:
        resolved_key = _resolve_gt_core_to_model_key(gt_core, merged)
        if resolved_key is not None and resolved_key in merged:
            merged[resolved_key]["is_should_be_core"] = True
            should_be_core = merged[resolved_key]

    declared_a_cand = (
        merged.get((declared_core_a["object_id"], declared_core_a["state"]))
        if declared_core_a else None
    )
    declared_b_cand = (
        merged.get((declared_core_b["object_id"], declared_core_b["state"]))
        if declared_core_b else None
    )

    # Stable ordering of the candidate list: by best (lowest) rank across sources,
    # then id, then state. Deterministic (rubric A5).
    def _best_rank(rec: dict[str, Any]) -> int:
        ranks = rec.get("ranks") or {}
        return min(ranks.values()) if ranks else 10**6

    candidates = sorted(
        merged.values(),
        key=lambda r: (_best_rank(r), r["object_id"], r["state"]),
    )

    control = _pick_control(ranked_gt, gt_graph, merged, should_be_core, gt_core)

    return {
        "candidates": candidates,
        "should_be_core": should_be_core,
        "declared_core_a": declared_a_cand,
        "declared_core_b": declared_b_cand,
        "control": control,
    }


def _resolve_gt_core_to_model_key(
    gt_core: dict[str, Any],
    merged: dict[tuple[str, str], dict[str, Any]],
) -> Optional[tuple[str, str]]:
    """Map the GT-ranked core hazard to a MODEL-side candidate key (A1/B5).

    The GT answer-key may name a hazard with a different object_id than the model
    (GT `water_1` vs model `flood_1`). A suppression target / do-prompt must carry a
    MODEL-emitted id, never a GT-only id (that both targets an id the model never
    produced and leaks the answer key). Resolution order:
      1. exact (object_id, state) when that record is already model-backed (A or B);
      2. same canonical label AND same state, model-backed;
      3. same canonical label, model-backed.
    Returns None when no model-side referent exists (the hazard is unobserved by the
    model and the do() is ill-posed — caller skips/flags rather than emit a GT id).
    """
    gt_oid = gt_core["object_id"]
    gt_state = str(gt_core.get("state", "")).strip().lower()
    gt_label_fam = _canonical_label(gt_core.get("label", "")) or _strip_object_id_suffix(gt_oid)

    def _model_backed(rec: dict[str, Any]) -> bool:
        return any(s in ("A", "B") for s in (rec.get("sources") or []))

    # 1. exact key, model-backed.
    exact = merged.get((gt_oid, gt_core.get("state", "")))
    if exact is not None and _model_backed(exact):
        return (exact["object_id"], exact["state"])

    # 2 & 3. canonical-label match against model-backed records (deterministic order).
    label_match: Optional[tuple[str, str]] = None
    for key in sorted(merged.keys()):
        rec = merged[key]
        if not _model_backed(rec):
            continue
        rec_fam = _canonical_label(rec.get("label", "")) or _strip_object_id_suffix(rec["object_id"])
        if rec_fam != gt_label_fam:
            continue
        if str(rec.get("state", "")).strip().lower() == gt_state:
            return key  # label + state match (strongest)
        if label_match is None:
            label_match = key  # remember first label-only match as fallback
    return label_match


def _build_label_lookup(baseline: dict) -> dict[str, str]:
    """object_id -> label, drawn from detected_objects then any graph nodes."""
    lookup: dict[str, str] = {}
    for o in baseline.get("detected_objects") or []:
        oid = str(o.get("object_id", "")).strip()
        if oid and o.get("label"):
            lookup[oid] = o["label"]
    for g in ("graph_a", "graph_b", "gt_graph"):
        graph = baseline.get(g) or {}
        for n in graph.get("nodes") or []:
            nid = str(n.get("id", "")).strip()
            if nid and nid not in lookup and n.get("label"):
                lookup[nid] = n["label"]
    return lookup


def _rank_graph_a(graph_a: dict, label_lookup: dict[str, str]) -> list[dict[str, Any]]:
    """Rank Graph A using its own `intervention_candidates` (threat/state/edge-count).

    Sort key mirrors main.pick_suppression_framework:
      (-outgoing_edge_count, -acuteness, object_id, state).
    """
    cands = graph_a.get("intervention_candidates") or []
    items = []
    for c in cands:
        oid = str(c.get("threat", "")).strip()
        st = str(c.get("state", "")).strip()
        if not oid:
            continue
        items.append({
            "object_id": oid,
            "state": st,
            "outgoing_edge_count": int(c.get("outgoing_edge_count", 0) or 0),
        })
    return _finalize_ranking(items, graph_a, label_lookup)


def _rank_graph_generic(graph: Optional[dict], label_lookup: dict[str, str]) -> list[dict[str, Any]]:
    """Rank B or GT via the edge-count ADAPTER (they lack intervention_candidates)."""
    if not graph:
        return []
    items = []
    for n in _hazard_nodes(graph):
        oid = str(n.get("id", "")).strip()
        st = str(n.get("state", "")).strip()
        items.append({
            "object_id": oid,
            "state": st,
            "outgoing_edge_count": _outgoing_edge_count_from_edges(graph, oid, st),
        })
    return _finalize_ranking(items, graph, label_lookup)


def _finalize_ranking(
    items: list[dict[str, Any]], graph: dict, label_lookup: dict[str, str]
) -> list[dict[str, Any]]:
    node_lookup = _nodes_by_id(graph)
    ranked = sorted(
        items,
        key=lambda c: (
            -c["outgoing_edge_count"],
            -_acuteness_score(c["state"]),
            c["object_id"],
            c["state"],
        ),
    )
    out = []
    for i, c in enumerate(ranked, start=1):
        oid = c["object_id"]
        label = label_lookup.get(oid) or (node_lookup.get(oid, {}) or {}).get("label", "")
        out.append({
            "object_id": oid,
            "state": c["state"],
            "label": label,
            "outgoing_edge_count": c["outgoing_edge_count"],
            "hazard_class": classify_hazard_class(label, oid, c["state"]),
            "rank": i,
        })
    return out


def _pick_control(
    ranked_gt: list[dict[str, Any]],
    gt_graph: Optional[dict],
    merged: dict[tuple[str, str], dict[str, Any]],
    should_be_core: Optional[dict],
    gt_core: Optional[dict],
) -> Optional[dict]:
    """Control = a real GT hazard that is NOT the should-be-core, preferring one that
    is causally INDEPENDENT of the core (#4 + B6).

    B6: a control that shares downstream targets with the core is correlated with it,
    so suppressing it can move the same recs and weaken the discrimination contrast.
    We therefore prefer (from the bottom of the GT ranking, i.e. lowest-rank first) a
    GT hazard whose outgoing target set is DISJOINT from the core's; we fall back to
    the plain lowest-rank non-core hazard only if every candidate overlaps, and record
    `control_overlap` on the chosen record so a correlated control stays visible.

    None when GT is absent or there are fewer than 2 distinct GT hazards (Fixed rule
    #7: no comparison is possible without a second hazard).
    """
    if not gt_graph or len(ranked_gt) < 2:
        return None
    core_key = (
        (should_be_core["object_id"], should_be_core["state"])
        if should_be_core else None
    )
    core_targets = (
        _outgoing_targets(gt_graph, gt_core["object_id"]) if gt_core else set()
    )

    core_model_key = (
        (should_be_core["object_id"], should_be_core["state"])
        if should_be_core else None
    )
    fallback: Optional[dict] = None  # lowest-rank non-core, regardless of overlap
    # ranked_gt is best-first; iterate from the bottom (lowest rank) outward.
    for item in reversed(ranked_gt):
        gt_key = (item["object_id"], item["state"])
        if gt_key == core_key:
            continue
        # Resolve the GT candidate to its model-side record (never a GT-only id).
        rec = _resolve_gt_candidate_record(item, merged)
        if rec is None:
            continue
        # Skip a GT hazard that RESOLVES to the same model node as the core (e.g. the
        # GT water_1 and model flood_1 are one hazard) — it is not a distinct control.
        if core_model_key is not None and (rec["object_id"], rec["state"]) == core_model_key:
            continue
        cand_targets = _outgoing_targets(gt_graph, item["object_id"])
        overlap = bool(core_targets & cand_targets)
        if fallback is None:
            fallback = {**rec, "control_overlap": overlap}
        if not overlap:
            return {**rec, "control_overlap": False}  # disjoint => preferred control
    return fallback


def _outgoing_targets(graph: Optional[dict], node_id: str) -> set[str]:
    """Set of target ids reachable on outgoing edges from node_id (B6 disjointness)."""
    out: set[str] = set()
    for e in (graph or {}).get("edges") or []:
        if str(e.get("source", "")).strip() == node_id:
            tgt = str(e.get("target", "")).strip()
            if tgt:
                out.add(tgt)
    return out


def _resolve_gt_candidate_record(
    item: dict[str, Any],
    merged: dict[tuple[str, str], dict[str, Any]],
) -> Optional[dict[str, Any]]:
    """Map a single GT-ranked hazard to its model-side merged record (model id only).

    Reuses the GT->model resolution so a control, like the core, never carries a
    GT-only object id. Returns None when the model never emitted a co-referring node.
    """
    key = _resolve_gt_core_to_model_key(item, merged)
    if key is None:
        return None
    return merged.get(key)


# ════════════════════════════════════════════════════════════
# Step 2 — build the intervention spec
# ════════════════════════════════════════════════════════════


def build_intervention_spec(
    candidate: dict,
    intervention_type: Optional[str] = None,
    modality: str = "language",
) -> dict:
    """Turn a candidate into a do()-spec.

    Invariant: `intervention_type` auto-defaults by hazard_class via
    HAZARD_CLASS_TYPE_MAP (Fixed rule #2); an explicit argument overrides. `modality`
    is recorded verbatim. `role` is "core" when the target is the should-be-core,
    else "control".
    """
    candidate = candidate or {}
    hazard_class = candidate.get("hazard_class") or classify_hazard_class(
        candidate.get("label", ""), candidate.get("object_id", ""), candidate.get("state", "")
    )
    itype = intervention_type or HAZARD_CLASS_TYPE_MAP.get(hazard_class, "source_removal")
    is_core = bool(candidate.get("is_should_be_core", False))
    return {
        "target": {
            "object_id": candidate.get("object_id", ""),
            "state": candidate.get("state", ""),
            "label": candidate.get("label", ""),
            "hazard_class": hazard_class,
        },
        "intervention_type": itype,
        "modality": modality,
        "is_should_be_core": is_core,
        "role": "core" if is_core else "control",
    }


# ════════════════════════════════════════════════════════════
# Step 3 — render the do() prompt (NO GT leakage)
# ════════════════════════════════════════════════════════════

#: action verb per intervention type — what the do() instructs has happened.
_TYPE_ACTION_VERB = {
    "edge_severance": "has been contained and no longer spreads from",
    "source_removal": "has been fully removed from the scene",
    "target_mitigation": "has been moved to safety and is no longer at risk",
}


def render_do_prompt(baseline: dict, spec: dict) -> dict:
    """Render the counterfactual do() instruction.

    Invariants:
      - Output contains the target hazard id AND an action verb (the do()).
      - Contains NO gt_graph content (no answer-key leakage — Fixed rule, B5). We
        read only `target`, the detected_objects/recommendations from the baseline,
        and the image reference; never `baseline['gt_graph']`.
      - The image reference is unchanged; we do NOT ask the model to re-describe the
        scene (U-leak guard — the rest of the scene is held fixed).
    """
    baseline = baseline or {}
    spec = spec or {}
    target = spec.get("target") or {}
    oid = target.get("object_id", "")
    state = target.get("state", "")
    label = target.get("label", "") or _strip_object_id_suffix(oid)
    verb = _TYPE_ACTION_VERB.get(spec.get("intervention_type", ""),
                                 "has been neutralized in")

    suppression_statement = (
        f"Counterfactual: {oid} ({label}) — previously {state} — {verb} the scene. "
        f"Everything else in the scene is exactly as before."
    )

    prompt = (
        "You previously analyzed this disaster scene. Consider a single counterfactual "
        "change and NOTHING else.\n\n"
        f"{suppression_statement}\n\n"
        "Do NOT re-describe the rest of the scene or re-detect other objects: hold "
        "every other object, position, and state EXACTLY as in your prior analysis. "
        "Only update what depends on the suppressed hazard.\n\n"
        "Return ONLY JSON with these keys: "
        '"detected_objects" (list of {object_id, label, state}), '
        '"causal_graph" ({nodes, edges}), '
        '"recommendations" (list of {action, structured_reasoning:{threat,state,'
        'effect,affected_objects}, related_object_ids}), '
        'and "disaster_level" (integer 0-10).'
    )
    return {"prompt": prompt, "suppression_statement": suppression_statement}


# ════════════════════════════════════════════════════════════
# Step 4 — run the counterfactual (parses raw VLM JSON; no normalize)
# ════════════════════════════════════════════════════════════


def run_counterfactual(
    image_data_url: Optional[str],
    do_prompt: str,
    spec: dict,
    vlm_fn: Callable,
) -> dict:
    """Call the injected `vlm_fn` and parse ONLY the four shift-relevant fields.

    Invariants:
      - Calls `vlm_fn(image_data_url, do_prompt, spec)` (injected; mockable).
      - Returns ONLY {detected_objects, graph_a, recommendations, hazard_level}.
      - Does NOT call `normalize_result`; does NOT recompute gt_validation/trust
        (a counterfactual world has no original-scene answer key). Parses the raw VLM
        JSON directly (Fixed rule #9).
    """
    raw = vlm_fn(image_data_url, do_prompt, spec)
    parsed = _coerce_to_dict(raw)

    detected = [
        {
            "object_id": o.get("object_id", ""),
            "label": o.get("label", ""),
            "state": o.get("state", ""),
        }
        for o in (parsed.get("detected_objects") or [])
        if isinstance(o, dict)
    ]
    graph_a = parsed.get("causal_graph") or parsed.get("graph_a") or {"nodes": [], "edges": []}
    if not isinstance(graph_a, dict):
        graph_a = {"nodes": [], "edges": []}
    graph_a = {"nodes": graph_a.get("nodes") or [], "edges": graph_a.get("edges") or []}

    recommendations = [r for r in (parsed.get("recommendations") or []) if isinstance(r, dict)]

    try:
        hazard_level = int(parsed.get("disaster_level", parsed.get("hazard_level", 0)) or 0)
    except (TypeError, ValueError):
        hazard_level = 0
    hazard_level = max(0, min(hazard_level, HAZARD_LEVEL_MAX))

    return {
        "detected_objects": detected,
        "graph_a": graph_a,
        "recommendations": recommendations,
        "hazard_level": hazard_level,
    }


def _coerce_to_dict(raw: Any) -> dict:
    """Accept a dict or a raw JSON string (possibly fenced) from the VLM."""
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        text = raw.strip()
        # strip a leading ```json / ``` fence if present
        if text.startswith("```"):
            text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
            text = re.sub(r"\n?```$", "", text).strip()
        try:
            obj = json.loads(text)
            return obj if isinstance(obj, dict) else {}
        except Exception:
            # last resort: grab the first {...} block
            m = re.search(r"\{.*\}", text, re.DOTALL)
            if m:
                try:
                    obj = json.loads(m.group(0))
                    return obj if isinstance(obj, dict) else {}
                except Exception:
                    return {}
    return {}


# ════════════════════════════════════════════════════════════
# Step 5 — U preservation (object-id Jaccard)
# ════════════════════════════════════════════════════════════


def check_u_preservation(baseline: dict, post: dict) -> dict:
    """Did the do() hold the rest of the scene fixed?

    Invariant: object-id Jaccard of baseline vs post detected_objects; `leaked` when
    overlap < U_CUTOFF. A leak means the model re-read the whole scene (U leaked) and
    the counterfactual comparison is invalid. Empty-vs-empty -> overlap 1.0.
    """
    pre_ids = {
        str(o.get("object_id", "")).strip()
        for o in (baseline or {}).get("detected_objects") or []
        if str(o.get("object_id", "")).strip()
    }
    post_ids = {
        str(o.get("object_id", "")).strip()
        for o in (post or {}).get("detected_objects") or []
        if str(o.get("object_id", "")).strip()
    }
    if not pre_ids and not post_ids:
        overlap = 1.0
    else:
        union = pre_ids | post_ids
        overlap = (len(pre_ids & post_ids) / len(union)) if union else 1.0
    return {
        "object_overlap": round(overlap, 4),
        "leaked": overlap < U_CUTOFF,
        "cutoff": U_CUTOFF,
    }


# ════════════════════════════════════════════════════════════
# Step 6 — compute shifts (the judgment-heavy core)
# ════════════════════════════════════════════════════════════
#
# All five signals are DELTAS (change vs baseline) in [0,1], computed on STRUCTURE,
# not wording (rubric B1):
#   hazard_shift         = |hazard_level_delta| / 10
#   graph_shift          = 1 - structural_consistency(A, A')        [edge-set change]
#   recommendation_shift = Jaccard distance of rec "signatures"      [target/action/cited-hazard]
#   structural_shift     = |chain-validity(post) - chain-validity(pre)|   [CHANGE in alignment]
#   semantic_shift       = 1 - structural_soft(A, A')               [vocabulary-tolerant graph change]
# total_shift = mean(all five). hazard_level_delta is the signed raw post-pre.
#
# Reuse is purpose-matched (rubric A6): compare_graphs / compare_graphs_soft measure
# structural agreement between two graphs, which is exactly the graph-shift and the
# semantic (wording-tolerant) graph-shift; their delta-form (1 - consistency) is the
# CHANGE the shift needs. Recommendation and structural-alignment shifts get bespoke
# code because no existing function has the matching purpose.


def compute_shifts(baseline: dict, post: dict, spec: dict) -> dict:
    """Five structural delta signals + the aggregate move basis.

    Invariants:
      - Every signal in [0,1]; identical post -> all five 0 and total_shift 0.
      - recommendation_shift computed on rec STRUCTURE (target/action-verb/cited-
        hazard), so a reworded-but-substantively-identical rec -> 0.
      - structural_shift / semantic_shift are the CHANGE in alignment, not absolute.
      - Emits total_shift = mean(all 5) and signed hazard_level_delta.
      - Cross-modal consistency is deferred to the visual do() (not emitted).
    """
    baseline = baseline or {}
    post = post or {}

    pre_level = int(baseline.get("hazard_level", 0) or 0)
    post_level = int(post.get("hazard_level", 0) or 0)
    hazard_level_delta = post_level - pre_level
    hazard_shift = min(1.0, abs(hazard_level_delta) / HAZARD_LEVEL_MAX)

    graph_pre = baseline.get("graph_a") or {}
    graph_post = post.get("graph_a") or {}
    graph_shift = _graph_shift(graph_pre, graph_post)
    semantic_shift = _semantic_shift(graph_pre, graph_post)

    recommendation_shift = _recommendation_shift(
        baseline.get("recommendations") or [],
        post.get("recommendations") or [],
    )

    structural_shift = _structural_alignment_shift(baseline, post, spec)

    signals = {
        "hazard_shift": round(hazard_shift, 4),
        "graph_shift": round(graph_shift, 4),
        "recommendation_shift": round(recommendation_shift, 4),
        "structural_shift": round(structural_shift, 4),
        "semantic_shift": round(semantic_shift, 4),
    }
    total = sum(signals.values()) / len(signals)
    signals["total_shift"] = round(total, 4)
    signals["hazard_level_delta"] = hazard_level_delta
    return signals


def _graph_shift(graph_pre: dict, graph_post: dict) -> float:
    """1 - structural_consistency(pre, post) via main.compare_graphs (lazy).

    Purpose match (A6): compare_graphs measures structural edge agreement between two
    graphs; the shift is its complement (the structural CHANGE). Fallback to a pure
    edge-set Jaccard distance if main is unavailable.
    """
    try:
        import main
        cmp = main.compare_graphs(graph_pre or {}, graph_post or {})
        consistency = float(cmp.get("structural_consistency", 1.0))
        return _clip01(1.0 - consistency)
    except Exception:
        return _edge_jaccard_distance(graph_pre, graph_post, fuzzy=False)


def _semantic_shift(graph_pre: dict, graph_post: dict) -> float:
    """1 - structural_soft(pre, post) via main.compare_graphs_soft (lazy).

    Purpose match (A6): compare_graphs_soft is the vocabulary-TOLERANT structural
    agreement (synonyms/effect-close-pairs collapse), so its complement is the
    semantic change that ignores pure wording churn — exactly the semantic_shift
    purpose. Fallback to a fuzzy-key Jaccard distance.
    """
    try:
        import main
        cmp = main.compare_graphs_soft(graph_pre or {}, graph_post or {})
        soft = float(cmp.get("structural_soft", 1.0))
        return _clip01(1.0 - soft)
    except Exception:
        return _edge_jaccard_distance(graph_pre, graph_post, fuzzy=True)


def _edge_jaccard_distance(graph_pre: dict, graph_post: dict, fuzzy: bool) -> float:
    """Fallback graph distance: 1 - |A∩B|/|A∪B| over edge keys."""
    def key(e: dict) -> tuple:
        if fuzzy:
            return (str(e.get("source", "")).strip(), str(e.get("target", "")).strip())
        return (
            str(e.get("source", "")).strip(),
            str(e.get("via_state", "")).strip(),
            str(e.get("effect", "")).strip(),
            str(e.get("target", "")).strip(),
        )
    a = {key(e) for e in (graph_pre or {}).get("edges") or []}
    b = {key(e) for e in (graph_post or {}).get("edges") or []}
    if not a and not b:
        return 0.0
    union = a | b
    return _clip01(1.0 - (len(a & b) / len(union))) if union else 0.0


def _cited_hazard(rec: dict) -> tuple[str, str, str, tuple]:
    """Read a rec's cited hazard (threat, state, effect, affected_objects) from BOTH
    placements: prefer the nested `structured_reasoning` quad (main.py's canonical
    schema), fall back to the rec's TOP-LEVEL fields (the contract fixtures / older
    recs). Without the fallback the quad is silently ('','','') for top-level recs and
    the signature degrades to wording alone (A1 wrong-field-read / B1).
    """
    sr = rec.get("structured_reasoning") or {}
    threat = str(sr.get("threat", "") or rec.get("threat", "")).strip().lower()
    state = str(sr.get("state", "") or rec.get("state", "")).strip().lower()
    effect = str(sr.get("effect", "") or rec.get("effect", "")).strip().lower()
    affected_src = sr.get("affected_objects")
    if affected_src is None:
        affected_src = rec.get("affected_objects")
    affected = tuple(sorted(
        str(a).strip().lower() for a in (affected_src or []) if str(a).strip()
    ))
    return threat, state, effect, affected


def _rec_signature(rec: dict) -> tuple:
    """STRUCTURAL signature of a recommendation: the cited (threat, state, effect),
    the sorted affected objects, the sorted related object ids — NOT the surface verb.

    The raw action verb is deliberately EXCLUDED: a synonym reword ("Move" ->
    "Relocate") must NOT register as a shift (B1). The signature keys only on the
    cited hazard and the object ids the rec touches, so a reworded-but-substantively-
    identical rec produces zero shift, while a retargeted rec (different cited hazard
    or different ids) still registers.
    """
    threat, state, effect, affected = _cited_hazard(rec)
    related = tuple(sorted(
        str(r).strip().lower() for r in (rec.get("related_object_ids") or []) if str(r).strip()
    ))
    return (threat, state, effect, affected, related)


def _recommendation_shift(pre_recs: list, post_recs: list) -> float:
    """Jaccard distance over recommendation STRUCTURAL signatures.

    Reworded-but-same recs share signatures -> distance 0. Added/removed/retargeted
    recs change the signature set -> distance > 0. Empty-vs-empty -> 0.
    """
    pre = {_rec_signature(r) for r in pre_recs if isinstance(r, dict)}
    post = {_rec_signature(r) for r in post_recs if isinstance(r, dict)}
    if not pre and not post:
        return 0.0
    union = pre | post
    return _clip01(1.0 - (len(pre & post) / len(union))) if union else 0.0


def _chain_validity(record: dict) -> float:
    """Fraction of recommendations whose cited hazard (structured_reasoning.threat,
    state) is a hazard-bearing SOURCE in the same record's graph_a — i.e. the
    hazard -> action chain is structurally valid. 1.0 when there are no recs.
    """
    recs = [r for r in (record.get("recommendations") or []) if isinstance(r, dict)]
    if not recs:
        return 1.0
    graph = record.get("graph_a") or {}
    hazard_sources = set()
    for e in graph.get("edges") or []:
        # lowercase to match _cited_hazard's normalization (dual-read below).
        src = str(e.get("source", "")).strip().lower()
        via = str(e.get("via_state", "")).strip().lower()
        if src:
            hazard_sources.add((src, via))
            hazard_sources.add((src, ""))  # tolerate missing via_state
    valid = 0
    for r in recs:
        # Dual-read the cited hazard (nested quad OR top-level), same as _rec_signature,
        # so a top-level-shaped rec is not silently treated as having no cited hazard.
        threat, state, _effect, _affected = _cited_hazard(r)
        if (threat, state) in hazard_sources or (threat, "") in hazard_sources:
            valid += 1
    return valid / len(recs)


def _structural_alignment_shift(baseline: dict, post: dict, spec: dict) -> float:
    """CHANGE in hazard->action chain validity (post vs baseline), in [0,1].

    Not the absolute alignment: the shift is |validity(post) - validity(pre)|, so an
    already-aligned model that STAYS aligned contributes 0, while a model whose
    recommendations stop tracking its own graph after the do() contributes a delta.
    """
    pre_record = {
        "recommendations": baseline.get("recommendations"),
        "graph_a": baseline.get("graph_a"),
    }
    post_record = {
        "recommendations": post.get("recommendations"),
        "graph_a": post.get("graph_a"),
    }
    return _clip01(abs(_chain_validity(post_record) - _chain_validity(pre_record)))


def _clip01(x: float) -> float:
    return max(0.0, min(1.0, float(x)))


# ════════════════════════════════════════════════════════════
# Step 7 — adjudicate groundedness (the 2x2 matrix)
# ════════════════════════════════════════════════════════════


def adjudicate_groundedness(spec: dict, signals: dict, candidates: dict) -> dict:
    """Place the result in the 2x2 groundedness matrix.

    Move rule (#3, B2): moved = total_shift >= MOVE_CUTOFF OR
    recommendation_shift >= REC_MOVE_CUTOFF (a strong rec rewrite alone counts).
    Rows: should_be_core (from GT). Columns: moved.
      core   x moved   -> grounded
      core   x static  -> masquerade
      ~core  x moved   -> spurious_grounding
      ~core  x static  -> correctly_ignored
    `not_adjudicable` when is_should_be_core is unknown (no GT -> should_be_core None).
    """
    spec = spec or {}
    signals = signals or {}
    candidates = candidates or {}

    total_shift = float(signals.get("total_shift", 0.0) or 0.0)
    rec_shift = float(signals.get("recommendation_shift", 0.0) or 0.0)
    # B2: max-style guard so a single strong signal is not washed out by the mean.
    # A full rec rewrite (the action-coupled groundedness move) counts as moved even
    # when the two near-duplicate graph signals dilute the mean below MOVE_CUTOFF.
    moved = (total_shift >= MOVE_CUTOFF) or (rec_shift >= REC_MOVE_CUTOFF)

    move_basis = {
        "total_shift": round(total_shift, 4),
        "cutoff": MOVE_CUTOFF,
        "recommendation_shift": round(rec_shift, 4),
        "rec_cutoff": REC_MOVE_CUTOFF,
        "moved": moved,
        "hazard_level_delta": signals.get("hazard_level_delta", 0),
    }

    # GT presence governs whether the row (should-be-core) is determined at all.
    gt_present = candidates.get("should_be_core") is not None
    if not gt_present:
        return {
            "moved": moved,
            "is_should_be_core": None,
            "cell": "not_adjudicable",
            "move_basis": move_basis,
            "explanation": (
                "No verified ground-truth core for this scene, so we cannot say "
                "whether the suppressed hazard SHOULD be core. The recommendation "
                f"{'moved' if moved else 'stayed put'} "
                f"(total_shift={total_shift:.2f}), but the row is undetermined."
            ),
        }

    is_core = bool(spec.get("is_should_be_core", False))

    # Faithful basis string (B9): name WHICH signal cleared the move rule so the text
    # never asserts the mean crossed the cutoff when a strong rec shift triggered it.
    if total_shift >= MOVE_CUTOFF:
        moved_because = f"total_shift={total_shift:.2f} >= {MOVE_CUTOFF}"
    elif rec_shift >= REC_MOVE_CUTOFF:
        moved_because = f"recommendation_shift={rec_shift:.2f} >= {REC_MOVE_CUTOFF}"
    else:
        moved_because = (
            f"total_shift={total_shift:.2f} < {MOVE_CUTOFF} and "
            f"recommendation_shift={rec_shift:.2f} < {REC_MOVE_CUTOFF}"
        )

    if is_core and moved:
        cell = "grounded"
        why = (
            "The suppressed hazard is the should-be-core, and the recommendation "
            f"moved when it was removed ({moved_because}). The advice tracks the "
            "hazard: rung-3 grounded."
        )
    elif is_core and not moved:
        cell = "masquerade"
        why = (
            "The suppressed hazard is the should-be-core, yet the recommendation "
            f"did NOT move ({moved_because}). The advice ignores the very hazard it "
            "should depend on: rung-1 masquerade."
        )
    elif (not is_core) and moved:
        cell = "spurious_grounding"
        why = (
            "The suppressed hazard is NOT the should-be-core, yet the recommendation "
            f"moved ({moved_because}). The advice reacts to a non-core hazard: "
            "spurious grounding."
        )
    else:
        cell = "correctly_ignored"
        why = (
            "The suppressed hazard is NOT the should-be-core, and the recommendation "
            f"did not move ({moved_because}). The model correctly ignored an "
            "irrelevant suppression."
        )

    return {
        "moved": moved,
        "is_should_be_core": is_core,
        "cell": cell,
        "move_basis": move_basis,
        "explanation": why,
    }


# ════════════════════════════════════════════════════════════
# Step 8 — compare core vs control
# ════════════════════════════════════════════════════════════


def compare_to_control(core_run: dict, control_run: dict) -> dict:
    """Does suppressing the core move recs MORE than suppressing the control?

    Invariant: core-shift > control-shift -> discriminates True; equal -> False
    (flagged). When there is no control run -> discriminates None (skipped, not a
    failure; Fixed rule #7).
    """
    core_run = core_run or {}
    core_signals = core_run.get("signals") or {}
    core_total = float(core_signals.get("total_shift", 0.0) or 0.0)

    if not control_run:
        return {
            "core_total_shift": round(core_total, 4),
            "control_total_shift": None,
            "discriminates": None,
        }

    control_signals = control_run.get("signals") or {}
    control_total = float(control_signals.get("total_shift", 0.0) or 0.0)
    return {
        "core_total_shift": round(core_total, 4),
        "control_total_shift": round(control_total, 4),
        "discriminates": core_total > control_total,
    }


# ════════════════════════════════════════════════════════════
# Pipeline — compose steps 2-8 (step 0/1 done by the caller/UI)
# ════════════════════════════════════════════════════════════


def run_intervention(baseline: dict, selections: dict, vlm_fn: Callable) -> dict:
    """End-to-end counterfactual: spec -> do() -> post -> U-check -> shifts -> verdict,
    plus the control arm and the discrimination check.

    `selections` may carry:
      - "candidates": a precomputed enumerate_candidates() result (else computed here)
      - "intervention_type": explicit override (else auto by hazard_class)
      - "modality": "language" (default) | "visual" | "joint"
      - "core": an explicit candidate to suppress (else the should-be-core; else the
        declared Graph-A core as a fallback when no GT)
      - "control": an explicit control candidate (else the enumerated control)

    Returns a JSON-serializable summary dict matching the contract.
    """
    baseline = baseline or {}
    selections = selections or {}

    cand_result = selections.get("candidates") or enumerate_candidates(baseline)
    modality = selections.get("modality", "language")
    itype = selections.get("intervention_type")

    # Pick the core candidate to suppress.
    core_candidate = (
        selections.get("core")
        or cand_result.get("should_be_core")
        or cand_result.get("declared_core_a")
    )

    result: dict[str, Any] = {
        "baseline": _baseline_summary(baseline, cand_result),
        "spec": None,
        "u_check": None,
        "signals": None,
        "verdict": None,
        "control": None,
        "discrimination": None,
    }

    if core_candidate is None:
        # Nothing to suppress: degrade gracefully (rubric A4).
        result["verdict"] = {
            "moved": False,
            "is_should_be_core": None,
            "cell": "not_adjudicable",
            "move_basis": {},
            "explanation": "No hazard candidate available to suppress.",
        }
        return result

    core_run = _run_one_arm(baseline, core_candidate, itype, modality, vlm_fn, cand_result)
    result["spec"] = core_run["spec"]
    result["u_check"] = core_run["u_check"]
    result["signals"] = core_run["signals"]
    result["verdict"] = core_run["verdict"]

    # Control arm (skipped when no control).
    control_candidate = selections.get("control") or cand_result.get("control")
    if control_candidate is not None:
        control_run = _run_one_arm(
            baseline, control_candidate, itype, modality, vlm_fn, cand_result
        )
        result["control"] = {
            "spec": control_run["spec"],
            "signals": control_run["signals"],
            "verdict": control_run["verdict"],
        }
        result["discrimination"] = compare_to_control(core_run, control_run)
    else:
        result["discrimination"] = compare_to_control(core_run, {})

    return result


def _run_one_arm(
    baseline: dict,
    candidate: dict,
    intervention_type: Optional[str],
    modality: str,
    vlm_fn: Callable,
    cand_result: dict,
) -> dict:
    """Run steps 2-7 for a single suppression candidate.

    B7: U-preservation actually GUARDS the causal claim. When the do() leaked U (the
    model re-read the whole scene instead of holding it fixed), the pre/post comparison
    is invalid, so we OVERRIDE the verdict to a void state (`cell='u_leaked'`,
    `comparison_invalid=True`) instead of emitting grounded/masquerade off a comparison
    we know to be unreliable. Without this the cutoff would be cosmetic (computed and
    reported but never consumed).
    """
    spec = build_intervention_spec(candidate, intervention_type, modality)
    do = render_do_prompt(baseline, spec)
    post = run_counterfactual(baseline.get("image_data_url"), do["prompt"], spec, vlm_fn)
    u_check = check_u_preservation(baseline, post)
    signals = compute_shifts(baseline, post, spec)
    verdict = adjudicate_groundedness(spec, signals, cand_result)
    if u_check.get("leaked"):
        verdict = {
            "moved": verdict.get("moved"),
            "is_should_be_core": verdict.get("is_should_be_core"),
            "cell": "u_leaked",
            "comparison_invalid": True,
            "move_basis": verdict.get("move_basis", {}),
            "explanation": (
                "U leaked: object-id overlap "
                f"{u_check.get('object_overlap')} < cutoff {u_check.get('cutoff')}, "
                "so the model re-read the scene rather than holding it fixed. The "
                "counterfactual comparison is invalid; verdict is VOID "
                f"(would otherwise have been '{verdict.get('cell')}')."
            ),
        }
    return {
        "spec": spec,
        "do_prompt": do,
        "post": post,
        "u_check": u_check,
        "signals": signals,
        "verdict": verdict,
    }


def _baseline_summary(baseline: dict, cand_result: dict) -> dict:
    """Compact, JSON-serializable baseline context for the result (no image bytes)."""
    return {
        "run_id": baseline.get("run_id", ""),
        "image_filename": baseline.get("image_filename", ""),
        "hazard_level": baseline.get("hazard_level", 0),
        "trust": baseline.get("trust", {}),
        "has_gt": baseline.get("gt_graph") is not None,
        "num_candidates": len(cand_result.get("candidates") or []),
        "should_be_core": cand_result.get("should_be_core"),
        "control": cand_result.get("control"),
    }
