"""Section A — Schema vocabulary consistency.

The state/effect vocabularies appear in three places: Python sets in main.py,
prompt strings in main.py, and the GT editor dropdown lists. Drift between
any two breaks comparison. These tests are pure structural Python — no Qwen,
no fixtures, no I/O beyond reading main.py once.
"""
from __future__ import annotations

import re

import pytest


# ---------------------------------------------------------------------------
# Prompt parsing helpers — locate the state-list paragraphs by stable
# substring anchors, then tokenize the comma-separated lists.
# ---------------------------------------------------------------------------
def _extract_main_prompt_states(main_prompt: str, header_anchor: str) -> set[str]:
    """Find the line block that starts with `header_anchor:` in the MAIN prompt
    and return the set of comma-separated state tokens that follow until a
    blank line (or until the next bold ** marker)."""
    idx = main_prompt.find(header_anchor)
    assert idx != -1, f"Could not locate '{header_anchor}' in main prompt."
    # Skip past the header line; take the next ~6 physical lines worth of text
    # until we hit a blank line.
    tail = main_prompt[idx + len(header_anchor):]
    # Stop at the first blank line (paragraph break).
    block_end = tail.find("\n\n")
    block = tail[: block_end if block_end != -1 else 2000]
    # The first character should be a newline-ish then the list itself.
    # Pull only comma-separated lowercase tokens (state words).
    tokens = re.findall(r"\b[a-z][a-z_]+\b", block)
    return set(tokens)


def _extract_graph_b_states(graph_b_prompt: str, header_anchor: str, end_anchor: str) -> set[str]:
    """For the Graph B prompt, states are inline on a single line.
    Slice between the anchor and the end of that line / next anchor.
    """
    start = graph_b_prompt.find(header_anchor)
    assert start != -1, f"'{header_anchor}' missing from Graph B prompt."
    after = start + len(header_anchor)
    end = graph_b_prompt.find(end_anchor, after) if end_anchor else len(graph_b_prompt)
    chunk = graph_b_prompt[after : end if end != -1 else after + 1500]
    # Just the first comma-list line(s) — stop at a period that ends the list
    # before any restricted-use sentence.
    # Conservative: take only tokens that look like single lowercase words.
    tokens = re.findall(r"\b[a-z][a-z_]+\b", chunk)
    return set(tokens)


@pytest.fixture
def hazard_states_from_main_prompt(main_prompt: str) -> set[str]:
    raw = _extract_main_prompt_states(
        main_prompt, "Hazard-bearing states (threat-producing"
    )
    # Filter to only words that look like actual state vocab — exclude the
    # surrounding prose words. We require the words to be lowercase, length>=3.
    # The list is enumerated under the header; the prose immediately after
    # begins with **`engulfing` and `hazardous_in_context` — restricted use.**
    # That bold marker terminates the comma list. Slice on that.
    # Re-extract more precisely:
    idx = main_prompt.find("Hazard-bearing states (threat-producing")
    # Skip past the header LINE entirely so its noise words don't pollute.
    line_end = main_prompt.find("\n", idx)
    end = main_prompt.find("**`engulfing`", idx)
    block = main_prompt[line_end:end]
    tokens = set(re.findall(r"\b[a-z][a-z_]+\b", block))
    return tokens


@pytest.fixture
def at_risk_states_from_main_prompt(main_prompt: str) -> set[str]:
    idx = main_prompt.find("At-risk states (victim")
    line_end = main_prompt.find("\n", idx)
    # The first bold prose block after the list terminates the comma list
    # (same pattern as the hazard-states fixture and its engulfing marker).
    end = main_prompt.find("**Three behavioral families", idx)
    if end == -1:
        end = main_prompt.find("**Living beings only", idx)
    if end == -1:
        end = main_prompt.find("Normal states", idx)
    block = main_prompt[line_end:end]
    tokens = set(re.findall(r"\b[a-z][a-z_]+\b", block))
    return tokens


@pytest.fixture
def normal_states_from_main_prompt(main_prompt: str) -> set[str]:
    idx = main_prompt.find("Normal states:")
    line_end = main_prompt.find("\n", idx)
    after = main_prompt[line_end:]
    para_end = after.find("\n\n")
    block = after[:para_end if para_end != -1 else 600]
    tokens = set(re.findall(r"\b[a-z][a-z_]+\b", block))
    return tokens


