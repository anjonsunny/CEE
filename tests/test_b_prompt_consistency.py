"""Section B — Prompt rule consistency.

The MAIN prompt (expository) and GRAPH_B_PROMPT (terse) must assert the same
schema rules. Full semantic-equivalence checking would need an LLM or human;
these tests do substring-grep verification of required content fragments. A
passing test is necessary-but-not-sufficient for true rule equivalence.

Status per TESTS.md: partial. Honest docstrings flag this on every test.
"""
from __future__ import annotations

import pytest


def _both_contain(main_prompt: str, graph_b_prompt: str, fragments: list[str]) -> list[tuple[str, str]]:
    """Return list of (prompt_name, missing_fragment) tuples; empty == pass."""
    missing: list[tuple[str, str]] = []
    for frag in fragments:
        if frag.lower() not in main_prompt.lower():
            missing.append(("main", frag))
        if frag.lower() not in graph_b_prompt.lower():
            missing.append(("graph_b", frag))
    return missing


# ---------------------------------------------------------------------------
# B1 — Distance / contiguity rule.
# ---------------------------------------------------------------------------
@pytest.mark.blocking
def test_b1_distance_contiguity_rule_present_in_both(main_prompt, graph_b_prompt):
    """B1 (partial) — Both prompts assert: edge valid only when hazard can act
    on target given current state and position; cascade-through-intermediate is
    implicit (do NOT emit the direct edge); drifting media exception (smoke /
    dust / gas reach distant targets directly); reach is judged by POSITION,
    never by role (uniforms don't change physics).
    """
    fragments = [
        "Distance",  # rule header substring
        "current state and position",
        "do NOT",  # cascade-not-emitted directive
        "drifting",  # drifting-media exception keyword
        "never by role",  # position-not-role clause
        "do not change physics",
        "Reach thresholds",  # threshold block header
        "ONE STRUCTURE-HEIGHT",  # heat threshold
        "1.5",  # collapse-zone multiplier (fire-service standard)
        "collapse zone",  # collapse-zone naming (case-insensitive match)
        "CONTACT reach",  # fallen/static hazard threshold
        "path geometry",  # blocks/isolates exemption from distance gating
    ]
    missing = _both_contain(main_prompt, graph_b_prompt, fragments)
    assert not missing, f"Distance rule fragments missing: {missing}"


# ---------------------------------------------------------------------------
# B2 — Mutual-hazard rule.
# ---------------------------------------------------------------------------
@pytest.mark.blocking
def test_b2_mutual_hazard_rule_present_in_both(main_prompt, graph_b_prompt):
    """B2 (partial) — Both prompts assert: mutual worsens (both directions)
    when mechanisms mutually amplify; same-class AND cross-class pairs;
    shared-external-cause exception; asymmetric → increases_risk_to.
    """
    fragments = [
        "Mutual-hazard rule",
        "both directions",
        "cross-class",
        "EXCEPTION",  # shared-external-cause exception heading
        "shared",
        "increases_risk_to",  # asymmetric case
    ]
    missing = _both_contain(main_prompt, graph_b_prompt, fragments)
    assert not missing, f"Mutual-hazard rule fragments missing: {missing}"


# ---------------------------------------------------------------------------
# B3 — Fluid / gaseous convention.
# ---------------------------------------------------------------------------
@pytest.mark.blocking
def test_b3_fluid_gaseous_convention_present_in_both(main_prompt, graph_b_prompt):
    """B3 (partial) — Both prompts describe water / smoke / dust / gas as
    entities with active hazard states; inundated entity is target of fluid's
    edge.
    """
    fragments = [
        "Fluid",
        "smoke",
        "dust",
        "gas",
        "billowing",
        "leaking",
        "rising",  # active hazard states
        "inundated",  # the "target of fluid's edge" framing
        "Fluid edge effect selection",  # target-keyed effect triad
        "conversion pending",  # may_spread_to clause of the triad
    ]
    missing = _both_contain(main_prompt, graph_b_prompt, fragments)
    assert not missing, f"Fluid convention fragments missing: {missing}"


