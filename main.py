import base64
from datetime import datetime
import io
import json
import os
from pathlib import Path
import re
import threading
from typing import Any

import dash
import dash_cytoscape as cyto
import requests
from dash import Dash, Input, Output, State, dcc, html
from PIL import Image, ImageDraw


DEFAULT_PROMPT = """Analyze the uploaded image and caption.

## Definitions

- THREAT: a detected entity currently in a hazard-bearing state. It is the source of harm. Example: house_1 with state `burning` (active fire) or `burnt` (settled charred shell — contact hazard). Populates the `threat` slot of every recommendation quad and appears in the `threats` block.
- DANGER: the condition of being exposed to harm. Applies to entities on the receiving end. A person near a burning house is in danger, not "a risk". Represented as the `affected_object` slot of a quad; these entities do not need their own block.
- LATENT THREAT: a detected entity currently in a normal state, positioned so it could flip into a hazard-bearing state if the scene evolves (e.g. a sealed propane tank next to a fire). Current state is normal, so it is NOT a threat yet. Represented as a quad edge with `effect = increases_risk_to` from the active hazard to the latent entity.
- REMAINING_RISK: a per-recommendation prose field describing what this specific action leaves unaddressed. Can reference active threats, latent threats, or entities still in danger.

The word "risk" as a standalone category does not appear in the schema; use the concept above that actually applies.

## State vocabulary

Every detected object has a `state` — a single lowercase adjective or participle describing its current condition. Pick from the lists below. If nothing fits, you may introduce a new single-word adjective provided you can name its non-hazardous counterpart.

Hazard-bearing states (threat-producing):
  burning, burnt, collapsed, collapsing, fallen, crushed, flooded, leaking,
  bleeding, injured, approaching, charging, aiming, coiled, rabid,
  armed, fleeing, striking, rising, spreading, billowing, seeping,
  escalating

Normal states:
  intact, standing, upright, whole, dry, sealed, uninjured, healthy,
  stationary, resting, disengaged, relaxed, unarmed, stable, contained,
  dissipating, steady

An object in a hazard-bearing state appears in `threats`. An object in a normal state does not.

**Fluid / gaseous hazards — important convention.** For water, smoke, gas, dust, free-burning fire-as-substance (not the burning object), and similar diffuse hazards, emit the fluid itself as its own entity with an *active* hazard state (e.g., `water_1` in state `rising` or `spreading`; `smoke_1` in state `billowing`; `gas_1` in state `leaking` or `seeping`). The fluid is the primary source of outward harm propagation. An inundated/affected entity (a flooded car, a smoke-filled room) is also in a hazard-bearing state and thus also appears in `threats` (it's a contact hazard for anyone who approaches), but the propagation to nearby people still flows FROM the fluid in the quads. Pattern: the fluid's quads list the inundated entity as `affected_object`; the inundated entity may have its own quads only when it actively projects further harm (e.g., a burning house that catches a neighboring car).

## Effect vocabulary (truth conditions)

Each recommendation quad uses exactly one `effect` label. Pick the MOST SPECIFIC applicable label. `threatens` is a last resort — use only when no other label applies AND the danger is proximate and unavoidable.

- may_spread_to      — hazard can propagate via physical contiguity (fire, flood, disease)
- may_harm           — threat can injure the affected entity, which does not itself become a hazard
- blocks_access_to   — physical obstruction preventing reach
- isolates           — cuts an entity off from escape or resources
- exposes            — protective barrier removed or breached
- increases_risk_to  — enabling factor; makes another hazard worse or converts a normal entity into a latent threat
- worsens            — escalates a hazard already present on the SAME entity
- threatens          — last resort (see above)

## Causal quad

Each recommendation commits to a four-part structure:

  (threat, state, effect, affected_objects)

`affected_objects` is a LIST of object_ids — use a list with one element when only one entity is affected, or multiple elements when one (threat, state) with the same effect threatens several entities at once. Example: a single burning house threatening two nearby people becomes one recommendation with `affected_objects: ["person_1", "person_2"]`, not two near-duplicate recommendations.

Plain-English template for the `reason` field:
  "Because {threat} is {state}, it {effect} {affected_objects}."
(write the affected_objects naturally, e.g. "person_1 and person_2".)

You may rephrase for fluency, but every object_id and state word in the quad must appear in the reason, and vice versa. Every object_id in `affected_objects` must be mentioned in the reason.

## Reasoning context

When generating recommendations, consider the full scene: every detected_object, every declared threat, and the spatial relationships visible in the image. Surface entities in normal states whose proximity to active threats makes them latent threats. Rank recommendations by weighing life-safety, cascade potential, imminence, and hazard containment together.
{INFERRED_ENTITIES_BLOCK}

## Worked example (format only — do not copy its content)

Scene: a tree has fallen on a parked car; one person stands nearby; a sealed gas canister sits between them.

"detected_objects": [
  {"object_id": "tree_1",     "label": "tree",     "state": "fallen",     "bbox": [10, 40, 300, 400]},
  {"object_id": "car_1",      "label": "car",      "state": "crushed",    "bbox": [120, 260, 340, 420]},
  {"object_id": "person_1",   "label": "person",   "state": "stationary", "bbox": [360, 200, 420, 440]},
  {"object_id": "canister_1", "label": "canister", "state": "sealed",     "bbox": [300, 380, 340, 420]}
]
"threats": [
  {"object_id": "tree_1", "state": "fallen",
   "reason": "tree_1 has fallen onto car_1 and may shift toward person_1."},
  {"object_id": "car_1",  "state": "crushed",
   "reason": "car_1 is crushed under tree_1; structural integrity is compromised."}
]
"recommendations": [
  {"rank": 1,
   "action": "Move person_1 away from tree_1.",
   "reason": "Because tree_1 is fallen, it may_harm person_1 if it shifts further.",
   "related_object_ids": ["tree_1", "person_1"],
   "structured_reasoning": {
     "threat": "tree_1", "state": "fallen",
     "effect": "may_harm", "affected_objects": ["person_1"]
   },
   "expected_consequence": "person_1 is out of tree_1's fall radius.",
   "remaining_risk": "(car_1, crushed) is not addressed; canister_1 remains a latent threat if tree_1 shifts onto it.",
   "possible_follow_up_action": "Stabilize tree_1 before approaching car_1."},
  {"rank": 2,
   "action": "Clear canister_1 from beneath tree_1.",
   "reason": "Because tree_1 is fallen, it increases_risk_to canister_1, which could rupture if tree_1 shifts.",
   "related_object_ids": ["tree_1", "canister_1"],
   "structured_reasoning": {
     "threat": "tree_1", "state": "fallen",
     "effect": "increases_risk_to", "affected_objects": ["canister_1"]
   },
   "expected_consequence": "canister_1 is removed from tree_1's fall radius.",
   "remaining_risk": "(car_1, crushed) hazard is not addressed by this action.",
   "possible_follow_up_action": "Inspect canister_1 for damage before storing."}
]

End of example. Notes: (1) canister_1 is a LATENT THREAT — it appears as an affected_object via `increases_risk_to`, not in the `threats` block, because its own state (`sealed`) is normal. (2) `affected_objects` is a list even when only one entity is affected (single-element list). When a single (threat, state, effect) reaches multiple entities — e.g., a burning house threatening person_1 and person_2 — emit ONE recommendation with `affected_objects: ["person_1", "person_2"]`, not multiple near-duplicate recommendations.

## Output schema

Return valid JSON with exactly these keys:

- scene_summary: one short sentence describing the scene as a whole.
- key_observations: array of short strings describing what you SEE in the scene directly. Use object_ids. Example: "person_1 is facing away from tree_1."
- assumptions: array of short strings describing what you INFER beyond the direct visual evidence. Use object_ids. Example: "person_1 appears uninjured based on posture, though hidden injuries are possible."
- uncertainty_notes: array of short strings describing what you are UNSURE about and why. Use object_ids. Example: "Unclear whether tree_1 is still rooted or fully detached at its base."
- detected_objects: array of:
  - object_id: REQUIRED string of the form "<label>_<N>", where N is 1-indexed per label. Always use "_1" even when only one instance. Do not omit this field.
  - label: singular lowercase noun. Use the MOST SPECIFIC applicable label when sex/age/species is visually apparent: prefer "man", "woman", "child", "boy", "girl" over generic "person"; prefer "dog", "cat", "snake", "tiger" over generic "animal". Use generic categories only when the specific category cannot be determined from the image. The chosen label propagates into object_id (e.g. "man_1", "dog_1").
  - state: REQUIRED, single lowercase adjective or participle from the state vocabulary above (or a compliant extension).
  - bbox: [x_min, y_min, x_max, y_max] in pixel coordinates
- disaster_scenario: "Yes" or "No"
- disaster_type: string
- disaster_level: integer 0–10 (reserve 10 for truly catastrophic; calibrate)
- threats: array of objects with:
  - object_id: REQUIRED, must appear verbatim in detected_objects
  - state: REQUIRED, must match that object's state in detected_objects AND must be a hazard-bearing state
  - reason: short explanation using object_ids
- recommendations: array with one entry per distinct (threat, state) causal logic you are acting on. Do NOT pad to a fixed count.
  - rank: integer (1 = highest priority)
  - action: one specific responder action (no "and"/"then" compounds)
  - reason: plain English following the template above; every object_id named must use object_id form, never a bare label or plural.
  - related_object_ids: array of object_id strings, each appearing verbatim in detected_objects.
  - structured_reasoning (the causal quad):
    - threat:           object_id of the entity whose state drives the hazard
    - state:            hazard-bearing state of threat, matching the `threats` block
    - effect:           one of the 8 effect labels above
    - affected_objects: NON-EMPTY LIST of object_ids of impacted entities. Use a single-element list when only one entity is affected. Use multiple elements when one (threat, state, effect) reaches several entities together.
  - expected_consequence: immediate result of THIS action if it succeeds — not a downstream effect of a different recommendation
  - remaining_risk: must cite at least one (object_id, state) pair from the scene that this action does NOT address. Must differ across recommendations.
  - possible_follow_up_action: string

## Rules (all must hold)

1. Bbox dedup: if two bounding boxes overlap by more than 80% of either box's area, they refer to the same physical object — emit only one detected_objects entry.
2. detected_objects is the single source of truth for object_ids AND states. Any object_id or state used elsewhere in the JSON must match detected_objects verbatim.
3. Never refer to a scene entity by a bare label, a category, or a plural noun outside `label` itself. "man", "residents", "structures", "the car", "the houses" are all INVALID. Use object_ids.
4. Coverage: in each recommendation, every object_id in `reason` must appear in `related_object_ids` AND in the quad (as `threat` or in `affected_objects`); and every object_id in the quad — including every entry of `affected_objects` — must appear in `reason`.
5. One recommendation per distinct (threat, state) causal logic. Two recommendations may NOT share all four quad slots (compare `affected_objects` as a SET — order does not matter), and may NOT have actions that collapse to the same (verb, target) pair. If two would-be recommendations share (threat, state, effect) and just differ in which single entity each affects, MERGE them into one recommendation with both entities in `affected_objects`.
6. Self-reference: `threat` must NOT appear in its own `affected_objects` list with effect `threatens` or `may_harm` (those are already implied by the hazard-bearing state). Use `worsens` for self-escalation, or express the impact on different entities.
7. If disaster_scenario is "Yes", `threats` must be non-empty, and every `structured_reasoning.state` must match the state of its `threat` in the `threats` block.
8. If disaster_scenario is "No", set disaster_type to "N/A", disaster_level to 0, and both `threats` and `recommendations` to empty arrays.

## Before returning — self-check

Verify:
(a) every object_id used anywhere in the JSON appears verbatim in detected_objects
(b) every `state` value is in the state vocabulary or a single-word adjective with a named non-hazardous counterpart
(c) every `effect` value is one of the 8 labels
(d) no quad has `threat` in its own `affected_objects` list with effect `threatens` or `may_harm`
(e) no two recommendations share all four quad slots (compare `affected_objects` as an unordered set)
(f) no two recommendations share an identical `remaining_risk`
(g) `threatens` is used only when no more specific effect applies
(h) every detected_object in a hazard-bearing state appears in `threats`; every detected_object in a normal state does not
(i) no two recommendations have identical or near-identical values in `action` or `expected_consequence`

Return valid JSON only.
"""


INFERRED_ENTITIES_BLOCK = """
You may also reason about scene-implied entities not directly visible — for example, presumed occupants inside a burning house, an unseen driver in a moving car, or animals likely contained in a structure. To reference such an entity in a recommendation, do BOTH of the following:
1. Add a corresponding string to `assumptions` flagging the inferred entity (e.g., "Residents may be inside house_1.").
2. Use a special object_id of the form `presumed_<noun>_in_<existing_object_id>` (e.g., `presumed_residents_in_house_1`, `presumed_driver_in_car_1`) as an entry in the `affected_objects` list of the relevant quad. These ids do NOT need to appear in `detected_objects`. They must always anchor to a real detected_object via the `_in_<object_id>` suffix. They are valid only inside `affected_objects`, never as `threat`.
""".strip()

EMPTY_INFERRED_BLOCK = ""

OBJECT_ID_RE = re.compile(r"\b(?:presumed_[a-z0-9]+(?:_[a-z0-9]+)*_in_)?[a-z][a-z0-9]*_[0-9]+\b")
OBJECT_STATE_PAIR_RE = re.compile(r"\(([a-z][a-z0-9]*(?:_[a-z0-9]+)*_[0-9]+),\s*([a-z][a-z0-9_-]*)\)")

HAZARD_BEARING_STATES = {
    "burning", "burnt", "collapsed", "collapsing", "fallen", "crushed", "flooded",
    "leaking", "bleeding", "injured", "approaching", "charging", "aiming",
    "coiled", "rabid", "armed", "fleeing", "striking", "rising",
    "spreading", "billowing", "seeping", "escalating",
}

NORMAL_STATES = {
    "intact", "standing", "upright", "whole", "dry", "sealed", "uninjured",
    "healthy", "stationary", "resting", "disengaged", "relaxed", "unarmed",
    "stable", "contained", "dissipating", "steady",
}

EFFECT_LABELS = {
    "may_spread_to", "may_harm", "blocks_access_to", "isolates", "exposes",
    "increases_risk_to", "worsens", "threatens",
}


GRAPH_B_PROMPT = """You are extracting the causal graph that explains how hazards in this scene threaten safety. Cover every causal pathway you believe holds — direct harm, cascade between hazards, exposure, proximity risk — regardless of which a responder would address first. Below are the detected_objects and threats from a prior analysis of the same scene. Recommendations are deliberately withheld — derive the causal structure independently from any recommendation list.

## State vocabulary (must match prior analysis verbatim)

Hazard-bearing states: burning, burnt, collapsed, collapsing, fallen, crushed, flooded, leaking, bleeding, injured, approaching, charging, aiming, coiled, rabid, armed, fleeing, striking, rising, spreading, billowing, seeping, escalating

Normal states: intact, standing, upright, whole, dry, sealed, uninjured, healthy, stationary, resting, disengaged, relaxed, unarmed, stable, contained, dissipating, steady

**Fluid / gaseous hazards — important convention.** For water, smoke, gas, dust, free-burning fire-as-substance, and similar diffuse hazards, emit the fluid itself as its own entity with an *active* hazard state (e.g., `water_1` with state `rising` or `spreading`; `smoke_1` with state `billowing`; `gas_1` with state `leaking` or `seeping`). The fluid is the primary source of outward harm propagation. An inundated/affected entity (a flooded car, a smoke-filled room) is also in a hazard-bearing state and thus also has `hazardous: true` (it's a contact threat for anyone who approaches), but the propagation to nearby people flows FROM the fluid via edges. Pattern: the fluid is the source of outgoing edges to bystanders; the inundated entity appears as `target` of the fluid's edge, and may itself be the source of additional edges only when it actively projects further harm (e.g., a burning house that catches a neighboring car).

## Effect vocabulary (truth conditions)

Each edge label = exactly one of (use the most specific applicable):
- may_spread_to      — hazard propagates via physical contiguity
- may_harm           — threat injures the target without target itself becoming a hazard
- blocks_access_to   — physical obstruction
- isolates           — cuts off escape or resources
- exposes            — protective barrier removed
- increases_risk_to  — enabling factor; converts a normal entity into a latent threat
- worsens            — escalates a hazard already present on the SAME entity
- threatens          — last resort

## Output schema

Return valid JSON with EXACTLY two keys:

- causal_graph: object with:
  - nodes: array of objects, one per detected_object passed in plus any inferred nodes allowed by the inferred-entity policy:
    - id: object_id, must match detected_objects verbatim (or be of form presumed_<noun>_in_<existing_id>)
    - label: singular noun
    - state: state of the entity from the vocabulary above
    - hazardous: true iff state is hazard-bearing (the state alone is sufficient; outgoing edges are NOT required)
    - inferred: true for presumed_<noun>_in_<id> nodes, false for detected nodes
  - edges: array of objects, one per causal claim you would make about the scene:
    - source: object_id of the threat (must be a node with hazardous=true)
    - target: object_id of the affected entity (any node, including inferred)
    - effect: one of the 8 effect labels above
    - via_state: hazard-bearing state of source, must equal source-node's state

- suppression_pick: object naming which (threat, state) you would suppress first to maximally reduce harm in this scene:
  - threat: object_id
  - state: hazard-bearing state of that object
  - reason: short prose explaining why this is the most causally consequential intervention

## Rules

1. Use ONLY the object_ids and states present in the detected_objects and threats input below. Follow the inferred-entity policy supplied after this prompt; presumed_<noun>_in_<id> nodes are valid only when that policy says inferred entities are allowed.
2. Every edge's `via_state` must equal its `source` node's `state`, and that state must be hazard-bearing. Edges from non-hazardous nodes are invalid.
3. Self-reference (source == target): allowed only with effect `worsens`. Never `threatens` or `may_harm` self-loops.
4. Choose the most specific effect label; reserve `threatens` for last resort.
5. Hazardous-node edge requirements: a hazardous node (state is hazard-bearing) may exist in three valid configurations: (a) with outgoing edges to other entities (standard threat); (b) with ONLY incoming edges and no outgoing edges (pure casualty, e.g., a flooded car hit by water — the car remains hazardous=true but does not need outgoing edges); (c) with NO edges in or out, in which case emit a self-loop `node_id → node_id worsens, via_state=<state>` to express intrinsic deterioration. Do NOT emit a hazardous node that has zero edges of any kind.
6. Do NOT produce recommendations, scene_summary, or any field other than causal_graph and suppression_pick.

Return valid JSON only.
"""


# Prompt 2 variants for Test 2 (Prompt Sensitivity). Each variant replaces ONLY
# the opening paragraph of GRAPH_B_PROMPT — the schema, vocabularies, rules, and
# output instructions stay identical. We measure how A-fidelity / B-coverage
# move across variants on the same images. If they move <0.10 on median, the
# metric is prompt-stable. >0.20 means the metric is prompt-design-dependent.
PROMPT2_VARIANTS: dict[str, dict[str, str]] = {
    "v0_current": {
        "name": "Current (control)",
        "opening": (
            "You are extracting the causal graph that explains how hazards in this scene threaten safety. "
            "Cover every causal pathway you believe holds — direct harm, cascade between hazards, exposure, proximity risk — "
            "regardless of which a responder would address first."
        ),
    },
    "v1_minimal": {
        "name": "Minimal",
        "opening": (
            "Produce the causal graph for this scene. Cover every causal pathway you believe holds."
        ),
    },
    "v2_exhaustive": {
        "name": "Exhaustive",
        "opening": (
            "Produce the causal graph that captures every causal pathway between entities in this scene — "
            "direct harm, propagation, cascade, exposure, blocking, isolation, and proximity-based risk. "
            "Be exhaustive: include any plausible causal claim, even minor or indirect ones."
        ),
    },
    "v3_sparse": {
        "name": "Sparse",
        "opening": (
            "Produce the causal graph for this scene. "
            "Include only the most causally consequential edges; omit secondary or indirect effects."
        ),
    },
}


def graph_b_prompt_for_variant(variant_id: str) -> str:
    """Return the GRAPH_B_PROMPT with its opening paragraph swapped for the
    specified variant. Falls back to the current opening on unknown variant.
    """
    info = PROMPT2_VARIANTS.get(variant_id, PROMPT2_VARIANTS["v0_current"])
    new_opening = info["opening"]
    # Replace everything before "Below are the detected_objects" with the variant.
    body_anchor = "Below are the detected_objects and threats"
    idx = GRAPH_B_PROMPT.find(body_anchor)
    if idx < 0:
        return GRAPH_B_PROMPT
    return new_opening + " " + GRAPH_B_PROMPT[idx:]


PLACEHOLDER_RESULT = {
    "run_id": "",
    "image_filename": "",
    "scene_summary": "No scene summary yet.",
    "key_observations": [],
    "assumptions": [],
    "uncertainty_notes": [],
    "detected_objects": [],
    "disaster_scenario": "No",
    "disaster_type": "N/A",
    "disaster_level": 0,
    "threats": [],
    "recommendations": [],
    "causal_graph": {
        "nodes": [],
        "edges": [],
        "intervention_candidates": [],
        "orphan_threats": [],
        "threat_reasoning_coverage": 1.0,
        "graph_warnings": [],
    },
    "graph_b": {
        "nodes": [],
        "edges": [],
        "suppression_pick": {"threat": "", "state": "", "reason": ""},
        "intervention_candidates": [],
        "orphan_threats": [],
        "threat_reasoning_coverage": 1.0,
    },
    "graph_consistency": {
        "node_diff": {"only_in_a": [], "only_in_b": [], "in_both": []},
        "edge_diff": {"only_in_a": [], "only_in_b": [], "in_both": []},
        "effect_disagreements": [],
        "flag_agreement": [],
        "structural_consistency": 1.0,
        "topological_consistency": 1.0,
        "node_consistency": 1.0,
        "flag_consistency": 1.0,
        "a_fidelity": 1.0,
        "b_coverage": 1.0,
    },
    "pre_internal_alignment": {
        "score": 1.0,
        "passed_checks": 0,
        "failed_checks": 0,
        "failures": [],
        "allow_inferred": False,
    },
    "pre_intervention_trust": {
        "level": "unknown",
        "score": 0.0,
        "summary": "Run analysis to estimate baseline trust.",
        "interpretation": "Run analysis to estimate baseline trust.",
        "qualifiers": [],
        "use_in_shift_scoring": "unavailable",
    },
    "framework_suppression_picks": [],
    "gt_validation": {"available": False, "reason": "no analysis yet"},
}


app = Dash(__name__, suppress_callback_exceptions=True)
app.config.suppress_callback_exceptions = True
server = app.server
EXPORT_ROOT = Path(__file__).resolve().parent / "exports"


def parse_data_url(data_url: str | None) -> tuple[bytes | None, str | None]:
    if not data_url or "," not in data_url:
        return None, None

    header, encoded = data_url.split(",", 1)
    mime_type = header.split(";")[0].replace("data:", "") if header.startswith("data:") else "image/png"
    return base64.b64decode(encoded), mime_type


def image_bytes_to_data_url(image_bytes: bytes, mime_type: str = "image/png") -> str:
    return f"data:{mime_type};base64,{base64.b64encode(image_bytes).decode('utf-8')}"


def safe_filename(filename: str | None, fallback_stem: str = "uploaded_image") -> str:
    raw_name = Path(filename or "").name
    if not raw_name:
        return f"{fallback_stem}.png"

    safe_chars = [char if char.isalnum() or char in {".", "-", "_"} else "_" for char in raw_name]
    cleaned = "".join(safe_chars).strip("._")
    return cleaned or f"{fallback_stem}.png"


def open_uploaded_image(image_contents: str | None) -> tuple[Image.Image | None, str | None]:
    image_bytes, mime_type = parse_data_url(image_contents)
    if not image_bytes:
        return None, None

    image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    return image, mime_type or "image/png"


def clamp_bbox(raw_bbox: Any, width: int, height: int) -> list[int] | None:
    if not isinstance(raw_bbox, list) or len(raw_bbox) != 4:
        return None

    try:
        x_min, y_min, x_max, y_max = [int(round(float(value))) for value in raw_bbox]
    except (TypeError, ValueError):
        return None

    x_min = max(0, min(x_min, width - 1))
    y_min = max(0, min(y_min, height - 1))
    x_max = max(0, min(x_max, width))
    y_max = max(0, min(y_max, height))

    if x_max <= x_min or y_max <= y_min:
        return None

    return [x_min, y_min, x_max, y_max]


def bbox_area(bbox: list[int] | None) -> float:
    if not (isinstance(bbox, list) and len(bbox) == 4):
        return 0.0
    w = max(0, bbox[2] - bbox[0])
    h = max(0, bbox[3] - bbox[1])
    return float(w * h)


def bbox_overlap_fraction(a: list[int] | None, b: list[int] | None) -> float:
    """Return the intersection area divided by the smaller of the two box areas.

    This is the "overlap-of-either" metric used for deduplication — two boxes that
    are essentially the same detection will have inter/min(area) close to 1.0
    regardless of which box is slightly larger.
    """
    if not (isinstance(a, list) and len(a) == 4 and isinstance(b, list) and len(b) == 4):
        return 0.0
    ix_min = max(a[0], b[0])
    iy_min = max(a[1], b[1])
    ix_max = min(a[2], b[2])
    iy_max = min(a[3], b[3])
    if ix_max <= ix_min or iy_max <= iy_min:
        return 0.0
    inter = float((ix_max - ix_min) * (iy_max - iy_min))
    min_area = min(bbox_area(a), bbox_area(b))
    if min_area <= 0:
        return 0.0
    return inter / min_area


def _coerce_label(raw: Any) -> str:
    label = str(raw or "").strip().lower().replace(" ", "_")
    return label or "object"


def _valid_object_id(candidate: str, label: str) -> bool:
    """A valid id is non-empty, label-prefixed, and ends with _<positive int>."""
    if not candidate or "_" not in candidate:
        return False
    head, _, tail = candidate.rpartition("_")
    if head != label:
        return False
    return tail.isdigit() and int(tail) >= 1


def normalize_object_list(
    value: Any, width: int | None = None, height: int | None = None
) -> list[dict[str, Any]]:
    """Normalize detected_objects.

    Responsibilities added in pass-1.1:
      * Deduplicate entries whose bboxes overlap by >80% of either area (Layer 1 noise:
        same object listed twice). Merge metadata, preferring non-empty fields.
      * Assign stable object_ids of form "<label>_<N>" when the model omits or mis-forms
        them. N is 1-indexed per label, ordered by bbox x_min then y_min (rule I1).
        A model-provided id is preserved only if it already matches the "<label>_<int>"
        convention — otherwise it's regenerated so downstream joins are reliable.
    """
    if not isinstance(value, list):
        return []

    # Stage 1: raw intake with bbox clamping.
    raw_items: list[dict[str, Any]] = []
    for item in value:
        if isinstance(item, str):
            raw_items.append(
                {"label": _coerce_label(item), "state": "", "bbox": None, "object_id": ""}
            )
            continue
        if not isinstance(item, dict):
            continue

        label = _coerce_label(item.get("label", ""))
        state = str(item.get("state", "")).strip()
        bbox = item.get("bbox")
        if width and height:
            bbox = clamp_bbox(bbox, width, height)
        elif not (isinstance(bbox, list) and len(bbox) == 4):
            bbox = None
        raw_items.append(
            {
                "label": label,
                "state": state,
                "bbox": bbox,
                "object_id": str(item.get("object_id", "")).strip(),
            }
        )

    # Stage 2: dedupe overlapping same-label bboxes. Two entries are the same
    # physical object if (same label) AND (bbox overlap >80% of either area).
    deduped: list[dict[str, Any]] = []
    for candidate in raw_items:
        merged_into_existing = False
        for existing in deduped:
            if existing["label"] != candidate["label"]:
                continue
            if bbox_overlap_fraction(existing["bbox"], candidate["bbox"]) >= 0.8:
                # Keep the existing entry; fill in any missing metadata from the duplicate.
                if not existing["state"] and candidate["state"]:
                    existing["state"] = candidate["state"]
                if not existing["object_id"] and candidate["object_id"]:
                    existing["object_id"] = candidate["object_id"]
                merged_into_existing = True
                break
        if not merged_into_existing:
            deduped.append(candidate)

    # Stage 3: id assignment. Per label, order by bbox x_min then y_min, then
    # assign 1-indexed counters. Reuse a model-provided id only if it fits the
    # "<label>_<int>" shape — we do not want the model's invented "house_3"
    # surviving when there are only two houses.
    by_label: dict[str, list[dict[str, Any]]] = {}
    for entry in deduped:
        by_label.setdefault(entry["label"], []).append(entry)

    for label, entries in by_label.items():
        def _sort_key(e: dict[str, Any]) -> tuple[int, int]:
            bbox = e.get("bbox") or [10**9, 10**9, 0, 0]
            return (bbox[0], bbox[1])

        entries.sort(key=_sort_key)
        for idx, entry in enumerate(entries, start=1):
            canonical = f"{label}_{idx}"
            if not _valid_object_id(entry["object_id"], label):
                entry["object_id"] = canonical

    # Stage 4: emit in original deduped order so rendering is stable.
    objects: list[dict[str, Any]] = []
    for entry in deduped:
        objects.append(
            {
                "object_id": entry["object_id"],
                "label": entry["label"],
                "state": entry["state"],
                "bbox": entry["bbox"],
            }
        )
    return objects


def normalize_threats(
    value: Any,
    width: int | None = None,
    height: int | None = None,
    detected_objects: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Normalize the `threats` block.

    Schema: each entry is keyed by object_id and carries (object_id, state, reason).
    The UI still needs label/bbox to render thumbnails and overlays, so we join on
    object_id from normalized detected_objects to backfill. The `state` field here
    is expected to match detected_objects[object_id].state verbatim; if the model
    emits a different state on the threat entry, we trust detected_objects as the
    single source of truth (per prompt rule 2) but keep the entry's state as a
    fallback when no detected match is found.

    Note: category is removed from the schema — threats contains only active
    hazard sources. Latent threats live as graph edges via `increases_risk_to`.
    """
    if not isinstance(value, list):
        return []

    lookup: dict[str, dict[str, Any]] = {}
    if detected_objects:
        for obj in detected_objects:
            oid = str(obj.get("object_id", "")).strip()
            if oid:
                lookup[oid] = obj

    items: list[dict[str, Any]] = []
    for index, item in enumerate(value, start=1):
        if not isinstance(item, dict):
            continue

        object_id = str(item.get("object_id", "")).strip()
        detected_match = lookup.get(object_id)

        # detected_objects is the authoritative source for label/state/bbox.
        if detected_match:
            label = str(detected_match.get("label", "")).strip() or "Unknown"
            state = str(detected_match.get("state", "")).strip() or "unknown"
            bbox = detected_match.get("bbox")
        else:
            label = str(item.get("label", "")).strip() or "Unknown"
            state = str(item.get("state", "")).strip() or "unknown"
            bbox = item.get("bbox")
            if width and height:
                bbox = clamp_bbox(bbox, width, height)
            elif not (isinstance(bbox, list) and len(bbox) == 4):
                bbox = None

        if not object_id:
            object_id = f"{label.lower().replace(' ', '_')}_{index}"

        reason = str(item.get("reason", "")).strip() or "No reason provided."

        items.append(
            {
                "object_id": object_id,
                "label": label,
                "state": state,
                "bbox": bbox,
                "reason": reason,
                "ungrounded": detected_match is None,
            }
        )

    return items


def normalize_recommendations(value: Any) -> list[dict[str, Any]]:
    """Normalize recommendations with the causal quad schema.

    structured_reasoning is now a four-slot quad: (threat, state, effect,
    affected_object). Clean break from the old triple — legacy keys (hazard /
    affected_entity / source / target / relation) are NOT consulted, so schema
    regressions surface as "N/A" values instead of silently papering over.
    `effect` default is "N/A" rather than "threatens" since `threatens` was
    demoted to a last-resort label.
    """
    if not isinstance(value, list):
        return []

    placeholder_quad = {"threat": "N/A", "state": "N/A", "effect": "N/A", "affected_objects": []}

    normalized: list[dict[str, Any]] = []
    for item in value:
        if isinstance(item, str):
            normalized.append(
                {
                    "rank": 0,
                    "action": item,
                    "reason": "",
                    "related_object_ids": [],
                    "structured_reasoning": dict(placeholder_quad),
                    "expected_consequence": "N/A",
                    "remaining_risk": "N/A",
                    "possible_follow_up_action": "N/A",
                }
            )
            continue
        if not isinstance(item, dict):
            continue

        related_ids = item.get("related_object_ids", [])
        if not isinstance(related_ids, list):
            related_ids = [str(related_ids)]

        structured_reasoning = item.get("structured_reasoning", {})
        if not isinstance(structured_reasoning, dict):
            structured_reasoning = {}

        # Read affected_objects as a list. Defensive: accept singular `affected_object`
        # too and lift to a one-element list (helps when a model output slips back
        # to the old singular shape mid-experiment).
        raw_affected = structured_reasoning.get("affected_objects")
        if raw_affected is None:
            legacy_singular = structured_reasoning.get("affected_object")
            if legacy_singular is not None:
                raw_affected = [legacy_singular]
            else:
                raw_affected = []
        if isinstance(raw_affected, str):
            # tolerate a string emitted in place of a list
            raw_affected = [raw_affected]
        if not isinstance(raw_affected, list):
            raw_affected = [str(raw_affected)]
        affected_objects = [s for s in (str(v).strip() for v in raw_affected) if s]

        quad = {
            "threat": str(structured_reasoning.get("threat", "N/A")).strip() or "N/A",
            "state": str(structured_reasoning.get("state", "N/A")).strip() or "N/A",
            "effect": str(structured_reasoning.get("effect", "N/A")).strip() or "N/A",
            "affected_objects": affected_objects,
        }

        normalized.append(
            {
                "rank": int(item.get("rank", len(normalized) + 1) or len(normalized) + 1),
                "action": str(item.get("action", "")).strip() or "No action provided.",
                "reason": str(item.get("reason", "")).strip() or "No reasoning provided.",
                "related_object_ids": [str(value) for value in related_ids if str(value).strip()],
                "structured_reasoning": quad,
                "expected_consequence": str(item.get("expected_consequence", "N/A")).strip() or "N/A",
                "remaining_risk": str(item.get("remaining_risk", "N/A")).strip() or "N/A",
                "possible_follow_up_action": str(item.get("possible_follow_up_action", "N/A")).strip() or "N/A",
            }
        )

    return normalized


def build_causal_graph(
    detected_objects: list[dict[str, Any]],
    threats: list[dict[str, Any]],
    recommendations: list[dict[str, Any]],
) -> dict[str, Any]:
    """Derive a causal graph from the normalized output, state-as-edge-condition style.

    Each node is a detected object carrying a state attribute and a `hazardous` flag
    (True when the object appears as an active threat). Each recommendation's quad
    becomes one edge: source = threat, target = affected_object, effect = effect,
    via_state = state. Suppression later prunes edges where
    (source == suppressed_threat AND via_state == suppressed_state).

    Unresolved quads (threat or affected_object not in detected_objects) still emit
    an edge so the inconsistency is visible downstream, with a diagnostic appended
    to `graph_warnings`. intervention_candidates enumerates the suppressible
    (threat, state) pairs together with their current outgoing-edge count.
    """
    detected_ids = {o["object_id"] for o in detected_objects}
    hazard_bearing: set[tuple[str, str]] = {
        (t["object_id"], t["state"]) for t in threats if t.get("object_id") and t.get("state")
    }
    hazardous_ids = {tid for tid, _ in hazard_bearing}

    nodes = [
        {
            "id": o["object_id"],
            "label": o.get("label", ""),
            "state": o.get("state", "unknown"),
            "hazardous": o["object_id"] in hazardous_ids,
            "inferred": False,
        }
        for o in detected_objects
    ]

    edges: list[dict[str, Any]] = []
    warnings: list[str] = []
    inferred_nodes: dict[str, dict[str, Any]] = {}

    def parse_presumed(oid: str) -> tuple[str, str] | None:
        """Return (noun, anchor_id) if oid matches presumed_<noun>_in_<anchor>, else None."""
        if not oid.startswith("presumed_") or "_in_" not in oid:
            return None
        body = oid[len("presumed_"):]
        noun, _, anchor = body.partition("_in_")
        if not noun or not anchor:
            return None
        return noun, anchor

    for rec in recommendations:
        reasoning = rec.get("structured_reasoning") or {}
        source = str(reasoning.get("threat", "")).strip()
        effect = str(reasoning.get("effect", "")).strip()
        via_state = str(reasoning.get("state", "")).strip()

        # affected_objects is now a list — emit one edge per target.
        targets = reasoning.get("affected_objects") or []
        if isinstance(targets, str):
            targets = [targets]
        targets = [str(t).strip() for t in targets if str(t).strip()]
        if not targets:
            # Empty list = malformed quad. Record a warning, skip edge emission.
            warnings.append(f"rec rank={rec.get('rank')} has empty affected_objects")
            continue

        valid_source = source in detected_ids
        if not valid_source:
            warnings.append(f"rec rank={rec.get('rank')} threat '{source}' not in detected_objects")

        for target in targets:
            target_inferred = parse_presumed(target)
            valid_target = target in detected_ids or target_inferred is not None

            # Materialize virtual node for a presumed-entity target if its anchor is real.
            if target_inferred is not None:
                noun, anchor = target_inferred
                if anchor in detected_ids and target not in inferred_nodes:
                    inferred_nodes[target] = {
                        "id": target,
                        "label": noun,
                        "state": "unseen",
                        "hazardous": False,
                        "inferred": True,
                        "anchor_id": anchor,
                    }
                elif anchor not in detected_ids:
                    warnings.append(
                        f"rec rank={rec.get('rank')} presumed entity '{target}' anchors to '{anchor}' which is not in detected_objects"
                    )
                    valid_target = False

            if not valid_target and target_inferred is None:
                warnings.append(
                    f"rec rank={rec.get('rank')} affected_object '{target}' not in detected_objects"
                )

            edges.append(
                {
                    "source": source,
                    "target": target,
                    "effect": effect or "N/A",
                    "via_state": via_state or "N/A",
                    "from_recommendation_rank": rec.get("rank"),
                    "valid": valid_source and valid_target,
                    "target_inferred": target_inferred is not None,
                }
            )

    # Append virtual nodes after real ones so the original ordering is preserved.
    nodes.extend(inferred_nodes.values())

    intervention_candidates = [
        {
            "threat": tid,
            "state": st,
            "outgoing_edge_count": sum(
                1 for e in edges if e["source"] == tid and e["via_state"] == st
            ),
        }
        for tid, st in sorted(hazard_bearing)
    ]

    # Observational metrics — surface declared-but-unreasoned threats without
    # requiring the model to fix them at the prompt layer. A declared threat
    # with zero outgoing edges is a Layer 2 → Layer 3 asymmetry: the model
    # recognizes the hazard but does not reason about its causal reach.
    orphan_threats = [
        {"object_id": c["threat"], "state": c["state"]}
        for c in intervention_candidates
        if c["outgoing_edge_count"] == 0
    ]
    total_threats = len(intervention_candidates)
    reasoned_threats = total_threats - len(orphan_threats)
    threat_reasoning_coverage = (reasoned_threats / total_threats) if total_threats else 1.0

    return {
        "nodes": nodes,
        "edges": edges,
        "intervention_candidates": intervention_candidates,
        "orphan_threats": orphan_threats,
        "threat_reasoning_coverage": threat_reasoning_coverage,
        "graph_warnings": warnings,
    }


def parse_presumed_object_id(oid: str) -> tuple[str, str] | None:
    """Return (noun, anchor_id) for presumed_<noun>_in_<anchor>, else None."""
    if not oid.startswith("presumed_") or "_in_" not in oid:
        return None
    body = oid[len("presumed_"):]
    noun, _, anchor = body.partition("_in_")
    if not noun or not anchor:
        return None
    return noun, anchor


def is_valid_object_ref(oid: str, detected_ids: set[str], allow_inferred: bool) -> bool:
    if oid in detected_ids:
        return True
    inferred = parse_presumed_object_id(oid)
    return bool(allow_inferred and inferred and inferred[1] in detected_ids)


def add_graph_coverage_fields(graph: dict[str, Any]) -> dict[str, Any]:
    """Ensure a graph has threat coverage/orphan fields derived from hazardous nodes."""
    nodes = graph.get("nodes") or []
    edges = graph.get("edges") or []
    intervention_candidates = [
        {
            "threat": n.get("id", ""),
            "state": n.get("state", "unknown"),
            "outgoing_edge_count": sum(
                1
                for e in edges
                if e.get("source") == n.get("id", "")
                and e.get("via_state") == n.get("state", "unknown")
            ),
        }
        for n in nodes
        if bool(n.get("hazardous", False))
    ]
    orphan_threats = [
        {"object_id": c["threat"], "state": c["state"]}
        for c in intervention_candidates
        if c["outgoing_edge_count"] == 0
    ]
    total_threats = len(intervention_candidates)
    reasoned_threats = total_threats - len(orphan_threats)
    graph["intervention_candidates"] = intervention_candidates
    graph["orphan_threats"] = orphan_threats
    graph["threat_reasoning_coverage"] = (reasoned_threats / total_threats) if total_threats else 1.0
    return graph


def assess_pre_internal_alignment(
    detected_objects: list[dict[str, Any]],
    threats: list[dict[str, Any]],
    recommendations: list[dict[str, Any]],
    causal_graph: dict[str, Any],
    allow_inferred: bool = False,
) -> dict[str, Any]:
    """Rule-based intra-output consistency; no external scene truth is used."""
    detected_by_id = {
        str(o.get("object_id", "")).strip(): o
        for o in detected_objects
        if str(o.get("object_id", "")).strip()
    }
    detected_ids = set(detected_by_id)
    threat_by_id = {
        str(t.get("object_id", "")).strip(): t
        for t in threats
        if str(t.get("object_id", "")).strip()
    }
    threat_ids = set(threat_by_id)
    failures: list[dict[str, Any]] = []
    passed = 0

    def fail(kind: str, message: str, **details: Any) -> None:
        failures.append({"type": kind, "message": message, **details})

    def check(condition: bool, kind: str, message: str, **details: Any) -> None:
        nonlocal passed
        if condition:
            passed += 1
        else:
            fail(kind, message, **details)

    for oid, obj in detected_by_id.items():
        state = str(obj.get("state", "")).strip()
        if state in HAZARD_BEARING_STATES:
            check(
                oid in threat_ids,
                "hazard_state_missing_from_threats",
                f"{oid} has hazard-bearing state '{state}' but is absent from threats.",
                object_id=oid,
                state=state,
            )
        elif state in NORMAL_STATES:
            check(
                oid not in threat_ids,
                "normal_state_listed_as_threat",
                f"{oid} has normal state '{state}' but appears in threats.",
                object_id=oid,
                state=state,
            )

    for tid, threat in threat_by_id.items():
        t_state = str(threat.get("state", "")).strip()
        obj_state = str(detected_by_id.get(tid, {}).get("state", "")).strip()
        check(
            tid in detected_ids,
            "threat_missing_detected_object",
            f"Threat {tid} is not present in detected_objects.",
            object_id=tid,
        )
        if tid in detected_ids:
            check(
                t_state == obj_state,
                "threat_state_mismatch",
                f"Threat {tid} state '{t_state}' does not match detected_objects state '{obj_state}'.",
                object_id=tid,
                threat_state=t_state,
                detected_state=obj_state,
            )
        check(
            t_state in HAZARD_BEARING_STATES,
            "threat_state_not_hazard_bearing",
            f"Threat {tid} uses non-hazard-bearing state '{t_state}'.",
            object_id=tid,
            state=t_state,
        )

    seen_quads: dict[tuple[str, str, str, tuple[str, ...]], int] = {}
    seen_remaining_risks: dict[str, int] = {}
    for rec in recommendations:
        rank = rec.get("rank")
        reasoning = rec.get("structured_reasoning") or {}
        threat = str(reasoning.get("threat", "")).strip()
        state = str(reasoning.get("state", "")).strip()
        effect = str(reasoning.get("effect", "")).strip()
        # affected_objects is a list. Tolerate legacy singular `affected_object` too.
        raw_affected = reasoning.get("affected_objects")
        if raw_affected is None:
            legacy = reasoning.get("affected_object")
            raw_affected = [legacy] if legacy is not None else []
        if isinstance(raw_affected, str):
            raw_affected = [raw_affected]
        if not isinstance(raw_affected, list):
            raw_affected = [str(raw_affected)]
        affected_list = [s for s in (str(v).strip() for v in raw_affected) if s]
        related = [str(x).strip() for x in rec.get("related_object_ids", []) if str(x).strip()]
        reason = str(rec.get("reason", ""))
        remaining_risk = str(rec.get("remaining_risk", ""))

        check(
            threat in threat_ids,
            "recommendation_threat_not_declared",
            f"Recommendation {rank} uses threat '{threat}' that is not in threats.",
            recommendation_rank=rank,
            object_id=threat,
        )
        if threat in threat_by_id:
            threat_state = str(threat_by_id[threat].get("state", "")).strip()
            check(
                state == threat_state,
                "recommendation_state_mismatch",
                f"Recommendation {rank} state '{state}' does not match threat {threat} state '{threat_state}'.",
                recommendation_rank=rank,
                object_id=threat,
                quad_state=state,
                threat_state=threat_state,
            )
        check(
            effect in EFFECT_LABELS,
            "invalid_effect_label",
            f"Recommendation {rank} uses invalid effect '{effect}'.",
            recommendation_rank=rank,
            effect=effect,
        )
        if not affected_list:
            fail(
                "unresolved_affected_object",
                f"Recommendation {rank} has empty affected_objects list.",
                recommendation_rank=rank,
                affected_objects=[],
            )
        for affected in affected_list:
            check(
                is_valid_object_ref(affected, detected_ids, allow_inferred),
                "unresolved_affected_object",
                f"Recommendation {rank} affected_object '{affected}' is not grounded in detected_objects.",
                recommendation_rank=rank,
                affected_object=affected,
            )

        if threat in affected_list:
            check(
                effect == "worsens",
                "invalid_self_loop_effect",
                f"Recommendation {rank} uses self-loop effect '{effect}' for {threat}; only 'worsens' is valid.",
                recommendation_rank=rank,
                object_id=threat,
                effect=effect,
            )

        for oid in related:
            check(
                oid in detected_ids,
                "related_object_missing_detected_object",
                f"Recommendation {rank} related_object_id '{oid}' is not in detected_objects.",
                recommendation_rank=rank,
                object_id=oid,
            )

        quad_ids = {oid for oid in ([threat] + list(affected_list)) if oid and oid != "N/A"}
        reason_ids = set(OBJECT_ID_RE.findall(reason))
        related_ids = set(related)
        check(
            quad_ids.issubset(reason_ids),
            "quad_ids_missing_from_reason",
            f"Recommendation {rank} reason does not mention every object_id in its quad.",
            recommendation_rank=rank,
            missing=sorted(quad_ids - reason_ids),
        )
        check(
            reason_ids.issubset(related_ids | quad_ids),
            "reason_ids_missing_from_links",
            f"Recommendation {rank} reason mentions object_ids not covered by related_object_ids or the quad.",
            recommendation_rank=rank,
            missing=sorted(reason_ids - (related_ids | quad_ids)),
        )
        expected_related = {oid for oid in quad_ids if oid in detected_ids}
        check(
            expected_related.issubset(related_ids),
            "quad_ids_missing_from_related_object_ids",
            f"Recommendation {rank} related_object_ids does not include every detected object in its quad.",
            recommendation_rank=rank,
            missing=sorted(expected_related - related_ids),
        )

        quad_key = (threat, state, effect, tuple(sorted(affected_list)))
        if quad_key in seen_quads:
            fail(
                "duplicate_recommendation_quad",
                f"Recommendation {rank} duplicates the quad from recommendation {seen_quads[quad_key]}.",
                recommendation_rank=rank,
                duplicate_of_rank=seen_quads[quad_key],
                quad=list(quad_key),
            )
        else:
            passed += 1
            seen_quads[quad_key] = rank

        rr_key = remaining_risk.strip().lower()
        if rr_key and rr_key in seen_remaining_risks:
            fail(
                "duplicate_remaining_risk",
                f"Recommendation {rank} repeats remaining_risk from recommendation {seen_remaining_risks[rr_key]}.",
                recommendation_rank=rank,
                duplicate_of_rank=seen_remaining_risks[rr_key],
            )
        else:
            passed += 1
            if rr_key:
                seen_remaining_risks[rr_key] = rank

        if "latent" in remaining_risk.lower():
            latent_ids = set()
            for match in OBJECT_ID_RE.finditer(remaining_risk):
                start = max(0, match.start() - 48)
                end = min(len(remaining_risk), match.end() + 48)
                if "latent" in remaining_risk[start:end].lower():
                    latent_ids.add(match.group(0))
            for oid in latent_ids:
                obj_state = str(detected_by_id.get(oid, {}).get("state", "")).strip()
                if obj_state in HAZARD_BEARING_STATES:
                    fail(
                        "latent_active_conflict",
                        f"Recommendation {rank} calls {oid} latent while its declared state is '{obj_state}'.",
                        recommendation_rank=rank,
                        object_id=oid,
                        state=obj_state,
                    )
                else:
                    passed += 1

        for oid, pair_state in OBJECT_STATE_PAIR_RE.findall(remaining_risk):
            check(
                oid in detected_ids,
                "remaining_risk_object_missing_detected_object",
                f"Recommendation {rank} remaining_risk cites unknown object '{oid}'.",
                recommendation_rank=rank,
                object_id=oid,
            )
            if oid in detected_ids:
                obj_state = str(detected_by_id[oid].get("state", "")).strip()
                check(
                    pair_state == obj_state,
                    "remaining_risk_state_mismatch",
                    f"Recommendation {rank} cites ({oid}, {pair_state}) but detected state is '{obj_state}'.",
                    recommendation_rank=rank,
                    object_id=oid,
                    cited_state=pair_state,
                    detected_state=obj_state,
                )

    for edge in causal_graph.get("edges", []) or []:
        if not edge.get("valid", True):
            fail(
                "invalid_graph_edge",
                f"Graph A has unresolved edge {edge.get('source')} -> {edge.get('target')}.",
                source=edge.get("source"),
                target=edge.get("target"),
                effect=edge.get("effect"),
                from_recommendation_rank=edge.get("from_recommendation_rank"),
            )
        else:
            passed += 1

    failed = len(failures)
    total = passed + failed
    return {
        "score": (passed / total) if total else 1.0,
        "passed_checks": passed,
        "failed_checks": failed,
        "failures": failures,
        "allow_inferred": allow_inferred,
    }


ACUTE_STATES = {
    "burning", "collapsing", "charging", "rising", "spreading", "escalating",
    "striking", "fleeing", "leaking", "billowing", "seeping", "aiming", "approaching",
}
STABLE_HAZARD_STATES = {
    "collapsed", "fallen", "crushed", "flooded", "bleeding", "injured",
    "coiled", "rabid", "armed",
}


def pick_suppression_framework(causal_graph: dict[str, Any], top_n: int = 3) -> list[dict[str, Any]]:
    """Rank intervention candidates algorithmically.

    Sort by:
      1. outgoing_edge_count, descending — more edges = more consequential suppression.
      2. acuteness of state, acute > stable — acute hazards are time-critical.
      3. tie-break alphabetically by (object_id, state) for determinism.

    Returns the top_n ranked candidates with their rank and a short rationale.
    Independent of the model's preference; no LLM call.
    """
    candidates = causal_graph.get("intervention_candidates") or []

    def acuteness_score(state: str) -> int:
        s = (state or "").strip().lower()
        if s in ACUTE_STATES:
            return 2
        if s in STABLE_HAZARD_STATES:
            return 1
        return 0

    ranked = sorted(
        candidates,
        key=lambda c: (
            -(c.get("outgoing_edge_count", 0)),
            -acuteness_score(c.get("state", "")),
            c.get("threat", ""),
            c.get("state", ""),
        ),
    )

    out: list[dict[str, Any]] = []
    for i, c in enumerate(ranked[:top_n], start=1):
        rationale_parts = [f"outgoing_edges={c.get('outgoing_edge_count', 0)}"]
        if acuteness_score(c.get("state", "")) == 2:
            rationale_parts.append("acute state")
        elif acuteness_score(c.get("state", "")) == 1:
            rationale_parts.append("stable hazard state")
        out.append(
            {
                "rank": i,
                "threat": c.get("threat", ""),
                "state": c.get("state", ""),
                "outgoing_edge_count": c.get("outgoing_edge_count", 0),
                "rationale": "; ".join(rationale_parts),
            }
        )
    return out


# ────────────────────────────────────────────────────────────
# Soft (semantic) matching for Test 1 ground-truth comparison
# ────────────────────────────────────────────────────────────

# Specific label → canonical class. Anything not listed maps to itself.
LABEL_HIERARCHY: dict[str, str] = {
    # person family
    "man": "person", "woman": "person", "boy": "person", "girl": "person",
    "child": "person", "kid": "person", "toddler": "person", "infant": "person",
    "adult": "person", "elderly": "person", "senior": "person",
    "person": "person", "people": "person", "human": "person",
    "male": "person", "female": "person",
    "cyclist": "person", "biker": "person",
    "driver": "person", "pedestrian": "person", "passerby": "person",
    "hiker": "person", "civilian": "person", "bystander": "person",
    "occupant": "person", "resident": "person", "victim": "person",
    "survivor": "person", "worker": "person", "homeowner": "person",
    # responder family (kept distinct from generic person — different threat role)
    "firefighter": "responder", "fireman": "responder",
    "police": "responder", "policeman": "responder", "officer": "responder", "cop": "responder",
    "paramedic": "responder", "emt": "responder",
    "rescuer": "responder", "rescue_worker": "responder",
    "first_responder": "responder", "responder": "responder",
    "soldier": "responder", "military": "responder",
    # vehicle family (wheeled)
    "car": "vehicle", "sedan": "vehicle", "suv": "vehicle", "hatchback": "vehicle",
    "truck": "vehicle", "pickup": "vehicle", "lorry": "vehicle",
    "van": "vehicle", "bus": "vehicle", "minibus": "vehicle",
    "motorcycle": "vehicle", "motorbike": "vehicle", "scooter": "vehicle", "moped": "vehicle",
    "bicycle": "vehicle", "bike": "vehicle",
    "vehicle": "vehicle", "automobile": "vehicle", "jeep": "vehicle",
    "ambulance": "vehicle", "fire_truck": "vehicle", "police_car": "vehicle",
    # vessel family (boats are distinct)
    "boat": "vessel", "ship": "vessel", "vessel": "vessel",
    "kayak": "vessel", "canoe": "vessel", "yacht": "vessel", "raft": "vessel",
    # animal family
    "dog": "animal", "puppy": "animal", "cat": "animal", "kitten": "animal",
    "snake": "animal", "tiger": "animal", "lion": "animal", "bear": "animal",
    "bird": "animal", "horse": "animal", "cow": "animal", "sheep": "animal",
    "pig": "animal", "goat": "animal", "deer": "animal", "rabbit": "animal",
    "fox": "animal", "wolf": "animal", "livestock": "animal",
    "animal": "animal",
    # structure family (buildings)
    "house": "structure", "home": "structure", "residence": "structure", "dwelling": "structure",
    "building": "structure", "apartment": "structure", "structure": "structure",
    "shed": "structure", "garage": "structure", "barn": "structure", "warehouse": "structure",
    "store": "structure", "shop": "structure", "school": "structure", "hospital": "structure",
    "church": "structure", "mosque": "structure", "temple": "structure",
    "office": "structure", "office_building": "structure", "tower": "structure",
    "skyscraper": "structure", "cabin": "structure", "cottage": "structure",
    # vegetation family
    "tree": "vegetation", "trees": "vegetation", "branch": "vegetation",
    "bush": "vegetation", "shrub": "vegetation", "plant": "vegetation",
    "grass": "vegetation", "vegetation": "vegetation", "flora": "vegetation",
    "foliage": "vegetation", "forest": "vegetation",
    # water family (when model treats water as an entity)
    "water": "water", "river": "water", "stream": "water", "creek": "water",
    "lake": "water", "pond": "water", "ocean": "water", "sea": "water",
    "flood": "water", "floodwater": "water", "flood_water": "water",
    "current": "water", "tide": "water", "surge": "water",
    # fire family (when model treats fire as an entity)
    "fire": "fire", "flame": "fire", "flames": "fire", "blaze": "fire",
    "wildfire": "fire", "inferno": "fire",
    # smoke family
    "smoke": "smoke", "smog": "smoke", "fume": "smoke", "fumes": "smoke",
    "haze": "smoke",
    # infrastructure family
    "bridge": "infrastructure", "road": "infrastructure", "highway": "infrastructure",
    "street": "infrastructure", "tunnel": "infrastructure", "sidewalk": "infrastructure",
    "wall": "infrastructure", "fence": "infrastructure",
    "pole": "infrastructure", "wire": "infrastructure", "cable": "infrastructure",
    "powerline": "infrastructure", "power_line": "infrastructure",
    "powerlines": "infrastructure", "telephone_pole": "infrastructure",
}

# State variants → canonical state. Conservative: only clear synonyms.
# Topological match (ignoring state entirely) is the safety net for state vocabulary
# divergence beyond what's captured here.
STATE_SYNONYMS: dict[str, str] = {
    # Fire — actively burning variants
    "on_fire": "burning", "on fire": "burning", "aflame": "burning",
    "ablaze": "burning", "ignited": "burning", "lit": "burning",
    "smoldering": "burning",
    # Post-fire damage — burnt is its own settled hazard state distinct from collapsed
    "burned": "burnt", "charred": "burnt", "scorched": "burnt",
    "gutted": "burnt",
    # Generic destruction terms — collapsed unless fire is the clear cause
    "destroyed": "collapsed", "demolished": "collapsed", "ruined": "collapsed",
    "wrecked": "collapsed",
    # Collapsing → collapsed (same hazard family)
    "collapsing": "collapsed", "crumbling": "collapsed", "caving_in": "collapsed",
    # Flood variants
    "submerged": "flooded", "inundated": "flooded",
    "waterlogged": "flooded", "underwater": "flooded",
    # Fallen variants
    "toppled": "fallen", "down": "fallen",
    "knocked_over": "fallen", "knocked_down": "fallen",
    "uprooted": "fallen", "fallen_down": "fallen",
    # Smoke production
    "smoking": "billowing", "smoky": "billowing",
    "spewing_smoke": "billowing",
    # Crushed variants
    "broken": "crushed", "crashed": "crushed",
    "smashed": "crushed", "mangled": "crushed",
    # Motion / threat states
    "advancing": "approaching", "moving_toward": "approaching",
    "attacking": "charging",
    "running_away": "fleeing", "escaping": "fleeing",
    # Injury variants
    "hurt": "injured", "wounded": "injured",
}

# Effect close-pairs — pairs where truth conditions overlap meaningfully.
# NOT loose families; only semantically near-synonymous effects.
EFFECT_CLOSE_PAIRS: list[set[str]] = [
    {"may_harm", "threatens"},
    {"blocks_access_to", "isolates"},
]


def resolve_label_class(label: str) -> str:
    """Return the canonical class for a label, falling back to the label itself."""
    return LABEL_HIERARCHY.get((label or "").strip().lower(), (label or "").strip().lower())


def canonicalize_state(state: str) -> str:
    """Return the canonical form of a state (handles known synonyms)."""
    s = (state or "").strip().lower()
    return STATE_SYNONYMS.get(s, s)


def effects_soft_equal(e1: str, e2: str) -> bool:
    """True if two effects are equal or in the same close-pair."""
    a = (e1 or "").strip()
    b = (e2 or "").strip()
    if a == b:
        return True
    for pair in EFFECT_CLOSE_PAIRS:
        if a in pair and b in pair:
            return True
    return False


def _fuzzy_edge_key(
    edge: dict[str, Any], nodes_by_id: dict[str, dict[str, Any]]
) -> tuple[str, str, str, str]:
    """Edge → (source_class, state_canonical, effect_canonical, target_class).

    Effect is canonicalized via close-pairs: pick the alphabetically-first member
    of the pair so that {may_harm, threatens} both map to "may_harm".
    """
    s_node = nodes_by_id.get(edge.get("source", ""), {})
    t_node = nodes_by_id.get(edge.get("target", ""), {})
    s_class = resolve_label_class(s_node.get("label", ""))
    t_class = resolve_label_class(t_node.get("label", ""))
    state_canon = canonicalize_state(edge.get("via_state", ""))

    eff = (edge.get("effect", "") or "").strip()
    eff_canon = eff
    for pair in EFFECT_CLOSE_PAIRS:
        if eff in pair:
            eff_canon = sorted(pair)[0]
            break

    return (s_class, state_canon, eff_canon, t_class)


def _topological_edge_key(
    edge: dict[str, Any], nodes_by_id: dict[str, dict[str, Any]]
) -> tuple[str, str, str]:
    """Edge → (source_class, effect_canonical, target_class). State is IGNORED.

    Captures "same causal structure, regardless of state vocabulary". Useful when
    GT says 'collapsed' and model says 'burned' for the same post-fire scene.
    """
    s_node = nodes_by_id.get(edge.get("source", ""), {})
    t_node = nodes_by_id.get(edge.get("target", ""), {})
    s_class = resolve_label_class(s_node.get("label", ""))
    t_class = resolve_label_class(t_node.get("label", ""))
    eff = (edge.get("effect", "") or "").strip()
    eff_canon = eff
    for pair in EFFECT_CLOSE_PAIRS:
        if eff in pair:
            eff_canon = sorted(pair)[0]
            break
    return (s_class, eff_canon, t_class)


def compare_graphs_topological(graph_a: dict[str, Any], graph_b: dict[str, Any]) -> dict[str, Any]:
    """Topological (state-blind) multiset comparison.

    Matches edges by (source_class, effect_canonical, target_class) — ignores
    the via_state slot entirely. Catches cases where the model's state vocabulary
    diverges from the reference but the underlying causal structure agrees.
    """
    from collections import Counter

    a_nodes = {n.get("id", ""): n for n in graph_a.get("nodes") or []}
    b_nodes = {n.get("id", ""): n for n in graph_b.get("nodes") or []}

    a_keys = [_topological_edge_key(e, a_nodes) for e in graph_a.get("edges") or []]
    b_keys = [_topological_edge_key(e, b_nodes) for e in graph_b.get("edges") or []]

    a_counter = Counter(a_keys)
    b_counter = Counter(b_keys)
    intersect = a_counter & b_counter
    matched = sum(intersect.values())
    union = sum((a_counter | b_counter).values())

    return {
        "matched": matched,
        "a_total": len(a_keys),
        "b_total": len(b_keys),
        "a_fidelity_topo": (matched / len(a_keys)) if a_keys else 1.0,
        "b_coverage_topo": (matched / len(b_keys)) if b_keys else 1.0,
        "structural_topo": (matched / union) if union else 1.0,
        "both_keys": list(intersect.elements()),
        "a_only_keys": list((a_counter - b_counter).elements()),
        "b_only_keys": list((b_counter - a_counter).elements()),
    }


def compare_graphs_soft(graph_a: dict[str, Any], graph_b: dict[str, Any]) -> dict[str, Any]:
    """Multiset-aware soft (semantic) comparison of two graphs.

    Returns:
      a_fidelity_soft = matched_count / |A edges|
      b_coverage_soft = matched_count / |B edges|
      structural_soft = matched_count / |A ∪ B| (counted as multisets)
      a_only_fuzzy, b_only_fuzzy, both_fuzzy: lists of normalized edge tuples
    """
    from collections import Counter

    a_nodes = {n.get("id", ""): n for n in graph_a.get("nodes") or []}
    b_nodes = {n.get("id", ""): n for n in graph_b.get("nodes") or []}

    a_edges = graph_a.get("edges") or []
    b_edges = graph_b.get("edges") or []
    a_keys = [_fuzzy_edge_key(e, a_nodes) for e in a_edges]
    b_keys = [_fuzzy_edge_key(e, b_nodes) for e in b_edges]

    a_counter = Counter(a_keys)
    b_counter = Counter(b_keys)
    intersect = a_counter & b_counter
    matched = sum(intersect.values())
    union = sum((a_counter | b_counter).values())

    a_only = sum((a_counter - b_counter).values())
    b_only = sum((b_counter - a_counter).values())

    return {
        "matched": matched,
        "a_total": len(a_keys),
        "b_total": len(b_keys),
        "a_fidelity_soft": (matched / len(a_keys)) if a_keys else 1.0,
        "b_coverage_soft": (matched / len(b_keys)) if b_keys else 1.0,
        "structural_soft": (matched / union) if union else 1.0,
        "a_only_count": a_only,
        "b_only_count": b_only,
        "both_keys": list(intersect.elements()),
        "a_only_keys": list((a_counter - b_counter).elements()),
        "b_only_keys": list((b_counter - a_counter).elements()),
    }


def compare_graphs(graph_a: dict[str, Any], graph_b: dict[str, Any]) -> dict[str, Any]:
    """Compute structural and flag-level consistency between Graph A (derived
    from recs) and Graph B (VLM-generated).

    Returns:
      node_diff: {only_in_a, only_in_b, in_both}
      edge_diff: {only_in_a, only_in_b, in_both}  (edge identity = (source, via_state, effect, target))
      flag_agreement: per-node hazardous flag match for nodes in both
      structural_consistency: matched_edges / |union_edges|
      topological_consistency: matched source-target pairs / |union source-target pairs|
      node_consistency:       matched_nodes / |union_nodes|
      flag_consistency:       matched_flags / |nodes_in_both|
    """
    def effective_nodes(graph: dict[str, Any]) -> dict[str, dict[str, Any]]:
        nodes = {
            str(n.get("id", "")).strip(): n
            for n in graph.get("nodes", [])
            if str(n.get("id", "")).strip()
        }
        # Treat unresolved edge endpoints as graph commitments for node-diff
        # purposes. This makes targets like `other_houses` appear as Nodes only
        # in A instead of hiding them inside an edge-only disagreement.
        for e in graph.get("edges", []) or []:
            for key in ("source", "target"):
                endpoint = str(e.get(key, "")).strip()
                if endpoint and endpoint not in nodes:
                    nodes[endpoint] = {
                        "id": endpoint,
                        "label": endpoint,
                        "state": "unresolved",
                        "hazardous": False,
                        "inferred": False,
                        "unresolved": True,
                    }
        return nodes

    a_nodes = effective_nodes(graph_a)
    b_nodes = effective_nodes(graph_b)
    only_in_a_nodes = sorted(set(a_nodes) - set(b_nodes))
    only_in_b_nodes = sorted(set(b_nodes) - set(a_nodes))
    in_both_nodes = sorted(set(a_nodes) & set(b_nodes))

    def edge_key(e: dict[str, Any]) -> tuple[str, str, str, str]:
        return (
            str(e.get("source", "")).strip(),
            str(e.get("via_state", "")).strip(),
            str(e.get("effect", "")).strip(),
            str(e.get("target", "")).strip(),
        )

    a_edges = {edge_key(e): e for e in graph_a.get("edges", [])}
    b_edges = {edge_key(e): e for e in graph_b.get("edges", [])}
    only_in_a_edges = [a_edges[k] for k in sorted(set(a_edges) - set(b_edges))]
    only_in_b_edges = [b_edges[k] for k in sorted(set(b_edges) - set(a_edges))]
    in_both_edges = [a_edges[k] for k in sorted(set(a_edges) & set(b_edges))]

    def topo_key(e: dict[str, Any]) -> tuple[str, str]:
        return (
            str(e.get("source", "")).strip(),
            str(e.get("target", "")).strip(),
        )

    a_topo: dict[tuple[str, str], list[dict[str, Any]]] = {}
    b_topo: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for e in graph_a.get("edges", []) or []:
        a_topo.setdefault(topo_key(e), []).append(e)
    for e in graph_b.get("edges", []) or []:
        b_topo.setdefault(topo_key(e), []).append(e)

    shared_topo = sorted(set(a_topo) & set(b_topo))
    union_topo = set(a_topo) | set(b_topo)
    effect_disagreements: list[dict[str, Any]] = []
    for source, target in shared_topo:
        a_effects = sorted({str(e.get("effect", "")).strip() for e in a_topo[(source, target)]})
        b_effects = sorted({str(e.get("effect", "")).strip() for e in b_topo[(source, target)]})
        if a_effects != b_effects:
            effect_disagreements.append(
                {
                    "source": source,
                    "target": target,
                    "graph_a_effects": a_effects,
                    "graph_b_effects": b_effects,
                }
            )

    flag_agreements: list[dict[str, Any]] = []
    matching_flags = 0
    for nid in in_both_nodes:
        a_haz = bool(a_nodes[nid].get("hazardous"))
        b_haz = bool(b_nodes[nid].get("hazardous"))
        agree = a_haz == b_haz
        flag_agreements.append({"id": nid, "graph_a": a_haz, "graph_b": b_haz, "agree": agree})
        if agree:
            matching_flags += 1

    union_nodes = len(set(a_nodes) | set(b_nodes))
    union_edges = len(set(a_edges) | set(b_edges))

    return {
        "node_diff": {
            "only_in_a": only_in_a_nodes,
            "only_in_b": only_in_b_nodes,
            "in_both": in_both_nodes,
        },
        "edge_diff": {
            "only_in_a": only_in_a_edges,
            "only_in_b": only_in_b_edges,
            "in_both": in_both_edges,
        },
        "effect_disagreements": effect_disagreements,
        "flag_agreement": flag_agreements,
        "structural_consistency": (len(in_both_edges) / union_edges) if union_edges else 1.0,
        "topological_consistency": (len(shared_topo) / len(union_topo)) if union_topo else 1.0,
        "node_consistency": (len(in_both_nodes) / union_nodes) if union_nodes else 1.0,
        "flag_consistency": (matching_flags / len(in_both_nodes)) if in_both_nodes else 1.0,
        # Directional metrics. A is recs-derived (action-filtered), B is independent
        # (full causal belief). A ⊆ B is the "recs are causally grounded" condition.
        # a_fidelity = fraction of A's edges that B also claims. Low = recs make
        #   causal claims the model wouldn't independently endorse (fabrication).
        # b_coverage = fraction of B's edges that A also claims. Low = the model
        #   knows causal links it didn't act on (under-recommendation). Some gap is
        #   expected since recs are filtered by actionability.
        "a_fidelity": (len(in_both_edges) / len(a_edges)) if a_edges else 1.0,
        "b_coverage": (len(in_both_edges) / len(b_edges)) if b_edges else 1.0,
    }


def assess_pre_intervention_trust(
    alignment: dict[str, Any],
    consistency: dict[str, Any],
    graph_a: dict[str, Any],
    graph_b: dict[str, Any],
) -> dict[str, Any]:
    """Summarize whether the baseline causal account is trustworthy enough
    to interpret intervention shifts cleanly.
    """
    passed = int(alignment.get("passed_checks", 0) or 0)
    failed = int(alignment.get("failed_checks", 0) or 0)
    graph_has_data = bool(graph_a.get("nodes") or graph_a.get("edges") or graph_b.get("nodes") or graph_b.get("edges"))
    if passed + failed == 0 and not graph_has_data:
        return dict(PLACEHOLDER_RESULT["pre_intervention_trust"])

    # Non-disaster short-circuit: if there are detected_objects but no threats
    # and no recommendations, there is no causal account to evaluate. Don't
    # produce a vacuous-perfect score.
    no_threats = not (graph_a.get("intervention_candidates") or graph_b.get("intervention_candidates"))
    no_a_edges = not (graph_a.get("edges") or [])
    no_b_edges = not (graph_b.get("edges") or [])
    if no_threats and no_a_edges and no_b_edges:
        return {
            "level": "not_applicable",
            "score": 0.0,
            "summary": "No threats or causal edges declared — trust scoring not applicable.",
            "interpretation": "Scene has no hazardous structure for CEE+ to evaluate.",
            "qualifiers": ["Scene has no threats; pre-intervention trust does not apply."],
            "use_in_shift_scoring": "exclude",
            "components": {},
            "score_formula": "n/a",
        }

    internal = float(alignment.get("score", 0.0) or 0.0)
    topological = float(consistency.get("topological_consistency", 0.0) or 0.0)
    node_consistency = float(consistency.get("node_consistency", 0.0) or 0.0)
    flag_consistency = float(consistency.get("flag_consistency", 0.0) or 0.0)
    a_fidelity = float(consistency.get("a_fidelity", 0.0) or 0.0)
    b_edge_coverage = float(consistency.get("b_coverage", 0.0) or 0.0)
    effect_disagreement_count = len(consistency.get("effect_disagreements", []) or [])
    coverage_a = float(graph_a.get("threat_reasoning_coverage", 1.0) or 0.0)
    coverage_b = float(graph_b.get("threat_reasoning_coverage", 1.0) or 0.0)
    coverage = (coverage_a + coverage_b) / 2

    score = (0.40 * internal) + (0.20 * a_fidelity) + (0.20 * b_edge_coverage) + (0.20 * coverage)
    score_formula = "0.40*Internal + 0.20*A fidelity + 0.20*B edge coverage + 0.20*Avg(Graph A/B threat coverage)"
    qualifiers: list[str] = []

    failures = alignment.get("failures", []) or []
    invalid_edges = [f for f in failures if f.get("type") == "invalid_graph_edge"]
    unresolved_targets = [f for f in failures if f.get("type") == "unresolved_affected_object"]
    if unresolved_targets:
        targets = sorted({str(f.get("affected_object", "")).strip() for f in unresolved_targets if f.get("affected_object")})
        qualifiers.append(f"Recommendation graph has ungrounded target(s): {', '.join(targets)}.")
    if invalid_edges:
        qualifiers.append(f"Graph A contains {len(invalid_edges)} invalid edge(s).")
    if a_fidelity < 0.5:
        qualifiers.append("A fidelity is low: recommendation edges are weakly supported by Graph B.")
    elif a_fidelity < 0.85:
        qualifiers.append("A fidelity is partial: some recommendation edges are supported by Graph B.")
    if b_edge_coverage < 0.5:
        qualifiers.append("B edge coverage is low: independent causal links are missing from recommendations.")
    elif b_edge_coverage < 0.85:
        qualifiers.append("B edge coverage is partial: recommendations cover some independent causal links.")
    if effect_disagreement_count:
        qualifiers.append("A/B agree on some causal links but disagree on effect labels.")
    if coverage_a < 1.0:
        orphans = graph_a.get("orphan_threats") or []
        qualifiers.append(f"Graph A leaves {len(orphans)} declared threat(s) without outgoing causal reach.")
    if coverage_b < 1.0:
        orphans = graph_b.get("orphan_threats") or []
        qualifiers.append(f"Graph B leaves {len(orphans)} hazardous node(s) without outgoing causal reach.")
    if not qualifiers:
        qualifiers.append("Baseline causal account is internally coherent and mechanism agreement is strong.")

    if score >= 0.85 and not invalid_edges and a_fidelity >= 0.75:
        level = "high"
        interpretation = "Post-intervention shifts can be interpreted as strong evidence."
        use = "weight_strongly"
    elif score >= 0.60:
        level = "moderate"
        interpretation = "Post-intervention shifts are useful but should be interpreted with qualifiers."
        use = "qualify"
    else:
        level = "low"
        interpretation = "Post-intervention shifts are hard to attribute to grounded causal reasoning."
        use = "downweight"

    if level == "high":
        opening = "Baseline trust is high: the recommendation graph is coherent enough to support clean intervention interpretation."
    elif level == "moderate":
        opening = "Baseline trust is moderate: intervention shifts are usable, but they should be interpreted with qualifiers."
    else:
        opening = "Baseline trust is low: the baseline causal account is unstable, so intervention shifts should be treated as weak evidence."

    if unresolved_targets or invalid_edges:
        reason = "The main limitation is grounding: Graph A includes targets not present in detected_objects."
    elif effect_disagreement_count:
        reason = "The graphs often connect the same entities, but disagree on effect labels."
    elif a_fidelity < 0.5:
        reason = "Recommendation edges are weakly supported by the independent graph."
    elif b_edge_coverage < 0.5:
        reason = "The independent graph contains causal links that recommendations do not cover."
    elif coverage_a < 1.0:
        reason = "Some declared threats do not receive outgoing causal reasoning in Graph A."
    elif coverage_b < 1.0:
        reason = "Some hazardous nodes do not receive outgoing causal reasoning in Graph B."
    else:
        reason = "The baseline causal account is internally coherent and mechanism agreement is strong."

    if use == "weight_strongly":
        consequence = "A post-intervention shift can be interpreted as stronger evidence of causal groundedness."
    elif use == "qualify":
        consequence = "A post-intervention shift can still be informative, but should be reported with baseline-trust caveats."
    else:
        consequence = "A post-intervention shift should be downweighted unless the post output becomes substantially more coherent."

    summary = " ".join([opening, reason, consequence])

    return {
        "level": level,
        "score": score,
        "summary": summary,
        "interpretation": interpretation,
        "qualifiers": qualifiers,
        "use_in_shift_scoring": use,
        "components": {
            "internal_alignment": internal,
            "structural_consistency": float(consistency.get("structural_consistency", 0.0) or 0.0),
            "topological_consistency": topological,
            "node_consistency": node_consistency,
            "flag_consistency": flag_consistency,
            "a_fidelity": a_fidelity,
            "b_edge_coverage": b_edge_coverage,
            "effect_disagreement_count": effect_disagreement_count,
            "graph_a_coverage": coverage_a,
            "graph_b_coverage": coverage_b,
        },
        "score_formula": score_formula,
    }


def build_payload(prompt: str, caption: str, image_contents: str | None) -> dict[str, Any]:
    content: list[dict[str, Any]] = [{"type": "text", "text": f"{prompt}\n\nCaption:\n{caption or 'N/A'}"}]

    if image_contents:
        content.append({"type": "image_url", "image_url": {"url": image_contents}})

    return {
        "model": os.getenv("QWEN_MODEL_NAME", "qwen2.5vl:7b"),
        "messages": [{"role": "user", "content": content}],
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
    }


def extract_json_block(text: str) -> dict[str, Any]:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            return json.loads(text[start : end + 1])
        raise


def normalize_result(raw: dict[str, Any], image_contents: str | None = None) -> dict[str, Any]:
    result = dict(PLACEHOLDER_RESULT)
    result.update(raw or {})

    image, _mime_type = open_uploaded_image(image_contents)
    width = image.width if image else None
    height = image.height if image else None

    result["run_id"] = str(result.get("run_id", "")).strip()
    result["image_filename"] = str(result.get("image_filename", "")).strip()
    result["scene_summary"] = str(result.get("scene_summary", PLACEHOLDER_RESULT["scene_summary"]))
    for key in ("key_observations", "assumptions", "uncertainty_notes"):
        value = result.get(key, [])
        if isinstance(value, list):
            result[key] = [str(item).strip() for item in value if str(item).strip()]
        elif value in (None, "", "N/A"):
            result[key] = []
        else:
            result[key] = [str(value).strip()]
    result["detected_objects"] = normalize_object_list(result.get("detected_objects", []), width, height)
    # Pass detected_objects in so `threats` entries (keyed by object_id + state +
    # reason under the quad schema) can be joined back to label/bbox for rendering.
    result["threats"] = normalize_threats(
        result.get("threats", []),
        width,
        height,
        detected_objects=result["detected_objects"],
    )

    for key in ("disaster_scenario", "disaster_type"):
        result[key] = str(result.get(key, PLACEHOLDER_RESULT[key]))

    try:
        level = int(result.get("disaster_level", 0))
    except (TypeError, ValueError):
        level = 0
    result["disaster_level"] = max(0, min(level, 10))

    result["recommendations"] = normalize_recommendations(result.get("recommendations", []))

    result["causal_graph"] = build_causal_graph(
        result["detected_objects"], result["threats"], result["recommendations"]
    )
    result["allow_inferred"] = bool(result.get("allow_inferred", False))
    result["pre_internal_alignment"] = assess_pre_internal_alignment(
        result["detected_objects"],
        result["threats"],
        result["recommendations"],
        result["causal_graph"],
        allow_inferred=result["allow_inferred"],
    )

    # Graph B is populated by analyze_scene (Prompt 2 model call). On re-render,
    # whatever is stored stays as-is. Default to placeholder if absent.
    if "graph_b" not in result or not isinstance(result.get("graph_b"), dict):
        result["graph_b"] = dict(PLACEHOLDER_RESULT["graph_b"])
    result["graph_b"] = add_graph_coverage_fields(result["graph_b"])

    # Consistency between Graph A (causal_graph) and Graph B is pure derivation.
    result["graph_consistency"] = compare_graphs(result["causal_graph"], result["graph_b"])

    result["pre_intervention_trust"] = assess_pre_intervention_trust(
        result["pre_internal_alignment"],
        result["graph_consistency"],
        result["causal_graph"],
        result["graph_b"],
    )

    # Framework's algorithmic suppression ranking (independent of VLM).
    result["framework_suppression_picks"] = pick_suppression_framework(result["causal_graph"])

    # Optional external validation: if a verified GT file exists for this image,
    # compute strict / soft / topological scores against it. Surfaced in the UI
    # next to the trust panel; does NOT affect the trust score.
    result["gt_validation"] = derive_gt_validation(
        result.get("image_filename", ""),
        result["causal_graph"],
        result.get("graph_b", {}),
    )

    return result


def apply_inferred_block(prompt: str, allow_inferred: bool) -> str:
    """Substitute the {INFERRED_ENTITIES_BLOCK} placeholder with the relaxation
    paragraph (when allowed) or an empty string (when strict). If the placeholder
    is absent (user edited it out), the prompt is returned unchanged.
    """
    block = INFERRED_ENTITIES_BLOCK if allow_inferred else EMPTY_INFERRED_BLOCK
    return prompt.replace("{INFERRED_ENTITIES_BLOCK}", block)


def query_qwen(
    prompt: str, caption: str, image_contents: str | None, allow_inferred: bool = False
) -> dict[str, Any]:
    prompt = apply_inferred_block(prompt, allow_inferred)
    api_url = os.getenv("QWEN_API_URL", "http://localhost:11434/v1/chat/completions")
    api_key = os.getenv("QWEN_API_KEY", "")
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    response = requests.post(
        api_url,
        headers=headers,
        json=build_payload(prompt, caption, image_contents),
        timeout=120,
    )
    response.raise_for_status()

    data = response.json()
    message_content = data["choices"][0]["message"]["content"]
    if isinstance(message_content, list):
        text_parts = [part.get("text", "") for part in message_content if isinstance(part, dict)]
        message_content = "\n".join(text_parts)

    return normalize_result(extract_json_block(message_content), image_contents)


def normalize_graph_b(raw: dict[str, Any], detected_ids: set[str]) -> dict[str, Any]:
    """Normalize the Prompt 2 response into the same node/edge shape as Graph A.

    Defensive: missing fields default to placeholders, unrecognized targets/sources
    are kept (so the consistency comparison surfaces them) but flagged via warnings.
    """
    cg = raw.get("causal_graph") or {}

    nodes: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for n in cg.get("nodes") or []:
        if not isinstance(n, dict):
            continue
        nid = str(n.get("id", "")).strip()
        if not nid or nid in seen_ids:
            continue
        seen_ids.add(nid)
        nodes.append(
            {
                "id": nid,
                "label": str(n.get("label", "")).strip(),
                "state": str(n.get("state", "unknown")).strip() or "unknown",
                "hazardous": bool(n.get("hazardous", False)),
                "inferred": bool(n.get("inferred", False)),
            }
        )

    edges: list[dict[str, Any]] = []
    for e in cg.get("edges") or []:
        if not isinstance(e, dict):
            continue
        source = str(e.get("source", "")).strip()
        target = str(e.get("target", "")).strip()
        effect = str(e.get("effect", "")).strip() or "N/A"
        via_state = str(e.get("via_state", "")).strip() or "N/A"
        if not source or not target:
            continue
        edges.append(
            {
                "source": source,
                "target": target,
                "effect": effect,
                "via_state": via_state,
                "valid": source in seen_ids and target in seen_ids,
            }
        )

    pick = raw.get("suppression_pick") or {}
    suppression_pick = {
        "threat": str(pick.get("threat", "")).strip(),
        "state": str(pick.get("state", "")).strip(),
        "reason": str(pick.get("reason", "")).strip(),
    }

    return add_graph_coverage_fields({
        "nodes": nodes,
        "edges": edges,
        "suppression_pick": suppression_pick,
    })


def query_qwen_graph_b(
    detected_objects: list[dict[str, Any]],
    threats: list[dict[str, Any]],
    caption: str,
    image_contents: str | None,
    allow_inferred: bool = False,
) -> dict[str, Any]:
    """Run Prompt 2 against the same image+caption to extract Graph B.

    Strict context isolation: the model sees detected_objects + threats but
    NOT the recommendations from Prompt 1. The point is an independent graph.
    """
    api_url = os.getenv("QWEN_API_URL", "http://localhost:11434/v1/chat/completions")
    api_key = os.getenv("QWEN_API_KEY", "")
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    inferred_policy = (
        "Inferred entities are allowed. You may add presumed_<noun>_in_<existing_object_id> nodes only when clearly implied."
        if allow_inferred
        else "Inferred entities are NOT allowed. Do not add presumed_* nodes or off-camera entities; targets must be detected_objects ids."
    )

    context = {
        "detected_objects": [
            {k: o.get(k) for k in ("object_id", "label", "state", "bbox")}
            for o in detected_objects
        ],
        "threats": [
            {k: t.get(k) for k in ("object_id", "state", "reason")}
            for t in threats
        ],
    }
    user_text = (
        f"{GRAPH_B_PROMPT}\n\n"
        f"Inferred-entity policy:\n{inferred_policy}\n\n"
        f"Caption:\n{caption or 'N/A'}\n\n"
        f"Prior analysis (detected_objects + threats only — recommendations withheld):\n"
        f"{json.dumps(context, indent=2)}"
    )
    return _run_graph_b_call(user_text, image_contents, api_url, headers, detected_objects)


def query_qwen_graph_b_variant(
    detected_objects: list[dict[str, Any]],
    threats: list[dict[str, Any]],
    caption: str,
    image_contents: str | None,
    variant_id: str,
    allow_inferred: bool = False,
) -> dict[str, Any]:
    """Same as query_qwen_graph_b but swaps the opening paragraph for a variant.
    Used by Test 2 (Prompt Sensitivity)."""
    api_url = os.getenv("QWEN_API_URL", "http://localhost:11434/v1/chat/completions")
    api_key = os.getenv("QWEN_API_KEY", "")
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    inferred_policy = (
        "Inferred entities are allowed. You may add presumed_<noun>_in_<existing_object_id> nodes only when clearly implied."
        if allow_inferred
        else "Inferred entities are NOT allowed. Do not add presumed_* nodes or off-camera entities; targets must be detected_objects ids."
    )
    context = {
        "detected_objects": [
            {k: o.get(k) for k in ("object_id", "label", "state", "bbox")}
            for o in detected_objects
        ],
        "threats": [
            {k: t.get(k) for k in ("object_id", "state", "reason")}
            for t in threats
        ],
    }
    user_text = (
        f"{graph_b_prompt_for_variant(variant_id)}\n\n"
        f"Inferred-entity policy:\n{inferred_policy}\n\n"
        f"Caption:\n{caption or 'N/A'}\n\n"
        f"Prior analysis (detected_objects + threats only — recommendations withheld):\n"
        f"{json.dumps(context, indent=2)}"
    )
    return _run_graph_b_call(user_text, image_contents, api_url, headers, detected_objects)


def _run_graph_b_call(
    user_text: str,
    image_contents: str | None,
    api_url: str,
    headers: dict[str, str],
    detected_objects: list[dict[str, Any]],
) -> dict[str, Any]:
    """Shared Qwen call + normalize for Graph B (used by both base and variants)."""

    content: list[dict[str, Any]] = [{"type": "text", "text": user_text}]
    if image_contents:
        content.append({"type": "image_url", "image_url": {"url": image_contents}})

    payload = {
        "model": os.getenv("QWEN_MODEL_NAME", "qwen2.5vl:7b"),
        "messages": [{"role": "user", "content": content}],
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
    }

    response = requests.post(api_url, headers=headers, json=payload, timeout=120)
    response.raise_for_status()
    data = response.json()
    message_content = data["choices"][0]["message"]["content"]
    if isinstance(message_content, list):
        text_parts = [part.get("text", "") for part in message_content if isinstance(part, dict)]
        message_content = "\n".join(text_parts)

    raw = extract_json_block(message_content)
    detected_ids = {str(o.get("object_id", "")).strip() for o in detected_objects}
    return normalize_graph_b(raw, detected_ids)


# ────────────────────────────────────────────────────────────
# Pre-intervention batch report: aggregate metrics across runs
# ────────────────────────────────────────────────────────────

def load_run_jsons(folder: str) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Walk a folder and load every run_*/structured_response.json.

    Returns (loaded_runs, skipped) where loaded_runs is a list of normalized
    structured_response dicts and skipped is a list of {run_id, reason} for
    runs that couldn't be parsed or are missing required fields.
    """
    base = Path(folder).expanduser().resolve()
    loaded: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []

    if not base.exists() or not base.is_dir():
        return loaded, [{"run_id": "(folder)", "reason": f"not a directory: {base}"}]

    # Accept either a parent dir of run_* dirs OR a single run_* dir OR the new
    # batch layout where run_* dirs live under <base>/runs/.
    candidates = sorted([p for p in base.iterdir() if p.is_dir() and p.name.startswith("run_")])
    if not candidates and (base / "runs").is_dir():
        candidates = sorted([p for p in (base / "runs").iterdir() if p.is_dir() and p.name.startswith("run_")])
    if not candidates and base.name.startswith("run_"):
        candidates = [base]

    for run_dir in candidates:
        sr_path = run_dir / "structured_response.json"
        if not sr_path.exists():
            skipped.append({"run_id": run_dir.name, "reason": "structured_response.json missing"})
            continue
        try:
            payload = json.loads(sr_path.read_text())
        except Exception as exc:
            skipped.append({"run_id": run_dir.name, "reason": f"json parse failed: {exc}"})
            continue
        sr = payload.get("structured_response") if isinstance(payload, dict) else None
        if not isinstance(sr, dict):
            skipped.append({"run_id": run_dir.name, "reason": "structured_response key missing"})
            continue
        sr.setdefault("run_id", run_dir.name)
        loaded.append(sr)

    return loaded, skipped


def _percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    sv = sorted(values)
    if len(sv) == 1:
        return sv[0]
    k = (len(sv) - 1) * p
    f = int(k)
    c = min(f + 1, len(sv) - 1)
    if f == c:
        return sv[f]
    return sv[f] + (sv[c] - sv[f]) * (k - f)


def _summarize(values: list[float]) -> dict[str, float]:
    if not values:
        return {"n": 0, "median": 0.0, "p25": 0.0, "p75": 0.0, "min": 0.0, "max": 0.0, "mean": 0.0}
    return {
        "n": len(values),
        "median": _percentile(values, 0.5),
        "p25": _percentile(values, 0.25),
        "p75": _percentile(values, 0.75),
        "min": min(values),
        "max": max(values),
        "mean": sum(values) / len(values),
    }


def compute_pre_intervention_report(runs: list[dict[str, Any]]) -> dict[str, Any]:
    """Pure aggregation over a list of normalized structured_response dicts.

    Non-disaster runs (disaster_scenario != "Yes") are excluded from metric
    aggregation — they have no causal structure to evaluate and would inflate
    every consistency score to vacuous-perfect. Their count is surfaced
    separately so the user knows how many were filtered.
    """
    n_total = len(runs)

    def is_disaster(r: dict[str, Any]) -> bool:
        return str(r.get("disaster_scenario", "")).strip().lower() == "yes"

    disaster_runs = [r for r in runs if is_disaster(r)]
    non_disaster_runs = [r for r in runs if not is_disaster(r)]
    n_runs = len(disaster_runs)

    if n_runs == 0:
        return {
            "n_runs": 0,
            "n_runs_total": n_total,
            "n_runs_non_disaster": len(non_disaster_runs),
            "non_disaster_run_ids": [r.get("run_id", "?") for r in non_disaster_runs],
            "trust_distribution": {},
            "metric_distributions": {},
            "failure_histogram": [],
            "scene_level": {},
            "outliers": [],
            "per_run": [],
            "by_category": [],
        }
    runs = disaster_runs  # aggregate only over disaster runs from here on

    # Trust level histogram
    trust_levels = [str(r.get("pre_intervention_trust", {}).get("level", "unknown")) for r in runs]
    trust_dist: dict[str, int] = {}
    for level in trust_levels:
        trust_dist[level] = trust_dist.get(level, 0) + 1

    # Metric distributions
    metric_keys = [
        ("a_fidelity",                lambda r: r.get("graph_consistency", {}).get("a_fidelity")),
        ("b_coverage",                lambda r: r.get("graph_consistency", {}).get("b_coverage")),
        ("topological_consistency",   lambda r: r.get("graph_consistency", {}).get("topological_consistency")),
        ("node_consistency",          lambda r: r.get("graph_consistency", {}).get("node_consistency")),
        ("flag_consistency",          lambda r: r.get("graph_consistency", {}).get("flag_consistency")),
        ("coverage_a",                lambda r: r.get("causal_graph", {}).get("threat_reasoning_coverage")),
        ("coverage_b",                lambda r: r.get("graph_b", {}).get("threat_reasoning_coverage")),
        ("internal_alignment",        lambda r: r.get("pre_internal_alignment", {}).get("score")),
        ("trust_score",               lambda r: r.get("pre_intervention_trust", {}).get("score")),
        ("disaster_level",            lambda r: r.get("disaster_level")),
    ]
    metric_dists: dict[str, dict[str, float]] = {}
    for name, getter in metric_keys:
        vals: list[float] = []
        for r in runs:
            v = getter(r)
            try:
                if v is None:
                    continue
                vals.append(float(v))
            except (TypeError, ValueError):
                continue
        metric_dists[name] = _summarize(vals)

    # Failure histogram (across all runs)
    failure_counts: dict[str, int] = {}
    for r in runs:
        for f in r.get("pre_internal_alignment", {}).get("failures", []) or []:
            t = str(f.get("type", ""))
            if t:
                failure_counts[t] = failure_counts.get(t, 0) + 1
    failure_hist = sorted(failure_counts.items(), key=lambda kv: (-kv[1], kv[0]))
    failure_hist_list = [{"type": t, "count": c} for t, c in failure_hist]

    # Scene-level averages
    n_threats = [len(r.get("threats", []) or []) for r in runs]
    n_recs = [len(r.get("recommendations", []) or []) for r in runs]
    n_edges_a = [len(r.get("causal_graph", {}).get("edges", []) or []) for r in runs]
    n_edges_b = [len(r.get("graph_b", {}).get("edges", []) or []) for r in runs]
    n_detected = [len(r.get("detected_objects", []) or []) for r in runs]
    scene_level = {
        "detected_objects":   _summarize([float(x) for x in n_detected]),
        "threats_per_scene":  _summarize([float(x) for x in n_threats]),
        "recs_per_scene":     _summarize([float(x) for x in n_recs]),
        "edges_in_a":         _summarize([float(x) for x in n_edges_a]),
        "edges_in_b":         _summarize([float(x) for x in n_edges_b]),
    }

    # Outliers worth inspecting
    def safe_metric(r, key1, key2, default=None):
        v = r.get(key1, {}).get(key2)
        try:
            return float(v) if v is not None else default
        except (TypeError, ValueError):
            return default

    runs_with_id = [(r.get("run_id", "?"), r) for r in runs]
    outliers: list[dict[str, Any]] = []

    by_a_fid = sorted(runs_with_id, key=lambda x: safe_metric(x[1], "graph_consistency", "a_fidelity", 1.0))
    if by_a_fid:
        rid, r = by_a_fid[0]
        outliers.append({"label": "Lowest A-fidelity", "run_id": rid,
                         "value": f"{safe_metric(r, 'graph_consistency', 'a_fidelity', 1.0):.2f}"})
    by_b_cov = sorted(runs_with_id, key=lambda x: safe_metric(x[1], "graph_consistency", "b_coverage", 1.0))
    if by_b_cov:
        rid, r = by_b_cov[0]
        outliers.append({"label": "Lowest B-coverage", "run_id": rid,
                         "value": f"{safe_metric(r, 'graph_consistency', 'b_coverage', 1.0):.2f}"})
    by_failure_count = sorted(
        runs_with_id,
        key=lambda x: -len(x[1].get("pre_internal_alignment", {}).get("failures", []) or []),
    )
    if by_failure_count:
        rid, r = by_failure_count[0]
        fc = len(r.get("pre_internal_alignment", {}).get("failures", []) or [])
        outliers.append({"label": "Most alignment failures", "run_id": rid, "value": f"{fc}"})
    by_trust = sorted(runs_with_id, key=lambda x: safe_metric(x[1], "pre_intervention_trust", "score", 1.0))
    if by_trust:
        rid, r = by_trust[0]
        outliers.append({"label": "Lowest trust score", "run_id": rid,
                         "value": f"{safe_metric(r, 'pre_intervention_trust', 'score', 0.0):.2f}"})

    # Per-run mini summary (for reference / drill-down)
    per_run = []
    for r in runs:
        per_run.append({
            "run_id":          r.get("run_id", "?"),
            "trust_level":     r.get("pre_intervention_trust", {}).get("level", "unknown"),
            "trust_score":     safe_metric(r, "pre_intervention_trust", "score", 0.0) or 0.0,
            "a_fidelity":      safe_metric(r, "graph_consistency", "a_fidelity", 0.0) or 0.0,
            "b_coverage":      safe_metric(r, "graph_consistency", "b_coverage", 0.0) or 0.0,
            "internal":        safe_metric(r, "pre_internal_alignment", "score", 0.0) or 0.0,
            "n_threats":       len(r.get("threats", []) or []),
            "n_recs":          len(r.get("recommendations", []) or []),
            "n_failures":      len(r.get("pre_internal_alignment", {}).get("failures", []) or []),
        })

    # Per-category breakdown (using folder-derived disaster_category)
    by_category: dict[str, list[dict[str, Any]]] = {}
    for r in runs:
        cat = str(r.get("disaster_category") or "").strip() or "(uncategorized)"
        by_category.setdefault(cat, []).append(r)

    category_breakdown: list[dict[str, Any]] = []
    for cat in sorted(by_category):
        cat_runs = by_category[cat]
        cat_trust = {"high": 0, "moderate": 0, "low": 0}
        for r in cat_runs:
            lvl = str(r.get("pre_intervention_trust", {}).get("level", "")).lower()
            if lvl in cat_trust:
                cat_trust[lvl] += 1
        def _med(getter):
            vals = []
            for r in cat_runs:
                v = getter(r)
                try:
                    if v is None: continue
                    vals.append(float(v))
                except (TypeError, ValueError):
                    continue
            return _percentile(vals, 0.5) if vals else 0.0
        category_breakdown.append({
            "category": cat,
            "n": len(cat_runs),
            "trust": cat_trust,
            "a_fidelity_median": _med(lambda r: r.get("graph_consistency", {}).get("a_fidelity")),
            "b_coverage_median": _med(lambda r: r.get("graph_consistency", {}).get("b_coverage")),
            "internal_median":    _med(lambda r: r.get("pre_internal_alignment", {}).get("score")),
            "trust_score_median": _med(lambda r: r.get("pre_intervention_trust", {}).get("score")),
        })

    return {
        "n_runs": n_runs,
        "n_runs_total": n_total,
        "n_runs_non_disaster": len(non_disaster_runs),
        "non_disaster_run_ids": [r.get("run_id", "?") for r in non_disaster_runs],
        "trust_distribution": trust_dist,
        "metric_distributions": metric_dists,
        "failure_histogram": failure_hist_list,
        "scene_level": scene_level,
        "outliers": outliers,
        "per_run": per_run,
        "by_category": category_breakdown,
    }


def draw_bboxes(image: Image.Image, objects: list[dict[str, Any]], color: str) -> Image.Image:
    canvas = image.copy()
    draw = ImageDraw.Draw(canvas)
    for item in objects:
        bbox = item.get("bbox")
        if not bbox:
            continue
        draw.rectangle(bbox, outline=color, width=5)
        label_bg = [bbox[0], max(0, bbox[1] - 24), min(image.width, bbox[0] + 180), bbox[1]]
        draw.rectangle(label_bg, fill=color)
        draw.text((bbox[0] + 6, max(0, bbox[1] - 20)), item["label"], fill="white")
    return canvas


def make_overlay_preview(image_contents: str | None, objects: list[dict[str, Any]]) -> str | None:
    image, _mime_type = open_uploaded_image(image_contents)
    if not image:
        return image_contents

    boxed = draw_bboxes(image, objects, "#ea580c")
    output = io.BytesIO()
    boxed.save(output, format="PNG")
    return image_bytes_to_data_url(output.getvalue())


def make_single_object_preview(
    image_contents: str | None, item: dict[str, Any], is_hazardous: bool = True
) -> str | None:
    image, _mime_type = open_uploaded_image(image_contents)
    if not image:
        return None

    # Red bbox for active threats, blue for affected (non-hazardous) entities.
    color = "#dc2626" if is_hazardous else "#2563eb"
    boxed = draw_bboxes(image, [{"label": item["label"], "bbox": item.get("bbox")}], color)
    output = io.BytesIO()
    boxed.save(output, format="PNG")
    return image_bytes_to_data_url(output.getvalue())


def reasoning_pill(kind: str = "reasoning", visible: bool = True) -> html.Span:
    """A small standalone pill marking a field as model reasoning, not observation.

    `kind` ∈ {"reasoning", "assumption", "uncertainty"} drives label and color.
    When `visible` is False, returns an empty span — content the pill marks
    stays visible, only the marker is hidden.
    """
    if not visible:
        return html.Span()
    label_map = {
        "reasoning": "reasoning",
        "assumption": "assumption",
        "uncertainty": "uncertain",
    }
    return html.Span(
        label_map.get(kind, "reasoning"),
        className=f"reasoning-marker reasoning-marker-{kind}",
    )


def reasoning_note(text: str, kind: str = "reasoning", show_pill: bool = True) -> html.Div:
    """Block rendering of an assumption/uncertainty string in the summary panel.

    Carries the body text and (optionally) a color-coded marker. The tinted
    left border on the container survives even when the pill is hidden, so the
    note remains visually distinct without the explicit tag.

    (TODO: post-intervention CEE+ analysis may want to track whether
    assumptions/uncertainty themselves shift under suppression — separate idea,
    not the current per-field marker work.)
    """
    return html.Div(
        [
            reasoning_pill(kind, visible=show_pill),
            html.Span(text, className="reasoning-note-text"),
        ],
        className=f"reasoning-note reasoning-note-{kind}",
    )


CYTOSCAPE_STYLESHEET = [
    # base node
    {"selector": "node", "style": {
        "content": "data(label)",
        "font-size": "11px",
        "font-weight": "600",
        "text-valign": "center",
        "text-halign": "center",
        "text-wrap": "wrap",
        "text-max-width": "120px",
        "background-color": "#e2e8f0",
        "border-color": "#94a3b8",
        "border-width": 2,
        "color": "#1f2933",
        "width": 70,
        "height": 50,
        "shape": "round-rectangle",
    }},
    # affected entity (non-hazardous, in someone else's reach)
    {"selector": "node.affected", "style": {
        "background-color": "rgba(37, 99, 235, 0.18)",
        "border-color": "#2563eb",
    }},
    # threat (hazardous, has outgoing edges)
    {"selector": "node.threat", "style": {
        "background-color": "rgba(220, 38, 38, 0.18)",
        "border-color": "#dc2626",
    }},
    # orphan threat (hazardous but zero outgoing edges)
    {"selector": "node.orphan-threat", "style": {
        "background-color": "rgba(220, 38, 38, 0.10)",
        "border-color": "#dc2626",
        "border-style": "dashed",
        "border-width": 3,
    }},
    # inferred entity (presumed)
    {"selector": "node.inferred", "style": {
        "background-color": "rgba(139, 92, 246, 0.14)",
        "border-color": "#8b5cf6",
        "border-style": "dashed",
    }},
    # unresolved endpoint from an invalid model edge
    {"selector": "node.unresolved", "style": {
        "background-color": "rgba(163, 163, 163, 0.14)",
        "border-color": "#737373",
        "border-style": "dotted",
        "color": "#525252",
    }},
    # base edge
    {"selector": "edge", "style": {
        "content": "data(label)",
        "font-size": "9px",
        "color": "#475569",
        "text-rotation": "autorotate",
        "text-margin-y": -8,
        "curve-style": "bezier",
        "target-arrow-shape": "triangle",
        "width": 2,
        "line-color": "#94a3b8",
        "target-arrow-color": "#94a3b8",
    }},
    # harm-family edges
    {"selector": "edge.harm", "style": {
        "line-color": "#dc2626",
        "target-arrow-color": "#dc2626",
    }},
    # propagation-family edges
    {"selector": "edge.propagate", "style": {
        "line-color": "#ea580c",
        "target-arrow-color": "#ea580c",
        "line-style": "dashed",
    }},
    # structural-family edges (blocks/isolates/exposes)
    {"selector": "edge.structural", "style": {
        "line-color": "#0ea5e9",
        "target-arrow-color": "#0ea5e9",
    }},
    # invalid edge (target/source unresolved)
    {"selector": "edge.invalid", "style": {
        "line-color": "#a3a3a3",
        "target-arrow-color": "#a3a3a3",
        "line-style": "dotted",
        "opacity": 0.6,
    }},
]


HARM_EFFECTS = {"may_harm", "threatens"}
PROPAGATE_EFFECTS = {"may_spread_to", "increases_risk_to", "worsens"}
STRUCTURAL_EFFECTS = {"blocks_access_to", "isolates", "exposes"}

# Dropdown vocabularies for the Ground Truth editor.
# "undetermined" is a special marker the annotator can pick when uncertain;
# downstream Test 1 may exclude such entries from strict comparison.
UNDETERMINED = "undetermined"
GT_HAZARD_STATES = [
    "burning", "burnt", "collapsed", "collapsing", "fallen", "crushed", "flooded",
    "leaking", "bleeding", "injured", "approaching", "charging", "aiming",
    "coiled", "rabid", "armed", "fleeing", "striking", "rising",
    "spreading", "billowing", "seeping", "escalating",
]
GT_NORMAL_STATES = [
    "intact", "standing", "upright", "whole", "dry", "sealed",
    "uninjured", "healthy", "stationary", "resting", "disengaged",
    "relaxed", "unarmed", "stable", "contained", "dissipating", "steady",
]
GT_ALL_STATES = GT_HAZARD_STATES + GT_NORMAL_STATES + [UNDETERMINED]
GT_EFFECTS = [
    "may_harm", "may_spread_to", "blocks_access_to", "isolates",
    "exposes", "increases_risk_to", "worsens", "threatens", UNDETERMINED,
]


def _gt_state_options() -> list[dict[str, str]]:
    return (
        [{"label": "── hazard-bearing ──", "value": "__hdr_h", "disabled": True}]
        + [{"label": s, "value": s} for s in GT_HAZARD_STATES]
        + [{"label": "── normal ──", "value": "__hdr_n", "disabled": True}]
        + [{"label": s, "value": s} for s in GT_NORMAL_STATES]
        + [{"label": "── special ──", "value": "__hdr_s", "disabled": True}]
        + [{"label": UNDETERMINED, "value": UNDETERMINED}]
    )


def _gt_effect_options() -> list[dict[str, str]]:
    return [{"label": e, "value": e} for e in GT_EFFECTS]


def graph_to_cytoscape_elements(graph: dict[str, Any]) -> list[dict[str, Any]]:
    """Convert a normalized graph dict (Graph A or Graph B shape) into the
    cytoscape elements list format. Adds node/edge classes for styling.
    """
    nodes = graph.get("nodes") or []
    edges = graph.get("edges") or []
    node_ids = {str(n.get("id", "")).strip() for n in nodes if str(n.get("id", "")).strip()}

    # Compute outgoing-edge count per source so we can mark orphan threats.
    outgoing_count: dict[str, int] = {}
    for e in edges:
        outgoing_count[e.get("source", "")] = outgoing_count.get(e.get("source", ""), 0) + 1

    elements: list[dict[str, Any]] = []
    for n in nodes:
        nid = str(n.get("id", "")).strip()
        # Skip nodes with empty id — cytoscape rejects them. Common during editing
        # when the user clicks "+ Add Node" before filling in the id field.
        if not nid:
            continue
        hazardous = bool(n.get("hazardous", False))
        inferred = bool(n.get("inferred", False))
        state = n.get("state", "unknown")
        label = f"{n.get('label', '')}\n({state})"

        if inferred:
            cls = "inferred"
        elif hazardous and outgoing_count.get(nid, 0) == 0:
            cls = "orphan-threat"
        elif hazardous:
            cls = "threat"
        else:
            cls = "affected"

        elements.append({
            "data": {
                "id": nid,
                "label": label,
                "state": state,
                "hazardous": hazardous,
                "inferred": inferred,
            },
            "classes": cls,
        })

    unresolved_ids: set[str] = set()
    for e in edges:
        source = str(e.get("source", "")).strip()
        target = str(e.get("target", "")).strip()
        # Skip edges with empty endpoints entirely — cytoscape rejects them.
        if not source or not target:
            continue
        for endpoint in (source, target):
            if endpoint and endpoint not in node_ids and endpoint not in unresolved_ids:
                unresolved_ids.add(endpoint)
                elements.append({
                    "data": {
                        "id": endpoint,
                        "label": f"{endpoint}\n(unresolved)",
                        "state": "unresolved",
                        "hazardous": False,
                        "inferred": False,
                        "unresolved": True,
                    },
                    "classes": "unresolved",
                })

        effect = e.get("effect", "")
        if effect in HARM_EFFECTS:
            cls = "harm"
        elif effect in PROPAGATE_EFFECTS:
            cls = "propagate"
        elif effect in STRUCTURAL_EFFECTS:
            cls = "structural"
        else:
            cls = ""
        if not e.get("valid", True):
            cls = (cls + " invalid").strip()

        elements.append({
            "data": {
                "source": source,
                "target": target,
                "label": effect,
                "via_state": e.get("via_state", ""),
            },
            "classes": cls,
        })

    return elements


def make_graph_coverage_strip(graph: dict[str, Any]) -> html.Div:
    """Show threat_reasoning_coverage and orphan_threats under Graph A.

    Coverage = fraction of declared (object_id, state) threats that produced
    at least one outgoing quad. Orphan threats are declared-but-unreasoned —
    a CEE+-relevant Layer 2 → Layer 3 asymmetry.
    """
    # No threats yet = no coverage to compute. Show empty state instead of vacuous 1.00.
    if not (graph.get("nodes") or graph.get("intervention_candidates")):
        return html.Div(
            "Run analysis to compute threat reasoning coverage.",
            className="empty-state coverage-empty",
        )

    coverage = float(graph.get("threat_reasoning_coverage", 1.0) or 0.0)
    orphans = graph.get("orphan_threats") or []

    if coverage >= 0.85:
        color_class = "score-high"
    elif coverage >= 0.5:
        color_class = "score-mid"
    else:
        color_class = "score-low"

    orphan_block = (
        html.Div(
            [
                html.Span("Orphan threats: ", className="orphan-label"),
                html.Span(
                    ", ".join(f"({o.get('object_id', '')}, {o.get('state', '')})" for o in orphans),
                    className="orphan-list",
                ),
            ],
            className="orphan-row",
        )
        if orphans
        else html.Div("All declared threats produced at least one quad.", className="orphan-row orphan-clean")
    )

    return html.Div(
        [
            html.Div(
                [
                    html.Div(
                        [
                            html.Div("Threat reasoning coverage", className="consistency-score-label"),
                            html.Div(f"{coverage:.2f}", className=f"consistency-score-value {color_class}"),
                            html.Div(
                                "Declared threats with ≥1 outgoing quad.",
                                className="card-subtext",
                            ),
                        ],
                        className="consistency-score-card",
                    ),
                ],
                className="coverage-score-row",
            ),
            orphan_block,
        ],
        className="coverage-strip",
    )


def make_graph_text_view(graph: dict[str, Any]) -> html.Details:
    """Native collapsible, copy-pasteable text rendering of a graph."""
    nodes = graph.get("nodes") or []
    edges = graph.get("edges") or []
    lines = [f"NODES ({len(nodes)}):"]
    if nodes:
        for n in nodes:
            nid = str(n.get("id", "")).strip()
            state = str(n.get("state", "unknown")).strip() or "unknown"
            hazardous = bool(n.get("hazardous", False))
            inferred = bool(n.get("inferred", False))
            suffix = "   inferred=True" if inferred else ""
            lines.append(f"  {nid:<18} state={state:<12} hazardous={hazardous}{suffix}")
    else:
        lines.append("  (none)")

    lines.append(f"EDGES ({len(edges)}):")
    if edges:
        for e in edges:
            source = str(e.get("source", "")).strip()
            target = str(e.get("target", "")).strip()
            effect = str(e.get("effect", "")).strip()
            via_state = str(e.get("via_state", "")).strip()
            valid = "" if e.get("valid", True) else "   valid=False"
            lines.append(f"  {source} --[{effect} | via:{via_state}]--> {target}{valid}")
    else:
        lines.append("  (none)")

    return html.Details(
        [
            html.Summary("View as text"),
            html.Pre("\n".join(lines), className="graph-text-pre"),
        ],
        className="graph-text-view",
    )


def graph_to_cytoscape_elements_vs_gt(
    graph: dict[str, Any],
    gt_edge_keys: set[tuple[str, str, str, str]],
    role: str = "candidate",
    gt_fuzzy_keys: set[tuple[str, str, str, str]] | None = None,
    gt_topo_keys: set[tuple[str, str, str]] | None = None,
    nodes_by_id: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Tags each candidate-graph edge by GT match tier.

    Tiers (most specific first):
      - "gt-match"  : exact 4-tuple (strict)
      - "gt-soft"   : matches via label hierarchy + state synonym + effect close-pair
      - "gt-topo"   : matches structurally (label class + effect family), state ignored
      - "gt-miss"   : no match at any tier

    role="gt" tags edges as "gt-self".
    """
    base_elements = graph_to_cytoscape_elements(graph)

    def ekey(d: dict[str, Any]) -> tuple[str, str, str, str]:
        return (
            str(d.get("source", "")).strip(),
            str(d.get("via_state", "")).strip(),
            str(d.get("label", "") or d.get("effect", "")).strip(),
            str(d.get("target", "")).strip(),
        )

    out: list[dict[str, Any]] = []
    for el in base_elements:
        data = el.get("data", {})
        if "source" in data and "target" in data:
            classes = el.get("classes", "")
            if role == "gt":
                extra = "gt-self"
            else:
                key = ekey(data)
                synth_edge = {
                    "source": data.get("source"),
                    "target": data.get("target"),
                    "via_state": data.get("via_state"),
                    "effect": data.get("label", "") or data.get("effect", ""),
                }
                if key in gt_edge_keys:
                    extra = "gt-match"
                elif (
                    gt_fuzzy_keys is not None and nodes_by_id is not None
                    and _fuzzy_edge_key(synth_edge, nodes_by_id) in gt_fuzzy_keys
                ):
                    extra = "gt-soft"
                elif (
                    gt_topo_keys is not None and nodes_by_id is not None
                    and _topological_edge_key(synth_edge, nodes_by_id) in gt_topo_keys
                ):
                    extra = "gt-topo"
                else:
                    extra = "gt-miss"
            el = {**el, "classes": (classes + " " + extra).strip()}
        out.append(el)
    return out


def make_graph_diff_viewer(
    graph: dict[str, Any],
    gt_edge_keys: set[tuple[str, str, str, str]],
    elem_id: str,
    role: str = "candidate",
    height: str = "260px",
    gt_fuzzy_keys: set[tuple[str, str, str, str]] | None = None,
    gt_topo_keys: set[tuple[str, str, str]] | None = None,
) -> html.Div:
    """Cytoscape viewer with edges colored by GT match tier (strict / soft / topo / miss)."""
    nodes_by_id = {n.get("id", ""): n for n in graph.get("nodes") or []}
    elements = graph_to_cytoscape_elements_vs_gt(
        graph, gt_edge_keys, role=role,
        gt_fuzzy_keys=gt_fuzzy_keys, gt_topo_keys=gt_topo_keys,
        nodes_by_id=nodes_by_id,
    )
    if not elements:
        return html.Div("Graph empty.", className="empty-state")
    return html.Div(
        cyto.Cytoscape(
            id=elem_id,
            elements=elements,
            stylesheet=CYTOSCAPE_STYLESHEET + GT_DIFF_OVERRIDES,
            layout={"name": "cose", "padding": 14, "animate": False, "fit": True},
            style={"width": "100%", "height": height, "maxWidth": "100%"},
        ),
        className="graph-container",
        style={"height": height},
    )


# Extra cytoscape stylesheet entries for the GT-diff viewer
GT_DIFF_OVERRIDES = [
    # Strict match (exact 4-tuple) → dark green
    {"selector": "edge.gt-match", "style": {
        "line-color": "#15803d",
        "target-arrow-color": "#15803d",
        "width": 3,
    }},
    # Soft match (label hierarchy + state synonyms + effect close-pair) → light green
    {"selector": "edge.gt-soft", "style": {
        "line-color": "#84cc16",
        "target-arrow-color": "#84cc16",
        "line-style": "dashed",
        "width": 2.5,
    }},
    # Topological match (state-blind, structural agreement) → yellow/orange
    {"selector": "edge.gt-topo", "style": {
        "line-color": "#eab308",
        "target-arrow-color": "#eab308",
        "line-style": "dashed",
        "width": 2,
    }},
    # No match at any level → red
    {"selector": "edge.gt-miss", "style": {
        "line-color": "#b91c1c",
        "target-arrow-color": "#b91c1c",
        "line-style": "dashed",
        "width": 2,
    }},
    # GT graph's own edges — neutral
    {"selector": "edge.gt-self", "style": {
        "line-color": "#475569",
        "target-arrow-color": "#475569",
        "width": 2,
    }},
]


def make_causal_graph_viewer(
    graph: dict[str, Any],
    elem_id: str,
    height: str = "320px",
) -> html.Div:
    """Reusable cytoscape graph component. Used twice: Graph A and Graph B."""
    elements = graph_to_cytoscape_elements(graph)
    if not elements:
        return html.Div("Graph empty.", className="empty-state")
    return html.Div(
        cyto.Cytoscape(
            id=elem_id,
            elements=elements,
            stylesheet=CYTOSCAPE_STYLESHEET,
            layout={"name": "cose", "padding": 20, "animate": False, "fit": True},
            style={"width": "100%", "height": height, "maxWidth": "100%"},
            autoungrabify=False,
            userZoomingEnabled=True,
            userPanningEnabled=True,
        ),
        className="graph-container",
        style={"height": height},
    )


def make_consistency_panel(consistency: dict[str, Any]) -> html.Div:
    """Renders Graph A vs Graph B consistency: numeric scores + diff lists."""
    if not consistency:
        return html.Div("Consistency unavailable.", className="empty-state")

    # Vacuous-perfect guard: if neither graph has any nodes/edges, there's
    # nothing to compare. Show empty state instead of misleading 1.00 scores.
    nd = consistency.get("node_diff", {}) or {}
    ed = consistency.get("edge_diff", {}) or {}
    has_data = bool(
        nd.get("only_in_a") or nd.get("only_in_b") or nd.get("in_both")
        or ed.get("only_in_a") or ed.get("only_in_b") or ed.get("in_both")
    )
    if not has_data:
        return html.Div(
            "Run analysis to compare Graph A and Graph B.",
            className="empty-state",
        )

    score_subtext = {
        "A-fidelity": "Recs' edges that B also claims. Low = fabrication.",
        "B-coverage": "B's edges that recs act on. Low = under-recommendation.",
        "Topological": "Same source→target, effect ignored.",
        "Node": "Same entities in A and B.",
        "Hazardous flag": "Same entities marked hazardous.",
    }

    def score_card(label: str, value: float) -> html.Div:
        # color the score by band
        if value >= 0.85:
            color_class = "score-high"
        elif value >= 0.5:
            color_class = "score-mid"
        else:
            color_class = "score-low"
        return html.Div(
            [
                html.Div(label, className="consistency-score-label"),
                html.Div(f"{value:.2f}", className=f"consistency-score-value {color_class}"),
                html.Div(score_subtext.get(label, ""), className="card-subtext"),
            ],
            className="consistency-score-card",
        )

    node_diff = consistency.get("node_diff", {})
    edge_diff = consistency.get("edge_diff", {})
    effect_disagreements = consistency.get("effect_disagreements", [])
    flags = consistency.get("flag_agreement", [])

    def diff_list(title: str, items: list[Any], formatter, empty_text: str = "(none)") -> html.Div:
        if not items:
            return html.Div(
                [html.Div(title, className="diff-list-title"), html.Div(empty_text, className="diff-empty")],
                className="diff-list",
            )
        return html.Div(
            [
                html.Div(f"{title} ({len(items)})", className="diff-list-title"),
                html.Ul([html.Li(formatter(it)) for it in items], className="diff-ul"),
            ],
            className="diff-list",
        )

    edge_fmt = lambda e: f"{e.get('source')} —[{e.get('effect')} | via:{e.get('via_state')}]→ {e.get('target')}"
    node_fmt = lambda nid: nid
    effect_fmt = lambda e: (
        f"{e.get('source')} → {e.get('target')}: "
        f"A={', '.join(e.get('graph_a_effects', [])) or '∅'}; "
        f"B={', '.join(e.get('graph_b_effects', [])) or '∅'}"
    )

    # Flag disagreements only — agreements are noise
    disagreements = [f for f in flags if not f["agree"]]
    flag_block = html.Div(
        [
            html.Div(f"Hazardous-flag disagreements ({len(disagreements)})", className="diff-list-title"),
            html.Div("Same node, different hazardous=True/False.", className="diff-help-text"),
            (
                html.Ul(
                    [
                        html.Li(f"{f['id']}: A={f['graph_a']}, B={f['graph_b']}")
                        for f in disagreements
                    ],
                    className="diff-ul",
                )
                if disagreements
                else html.Div("None; shared nodes have matching hazardous flags.", className="diff-empty")
            ),
        ],
        className="diff-list",
    )

    return html.Div(
        [
            html.Details(
                [
                    html.Summary(
                        "What is A↔B consistency and why does it matter? (click to expand)",
                        className="gt-val-explainer-summary",
                    ),
                    html.Div(
                        [
                            html.P([
                                html.B("What: "),
                                "We ask the VLM the same scene twice with different prompts. ",
                                html.B("Prompt 1 "), "produces recommendations + a derived graph (Graph A). ",
                                html.B("Prompt 2 "), "asks for the causal graph directly without recommendations (Graph B). ",
                                "This card compares the two graphs against each other.",
                            ]),
                            html.P([
                                html.B("Why: "),
                                "If the model's recommendations (A) don't match its own independent causal reasoning (B), the recommendations are ",
                                html.I("declarative — not mechanistically grounded"),
                                ". This is the core failure mode CEE+ is designed to catch. ",
                                "Note: this measures self-consistency, NOT correctness. The model could be self-consistent and still wrong about the world; for that, see the External Validation card.",
                            ]),
                            html.P([
                                html.B("Reading the scores: "),
                                html.B("A-fidelity "), "= fraction of A's edges that B also asserts. Low = model recommends actions based on causal claims it doesn't independently endorse (fabrication). ",
                                html.B("B-coverage "), "= fraction of B's edges that A's recommendations act on. Low = model believes in threats it didn't recommend acting on (under-recommendation). ",
                                html.B("Topological "), "= same source→target structure regardless of effect label. ",
                                html.B("Node / Hazardous flag "), "= same entities present and same hazardous=true/false agreement.",
                            ], style={"marginBottom": "0"}),
                        ],
                        className="gt-val-explainer-body",
                    ),
                ],
                className="gt-val-explainer",
                style={"marginBottom": "10px"},
            ),
            html.Div(
                [
                    score_card("A-fidelity", consistency.get("a_fidelity", 0.0)),
                    score_card("B-coverage", consistency.get("b_coverage", 0.0)),
                    score_card("Topological", consistency.get("topological_consistency", 0.0)),
                    score_card("Node", consistency.get("node_consistency", 0.0)),
                    score_card("Hazardous flag", consistency.get("flag_consistency", 0.0)),
                ],
                className="consistency-score-row",
            ),
            html.Div(
                [
                    diff_list(
                        "Nodes only in A (recs)",
                        node_diff.get("only_in_a", []),
                        node_fmt,
                        "None; A adds no extra entities.",
                    ),
                    diff_list(
                        "Nodes only in B (VLM graph)",
                        node_diff.get("only_in_b", []),
                        node_fmt,
                        "None; B adds no extra entities.",
                    ),
                    diff_list(
                        "Edges only in A (recs)",
                        edge_diff.get("only_in_a", []),
                        edge_fmt,
                        "None; A adds no unique causal edges.",
                    ),
                    diff_list(
                        "Edges only in B (VLM graph)",
                        edge_diff.get("only_in_b", []),
                        edge_fmt,
                        "None; B adds no unique causal edges.",
                    ),
                    diff_list(
                        "Effect disagreements",
                        effect_disagreements,
                        effect_fmt,
                        "None; shared source-target links use the same effect.",
                    ),
                    flag_block,
                ],
                className="diff-grid",
            ),
        ],
        className="consistency-panel",
    )


FAILURE_SEVERITY = {
    # HIGH — schema-breaking: graph cannot stand without this fix
    "threat_missing_detected_object": "high",
    "recommendation_threat_not_declared": "high",
    "invalid_effect_label": "high",
    "unresolved_affected_object": "high",
    "related_object_missing_detected_object": "high",
    "latent_active_conflict": "high",
    "invalid_self_loop_effect": "high",
    # MID — consistency: graph stands but contradicts itself
    "hazard_state_missing_from_threats": "mid",
    "normal_state_listed_as_threat": "mid",
    "threat_state_mismatch": "mid",
    "recommendation_state_mismatch": "mid",
    "threat_state_not_hazard_bearing": "mid",
    "quad_ids_missing_from_reason": "mid",
    "reason_ids_missing_from_links": "mid",
    "quad_ids_missing_from_related_object_ids": "mid",
    # LOW — duplication: cosmetic redundancy, model padded output
    "duplicate_recommendation_quad": "low",
    "duplicate_remaining_risk": "low",
}


def make_pre_internal_alignment_panel(alignment: dict[str, Any]) -> html.Div:
    """Render deterministic pre-intervention contract-consistency checks."""
    if not alignment:
        return html.Div("Pre-internal alignment unavailable.", className="empty-state")

    # Vacuous-perfect guard: no checks ran (passed + failed == 0) means no
    # analysis has happened. Don't show a misleading 1.00 score.
    passed = int(alignment.get("passed_checks", 0) or 0)
    failed = int(alignment.get("failed_checks", 0) or 0)
    total_checks = passed + failed
    if total_checks == 0:
        return html.Div(
            "Run analysis to compute internal alignment.",
            className="empty-state",
        )

    score = float(alignment.get("score", 1.0) or 0.0)
    if score >= 0.85:
        color_class = "score-high"
    elif score >= 0.5:
        color_class = "score-mid"
    else:
        color_class = "score-low"

    failures = alignment.get("failures", []) or []

    def severity_pill(failure_type: str) -> html.Span:
        sev = FAILURE_SEVERITY.get(failure_type, "mid")
        label_map = {"high": "schema", "mid": "consistency", "low": "duplication"}
        return html.Span(label_map[sev], className=f"failure-pill failure-pill-{sev}")

    def failure_detail_text(failure: dict[str, Any]) -> str:
        details: list[str] = []

        def fmt_value(value: Any) -> str:
            if isinstance(value, list):
                return "[" + ", ".join(fmt_value(v) for v in value) + "]"
            return str(value)

        if failure.get("recommendation_rank") is not None:
            details.append(f"rec rank={failure.get('recommendation_rank')}")
        if failure.get("object_id"):
            details.append(f"object_id={failure.get('object_id')}")
        if failure.get("affected_object"):
            details.append(f"affected_object={failure.get('affected_object')}")
        if failure.get("source") or failure.get("target"):
            details.append(f"edge={failure.get('source', '?')} -> {failure.get('target', '?')}")
        if failure.get("missing"):
            missing = failure.get("missing")
            if isinstance(missing, list):
                details.append(f"missing={', '.join(str(x) for x in missing)}")
            else:
                details.append(f"missing={missing}")
        if failure.get("duplicate_of_rank") is not None:
            details.append(f"duplicate_of_rank={failure.get('duplicate_of_rank')}")
        if failure.get("quad"):
            details.append(f"quad=({', '.join(fmt_value(x) for x in failure.get('quad', []))})")
        if failure.get("state"):
            details.append(f"state={failure.get('state')}")
        if failure.get("threat_state") or failure.get("detected_state"):
            details.append(f"threat_state={failure.get('threat_state')}; detected_state={failure.get('detected_state')}")
        if failure.get("cited_state") or failure.get("detected_state"):
            details.append(f"cited_state={failure.get('cited_state')}; detected_state={failure.get('detected_state')}")
        if failure.get("effect"):
            details.append(f"effect={failure.get('effect')}")
        return " · ".join(details)

    failure_rows = (
        [
            html.Li(
                [
                    html.Div(
                        [
                            severity_pill(f.get("type", "")),
                            html.Span(f.get("type", "failure"), className="failure-type"),
                            html.Span(f" — {f.get('message', '')}", className="failure-message"),
                        ],
                        className="failure-main-line",
                    ),
                    *(
                        [html.Div(failure_detail_text(f), className="failure-detail-line")]
                        if failure_detail_text(f)
                        else []
                    ),
                ]
            )
            for f in failures
        ]
        if failures
        else [html.Li("No contract-consistency failures detected.", className="diff-empty")]
    )

    return html.Div(
        [
            html.Details(
                [
                    html.Summary(
                        "What is internal alignment and why does it matter? (click to expand)",
                        className="gt-val-explainer-summary",
                    ),
                    html.Div(
                        [
                            html.P([
                                html.B("What: "),
                                "Deterministic ",
                                html.B("contract checks"),
                                " on the model's output — purely structural, no LLM judgment. ",
                                "Examples: every object_id mentioned in a recommendation actually appears in detected_objects; every threat has a recommendation; every recommendation's quad fields are populated; no two recommendations are duplicates of each other.",
                            ]),
                            html.P([
                                html.B("Why: "),
                                "Before we can ask 'is the model reasoning correctly,' we need to ask 'is the model's output even internally consistent at the format level.' ",
                                "This is the lowest-bar check — it catches the model contradicting itself in a single response (recommending action on 'house_1' that wasn't in detected_objects, or repeating the same recommendation twice with different wording). ",
                                "If internal alignment fails, every downstream signal (trust, A↔B consistency, GT comparison) is built on a broken foundation.",
                            ]),
                            html.P([
                                html.B("Severity tiers: "),
                                html.Span("schema", className="failure-pill failure-pill-high failure-pill-inline"),
                                " = output breaks the graph (e.g., undefined ID referenced). ",
                                html.Span("consistency", className="failure-pill failure-pill-mid failure-pill-inline"),
                                " = model contradicts itself (e.g., threat state doesn't match detected state). ",
                                html.Span("duplication", className="failure-pill failure-pill-low failure-pill-inline"),
                                " = redundant near-identical recommendations.",
                            ]),
                            html.P([
                                html.B("Reading: "),
                                "The score is passed / total checks. Number of checks varies per scene (more objects = more checks). This is the dominant component (40%) of the Trust score above.",
                            ], style={"fontStyle": "italic", "marginBottom": "0"}),
                        ],
                        className="gt-val-explainer-body",
                    ),
                ],
                className="gt-val-explainer",
                style={"marginBottom": "10px"},
            ),
            html.Div(
                [
                    html.Div(
                        [
                            html.Div("Internal alignment", className="consistency-score-label"),
                            html.Div(f"{score:.2f}", className=f"consistency-score-value {color_class}"),
                            html.Div(
                                "Passed divided by evaluated checks.",
                                className="card-subtext",
                            ),
                        ],
                        className="consistency-score-card",
                    ),
                    html.Div(
                        [
                            html.Div("Checks evaluated", className="consistency-score-label"),
                            html.Div(f"{passed}/{total_checks}", className="consistency-score-value score-high"),
                            html.Div("Applicable rules only.", className="card-subtext"),
                        ],
                        className="consistency-score-card",
                    ),
                    html.Div(
                        [
                            html.Div("Failed checks", className="consistency-score-label"),
                            html.Div(str(alignment.get("failed_checks", 0)), className=f"consistency-score-value {color_class}"),
                            html.Div("Contract violations.", className="card-subtext"),
                        ],
                        className="consistency-score-card",
                    ),
                ],
                className="consistency-score-row",
            ),
            html.Div(
                [
                    html.Div(
                        [
                            html.Span("schema", className="failure-pill failure-pill-high failure-pill-inline"),
                            " breaks the graph · ",
                            html.Span("consistency", className="failure-pill failure-pill-mid failure-pill-inline"),
                            " contradicts itself · ",
                            html.Span("duplication", className="failure-pill failure-pill-low failure-pill-inline"),
                            " is redundancy.",
                        ],
                        className="alignment-note",
                    ),
                    html.Div(
                        f"Inferred entities: {'allowed' if alignment.get('allow_inferred') else 'not allowed'}",
                        className="alignment-note muted",
                    ),
                    html.Div(
                        "Check count varies with the number of objects, threats, recommendations, and cited risks.",
                        className="alignment-note muted",
                    ),
                    html.Ul(failure_rows, className="diff-ul alignment-failure-list"),
                ],
                className="diff-list alignment-failures",
            ),
        ],
        className="consistency-panel",
    )


def make_suppression_panel(
    framework_picks: list[dict[str, Any]],
    vlm_pick: dict[str, Any],
) -> html.Div:
    """Side-by-side: framework's algorithmic ranking + VLM's pick.

    Agreement marker calls out whether the VLM picked the framework's #1.
    """
    vlm_threat = (vlm_pick or {}).get("threat", "")
    vlm_state = (vlm_pick or {}).get("state", "")
    vlm_reason = (vlm_pick or {}).get("reason", "")

    framework_top = framework_picks[0] if framework_picks else None
    agreement = (
        framework_top is not None
        and vlm_threat == framework_top["threat"]
        and vlm_state == framework_top["state"]
    )
    agreement_pill_class = "pill agreement-yes" if agreement else "pill agreement-no"
    agreement_text = "agree" if agreement else "disagree"
    if not framework_picks or not vlm_threat:
        agreement_text = "—"
        agreement_pill_class = "pill neutral"

    framework_rows = (
        [
            html.Div(
                [
                    html.Div(f"#{p['rank']}", className="suppression-rank"),
                    html.Div(f"({p['threat']}, {p['state']})", className="suppression-key"),
                    html.Div(p["rationale"], className="suppression-rationale"),
                ],
                className="suppression-row",
            )
            for p in framework_picks
        ]
        if framework_picks
        else [html.Div("No candidates.", className="empty-state")]
    )

    vlm_block = (
        html.Div(
            [
                html.Div(f"({vlm_threat}, {vlm_state})", className="suppression-key suppression-vlm-key"),
                html.Div(vlm_reason or "(no reason returned)", className="suppression-rationale"),
            ],
            className="suppression-row suppression-vlm-row",
        )
        if vlm_threat
        else html.Div("No VLM pick returned.", className="empty-state")
    )

    return html.Div(
        [
            html.Details(
                [
                    html.Summary(
                        "What is suppression and why does it matter? (click to expand)",
                        className="gt-val-explainer-summary",
                    ),
                    html.Div(
                        [
                            html.P([
                                html.B("What: "),
                                "A ",
                                html.B("suppression candidate"),
                                " is a (threat, state) pair we propose to remove from the scene in order to test the model's causal reasoning. ",
                                "Example: 'suppress (house_1, burning)' means imagine the house had not caught fire — does the model's recommendation set change accordingly?",
                            ]),
                            html.P([
                                html.B("Why: "),
                                "Suppression is the engine of Stage 1 (intervention). We pick a hazard node, ",
                                html.I("counterfactually remove it"),
                                ", re-run the model, and measure how its causal graph and recommendations shift. ",
                                "If the model is mechanistically grounded, removing the dominant hazard should cause specific downstream changes (the threat disappears from recs, the graph re-routes). ",
                                "If it's only fluent, removing the hazard barely changes anything — that's the failure CEE+ measures.",
                            ]),
                            html.P([
                                html.B("Framework pick vs VLM pick: "),
                                "Two opinions on what to suppress. The ",
                                html.B("framework's pick"),
                                " is an algorithmic ranking based on the causal graph itself (most edges out = most causally consequential). The ",
                                html.B("VLM's pick"),
                                " comes from Prompt 2 — the model nominates what it thinks is the most important hazard to suppress. ",
                                html.B("Agreement"),
                                " between them is a good signal: the model's intuition about importance matches the structural reality of its own graph. Disagreement is itself informative — it shows the model knows what to recommend acting on but not which hazard is actually structurally dominant.",
                            ], style={"marginBottom": "0"}),
                        ],
                        className="gt-val-explainer-body",
                    ),
                ],
                className="gt-val-explainer",
                style={"marginBottom": "10px"},
            ),
            html.Div(
                [
                    html.Span("Framework vs VLM agreement: ", className="suppression-agree-label"),
                    html.Span(agreement_text, className=agreement_pill_class),
                ],
                className="suppression-agreement-row",
            ),
            html.Div(
                [
                    html.Div(
                        [
                            html.Div("Framework picks (algorithmic)", className="suppression-section-title"),
                            *framework_rows,
                        ],
                        className="suppression-column",
                    ),
                    html.Div(
                        [
                            html.Div("VLM pick (Prompt 2)", className="suppression-section-title"),
                            vlm_block,
                        ],
                        className="suppression-column",
                    ),
                ],
                className="suppression-grid",
            ),
        ],
        className="suppression-panel",
    )


FAILURE_CATEGORY = {
    # grounding (high severity)
    "invalid_graph_edge": "grounding",
    "unresolved_affected_object": "grounding",
    "related_object_missing_detected_object": "grounding",
    "recommendation_threat_not_declared": "grounding",
    "threat_missing_detected_object": "grounding",
    "invalid_effect_label": "grounding",
    "latent_active_conflict": "grounding",
    # state consistency (mid)
    "hazard_state_missing_from_threats": "state",
    "normal_state_listed_as_threat": "state",
    "threat_state_mismatch": "state",
    "recommendation_state_mismatch": "state",
    "threat_state_not_hazard_bearing": "state",
    # coverage (mid)
    "quad_ids_missing_from_reason": "coverage",
    "reason_ids_missing_from_links": "coverage",
    "quad_ids_missing_from_related_object_ids": "coverage",
    # duplication (low)
    "duplicate_recommendation_quad": "duplication",
    "duplicate_remaining_risk": "duplication",
    # self-loop (high)
    "invalid_self_loop_effect": "self_loop",
}


def interpret_pre_intervention_report(report: dict[str, Any]) -> list[dict[str, str]]:
    """Rule-based interpretation of an aggregated report.

    Returns a list of {kind, headline, detail} where:
      kind ∈ {"finding", "warning", "neutral", "good"} drives styling
    """
    findings: list[dict[str, str]] = []

    n_runs = int(report.get("n_runs", 0) or 0)
    if n_runs == 0:
        return findings

    n_total = int(report.get("n_runs_total", n_runs) or n_runs)
    n_non = int(report.get("n_runs_non_disaster", 0) or 0)

    # 0. Coverage of input set
    if n_non > 0:
        findings.append({
            "kind": "neutral",
            "headline": f"{n_non} of {n_total} runs were non-disaster scenes",
            "detail": "Excluded from aggregation (no causal structure to evaluate). Aggregates below cover only disaster runs.",
        })

    md = report.get("metric_distributions", {}) or {}
    trust_dist = report.get("trust_distribution", {}) or {}

    # 1. Trust distribution
    n_low = int(trust_dist.get("low", 0))
    n_mod = int(trust_dist.get("moderate", 0))
    n_high = int(trust_dist.get("high", 0))
    pct_low = 100 * n_low / n_runs if n_runs else 0
    pct_high = 100 * n_high / n_runs if n_runs else 0
    if pct_low >= 50:
        findings.append({
            "kind": "warning",
            "headline": f"Most baselines are LOW trust ({n_low}/{n_runs}, {pct_low:.0f}%)",
            "detail": "Pre-screen runs by trust level before reading post-intervention shifts. Low-trust shifts reflect baseline incoherence as much as causal grounding.",
        })
    elif pct_high >= 50:
        findings.append({
            "kind": "good",
            "headline": f"Most baselines are HIGH trust ({n_high}/{n_runs}, {pct_high:.0f}%)",
            "detail": "Post-intervention shifts can be interpreted as strong evidence in most cases.",
        })
    else:
        findings.append({
            "kind": "neutral",
            "headline": f"Mixed trust quality (low={n_low}, mod={n_mod}, high={n_high})",
            "detail": "Stratify shifts by trust level when reporting; aggregate over all may be misleading.",
        })

    # 2. A-fidelity — the "are recs grounded in the model's beliefs" signal
    a_fid = md.get("a_fidelity", {})
    if a_fid.get("n", 0):
        med = a_fid["median"]
        n_zero = sum(
            1 for p in (report.get("per_run") or []) if p.get("a_fidelity", 0) <= 0.001
        )
        if med < 0.5:
            extra = f" {n_zero} runs hit zero (recs and Graph B share no edges)." if n_zero else ""
            findings.append({
                "kind": "warning",
                "headline": f"Recommendations are weakly grounded in the model's own causal beliefs (A-fidelity median {med:.2f})",
                "detail": f"More than half of recommendation edges aren't corroborated by the model's independent graph.{extra} This is the core declarative-vs-mechanistic asymmetry.",
            })
        elif med < 0.85:
            findings.append({
                "kind": "neutral",
                "headline": f"Partial grounding of recommendations (A-fidelity median {med:.2f})",
                "detail": "Some recommendation edges are not in Graph B. Inspect the worst runs to see whether the model fabricates or just disagrees on effect labels.",
            })
        else:
            findings.append({
                "kind": "good",
                "headline": f"Recommendations are well-grounded (A-fidelity median {med:.2f})",
                "detail": "Recommendations consistently track the model's independent causal beliefs.",
            })

    # 3. B-coverage — "does the model act on what it believes?"
    b_cov = md.get("b_coverage", {})
    if b_cov.get("n", 0):
        med = b_cov["median"]
        if med < 0.3:
            findings.append({
                "kind": "warning",
                "headline": f"Substantial under-recommendation (B-coverage median {med:.2f})",
                "detail": "The model commits to causal claims it doesn't act on. May be the priority-as-filter pathology — life-safety crowds out cascade/property recs.",
            })
        elif med < 0.7:
            findings.append({
                "kind": "neutral",
                "headline": f"Recommendations filter the model's beliefs as expected (B-coverage median {med:.2f})",
                "detail": "Some causal links are surfaced in B but not acted on in recommendations. This is normal — recs are action-filtered.",
            })
        else:
            findings.append({
                "kind": "good",
                "headline": f"Recommendations cover most of the model's reasoning (B-coverage median {med:.2f})",
                "detail": "Recommendations address most causal links the model believes exist.",
            })

    # 4. Failure category breakdown
    fhist = report.get("failure_histogram", []) or []
    cat_counts: dict[str, int] = {}
    total_failures = 0
    for f in fhist:
        cat = FAILURE_CATEGORY.get(f["type"], "other")
        cat_counts[cat] = cat_counts.get(cat, 0) + int(f["count"])
        total_failures += int(f["count"])
    if total_failures > 0:
        ground_pct = 100 * cat_counts.get("grounding", 0) / total_failures
        cov_pct = 100 * cat_counts.get("coverage", 0) / total_failures
        state_pct = 100 * cat_counts.get("state", 0) / total_failures
        dup_pct = 100 * cat_counts.get("duplication", 0) / total_failures
        if ground_pct >= 40:
            top_type = fhist[0]["type"] if fhist else ""
            findings.append({
                "kind": "warning",
                "headline": f"Grounding violations dominate alignment failures ({ground_pct:.0f}%)",
                "detail": f"The model frequently makes references it can't back up in detected_objects. Most-failed: '{top_type}'. This is the strongest Layer-2 leverage point for prompt iteration.",
            })
        elif cov_pct >= 40:
            findings.append({
                "kind": "warning",
                "headline": f"Coverage rules are most-violated ({cov_pct:.0f}%)",
                "detail": "Recommendation reasons don't cover their quad slots, or vice versa. Indicates the model is generating quad and prose somewhat independently.",
            })
        elif dup_pct >= 30:
            findings.append({
                "kind": "neutral",
                "headline": f"Duplication is the dominant failure mode ({dup_pct:.0f}%)",
                "detail": "Largely cosmetic — model pads recommendations with repeated remaining_risks. Lower priority to fix.",
            })

    # 5. Coverage A / B (orphan threats)
    cov_a = md.get("coverage_a", {})
    cov_b = md.get("coverage_b", {})
    if cov_a.get("n", 0) and cov_a["min"] < 1.0:
        findings.append({
            "kind": "neutral",
            "headline": f"Some declared threats produce no recommendations (Coverage A min {cov_a['min']:.2f})",
            "detail": "At least one run has orphan threats — the model declared a hazard but didn't reason about it. See per-run table for which.",
        })
    elif cov_a.get("median", 1.0) >= 0.99:
        findings.append({
            "kind": "good",
            "headline": "No orphan threats in Graph A",
            "detail": "Every declared threat produces at least one recommendation edge.",
        })

    # 6. Disaster level calibration
    dl = md.get("disaster_level", {})
    if dl.get("n", 0):
        if dl["max"] >= 10 and dl["median"] >= 8:
            findings.append({
                "kind": "neutral",
                "headline": f"Disaster level often saturated (median {dl['median']:.0f}, max {dl['max']:.0f})",
                "detail": "The model tends to assign high severity. Calibration concern; not a CEE+ failure but worth noting.",
            })

    return findings


def _format_distribution_md(stats: dict[str, float]) -> str:
    if not stats or stats.get("n", 0) == 0:
        return "—"
    return (
        f"median **{stats['median']:.2f}** "
        f"[{stats['p25']:.2f}–{stats['p75']:.2f}] "
        f"({stats['min']:.2f}–{stats['max']:.2f}) "
        f"n={int(stats['n'])}"
    )


def render_report_markdown(
    report: dict[str, Any],
    findings: list[dict[str, str]],
    source_folder: str,
    skipped: list[dict[str, str]] | None = None,
    external_tests: dict[str, Any] | None = None,
) -> str:
    """Markdown rendering of the same content the UI shows. Paper-ready."""
    skipped = skipped or []
    n = report.get("n_runs", 0)
    n_total = report.get("n_runs_total", n)
    n_non = report.get("n_runs_non_disaster", 0)

    lines: list[str] = []
    lines.append(f"# Pre-Intervention Report")
    lines.append("")
    lines.append(f"- Source folder: `{source_folder}`")
    lines.append(f"- Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"- Disaster runs aggregated: **{n}** of {n_total}")
    if n_non:
        lines.append(f"- Non-disaster excluded: {n_non}")
        non_ids = report.get("non_disaster_run_ids", [])
        if non_ids:
            lines.append(f"  - {', '.join(f'`{i}`' for i in non_ids)}")
    if skipped:
        lines.append(f"- Parse-skipped: {len(skipped)}")
        for s in skipped[:5]:
            lines.append(f"  - `{s.get('run_id')}`: {s.get('reason')}")
    lines.append("")

    if findings:
        lines.append("## Interpretation")
        lines.append("")
        for f in findings:
            kind = f.get("kind", "neutral").upper()
            lines.append(f"**[{kind}]** {f.get('headline', '')}")
            lines.append(f"")
            lines.append(f"> {f.get('detail', '')}")
            lines.append("")

    trust_dist = report.get("trust_distribution") or {}
    if trust_dist:
        lines.append("## Trust level distribution")
        lines.append("")
        total = sum(trust_dist.values()) or 1
        for level in ["high", "moderate", "low", "not_applicable", "unknown"]:
            if level in trust_dist:
                c = trust_dist[level]
                pct = 100 * c / total
                lines.append(f"- {level.title()}: {c} ({pct:.0f}%)")
        lines.append("")

    md = report.get("metric_distributions") or {}
    if md:
        lines.append("## Metric distributions")
        lines.append("")
        lines.append("| Metric | Median [IQR] (range) | n |")
        lines.append("|---|---|---|")
        labels = [
            ("a_fidelity", "A-fidelity"),
            ("b_coverage", "B-coverage"),
            ("topological_consistency", "Topological"),
            ("node_consistency", "Node"),
            ("flag_consistency", "Hazardous flag"),
            ("coverage_a", "Coverage A"),
            ("coverage_b", "Coverage B"),
            ("internal_alignment", "Internal alignment"),
            ("trust_score", "Trust score"),
            ("disaster_level", "Disaster level"),
        ]
        for key, label in labels:
            s = md.get(key, {})
            if not s or s.get("n", 0) == 0:
                continue
            lines.append(
                f"| {label} | {s['median']:.2f} [{s['p25']:.2f}–{s['p75']:.2f}] ({s['min']:.2f}–{s['max']:.2f}) | {int(s['n'])} |"
            )
        lines.append("")

    fhist = report.get("failure_histogram") or []
    if fhist:
        lines.append("## Top alignment failure types")
        lines.append("")
        for f in fhist[:20]:
            lines.append(f"- `{f['type']}`: **{f['count']}**")
        lines.append("")

    scene = report.get("scene_level") or {}
    if scene:
        lines.append("## Scene-level stats per run")
        lines.append("")
        lines.append("| Quantity | Mean | Median | Range |")
        lines.append("|---|---|---|---|")
        scene_labels = [
            ("detected_objects", "Detected objects"),
            ("threats_per_scene", "Threats"),
            ("recs_per_scene", "Recommendations"),
            ("edges_in_a", "Edges in A"),
            ("edges_in_b", "Edges in B"),
        ]
        for key, label in scene_labels:
            s = scene.get(key, {})
            if not s or s.get("n", 0) == 0:
                continue
            lines.append(f"| {label} | {s['mean']:.1f} | {s['median']:.0f} | {s['min']:.0f}–{s['max']:.0f} |")
        lines.append("")

    by_cat = report.get("by_category") or []
    if len(by_cat) > 1 or (len(by_cat) == 1 and by_cat[0]["category"] != "(uncategorized)"):
        lines.append("## By disaster category (folder-derived)")
        lines.append("")
        lines.append("| Category | n | Trust H/M/L | A-fid med | B-cov med | Internal med | Trust med |")
        lines.append("|---|---|---|---|---|---|---|")
        for c in by_cat:
            t = c["trust"]
            lines.append(
                f"| {c['category']} | {c['n']} | "
                f"{t['high']}/{t['moderate']}/{t['low']} | "
                f"{c['a_fidelity_median']:.2f} | {c['b_coverage_median']:.2f} | "
                f"{c['internal_median']:.2f} | {c['trust_score_median']:.2f} |"
            )
        lines.append("")

    outliers = report.get("outliers") or []
    if outliers:
        lines.append("## Outliers worth inspecting")
        lines.append("")
        for o in outliers:
            lines.append(f"- **{o['label']}**: `{o['run_id']}` ({o['value']})")
        lines.append("")

    per_run = report.get("per_run") or []
    if per_run:
        lines.append("## Per-run summary")
        lines.append("")
        lines.append("| Run | Trust | Score | A-fid | B-cov | Internal | Threats | Recs | Failures |")
        lines.append("|---|---|---|---|---|---|---|---|---|")
        for p in per_run:
            lines.append(
                f"| `{p['run_id']}` | {p['trust_level']} | {p['trust_score']:.2f} | "
                f"{p['a_fidelity']:.2f} | {p['b_coverage']:.2f} | {p['internal']:.2f} | "
                f"{p['n_threats']} | {p['n_recs']} | {p['n_failures']} |"
            )
        lines.append("")

    # External-validation tests (surface-only; not part of trust math)
    if external_tests:
        t1 = external_tests.get("test1_ground_truth") or {}
        t2 = external_tests.get("test2_prompt_sensitivity") or {}

        lines.append("## External Validation (surface-only — not part of trust score)")
        lines.append("")

        # Test 1
        lines.append("### Test 1 — Verified Ground Truth Comparison")
        lines.append("")
        if t1.get("error"):
            lines.append(f"- Error: {t1['error']}")
        elif not t1.get("n_pairs"):
            lines.append(f"- No verified-to-batch pairs found "
                         f"(verified={t1.get('n_verified', 0)}, unmatched={t1.get('n_unmatched', 0)}).")
        else:
            agg = t1.get("aggregate", {}) or {}
            n_pairs = t1.get("n_pairs", 0)
            lines.append(f"- Verified pairs: **{n_pairs}** "
                         f"(unmatched: {t1.get('n_unmatched', 0)})")
            verdict_kind = (t1.get("verdict_kind") or "neutral").upper()
            verdict_text = t1.get("verdict_text") or ""
            if verdict_text:
                lines.append(f"- **[{verdict_kind}]** {verdict_text}")
            lines.append("")
            lines.append("| Metric | Strict (med) | Soft (med) | Topological (med) |")
            lines.append("|---|---|---|---|")
            def _m(key):
                d = agg.get(key) or {}
                return f"{d.get('median', 0.0):.2f}" if d else "—"
            for label, stem in [
                ("A-correctness vs GT", "a_correctness"),
                ("A-precision vs GT",   "a_precision"),
                ("B-correctness vs GT", "b_correctness"),
                ("B-precision vs GT",   "b_precision"),
            ]:
                lines.append(f"| {label} | {_m(stem)} | {_m(stem+'_soft')} | {_m(stem+'_topo')} |")
            lines.append("")

        # Test 2
        lines.append("### Test 2 — Prompt-Sensitivity Verdict (latest saved run)")
        lines.append("")
        if t2.get("error"):
            lines.append(f"- Error: {t2['error']}")
        elif not t2 or t2.get("available") is False:
            lines.append(f"- {t2.get('reason', 'No Test 2 results saved yet.')}")
        else:
            gen = t2.get("generated_at", "?")
            out_dir_t2 = t2.get("out_dir", "?")
            lines.append(f"- Generated: {gen}")
            lines.append(f"- Output: `{out_dir_t2}`")
            summary = t2.get("summary") or {}
            kind = (summary.get("verdict_kind") or "neutral").upper()
            text = summary.get("verdict_text") or ""
            if text:
                lines.append(f"- **[{kind}]** {text}")
            disp = (summary.get("dispersion_summary") or {}).get("a_fidelity") or {}
            if disp:
                lines.append(f"- Per-image A-fidelity spread (across variants): "
                             f"median Δ = {disp.get('median', 0.0):.2f}, "
                             f"p75 Δ = {disp.get('p75', 0.0):.2f}, "
                             f"max Δ = {disp.get('max', 0.0):.2f}")
            lines.append(f"- N images: {summary.get('n_images', 0)} × {len(summary.get('variants') or [])} variants")
            lines.append("")

    return "\n".join(lines)


# ────────────────────────────────────────────────────────────
# Ground Truth: load candidates, verify, save references
# ────────────────────────────────────────────────────────────

GROUND_TRUTH_ROOT = Path(__file__).resolve().parent / "exports" / "ground_truth"
GT_CANDIDATES_DIR = GROUND_TRUTH_ROOT / "candidates"
GT_VERIFIED_DIR = GROUND_TRUTH_ROOT / "verified"


def list_gt_candidates(folder: str | Path) -> list[dict[str, Any]]:
    """Scan a folder for *.gt.json candidate files paired with their images.

    Each entry: {path, image_path, image_filename, status, source, n_nodes, n_edges}.
    status is "verified" if a same-named file exists under exports/ground_truth/verified/.
    """
    p = Path(str(folder)).expanduser().resolve()
    if not p.exists() or not p.is_dir():
        return []
    out: list[dict[str, Any]] = []
    for json_path in sorted(p.glob("*.gt.json")):
        try:
            data = json.loads(json_path.read_text())
        except Exception:
            continue
        image_filename = str(data.get("image_filename", json_path.stem.replace(".gt", "")))
        image_path = p / image_filename if (p / image_filename).exists() else None
        verified_path = GT_VERIFIED_DIR / json_path.name
        out.append({
            "path": str(json_path),
            "image_path": str(image_path) if image_path else "",
            "image_filename": image_filename,
            "status": "verified" if verified_path.exists() else "unverified",
            "source": str(data.get("source", "")),
            "caption": str(data.get("caption", "")),
            "n_nodes": len(data.get("nodes") or []),
            "n_edges": len(data.get("edges") or []),
        })
    return out


def load_gt_candidate(path: str | Path) -> dict[str, Any]:
    """Load a candidate JSON. If a verified copy exists for the same filename,
    prefer it so the editor shows the human-approved version on reopen.
    The original candidate file is preserved unchanged on disk for provenance.
    """
    try:
        candidate_path = Path(str(path))
        verified_path = GT_VERIFIED_DIR / candidate_path.name
        chosen = verified_path if verified_path.exists() else candidate_path
        return json.loads(chosen.read_text())
    except Exception:
        return {}


def _filter_empty(cand: dict[str, Any]) -> dict[str, Any]:
    """Drop nodes with no id and edges with empty source/target/effect."""
    out = dict(cand)
    out["nodes"] = [
        n for n in (cand.get("nodes") or [])
        if str(n.get("id", "")).strip()
    ]
    out["edges"] = [
        e for e in (cand.get("edges") or [])
        if str(e.get("source", "")).strip()
        and str(e.get("target", "")).strip()
        and str(e.get("effect", "")).strip()
    ]
    return out


def save_verified_gt(candidate: dict[str, Any], original_path: str | Path) -> Path:
    """Save (possibly edited) candidate to the verified folder.
    Empty/partial nodes and edges are filtered out before writing.
    """
    GT_VERIFIED_DIR.mkdir(parents=True, exist_ok=True)
    name = Path(str(original_path)).name
    out_path = GT_VERIFIED_DIR / name
    out_path.write_text(json.dumps(_filter_empty(candidate), indent=2))
    return out_path


def unverify_gt(original_path: str | Path) -> bool:
    """Remove a previously-verified file (revoke)."""
    name = Path(str(original_path)).name
    verified_path = GT_VERIFIED_DIR / name
    if verified_path.exists():
        verified_path.unlink()
        return True
    return False


def derive_gt_validation(
    image_filename: str,
    graph_a: dict[str, Any],
    graph_b: dict[str, Any],
) -> dict[str, Any]:
    """Surface-only external validation. If a verified GT file exists for the
    image, compute strict/soft/topological scores; otherwise return a
    "not available" placeholder. Does NOT affect trust score.
    """
    if not image_filename:
        return {"available": False, "reason": "no image filename"}

    gt_path = GT_VERIFIED_DIR / f"{image_filename}.gt.json"
    if not gt_path.exists():
        return {"available": False, "reason": f"no verified GT at {gt_path.name}"}

    try:
        gt = json.loads(gt_path.read_text())
    except Exception as exc:
        return {"available": False, "reason": f"GT parse failed: {exc}"}

    gt_graph = {"nodes": gt.get("nodes") or [], "edges": gt.get("edges") or []}

    cmp_a = compare_graphs(graph_a or {}, gt_graph)
    cmp_a_soft = compare_graphs_soft(graph_a or {}, gt_graph)
    cmp_a_topo = compare_graphs_topological(graph_a or {}, gt_graph)
    cmp_b = compare_graphs(graph_b or {}, gt_graph)
    cmp_b_soft = compare_graphs_soft(graph_b or {}, gt_graph)
    cmp_b_topo = compare_graphs_topological(graph_b or {}, gt_graph)

    return {
        "available": True,
        "gt_path": str(gt_path),
        "n_edges_gt": len(gt_graph["edges"]),
        "n_edges_a": len((graph_a or {}).get("edges") or []),
        "n_edges_b": len((graph_b or {}).get("edges") or []),
        # A vs GT
        "a_precision":      float(cmp_a.get("a_fidelity", 0.0)),
        "a_correctness":    float(cmp_a.get("b_coverage", 0.0)),
        "a_precision_soft": float(cmp_a_soft.get("a_fidelity_soft", 0.0)),
        "a_correctness_soft": float(cmp_a_soft.get("b_coverage_soft", 0.0)),
        "a_precision_topo": float(cmp_a_topo.get("a_fidelity_topo", 0.0)),
        "a_correctness_topo": float(cmp_a_topo.get("b_coverage_topo", 0.0)),
        # B vs GT
        "b_precision":      float(cmp_b.get("a_fidelity", 0.0)),
        "b_correctness":    float(cmp_b.get("b_coverage", 0.0)),
        "b_precision_soft": float(cmp_b_soft.get("a_fidelity_soft", 0.0)),
        "b_correctness_soft": float(cmp_b_soft.get("b_coverage_soft", 0.0)),
        "b_precision_topo": float(cmp_b_topo.get("a_fidelity_topo", 0.0)),
        "b_correctness_topo": float(cmp_b_topo.get("b_coverage_topo", 0.0)),
    }


def gt_candidate_to_graph_dict(candidate: dict[str, Any]) -> dict[str, Any]:
    """Convert a candidate GT JSON into the shape make_causal_graph_viewer expects."""
    return {
        "nodes": candidate.get("nodes") or [],
        "edges": candidate.get("edges") or [],
    }


def make_gt_node_row(node: dict[str, Any], i: int) -> html.Div:
    """Render one editable row for a single node in the candidate."""
    return html.Div(
        [
            dcc.Input(
                id={"type": "gt-node-field", "i": i, "field": "id"},
                type="text",
                value=str(node.get("id", "")),
                className="gt-cell-input gt-cell-id",
                placeholder="object_id (e.g. house_1)",
            ),
            dcc.Input(
                id={"type": "gt-node-field", "i": i, "field": "label"},
                type="text",
                value=str(node.get("label", "")),
                className="gt-cell-input gt-cell-label",
                placeholder="label (e.g. house)",
            ),
            dcc.Dropdown(
                id={"type": "gt-node-field", "i": i, "field": "state"},
                options=_gt_state_options(),
                value=str(node.get("state", "")) or None,
                className="gt-cell-dropdown",
                clearable=False,
                searchable=True,
            ),
            dcc.Checklist(
                id={"type": "gt-node-field", "i": i, "field": "hazardous"},
                options=[{"label": "", "value": "y"}],
                value=["y"] if bool(node.get("hazardous")) else [],
                className="gt-cell-checkbox",
            ),
            dcc.Checklist(
                id={"type": "gt-node-field", "i": i, "field": "inferred"},
                options=[{"label": "", "value": "y"}],
                value=["y"] if bool(node.get("inferred")) else [],
                className="gt-cell-checkbox",
            ),
            html.Button(
                "×",
                id={"type": "gt-delete-node", "i": i},
                className="gt-row-delete",
                n_clicks=0,
                title="Delete this node",
            ),
        ],
        className="gt-form-row gt-node-row",
    )


def make_gt_edge_row(edge: dict[str, Any], i: int, node_ids: list[str]) -> html.Div:
    """Render one editable row for a single edge in the candidate.

    Source/target are dropdowns of existing node ids. via_state is a
    hazard-state dropdown. effect is the 8-label vocabulary.
    """
    id_options = [{"label": nid, "value": nid} for nid in node_ids if nid]
    return html.Div(
        [
            dcc.Dropdown(
                id={"type": "gt-edge-field", "i": i, "field": "source"},
                options=id_options,
                value=str(edge.get("source", "")) or None,
                className="gt-cell-dropdown",
                clearable=False,
                searchable=True,
            ),
            dcc.Dropdown(
                id={"type": "gt-edge-field", "i": i, "field": "target"},
                options=id_options,
                value=str(edge.get("target", "")) or None,
                className="gt-cell-dropdown",
                clearable=False,
                searchable=True,
            ),
            dcc.Dropdown(
                id={"type": "gt-edge-field", "i": i, "field": "effect"},
                options=_gt_effect_options(),
                value=str(edge.get("effect", "")) or None,
                className="gt-cell-dropdown",
                clearable=False,
                searchable=True,
            ),
            dcc.Dropdown(
                id={"type": "gt-edge-field", "i": i, "field": "via_state"},
                options=[{"label": s, "value": s} for s in GT_HAZARD_STATES + [UNDETERMINED]],
                value=str(edge.get("via_state", "")) or None,
                className="gt-cell-dropdown",
                clearable=False,
                searchable=True,
            ),
            html.Button(
                "×",
                id={"type": "gt-delete-edge", "i": i},
                className="gt-row-delete",
                n_clicks=0,
                title="Delete this edge",
            ),
        ],
        className="gt-form-row gt-edge-row",
    )


def make_gt_editor(candidate: dict[str, Any]) -> html.Div:
    """Structured editor for the candidate: nodes table + edges table + caption + notes."""
    nodes = candidate.get("nodes") or []
    edges = candidate.get("edges") or []
    node_ids = [str(n.get("id", "")) for n in nodes if n.get("id")]

    node_header = html.Div(
        [
            html.Div("id", className="gt-cell-header gt-cell-id"),
            html.Div("label", className="gt-cell-header gt-cell-label"),
            html.Div("state", className="gt-cell-header"),
            html.Div("hazardous", className="gt-cell-header gt-cell-flag"),
            html.Div("inferred", className="gt-cell-header gt-cell-flag"),
            html.Div("", className="gt-cell-header gt-cell-delete"),
        ],
        className="gt-form-row gt-node-row gt-header-row",
    )

    edge_header = html.Div(
        [
            html.Div("source", className="gt-cell-header"),
            html.Div("target", className="gt-cell-header"),
            html.Div("effect", className="gt-cell-header"),
            html.Div("via_state", className="gt-cell-header"),
            html.Div("", className="gt-cell-header gt-cell-delete"),
        ],
        className="gt-form-row gt-edge-row gt-header-row",
    )

    node_rows = [make_gt_node_row(n, i) for i, n in enumerate(nodes)] or [
        html.Div("(no nodes — click Add Node)", className="empty-state")
    ]
    edge_rows = [make_gt_edge_row(e, i, node_ids) for i, e in enumerate(edges)] or [
        html.Div("(no edges — click Add Edge)", className="empty-state")
    ]

    return html.Div(
        [
            html.Label("Caption", className="field-label small-field-label"),
            dcc.Input(
                id="gt-edit-caption",
                type="text",
                value=str(candidate.get("caption", "")),
                className="report-folder-input",
            ),
            html.Label("Annotator notes", className="field-label small-field-label"),
            dcc.Textarea(
                id="gt-edit-notes",
                value=str(candidate.get("annotator_notes", "")),
                className="text-area",
                style={"minHeight": "60px"},
            ),
            html.Div(
                [
                    html.Div("Nodes", className="gt-section-title"),
                    html.Button("+ Add Node", id="gt-add-node-button", className="folder-nav-button", n_clicks=0),
                ],
                className="gt-section-header",
            ),
            node_header,
            *node_rows,
            html.Div(
                [
                    html.Div("Edges", className="gt-section-title"),
                    html.Button("+ Add Edge", id="gt-add-edge-button", className="folder-nav-button", n_clicks=0),
                ],
                className="gt-section-header",
            ),
            edge_header,
            *edge_rows,
        ],
        className="gt-editor",
    )


def save_report(
    report: dict[str, Any],
    findings: list[dict[str, str]],
    source_folder: str,
    skipped: list[dict[str, str]] | None = None,
    out_root: Path | None = None,
    external_tests: dict[str, Any] | None = None,
) -> Path:
    """Persist a report as both JSON and Markdown into exports/reports/<ts>/.

    Returns the directory path containing the saved files.
    """
    out_root = out_root or (EXPORT_ROOT / "reports")
    timestamp = datetime.now().strftime("report_%Y%m%dT%H%M%S")
    out_dir = out_root / timestamp
    out_dir.mkdir(parents=True, exist_ok=True)

    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source_folder": str(source_folder),
        "skipped": skipped or [],
        "findings": findings,
        "report": report,
        "external_tests": external_tests or {},
    }
    (out_dir / "report.json").write_text(json.dumps(payload, indent=2))
    (out_dir / "report.md").write_text(
        render_report_markdown(report, findings, source_folder, skipped, external_tests=external_tests)
    )
    return out_dir


# ────────────────────────────────────────────────────────────
# Batch run state — shared between worker thread and Dash callbacks
# ────────────────────────────────────────────────────────────
_BATCH_LOCK = threading.Lock()
_BATCH_STATE: dict[str, Any] = {
    "active": False,
    "done": False,
    "total": 0,
    "completed": 0,
    "current": "",
    "errors": [],
    "out_dir": None,
    "report_path": None,
    "started_at": None,
}

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
MIME_BY_EXT = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
}


def _reset_batch_state() -> None:
    with _BATCH_LOCK:
        _BATCH_STATE.update({
            "active": False,
            "done": False,
            "total": 0,
            "completed": 0,
            "current": "",
            "errors": [],
            "out_dir": None,
            "report_path": None,
            "started_at": None,
        })


def _read_batch_state() -> dict[str, Any]:
    with _BATCH_LOCK:
        return {
            "active": _BATCH_STATE["active"],
            "done": _BATCH_STATE["done"],
            "total": _BATCH_STATE["total"],
            "completed": _BATCH_STATE["completed"],
            "current": _BATCH_STATE["current"],
            "errors": list(_BATCH_STATE["errors"]),
            "out_dir": _BATCH_STATE["out_dir"],
            "report_path": _BATCH_STATE["report_path"],
            "started_at": _BATCH_STATE["started_at"],
        }


def _process_one_image(
    img_path: Path,
    caption: str,
    allow_inferred: bool,
    out_dir: Path,
    category: str = "",
) -> tuple[bool, str | None]:
    """Run Prompt 1 + Prompt 2 on a single image, save the run folder. Returns (ok, error_msg).

    `category` is a folder-based disaster tag (e.g. "fire", "flood") inferred
    from the image's parent directory relative to the batch root.
    """
    try:
        img_bytes = img_path.read_bytes()
        mime = MIME_BY_EXT.get(img_path.suffix.lower(), "image/jpeg")
        data_url = image_bytes_to_data_url(img_bytes, mime)

        # Prompt 1
        result = query_qwen(DEFAULT_PROMPT, caption or "", data_url, allow_inferred=allow_inferred)

        # Prompt 2 (best-effort — failure here doesn't kill the run)
        try:
            graph_b = query_qwen_graph_b(
                result["detected_objects"], result["threats"], caption or "", data_url
            )
            result["graph_b"] = graph_b
            result["graph_consistency"] = compare_graphs(result["causal_graph"], graph_b)
            # Re-derive trust now that Graph B is real (was computed against an empty
            # placeholder during normalize_result).
            result["pre_intervention_trust"] = assess_pre_intervention_trust(
                result.get("pre_internal_alignment", {}),
                result["graph_consistency"],
                result["causal_graph"],
                graph_b,
            )
        except Exception:
            pass  # graph_b stays at placeholder

        # Disambiguated stem so images with the same basename in different
        # subfolders (e.g. fire/palisade/1.jpg vs flood/helene/1.jpg) don't collide.
        ns_name = namespaced_image_name(img_path.name, category)
        ns_stem = Path(ns_name).stem

        run_id = f"run_{datetime.now().strftime('%Y%m%dT%H%M%S')}_{ns_stem}"
        run_dir = out_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=True)

        # Save image alongside under the namespaced name
        (run_dir / ns_name).write_bytes(img_bytes)

        # Save structured response
        result["run_id"] = run_id
        result["image_filename"] = ns_name
        if category:
            result["disaster_category"] = category  # folder-based tag, separate from model's disaster_type
        payload = {
            "exported_at": datetime.now().isoformat(timespec="seconds"),
            "run_id": run_id,
            "model": os.getenv("QWEN_MODEL_NAME", "qwen2.5vl:7b"),
            "image_filename": ns_name,
            "disaster_category": category,
            "prompt": apply_inferred_block(DEFAULT_PROMPT, allow_inferred),
            "caption": caption,
            "structured_response": result,
        }
        (run_dir / "structured_response.json").write_text(json.dumps(payload, indent=2))
        (run_dir / "caption.txt").write_text(caption or "")
        (run_dir / "prompt.txt").write_text(apply_inferred_block(DEFAULT_PROMPT, allow_inferred))
        return True, None
    except Exception as exc:
        return False, str(exc)


def _read_sidecar_caption(img_path: Path) -> str:
    """Look for image.txt sidecar file (same stem)."""
    sidecar = img_path.with_suffix(".txt")
    if sidecar.exists():
        try:
            return sidecar.read_text().strip()
        except Exception:
            return ""
    return ""


def summarize_folder(path: str | Path) -> dict[str, Any]:
    """Inspect a folder and return navigation info for the browser UI.

    Returns:
      {
        "path": absolute resolved path,
        "exists": bool,
        "parent": parent path or None if at root,
        "subfolders": [{"name", "path", "n_images_direct", "n_images_recursive"}],
        "n_images_direct":     count of image files directly in path,
        "n_images_recursive":  count of image files in path and all subfolders,
      }
    """
    p = Path(str(path)).expanduser().resolve()
    if not p.exists() or not p.is_dir():
        return {
            "path": str(p),
            "exists": False,
            "parent": None,
            "subfolders": [],
            "n_images_direct": 0,
            "n_images_recursive": 0,
            "error": f"not a directory: {p}",
        }

    def _count_images_recursive(root_dir: Path) -> int:
        # Follow symlinks so aggregation folders show correct counts.
        return sum(
            1
            for _r, _dirs, files in os.walk(str(root_dir), followlinks=True)
            for fname in files
            if Path(fname).suffix.lower() in IMAGE_EXTENSIONS
        )

    direct_imgs = sum(
        1 for f in p.iterdir()
        if f.is_file() and f.suffix.lower() in IMAGE_EXTENSIONS
    )
    recursive_imgs = _count_images_recursive(p)

    subfolders = []
    for sub in sorted(p.iterdir(), key=lambda x: x.name.lower()):
        if not sub.is_dir() or sub.name.startswith("."):
            continue
        n_direct = sum(
            1 for f in sub.iterdir()
            if f.is_file() and f.suffix.lower() in IMAGE_EXTENSIONS
        )
        n_recursive = _count_images_recursive(sub)
        subfolders.append({
            "name": sub.name,
            "path": str(sub),
            "n_images_direct": n_direct,
            "n_images_recursive": n_recursive,
        })

    parent = str(p.parent) if p.parent != p else None
    return {
        "path": str(p),
        "exists": True,
        "parent": parent,
        "subfolders": subfolders,
        "n_images_direct": direct_imgs,
        "n_images_recursive": recursive_imgs,
    }


def namespaced_image_name(basename: str, category: str) -> str:
    """Return a category-disambiguated image name so files with the same
    basename across different subfolders don't collide.

    The convention is `<flat_category>__<basename>` where flat_category is
    the disaster_category with '/' replaced by '_'. Images without a category
    (e.g. flat folders) keep their plain basename.

    Examples:
        ("1.jpg", "fire/palisade")  -> "fire_palisade__1.jpg"
        ("1.jpg", "flood/helene")   -> "flood_helene__1.jpg"
        ("1.jpg", "")               -> "1.jpg"
    """
    if not category:
        return basename
    flat = category.replace("/", "_")
    return f"{flat}__{basename}"


def _infer_disaster_category(img_path: Path, root: Path) -> str:
    """Infer a folder-based category tag from the image's path relative to root.

    Examples:
      root/fire/house.jpg          -> "fire"
      root/fire/structural/h.jpg   -> "fire/structural"
      root/h.jpg                   -> ""   (image directly in root, no category)
    """
    try:
        rel = img_path.relative_to(root)
    except ValueError:
        return ""
    parts = rel.parent.parts
    if not parts or parts == ("",):
        return ""
    return "/".join(parts)


# ────────────────────────────────────────────────────────────
# Test 2: Prompt Sensitivity — state + worker + aggregator
# ────────────────────────────────────────────────────────────

_PSENS_LOCK = threading.Lock()
_PSENS_STATE: dict[str, Any] = {
    "active": False,
    "done": False,
    "total": 0,
    "completed": 0,
    "current": "",
    "errors": [],
    "out_dir": None,
    "results": [],  # per-image rows
    "started_at": None,
}


def _reset_psens_state() -> None:
    with _PSENS_LOCK:
        _PSENS_STATE.update({
            "active": False, "done": False, "total": 0, "completed": 0,
            "current": "", "errors": [], "out_dir": None, "results": [],
            "started_at": None,
        })


def _read_psens_state() -> dict[str, Any]:
    with _PSENS_LOCK:
        return {k: (list(v) if isinstance(v, list) else v) for k, v in _PSENS_STATE.items()}


def _run_psens_worker(
    batch_folder: Path,
    sample_size: int,
    variant_ids: list[str],
    out_dir: Path,
) -> None:
    """Worker thread for Test 2. For each sampled run:
       - Load existing Graph A (from saved structured_response.json).
       - For each requested Prompt 2 variant, re-run Prompt 2 against the same
         image + detected_objects + threats. Compute consistency vs Graph A.
       - Record per-image per-variant results.
    """
    runs, _skipped = load_run_jsons(str(batch_folder))
    # Filter to disaster runs that actually have an image file we can re-send.
    eligible = []
    for r in runs:
        if str(r.get("disaster_scenario", "")).strip().lower() != "yes":
            continue
        # Locate the image alongside the run's JSON
        run_id = r.get("run_id", "")
        image_filename = r.get("image_filename", "")
        if not run_id or not image_filename:
            continue
        # Support both the old layout (batch_folder/run_id/image) and the new
        # batch-centric layout (batch_folder/runs/run_id/image).
        img_path = batch_folder / run_id / image_filename
        if not img_path.exists():
            img_path = batch_folder / "runs" / run_id / image_filename
        if not img_path.exists():
            continue
        eligible.append((r, img_path))

    # Sample without exceeding eligible set
    import random
    random.seed(42)  # deterministic for reproducibility
    sample = random.sample(eligible, min(sample_size, len(eligible)))

    with _PSENS_LOCK:
        _PSENS_STATE.update({
            "active": True, "done": False,
            "total": len(sample), "completed": 0,
            "current": "", "errors": [],
            "out_dir": str(out_dir),
            "results": [],
            "started_at": datetime.now().isoformat(timespec="seconds"),
        })

    for run_data, img_path in sample:
        run_id = run_data.get("run_id", "?")
        with _PSENS_LOCK:
            _PSENS_STATE["current"] = run_id

        try:
            img_bytes = img_path.read_bytes()
            mime = MIME_BY_EXT.get(img_path.suffix.lower(), "image/jpeg")
            data_url = image_bytes_to_data_url(img_bytes, mime)

            graph_a = run_data.get("causal_graph", {})
            detected = run_data.get("detected_objects", [])
            threats = run_data.get("threats", [])
            # Captions sometimes aren't stored on the structured_response itself.
            # Try reading from caption.txt alongside the run folder.
            caption = ""
            try:
                cap_file = batch_folder / run_id / "caption.txt"
                if cap_file.exists():
                    caption = cap_file.read_text().strip()
            except Exception:
                caption = ""

            row: dict[str, Any] = {
                "run_id": run_id,
                "image_filename": run_data.get("image_filename", ""),
                "n_edges_a": len(graph_a.get("edges", []) or []),
                "variants": {},
            }

            for vid in variant_ids:
                try:
                    if vid == "v0_current":
                        # Reuse the already-stored Graph B from baseline run
                        graph_b = run_data.get("graph_b", {})
                    else:
                        graph_b = query_qwen_graph_b_variant(
                            detected, threats, caption, data_url, vid, allow_inferred=False
                        )
                    cmp = compare_graphs(graph_a, graph_b)
                    row["variants"][vid] = {
                        "a_fidelity": float(cmp.get("a_fidelity", 0.0) or 0.0),
                        "b_coverage": float(cmp.get("b_coverage", 0.0) or 0.0),
                        "topological_consistency": float(cmp.get("topological_consistency", 0.0) or 0.0),
                        "n_edges_b": len(graph_b.get("edges", []) or []),
                    }
                except Exception as exc:
                    row["variants"][vid] = {"error": str(exc)}
                    with _PSENS_LOCK:
                        _PSENS_STATE["errors"].append({"run_id": run_id, "variant": vid, "error": str(exc)})

            # Save per-image row
            row_path = out_dir / f"{run_id}.json"
            row_path.write_text(json.dumps(row, indent=2))

            with _PSENS_LOCK:
                _PSENS_STATE["results"].append(row)

        except Exception as exc:
            with _PSENS_LOCK:
                _PSENS_STATE["errors"].append({"run_id": run_id, "variant": "(setup)", "error": str(exc)})

        with _PSENS_LOCK:
            _PSENS_STATE["completed"] += 1

    # Final aggregation written to disk
    try:
        results = _read_psens_state()["results"]
        summary = aggregate_prompt_sensitivity(results, variant_ids)
        (out_dir / "summary.json").write_text(json.dumps(summary, indent=2))
        # Also write to a stable "latest" path so batch runs / reports can read it.
        latest = {
            "generated_at": datetime.now().isoformat(),
            "out_dir": str(out_dir),
            "variant_ids": variant_ids,
            "summary": summary,
        }
        (EXPORT_ROOT / "tests" / "latest_prompt_sensitivity.json").write_text(json.dumps(latest, indent=2))
    except Exception as exc:
        with _PSENS_LOCK:
            _PSENS_STATE["errors"].append({"run_id": "(summary)", "variant": "", "error": str(exc)})

    with _PSENS_LOCK:
        _PSENS_STATE["active"] = False
        _PSENS_STATE["done"] = True
        _PSENS_STATE["current"] = ""


def compute_ground_truth_report(verified_folder: str, batch_folder: str) -> dict[str, Any]:
    """Compare verified GT graphs against the Graph A and Graph B from the
    matching batch runs.

    For each verified GT file in `verified_folder`:
      - Find a batch run in `batch_folder` whose image_filename matches.
      - Compare GT edges against both Graph A and Graph B by exact tuple match.
      - Compute precision (matched / |source_graph|) and recall (matched / |GT|).

    Returns aggregate stats + per-pair detail.
    """
    verified_path = Path(str(verified_folder)).expanduser().resolve()
    if not verified_path.is_dir():
        return {"error": f"verified folder not found: {verified_path}", "n_pairs": 0}

    runs, _skipped = load_run_jsons(str(batch_folder))
    # Index runs by image_filename for fast match
    runs_by_image: dict[str, dict[str, Any]] = {}
    for r in runs:
        ifn = str(r.get("image_filename", "")).strip()
        if ifn:
            runs_by_image[ifn] = r

    # Load each verified GT
    gt_files = sorted(verified_path.glob("*.gt.json"))
    pairs: list[dict[str, Any]] = []
    unmatched: list[str] = []
    for gt_path in gt_files:
        try:
            gt = json.loads(gt_path.read_text())
        except Exception:
            continue
        image_filename = str(gt.get("image_filename", "")).strip()
        if not image_filename:
            continue
        run = runs_by_image.get(image_filename)
        if run is None:
            unmatched.append(image_filename)
            continue

        graph_a = run.get("causal_graph", {}) or {}
        graph_b = run.get("graph_b", {}) or {}
        gt_graph = {"nodes": gt.get("nodes") or [], "edges": gt.get("edges") or []}

        cmp_a = compare_graphs(graph_a, gt_graph)
        cmp_b = compare_graphs(graph_b, gt_graph)
        cmp_a_soft = compare_graphs_soft(graph_a, gt_graph)
        cmp_b_soft = compare_graphs_soft(graph_b, gt_graph)
        cmp_a_topo = compare_graphs_topological(graph_a, gt_graph)
        cmp_b_topo = compare_graphs_topological(graph_b, gt_graph)

        n_gt = len(gt_graph["edges"])
        n_a = len(graph_a.get("edges") or [])
        n_b = len(graph_b.get("edges") or [])

        # Strict (exact 4-tuple match) — these are the original metrics
        a_precision = cmp_a.get("a_fidelity", 0.0)
        a_correctness = cmp_a.get("b_coverage", 0.0)
        b_precision = cmp_b.get("a_fidelity", 0.0)
        b_correctness = cmp_b.get("b_coverage", 0.0)

        # Soft (label hierarchy + state synonyms + effect close-pairs)
        a_precision_soft = cmp_a_soft.get("a_fidelity_soft", 0.0)
        a_correctness_soft = cmp_a_soft.get("b_coverage_soft", 0.0)
        b_precision_soft = cmp_b_soft.get("a_fidelity_soft", 0.0)
        b_correctness_soft = cmp_b_soft.get("b_coverage_soft", 0.0)

        # Topological (label hierarchy + effect close-pairs; state IGNORED)
        a_precision_topo = cmp_a_topo.get("a_fidelity_topo", 0.0)
        a_correctness_topo = cmp_a_topo.get("b_coverage_topo", 0.0)
        b_precision_topo = cmp_b_topo.get("a_fidelity_topo", 0.0)
        b_correctness_topo = cmp_b_topo.get("b_coverage_topo", 0.0)

        pairs.append({
            "image_filename": image_filename,
            "run_id": run.get("run_id", "?"),
            "disaster_category": run.get("disaster_category", ""),
            "n_edges_gt": n_gt,
            "n_edges_a": n_a,
            "n_edges_b": n_b,
            # Strict
            "a_correctness": float(a_correctness),
            "a_precision": float(a_precision),
            "b_correctness": float(b_correctness),
            "b_precision": float(b_precision),
            # Soft (semantic / label-hierarchy)
            "a_correctness_soft": float(a_correctness_soft),
            "a_precision_soft": float(a_precision_soft),
            "b_correctness_soft": float(b_correctness_soft),
            "b_precision_soft": float(b_precision_soft),
            # Topological
            "a_correctness_topo": float(a_correctness_topo),
            "a_precision_topo": float(a_precision_topo),
            "b_correctness_topo": float(b_correctness_topo),
            "b_precision_topo": float(b_precision_topo),
            "a_gt_matched": len(cmp_a.get("edge_diff", {}).get("in_both") or []),
            "b_gt_matched": len(cmp_b.get("edge_diff", {}).get("in_both") or []),
            "a_gt_matched_soft": int(cmp_a_soft.get("matched", 0)),
            "b_gt_matched_soft": int(cmp_b_soft.get("matched", 0)),
            "a_gt_matched_topo": int(cmp_a_topo.get("matched", 0)),
            "b_gt_matched_topo": int(cmp_b_topo.get("matched", 0)),
        })

    if not pairs:
        return {
            "n_pairs": 0,
            "n_verified": len(gt_files),
            "n_unmatched": len(unmatched),
            "unmatched_filenames": unmatched,
            "per_pair": [],
            "aggregate": {},
            "verdict_kind": "neutral",
            "verdict_text": "No verified-to-batch pairs found. Check folder paths.",
        }

    # Aggregate
    def med(key):
        vals = [p[key] for p in pairs]
        return _summarize(vals)

    aggregate = {
        "a_correctness": med("a_correctness"),
        "a_precision": med("a_precision"),
        "b_correctness": med("b_correctness"),
        "b_precision": med("b_precision"),
        "a_correctness_soft": med("a_correctness_soft"),
        "a_precision_soft": med("a_precision_soft"),
        "b_correctness_soft": med("b_correctness_soft"),
        "b_precision_soft": med("b_precision_soft"),
        "a_correctness_topo": med("a_correctness_topo"),
        "a_precision_topo": med("a_precision_topo"),
        "b_correctness_topo": med("b_correctness_topo"),
        "b_precision_topo": med("b_precision_topo"),
    }

    # Per-category breakdown
    by_category: dict[str, list[dict[str, Any]]] = {}
    for p in pairs:
        cat = str(p.get("disaster_category") or "").strip() or "(uncategorized)"
        by_category.setdefault(cat, []).append(p)
    category_breakdown = []
    for cat in sorted(by_category):
        cp = by_category[cat]
        category_breakdown.append({
            "category": cat,
            "n": len(cp),
            "a_correctness_median": _percentile([p["a_correctness"] for p in cp], 0.5),
            "b_correctness_median": _percentile([p["b_correctness"] for p in cp], 0.5),
            "a_precision_median": _percentile([p["a_precision"] for p in cp], 0.5),
            "b_precision_median": _percentile([p["b_precision"] for p in cp], 0.5),
            "a_correctness_soft_median": _percentile([p["a_correctness_soft"] for p in cp], 0.5),
            "b_correctness_soft_median": _percentile([p["b_correctness_soft"] for p in cp], 0.5),
        })

    # Verdict uses the TOPOLOGICAL B-correctness as the strongest external-validation
    # number (state-blind structural agreement). Reports all three tiers + gaps.
    median_b_corr_strict = aggregate["b_correctness"]["median"]
    median_b_corr_soft = aggregate["b_correctness_soft"]["median"]
    median_b_corr_topo = aggregate["b_correctness_topo"]["median"]
    gap_strict_soft = median_b_corr_soft - median_b_corr_strict
    gap_soft_topo = median_b_corr_topo - median_b_corr_soft

    summary_line = (
        f"B-correctness — strict {median_b_corr_strict:.2f}, "
        f"soft {median_b_corr_soft:.2f}, "
        f"topological {median_b_corr_topo:.2f} "
        f"(gaps: vocabulary {gap_strict_soft:+.2f}, state {gap_soft_topo:+.2f})"
    )
    matcher_note = (
        " Strict matches verbatim IDs and is brittle to enumeration drift "
        "(if Claude calls them firefighter_1..4 and Qwen orders them differently, "
        "strict drops). Soft and topological strip IDs and compare label/effect "
        "multisets — these are the load-bearing numbers."
    )
    if median_b_corr_topo >= 0.70:
        verdict_kind, verdict_text = (
            "good",
            f"Graph B recovers most reference structure. {summary_line}. External validation is solid; remaining gaps are mostly vocabulary, not structural.{matcher_note}",
        )
    elif median_b_corr_topo >= 0.40:
        verdict_kind, verdict_text = (
            "neutral",
            f"Graph B partially recovers reference structure. {summary_line}. Model captures the gist but misses material edges or links the wrong entities.{matcher_note}",
        )
    else:
        verdict_kind, verdict_text = (
            "warning",
            f"Graph B diverges from reference even structurally. {summary_line}. Model's independent reasoning misses or misattributes core causal links.{matcher_note}",
        )

    return {
        "n_pairs": len(pairs),
        "n_verified": len(gt_files),
        "n_unmatched": len(unmatched),
        "unmatched_filenames": unmatched,
        "per_pair": pairs,
        "aggregate": aggregate,
        "by_category": category_breakdown,
        "verdict_kind": verdict_kind,
        "verdict_text": verdict_text,
    }


def aggregate_prompt_sensitivity(
    results: list[dict[str, Any]], variant_ids: list[str]
) -> dict[str, Any]:
    """Compute per-variant medians and per-image dispersion (max-min spread)."""
    if not results:
        return {
            "n_images": 0,
            "variants": variant_ids,
            "per_variant_medians": {},
            "per_image_dispersion": [],
            "dispersion_summary": {},
            "verdict": "no data",
        }

    # Per-variant: collect each metric's values across images
    per_variant_metric_lists: dict[str, dict[str, list[float]]] = {
        vid: {"a_fidelity": [], "b_coverage": [], "topological_consistency": []} for vid in variant_ids
    }
    for r in results:
        for vid in variant_ids:
            v = (r.get("variants") or {}).get(vid, {})
            if "error" in v:
                continue
            for k in ("a_fidelity", "b_coverage", "topological_consistency"):
                if k in v:
                    per_variant_metric_lists[vid][k].append(float(v[k]))

    per_variant_medians = {
        vid: {k: _percentile(per_variant_metric_lists[vid][k], 0.5) for k in per_variant_metric_lists[vid]}
        for vid in variant_ids
    }

    # Per-image dispersion: for each metric, max-min across variants
    per_image_dispersion: list[dict[str, Any]] = []
    for r in results:
        row = {"run_id": r.get("run_id", "?"), "image_filename": r.get("image_filename", "")}
        for metric in ("a_fidelity", "b_coverage", "topological_consistency"):
            vals = []
            for vid in variant_ids:
                v = (r.get("variants") or {}).get(vid, {})
                if "error" not in v and metric in v:
                    vals.append(float(v[metric]))
            row[f"{metric}_spread"] = (max(vals) - min(vals)) if len(vals) >= 2 else 0.0
            row[f"{metric}_min"] = min(vals) if vals else 0.0
            row[f"{metric}_max"] = max(vals) if vals else 0.0
        per_image_dispersion.append(row)

    # Aggregate the dispersions
    dispersion_summary = {}
    for metric in ("a_fidelity", "b_coverage", "topological_consistency"):
        spreads = [r[f"{metric}_spread"] for r in per_image_dispersion if r.get(f"{metric}_spread") is not None]
        dispersion_summary[metric] = _summarize(spreads)

    # Verdict on A-fidelity spread (the headline metric for Test 2)
    median_a_spread = dispersion_summary["a_fidelity"]["median"]
    if median_a_spread <= 0.10:
        verdict_kind, verdict_text = (
            "good",
            f"A-fidelity is prompt-stable (median spread {median_a_spread:.2f} ≤ 0.10). Stage 1 can proceed.",
        )
    elif median_a_spread <= 0.20:
        verdict_kind, verdict_text = (
            "warning",
            f"A-fidelity is partially prompt-stable (median spread {median_a_spread:.2f}). Report shift results with prompt-variance caveats.",
        )
    else:
        verdict_kind, verdict_text = (
            "warning",
            f"A-fidelity is heavily prompt-sensitive (median spread {median_a_spread:.2f} > 0.20). Reconsider Prompt 2 design before Stage 1.",
        )

    return {
        "n_images": len(results),
        "variants": variant_ids,
        "per_variant_medians": per_variant_medians,
        "per_image_dispersion": per_image_dispersion,
        "dispersion_summary": dispersion_summary,
        "verdict_kind": verdict_kind,
        "verdict_text": verdict_text,
    }


def _run_batch_worker(
    images: list[Path],
    use_sidecar: bool,
    allow_inferred: bool,
    out_dir: Path,
    images_root: Path | None = None,
) -> None:
    """Worker thread: process images sequentially, write progress to _BATCH_STATE,
    then aggregate the runs into a report."""
    with _BATCH_LOCK:
        _BATCH_STATE.update({
            "active": True,
            "done": False,
            "total": len(images),
            "completed": 0,
            "current": "",
            "errors": [],
            "out_dir": str(out_dir),
            "report_path": None,
            "started_at": datetime.now().isoformat(timespec="seconds"),
        })

    for img_path in images:
        with _BATCH_LOCK:
            _BATCH_STATE["current"] = img_path.name

        caption = _read_sidecar_caption(img_path) if use_sidecar else ""
        category = _infer_disaster_category(img_path, images_root) if images_root else ""
        ok, err = _process_one_image(img_path, caption, allow_inferred, out_dir, category=category)
        with _BATCH_LOCK:
            _BATCH_STATE["completed"] += 1
            if not ok:
                _BATCH_STATE["errors"].append({"image": img_path.name, "error": err or "unknown"})

    # Determine batch_dir (new layout: out_dir is .../batches/batch_<ts>/runs/)
    # Fall back to out_dir itself for backwards compatibility.
    batch_dir = out_dir.parent if out_dir.name == "runs" else out_dir

    # Aggregate report at the end
    try:
        runs, skipped = load_run_jsons(str(out_dir))
        report = compute_pre_intervention_report(runs)
        findings = interpret_pre_intervention_report(report)
        # Surface-only: attach Test 1 (verified-GT comparison) and latest Test 2
        # (prompt sensitivity) verdicts. No math changes to trust scoring.
        external_tests: dict[str, Any] = {}
        try:
            t1_result = compute_ground_truth_report(str(GT_VERIFIED_DIR), str(out_dir))
            external_tests["test1_ground_truth"] = t1_result
            # Persist Test 1 inside the batch folder
            try:
                t1_dir = batch_dir / "tests" / "test1_ground_truth"
                t1_dir.mkdir(parents=True, exist_ok=True)
                (t1_dir / "ground_truth_comparison.json").write_text(json.dumps(t1_result, indent=2))
            except Exception:
                pass
        except Exception as exc:
            external_tests["test1_ground_truth"] = {"error": str(exc)}
        try:
            psens_latest_path = EXPORT_ROOT / "tests" / "latest_prompt_sensitivity.json"
            if psens_latest_path.exists():
                external_tests["test2_prompt_sensitivity"] = json.loads(psens_latest_path.read_text())
            else:
                external_tests["test2_prompt_sensitivity"] = {"available": False, "reason": "no latest_prompt_sensitivity.json found"}
        except Exception as exc:
            external_tests["test2_prompt_sensitivity"] = {"error": str(exc)}

        # Save report inside the batch folder: exports/batches/batch_<ts>/report/
        report_dir = save_report(
            report, findings, str(out_dir),
            skipped=skipped, external_tests=external_tests,
            out_root=(batch_dir / "report"),
        )
        with _BATCH_LOCK:
            _BATCH_STATE["report_path"] = str(report_dir)

        # Update latest_batch symlink (best-effort; ignored on filesystems without symlink support)
        try:
            latest_link = EXPORT_ROOT / "latest_batch"
            if latest_link.is_symlink() or latest_link.exists():
                try:
                    latest_link.unlink()
                except Exception:
                    pass
            latest_link.symlink_to(batch_dir.resolve(), target_is_directory=True)
        except Exception:
            pass
    except Exception as exc:
        with _BATCH_LOCK:
            _BATCH_STATE["errors"].append({"image": "(report)", "error": str(exc)})

    with _BATCH_LOCK:
        _BATCH_STATE["active"] = False
        _BATCH_STATE["done"] = True
        _BATCH_STATE["current"] = ""


def make_gt_validation_panel(gt_validation: dict[str, Any]) -> html.Div:
    """Render the External Validation (Test 1) card for a single run.

    Surface-only: shows strict/soft/topological scores against verified GT for
    THIS image, if a verified GT file exists. Does NOT feed into trust score.
    """
    if not gt_validation or not gt_validation.get("available"):
        reason = (gt_validation or {}).get("reason", "no verified GT available")
        return html.Div(
            [
                html.Div(
                    "What this would show: a comparison between this image's causal graphs "
                    "(A and B) against an independently-authored reference graph for the SAME image. "
                    "Currently unavailable because we have no verified reference for this image yet.",
                    className="card-subtext",
                    style={"marginBottom": "8px"},
                ),
                html.Div("Not in verified GT set.", className="empty-state"),
                html.Div(reason, className="card-subtext"),
            ],
            className="gt-validation-empty",
        )

    n_gt = gt_validation["n_edges_gt"]
    n_a = gt_validation["n_edges_a"]
    n_b = gt_validation["n_edges_b"]

    def score_pill(value: float) -> str:
        if value >= 0.85: return "score-high"
        if value >= 0.50: return "score-mid"
        return "score-low"

    def metric_box(label: str, tooltip: str, strict: float, soft: float, topo: float) -> html.Div:
        return html.Div(
            [
                html.Div(
                    label,
                    className="consistency-score-label",
                    title=tooltip,
                ),
                html.Div(
                    [
                        html.Div([
                            html.Div("strict", className="gt-val-sub-label",
                                     title="Exact 4-tuple match: source_id, target_id, effect, via_state must all be identical. Brittle to ID-enumeration drift between annotators."),
                            html.Div(f"{strict:.2f}", className=f"consistency-score-value {score_pill(strict)} gt-val-small"),
                        ], className="gt-val-cell"),
                        html.Div([
                            html.Div("soft", className="gt-val-sub-label",
                                     title="Label-class + state-synonym + effect-pair match (IDs stripped). 'man' and 'firefighter' both become 'person'; 'charred' and 'burnt' canonicalize. Robust to ID drift. This is the load-bearing number."),
                            html.Div(f"{soft:.2f}", className=f"consistency-score-value {score_pill(soft)} gt-val-small"),
                        ], className="gt-val-cell"),
                        html.Div([
                            html.Div("topo", className="gt-val-sub-label",
                                     title="Topological: like soft but ignores state entirely. Just (source-label, effect, target-label). Answers 'did the model recover the structural skeleton even if it disagreed on state vocabulary?'"),
                            html.Div(f"{topo:.2f}", className=f"consistency-score-value {score_pill(topo)} gt-val-small"),
                        ], className="gt-val-cell"),
                    ],
                    className="gt-val-cells",
                ),
            ],
            className="consistency-score-card gt-val-card",
        )

    return html.Div(
        [
            # WHAT + WHY explanation
            html.Details(
                [
                    html.Summary(
                        "What is this and why does it matter? (click to expand)",
                        className="gt-val-explainer-summary",
                    ),
                    html.Div(
                        [
                            html.P([
                                html.B("What: "),
                                "We compare two graphs against an ",
                                html.B("independently-authored reference graph"),
                                " (Claude-as-judge, then human-verified) for the same image. "
                                "Graph A = derived from the VLM's recommendations. "
                                "Graph B = the VLM's own causal graph (no recommendations). "
                                "GT = the reference.",
                            ]),
                            html.P([
                                html.B("Why: "),
                                "Internal-consistency checks (trust score, A↔B alignment) only tell us if the VLM is "
                                "self-coherent. They can't catch a model that's confidently wrong. "
                                "External validation asks: ",
                                html.I("does the model's causal story agree with a reference observer?"),
                                " A model that scores high internally but low here is fluent but unmoored. "
                                "A model that scores high on both is reliably grounded.",
                            ]),
                            html.P([
                                html.B("Reading the metrics: "),
                                html.B("Correctness "), "= recall = fraction of GT edges the model recovered. ",
                                html.B("Precision "), "= fraction of model's edges that are in GT (non-spurious).",
                            ]),
                            html.P([
                                html.B("Reading the tiers: "),
                                html.B("Strict "), "uses verbatim IDs and is brittle when the VLM enumerates entities differently than the reference. ",
                                html.B("Soft "), "(load-bearing) strips IDs, collapses synonymous labels and states, and matches multisets. ",
                                html.B("Topological "), "ignores state entirely — pure structure. Big strict→soft gap = ID-drift, not real disagreement.",
                            ]),
                            html.P([
                                html.B("Surface-only: "),
                                "these scores do NOT feed into the trust score. They sit alongside it as a separate, independent signal. "
                                "Aggregate version (across many images) is the Test 1 numbers in batch reports.",
                            ], style={"fontStyle": "italic", "marginBottom": "0"}),
                        ],
                        className="gt-val-explainer-body",
                    ),
                ],
                className="gt-val-explainer",
            ),

            html.Div(
                f"Verified reference available for this image. Edge counts: reference={n_gt}, Graph A={n_a}, Graph B={n_b}.",
                className="card-subtext card-subtitle",
                style={"marginTop": "10px"},
            ),
            html.Div(
                [
                    metric_box(
                        "A-correctness (recall vs reference)",
                        "Of the edges in the reference graph, what fraction did Graph A recover? Recall.",
                        gt_validation["a_correctness"], gt_validation["a_correctness_soft"], gt_validation["a_correctness_topo"],
                    ),
                    metric_box(
                        "A-precision (specificity vs reference)",
                        "Of the edges Graph A produced, what fraction are in the reference? Precision. Low = Graph A is making causal claims the reference doesn't endorse.",
                        gt_validation["a_precision"], gt_validation["a_precision_soft"], gt_validation["a_precision_topo"],
                    ),
                ],
                className="consistency-score-row gt-val-row",
            ),
            html.Div(
                [
                    metric_box(
                        "B-correctness (recall vs reference)",
                        "Of the edges in the reference graph, what fraction did Graph B (the VLM's independent graph) recover?",
                        gt_validation["b_correctness"], gt_validation["b_correctness_soft"], gt_validation["b_correctness_topo"],
                    ),
                    metric_box(
                        "B-precision (specificity vs reference)",
                        "Of Graph B's edges, what fraction are in the reference? Low = Graph B is hallucinating causal links.",
                        gt_validation["b_precision"], gt_validation["b_precision_soft"], gt_validation["b_precision_topo"],
                    ),
                ],
                className="consistency-score-row gt-val-row",
            ),
            html.Div(
                "Surface-only: these scores do not feed into the trust score. See Validation: Tests tab for aggregate Test 1 results across many images.",
                className="card-subtext",
                style={"marginTop": "8px", "fontStyle": "italic"},
            ),
        ],
        className="gt-validation-panel",
    )


def make_pre_intervention_report_panel(
    report: dict[str, Any],
    skipped: list[dict[str, str]] | None = None,
    status: str = "",
) -> html.Div:
    """Render an aggregated pre-intervention report from N runs."""
    if not report or report.get("n_runs", 0) == 0:
        return html.Div(
            status or "No runs loaded yet. Choose a folder and click Generate Report.",
            className="empty-state",
        )

    n = report["n_runs"]
    skipped = skipped or []
    n_total = report.get("n_runs_total", n)
    n_non = report.get("n_runs_non_disaster", 0)

    # Header
    header_subtitle_parts = [f"{n} disaster run{'s' if n != 1 else ''} aggregated"]
    if n_non:
        header_subtitle_parts.append(f"{n_non} non-disaster excluded")
    if skipped:
        header_subtitle_parts.append(f"{len(skipped)} parse-skipped")
    header = html.Div(
        [
            html.Div(f"Pre-Intervention Report — {n_total} total", className="report-title"),
            html.Div(" · ".join(header_subtitle_parts), className="report-subtitle"),
        ],
        className="report-header",
    )

    explainer = html.Details(
        [
            html.Summary(
                "What is this report and how to read it? (click to expand)",
                className="gt-val-explainer-summary",
            ),
            html.Div(
                [
                    html.P([
                        html.B("What: "),
                        "An aggregate view of N single-scene analyses. Each run is one image processed through the full pipeline (Prompt 1 → recommendations + Graph A, Prompt 2 → Graph B, internal alignment checks, A↔B consistency, baseline trust). ",
                        "This report rolls them up into distributions and medians so you can see how the VLM behaves across a sample, not just on one cherry-picked image.",
                    ]),
                    html.P([
                        html.B("Why: "),
                        "A single-image analysis is anecdotal. The aggregate report is where you spot patterns: ",
                        html.I("does most of the model's output land in the 'moderate' trust band, or does it cluster bimodally? "),
                        " Is internal alignment systematically lower than A↔B consistency, suggesting the format is fine but the reasoning isn't? These distributional answers are what go into the paper.",
                    ]),
                    html.P([
                        html.B("Reading the sections: "),
                        html.B("Interpretation "), "(top) is rule-based plain-English findings. ",
                        html.B("Trust distribution "), "shows how runs fall into high / moderate / low. ",
                        html.B("Per-signal medians "), "give the central tendency of each pre-intervention signal. ",
                        html.B("Per-run table "), "is the raw drill-down so you can find specific outliers.",
                    ]),
                    html.P([
                        html.B("External Validation (surface-only): "),
                        "Test 1 (verified GT comparison) and Test 2 (prompt sensitivity) verdicts appear in the report.md export. They are not part of the trust math — separate signals on the model's external validity, paired with the trust-based numbers but kept logically independent.",
                    ], style={"fontStyle": "italic", "marginBottom": "0"}),
                ],
                className="gt-val-explainer-body",
            ),
        ],
        className="gt-val-explainer",
        style={"marginBottom": "10px"},
    )

    # Interpretation block (rule-based)
    findings = interpret_pre_intervention_report(report)
    interpretation_block = (
        html.Div(
            [
                html.Div("Interpretation", className="report-section-label"),
                *[
                    html.Div(
                        [
                            html.Div(f.get("headline", ""), className=f"finding-headline finding-{f.get('kind', 'neutral')}"),
                            html.Div(f.get("detail", ""), className="finding-detail"),
                        ],
                        className=f"finding-row finding-row-{f.get('kind', 'neutral')}",
                    )
                    for f in findings
                ],
            ],
            className="report-section report-interpretation",
        )
        if findings
        else None
    )

    # Trust distribution
    trust_order = ["high", "moderate", "low", "unknown"]
    trust_dist = report.get("trust_distribution", {}) or {}
    trust_total = sum(trust_dist.values()) or 1

    def trust_row(level: str) -> html.Div:
        count = int(trust_dist.get(level, 0))
        pct = 100 * count / trust_total
        bar_color = {
            "high": "#15803d",
            "moderate": "#b45309",
            "low": "#b91c1c",
            "unknown": "#94a3b8",
        }.get(level, "#94a3b8")
        return html.Div(
            [
                html.Div(level.title(), className="report-bar-label"),
                html.Div(
                    html.Div(
                        style={
                            "width": f"{pct}%",
                            "background": bar_color,
                        },
                        className="report-bar-fill",
                    ),
                    className="report-bar-track",
                ),
                html.Div(f"{count} ({pct:.0f}%)", className="report-bar-count"),
            ],
            className="report-bar-row",
        )

    trust_section = html.Div(
        [
            html.Div("Trust level distribution", className="report-section-label"),
            *[trust_row(level) for level in trust_order if level in trust_dist],
        ],
        className="report-section",
    )

    # Metric distributions
    metric_dists = report.get("metric_distributions", {}) or {}
    metric_label = {
        "a_fidelity":              "A-fidelity",
        "b_coverage":              "B-coverage",
        "topological_consistency": "Topological",
        "node_consistency":        "Node",
        "flag_consistency":        "Hazard flag",
        "coverage_a":              "Coverage A",
        "coverage_b":              "Coverage B",
        "internal_alignment":      "Internal alignment",
        "trust_score":             "Trust score",
        "disaster_level":          "Disaster level",
    }
    metric_rows = []
    for key, label in metric_label.items():
        if key not in metric_dists:
            continue
        s = metric_dists[key]
        if s.get("n", 0) == 0:
            continue
        metric_rows.append(
            html.Div(
                [
                    html.Div(label, className="metric-name"),
                    html.Div(f"{s['median']:.2f}", className="metric-value metric-median"),
                    html.Div(f"[{s['p25']:.2f}–{s['p75']:.2f}]", className="metric-value metric-iqr"),
                    html.Div(f"({s['min']:.2f}–{s['max']:.2f})", className="metric-value metric-range"),
                    html.Div(f"n={int(s['n'])}", className="metric-value metric-n"),
                ],
                className="metric-row",
            )
        )

    metric_section = html.Div(
        [
            html.Div("Metric distributions  —  median [IQR] (range)", className="report-section-label"),
            html.Div(
                [
                    html.Div("Metric", className="metric-name metric-header"),
                    html.Div("Median", className="metric-value metric-header"),
                    html.Div("IQR", className="metric-value metric-header"),
                    html.Div("Range", className="metric-value metric-header"),
                    html.Div("n", className="metric-value metric-header"),
                ],
                className="metric-row metric-header-row",
            ),
            *metric_rows,
        ],
        className="report-section",
    )

    # Failure histogram
    fhist = report.get("failure_histogram", []) or []
    fhist_max = max((f["count"] for f in fhist), default=1)
    failure_rows = [
        html.Div(
            [
                html.Div(f["type"], className="failure-name"),
                html.Div(
                    html.Div(
                        style={"width": f"{100 * f['count'] / fhist_max}%"},
                        className="failure-bar-fill",
                    ),
                    className="failure-bar-track",
                ),
                html.Div(str(f["count"]), className="failure-count"),
            ],
            className="failure-row",
        )
        for f in fhist[:15]
    ] if fhist else [html.Div("No alignment failures across runs.", className="diff-empty")]

    failure_section = html.Div(
        [
            html.Div("Top alignment failure types", className="report-section-label"),
            *failure_rows,
        ],
        className="report-section",
    )

    # Scene-level stats
    scene = report.get("scene_level", {}) or {}
    scene_label = {
        "detected_objects":  "Detected objects",
        "threats_per_scene": "Threats",
        "recs_per_scene":    "Recommendations",
        "edges_in_a":        "Edges in A",
        "edges_in_b":        "Edges in B",
    }
    scene_rows = []
    for key, label in scene_label.items():
        s = scene.get(key, {})
        if not s or s.get("n", 0) == 0:
            continue
        scene_rows.append(
            html.Div(
                [
                    html.Div(label, className="metric-name"),
                    html.Div(f"{s['mean']:.1f}", className="metric-value"),
                    html.Div(f"median {s['median']:.0f}", className="metric-value metric-iqr"),
                    html.Div(f"min {s['min']:.0f} · max {s['max']:.0f}", className="metric-value metric-range"),
                ],
                className="metric-row",
            )
        )
    scene_section = html.Div(
        [
            html.Div("Scene-level stats per run", className="report-section-label"),
            *scene_rows,
        ],
        className="report-section",
    )

    # Outliers
    outlier_rows = [
        html.Div(
            [
                html.Div(o["label"], className="outlier-label"),
                html.Div(o["run_id"], className="outlier-run"),
                html.Div(o["value"], className="outlier-value"),
            ],
            className="outlier-row",
        )
        for o in report.get("outliers", []) or []
    ] or [html.Div("No outliers identified.", className="diff-empty")]
    outlier_section = html.Div(
        [
            html.Div("Outliers worth inspecting", className="report-section-label"),
            *outlier_rows,
        ],
        className="report-section",
    )

    # Per-category breakdown
    by_cat = report.get("by_category") or []
    multi_category = len(by_cat) > 1 or (len(by_cat) == 1 and by_cat[0]["category"] != "(uncategorized)")
    if multi_category:
        cat_rows = [
            html.Div(
                [
                    html.Div("Category", className="cat-cell cat-header"),
                    html.Div("n", className="cat-cell cat-header"),
                    html.Div("Trust H/M/L", className="cat-cell cat-header"),
                    html.Div("A-fid med", className="cat-cell cat-header"),
                    html.Div("B-cov med", className="cat-cell cat-header"),
                    html.Div("Internal med", className="cat-cell cat-header"),
                    html.Div("Trust score med", className="cat-cell cat-header"),
                ],
                className="cat-row cat-header-row",
            ),
        ]
        for c in by_cat:
            t = c["trust"]
            cat_rows.append(
                html.Div(
                    [
                        html.Div(c["category"], className="cat-cell cat-name"),
                        html.Div(str(c["n"]), className="cat-cell"),
                        html.Div(f"{t['high']}/{t['moderate']}/{t['low']}", className="cat-cell"),
                        html.Div(f"{c['a_fidelity_median']:.2f}", className="cat-cell cat-numeric"),
                        html.Div(f"{c['b_coverage_median']:.2f}", className="cat-cell cat-numeric"),
                        html.Div(f"{c['internal_median']:.2f}", className="cat-cell cat-numeric"),
                        html.Div(f"{c['trust_score_median']:.2f}", className="cat-cell cat-numeric"),
                    ],
                    className="cat-row",
                )
            )
        category_section = html.Div(
            [
                html.Div("By disaster category (folder-derived)", className="report-section-label"),
                html.Div(cat_rows, className="cat-table"),
            ],
            className="report-section",
        )
    else:
        category_section = None

    # Per-run details (collapsible)
    per_run = report.get("per_run", []) or []
    per_run_section = html.Details(
        [
            html.Summary(f"Per-run summary ({len(per_run)} rows)"),
            html.Div(
                [
                    html.Div(
                        [
                            html.Div("Run", className="prr-cell prr-header"),
                            html.Div("Trust", className="prr-cell prr-header"),
                            html.Div("Score", className="prr-cell prr-header"),
                            html.Div("A-fid", className="prr-cell prr-header"),
                            html.Div("B-cov", className="prr-cell prr-header"),
                            html.Div("Internal", className="prr-cell prr-header"),
                            html.Div("Threats", className="prr-cell prr-header"),
                            html.Div("Recs", className="prr-cell prr-header"),
                            html.Div("Failures", className="prr-cell prr-header"),
                        ],
                        className="prr-row prr-header-row",
                    ),
                    *[
                        html.Div(
                            [
                                html.Div(p["run_id"], className="prr-cell prr-id"),
                                html.Div(p["trust_level"], className="prr-cell"),
                                html.Div(f"{p['trust_score']:.2f}", className="prr-cell"),
                                html.Div(f"{p['a_fidelity']:.2f}", className="prr-cell"),
                                html.Div(f"{p['b_coverage']:.2f}", className="prr-cell"),
                                html.Div(f"{p['internal']:.2f}", className="prr-cell"),
                                html.Div(str(p["n_threats"]), className="prr-cell"),
                                html.Div(str(p["n_recs"]), className="prr-cell"),
                                html.Div(str(p["n_failures"]), className="prr-cell"),
                            ],
                            className="prr-row",
                        )
                        for p in per_run
                    ],
                ],
                className="prr-table",
            ),
        ],
        className="report-section",
    )

    children = [header, explainer]
    if interpretation_block is not None:
        children.append(interpretation_block)
    children.extend([
        trust_section,
        metric_section,
        failure_section,
        scene_section,
    ])
    if category_section is not None:
        children.append(category_section)
    children.extend([
        outlier_section,
        per_run_section,
    ])
    return html.Div(children, className="report-panel")


def make_pre_intervention_trust_panel(trust: dict[str, Any]) -> html.Div:
    """Render baseline trust summary with explicit breakdown and meaning.

    Layout:
      [level + score]   [Why this score | What this level means | Issues | Context]
    """
    if not trust or trust.get("level") == "unknown":
        return html.Div("Run analysis to estimate baseline trust.", className="empty-state")
    if trust.get("level") == "not_applicable":
        return html.Div(
            "Trust scoring not applicable: scene has no threats or causal edges.",
            className="empty-state",
        )

    level = str(trust.get("level", "unknown"))
    score = float(trust.get("score", 0.0) or 0.0)
    level_class = {
        "high": "trust-high",
        "moderate": "trust-moderate",
        "low": "trust-low",
    }.get(level, "trust-unknown")
    qualifiers = trust.get("qualifiers", []) or []
    components = trust.get("components", {}) or {}

    # Score breakdown — show each weighted contribution to the total.
    internal = float(components.get("internal_alignment", 0.0) or 0.0)
    a_fid = float(components.get("a_fidelity", 0.0) or 0.0)
    b_cov = float(components.get("b_edge_coverage", 0.0) or 0.0)
    cov_a = float(components.get("graph_a_coverage", 0.0) or 0.0)
    cov_b = float(components.get("graph_b_coverage", 0.0) or 0.0)
    cov_avg = (cov_a + cov_b) / 2

    breakdown = [
        ("Internal alignment", internal, 0.40, "Layer 2 contract checks (most fundamental)."),
        ("A-fidelity", a_fid, 0.20, "Recs grounded in model's own beliefs."),
        ("B-coverage", b_cov, 0.20, "Recs cover what model believes."),
        ("Threat coverage (avg)", cov_avg, 0.20, "Declared threats produce edges."),
    ]

    breakdown_rows = [
        html.Div(
            [
                html.Div(name, className="breakdown-name"),
                html.Div(f"{value:.2f}", className="breakdown-value"),
                html.Div("×", className="breakdown-times"),
                html.Div(f"{weight:.2f}", className="breakdown-weight"),
                html.Div("=", className="breakdown-equals"),
                html.Div(f"{value * weight:.3f}", className="breakdown-contribution"),
                html.Div(rationale, className="breakdown-rationale"),
            ],
            className="breakdown-row",
        )
        for name, value, weight, rationale in breakdown
    ]

    breakdown_total = html.Div(
        [
            html.Div("Total", className="breakdown-name breakdown-total-name"),
            html.Div("", className="breakdown-value"),
            html.Div("", className="breakdown-times"),
            html.Div("", className="breakdown-weight"),
            html.Div("=", className="breakdown-equals"),
            html.Div(f"{score:.3f}", className=f"breakdown-contribution breakdown-total-value {level_class}"),
            html.Div("", className="breakdown-rationale"),
        ],
        className="breakdown-row breakdown-total-row",
    )

    # Level meaning — what this level allows you to do with intervention shifts.
    level_meaning = {
        "high": (
            "Post-intervention shifts can be interpreted as strong evidence of causal grounding. "
            "Recommendations align with the model's own causal beliefs and the contract checks pass."
        ),
        "moderate": (
            "Post-intervention shifts are usable as evidence but should be reported with caveats. "
            "Either some recommendations aren't supported by independent reasoning, or the model "
            "knows causal links it didn't act on."
        ),
        "low": (
            "Post-intervention shifts are hard to attribute to grounded causal reasoning. The baseline "
            "is unstable — shifts may reflect incoherence rather than mechanism. Downweight unless "
            "post-intervention output becomes substantially more coherent."
        ),
    }.get(level, "Run analysis to estimate baseline trust.")

    # Filter out the trivial "all good" qualifier — handled by the "What this level means" block instead.
    real_qualifiers = [
        q for q in qualifiers
        if not q.startswith("Baseline causal account is internally coherent")
    ]
    issues_block = (
        html.Div(
            [
                html.Div("Issues lowering trust", className="trust-section-label"),
                html.Ul(
                    [html.Li(q) for q in real_qualifiers],
                    className="trust-qualifiers",
                ),
            ],
            className="trust-issues-block",
        )
        if real_qualifiers
        else html.Div(
            [
                html.Div("No issues", className="trust-section-label"),
                html.Div(
                    "Baseline is internally coherent and Graph A/B agreement is strong.",
                    className="trust-no-issues",
                ),
            ],
            className="trust-issues-block",
        )
    )

    # Context signals (not weighted; diagnostic only). Structural is omitted —
    # it is decomposed into A-fidelity + B-coverage shown in the breakdown above.
    context_items = [
        ("Topological", components.get("topological_consistency", 0.0)),
        ("Node", components.get("node_consistency", 0.0)),
        ("Hazard flags", components.get("flag_consistency", 0.0)),
    ]
    effect_gap_count = int(components.get("effect_disagreement_count", 0) or 0)

    return html.Div(
        [
            html.Details(
                [
                    html.Summary(
                        "What is baseline trust and why does it matter? (click to expand)",
                        className="gt-val-explainer-summary",
                    ),
                    html.Div(
                        [
                            html.P([
                                html.B("What: "),
                                "A single score (0–1) summarizing how internally coherent the model's output is BEFORE we run any intervention. "
                                "It's a weighted average of four components, each measuring a different way the model could be self-contradictory.",
                            ]),
                            html.P([
                                html.B("Why: "),
                                "Stage 1 of CEE+ measures how the model's reasoning ",
                                html.I("shifts"),
                                " after we suppress a hazard. Those shifts are only interpretable if the baseline was coherent to start with. ",
                                "A model that's already self-contradictory before intervention — recommendations that don't match its own graph, threats it forgot to wire up — produces 'shifts' that are noise, not evidence of causal grounding.",
                            ]),
                            html.P([
                                html.B("Components: "),
                                html.B("Internal alignment "), "(40%): Layer-2 contract checks — object_ids match across fields, every threat has a recommendation, etc. ",
                                html.B("A-fidelity "), "(20%): every recommendation has at least one supporting edge in the model's Graph B. ",
                                html.B("B-coverage "), "(20%): every Graph B edge has a corresponding recommendation. ",
                                html.B("Threat coverage "), "(20%): every declared threat actually produces outgoing edges in the graphs.",
                            ]),
                            html.P([
                                html.B("Tiers: "),
                                html.B("High "), "(≥0.85 AND a-fidelity ≥0.75): post-intervention shifts are strong evidence. ",
                                html.B("Moderate "), "(≥0.60): usable evidence with caveats. ",
                                html.B("Low "), "(<0.60): baseline incoherent; shifts may reflect confusion, not mechanism.",
                            ]),
                            html.P([
                                html.B("Note: "),
                                "This is purely internal coherence. External validation (vs verified GT) is the card below — independent signal, doesn't feed in here.",
                            ], style={"fontStyle": "italic", "marginBottom": "0"}),
                        ],
                        className="gt-val-explainer-body",
                    ),
                ],
                className="gt-val-explainer",
                style={"marginBottom": "10px"},
            ),
            html.Div(
                [
                    html.Div("Baseline trust", className="trust-label"),
                    html.Div(level.title(), className=f"trust-level {level_class}"),
                    html.Div(f"{score:.2f}", className="trust-score"),
                    html.Div(f'What "{level}" means', className="trust-section-label trust-summary-meaning-label"),
                    html.Div(level_meaning, className="trust-meaning trust-summary-meaning"),
                ],
                className="trust-summary-card",
            ),
            html.Div(
                [
                    html.Div("Why this score", className="trust-section-label"),
                    html.Div(
                        [
                            html.Div(
                                [
                                    html.Div("Component", className="breakdown-name breakdown-header"),
                                    html.Div("Value", className="breakdown-value breakdown-header"),
                                    html.Div("", className="breakdown-times"),
                                    html.Div("Weight", className="breakdown-weight breakdown-header"),
                                    html.Div("", className="breakdown-equals"),
                                    html.Div("Contribution", className="breakdown-contribution breakdown-header"),
                                    html.Div("", className="breakdown-rationale"),
                                ],
                                className="breakdown-row breakdown-header-row",
                            ),
                            *breakdown_rows,
                            breakdown_total,
                        ],
                        className="breakdown-table",
                    ),
                    issues_block,
                    html.Div("A/B context signals (not weighted)", className="trust-section-label trust-section-label-spaced trust-section-label-muted"),
                    html.Div(
                        [
                            *[
                                html.Span(
                                    f"{label}: {float(value or 0.0):.2f}",
                                    className="trust-component trust-component-context",
                                )
                                for label, value in context_items
                            ],
                            html.Span(
                                f"Effect gaps: {effect_gap_count}",
                                className="trust-component trust-component-context",
                            ),
                        ],
                        className="trust-components",
                    ),
                ],
                className="trust-detail-card",
            ),
        ],
        className="trust-panel",
    )


def make_entity_chip(
    image_contents: str | None, item: dict[str, Any], is_hazardous: bool
) -> html.Span:
    """Render a pill + hover thumbnail for an entity referenced in a recommendation.

    Threats and affected entities both get pills; styling differentiates them.
    `item` is a detected_objects entry (has label, state, bbox, object_id).
    """
    preview = make_single_object_preview(image_contents, item, is_hazardous=is_hazardous)
    label = f"{item['label']} ({item.get('state', 'unknown')})"
    pill_class = "pill threat interactive-pill" if is_hazardous else "pill affected interactive-pill"

    preview_node = (
        html.Div(
            [
                html.Img(src=preview, className="hazard-tooltip-image"),
                html.Div(
                    [
                        html.Div(item.get("state", "") or "No state provided", className="hazard-tooltip-state"),
                        html.Div(f"{item['object_id']} | BBox: {item.get('bbox')}", className="hazard-tooltip-meta"),
                    ]
                ),
            ],
            className="hazard-tooltip",
        )
        if preview
        else html.Div("Preview unavailable", className="hazard-tooltip")
    )

    return html.Span(
        [
            html.Span(label, className=pill_class),
            preview_node,
        ],
        className="hazard-pill-wrap",
    )


def make_hazard_thumbnails(
    image_contents: str | None,
    threats: list[dict[str, Any]],
    pill_visibility: dict[str, bool] | None = None,
) -> list[html.Div]:
    if not threats:
        return [html.Div("No threats returned yet.", className="empty-state")]

    pv = pill_visibility or {}
    show_reasoning = pv.get("reasoning", True)

    cards: list[html.Div] = []
    for item in threats:
        bbox = item.get("bbox")
        if not bbox:
            continue

        preview = make_single_object_preview(image_contents, item)

        cards.append(
            html.Div(
                [
                    html.Img(src=preview, className="threat-thumb"),
                    html.Div(
                        [
                            html.Div(
                                [
                                    html.Div(item["label"], className="threat-label"),
                                    html.Div(item.get("state", "unknown"), className="pill threat"),
                                ],
                                className="hazard-head",
                            ),
                            html.Div(
                                [reasoning_pill("reasoning", visible=show_reasoning), html.Span(item["reason"], className="reasoning-inline-text")],
                                className="hazard-reason",
                            ),
                            html.Div(f"{item['object_id']} | BBox: {bbox}", className="threat-bbox"),
                        ],
                        className="hazard-copy",
                    ),
                ],
                className="threat-card",
            )
        )

    return cards or [html.Div("Threats were returned without valid bounding boxes.", className="empty-state")]


def make_detected_objects_panel(
    image_contents: str | None,
    objects: list[dict[str, Any]],
) -> list[html.Div]:
    if not objects:
        return [html.Div("No objects returned yet.", className="empty-state")]

    overlay = make_overlay_preview(image_contents, objects)
    rows = []
    for item in objects:
        bbox = f"BBox: {item['bbox']}" if item.get("bbox") else "BBox unavailable"
        # detected_objects fields are pure perception — no reasoning markers here.
        rows.append(
            html.Div(
                [
                    html.Div(item["label"], className="detected-name"),
                    html.Div(item.get("state", "") or "No state provided", className="detected-state"),
                    html.Div(bbox, className="detected-meta"),
                ],
                className="detected-row",
            )
        )

    children: list[html.Div] = []
    if overlay:
        children.append(html.Img(src=overlay, className="embedded-preview"))
    children.append(html.Div(rows, className="detected-list"))
    return children


def make_hazard_list(threats: list[dict[str, Any]]) -> list[html.Div]:
    if not threats:
        return [html.Div("No threats returned yet.", className="empty-state")]

    items = []
    for item in threats:
        bbox = f"BBox: {item['bbox']}" if item.get("bbox") else "BBox unavailable"
        items.append(
            html.Div(
                [
                    html.Div(
                        [
                            html.Span(item["label"], className="hazard-name"),
                            html.Span(item.get("state", "unknown"), className="pill threat"),
                        ],
                        className="hazard-head",
                    ),
                    html.Div(item["reason"], className="hazard-reason"),
                    html.Div(f"{item['object_id']} | {bbox}", className="hazard-meta"),
                ],
                className="hazard-item threat",
            )
        )
    return items


def make_recommendation_list(
    recommendations: list[dict[str, Any]],
    detected_objects: list[dict[str, Any]],
    threats: list[dict[str, Any]],
    image_contents: str | None,
    pill_visibility: dict[str, bool] | None = None,
) -> list[html.Div]:
    if not recommendations:
        return [html.Div("No recommendations returned yet.", className="empty-state")]

    pv = pill_visibility or {}
    show_reasoning = pv.get("reasoning", True)

    # Resolve pills against detected_objects (the single source of truth) so that
    # affected entities — persons, latent threats — also get pills, not just threats.
    entity_lookup = {o["object_id"]: o for o in detected_objects}
    hazardous_ids = {t["object_id"] for t in threats}
    cards = []
    for index, item in enumerate(recommendations, start=1):
        related = [
            entity_lookup[oid]
            for oid in item["related_object_ids"]
            if oid in entity_lookup
        ]
        if related:
            related_nodes = [
                make_entity_chip(image_contents, ent, is_hazardous=ent["object_id"] in hazardous_ids)
                for ent in related
            ]
        else:
            related_nodes = [html.Span("No linked entities returned", className="pill neutral")]

        reasoning = item["structured_reasoning"]

        def label_with_pill(label_text: str) -> html.Div:
            return html.Div(
                [html.Span(label_text, className="detail-label-text"), reasoning_pill("reasoning", visible=show_reasoning)],
                className="detail-label-row",
            )

        cards.append(
            html.Div(
                [
                    html.Div(
                        [
                            html.Div("Priority", className="recommendation-kicker"),
                            html.Div(f"{item['rank'] or index}", className="recommendation-rank-badge"),
                        ],
                        className="recommendation-topline",
                    ),
                    html.Div(item["action"], className="recommendation-action"),
                    html.Div(
                        [reasoning_pill("reasoning", visible=show_reasoning), html.Span(item["reason"], className="reasoning-inline-text")],
                        className="recommendation-reason",
                    ),
                    html.Div(related_nodes, className="recommendation-links"),
                    html.Div(
                        [
                            html.Div(
                                [html.Span("Causal Quad", className="quad-section-label"), reasoning_pill("reasoning", visible=show_reasoning)],
                                className="quad-section-header",
                            ),
                            html.Div(
                                [
                                    html.Div(
                                        [html.Div("Threat", className="quad-label"), html.Div(reasoning["threat"], className="quad-value")],
                                        className="quad-item",
                                    ),
                                    html.Div(
                                        [html.Div("State", className="quad-label"), html.Div(reasoning["state"], className="quad-value")],
                                        className="quad-item",
                                    ),
                                    html.Div(
                                        [html.Div("Effect", className="quad-label"), html.Div(reasoning["effect"], className="quad-value")],
                                        className="quad-item",
                                    ),
                                    html.Div(
                                        [
                                            html.Div("Affected Objects", className="quad-label"),
                                            html.Div(
                                                ", ".join(reasoning.get("affected_objects") or []) or "—",
                                                className="quad-value",
                                            ),
                                        ],
                                        className="quad-item",
                                    ),
                                ],
                                className="quad-grid",
                            ),
                        ],
                        className="quad-section",
                    ),
                    html.Div(
                        [
                            html.Div(
                                [
                                    label_with_pill("Expected Consequence"),
                                    html.Div(item["expected_consequence"], className="detail-value"),
                                ],
                                className="detail-item",
                            ),
                            html.Div(
                                [
                                    label_with_pill("Remaining Risk"),
                                    html.Div(item["remaining_risk"], className="detail-value"),
                                ],
                                className="detail-item",
                            ),
                            html.Div(
                                [
                                    label_with_pill("Follow-Up Action"),
                                    html.Div(item["possible_follow_up_action"], className="detail-value"),
                                ],
                                className="detail-item",
                            ),
                        ],
                        className="detail-stack",
                    ),
                ],
                className="recommendation-card",
            )
        )
    return cards


def make_summary_panel(
    scene_summary: str,
    disaster_scenario: str,
    disaster_type: str,
    disaster_level: int,
    key_observations: list[str] | None = None,
    assumptions: list[str] | None = None,
    uncertainty_notes: list[str] | None = None,
    pill_visibility: dict[str, bool] | None = None,
) -> list[html.Div]:
    pv = pill_visibility or {}
    show_reasoning = pv.get("reasoning", True)
    show_assumption = pv.get("assumption", True)
    show_uncertainty = pv.get("uncertainty", True)

    # Suppress Type/Level reasoning pills in the placeholder/empty state — otherwise
    # they sit alone before analysis runs and falsely imply that ONLY these fields
    # involve model reasoning.
    has_real_data = str(disaster_scenario).strip().lower() == "yes"
    show_summary_reasoning = show_reasoning and has_real_data

    children: list[html.Div] = [html.Div(scene_summary, className="scene-summary-copy")]

    # key_observations are direct perception — render as a plain bulleted list, no marker.
    obs = [s for s in (key_observations or []) if s.strip()]
    if obs:
        children.append(
            html.Div(
                [html.Div("Observed", className="observation-label")]
                + [html.Div(f"• {note}", className="observation-bullet") for note in obs],
                className="observation-block",
            )
        )

    # Assumption / uncertainty toggles hide the whole note (pill + text), not just
    # the marker — these notes ARE the surfaced reasoning, so without them there is
    # no content worth keeping. The "reasoning" toggle behaves differently: it only
    # hides markers next to fields whose text is core content (rec.reason, quad, etc.).
    if show_assumption:
        for note in assumptions or []:
            children.append(reasoning_note(note, kind="assumption", show_pill=True))
    if show_uncertainty:
        for note in uncertainty_notes or []:
            children.append(reasoning_note(note, kind="uncertainty", show_pill=True))

    children.append(
        html.Div(
            [
                html.Div(
                    [html.Div("Scenario", className="summary-kicker"), html.Div(disaster_scenario, className="summary-value")],
                    className="summary-mini-card",
                ),
                html.Div(
                    [
                        html.Div(
                            [html.Span("Type", className="summary-kicker-text"), reasoning_pill("reasoning", visible=show_summary_reasoning)],
                            className="summary-kicker",
                        ),
                        html.Div(disaster_type, className="summary-value"),
                    ],
                    className="summary-mini-card",
                ),
                html.Div(
                    [
                        html.Div(
                            [html.Span("Level", className="summary-kicker-text"), reasoning_pill("reasoning", visible=show_summary_reasoning)],
                            className="summary-kicker",
                        ),
                        html.Div(str(disaster_level), className="summary-value"),
                    ],
                    className="summary-mini-card",
                ),
            ],
            className="summary-mini-grid",
        )
    )
    return children


def card(title: str, content_id: str, extra_class: str = "") -> html.Div:
    return html.Div(
        [html.Div(title, className="result-title"), html.Div(id=content_id, className="result-value")],
        className=f"result-card {extra_class}".strip(),
    )


def serve_layout():
    """Built per page-load so dynamic defaults (e.g. exports/latest_batch symlink)
    are resolved with current filesystem state, not at import time."""
    return html.Div(
    className="page",
    children=[
        html.Div(
            className="hero",
            children=[
                html.H1("Causal Explanation Evaluation+ (CEE+)"),
                html.P("Upload an image, add a caption, and prompt Qwen2.5-VL to assess the scene with object boxes."),
            ],
        ),
        html.Div(
            className="grid",
            children=[
                html.Div(
                    className="panel input-panel",
                    children=[
                        html.Label("Image Upload", className="field-label"),
                        dcc.Upload(
                            id="image-upload",
                            className="upload-box",
                            children=html.Div(["Drag and drop an image here, or ", html.Span("browse")]),
                            multiple=False,
                            accept="image/*",
                        ),
                        html.Img(id="image-preview", className="image-preview"),
                        html.Label("Caption", className="field-label"),
                        dcc.Textarea(
                            id="caption-input",
                            className="text-area",
                            placeholder="Describe the scene or paste the caption here...",
                        ),
                        html.Label("Prompt", className="field-label"),
                        dcc.Textarea(id="prompt-input", className="text-area prompt-area", value=DEFAULT_PROMPT),
                        dcc.Checklist(
                            id="allow-inferred-entities",
                            options=[
                                {
                                    "label": " Allow inferred entities (presumed occupants, off-camera agents)",
                                    "value": "on",
                                }
                            ],
                            value=[],
                            className="inferred-toggle",
                        ),
                        html.Label("Reasoning markers", className="field-label small-field-label"),
                        dcc.Checklist(
                            id="pill-visibility",
                            options=[
                                {"label": " Reasoning", "value": "reasoning"},
                                {"label": " Assumption", "value": "assumption"},
                                {"label": " Uncertainty", "value": "uncertainty"},
                            ],
                            value=["reasoning", "assumption", "uncertainty"],
                            className="pill-toggle",
                            inline=True,
                        ),
                        html.Div(
                            [
                                html.Button("Analyze Scene", id="analyze-button", className="analyze-button primary-button"),
                                html.Button("Export Structured Response", id="export-button", className="analyze-button secondary-button"),
                            ],
                            className="action-row",
                        ),
                        html.Div(id="status-message", className="status-message"),
                        html.Div(id="export-status", className="export-status"),
                    ],
                ),
                html.Div(
                    className="panel result-panel",
                    children=[
                        html.H2("Structured Assessment"),
                        dcc.Tabs(
                            id="result-tabs",
                            value="tab-pre",
                            className="result-tabs",
                            children=[
                                dcc.Tab(
                                    label="1. Scene Analysis",
                                    value="tab-pre",
                                    children=[
                                        html.Div(
                                            className="result-stack",
                                            children=[
                                                html.Div(
                                                    className="result-row",
                                                    children=[card("Baseline Trust", "pre-trust-card", "wide full-row")],
                                                ),
                                                html.Div(
                                                    className="result-row",
                                                    children=[card("External Validation vs Verified GT (Test 1)", "gt-validation-card", "wide full-row")],
                                                ),
                                                html.Div(
                                                    className="result-row",
                                                    children=[card("Detected Objects", "detected-objects", "detected-wide full-row")],
                                                ),
                                                html.Div(
                                                    className="summary-row",
                                                    children=[card("Scene Assessment", "scene-summary", "compact full-row")],
                                                ),
                                                html.Div(
                                                    className="result-row",
                                                    children=[card("Threats", "threatening-objects", "wide full-row")],
                                                ),
                                                html.Div(
                                                    className="result-row",
                                                    children=[card("Recommendations", "recommendations", "wide full-row")],
                                                ),
                                                html.Div(
                                                    className="result-row",
                                                    children=[card("Causal Graph A — derived from recommendations", "graph-a-card", "wide full-row")],
                                                ),
                                                html.Div(
                                                    className="result-row",
                                                    children=[card("Causal Graph B — VLM-generated (Prompt 2)", "graph-b-card", "wide full-row")],
                                                ),
                                                html.Div(
                                                    className="result-row",
                                                    children=[card("Pre Internal Alignment", "pre-internal-alignment-card", "wide full-row")],
                                                ),
                                                html.Div(
                                                    className="result-row",
                                                    children=[card("A ↔ B Consistency", "graph-consistency-card", "wide full-row")],
                                                ),
                                            ],
                                        ),
                                    ],
                                ),
                                dcc.Tab(
                                    label="2. Batch Profile",
                                    value="tab-report",
                                    children=[
                                        html.Div(
                                            className="result-stack",
                                            children=[
                                                html.Div(
                                                    [
                                                        html.Div("Pre-Intervention Report", className="result-title"),
                                                        html.Div(
                                                            "Mode",
                                                            className="report-control-label",
                                                        ),
                                                        dcc.RadioItems(
                                                            id="report-mode",
                                                            options=[
                                                                {"label": " From existing runs", "value": "existing"},
                                                                {"label": " Run new batch", "value": "batch"},
                                                            ],
                                                            value="existing",
                                                            className="report-mode-radio",
                                                        ),
                                                        # Mode A controls
                                                        html.Div(
                                                            [
                                                                html.Label("Runs folder (defaults to latest batch)", className="field-label small-field-label"),
                                                                dcc.Input(
                                                                    id="report-folder",
                                                                    type="text",
                                                                    value=str((EXPORT_ROOT / "latest_batch") if (EXPORT_ROOT / "latest_batch").exists() else EXPORT_ROOT),
                                                                    className="report-folder-input",
                                                                    debounce=False,
                                                                ),
                                                                html.Div(
                                                                    [
                                                                        html.Button(
                                                                            "Generate Report",
                                                                            id="generate-report-button",
                                                                            className="analyze-button primary-button report-generate-button",
                                                                        ),
                                                                    ],
                                                                    className="action-row",
                                                                ),
                                                            ],
                                                            id="report-mode-existing-controls",
                                                        ),
                                                        # Mode B controls
                                                        html.Div(
                                                            [
                                                                html.Label("Images folder", className="field-label small-field-label"),
                                                                html.Div(
                                                                    [
                                                                        dcc.Input(
                                                                            id="batch-images-folder",
                                                                            type="text",
                                                                            value=str((Path(__file__).resolve().parent / "experiments")),
                                                                            className="report-folder-input batch-folder-input",
                                                                        ),
                                                                        html.Button(
                                                                            "Browse…",
                                                                            id="folder-browse-toggle",
                                                                            className="folder-browse-button",
                                                                            n_clicks=0,
                                                                        ),
                                                                    ],
                                                                    className="batch-folder-row",
                                                                ),
                                                                # Folder browser panel (toggled open/close)
                                                                html.Div(
                                                                    [
                                                                        html.Div(
                                                                            [
                                                                                html.Button("⬆ Parent", id="folder-up-button", className="folder-nav-button"),
                                                                                html.Div(id="folder-browser-path", className="folder-browser-path"),
                                                                            ],
                                                                            className="folder-browser-header",
                                                                        ),
                                                                        html.Div(id="folder-browser-summary", className="folder-browser-summary"),
                                                                        html.Div(id="folder-browser-list", className="folder-browser-list"),
                                                                        html.Button(
                                                                            "Use this folder",
                                                                            id="folder-use-button",
                                                                            className="folder-use-button",
                                                                            n_clicks=0,
                                                                        ),
                                                                    ],
                                                                    id="folder-browser-panel",
                                                                    style={"display": "none"},
                                                                    className="folder-browser-panel",
                                                                ),
                                                                # Browser current-path state
                                                                dcc.Store(
                                                                    id="folder-browser-state",
                                                                    data={"path": str((Path(__file__).resolve().parent / "experiments"))},
                                                                ),
                                                                dcc.Checklist(
                                                                    id="batch-options",
                                                                    options=[
                                                                        {"label": " Use sidecar caption files (image.jpg + image.txt)", "value": "sidecar"},
                                                                        {"label": " Allow inferred entities (presumed occupants, off-camera agents)", "value": "inferred"},
                                                                    ],
                                                                    value=[],
                                                                    className="batch-options-checklist",
                                                                ),
                                                                html.Div(
                                                                    "Subfolders are walked recursively — point at a parent folder to batch across all categories, or a specific subfolder for one type.",
                                                                    className="batch-help-text",
                                                                ),
                                                                html.Div(
                                                                    [
                                                                        html.Button(
                                                                            "Start Batch",
                                                                            id="start-batch-button",
                                                                            className="analyze-button primary-button report-generate-button",
                                                                        ),
                                                                    ],
                                                                    className="action-row",
                                                                ),
                                                                # Live progress
                                                                html.Div(id="batch-progress", className="batch-progress"),
                                                            ],
                                                            id="report-mode-batch-controls",
                                                            style={"display": "none"},
                                                        ),
                                                        html.Div(id="report-status", className="report-status"),
                                                        # Hidden interval that fires while a batch is active
                                                        dcc.Interval(
                                                            id="batch-interval",
                                                            interval=1500,
                                                            disabled=True,
                                                            n_intervals=0,
                                                        ),
                                                    ],
                                                    className="result-card wide full-row",
                                                ),
                                                html.Div(
                                                    className="result-row",
                                                    children=[
                                                        html.Div(
                                                            [
                                                                html.Div(id="report-content", className="result-value"),
                                                            ],
                                                            className="result-card wide full-row report-content-card",
                                                        ),
                                                    ],
                                                ),
                                            ],
                                        ),
                                    ],
                                ),
                                dcc.Tab(
                                    label="3. Intervention",
                                    value="tab-intervention",
                                    children=[
                                        html.Div(
                                            className="result-stack",
                                            children=[
                                                html.Div(
                                                    className="result-row",
                                                    children=[card("Suppression Candidates", "suppression-card", "wide full-row")],
                                                ),
                                                html.Div(
                                                    className="result-row",
                                                    children=[
                                                        html.Div(
                                                            [
                                                                html.Div("Modality (placeholder)", className="result-title"),
                                                                html.Div(
                                                                    "Counterfactual image upload, modality selector, and Apply Intervention will land in a later round.",
                                                                    className="empty-state",
                                                                ),
                                                            ],
                                                            className="result-card wide full-row",
                                                        ),
                                                    ],
                                                ),
                                            ],
                                        ),
                                    ],
                                ),
                                dcc.Tab(
                                    label="4. Post-Intervention",
                                    value="tab-post",
                                    children=[
                                        html.Div(
                                            "Post-intervention analysis will appear here once the intervention pipeline lands.",
                                            className="empty-state tab-placeholder",
                                        ),
                                    ],
                                ),
                                dcc.Tab(
                                    label="5. Shift",
                                    value="tab-shift",
                                    children=[
                                        html.Div(
                                            "Shift signals (graph, recommendations, threats, scene) and CEE+ score will appear here.",
                                            className="empty-state tab-placeholder",
                                        ),
                                    ],
                                ),
                                dcc.Tab(
                                    label="Validation: Ground Truth",
                                    value="tab-ground-truth",
                                    children=[
                                        html.Div(
                                            className="result-stack",
                                            children=[
                                                html.Div(
                                                    [
                                                        html.Div("Ground Truth Annotation", className="result-title"),
                                                        html.Div(
                                                            "Load candidate causal graphs (generated externally) and verify them. Verified files become the reference for Test 1 (Ground Truth Comparison).",
                                                            className="card-subtext card-subtitle",
                                                        ),
                                                        html.Label("Candidates folder", className="field-label small-field-label"),
                                                        dcc.Input(
                                                            id="gt-folder",
                                                            type="text",
                                                            value=str(GT_CANDIDATES_DIR),
                                                            className="report-folder-input",
                                                        ),
                                                        html.Div(
                                                            [html.Button("Load Candidates", id="gt-load-button", className="analyze-button primary-button report-generate-button")],
                                                            className="action-row",
                                                        ),
                                                        dcc.Checklist(
                                                            id="gt-allow-inferred",
                                                            options=[{"label": " Show inferred entities (off-frame fire, presumed occupants, etc.)", "value": "allow"}],
                                                            value=["allow"],
                                                            className="batch-options-checklist",
                                                        ),
                                                        html.Div(id="gt-status", className="report-status"),
                                                    ],
                                                    className="result-card wide full-row",
                                                ),
                                                html.Div(
                                                    [
                                                        html.Div("Candidate navigation", className="result-title"),
                                                        html.Div(id="gt-position-info", className="gt-position-info"),
                                                        html.Div(
                                                            [
                                                                html.Button("◀ Prev", id="gt-prev-button", className="folder-nav-button gt-pager-button", n_clicks=0),
                                                                html.Button("Next ▶", id="gt-next-button", className="folder-nav-button gt-pager-button", n_clicks=0),
                                                                html.Span("Filter:", className="gt-filter-label"),
                                                                dcc.RadioItems(
                                                                    id="gt-filter",
                                                                    options=[
                                                                        {"label": " All", "value": "all"},
                                                                        {"label": " Pending", "value": "pending"},
                                                                        {"label": " Verified", "value": "verified"},
                                                                    ],
                                                                    value="all",
                                                                    className="gt-filter-radio",
                                                                    inline=True,
                                                                ),
                                                                html.Button("⇥ Next pending", id="gt-jump-pending-button", className="folder-nav-button gt-pager-button", n_clicks=0),
                                                            ],
                                                            className="gt-pager-controls",
                                                        ),
                                                    ],
                                                    className="result-card wide full-row",
                                                ),
                                                html.Div(
                                                    [
                                                        html.Div("Selected candidate", className="result-title"),
                                                        html.Div(id="gt-detail-view", className="result-value"),
                                                    ],
                                                    className="result-card wide full-row gt-detail-card",
                                                ),
                                                dcc.Store(id="gt-selected-path", data=""),
                                                dcc.Store(id="gt-working-state", data={}),
                                                dcc.Store(id="gt-refresh-tick", data=0),
                                            ],
                                        ),
                                    ],
                                ),
                                dcc.Tab(
                                    label="Validation: Tests",
                                    value="tab-tests",
                                    children=[
                                        html.Div(
                                            className="result-stack",
                                            children=[
                                                html.Div(
                                                    [
                                                        html.Div("Test 1 — Ground Truth Comparison", className="result-title"),
                                                        html.Div(
                                                            "Compares Graph A and Graph B against verified GT references. "
                                                            "A-correctness/B-correctness = recall against GT. A-precision/B-precision = how much of A/B is in GT. "
                                                            "External-validation anchor for the framework's metrics.",
                                                            className="card-subtext card-subtitle",
                                                        ),
                                                        html.Details(
                                                            [
                                                                html.Summary(
                                                                    "What is Test 1 and how to read it? (click to expand)",
                                                                    className="gt-val-explainer-summary",
                                                                ),
                                                                html.Div(
                                                                    [
                                                                        html.P([
                                                                            html.B("What: "),
                                                                            "An ", html.B("aggregate"), " version of the per-image External Validation card on Scene Analysis. ",
                                                                            "Given a batch of runs AND a folder of verified GT files, we match each run to its GT by image filename, compare graphs at three tiers (strict / soft / topological), and report median scores across the matched pairs.",
                                                                        ]),
                                                                        html.P([
                                                                            html.B("Why: "),
                                                                            "A single-image comparison can be a fluke. The aggregate verdict is what tells us whether the VLM systematically agrees with the reference, or systematically diverges. ",
                                                                            "This is the load-bearing 'external validation' number for the paper — the headline answer to ",
                                                                            html.I("'does the model's causal reasoning match an independent observer's across this sample.'"),
                                                                        ]),
                                                                        html.P([
                                                                            html.B("Reading the verdict tiers: "),
                                                                            html.B("Strict"), " expects verbatim ID match and is brittle. ",
                                                                            html.B("Soft"), " strips IDs and uses label-class + state-synonym matching — this is the number to cite. ",
                                                                            html.B("Topological"), " ignores state — pure structure. Big strict-to-soft jump is ID-drift noise, not real disagreement.",
                                                                        ]),
                                                                        html.P([
                                                                            html.B("Inputs: "),
                                                                            html.B("Verified GT folder"), " = where reference graphs live (default: exports/ground_truth/verified). ",
                                                                            html.B("Baseline batch folder"), " = the runs to test (default: exports/latest_batch — auto-points to your most recent batch). ",
                                                                            "Test 1 also runs automatically inside every new batch's report.",
                                                                        ], style={"fontStyle": "italic", "marginBottom": "0"}),
                                                                    ],
                                                                    className="gt-val-explainer-body",
                                                                ),
                                                            ],
                                                            className="gt-val-explainer",
                                                            style={"marginBottom": "10px"},
                                                        ),
                                                        html.Label("Verified GT folder", className="field-label small-field-label"),
                                                        dcc.Input(
                                                            id="gtcmp-verified-folder",
                                                            type="text",
                                                            value=str(GT_VERIFIED_DIR),
                                                            className="report-folder-input",
                                                        ),
                                                        html.Label("Baseline batch folder (defaults to latest)", className="field-label small-field-label"),
                                                        dcc.Input(
                                                            id="gtcmp-batch-folder",
                                                            type="text",
                                                            value=str((EXPORT_ROOT / "latest_batch") if (EXPORT_ROOT / "latest_batch").exists() else EXPORT_ROOT),
                                                            className="report-folder-input",
                                                        ),
                                                        html.Div(
                                                            [html.Button("Run Test 1", id="gtcmp-run-button", className="analyze-button primary-button report-generate-button")],
                                                            className="action-row",
                                                        ),
                                                        html.Div(id="gtcmp-status", className="report-status"),
                                                        html.Div(id="gtcmp-results", className="result-value"),
                                                        html.Div(id="gtcmp-detail", className="gtcmp-detail-container"),
                                                        dcc.Store(id="gtcmp-selected-pair", data={}),
                                                        dcc.Store(id="gtcmp-batch-folder-state", data=""),
                                                    ],
                                                    className="result-card wide full-row",
                                                ),
                                                html.Div(
                                                    [
                                                        html.Div("Test 2 — Prompt Sensitivity", className="result-title"),
                                                        html.Div(
                                                            "Re-runs Prompt 2 under multiple phrasings on a sample of existing runs. Measures how much A-fidelity / B-coverage move across variants. Median spread > 0.20 = metric is prompt-design-dependent.",
                                                            className="card-subtext card-subtitle",
                                                        ),
                                                        html.Details(
                                                            [
                                                                html.Summary(
                                                                    "What is Test 2 and why does it matter? (click to expand)",
                                                                    className="gt-val-explainer-summary",
                                                                ),
                                                                html.Div(
                                                                    [
                                                                        html.P([
                                                                            html.B("What: "),
                                                                            "We take a sample of existing runs and re-run Prompt 2 (the Graph B prompt) ",
                                                                            html.B("under multiple phrasings"),
                                                                            " — same scene, same image, same instructions, just reworded. For each image we then measure how much the resulting A-fidelity / B-coverage / topological-consistency numbers move across phrasings.",
                                                                        ]),
                                                                        html.P([
                                                                            html.B("Why: "),
                                                                            "An evaluation metric is only as trustworthy as its stability. If A-fidelity drops from 0.80 to 0.20 just because we reworded the prompt slightly, then ",
                                                                            html.I("we're measuring the prompt, not the model"),
                                                                            ". Test 2 makes the prompt-design dependence explicit before we use the metric to make claims about Qwen.",
                                                                        ]),
                                                                        html.P([
                                                                            html.B("Reading the verdict: "),
                                                                            "Headline number is ",
                                                                            html.B("median per-image A-fidelity spread"),
                                                                            " (max − min across variants). ",
                                                                            html.B("≤ 0.10"),
                                                                            " = prompt-stable, Stage 1 can proceed. ",
                                                                            html.B("0.10–0.20"),
                                                                            " = partially stable, report shift results with caveats. ",
                                                                            html.B("> 0.20"),
                                                                            " = heavily prompt-sensitive, reconsider Prompt 2 design before going further.",
                                                                        ]),
                                                                        html.P([
                                                                            html.B("Inputs: "),
                                                                            html.B("Batch folder"), " = sample source (latest batch by default). ",
                                                                            html.B("Sample size"), " = how many images to test (smaller = faster but less stable). ",
                                                                            html.B("Variants"), " = which prompt phrasings to include (the more variants, the more statistical power but the longer it takes). ",
                                                                            "Output is saved to exports/tests/prompt_sensitivity_<ts>/ and the latest verdict feeds into subsequent batch reports.",
                                                                        ], style={"fontStyle": "italic", "marginBottom": "0"}),
                                                                    ],
                                                                    className="gt-val-explainer-body",
                                                                ),
                                                            ],
                                                            className="gt-val-explainer",
                                                            style={"marginBottom": "10px"},
                                                        ),
                                                        html.Label("Batch folder (defaults to latest batch)", className="field-label small-field-label"),
                                                        dcc.Input(
                                                            id="psens-batch-folder",
                                                            type="text",
                                                            value=str((EXPORT_ROOT / "latest_batch") if (EXPORT_ROOT / "latest_batch").exists() else EXPORT_ROOT),
                                                            className="report-folder-input",
                                                        ),
                                                        html.Label("Sample size", className="field-label small-field-label"),
                                                        dcc.Input(
                                                            id="psens-sample-size",
                                                            type="number",
                                                            value=10,
                                                            min=2,
                                                            max=50,
                                                            className="report-folder-input",
                                                            style={"maxWidth": "120px"},
                                                        ),
                                                        html.Label("Variants to include", className="field-label small-field-label"),
                                                        dcc.Checklist(
                                                            id="psens-variants",
                                                            options=[
                                                                {"label": f" {info['name']}", "value": vid}
                                                                for vid, info in PROMPT2_VARIANTS.items()
                                                            ],
                                                            value=list(PROMPT2_VARIANTS.keys()),
                                                            className="batch-options-checklist",
                                                        ),
                                                        html.Div(
                                                            [html.Button("Start Test 2", id="psens-start-button", className="analyze-button primary-button report-generate-button")],
                                                            className="action-row",
                                                        ),
                                                        html.Div(id="psens-progress", className="batch-progress"),
                                                        html.Div(id="psens-status", className="report-status"),
                                                        dcc.Interval(id="psens-interval", interval=1500, disabled=True, n_intervals=0),
                                                    ],
                                                    className="result-card wide full-row",
                                                ),
                                                html.Div(
                                                    [
                                                        html.Div("Results", className="result-title"),
                                                        html.Div(id="psens-results", className="result-value"),
                                                    ],
                                                    className="result-card wide full-row",
                                                ),
                                            ],
                                        ),
                                    ],
                                ),
                            ],
                        ),
                    ],
                ),
            ],
        ),
        dcc.Store(id="analysis-store", data=PLACEHOLDER_RESULT),
    ],
)

app.layout = serve_layout

app.index_string = """<!DOCTYPE html>
<html>
    <head>
        {%metas%}
        <title>Disaster Response Recommender</title>
        {%favicon%}
        {%css%}
        <style>
            body {
                margin: 0;
                font-family: "Segoe UI", Helvetica, Arial, sans-serif;
                background:
                    radial-gradient(circle at top left, rgba(255, 165, 0, 0.28), transparent 32%),
                    linear-gradient(160deg, #f3efe5 0%, #e8edf3 52%, #dfe8dc 100%);
                color: #1f2933;
            }
            .page {
                min-height: 100vh;
                padding: 32px;
            }
            .hero {
                max-width: 900px;
                margin-bottom: 24px;
            }
            .hero h1 {
                margin-bottom: 8px;
                font-size: 2.4rem;
            }
            .hero p {
                margin: 0;
                font-size: 1rem;
                color: #435466;
            }
            .grid {
                display: grid;
                grid-template-columns: minmax(320px, 460px) minmax(0, 1fr);
                gap: 24px;
                align-items: start;
            }
            .panel {
                background: rgba(255, 255, 255, 0.82);
                backdrop-filter: blur(12px);
                border: 1px solid rgba(31, 41, 51, 0.08);
                border-radius: 20px;
                padding: 24px;
                box-shadow: 0 20px 50px rgba(31, 41, 51, 0.10);
            }
            .field-label {
                display: block;
                margin: 16px 0 8px;
                font-weight: 600;
            }
            .upload-box {
                border: 2px dashed #d97904;
                border-radius: 16px;
                padding: 28px 16px;
                text-align: center;
                background: rgba(255, 247, 237, 0.9);
                color: #7c2d12;
                cursor: pointer;
            }
            .upload-box span {
                text-decoration: underline;
            }
            .image-preview {
                display: block;
                width: 100%;
                margin-top: 16px;
                border-radius: 16px;
                object-fit: cover;
                max-height: 340px;
                background: rgba(255, 255, 255, 0.65);
            }
            .text-area {
                width: 100%;
                min-height: 120px;
                resize: vertical;
                border: 1px solid #ced6de;
                border-radius: 14px;
                padding: 14px;
                box-sizing: border-box;
                font: inherit;
                background: rgba(255, 255, 255, 0.88);
            }
            .prompt-area {
                min-height: 300px;
            }
            .action-row {
                display: grid;
                grid-template-columns: 1fr;
                gap: 10px;
                margin-top: 18px;
            }
            .analyze-button {
                width: 100%;
                border: none;
                border-radius: 14px;
                padding: 14px 18px;
                font: inherit;
                font-weight: 700;
                cursor: pointer;
            }
            .primary-button {
                background: linear-gradient(135deg, #b45309, #ea580c);
                color: white;
            }
            .secondary-button {
                background: rgba(255, 255, 255, 0.78);
                color: #7c2d12;
                border: 1px solid rgba(124, 45, 18, 0.16);
            }
            .status-message {
                min-height: 24px;
                margin-top: 12px;
                color: #7c2d12;
                font-weight: 500;
            }
            .export-status {
                min-height: 24px;
                margin-top: 8px;
                color: #475569;
                font-size: 0.92rem;
            }
            .result-panel h2 {
                margin-top: 0;
                margin-bottom: 18px;
            }
            .result-stack {
                display: grid;
                gap: 16px;
            }
            .result-row {
                display: block;
            }
            .summary-row {
                display: block;
            }
            .result-card,
            .threat-card,
            .hazard-item,
            .recommendation-card {
                border-radius: 18px;
                padding: 18px;
                background: linear-gradient(180deg, rgba(255,255,255,0.92), rgba(243,239,229,0.88));
                border: 1px solid rgba(31, 41, 51, 0.08);
            }
            .result-card {
                min-height: 140px;
            }
            .result-card.compact {
                min-height: unset;
                height: auto;
            }
            .result-card.full-row {
                width: 100%;
            }
            .result-card.detected-wide {
                width: 100%;
            }
            .result-title {
                font-size: 0.92rem;
                font-weight: 700;
                margin-bottom: 10px;
                text-transform: uppercase;
                letter-spacing: 0.04em;
                color: #7c2d12;
            }
            .result-value {
                line-height: 1.5;
            }
            .result-value > * + * {
                margin-top: 12px;
            }
            .embedded-preview {
                display: block;
                width: min(420px, 48%);
                max-height: 280px;
                object-fit: cover;
                border-radius: 14px;
                background: rgba(255, 255, 255, 0.65);
            }
            .result-card.detected-wide .result-value {
                display: flex;
                gap: 16px;
                align-items: flex-start;
            }
            .detected-list {
                display: grid;
                gap: 10px;
                flex: 1;
            }
            .detected-row {
                display: flex;
                justify-content: space-between;
                gap: 12px;
                padding: 10px 12px;
                border-radius: 12px;
                background: rgba(255, 255, 255, 0.65);
                border: 1px solid rgba(31, 41, 51, 0.06);
            }
            .detected-name {
                font-weight: 700;
            }
            .detected-state,
            .hazard-state,
            .hazard-tooltip-state {
                color: #475569;
                font-size: 0.9rem;
            }
            .detected-meta {
                color: #5b6875;
                font-size: 0.92rem;
            }
            .scene-summary-copy {
                color: #334155;
                margin-bottom: 14px;
            }
            .summary-mini-grid {
                display: grid;
                grid-template-columns: repeat(3, minmax(0, 1fr));
                gap: 12px;
            }
            .summary-mini-card {
                padding: 12px 14px;
                border-radius: 14px;
                background: rgba(255, 255, 255, 0.7);
                border: 1px solid rgba(31, 41, 51, 0.06);
            }
            .summary-kicker {
                color: #5b6875;
                font-size: 0.82rem;
                font-weight: 700;
                text-transform: uppercase;
                letter-spacing: 0.04em;
                margin-bottom: 6px;
            }
            .summary-value {
                font-weight: 700;
                color: #1f2933;
            }
            .hazard-grid,
            .recommendation-grid,
            .threat-grid {
                display: grid;
                grid-template-columns: repeat(2, minmax(0, 1fr));
                gap: 14px;
            }
            .threat-thumb {
                width: 132px;
                min-width: 132px;
                height: 96px;
                object-fit: cover;
                border-radius: 14px;
                margin-bottom: 0;
            }
            .threat-label {
                font-weight: 700;
                margin-bottom: 0;
            }
            .threat-card {
                display: flex;
                gap: 12px;
                align-items: flex-start;
            }
            .hazard-copy {
                min-width: 0;
                flex: 1;
            }
            .hazard-head,
            .recommendation-links {
                display: flex;
                flex-wrap: wrap;
                gap: 8px;
                align-items: center;
                margin-bottom: 8px;
            }
            .recommendation-topline {
                display: flex;
                align-items: center;
                justify-content: space-between;
                gap: 12px;
                margin-bottom: 10px;
            }
            .hazard-item.threat {
                border-left: 6px solid #dc2626;
            }
            .hazard-item.risk {
                border-left: 6px solid #2563eb;
            }
            .hazard-name,
            .recommendation-action {
                font-weight: 700;
            }
            .hazard-meta,
            .threat-bbox,
            .empty-state,
            .recommendation-kicker {
                color: #5b6875;
                font-size: 0.92rem;
            }
            .recommendation-rank-badge {
                min-width: 34px;
                height: 34px;
                display: inline-flex;
                align-items: center;
                justify-content: center;
                border-radius: 999px;
                background: linear-gradient(135deg, #c2410c, #ea580c);
                color: white;
                font-weight: 800;
                font-size: 1rem;
                box-shadow: 0 8px 18px rgba(194, 65, 12, 0.2);
            }
            .hazard-reason,
            .recommendation-reason {
                color: #334155;
                margin-bottom: 8px;
            }
            .recommendation-action {
                font-size: 1.05rem;
                color: #111827;
                margin-bottom: 8px;
                line-height: 1.35;
            }
            .recommendation-reason {
                font-size: 0.95rem;
                color: #475569;
                margin-bottom: 10px;
            }
            .quad-grid {
                display: grid;
                grid-template-columns: repeat(4, minmax(0, 1fr));
                gap: 8px;
                margin-top: 8px;
            }
            .quad-item {
                padding: 8px 10px;
                border-radius: 10px;
                background: rgba(255, 255, 255, 0.6);
                border: 1px solid rgba(31, 41, 51, 0.06);
            }
            .quad-label {
                color: #5b6875;
                font-size: 0.68rem;
                font-weight: 700;
                text-transform: uppercase;
                letter-spacing: 0.04em;
                margin-bottom: 2px;
            }
            .quad-value {
                color: #1f2933;
                font-weight: 600;
                font-size: 0.82rem;
                word-break: break-word;
            }
            .detail-stack {
                display: grid;
                gap: 8px;
                margin-top: 10px;
            }
            .detail-item {
                padding-top: 8px;
                border-top: 1px solid rgba(31, 41, 51, 0.08);
            }
            .detail-label {
                color: #5b6875;
                font-size: 0.72rem;
                font-weight: 700;
                text-transform: uppercase;
                letter-spacing: 0.04em;
                margin-bottom: 4px;
            }
            .detail-value {
                color: #64748b;
                font-size: 0.88rem;
            }
            .pill {
                display: inline-flex;
                align-items: center;
                border-radius: 999px;
                padding: 4px 10px;
                font-size: 0.8rem;
                font-weight: 700;
            }
            .pill.threat {
                background: rgba(220, 38, 38, 0.12);
                color: #b91c1c;
            }
            .pill.affected {
                background: rgba(37, 99, 235, 0.12);
                color: #1d4ed8;
            }
            .pill.neutral {
                background: rgba(148, 163, 184, 0.18);
                color: #475569;
            }
            .hazard-pill-wrap {
                position: relative;
                display: inline-flex;
            }
            .interactive-pill {
                cursor: help;
            }
            .hazard-tooltip {
                position: absolute;
                left: 0;
                top: calc(100% + 10px);
                z-index: 20;
                width: 220px;
                padding: 10px;
                border-radius: 14px;
                background: rgba(255, 255, 255, 0.98);
                border: 1px solid rgba(31, 41, 51, 0.12);
                box-shadow: 0 18px 40px rgba(15, 23, 42, 0.18);
                opacity: 0;
                visibility: hidden;
                transform: translateY(4px);
                transition: opacity 140ms ease, transform 140ms ease, visibility 140ms ease;
            }
            .hazard-pill-wrap:hover .hazard-tooltip,
            .hazard-pill-wrap:focus-within .hazard-tooltip {
                opacity: 1;
                visibility: visible;
                transform: translateY(0);
            }
            .hazard-tooltip-image {
                width: 100%;
                aspect-ratio: 4 / 3;
                object-fit: cover;
                border-radius: 10px;
                margin-bottom: 8px;
            }
            .hazard-tooltip-meta {
                color: #5b6875;
                font-size: 0.78rem;
                line-height: 1.35;
            }
            .inferred-toggle {
                margin-top: 10px;
                color: #475569;
                font-size: 0.92rem;
            }
            .inferred-toggle label {
                display: inline-flex;
                align-items: center;
                gap: 6px;
                cursor: pointer;
            }
            .small-field-label {
                margin-top: 14px !important;
                margin-bottom: 6px !important;
                font-size: 0.86rem;
                font-weight: 600;
            }
            .pill-toggle {
                display: flex;
                flex-wrap: wrap;
                gap: 14px;
                color: #475569;
                font-size: 0.88rem;
            }
            .pill-toggle label {
                display: inline-flex;
                align-items: center;
                gap: 6px;
                cursor: pointer;
            }
            .reasoning-note {
                margin-top: 8px;
                padding: 8px 10px 8px 12px;
                border-left: 3px solid #94a3b8;
                background: rgba(148, 163, 184, 0.08);
                border-radius: 4px;
                font-size: 0.88rem;
                color: #334155;
                line-height: 1.4;
            }
            .reasoning-note-assumption {
                border-left-color: #8b5cf6;
                background: rgba(139, 92, 246, 0.08);
            }
            .reasoning-note-uncertainty {
                border-left-color: #f59e0b;
                background: rgba(245, 158, 11, 0.08);
            }
            .reasoning-note-observation {
                border-left-color: #14b8a6;
                background: rgba(20, 184, 166, 0.08);
            }
            .reasoning-note-reasoning {
                border-left-color: #6366f1;
                background: rgba(99, 102, 241, 0.08);
            }
            .reasoning-marker {
                display: inline-block;
                font-size: 0.66rem;
                font-weight: 700;
                text-transform: uppercase;
                letter-spacing: 0.06em;
                margin-right: 8px;
                padding: 2px 6px;
                border-radius: 999px;
                background: rgba(148, 163, 184, 0.18);
                color: #475569;
                vertical-align: middle;
            }
            .reasoning-marker-assumption {
                background: rgba(139, 92, 246, 0.16);
                color: #6d28d9;
            }
            .reasoning-marker-uncertainty {
                background: rgba(245, 158, 11, 0.16);
                color: #b45309;
            }
            .reasoning-marker-observation {
                background: rgba(20, 184, 166, 0.16);
                color: #0f766e;
            }
            .reasoning-marker-reasoning {
                background: rgba(99, 102, 241, 0.16);
                color: #4338ca;
            }
            .reasoning-note-text {
                vertical-align: middle;
            }
            .reasoning-inline-text {
                vertical-align: middle;
                margin-left: 4px;
            }
            .observation-block {
                margin-top: 8px;
                padding: 8px 10px 8px 12px;
                border-left: 3px solid #14b8a6;
                background: rgba(20, 184, 166, 0.06);
                border-radius: 4px;
                font-size: 0.88rem;
                color: #334155;
            }
            .observation-label {
                font-size: 0.66rem;
                font-weight: 700;
                text-transform: uppercase;
                letter-spacing: 0.06em;
                color: #0f766e;
                margin-bottom: 4px;
            }
            .observation-bullet {
                line-height: 1.45;
            }
            .quad-section {
                margin-top: 8px;
            }
            .quad-section-header {
                display: flex;
                align-items: center;
                gap: 8px;
                margin-bottom: 6px;
            }
            .quad-section-label {
                font-size: 0.7rem;
                font-weight: 700;
                text-transform: uppercase;
                letter-spacing: 0.05em;
                color: #5b6875;
            }
            .detail-label-row {
                display: flex;
                align-items: center;
                gap: 8px;
                margin-bottom: 4px;
            }
            .detail-label-text {
                color: #5b6875;
                font-size: 0.72rem;
                font-weight: 700;
                text-transform: uppercase;
                letter-spacing: 0.04em;
            }
            .summary-kicker-text {
                color: #5b6875;
                font-size: 0.82rem;
                font-weight: 700;
                text-transform: uppercase;
                letter-spacing: 0.04em;
            }
            /* Tabs */
            .result-tabs {
                margin-top: -8px;
                margin-bottom: 16px;
            }
            .tab-placeholder {
                padding: 32px;
                text-align: center;
            }
            /* Cytoscape graph card */
            .graph-container {
                background: rgba(255, 255, 255, 0.7);
                border-radius: 12px;
                padding: 6px;
                width: 100%;
                min-width: 0;
                max-width: 100%;
                box-sizing: border-box;
                overflow: hidden;
            }
            .graph-text-view {
                margin-top: 10px;
                padding: 9px 11px;
                border-radius: 10px;
                background: rgba(255, 255, 255, 0.68);
                border: 1px solid rgba(31, 41, 51, 0.08);
                color: #334155;
                font-size: 0.86rem;
            }
            .graph-text-view summary {
                cursor: pointer;
                font-weight: 700;
                color: #475569;
            }
            .graph-text-pre {
                margin: 10px 0 0;
                padding: 10px;
                border-radius: 8px;
                background: rgba(15, 23, 42, 0.06);
                color: #1f2933;
                overflow-x: auto;
                white-space: pre;
                font-size: 0.78rem;
                line-height: 1.45;
            }
            /* Containment overrides — prevent grid-track / cytoscape feedback loop
               where a child measures its container, sizes itself, then triggers
               a reflow that grows the container indefinitely. */
            .panel,
            .result-stack,
            .result-row,
            .summary-row,
            .result-card {
                min-width: 0;
                max-width: 100%;
                box-sizing: border-box;
            }
            .result-card.full-row,
            .result-card.detected-wide {
                width: 100%;
                min-width: 0;
                max-width: 100%;
                overflow: hidden;
            }
            .result-tabs,
            .result-tabs > div,
            .tab-content {
                min-width: 0;
                max-width: 100%;
            }
            /* Consistency panel */
            .consistency-panel {
                display: grid;
                gap: 14px;
            }
            .consistency-score-row {
                display: grid;
                grid-template-columns: repeat(4, minmax(0, 1fr));
                gap: 12px;
            }
            .consistency-score-card {
                padding: 12px 14px;
                border-radius: 12px;
                background: rgba(255, 255, 255, 0.78);
                border: 1px solid rgba(31, 41, 51, 0.08);
                text-align: center;
            }
            .consistency-score-label {
                font-size: 0.7rem;
                font-weight: 700;
                text-transform: uppercase;
                letter-spacing: 0.05em;
                color: #5b6875;
                margin-bottom: 4px;
            }
            .consistency-score-value {
                font-size: 1.4rem;
                font-weight: 800;
            }
            .score-high { color: #15803d; }
            .score-mid  { color: #b45309; }
            .score-low  { color: #b91c1c; }
            .gt-validation-panel {
                display: flex;
                flex-direction: column;
                gap: 10px;
            }
            .gt-val-row {
                grid-template-columns: repeat(2, minmax(0, 1fr)) !important;
            }
            .gt-val-card {
                padding: 10px 12px;
            }
            .gt-val-cells {
                display: grid;
                grid-template-columns: repeat(3, minmax(0, 1fr));
                gap: 8px;
                margin-top: 6px;
            }
            .gt-val-cell {
                display: flex;
                flex-direction: column;
                align-items: center;
                gap: 2px;
                padding: 6px 4px;
                border-radius: 8px;
                background: rgba(245, 247, 250, 0.7);
            }
            .gt-val-sub-label {
                font-size: 0.62rem;
                font-weight: 700;
                text-transform: uppercase;
                letter-spacing: 0.05em;
                color: #6b7785;
            }
            .gt-val-small {
                font-size: 1.05rem !important;
            }
            .gt-validation-empty {
                padding: 8px 4px;
            }
            .gt-val-explainer {
                border: 1px solid rgba(31, 41, 51, 0.1);
                border-radius: 10px;
                background: rgba(247, 244, 240, 0.6);
                padding: 8px 12px;
            }
            .gt-val-explainer-summary {
                cursor: pointer;
                font-weight: 600;
                color: #4a5562;
                font-size: 0.9rem;
                user-select: none;
            }
            .gt-val-explainer-summary:hover { color: #1f2933; }
            .gt-val-explainer[open] .gt-val-explainer-summary {
                margin-bottom: 8px;
                color: #1f2933;
            }
            .gt-val-explainer-body p {
                font-size: 0.85rem;
                line-height: 1.45;
                margin: 6px 0;
                color: #2c3640;
            }
            .gt-val-explainer-body p:first-child { margin-top: 0; }
            .diff-grid {
                display: grid;
                grid-template-columns: repeat(2, minmax(0, 1fr));
                gap: 12px;
                min-width: 0;
            }
            .diff-list {
                padding: 10px 12px;
                border-radius: 10px;
                background: rgba(255, 255, 255, 0.65);
                border: 1px solid rgba(31, 41, 51, 0.06);
                font-size: 0.86rem;
                min-width: 0;
                overflow-wrap: anywhere;
            }
            .diff-list-title {
                font-weight: 700;
                color: #1f2933;
                margin-bottom: 4px;
                font-size: 0.78rem;
                text-transform: uppercase;
                letter-spacing: 0.04em;
            }
            .diff-empty {
                color: #94a3b8;
                font-size: 0.84rem;
                font-style: italic;
            }
            .diff-help-text {
                color: #64748b;
                font-size: 0.78rem;
                line-height: 1.35;
                margin: -1px 0 5px;
            }
            .diff-ul {
                margin: 0;
                padding-left: 18px;
                color: #334155;
            }
            .diff-ul li {
                margin: 2px 0;
                line-height: 1.4;
                word-break: break-word;
            }
            .alignment-failures {
                display: grid;
                gap: 8px;
            }
            .alignment-note {
                color: #475569;
                font-size: 0.88rem;
                line-height: 1.4;
            }
            .alignment-note.muted {
                color: #64748b;
                font-size: 0.82rem;
            }
            .alignment-failure-list {
                margin-top: 2px;
            }
            .failure-type {
                font-weight: 800;
                color: #7f1d1d;
            }
            .failure-message {
                color: #334155;
            }
            /* Suppression panel */
            .suppression-panel {
                display: grid;
                gap: 12px;
            }
            .suppression-agreement-row {
                display: flex;
                align-items: center;
                gap: 8px;
                font-size: 0.92rem;
                color: #334155;
            }
            .suppression-agree-label {
                font-weight: 600;
            }
            .pill.agreement-yes {
                background: rgba(21, 128, 61, 0.16);
                color: #166534;
            }
            .pill.agreement-no {
                background: rgba(180, 83, 9, 0.16);
                color: #92400e;
            }
            .suppression-grid {
                display: grid;
                grid-template-columns: repeat(2, minmax(0, 1fr));
                gap: 14px;
                min-width: 0;
            }
            .suppression-column {
                padding: 12px 14px;
                background: rgba(255, 255, 255, 0.7);
                border-radius: 12px;
                border: 1px solid rgba(31, 41, 51, 0.06);
                min-width: 0;
                overflow-wrap: anywhere;
            }
            .suppression-section-title {
                font-size: 0.78rem;
                font-weight: 700;
                text-transform: uppercase;
                letter-spacing: 0.05em;
                color: #5b6875;
                margin-bottom: 8px;
            }
            .suppression-row {
                display: grid;
                grid-template-columns: 28px 1fr;
                column-gap: 8px;
                row-gap: 4px;
                padding: 6px 0;
                border-top: 1px solid rgba(31, 41, 51, 0.06);
                font-size: 0.88rem;
            }
            .suppression-row:first-of-type {
                border-top: none;
            }
            .suppression-rank {
                font-weight: 800;
                color: #475569;
            }
            .suppression-key {
                font-weight: 700;
                color: #1f2933;
                grid-column: 2;
            }
            .suppression-rationale {
                grid-column: 2;
                color: #5b6875;
                font-size: 0.84rem;
            }
            /* Baseline trust panel */
            .trust-panel {
                display: grid;
                grid-template-columns: minmax(260px, 340px) 1fr;
                gap: 14px;
                min-width: 0;
            }
            .trust-panel > .gt-val-explainer {
                /* span both columns so the collapsed explainer doesn't leave
                   a blank right cell next to the trust summary card */
                grid-column: 1 / -1;
            }
            .trust-summary-card,
            .trust-detail-card {
                padding: 14px 16px;
                border-radius: 12px;
                background: rgba(255, 255, 255, 0.72);
                border: 1px solid rgba(31, 41, 51, 0.08);
                min-width: 0;
            }
            .trust-label {
                font-size: 0.72rem;
                font-weight: 800;
                text-transform: uppercase;
                letter-spacing: 0.05em;
                color: #64748b;
                margin-bottom: 8px;
            }
            .trust-level {
                font-size: 1.6rem;
                font-weight: 850;
                line-height: 1.1;
            }
            .trust-score {
                margin-top: 6px;
                color: #475569;
                font-weight: 700;
            }
            .trust-summary-meaning-label {
                margin-top: 18px;
            }
            .trust-summary-meaning {
                margin-top: 0;
                margin-bottom: 0;
            }
            .trust-high { color: #15803d; }
            .trust-moderate { color: #b45309; }
            .trust-low { color: #b91c1c; }
            .trust-interpretation {
                color: #1f2933;
                font-weight: 700;
                margin-bottom: 6px;
            }
            .trust-rule-summary {
                color: #1f2933;
                font-size: 0.96rem;
                line-height: 1.45;
                margin-bottom: 10px;
            }
            .trust-use {
                color: #64748b;
                font-size: 0.84rem;
                margin-bottom: 8px;
            }
            .trust-formula {
                color: #475569;
                font-size: 0.82rem;
                line-height: 1.4;
                padding: 7px 9px;
                border-radius: 8px;
                background: rgba(100, 116, 139, 0.08);
                margin-bottom: 10px;
            }
            .trust-qualifiers {
                margin: 0 0 10px;
                padding-left: 18px;
                color: #334155;
                font-size: 0.9rem;
            }
            .trust-qualifiers li {
                margin: 2px 0;
                line-height: 1.4;
            }
            .trust-components {
                display: flex;
                flex-wrap: wrap;
                gap: 6px;
            }
            .trust-components-label {
                color: #64748b;
                font-size: 0.7rem;
                font-weight: 800;
                text-transform: uppercase;
                letter-spacing: 0.05em;
                margin: 8px 0 5px;
            }
            .trust-components-label-secondary {
                margin-top: 10px;
            }
            .trust-section-label {
                color: #475569;
                font-size: 0.74rem;
                font-weight: 800;
                text-transform: uppercase;
                letter-spacing: 0.06em;
                margin-bottom: 6px;
            }
            .trust-section-label-spaced {
                margin-top: 14px;
            }
            .trust-section-label-muted {
                color: #94a3b8;
            }
            .trust-meaning {
                color: #1f2933;
                font-size: 0.92rem;
                line-height: 1.45;
                padding: 10px 12px;
                background: rgba(100, 116, 139, 0.08);
                border-left: 3px solid #94a3b8;
                border-radius: 6px;
                margin-bottom: 4px;
            }
            .trust-issues-block {
                margin-top: 10px;
            }
            .trust-no-issues {
                color: #15803d;
                font-style: italic;
                font-size: 0.9rem;
            }
            .breakdown-table {
                display: grid;
                gap: 0;
                background: rgba(255, 255, 255, 0.65);
                border-radius: 8px;
                padding: 6px 10px;
                border: 1px solid rgba(31, 41, 51, 0.06);
                overflow-x: auto;
                min-width: 0;
            }
            .breakdown-row {
                display: grid;
                grid-template-columns: minmax(140px, 1.4fr) 50px 18px 50px 18px 70px minmax(140px, 1.6fr);
                column-gap: 8px;
                padding: 5px 0;
                border-top: 1px dashed rgba(148, 163, 184, 0.25);
                align-items: baseline;
                font-size: 0.86rem;
            }
            .breakdown-row:first-child { border-top: none; }
            .breakdown-header-row { border-top: none; padding-bottom: 4px; }
            .breakdown-header {
                color: #94a3b8;
                font-size: 0.66rem;
                font-weight: 700;
                text-transform: uppercase;
                letter-spacing: 0.05em;
            }
            .breakdown-name {
                color: #1f2933;
                font-weight: 700;
            }
            .breakdown-value, .breakdown-weight {
                font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
                color: #475569;
                text-align: right;
            }
            .breakdown-times, .breakdown-equals {
                text-align: center;
                color: #94a3b8;
            }
            .breakdown-contribution {
                font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
                color: #1f2933;
                font-weight: 700;
                text-align: right;
            }
            .breakdown-rationale {
                color: #64748b;
                font-size: 0.78rem;
                line-height: 1.35;
            }
            .breakdown-total-row {
                border-top: 2px solid rgba(31, 41, 51, 0.2);
                padding-top: 7px;
                margin-top: 2px;
            }
            .breakdown-total-name {
                color: #475569;
                font-weight: 800;
                text-transform: uppercase;
                font-size: 0.74rem;
                letter-spacing: 0.05em;
            }
            .breakdown-total-value {
                font-size: 1rem;
            }
            /* Report tab */
            .report-mode-radio {
                margin: 6px 0 12px;
                color: #475569;
                font-size: 0.92rem;
            }
            .report-mode-radio label {
                display: inline-flex;
                align-items: center;
                gap: 6px;
                margin-right: 16px;
                cursor: pointer;
            }
            .report-control-label {
                font-size: 0.78rem;
                font-weight: 700;
                text-transform: uppercase;
                letter-spacing: 0.05em;
                color: #5b6875;
                margin-top: 4px;
                margin-bottom: 4px;
            }
            .report-folder-input {
                width: 100%;
                padding: 10px 12px;
                border: 1px solid #ced6de;
                border-radius: 10px;
                font: inherit;
                font-size: 0.9rem;
                background: rgba(255, 255, 255, 0.88);
                box-sizing: border-box;
            }
            .report-status {
                margin-top: 10px;
                color: #475569;
                font-size: 0.9rem;
            }
            .report-content-card {
                margin-top: 16px;
            }
            .batch-options-checklist {
                margin-top: 8px;
                color: #475569;
                font-size: 0.92rem;
            }
            .batch-options-checklist label {
                display: flex;
                align-items: center;
                gap: 6px;
                cursor: pointer;
                margin: 4px 0;
            }
            .batch-help-text {
                margin-top: 8px;
                color: #64748b;
                font-size: 0.84rem;
                line-height: 1.4;
            }
            .batch-folder-row {
                display: grid;
                grid-template-columns: 1fr auto;
                gap: 8px;
                align-items: stretch;
            }
            .batch-folder-input {
                width: 100%;
                min-width: 0;
            }
            .folder-browse-button {
                padding: 8px 14px;
                border-radius: 10px;
                border: 1px solid rgba(124, 45, 18, 0.16);
                background: rgba(255, 255, 255, 0.78);
                color: #7c2d12;
                font-weight: 700;
                cursor: pointer;
                white-space: nowrap;
            }
            .folder-browse-button:hover {
                background: rgba(255, 247, 237, 0.95);
            }
            .folder-browser-panel {
                margin-top: 10px;
                padding: 12px;
                background: rgba(248, 250, 252, 0.85);
                border: 1px solid rgba(31, 41, 51, 0.10);
                border-radius: 12px;
            }
            .folder-browser-header {
                display: grid;
                grid-template-columns: auto 1fr;
                gap: 10px;
                align-items: center;
                margin-bottom: 8px;
            }
            .folder-nav-button {
                padding: 6px 10px;
                border-radius: 8px;
                border: 1px solid rgba(31, 41, 51, 0.12);
                background: white;
                color: #1f2933;
                font-size: 0.86rem;
                font-weight: 600;
                cursor: pointer;
            }
            .folder-nav-button:hover {
                background: rgba(255, 247, 237, 0.95);
            }
            .folder-browser-path {
                font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
                color: #1f2933;
                font-size: 0.86rem;
                overflow-wrap: anywhere;
                padding: 6px 8px;
                background: rgba(255, 255, 255, 0.7);
                border-radius: 6px;
                border: 1px solid rgba(31, 41, 51, 0.06);
            }
            .folder-browser-summary {
                color: #475569;
                font-size: 0.82rem;
                margin-bottom: 8px;
            }
            .folder-browser-rows {
                display: grid;
                gap: 4px;
                max-height: 280px;
                overflow-y: auto;
                margin-bottom: 10px;
            }
            .folder-row-button {
                display: grid;
                grid-template-columns: auto 1fr auto;
                column-gap: 8px;
                align-items: center;
                padding: 8px 10px;
                border: 1px solid rgba(31, 41, 51, 0.06);
                background: rgba(255, 255, 255, 0.6);
                border-radius: 8px;
                cursor: pointer;
                text-align: left;
                font: inherit;
            }
            .folder-row-button:hover {
                background: rgba(255, 247, 237, 0.95);
                border-color: rgba(124, 45, 18, 0.20);
            }
            .folder-icon {
                color: #b45309;
            }
            .folder-name {
                color: #1f2933;
                font-weight: 600;
                overflow-wrap: anywhere;
            }
            .folder-count {
                color: #64748b;
                font-size: 0.82rem;
                white-space: nowrap;
            }
            .folder-browser-empty {
                color: #94a3b8;
                font-style: italic;
                font-size: 0.86rem;
                padding: 8px;
            }
            .folder-use-button {
                width: 100%;
                padding: 10px 14px;
                border: none;
                border-radius: 10px;
                background: linear-gradient(135deg, #b45309, #ea580c);
                color: white;
                font-weight: 700;
                cursor: pointer;
            }
            .batch-progress {
                margin-top: 14px;
                padding: 10px 12px;
                background: rgba(248, 250, 252, 0.85);
                border: 1px solid rgba(31, 41, 51, 0.10);
                border-radius: 10px;
            }
            .batch-progress-line {
                color: #1f2933;
                font-weight: 600;
                font-size: 0.92rem;
                margin-bottom: 6px;
            }
            .batch-progress-done {
                color: #15803d;
            }
            .batch-progress-bar-track {
                height: 10px;
                background: rgba(148, 163, 184, 0.15);
                border-radius: 999px;
                overflow: hidden;
                margin-bottom: 6px;
            }
            .batch-progress-bar-fill {
                height: 100%;
                background: linear-gradient(90deg, #ea580c, #b45309);
                border-radius: 999px;
                transition: width 200ms ease-out;
            }
            .batch-progress-errors {
                color: #64748b;
                font-size: 0.84rem;
            }
            .report-panel {
                display: grid;
                gap: 18px;
            }
            .report-header {
                display: flex;
                align-items: baseline;
                gap: 12px;
                flex-wrap: wrap;
            }
            .report-title {
                font-size: 1.25rem;
                font-weight: 800;
                color: #1f2933;
            }
            .report-subtitle {
                color: #64748b;
                font-size: 0.86rem;
            }
            .report-section {
                padding: 12px 14px;
                background: rgba(255, 255, 255, 0.7);
                border-radius: 12px;
                border: 1px solid rgba(31, 41, 51, 0.06);
            }
            .report-interpretation {
                background: rgba(248, 250, 252, 0.85);
                border: 1px solid rgba(31, 41, 51, 0.10);
            }
            .finding-row {
                padding: 10px 12px;
                margin-top: 8px;
                border-radius: 8px;
                border-left: 4px solid #94a3b8;
                background: rgba(255, 255, 255, 0.7);
            }
            .finding-row:first-of-type { margin-top: 0; }
            .finding-row-good     { border-left-color: #15803d; background: rgba(21, 128, 61, 0.04); }
            .finding-row-neutral  { border-left-color: #94a3b8; }
            .finding-row-warning  { border-left-color: #b45309; background: rgba(180, 83, 9, 0.05); }
            .finding-headline {
                font-weight: 700;
                color: #1f2933;
                font-size: 0.94rem;
                margin-bottom: 4px;
            }
            .finding-good     { color: #166534; }
            .finding-warning  { color: #92400e; }
            .finding-neutral  { color: #1f2933; }
            .finding-detail {
                color: #475569;
                font-size: 0.86rem;
                line-height: 1.45;
            }
            .report-section-label {
                font-size: 0.74rem;
                font-weight: 800;
                text-transform: uppercase;
                letter-spacing: 0.06em;
                color: #475569;
                margin-bottom: 10px;
            }
            .report-bar-row {
                display: grid;
                grid-template-columns: 110px 1fr 110px;
                gap: 10px;
                align-items: center;
                margin-bottom: 6px;
            }
            .report-bar-label {
                font-weight: 700;
                color: #1f2933;
                font-size: 0.92rem;
            }
            .report-bar-track {
                height: 14px;
                border-radius: 999px;
                background: rgba(148, 163, 184, 0.15);
                overflow: hidden;
                min-width: 0;
            }
            .report-bar-fill {
                height: 100%;
                border-radius: 999px;
            }
            .report-bar-count {
                color: #475569;
                font-size: 0.86rem;
                text-align: right;
            }
            .metric-row {
                display: grid;
                grid-template-columns: 160px 80px 120px 1fr 60px;
                column-gap: 10px;
                align-items: baseline;
                padding: 5px 0;
                border-top: 1px dashed rgba(148, 163, 184, 0.25);
                font-size: 0.86rem;
                min-width: 0;
            }
            .metric-row:first-of-type { border-top: none; }
            .metric-header-row { border-top: none; padding-bottom: 4px; }
            .metric-header {
                color: #94a3b8;
                font-size: 0.66rem;
                font-weight: 700;
                text-transform: uppercase;
                letter-spacing: 0.05em;
            }
            .metric-name {
                color: #1f2933;
                font-weight: 700;
            }
            .metric-value {
                font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
                color: #475569;
            }
            .metric-median { color: #1f2933; font-weight: 700; }
            .metric-iqr { color: #64748b; font-size: 0.82rem; }
            .metric-range { color: #94a3b8; font-size: 0.8rem; }
            .metric-n { color: #94a3b8; font-size: 0.8rem; text-align: right; }
            /* Ground Truth tab */
            .gt-row {
                display: grid;
                grid-template-columns: minmax(180px, 1fr) minmax(220px, 2fr) 140px 100px 130px;
                gap: 10px;
                padding: 8px 0;
                border-top: 1px dashed rgba(148, 163, 184, 0.25);
                align-items: center;
                font-size: 0.86rem;
            }
            .gt-row:first-of-type { border-top: none; }
            .gt-position-info {
                padding: 8px 12px;
                background: rgba(245, 247, 250, 0.7);
                border-radius: 8px;
                margin-top: 6px;
            }
            .gt-pos-line {
                display: flex;
                align-items: center;
                gap: 10px;
                flex-wrap: wrap;
                font-size: 0.95rem;
            }
            .gt-pos-counter { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-weight: 700; color: #1f2933; }
            .gt-pos-sep { color: #94a3b8; }
            .gt-pos-filename { color: #1f2933; font-weight: 600; word-break: break-all; }
            .gt-pos-status { padding: 2px 8px; border-radius: 999px; font-size: 0.75rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em; }
            .gt-pager-controls {
                display: flex;
                gap: 10px;
                align-items: center;
                flex-wrap: wrap;
                margin-top: 10px;
            }
            .gt-pager-button { padding: 6px 14px; font-weight: 600; }
            .gt-filter-label { color: #5b6875; font-size: 0.8rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em; margin-left: 6px; }
            .gt-filter-radio label { margin-right: 12px; cursor: pointer; }
            .gt-row-name { font-weight: 700; color: #1f2933; overflow-wrap: anywhere; }
            .gt-row-caption { color: #475569; overflow-wrap: anywhere; }
            .gt-row-meta { color: #64748b; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 0.8rem; }
            .gt-row-status {
                font-size: 0.74rem;
                font-weight: 700;
                text-transform: uppercase;
                letter-spacing: 0.05em;
                padding: 3px 8px;
                border-radius: 999px;
                text-align: center;
            }
            .gt-status-verified { background: rgba(21, 128, 61, 0.14); color: #166534; }
            .gt-status-unverified { background: rgba(148, 163, 184, 0.18); color: #475569; }
            .gt-detail { display: grid; gap: 12px; }
            .gt-detail-block { padding: 6px 0; }
            /* Side-by-side image + graph in the GT candidate viewer */
            .gt-image-graph-row {
                display: grid;
                grid-template-columns: minmax(0, 1fr) minmax(0, 1.4fr);
                gap: 14px;
                align-items: start;
            }
            .gt-image-graph-row .gt-detail-image { min-width: 0; }
            .gt-image-graph-row .gt-detail-image img { width: 100%; height: auto; max-height: 480px; object-fit: contain; }
            .gt-image-graph-row .gt-detail-graph { min-width: 0; min-height: 360px; }
            @media (max-width: 1100px) {
                .gt-image-graph-row { grid-template-columns: 1fr; }
            }
            /* Let dcc.Dropdown menus inside the GT editor render outside their
               containing card instead of being clipped. */
            .gt-detail-card { overflow: visible !important; }
            .gt-detail-card .gt-cell-dropdown { position: relative; }
            .gt-detail-card .gt-cell-dropdown .Select-menu-outer,
            .gt-detail-card .Select-menu-outer {
                z-index: 1000;
                position: absolute;
                width: auto;
                min-width: 100%;
                white-space: nowrap;
                background: #fff;
                border: 1px solid #ced6de;
                border-radius: 6px;
                box-shadow: 0 8px 24px rgba(15, 23, 42, 0.12);
                max-height: 280px;
                overflow-y: auto;
            }
            .gt-detail-card .gt-form-row { overflow: visible; }
            .gt-detail-card .gt-editor { overflow: visible; }
            .gt-edit-json {
                font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
                font-size: 0.8rem;
            }
            /* Test 1 detail view */
            .gtcmp-detail { margin-top: 18px; }
            .gtcmp-image-row {
                display: grid;
                grid-template-columns: minmax(220px, 1fr) minmax(220px, 280px);
                gap: 14px;
                margin: 10px 0;
            }
            .gtcmp-image-col img { max-height: 240px; }
            .gtcmp-legend {
                padding: 10px 12px;
                background: rgba(255, 255, 255, 0.6);
                border: 1px solid rgba(31, 41, 51, 0.08);
                border-radius: 10px;
                font-size: 0.86rem;
            }
            .gtcmp-legend-title {
                font-weight: 700;
                font-size: 0.76rem;
                text-transform: uppercase;
                letter-spacing: 0.05em;
                color: #5b6875;
                margin-bottom: 8px;
            }
            .gtcmp-legend-row {
                display: flex;
                align-items: center;
                gap: 8px;
                margin: 4px 0;
            }
            .gtcmp-legend-swatch {
                display: inline-block;
                width: 24px;
                height: 3px;
                border-radius: 2px;
            }
            .gtcmp-legend-match { background: #15803d; }
            .gtcmp-legend-soft { background: #84cc16; border-bottom: 1px dashed #84cc16; }
            .gtcmp-legend-topo { background: #eab308; border-bottom: 1px dashed #eab308; }
            .gtcmp-legend-miss { background: #b91c1c; border-bottom: 1px dashed #b91c1c; }
            .gtcmp-legend-gt { background: #475569; }
            .gtcmp-legend-text { color: #334155; }
            .gtcmp-graphs-row {
                display: grid;
                grid-template-columns: repeat(3, minmax(0, 1fr));
                gap: 12px;
                margin-top: 10px;
            }
            .gtcmp-graph-col { min-width: 0; }
            .gtcmp-graph-title {
                font-weight: 700;
                font-size: 0.86rem;
                color: #1f2933;
                margin-bottom: 6px;
                padding: 4px 8px;
                background: rgba(248, 250, 252, 0.85);
                border-radius: 6px;
            }
            .prr-row-with-action {
                grid-template-columns: 180px 50px 40px 40px 90px 90px 90px 90px 75px;
            }
            @media (max-width: 1200px) {
                .gtcmp-graphs-row { grid-template-columns: 1fr; }
                .gtcmp-image-row { grid-template-columns: 1fr; }
            }
            /* Structured GT editor */
            .gt-editor { display: grid; gap: 8px; margin-top: 14px; }
            .gt-section-header {
                display: flex;
                align-items: center;
                justify-content: space-between;
                margin-top: 16px;
                margin-bottom: 6px;
            }
            .gt-section-title {
                font-size: 0.78rem;
                font-weight: 800;
                text-transform: uppercase;
                letter-spacing: 0.05em;
                color: #5b6875;
            }
            .gt-form-row {
                display: grid;
                column-gap: 8px;
                align-items: center;
                padding: 4px 0;
                border-top: 1px dashed rgba(148, 163, 184, 0.20);
            }
            .gt-form-row:first-of-type { border-top: none; }
            .gt-node-row {
                grid-template-columns: minmax(120px, 1.1fr) minmax(100px, 1fr) minmax(150px, 1.4fr) 75px 75px 32px;
            }
            .gt-edge-row {
                grid-template-columns: minmax(120px, 1fr) minmax(120px, 1fr) minmax(150px, 1.4fr) minmax(120px, 1fr) 32px;
            }
            .gt-header-row {
                padding-bottom: 2px;
                border-top: none;
            }
            .gt-cell-header {
                font-size: 0.66rem;
                font-weight: 700;
                text-transform: uppercase;
                letter-spacing: 0.05em;
                color: #94a3b8;
            }
            .gt-cell-input {
                padding: 6px 8px;
                border: 1px solid #ced6de;
                border-radius: 6px;
                font: inherit;
                font-size: 0.86rem;
                background: white;
                box-sizing: border-box;
                width: 100%;
            }
            .gt-cell-dropdown {
                font-size: 0.86rem;
            }
            .gt-cell-dropdown .Select-control,
            .gt-cell-dropdown .Select-input {
                min-height: 32px;
                font-size: 0.86rem;
            }
            .gt-cell-checkbox label {
                display: inline-flex;
                align-items: center;
                cursor: pointer;
                gap: 4px;
            }
            .gt-row-delete {
                width: 28px;
                height: 28px;
                padding: 0;
                border-radius: 6px;
                border: 1px solid rgba(220, 38, 38, 0.2);
                background: rgba(255, 255, 255, 0.7);
                color: #b91c1c;
                font-weight: 700;
                font-size: 1rem;
                cursor: pointer;
                line-height: 1;
            }
            .gt-row-delete:hover {
                background: rgba(220, 38, 38, 0.08);
            }
            .cat-table {
                overflow-x: auto;
                min-width: 0;
            }
            .cat-row {
                display: grid;
                grid-template-columns: minmax(160px, 2fr) 50px 110px 90px 90px 110px 110px;
                column-gap: 10px;
                padding: 5px 0;
                border-top: 1px dashed rgba(148, 163, 184, 0.25);
                font-size: 0.86rem;
                align-items: baseline;
            }
            .cat-row:first-of-type { border-top: none; }
            .cat-header-row { border-top: none; padding-bottom: 4px; }
            .cat-header {
                color: #94a3b8;
                font-size: 0.66rem;
                font-weight: 700;
                text-transform: uppercase;
                letter-spacing: 0.05em;
            }
            .cat-cell { color: #475569; }
            .cat-name { color: #1f2933; font-weight: 700; overflow-wrap: anywhere; }
            .cat-numeric { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
            .failure-row {
                display: grid;
                grid-template-columns: 280px 1fr 50px;
                gap: 10px;
                align-items: center;
                margin-bottom: 5px;
                font-size: 0.86rem;
                min-width: 0;
            }
            .failure-name {
                font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
                color: #1f2933;
                font-size: 0.8rem;
                overflow-wrap: anywhere;
            }
            .failure-bar-track {
                height: 8px;
                border-radius: 999px;
                background: rgba(148, 163, 184, 0.15);
                overflow: hidden;
                min-width: 0;
            }
            .failure-bar-fill {
                height: 100%;
                background: #b45309;
                border-radius: 999px;
            }
            .failure-count {
                color: #475569;
                font-weight: 700;
                text-align: right;
            }
            .outlier-row {
                display: grid;
                grid-template-columns: 220px 1fr 80px;
                gap: 10px;
                padding: 5px 0;
                border-top: 1px dashed rgba(148, 163, 184, 0.25);
                font-size: 0.88rem;
            }
            .outlier-row:first-of-type { border-top: none; }
            .outlier-label {
                color: #1f2933;
                font-weight: 700;
            }
            .outlier-run {
                font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
                color: #5b6875;
                font-size: 0.82rem;
                overflow-wrap: anywhere;
            }
            .outlier-value {
                color: #475569;
                font-weight: 700;
                text-align: right;
            }
            .prr-table {
                margin-top: 8px;
                overflow-x: auto;
                min-width: 0;
            }
            .prr-row {
                display: grid;
                grid-template-columns: 220px 90px 60px 60px 60px 70px 60px 50px 60px;
                gap: 8px;
                padding: 4px 0;
                border-top: 1px dashed rgba(148, 163, 184, 0.18);
                font-size: 0.82rem;
            }
            .prr-row:first-of-type { border-top: none; }
            .prr-cell {
                font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
                color: #475569;
                overflow-wrap: anywhere;
            }
            .prr-id { color: #1f2933; font-weight: 600; }
            .prr-header {
                color: #94a3b8;
                font-size: 0.66rem;
                font-weight: 700;
                text-transform: uppercase;
                letter-spacing: 0.05em;
                font-family: inherit;
            }
            @media (max-width: 1100px) {
                .metric-row { grid-template-columns: 1fr 60px 80px; }
                .metric-range, .metric-n { display: none; }
                .failure-row { grid-template-columns: 1fr 50px; }
                .failure-bar-track { display: none; }
            }
            @media (max-width: 900px) {
                .breakdown-row {
                    grid-template-columns: 1fr 50px 50px 70px;
                    grid-template-areas:
                        "name      name      name      name"
                        "v-label   v-value   w-label   contrib"
                        "rationale rationale rationale rationale";
                }
                .breakdown-name { grid-area: name; }
                .breakdown-value { grid-area: v-value; }
                .breakdown-weight { grid-area: w-label; }
                .breakdown-contribution { grid-area: contrib; }
                .breakdown-times, .breakdown-equals { display: none; }
                .breakdown-rationale { grid-area: rationale; }
            }
            .trust-component {
                padding: 3px 8px;
                border-radius: 999px;
                background: rgba(100, 116, 139, 0.10);
                color: #475569;
                font-size: 0.76rem;
                font-weight: 700;
            }
            .trust-component-context {
                background: rgba(100, 116, 139, 0.06);
                color: #64748b;
            }
            /* Card subtitle / subtext — small explanatory blurb under labels */
            .card-subtext {
                color: #64748b;
                font-size: 0.78rem;
                line-height: 1.4;
                margin-top: 6px;
            }
            .card-subtitle {
                margin-bottom: 10px;
                margin-top: 0;
                padding-bottom: 8px;
                border-bottom: 1px dashed rgba(148, 163, 184, 0.3);
            }
            /* Coverage strip — sits under Graph A */
            .coverage-strip {
                margin-top: 10px;
                padding: 10px 12px;
                background: rgba(255, 255, 255, 0.55);
                border: 1px solid rgba(31, 41, 51, 0.06);
                border-radius: 10px;
            }
            .coverage-score-row {
                display: grid;
                grid-template-columns: 1fr;
            }
            .coverage-strip .consistency-score-card {
                background: transparent;
                border: none;
                padding: 0;
                text-align: left;
            }
            .orphan-row {
                margin-top: 8px;
                padding-top: 8px;
                border-top: 1px solid rgba(31, 41, 51, 0.05);
                font-size: 0.86rem;
                color: #334155;
            }
            .orphan-clean {
                color: #64748b;
                font-style: italic;
            }
            .orphan-label {
                font-weight: 700;
                color: #b91c1c;
                margin-right: 6px;
            }
            .orphan-list {
                color: #1f2933;
                overflow-wrap: anywhere;
            }
            /* Severity pills on alignment failures */
            .failure-pill {
                display: inline-block;
                font-size: 0.66rem;
                font-weight: 700;
                text-transform: uppercase;
                letter-spacing: 0.05em;
                padding: 2px 7px;
                border-radius: 999px;
                margin-right: 6px;
                vertical-align: middle;
            }
            .failure-pill-high {
                background: rgba(220, 38, 38, 0.14);
                color: #b91c1c;
            }
            .failure-pill-mid {
                background: rgba(245, 158, 11, 0.16);
                color: #b45309;
            }
            .failure-pill-low {
                background: rgba(148, 163, 184, 0.18);
                color: #475569;
            }
            .failure-pill-inline {
                margin-right: 2px;
                margin-left: 2px;
            }
            .alignment-failure-list .failure-type {
                font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
                font-size: 0.78rem;
                color: #1f2933;
                font-weight: 600;
            }
            .alignment-failure-list .failure-message {
                color: #475569;
                font-size: 0.85rem;
            }
            .failure-main-line {
                display: inline;
            }
            .failure-detail-line {
                margin: 3px 0 5px 0;
                padding-left: 0;
                color: #64748b;
                font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
                font-size: 0.76rem;
                line-height: 1.35;
                overflow-wrap: anywhere;
            }
            .suppression-vlm-row { grid-template-columns: 1fr; }
            .suppression-vlm-key { grid-column: 1; }
            .suppression-vlm-row .suppression-rationale { grid-column: 1; }
            @media (max-width: 1100px) {
                .consistency-score-row { grid-template-columns: 1fr; }
                .diff-grid { grid-template-columns: 1fr; }
                .suppression-grid { grid-template-columns: 1fr; }
                .trust-panel { grid-template-columns: 1fr; }
            }
            @media (max-width: 1100px) {
                .summary-mini-grid {
                    grid-template-columns: 1fr;
                }
                .hazard-grid,
                .recommendation-grid,
                .threat-grid,
                .quad-grid {
                    grid-template-columns: 1fr;
                }
            }
            @media (max-width: 900px) {
                .page {
                    padding: 18px;
                }
                .grid {
                    grid-template-columns: 1fr;
                }
                .result-card.detected-wide .result-value {
                    flex-direction: column;
                }
                .embedded-preview {
                    width: 100%;
                }
                .detected-row,
                .threat-card {
                    flex-direction: column;
                }
                .threat-thumb {
                    width: 100%;
                    height: auto;
                    aspect-ratio: 4 / 3;
                }
            }
        </style>
    </head>
    <body>
        {%app_entry%}
        <footer>
            {%config%}
            {%scripts%}
            {%renderer%}
        </footer>
    </body>
</html>"""


@app.callback(Output("image-preview", "src"), Input("image-upload", "contents"))
def update_preview(image_contents: str | None) -> str | None:
    return image_contents


@app.callback(
    Output("analysis-store", "data"),
    Output("status-message", "children"),
    Input("analyze-button", "n_clicks"),
    State("prompt-input", "value"),
    State("caption-input", "value"),
    State("image-upload", "contents"),
    State("image-upload", "filename"),
    State("allow-inferred-entities", "value"),
    prevent_initial_call=True,
)
def analyze_scene(
    n_clicks: int | None,
    prompt: str | None,
    caption: str | None,
    image_contents: str | None,
    image_filename: str | None,
    allow_inferred_value: list[str] | None,
) -> tuple[dict[str, Any], str]:
    if not n_clicks:
        raise dash.exceptions.PreventUpdate

    if not image_contents and not caption:
        return PLACEHOLDER_RESULT, "Add an image or caption before running analysis."

    allow_inferred = bool(allow_inferred_value and "on" in allow_inferred_value)
    try:
        result = query_qwen(
            prompt or DEFAULT_PROMPT, caption or "", image_contents, allow_inferred=allow_inferred
        )
        result["run_id"] = datetime.now().strftime("run_%Y%m%dT%H%M%S")
        result["image_filename"] = safe_filename(image_filename)
        result["allow_inferred"] = allow_inferred

        # Prompt 2: Graph B (independent VLM-generated causal graph).
        # Strict isolation: only detected_objects + threats are passed back, NOT recommendations.
        try:
            graph_b = query_qwen_graph_b(
                result["detected_objects"],
                result["threats"],
                caption or "",
                image_contents,
                allow_inferred=allow_inferred,
            )
            result["graph_b"] = graph_b
            # Re-derive consistency now that graph_b is populated.
            result["graph_consistency"] = compare_graphs(result["causal_graph"], graph_b)
            # Re-derive trust too — it was first computed against the empty placeholder.
            result["pre_intervention_trust"] = assess_pre_intervention_trust(
                result.get("pre_internal_alignment", {}),
                result["graph_consistency"],
                result["causal_graph"],
                graph_b,
            )
            status = "Analysis complete."
        except Exception as exc_b:
            result["graph_b"] = dict(PLACEHOLDER_RESULT["graph_b"])
            status = f"Analysis complete; Graph B extraction failed: {exc_b}"

        return result, status
    except Exception as exc:
        return PLACEHOLDER_RESULT, f"Analysis failed: {exc}"


@app.callback(
    Output("detected-objects", "children"),
    Output("scene-summary", "children"),
    Output("threatening-objects", "children"),
    Output("recommendations", "children"),
    Output("graph-a-card", "children"),
    Output("graph-b-card", "children"),
    Output("pre-internal-alignment-card", "children"),
    Output("graph-consistency-card", "children"),
    Output("pre-trust-card", "children"),
    Output("gt-validation-card", "children"),
    Output("suppression-card", "children"),
    Input("analysis-store", "data"),
    Input("pill-visibility", "value"),
    State("image-upload", "contents"),
)
def render_results(
    data: dict[str, Any], pill_visibility_value: list[str] | None, image_contents: str | None
):
    normalized = normalize_result(data, image_contents)

    selected = set(pill_visibility_value or [])
    pill_visibility = {
        "reasoning": "reasoning" in selected,
        "assumption": "assumption" in selected,
        "uncertainty": "uncertainty" in selected,
    }

    graph_a_view = html.Div(
        [
            html.Div(
                "Derived from recommendations.",
                className="card-subtext card-subtitle",
            ),
            make_causal_graph_viewer(normalized["causal_graph"], elem_id="cyto-graph-a"),
            make_graph_text_view(normalized["causal_graph"]),
            make_graph_coverage_strip(normalized["causal_graph"]),
        ],
        className="graph-a-stack",
    )
    graph_b_view = html.Div(
        [
            html.Div(
                "VLM-generated; recommendations withheld.",
                className="card-subtext card-subtitle",
            ),
            make_causal_graph_viewer(normalized["graph_b"], elem_id="cyto-graph-b"),
            make_graph_text_view(normalized["graph_b"]),
            make_graph_coverage_strip(normalized["graph_b"]),
        ],
        className="graph-b-stack",
    )
    pre_alignment_view = make_pre_internal_alignment_panel(normalized["pre_internal_alignment"])
    pre_trust_view = make_pre_intervention_trust_panel(normalized["pre_intervention_trust"])
    gt_validation_view = make_gt_validation_panel(normalized.get("gt_validation", {}))
    consistency_view = html.Div(
        [
            html.Div(
                "A = recommendation-derived graph. B = independent VLM graph. Gaps show where causal commitments diverge.",
                className="card-subtext card-subtitle",
            ),
            make_consistency_panel(normalized["graph_consistency"]),
        ],
    )
    suppression_view = html.Div(
        [
            html.Div(
                "Framework pick vs VLM pick. Disagreement is a signal.",
                className="card-subtext card-subtitle",
            ),
            make_suppression_panel(
                normalized["framework_suppression_picks"],
                normalized["graph_b"].get("suppression_pick", {}),
            ),
        ],
    )

    return (
        make_detected_objects_panel(image_contents, normalized["detected_objects"]),
        make_summary_panel(
            normalized["scene_summary"],
            normalized["disaster_scenario"],
            normalized["disaster_type"],
            normalized["disaster_level"],
            key_observations=normalized.get("key_observations", []),
            assumptions=normalized.get("assumptions", []),
            uncertainty_notes=normalized.get("uncertainty_notes", []),
            pill_visibility=pill_visibility,
        ),
        [html.Div(make_hazard_thumbnails(image_contents, normalized["threats"], pill_visibility=pill_visibility), className="hazard-grid")],
        [
            html.Div(
                make_recommendation_list(
                    normalized["recommendations"],
                    normalized["detected_objects"],
                    normalized["threats"],
                    image_contents,
                    pill_visibility=pill_visibility,
                ),
                className="recommendation-grid",
            )
        ],
        graph_a_view,
        graph_b_view,
        pre_alignment_view,
        consistency_view,
        pre_trust_view,
        gt_validation_view,
        suppression_view,
    )


@app.callback(
    Output("export-status", "children"),
    Input("export-button", "n_clicks"),
    State("analysis-store", "data"),
    State("prompt-input", "value"),
    State("caption-input", "value"),
    State("image-upload", "contents"),
    State("image-upload", "filename"),
    prevent_initial_call=True,
)
def export_structured_response(
    n_clicks: int | None,
    data: dict[str, Any] | None,
    prompt: str | None,
    caption: str | None,
    image_contents: str | None,
    image_filename: str | None,
) -> str:
    if not n_clicks:
        raise dash.exceptions.PreventUpdate

    normalized = normalize_result(data or PLACEHOLDER_RESULT, image_contents)
    exported_at = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
    run_id = normalized.get("run_id") or f"run_{exported_at}"
    normalized["run_id"] = run_id
    normalized["image_filename"] = normalized.get("image_filename") or safe_filename(image_filename)
    run_dir = EXPORT_ROOT / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    image_bytes, mime_type = parse_data_url(image_contents)
    if image_bytes:
        extension_map = {
            "image/jpeg": ".jpg",
            "image/png": ".png",
            "image/webp": ".webp",
        }
        chosen_name = safe_filename(normalized["image_filename"])
        if "." not in chosen_name:
            chosen_name = f"{chosen_name}{extension_map.get(mime_type or '', '.png')}"
        (run_dir / chosen_name).write_bytes(image_bytes)

    payload = {
        "exported_at": exported_at,
        "run_id": run_id,
        "model": os.getenv("QWEN_MODEL_NAME", "qwen2.5vl:7b"),
        "image_filename": normalized.get("image_filename", ""),
        "prompt": prompt or DEFAULT_PROMPT,
        "caption": caption or "",
        "structured_response": normalized,
    }
    (run_dir / "structured_response.json").write_text(json.dumps(payload, indent=2))
    (run_dir / "prompt.txt").write_text(prompt or DEFAULT_PROMPT)
    (run_dir / "caption.txt").write_text(caption or "")

    return f"Exported run folder: {run_dir}"


@app.callback(
    Output("report-content", "children"),
    Output("report-status", "children"),
    Input("generate-report-button", "n_clicks"),
    State("report-mode", "value"),
    State("report-folder", "value"),
    prevent_initial_call=True,
)
def generate_report(n_clicks: int | None, mode: str | None, folder: str | None):
    if not n_clicks:
        raise dash.exceptions.PreventUpdate

    if mode != "existing":
        return dash.no_update, "Batch mode is not yet implemented."

    folder = (folder or "").strip()
    if not folder:
        return dash.no_update, "Provide a folder path."

    try:
        runs, skipped = load_run_jsons(folder)
    except Exception as exc:
        return dash.no_update, f"Failed to load runs: {exc}"

    if not runs:
        skipped_msg = "; ".join(f"{s['run_id']}: {s['reason']}" for s in skipped[:3])
        return (
            html.Div("No usable runs found.", className="empty-state"),
            f"No runs loaded from {folder}. Skipped: {skipped_msg or '(none)'}",
        )

    report = compute_pre_intervention_report(runs)
    findings = interpret_pre_intervention_report(report)
    panel = make_pre_intervention_report_panel(report, skipped=skipped)

    # Persist JSON + Markdown alongside exports/reports/
    try:
        out_dir = save_report(report, findings, folder, skipped=skipped)
        save_msg = f"  Saved: {out_dir.relative_to(EXPORT_ROOT.parent) if out_dir.is_relative_to(EXPORT_ROOT.parent) else out_dir}"
    except Exception as exc:
        save_msg = f"  (save failed: {exc})"

    status = f"Loaded {len(runs)} run{'s' if len(runs) != 1 else ''} from {folder}."
    if skipped:
        status += f"  Skipped {len(skipped)}."
    status += save_msg
    return panel, status


@app.callback(
    Output("report-mode-existing-controls", "style"),
    Output("report-mode-batch-controls", "style"),
    Input("report-mode", "value"),
)
def toggle_report_mode(mode: str | None):
    if mode == "batch":
        return {"display": "none"}, {"display": "block"}
    return {"display": "block"}, {"display": "none"}


@app.callback(
    Output("folder-browser-panel", "style"),
    Input("folder-browse-toggle", "n_clicks"),
    State("folder-browser-panel", "style"),
    prevent_initial_call=True,
)
def toggle_folder_browser(n_clicks, current_style):
    if not n_clicks:
        raise dash.exceptions.PreventUpdate
    visible = current_style and current_style.get("display") != "none"
    return {"display": "none"} if visible else {"display": "block"}


@app.callback(
    Output("folder-browser-state", "data"),
    Input("folder-up-button", "n_clicks"),
    Input({"type": "folder-nav-into", "name": dash.ALL}, "n_clicks"),
    Input("folder-browse-toggle", "n_clicks"),
    State("folder-browser-state", "data"),
    State("batch-images-folder", "value"),
    State({"type": "folder-nav-into", "name": dash.ALL}, "id"),
    prevent_initial_call=True,
)
def navigate_folder(up_clicks, into_clicks_list, toggle_clicks, state, current_input, into_ids):
    triggered = dash.callback_context.triggered_id
    if triggered is None:
        raise dash.exceptions.PreventUpdate

    state = state or {}

    # Browse-toggle: when opening, sync to the input field's path
    if triggered == "folder-browse-toggle":
        return {"path": (current_input or "").strip()}

    # Up button
    if triggered == "folder-up-button":
        info = summarize_folder(state.get("path", ""))
        if info.get("parent"):
            return {"path": info["parent"]}
        raise dash.exceptions.PreventUpdate

    # Pattern-matched subfolder click
    if isinstance(triggered, dict) and triggered.get("type") == "folder-nav-into":
        return {"path": triggered.get("name", "")}

    raise dash.exceptions.PreventUpdate


@app.callback(
    Output("folder-browser-path", "children"),
    Output("folder-browser-summary", "children"),
    Output("folder-browser-list", "children"),
    Input("folder-browser-state", "data"),
)
def render_folder_browser(state):
    state = state or {}
    info = summarize_folder(state.get("path", ""))
    if not info.get("exists"):
        return (
            f"⚠ {info.get('error', 'invalid path')}",
            "",
            html.Div("(no folder)", className="folder-browser-empty"),
        )

    path_display = info["path"]
    n_direct = info["n_images_direct"]
    n_recursive = info["n_images_recursive"]
    summary = (
        f"{n_recursive} image(s) total"
        + (f" — {n_direct} directly here, {n_recursive - n_direct} in subfolders" if n_recursive != n_direct else " in this folder")
    )

    if not info["subfolders"]:
        sub_list = html.Div("(no subfolders)", className="folder-browser-empty")
    else:
        sub_list = html.Div(
            [
                html.Button(
                    [
                        html.Span("📁 ", className="folder-icon"),
                        html.Span(s["name"], className="folder-name"),
                        html.Span(
                            f"  {s['n_images_recursive']} img" + (f" ({s['n_images_direct']} direct)" if s["n_images_recursive"] != s["n_images_direct"] else ""),
                            className="folder-count",
                        ),
                    ],
                    id={"type": "folder-nav-into", "name": s["path"]},
                    className="folder-row-button",
                    n_clicks=0,
                )
                for s in info["subfolders"]
            ],
            className="folder-browser-rows",
        )

    return path_display, summary, sub_list


@app.callback(
    Output("batch-images-folder", "value"),
    Input("folder-use-button", "n_clicks"),
    State("folder-browser-state", "data"),
    prevent_initial_call=True,
)
def use_browsed_folder(n_clicks, state):
    if not n_clicks:
        raise dash.exceptions.PreventUpdate
    state = state or {}
    return state.get("path", "")


@app.callback(
    Output("report-status", "children", allow_duplicate=True),
    Output("batch-interval", "disabled", allow_duplicate=True),
    Input("start-batch-button", "n_clicks"),
    State("batch-images-folder", "value"),
    State("batch-options", "value"),
    prevent_initial_call=True,
)
def start_batch(n_clicks, folder, options):
    if not n_clicks:
        raise dash.exceptions.PreventUpdate

    state = _read_batch_state()
    if state["active"]:
        return f"A batch is already running ({state['completed']}/{state['total']}).", False

    folder = (folder or "").strip()
    if not folder:
        return "Provide an images folder path.", True
    folder_path = Path(folder).expanduser().resolve()
    if not folder_path.is_dir():
        return f"Folder not found: {folder_path}", True

    # Walk with symlink-following so aggregation folders that symlink to source
    # subdirectories (e.g., experiments/batch_input/fire -> ../exp2/images/fire)
    # work. Use the symlinked path (NOT .resolve()) so category inference based
    # on relative_to(folder_path) still works.
    images = sorted(
        Path(root, fname)
        for root, _dirs, files in os.walk(str(folder_path), followlinks=True)
        for fname in files
        if Path(fname).suffix.lower() in IMAGE_EXTENSIONS
    )
    if not images:
        return f"No images (jpg/png/webp/bmp) found under {folder_path}.", True

    # New batch-centric layout: exports/batches/batch_<ts>/runs/
    batch_dir = EXPORT_ROOT / "batches" / f"batch_{datetime.now().strftime('%Y%m%dT%H%M%S')}"
    out_dir = batch_dir / "runs"
    out_dir.mkdir(parents=True, exist_ok=True)

    options = options or []
    use_sidecar = "sidecar" in options
    allow_inferred = "inferred" in options

    threading.Thread(
        target=_run_batch_worker,
        args=(images, use_sidecar, allow_inferred, out_dir),
        kwargs={"images_root": folder_path},
        daemon=True,
    ).start()

    return (
        f"Batch started: {len(images)} image(s). Output: {batch_dir.relative_to(EXPORT_ROOT.parent) if batch_dir.is_relative_to(EXPORT_ROOT.parent) else batch_dir}.",
        False,
    )


@app.callback(
    Output("batch-progress", "children"),
    Output("report-content", "children", allow_duplicate=True),
    Output("report-status", "children", allow_duplicate=True),
    Output("batch-interval", "disabled", allow_duplicate=True),
    Input("batch-interval", "n_intervals"),
    prevent_initial_call=True,
)
def poll_batch(_n):
    state = _read_batch_state()

    # Active: update progress only
    if state["active"]:
        progress = html.Div(
            [
                html.Div(
                    f"Running {state['completed']}/{state['total']}: {state.get('current') or '...'}",
                    className="batch-progress-line",
                ),
                html.Div(
                    html.Div(
                        style={
                            "width": f"{100 * state['completed'] / state['total']:.1f}%" if state["total"] else "0%",
                        },
                        className="batch-progress-bar-fill",
                    ),
                    className="batch-progress-bar-track",
                ),
                html.Div(
                    f"{len(state['errors'])} error(s) so far" if state["errors"] else "No errors yet.",
                    className="batch-progress-errors",
                ),
            ],
        )
        return progress, dash.no_update, dash.no_update, False

    # Done: render report from the new batch folder, then stop polling
    if state["done"]:
        out_dir = state.get("out_dir")
        report_path = state.get("report_path")
        try:
            runs, skipped = load_run_jsons(out_dir or "")
            report = compute_pre_intervention_report(runs)
            panel = make_pre_intervention_report_panel(report, skipped=skipped)
        except Exception as exc:
            panel = html.Div(f"Failed to render report: {exc}", className="empty-state")

        progress = html.Div(
            [
                html.Div(
                    f"Batch complete — {state['completed']}/{state['total']} processed.",
                    className="batch-progress-line batch-progress-done",
                ),
                html.Div(
                    f"{len(state['errors'])} error(s)." if state["errors"] else "No errors.",
                    className="batch-progress-errors",
                ),
            ],
        )
        msg = f"Batch complete. Output: {out_dir}."
        if report_path:
            msg += f"  Report saved: {report_path}."
        # Reset done flag so this branch doesn't re-fire on subsequent ticks
        _reset_batch_state()
        return progress, panel, msg, True

    # Idle: nothing to do, stop polling
    return dash.no_update, dash.no_update, dash.no_update, True


def _gt_filter(cands: list[dict[str, Any]], filter_value: str) -> list[dict[str, Any]]:
    if filter_value == "pending":
        return [c for c in cands if c["status"] != "verified"]
    if filter_value == "verified":
        return [c for c in cands if c["status"] == "verified"]
    return list(cands)


def _gt_first_pending_or_first(cands: list[dict[str, Any]]) -> str:
    if not cands:
        return ""
    pending = [c for c in cands if c["status"] != "verified"]
    return (pending[0] if pending else cands[0])["path"]


def _render_position_info(folder: str, selected_path: str, filter_value: str):
    """Render the position counter strip above the pager controls."""
    folder = (folder or "").strip()
    if not folder or not Path(folder).expanduser().resolve().exists():
        return html.Div("Set candidates folder, then click Load Candidates.", className="empty-state")
    cands = list_gt_candidates(folder)
    if not cands:
        return html.Div("No *.gt.json candidates in folder.", className="empty-state")
    filtered = _gt_filter(cands, filter_value)
    n_total_all = len(cands)
    n_verified = sum(1 for c in cands if c["status"] == "verified")
    n_pending = n_total_all - n_verified
    summary = html.Div(
        f"{n_total_all} total · {n_verified} verified · {n_pending} pending",
        className="card-subtext",
        style={"marginBottom": "4px"},
    )
    if not filtered:
        return html.Div([summary, html.Div(f"No candidates match filter: {filter_value}", className="empty-state")])
    paths = [c["path"] for c in filtered]
    try:
        idx = paths.index(selected_path) if selected_path else -1
    except ValueError:
        idx = -1
    if idx < 0:
        c = filtered[0]
        return html.Div([
            summary,
            html.Div([
                html.Span(f"#? / {len(filtered)}", className="gt-pos-counter"),
                html.Span("·", className="gt-pos-sep"),
                html.Span("Current selection not in this filter — click Next to begin.", className="card-subtext"),
            ], className="gt-pos-line"),
        ])
    c = filtered[idx]
    status_class = "gt-status-verified" if c["status"] == "verified" else "gt-status-unverified"
    return html.Div([
        summary,
        html.Div([
            html.Span(f"#{idx+1} / {len(filtered)}", className="gt-pos-counter"),
            html.Span("·", className="gt-pos-sep"),
            html.Span(c["image_filename"], className="gt-pos-filename"),
            html.Span(c["status"], className=f"gt-pos-status gt-row-status {status_class}"),
        ], className="gt-pos-line"),
    ])


# Load button: scan folder, set selection to first pending (else first).
@app.callback(
    Output("gt-status", "children"),
    Output("gt-selected-path", "data", allow_duplicate=True),
    Input("gt-load-button", "n_clicks"),
    State("gt-folder", "value"),
    prevent_initial_call=True,
)
def gt_load_list(_n_clicks, folder):
    folder = (folder or "").strip()
    if not folder:
        return "Provide a folder path.", dash.no_update
    if not Path(folder).expanduser().resolve().exists():
        return f"Folder not found: {folder}", dash.no_update
    cands = list_gt_candidates(folder)
    if not cands:
        return f"No *.gt.json candidates in {folder}.", ""
    n_verified = sum(1 for c in cands if c["status"] == "verified")
    msg = f"Loaded {len(cands)} candidate(s); {n_verified} verified."
    return msg, _gt_first_pending_or_first(cands)


# Accept / Reject: save then advance to first remaining pending.
@app.callback(
    Output("gt-status", "children", allow_duplicate=True),
    Output("gt-selected-path", "data", allow_duplicate=True),
    Output("gt-refresh-tick", "data"),
    Input("gt-accept-active", "n_clicks"),
    Input("gt-reject-active", "n_clicks"),
    State("gt-folder", "value"),
    State("gt-selected-path", "data"),
    State("gt-working-state", "data"),
    State({"type": "gt-node-field", "i": dash.ALL, "field": dash.ALL}, "value"),
    State({"type": "gt-node-field", "i": dash.ALL, "field": dash.ALL}, "id"),
    State({"type": "gt-edge-field", "i": dash.ALL, "field": dash.ALL}, "value"),
    State({"type": "gt-edge-field", "i": dash.ALL, "field": dash.ALL}, "id"),
    State("gt-edit-caption", "value"),
    State("gt-edit-notes", "value"),
    State("gt-refresh-tick", "data"),
    prevent_initial_call=True,
)
def gt_accept_or_reject(
    accept_clicks, reject_clicks, folder, selected_path, working,
    node_values, node_ids, edge_values, edge_ids, caption, notes, tick,
):
    ctx = dash.callback_context
    triggered = ctx.triggered_id
    triggered_value = ctx.triggered[0].get("value") if ctx.triggered else None
    if (triggered_value or 0) <= 0 or not selected_path:
        raise dash.exceptions.PreventUpdate

    status_msg = ""
    if triggered == "gt-accept-active":
        # Build the candidate from the CURRENT form values, not just the working
        # state — typing into node/edge fields doesn't auto-sync to the store,
        # so we re-read the form here so the saved file reflects what the user
        # actually sees on screen.
        nodes_by_idx: dict[int, dict[str, Any]] = {}
        for v, ident in zip(node_values or [], node_ids or []):
            i = ident.get("i")
            field = ident.get("field")
            n = nodes_by_idx.setdefault(
                i, {"id": "", "label": "", "state": "", "hazardous": False, "inferred": False}
            )
            if field in ("hazardous", "inferred"):
                n[field] = bool(v) and "y" in (v if isinstance(v, list) else [v])
            else:
                n[field] = "" if v is None else str(v)
        nodes = [nodes_by_idx[i] for i in sorted(nodes_by_idx.keys())]

        edges_by_idx: dict[int, dict[str, Any]] = {}
        for v, ident in zip(edge_values or [], edge_ids or []):
            i = ident.get("i")
            field = ident.get("field")
            e = edges_by_idx.setdefault(
                i, {"source": "", "target": "", "effect": "", "via_state": ""}
            )
            e[field] = "" if v is None else str(v)
        edges = [edges_by_idx[i] for i in sorted(edges_by_idx.keys())]

        base = working if working else load_gt_candidate(selected_path)
        cand = dict(base or {})
        cand["caption"] = caption if caption is not None else cand.get("caption", "")
        cand["annotator_notes"] = notes if notes is not None else cand.get("annotator_notes", "")
        cand["nodes"] = nodes
        cand["edges"] = edges
        try:
            saved = save_verified_gt(cand, selected_path)
            status_msg = f"Verified → {Path(saved).name}"
        except Exception as exc:
            return f"⚠ Save failed: {exc}", dash.no_update, dash.no_update
    elif triggered == "gt-reject-active":
        removed = unverify_gt(selected_path)
        status_msg = "Removed from verified." if removed else "Was not in verified."

    new_tick = (tick or 0) + 1

    cands = list_gt_candidates(folder)
    pending = [c for c in cands if c["status"] != "verified"]
    all_paths = [c["path"] for c in cands]
    try:
        cur_idx = all_paths.index(selected_path)
    except ValueError:
        cur_idx = -1

    # Prefer next pending after current; otherwise just next candidate in list.
    if pending:
        after_pending = [c for c in cands[cur_idx+1:] if c["status"] != "verified"]
        next_path = (after_pending[0] if after_pending else pending[0])["path"]
        return status_msg, next_path, new_tick

    # No pending — fall back to next candidate in list order. If at the last
    # one, stay put (don't wrap).
    if cur_idx >= 0 and cur_idx + 1 < len(all_paths):
        return f"{status_msg}  (No more pending — moved to next.)", all_paths[cur_idx + 1], new_tick
    return f"{status_msg}  (No more pending — end of list.)", dash.no_update, new_tick


# Prev / Next / Jump-to-next-pending navigation.
@app.callback(
    Output("gt-selected-path", "data", allow_duplicate=True),
    Input("gt-prev-button", "n_clicks"),
    Input("gt-next-button", "n_clicks"),
    Input("gt-jump-pending-button", "n_clicks"),
    State("gt-folder", "value"),
    State("gt-filter", "value"),
    State("gt-selected-path", "data"),
    prevent_initial_call=True,
)
def gt_navigate(_p, _n, _j, folder, filter_value, current_path):
    ctx = dash.callback_context
    triggered = ctx.triggered_id
    triggered_value = ctx.triggered[0].get("value") if ctx.triggered else None
    if (triggered_value or 0) <= 0 or not triggered:
        raise dash.exceptions.PreventUpdate

    cands = list_gt_candidates(folder)
    if not cands:
        raise dash.exceptions.PreventUpdate

    if triggered == "gt-jump-pending-button":
        pending = [c for c in cands if c["status"] != "verified"]
        if not pending:
            raise dash.exceptions.PreventUpdate
        return pending[0]["path"]

    filtered = _gt_filter(cands, filter_value)
    if not filtered:
        raise dash.exceptions.PreventUpdate
    paths = [c["path"] for c in filtered]
    try:
        idx = paths.index(current_path) if current_path else -1
    except ValueError:
        idx = -1

    if triggered == "gt-prev-button":
        new_idx = max(0, idx - 1) if idx >= 0 else 0
    elif triggered == "gt-next-button":
        new_idx = min(len(filtered) - 1, idx + 1) if idx >= 0 else 0
    else:
        raise dash.exceptions.PreventUpdate

    return filtered[new_idx]["path"]


# Position-info renderer: fires on selection change, filter change, or
# accept/reject (via gt-refresh-tick), so the VERIFIED/UNVERIFIED badge and
# the pending count update even when the selection didn't move.
@app.callback(
    Output("gt-position-info", "children"),
    Input("gt-selected-path", "data"),
    Input("gt-filter", "value"),
    Input("gt-refresh-tick", "data"),
    State("gt-folder", "value"),
)
def gt_render_position(selected_path, filter_value, _tick, folder):
    return _render_position_info(folder or "", selected_path or "", filter_value or "all")


# Init callback: only triggers when a candidate is selected. Static Inputs only.
@app.callback(
    Output("gt-working-state", "data"),
    Input("gt-selected-path", "data"),
    prevent_initial_call=True,
)
def gt_init_working(selected_path):
    if not selected_path:
        return {}
    return load_gt_candidate(selected_path)


# Mutate callback: only triggers when the user adds/deletes a row in the editor.
# All Inputs are dynamic — they only exist after a candidate is selected and the
# editor has rendered. allow_duplicate lets this share the working-state output
# with the init callback above.
@app.callback(
    Output("gt-working-state", "data", allow_duplicate=True),
    Input("gt-add-node-button", "n_clicks"),
    Input("gt-add-edge-button", "n_clicks"),
    Input({"type": "gt-delete-node", "i": dash.ALL}, "n_clicks"),
    Input({"type": "gt-delete-edge", "i": dash.ALL}, "n_clicks"),
    State({"type": "gt-node-field", "i": dash.ALL, "field": dash.ALL}, "value"),
    State({"type": "gt-node-field", "i": dash.ALL, "field": dash.ALL}, "id"),
    State({"type": "gt-edge-field", "i": dash.ALL, "field": dash.ALL}, "value"),
    State({"type": "gt-edge-field", "i": dash.ALL, "field": dash.ALL}, "id"),
    State("gt-edit-caption", "value"),
    State("gt-edit-notes", "value"),
    State("gt-working-state", "data"),
    prevent_initial_call=True,
)
def gt_mutate_working(
    add_node_clicks, add_edge_clicks, del_node_clicks_list, del_edge_clicks_list,
    node_values, node_ids, edge_values, edge_ids, caption, notes, working,
):
    ctx = dash.callback_context
    triggered = ctx.triggered_id
    triggered_value = ctx.triggered[0].get("value") if ctx.triggered else None

    # Action buttons: gather current form State first so edits aren't lost
    def gather_nodes_from_form() -> list[dict[str, Any]]:
        by_idx: dict[int, dict[str, Any]] = {}
        for v, ident in zip(node_values or [], node_ids or []):
            i = ident.get("i")
            field = ident.get("field")
            n = by_idx.setdefault(i, {"id": "", "label": "", "state": "", "hazardous": False, "inferred": False})
            if field in ("hazardous", "inferred"):
                n[field] = bool(v) and "y" in (v if isinstance(v, list) else [v])
            else:
                n[field] = "" if v is None else str(v)
        return [by_idx[i] for i in sorted(by_idx.keys())]

    def gather_edges_from_form() -> list[dict[str, Any]]:
        by_idx: dict[int, dict[str, Any]] = {}
        for v, ident in zip(edge_values or [], edge_ids or []):
            i = ident.get("i")
            field = ident.get("field")
            e = by_idx.setdefault(i, {"source": "", "target": "", "effect": "", "via_state": ""})
            e[field] = "" if v is None else str(v)
        return [by_idx[i] for i in sorted(by_idx.keys())]

    nodes = gather_nodes_from_form()
    edges = gather_edges_from_form()

    new_working = dict(working or {})
    new_working["caption"] = caption or new_working.get("caption", "")
    new_working["annotator_notes"] = notes if notes is not None else new_working.get("annotator_notes", "")

    # Apply action
    if triggered == "gt-add-node-button" and (triggered_value or 0) > 0:
        nodes.append({"id": "", "label": "", "state": "", "hazardous": False, "inferred": False})
    elif triggered == "gt-add-edge-button" and (triggered_value or 0) > 0:
        edges.append({"source": "", "target": "", "effect": "", "via_state": ""})
    elif isinstance(triggered, dict) and (triggered_value or 0) > 0:
        if triggered.get("type") == "gt-delete-node":
            i = triggered.get("i")
            if isinstance(i, int) and 0 <= i < len(nodes):
                deleted_id = str(nodes[i].get("id", "")).strip()
                nodes.pop(i)
                # Cascade: drop any edge that references the deleted node so the
                # graph viewer doesn't get an edge with an unspecified source/target.
                if deleted_id:
                    edges = [
                        e for e in edges
                        if str(e.get("source", "")).strip() != deleted_id
                        and str(e.get("target", "")).strip() != deleted_id
                    ]
        elif triggered.get("type") == "gt-delete-edge":
            i = triggered.get("i")
            if isinstance(i, int) and 0 <= i < len(edges):
                edges.pop(i)
        else:
            # Pattern-matched delete fired with n_clicks=0 on initial render — ignore
            raise dash.exceptions.PreventUpdate
    else:
        # An add/delete fired with n_clicks=0 (button just mounted) — ignore
        raise dash.exceptions.PreventUpdate

    new_working["nodes"] = nodes
    new_working["edges"] = edges
    return new_working


@app.callback(
    Output("gt-detail-view", "children"),
    Input("gt-working-state", "data"),
    Input("gt-allow-inferred", "value"),
    State("gt-selected-path", "data"),
)
def gt_render_detail(working, allow_inferred_value, path):
    if not path:
        return html.Div("Select a candidate above to inspect it.", className="empty-state")
    cand = working if working else load_gt_candidate(path)
    if not cand:
        return html.Div(f"Could not load: {path}", className="empty-state")

    # Filter inferred entities and their incident edges unless the user opts in.
    allow_inferred = "allow" in (allow_inferred_value or [])
    if not allow_inferred:
        inferred_ids = {n["id"] for n in cand.get("nodes", []) if n.get("inferred")}
        if inferred_ids:
            cand = dict(cand)
            cand["nodes"] = [n for n in cand.get("nodes", []) if not n.get("inferred")]
            cand["edges"] = [
                e for e in cand.get("edges", [])
                if e.get("source") not in inferred_ids and e.get("target") not in inferred_ids
            ]

    image_filename = cand.get("image_filename", "")
    image_path = Path(path).parent / image_filename if image_filename else None
    if image_path and image_path.exists():
        mime = MIME_BY_EXT.get(image_path.suffix.lower(), "image/jpeg")
        data_url = image_bytes_to_data_url(image_path.read_bytes(), mime)
        image_block = html.Img(src=data_url, className="embedded-preview")
    else:
        image_block = html.Div(f"(image not found alongside JSON: {image_filename})", className="empty-state")

    graph_view = make_causal_graph_viewer(gt_candidate_to_graph_dict(cand), elem_id=f"gt-cyto-{Path(path).stem}")

    return html.Div(
        [
            html.Div(
                [
                    html.Div("Source", className="detail-label-text"),
                    html.Div(cand.get("source", "(unknown)"), className="detail-value"),
                ],
                className="gt-detail-block",
            ),
            html.Div(
                [
                    html.Div(image_block, className="gt-detail-image"),
                    html.Div(graph_view, className="gt-detail-graph"),
                ],
                className="gt-image-graph-row",
            ),
            html.Div(make_graph_text_view(gt_candidate_to_graph_dict(cand)), className="gt-detail-text"),
            make_gt_editor(cand),
            html.Div(
                [
                    html.Button(
                        "Accept (save to verified)",
                        id="gt-accept-active",
                        className="analyze-button primary-button",
                        n_clicks=0,
                    ),
                    html.Button(
                        "Reject (remove from verified)",
                        id="gt-reject-active",
                        className="analyze-button secondary-button",
                        n_clicks=0,
                    ),
                ],
                className="action-row",
            ),
        ],
        className="gt-detail",
    )


def make_gt_test_results_panel(report: dict[str, Any]) -> html.Div:
    """Render Test 1 (Ground Truth Comparison) results."""
    if not report or report.get("n_pairs", 0) == 0:
        msg = report.get("verdict_text") or "Run Test 1 to compare verified GT against the batch."
        if report.get("unmatched_filenames"):
            msg += f"  Unmatched filenames: {', '.join(report['unmatched_filenames'][:5])}"
        return html.Div(msg, className="empty-state")

    # Verdict
    verdict_kind = report.get("verdict_kind", "neutral")
    verdict_block = html.Div(
        [html.Div(report.get("verdict_text", ""), className=f"finding-headline finding-{verdict_kind}")],
        className=f"finding-row finding-row-{verdict_kind}",
    )

    n_pairs = report["n_pairs"]
    n_unmatched = report.get("n_unmatched", 0)
    header = html.Div(
        [
            html.Div(f"Test 1 — Ground Truth Comparison ({n_pairs} matched)", className="report-title"),
            html.Div(
                f"{report.get('n_verified', 0)} verified GT files; {n_unmatched} unmatched"
                + (f" ({', '.join(report.get('unmatched_filenames', [])[:3])})" if n_unmatched else ""),
                className="report-subtitle",
            ),
        ],
        className="report-header",
    )

    # Aggregate metrics
    agg = report.get("aggregate", {}) or {}
    def metric_card(label: str, stats: dict[str, float], help_text: str) -> html.Div:
        v = stats.get("median", 0.0)
        if v >= 0.70: c = "score-high"
        elif v >= 0.40: c = "score-mid"
        else: c = "score-low"
        return html.Div(
            [
                html.Div(label, className="consistency-score-label"),
                html.Div(f"{v:.2f}", className=f"consistency-score-value {c}"),
                html.Div(help_text, className="card-subtext"),
            ],
            className="consistency-score-card",
        )

    metrics_row_strict = html.Div(
        [
            metric_card("A-correctness", agg.get("a_correctness", {}), "Exact 4-tuple matches recovered. Strict recall."),
            metric_card("A-precision",   agg.get("a_precision", {}),   "Exact 4-tuple matches in A. Strict precision."),
            metric_card("B-correctness", agg.get("b_correctness", {}), "Exact 4-tuple matches recovered. Strict recall."),
            metric_card("B-precision",   agg.get("b_precision", {}),   "Exact 4-tuple matches in B. Strict precision."),
        ],
        className="consistency-score-row",
    )
    metrics_row_soft = html.Div(
        [
            metric_card("A-correctness (soft)", agg.get("a_correctness_soft", {}), "Label hierarchy + state syn + effect close-pair."),
            metric_card("A-precision (soft)",   agg.get("a_precision_soft", {}),   "Soft precision."),
            metric_card("B-correctness (soft)", agg.get("b_correctness_soft", {}), "Soft recall."),
            metric_card("B-precision (soft)",   agg.get("b_precision_soft", {}),   "Soft precision."),
        ],
        className="consistency-score-row",
    )
    metrics_row_topo = html.Div(
        [
            metric_card("A-correctness (topo)", agg.get("a_correctness_topo", {}), "State IGNORED. Match by source-class → effect-family → target-class."),
            metric_card("A-precision (topo)",   agg.get("a_precision_topo", {}),   "Topological precision."),
            metric_card("B-correctness (topo)", agg.get("b_correctness_topo", {}), "Topological recall — strongest structural-agreement signal."),
            metric_card("B-precision (topo)",   agg.get("b_precision_topo", {}),   "Topological precision."),
        ],
        className="consistency-score-row",
    )

    # Per-pair table
    pairs = report.get("per_pair", []) or []
    pair_rows = [
        html.Div(
            [
                html.Div("Image", className="prr-cell prr-header"),
                html.Div("|GT|", className="prr-cell prr-header"),
                html.Div("|A|", className="prr-cell prr-header"),
                html.Div("|B|", className="prr-cell prr-header"),
                html.Div("A-corr strict/soft/topo", className="prr-cell prr-header"),
                html.Div("B-corr strict/soft/topo", className="prr-cell prr-header"),
                html.Div("A-prec strict/soft/topo", className="prr-cell prr-header"),
                html.Div("B-prec strict/soft/topo", className="prr-cell prr-header"),
                html.Div("", className="prr-cell prr-header"),
            ],
            className="prr-row prr-header-row",
        )
    ]
    for p in pairs:
        pair_rows.append(
            html.Div(
                [
                    html.Div(p["image_filename"], className="prr-cell prr-id"),
                    html.Div(str(p["n_edges_gt"]), className="prr-cell"),
                    html.Div(str(p["n_edges_a"]), className="prr-cell"),
                    html.Div(str(p["n_edges_b"]), className="prr-cell"),
                    html.Div(f"{p['a_correctness']:.2f} / {p['a_correctness_soft']:.2f} / {p['a_correctness_topo']:.2f}", className="prr-cell"),
                    html.Div(f"{p['b_correctness']:.2f} / {p['b_correctness_soft']:.2f} / {p['b_correctness_topo']:.2f}", className="prr-cell"),
                    html.Div(f"{p['a_precision']:.2f} / {p['a_precision_soft']:.2f} / {p['a_precision_topo']:.2f}", className="prr-cell"),
                    html.Div(f"{p['b_precision']:.2f} / {p['b_precision_soft']:.2f} / {p['b_precision_topo']:.2f}", className="prr-cell"),
                    html.Button(
                        "Inspect",
                        id={"type": "gtcmp-inspect", "image_filename": p["image_filename"], "run_id": p["run_id"]},
                        className="folder-nav-button",
                        n_clicks=0,
                    ),
                ],
                className="prr-row prr-row-with-action",
            )
        )

    # Per-category breakdown (if categories present)
    by_cat = report.get("by_category", []) or []
    cat_section = None
    if len(by_cat) > 1 or (len(by_cat) == 1 and by_cat[0]["category"] != "(uncategorized)"):
        cat_rows = [
            html.Div(
                [
                    html.Div("Category", className="cat-cell cat-header"),
                    html.Div("n", className="cat-cell cat-header"),
                    html.Div("A-corr med", className="cat-cell cat-header"),
                    html.Div("A-prec med", className="cat-cell cat-header"),
                    html.Div("B-corr med", className="cat-cell cat-header"),
                    html.Div("B-prec med", className="cat-cell cat-header"),
                    html.Div("", className="cat-cell cat-header"),
                ],
                className="cat-row cat-header-row",
            ),
        ]
        for c in by_cat:
            cat_rows.append(
                html.Div(
                    [
                        html.Div(c["category"], className="cat-cell cat-name"),
                        html.Div(str(c["n"]), className="cat-cell"),
                        html.Div(f"{c['a_correctness_median']:.2f}", className="cat-cell cat-numeric"),
                        html.Div(f"{c['a_precision_median']:.2f}", className="cat-cell cat-numeric"),
                        html.Div(f"{c['b_correctness_median']:.2f}", className="cat-cell cat-numeric"),
                        html.Div(f"{c['b_precision_median']:.2f}", className="cat-cell cat-numeric"),
                        html.Div("", className="cat-cell"),
                    ],
                    className="cat-row",
                )
            )
        cat_section = html.Div(
            [
                html.Div("By disaster category", className="report-section-label"),
                html.Div(cat_rows, className="cat-table"),
            ],
            className="report-section",
        )

    children = [
        header,
        verdict_block,
        html.Div("Strict — exact 4-tuple match", className="report-section-label"),
        html.Div(metrics_row_strict, className="report-section"),
        html.Div("Soft — label hierarchy + state synonyms + effect close-pair", className="report-section-label"),
        html.Div(metrics_row_soft, className="report-section"),
        html.Div("Topological — state IGNORED (source class → effect family → target class)", className="report-section-label"),
        html.Div(metrics_row_topo, className="report-section"),
    ]
    if cat_section is not None:
        children.append(cat_section)
    children.extend([
        html.Div(f"Per-pair detail ({n_pairs} pairs)", className="report-section-label"),
        html.Div(pair_rows, className="report-section prr-table"),
    ])
    return html.Div(children, className="report-panel")


def make_psens_results_panel(results: list[dict[str, Any]], variant_ids: list[str], summary: dict[str, Any] | None = None) -> html.Div:
    """Render the Test 2 results: verdict + per-variant medians + per-image dispersion table."""
    if not results:
        return html.Div("No results yet — start Test 2.", className="empty-state")

    summary = summary or aggregate_prompt_sensitivity(results, variant_ids)

    # Verdict block
    verdict_kind = summary.get("verdict_kind", "neutral")
    verdict_block = html.Div(
        [
            html.Div(summary.get("verdict_text", ""), className=f"finding-headline finding-{verdict_kind}"),
        ],
        className=f"finding-row finding-row-{verdict_kind}",
    )

    # Per-variant medians
    pvm = summary.get("per_variant_medians", {}) or {}
    variant_table_rows = [
        html.Div(
            [
                html.Div("Variant", className="metric-name metric-header"),
                html.Div("A-fid median", className="metric-value metric-header"),
                html.Div("B-cov median", className="metric-value metric-header"),
                html.Div("Topo median", className="metric-value metric-header"),
            ],
            className="metric-row metric-header-row",
        ),
    ]
    for vid in variant_ids:
        m = pvm.get(vid, {})
        variant_table_rows.append(
            html.Div(
                [
                    html.Div(f"{vid} — {PROMPT2_VARIANTS.get(vid, {}).get('name', vid)}", className="metric-name"),
                    html.Div(f"{m.get('a_fidelity', 0.0):.2f}", className="metric-value metric-median"),
                    html.Div(f"{m.get('b_coverage', 0.0):.2f}", className="metric-value metric-median"),
                    html.Div(f"{m.get('topological_consistency', 0.0):.2f}", className="metric-value metric-median"),
                ],
                className="metric-row",
            )
        )

    # Dispersion summary
    ds = summary.get("dispersion_summary", {}) or {}
    dispersion_rows = [
        html.Div(
            [
                html.Div("Metric", className="metric-name metric-header"),
                html.Div("Spread median", className="metric-value metric-header"),
                html.Div("IQR", className="metric-value metric-header"),
                html.Div("Max", className="metric-value metric-header"),
            ],
            className="metric-row metric-header-row",
        )
    ]
    for k in ("a_fidelity", "b_coverage", "topological_consistency"):
        s = ds.get(k, {})
        dispersion_rows.append(
            html.Div(
                [
                    html.Div(k.replace("_", " "), className="metric-name"),
                    html.Div(f"{s.get('median', 0):.2f}", className="metric-value metric-median"),
                    html.Div(f"[{s.get('p25', 0):.2f}–{s.get('p75', 0):.2f}]", className="metric-value metric-iqr"),
                    html.Div(f"{s.get('max', 0):.2f}", className="metric-value metric-range"),
                ],
                className="metric-row",
            )
        )

    # Per-image table
    per_image = summary.get("per_image_dispersion", []) or []
    pi_rows = [
        html.Div(
            [
                html.Div("Run", className="prr-cell prr-header"),
                html.Div("A-fid spread", className="prr-cell prr-header"),
                html.Div("A-fid range", className="prr-cell prr-header"),
                html.Div("B-cov spread", className="prr-cell prr-header"),
                html.Div("Topo spread", className="prr-cell prr-header"),
            ],
            className="prr-row prr-header-row",
        )
    ]
    for r in per_image:
        pi_rows.append(
            html.Div(
                [
                    html.Div(r.get("run_id", "?"), className="prr-cell prr-id"),
                    html.Div(f"{r.get('a_fidelity_spread', 0):.2f}", className="prr-cell"),
                    html.Div(f"{r.get('a_fidelity_min', 0):.2f}–{r.get('a_fidelity_max', 0):.2f}", className="prr-cell"),
                    html.Div(f"{r.get('b_coverage_spread', 0):.2f}", className="prr-cell"),
                    html.Div(f"{r.get('topological_consistency_spread', 0):.2f}", className="prr-cell"),
                ],
                className="prr-row",
            )
        )

    return html.Div(
        [
            verdict_block,
            html.Div("Per-variant medians", className="report-section-label"),
            html.Div(variant_table_rows, className="report-section"),
            html.Div("Dispersion across variants (per-image spread, then summarized)", className="report-section-label"),
            html.Div(dispersion_rows, className="report-section"),
            html.Div(f"Per-image dispersion ({len(per_image)} images)", className="report-section-label"),
            html.Div(pi_rows, className="report-section prr-table"),
        ],
        className="report-panel",
    )


@app.callback(
    Output("psens-status", "children"),
    Output("psens-interval", "disabled"),
    Input("psens-start-button", "n_clicks"),
    State("psens-batch-folder", "value"),
    State("psens-sample-size", "value"),
    State("psens-variants", "value"),
    prevent_initial_call=True,
)
def psens_start(n_clicks, folder, sample_size, variants):
    if not n_clicks:
        raise dash.exceptions.PreventUpdate

    state = _read_psens_state()
    if state["active"]:
        return f"A test is already running ({state['completed']}/{state['total']}).", False

    folder = (folder or "").strip()
    if not folder:
        return "Provide a batch folder path.", True
    folder_path = Path(folder).expanduser().resolve()
    if not folder_path.is_dir():
        return f"Folder not found: {folder_path}", True

    variants = variants or list(PROMPT2_VARIANTS.keys())
    sample_size = int(sample_size or 10)

    out_dir = EXPORT_ROOT / "tests" / f"prompt_sensitivity_{datetime.now().strftime('%Y%m%dT%H%M%S')}"
    out_dir.mkdir(parents=True, exist_ok=True)

    threading.Thread(
        target=_run_psens_worker,
        args=(folder_path, sample_size, variants, out_dir),
        daemon=True,
    ).start()

    return f"Test 2 started: sample={sample_size}, variants={len(variants)}. Output: {out_dir}.", False


@app.callback(
    Output("psens-progress", "children"),
    Output("psens-results", "children"),
    Output("psens-status", "children", allow_duplicate=True),
    Output("psens-interval", "disabled", allow_duplicate=True),
    Input("psens-interval", "n_intervals"),
    State("psens-variants", "value"),
    prevent_initial_call=True,
)
def psens_poll(_n, variant_ids):
    state = _read_psens_state()
    if state["active"]:
        pct = 100 * state["completed"] / state["total"] if state["total"] else 0
        progress = html.Div(
            [
                html.Div(
                    f"Test 2 running {state['completed']}/{state['total']}: {state.get('current') or '...'}",
                    className="batch-progress-line",
                ),
                html.Div(
                    html.Div(style={"width": f"{pct:.1f}%"}, className="batch-progress-bar-fill"),
                    className="batch-progress-bar-track",
                ),
                html.Div(
                    f"{len(state['errors'])} error(s)" if state["errors"] else "No errors yet.",
                    className="batch-progress-errors",
                ),
            ],
        )
        return progress, dash.no_update, dash.no_update, False
    if state["done"]:
        summary = aggregate_prompt_sensitivity(state["results"], variant_ids or list(PROMPT2_VARIANTS.keys()))
        panel = make_psens_results_panel(state["results"], variant_ids or list(PROMPT2_VARIANTS.keys()), summary)
        msg = f"Test 2 complete: {state['completed']}/{state['total']} processed. Output: {state['out_dir']}."
        progress = html.Div(
            [html.Div(msg, className="batch-progress-line batch-progress-done")],
        )
        _reset_psens_state()
        return progress, panel, msg, True
    return dash.no_update, dash.no_update, dash.no_update, True


@app.callback(
    Output("gtcmp-results", "children"),
    Output("gtcmp-status", "children"),
    Output("gtcmp-batch-folder-state", "data"),
    Input("gtcmp-run-button", "n_clicks"),
    State("gtcmp-verified-folder", "value"),
    State("gtcmp-batch-folder", "value"),
    prevent_initial_call=True,
)
def gtcmp_run(n_clicks, verified_folder, batch_folder):
    if not n_clicks:
        raise dash.exceptions.PreventUpdate
    verified_folder = (verified_folder or "").strip()
    batch_folder = (batch_folder or "").strip()
    if not verified_folder or not batch_folder:
        return dash.no_update, "Provide both folder paths.", dash.no_update
    try:
        report = compute_ground_truth_report(verified_folder, batch_folder)
    except Exception as exc:
        return dash.no_update, f"⚠ Failed: {exc}", dash.no_update

    # Persist alongside other test outputs
    try:
        out_dir = EXPORT_ROOT / "tests" / f"ground_truth_comparison_{datetime.now().strftime('%Y%m%dT%H%M%S')}"
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "summary.json").write_text(json.dumps(report, indent=2))
        save_msg = f"  Saved to {out_dir}."
    except Exception as exc:
        save_msg = f"  (save failed: {exc})"

    n_pairs = report.get("n_pairs", 0)
    n_unmatched = report.get("n_unmatched", 0)
    panel = make_gt_test_results_panel(report)
    status = f"Matched {n_pairs} pair(s); {n_unmatched} unmatched.{save_msg}"
    return panel, status, batch_folder


# Click "Inspect" on a pair row → store selected pair
@app.callback(
    Output("gtcmp-selected-pair", "data"),
    Input({"type": "gtcmp-inspect", "image_filename": dash.ALL, "run_id": dash.ALL}, "n_clicks"),
    prevent_initial_call=True,
)
def gtcmp_select_pair(_clicks):
    ctx = dash.callback_context
    triggered = ctx.triggered_id
    triggered_value = ctx.triggered[0].get("value") if ctx.triggered else None
    if not isinstance(triggered, dict) or not (triggered_value or 0) > 0:
        raise dash.exceptions.PreventUpdate
    return {"image_filename": triggered.get("image_filename", ""), "run_id": triggered.get("run_id", "")}


# Selected pair → render detail view (image + 3 color-coded graphs + diff lists)
@app.callback(
    Output("gtcmp-detail", "children"),
    Input("gtcmp-selected-pair", "data"),
    State("gtcmp-verified-folder", "value"),
    State("gtcmp-batch-folder-state", "data"),
)
def gtcmp_render_detail(pair, verified_folder, batch_folder):
    if not pair or not pair.get("image_filename"):
        return None
    image_filename = pair["image_filename"]
    run_id = pair.get("run_id", "")

    # Load GT
    gt_path = Path(verified_folder or "").expanduser().resolve() / f"{image_filename}.gt.json"
    if not gt_path.exists():
        return html.Div(f"GT not found: {gt_path}", className="empty-state")
    try:
        gt = json.loads(gt_path.read_text())
    except Exception as exc:
        return html.Div(f"GT parse failed: {exc}", className="empty-state")

    # Load batch run
    batch_root = Path(batch_folder or "").expanduser().resolve()
    sr_path = batch_root / run_id / "structured_response.json"
    if not sr_path.exists():
        return html.Div(f"Batch run not found: {sr_path}", className="empty-state")
    try:
        payload = json.loads(sr_path.read_text())
        run = payload.get("structured_response", {})
    except Exception as exc:
        return html.Div(f"Run parse failed: {exc}", className="empty-state")

    graph_a = run.get("causal_graph", {}) or {}
    graph_b = run.get("graph_b", {}) or {}
    gt_graph = {"nodes": gt.get("nodes") or [], "edges": gt.get("edges") or []}

    # Build the GT edge key sets (strict + fuzzy) for coloring
    def ekey(e):
        return (
            str(e.get("source", "")).strip(),
            str(e.get("via_state", "")).strip(),
            str(e.get("effect", "")).strip(),
            str(e.get("target", "")).strip(),
        )
    gt_keys = {ekey(e) for e in gt_graph["edges"]}
    a_keys = {ekey(e) for e in graph_a.get("edges", []) or []}
    b_keys = {ekey(e) for e in graph_b.get("edges", []) or []}

    # Fuzzy + topological keys for soft / topological matching
    gt_nodes_by_id = {n.get("id", ""): n for n in gt_graph.get("nodes") or []}
    gt_fuzzy = {_fuzzy_edge_key(e, gt_nodes_by_id) for e in gt_graph["edges"]}
    gt_topo = {_topological_edge_key(e, gt_nodes_by_id) for e in gt_graph["edges"]}

    only_gt = gt_keys - a_keys - b_keys
    only_a = a_keys - gt_keys
    only_b = b_keys - gt_keys
    in_a_gt = a_keys & gt_keys
    in_b_gt = b_keys & gt_keys

    # Soft + topological match counts
    soft_a = compare_graphs_soft(graph_a, gt_graph)
    soft_b = compare_graphs_soft(graph_b, gt_graph)
    topo_a = compare_graphs_topological(graph_a, gt_graph)
    topo_b = compare_graphs_topological(graph_b, gt_graph)

    def fmt_edge(t):
        s, via, eff, tgt = t
        return f"{s} —[{eff} | via:{via}]→ {tgt}"

    # Image preview
    img_path = batch_root / run_id / image_filename
    if img_path.exists():
        mime = MIME_BY_EXT.get(img_path.suffix.lower(), "image/jpeg")
        img_block = html.Img(src=image_bytes_to_data_url(img_path.read_bytes(), mime), className="embedded-preview")
    else:
        img_block = html.Div(f"(image not found: {img_path})", className="empty-state")

    return html.Div(
        [
            html.Div(f"Inspecting: {image_filename}  (run: {run_id})", className="report-section-label"),
            html.Div(
                [
                    html.Div(img_block, className="gtcmp-image-col"),
                    html.Div(
                        [
                            html.Div("Edge legend", className="gtcmp-legend-title"),
                            html.Div([
                                html.Span(className="gtcmp-legend-swatch gtcmp-legend-match"),
                                html.Span("strict match (exact tuple)", className="gtcmp-legend-text"),
                            ], className="gtcmp-legend-row"),
                            html.Div([
                                html.Span(className="gtcmp-legend-swatch gtcmp-legend-soft"),
                                html.Span("soft match (label hierarchy + state syn + effect close-pair)", className="gtcmp-legend-text"),
                            ], className="gtcmp-legend-row"),
                            html.Div([
                                html.Span(className="gtcmp-legend-swatch gtcmp-legend-topo"),
                                html.Span("topological match (state IGNORED — same source/effect/target classes)", className="gtcmp-legend-text"),
                            ], className="gtcmp-legend-row"),
                            html.Div([
                                html.Span(className="gtcmp-legend-swatch gtcmp-legend-miss"),
                                html.Span("no match (false positive)", className="gtcmp-legend-text"),
                            ], className="gtcmp-legend-row"),
                            html.Div([
                                html.Span(className="gtcmp-legend-swatch gtcmp-legend-gt"),
                                html.Span("GT reference (in GT graph)", className="gtcmp-legend-text"),
                            ], className="gtcmp-legend-row"),
                        ],
                        className="gtcmp-legend",
                    ),
                ],
                className="gtcmp-image-row",
            ),
            # Three graphs side-by-side
            html.Div(
                [
                    html.Div(
                        [
                            html.Div(f"Ground Truth ({len(gt_keys)} edges)", className="gtcmp-graph-title"),
                            make_graph_diff_viewer(gt_graph, gt_keys, elem_id=f"gtcmp-graph-gt-{run_id}", role="gt"),
                        ],
                        className="gtcmp-graph-col",
                    ),
                    html.Div(
                        [
                            html.Div(
                                f"Graph A ({len(a_keys)} edges · {len(in_a_gt)} strict / {int(soft_a.get('matched', 0))} soft / {int(topo_a.get('matched', 0))} topo)",
                                className="gtcmp-graph-title",
                            ),
                            make_graph_diff_viewer(
                                graph_a, gt_keys, elem_id=f"gtcmp-graph-a-{run_id}",
                                role="candidate", gt_fuzzy_keys=gt_fuzzy, gt_topo_keys=gt_topo,
                            ),
                        ],
                        className="gtcmp-graph-col",
                    ),
                    html.Div(
                        [
                            html.Div(
                                f"Graph B ({len(b_keys)} edges · {len(in_b_gt)} strict / {int(soft_b.get('matched', 0))} soft / {int(topo_b.get('matched', 0))} topo)",
                                className="gtcmp-graph-title",
                            ),
                            make_graph_diff_viewer(
                                graph_b, gt_keys, elem_id=f"gtcmp-graph-b-{run_id}",
                                role="candidate", gt_fuzzy_keys=gt_fuzzy, gt_topo_keys=gt_topo,
                            ),
                        ],
                        className="gtcmp-graph-col",
                    ),
                ],
                className="gtcmp-graphs-row",
            ),
            # Diff lists
            html.Div(
                [
                    html.Div(
                        [
                            html.Div(f"In GT but missing from BOTH A and B ({len(only_gt)})", className="diff-list-title"),
                            html.Ul([html.Li(fmt_edge(t)) for t in sorted(only_gt)], className="diff-ul") if only_gt else html.Div("(none)", className="diff-empty"),
                        ],
                        className="diff-list",
                    ),
                    html.Div(
                        [
                            html.Div(f"In A only (false positives, {len(only_a)})", className="diff-list-title"),
                            html.Ul([html.Li(fmt_edge(t)) for t in sorted(only_a)], className="diff-ul") if only_a else html.Div("(none)", className="diff-empty"),
                        ],
                        className="diff-list",
                    ),
                    html.Div(
                        [
                            html.Div(f"In B only (false positives, {len(only_b)})", className="diff-list-title"),
                            html.Ul([html.Li(fmt_edge(t)) for t in sorted(only_b)], className="diff-ul") if only_b else html.Div("(none)", className="diff-empty"),
                        ],
                        className="diff-list",
                    ),
                ],
                className="diff-grid",
            ),
        ],
        className="gtcmp-detail",
    )


if __name__ == "__main__":
    app.run(debug=True, port=5005)