@pytest.fixture
def effect_labels_from_main_prompt(main_prompt: str) -> set[str]:
    idx = main_prompt.find("## Effect vocabulary")
    after = main_prompt[idx:]
    # Stop at the first bold-text rule paragraph or next ## header.
    end = after.find("**Distance")
    block = after[:end if end != -1 else 1500]
    # Effects are at the start of bullet lines: `- effect_name      — ...`
    tokens = set(re.findall(r"^- ([a-z_]+)\s", block, re.MULTILINE))
    return tokens


@pytest.fixture
def hazard_states_from_graph_b(graph_b_prompt: str) -> set[str]:
    start = graph_b_prompt.find("Hazard-bearing states (entity is a SOURCE of harm):")
    assert start != -1
    after = start + len("Hazard-bearing states (entity is a SOURCE of harm):")
    # End at the period that closes the sentence right before `engulfing` clause.
    end = graph_b_prompt.find(". `engulfing`", after)
    block = graph_b_prompt[after:end if end != -1 else after + 800]
    tokens = set(re.findall(r"\b[a-z][a-z_]+\b", block))
    return tokens


@pytest.fixture
def at_risk_states_from_graph_b(graph_b_prompt: str) -> set[str]:
    start = graph_b_prompt.find("At-risk states (entity is a TARGET of harm — Distress kind):")
    after = start + len("At-risk states (entity is a TARGET of harm — Distress kind):")
    end = graph_b_prompt.find(".", after)
    block = graph_b_prompt[after:end]
    tokens = set(re.findall(r"\b[a-z][a-z_]+\b", block))
    return tokens


@pytest.fixture
def normal_states_from_graph_b(graph_b_prompt: str) -> set[str]:
    start = graph_b_prompt.find("Normal states:")
    after = start + len("Normal states:")
    # Next \n\n terminates the line
    end = graph_b_prompt.find("\n\n", after)
    block = graph_b_prompt[after:end]
    tokens = set(re.findall(r"\b[a-z][a-z_]+\b", block))
    return tokens


@pytest.fixture
def effect_labels_from_graph_b(graph_b_prompt: str) -> set[str]:
    idx = graph_b_prompt.find("## Effect vocabulary")
    after = graph_b_prompt[idx:]
    end = after.find("**Distance")
    block = after[:end if end != -1 else 1500]
    tokens = set(re.findall(r"^- ([a-z_]+)\s", block, re.MULTILINE))
    return tokens


# ---------------------------------------------------------------------------
# A1–A5 — Python set vs prompt list equality.
# ---------------------------------------------------------------------------
@pytest.mark.blocking
def test_a1_hazard_states_match_main_prompt(main_module, hazard_states_from_main_prompt):
    """A1 — HAZARD_BEARING_STATES set matches the main Qwen prompt list."""
    assert hazard_states_from_main_prompt == main_module.HAZARD_BEARING_STATES, (
        f"In set but not in prompt: {main_module.HAZARD_BEARING_STATES - hazard_states_from_main_prompt}\n"
        f"In prompt but not in set: {hazard_states_from_main_prompt - main_module.HAZARD_BEARING_STATES}"
    )


@pytest.mark.blocking
def test_a2_hazard_states_match_graph_b_prompt(main_module, hazard_states_from_graph_b):
    """A2 — HAZARD_BEARING_STATES set matches the Graph B prompt list."""
    assert hazard_states_from_graph_b == main_module.HAZARD_BEARING_STATES, (
        f"In set but not in Graph B prompt: "
        f"{main_module.HAZARD_BEARING_STATES - hazard_states_from_graph_b}\n"
        f"In Graph B prompt but not in set: "
        f"{hazard_states_from_graph_b - main_module.HAZARD_BEARING_STATES}"
    )


@pytest.mark.blocking
def test_a3_at_risk_states_match_both_prompts(
    main_module, at_risk_states_from_main_prompt, at_risk_states_from_graph_b
):
    """A3 — AT_RISK_STATES set matches both prompts."""
    assert at_risk_states_from_main_prompt == main_module.AT_RISK_STATES, (
        f"Main prompt diff: "
        f"set-only={main_module.AT_RISK_STATES - at_risk_states_from_main_prompt}, "
        f"prompt-only={at_risk_states_from_main_prompt - main_module.AT_RISK_STATES}"
    )
    assert at_risk_states_from_graph_b == main_module.AT_RISK_STATES, (
        f"Graph B prompt diff: "
        f"set-only={main_module.AT_RISK_STATES - at_risk_states_from_graph_b}, "
        f"prompt-only={at_risk_states_from_graph_b - main_module.AT_RISK_STATES}"
    )