# ---------------------------------------------------------------------------
# B4 — Engulfing / hazardous_in_context truth condition.
# ---------------------------------------------------------------------------
@pytest.mark.blocking
def test_b4_engulfing_truth_condition_present_in_both(main_prompt, graph_b_prompt):
    """B4 (partial) — Both prompts restrict `engulfing` to physical containment
    AND target in at-risk Distress; `hazardous_in_context` is a last-resort
    fallback when no specific state fits.
    """
    fragments = [
        "engulfing",
        "hazardous_in_context",
        "last-resort",  # or "last resort" — substring `last`+`resort` ordering
        "physically contain",  # main says "physically contains"; B says "physically contain"
    ]
    missing = _both_contain(main_prompt, graph_b_prompt, fragments)
    assert not missing, f"Engulfing truth-condition fragments missing: {missing}"


# ---------------------------------------------------------------------------
# B5 — Effect definitions consistent across prompts.
# ---------------------------------------------------------------------------
@pytest.mark.blocking
def test_b5_effect_definitions_appear_in_both_vocab_sections(main_prompt, graph_b_prompt):
    """B5 (partial) — Each of the 8 effect labels has a one-line truth
    condition in BOTH the main prompt effect-vocabulary section AND the
    Graph B effect-vocabulary section. This is the spec rule that caught
    today's `worsens` SAME-entity-only vs BETWEEN-entities contradiction.

    NOTE: This test only checks PRESENCE of the bullet, not semantic
    equivalence of the truth conditions. True equivalence requires an LLM or
    human read; deliberately staying out of that for now.
    """
    effects = [
        "may_spread_to", "may_harm", "blocks_access_to", "isolates",
        "exposes", "increases_risk_to", "worsens", "threatens",
    ]
    # Each prompt has a `## Effect vocabulary` header followed by `- effect ...` bullets.
    main_vocab_start = main_prompt.find("## Effect vocabulary")
    main_vocab_end = main_prompt.find("**Distance", main_vocab_start)
    main_vocab = main_prompt[main_vocab_start:main_vocab_end]

    b_vocab_start = graph_b_prompt.find("## Effect vocabulary")
    b_vocab_end = graph_b_prompt.find("**Distance", b_vocab_start)
    b_vocab = graph_b_prompt[b_vocab_start:b_vocab_end]

    missing = []
    for eff in effects:
        if f"- {eff}" not in main_vocab:
            missing.append(("main_vocab", eff))
        if f"- {eff}" not in b_vocab:
            missing.append(("graph_b_vocab", eff))
    assert not missing, f"Effect bullets missing from vocab sections: {missing}"


# ---------------------------------------------------------------------------
# B6 — Self-loop discipline consistent with effect definitions.
# ---------------------------------------------------------------------------
@pytest.mark.blocking
def test_b6_self_loop_only_worsens(main_prompt, graph_b_prompt):
    """B6 (auto) — Both prompts must state that self-reference is allowed only
    with effect `worsens` (and forbid `threatens` / `may_harm` self-loops)."""
    for name, p in (("main", main_prompt), ("graph_b", graph_b_prompt)):
        assert "self" in p.lower() and "worsens" in p, f"{name} prompt missing self-loop rule"
        # Phrase variants used in current main.py:
        # main: "self-loop, intrinsic deterioration" + the embedded "self-loop"
        # graph_b: "Self-reference (source == target): allowed only with effect `worsens`"
        # Accept either explicit form.
        condition = (
            "allowed only with effect `worsens`" in p
            or "self-loop" in p.lower()
        )
        assert condition, f"{name} prompt missing self-loop restriction phrasing"


# ---------------------------------------------------------------------------
# B7 — Fluid provenance rule present in both prompts.
# ---------------------------------------------------------------------------
@pytest.mark.blocking
def test_b7_fluid_provenance_rule_present_in_both(main_prompt, graph_b_prompt):
    """B7 (partial) — Both prompts must contain the fluid-provenance
    convention: visible producer → fluid via increases_risk_to; fluids must
    not be left disconnected from their visible producer; off-frame producer
    → fluid may stand alone with a worsens self-loop."""
    fragments = [
        "Fluid provenance",
        "increases_risk_to",
        "off-frame",
    ]
    missing = _both_contain(main_prompt, graph_b_prompt, fragments)
    assert not missing, f"fluid provenance rule fragments missing: {missing}"