@pytest.mark.blocking
def test_a4_normal_states_match_both_prompts(
    main_module, normal_states_from_main_prompt, normal_states_from_graph_b
):
    """A4 — NORMAL_STATES set matches both prompts."""
    assert normal_states_from_main_prompt == main_module.NORMAL_STATES, (
        f"Main prompt diff: "
        f"set-only={main_module.NORMAL_STATES - normal_states_from_main_prompt}, "
        f"prompt-only={normal_states_from_main_prompt - main_module.NORMAL_STATES}"
    )
    assert normal_states_from_graph_b == main_module.NORMAL_STATES, (
        f"Graph B prompt diff: "
        f"set-only={main_module.NORMAL_STATES - normal_states_from_graph_b}, "
        f"prompt-only={normal_states_from_graph_b - main_module.NORMAL_STATES}"
    )


@pytest.mark.blocking
def test_a5_effect_labels_match_both_prompts(
    main_module, effect_labels_from_main_prompt, effect_labels_from_graph_b
):
    """A5 — EFFECT_LABELS set matches both prompts (exactly 8 effects)."""
    assert len(main_module.EFFECT_LABELS) == 8, (
        f"EFFECT_LABELS has {len(main_module.EFFECT_LABELS)} entries; expected 8."
    )
    assert effect_labels_from_main_prompt == main_module.EFFECT_LABELS, (
        f"Main prompt diff: "
        f"set-only={main_module.EFFECT_LABELS - effect_labels_from_main_prompt}, "
        f"prompt-only={effect_labels_from_main_prompt - main_module.EFFECT_LABELS}"
    )
    assert effect_labels_from_graph_b == main_module.EFFECT_LABELS, (
        f"Graph B prompt diff: "
        f"set-only={main_module.EFFECT_LABELS - effect_labels_from_graph_b}, "
        f"prompt-only={effect_labels_from_graph_b - main_module.EFFECT_LABELS}"
    )


# ---------------------------------------------------------------------------
# A6 — GT editor dropdowns match code vocabulary.
# ---------------------------------------------------------------------------
@pytest.mark.blocking
def test_a6_gt_dropdowns_match_code_vocabulary(main_module):
    """A6 — GT_* lists contain exactly the same elements as the corresponding sets."""
    assert set(main_module.GT_HAZARD_STATES) == main_module.HAZARD_BEARING_STATES
    assert set(main_module.GT_AT_RISK_STATES) == main_module.AT_RISK_STATES
    assert set(main_module.GT_NORMAL_STATES) == main_module.NORMAL_STATES
    # GT_EFFECTS has an "undetermined" sentinel — strip it before comparing.
    gt_effects_clean = set(main_module.GT_EFFECTS) - {main_module.UNDETERMINED}
    assert gt_effects_clean == main_module.EFFECT_LABELS


# ---------------------------------------------------------------------------
# A7–A8, A12–A13 — Synonym table sanity.
# ---------------------------------------------------------------------------
@pytest.mark.blocking
def test_a7_state_synonyms_canonicals_valid(main_module):
    """A7 — every STATE_SYNONYMS value is a canonical in one of the three sets."""
    canonical_universe = (
        main_module.HAZARD_BEARING_STATES
        | main_module.AT_RISK_STATES
        | main_module.NORMAL_STATES
    )
    bad = {
        syn: canon
        for syn, canon in main_module.STATE_SYNONYMS.items()
        if canon not in canonical_universe
    }
    assert not bad, f"Synonyms mapping to non-canonical values: {bad}"


@pytest.mark.warn
def test_a8_state_synonyms_keys_not_canonical(main_module):
    """A8 — no STATE_SYNONYMS key is itself a canonical state.

    NOTE: As of this writing, `collapsing` is BOTH a canonical hazard state
    AND a STATE_SYNONYMS key (mapping to `collapsed`). This is a real
    self-referential entry per the test's intent and will fail until Sunny
    resolves it. Reported, not silently allowed.
    """
    canonical_universe = (
        main_module.HAZARD_BEARING_STATES
        | main_module.AT_RISK_STATES
        | main_module.NORMAL_STATES
    )
    collisions = {
        syn for syn in main_module.STATE_SYNONYMS.keys() if syn in canonical_universe
    }
    assert not collisions, (
        f"Synonym keys that are also canonical states: {sorted(collisions)}. "
        "These are likely copy-paste errors or in-flight migrations."
    )


@pytest.mark.blocking
def test_a12_synonym_canonicalization_idempotent(main_module):
    """A12 — canonicalize(canonicalize(x)) == canonicalize(x) for every
    vocabulary state."""
    universe = (
        main_module.HAZARD_BEARING_STATES
        | main_module.AT_RISK_STATES
        | main_module.NORMAL_STATES
        | set(main_module.STATE_SYNONYMS.keys())
    )
    bad_chains: dict[str, tuple[str, str]] = {}
    for state in universe:
        once = main_module.canonicalize_state(state)
        twice = main_module.canonicalize_state(once)
        if once != twice:
            bad_chains[state] = (once, twice)
    assert not bad_chains, f"Non-idempotent canonicalization chains: {bad_chains}"


@pytest.mark.warn
def test_a13_state_synonyms_single_valued(main_module):
    """A13 — Every synonym key maps to exactly one canonical (a string).
    Structural sentinel for any future migration to multi-valued mapping.
    """
    bad = {
        syn: type(val).__name__
        for syn, val in main_module.STATE_SYNONYMS.items()
        if not isinstance(val, str)
    }
    assert not bad, f"Non-string synonym values: {bad}"


# ---------------------------------------------------------------------------
# A9 — Effect partition coverage.
# ---------------------------------------------------------------------------
@pytest.mark.blocking
def test_a9_effect_partitions_cover_all_effects(main_module):
    """A9 — HARM_EFFECTS ∪ PROPAGATE_EFFECTS ∪ STRUCTURAL_EFFECTS == EFFECT_LABELS, no overlaps."""
    union = (
        main_module.HARM_EFFECTS
        | main_module.PROPAGATE_EFFECTS
        | main_module.STRUCTURAL_EFFECTS
    )
    assert union == main_module.EFFECT_LABELS, (
        f"Missing from partitions: {main_module.EFFECT_LABELS - union}\n"
        f"In partitions but not in EFFECT_LABELS: {union - main_module.EFFECT_LABELS}"
    )
    # Overlap check
    overlap_hp = main_module.HARM_EFFECTS & main_module.PROPAGATE_EFFECTS
    overlap_hs = main_module.HARM_EFFECTS & main_module.STRUCTURAL_EFFECTS
    overlap_ps = main_module.PROPAGATE_EFFECTS & main_module.STRUCTURAL_EFFECTS
    assert not overlap_hp, f"HARM ∩ PROPAGATE non-empty: {overlap_hp}"
    assert not overlap_hs, f"HARM ∩ STRUCTURAL non-empty: {overlap_hs}"
    assert not overlap_ps, f"PROPAGATE ∩ STRUCTURAL non-empty: {overlap_ps}"


# ---------------------------------------------------------------------------
# A10 — Effect partition semantic correctness (hardcoded membership).
# ---------------------------------------------------------------------------
@pytest.mark.blocking
def test_a10_effect_partition_semantic_correctness(main_module):
    """A10 — Each effect lands in the partition matching its documented intent."""
    assert {"may_harm", "threatens"}.issubset(main_module.HARM_EFFECTS)
    assert {"may_spread_to", "increases_risk_to", "worsens"}.issubset(main_module.PROPAGATE_EFFECTS)
    assert {"blocks_access_to", "isolates", "exposes"}.issubset(main_module.STRUCTURAL_EFFECTS)


# ---------------------------------------------------------------------------
# A11 — _gt_state_options structure (canonicals + synonyms with section overlay).
# ---------------------------------------------------------------------------
@pytest.mark.blocking
def test_a11_gt_state_options_includes_synonyms(main_module):
    """A11 — _gt_state_options returns each canonical state plus each
    STATE_SYNONYMS entry whose canonical belongs to that section, in the
    documented `<syn>  (→ <canon>)` label format."""
    options = main_module._gt_state_options()
    # Strip header / disabled rows.
    real = [o for o in options if not o.get("disabled")]
    values = {o["value"] for o in real}
    # All canonicals are present.
    canonical_universe = (
        main_module.HAZARD_BEARING_STATES
        | main_module.AT_RISK_STATES
        | main_module.NORMAL_STATES
    )
    missing_canon = canonical_universe - values
    assert not missing_canon, f"Canonical states missing from dropdown: {missing_canon}"
    # All synonyms (whose canonical is in the universe) are present.
    expected_syns = {
        syn
        for syn, canon in main_module.STATE_SYNONYMS.items()
        if canon in canonical_universe and syn not in canonical_universe
    }
    missing_syns = expected_syns - values
    assert not missing_syns, f"Synonyms missing from dropdown: {missing_syns}"
    # Synonym rows use the "(→ canon)" label format.
    syn_rows = [o for o in real if o["value"] in expected_syns]
    for row in syn_rows:
        assert "→" in row["label"], (
            f"Synonym row {row['value']} should display as '<syn>  (→ <canon>)'; got {row['label']!r}"
        )