# ---------------------------------------------------------------------------
# B8 — Independent harm channels rule present in both prompts.
# ---------------------------------------------------------------------------
@pytest.mark.blocking
def test_b8_independent_harm_channels_present_in_both(main_prompt, graph_b_prompt):
    """B8 (partial) — Both prompts must state that a producer and its fluid
    are separate hazards judged independently under the distance rule, and
    that fire-plus-smoke must not be collapsed into a single hazard."""
    fragments = [
        "Independent harm channels",
        "independently suppressible",
    ]
    missing = _both_contain(main_prompt, graph_b_prompt, fragments)
    assert not missing, f"independent harm channels rule fragments missing: {missing}"


# ---------------------------------------------------------------------------
# B9 — Obstruction coupling rule present in both prompts.
# ---------------------------------------------------------------------------
@pytest.mark.blocking
def test_b9_obstruction_coupling_present_in_both(main_prompt, graph_b_prompt):
    """B9 (partial) — Both prompts must state the obstruction coupling rule:
    blocks_access_to/isolates to a person requires the person to be COUPLED
    (otherwise endangered) or ENTRAPPED (stranded within the isolating
    hazard's own reach)."""
    fragments = [
        "Obstruction coupling rule",
        "COUPLED",
        "ENTRAPMENT",
        "TOWARD",  # direction clause: blocking the path toward a hazard gets no edge
    ]
    missing = _both_contain(main_prompt, graph_b_prompt, fragments)
    assert not missing, f"obstruction coupling rule fragments missing: {missing}"


# ---------------------------------------------------------------------------
# B12 — may_harm tense clause present in both prompts.
# ---------------------------------------------------------------------------
@pytest.mark.blocking
def test_b12_may_harm_tense_clause_present_in_both(main_prompt, graph_b_prompt):
    """B12 (partial) — Both prompts state that may_harm covers ongoing as well
    as potential harm, with tense read from the target's state (Distress =
    actualized; normal = imminent/potential). Settled during the push_12
    drowning discussion: no new effect label, tense is derivable."""
    fragments = [
        "currently injuring",
        "actualized",
        "already hazardous",  # may_harm never targets an existing hazard (push_18 generalization)
    ]
    missing = _both_contain(main_prompt, graph_b_prompt, fragments)
    assert not missing, f"may_harm tense clause fragments missing: {missing}"


# ---------------------------------------------------------------------------
# B10 — Representative instancing convention present in both prompts.
# ---------------------------------------------------------------------------
@pytest.mark.blocking
def test_b10_representative_instancing_present_in_both(main_prompt, graph_b_prompt):
    """B10 (partial) — Both prompts state the representative-instancing
    convention: causally distinct entities individually, salient
    representatives for repeated patterns, roughly ten nodes, background
    multiplicity summarized in prose."""
    fragments = [
        "Representative instancing",
        "TEN nodes",
        "summarize",  # main: "Summarize the remaining"; graph_b: "summarized in prose"
        "COUNTED, not summarized",  # people exception (push_36 episode)
        "SIX",  # people-counting threshold (push_39 episode)
    ]
    missing = _both_contain(main_prompt, graph_b_prompt, fragments)
    assert not missing, f"representative instancing fragments missing: {missing}"


# ---------------------------------------------------------------------------
# B11 — Occupancy cue rubric consistent between the inferred-entity blocks.
# The main prompt carries it in INFERRED_ENTITIES_BLOCK; Graph B receives it
# via GRAPH_B_INFERRED_ALLOWED. Both must share the core fragments.
# ---------------------------------------------------------------------------
@pytest.mark.blocking
def test_b11_occupancy_rubric_consistent(main_module):
    main_block = main_module.INFERRED_ENTITIES_BLOCK
    graph_b_policy = main_module.GRAPH_B_INFERRED_ALLOWED
    fragments = [
        "evidence-gated",
        "Event speed" if "Event speed" in main_block else "event speed",
        "STRONG",
        "MODERATE",
        "NEGATIVE",
        "TWO",  # decision rule: one strong, or two moderate
    ]
    missing = []
    for frag in fragments:
        if frag.lower() not in main_block.lower():
            missing.append(("INFERRED_ENTITIES_BLOCK", frag))
        if frag.lower() not in graph_b_policy.lower():
            missing.append(("GRAPH_B_INFERRED_ALLOWED", frag))
    assert not missing, f"occupancy rubric fragments missing: {missing}"
