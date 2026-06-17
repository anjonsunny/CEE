"""Section Q — Meaning Generator from Failure.

Rule violations group into cognitive failure families; the generator emits an
authored meaning + decision impact for the dominant family, deterministically.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from conftest import main_module  # noqa: E402, F401


# Q1 — every conformance rule maps to exactly one family (total coverage, no overlap).
@pytest.mark.blocking
def test_q1_family_map_total_and_disjoint(main_module):
    import re
    src = (Path(main_module.__file__).read_text())
    rules_in_code = set(re.findall(r'violation\("([a-z_]+)"', src))
    mapped = set(main_module.RULE_TO_FAMILY)
    assert rules_in_code == mapped, (
        f"family map out of sync: unmapped={rules_in_code - mapped}, "
        f"stale={mapped - rules_in_code}")
    # no rule in two families
    seen = {}
    for fam, spec in main_module.FAILURE_FAMILIES.items():
        for r in spec["rules"]:
            assert r not in seen, f"{r} in both {seen[r]} and {fam}"
            seen[r] = fam


# Q2 — clean conformance yields the grounded message + one green pill.
@pytest.mark.blocking
def test_q2_clean_is_grounded(main_module):
    out = main_module.generate_conformance_meaning({"by_rule": {}})
    assert "No rulebook violations" in out["takeaway"]
    assert len(out["pills"]) == 1 and out["pills"][0]["color"] == "green"


# Q3 — a state-blind violation produces the state-blind pattern, not a count.
@pytest.mark.blocking
def test_q3_state_blind_pattern(main_module):
    out = main_module.generate_conformance_meaning({"by_rule": {"may_harm_hazardous_target": 1}})
    assert "misreads what an entity is" in out["takeaway"].lower()
    assert "misdirect" in out["takeaway"].lower() or "triage" in out["takeaway"].lower()
    assert out["pills"][0]["color"] == "amber"  # single occurrence
    assert "may_harm_hazardous_target" in out["pills"][0]["tooltip"]


# Q4 — hallucination family is always red, even at count 1.
@pytest.mark.blocking
def test_q4_hallucination_always_red(main_module):
    out = main_module.generate_conformance_meaning({"by_rule": {"unresolved_endpoint": 1}})
    assert out["pills"][0]["color"] == "red"
    assert "fabricat" in out["takeaway"].lower() or "garbled" in out["pills"][0]["label"].lower() \
        or "hallucination" in out["pills"][0]["label"].lower()


# Q5 — count >= 2 in a cognitive family escalates to red.
@pytest.mark.blocking
def test_q5_repeat_escalates_to_red(main_module):
    out = main_module.generate_conformance_meaning(
        {"by_rule": {"may_harm_hazardous_target": 1, "distress_state_on_non_living": 1}})
    # both are state_blind -> count 2 -> red
    sb = [p for p in out["pills"] if "Misreads what an entity is" in p["label"]][0]
    assert sb["color"] == "red" and "×2" in sb["label"]


# Q6 — deterministic: same input twice, identical output.
@pytest.mark.blocking
def test_q6_deterministic(main_module):
    inp = {"by_rule": {"smoke_superset_violation": 1, "one_way_worsens": 2}}
    assert main_module.generate_conformance_meaning(inp) == main_module.generate_conformance_meaning(inp)


# Q7 — sibling generators produce a takeaway + at least one pill for each section type.
@pytest.mark.blocking
def test_q7_sibling_generators(main_module):
    al = main_module.generate_alignment_meaning({"failed_checks": 9, "score": 0.5})
    assert "self-incoherent" in al["takeaway"].lower() and al["pills"][0]["color"] == "red"
    al0 = main_module.generate_alignment_meaning({"failed_checks": 0, "score": 1.0})
    assert al0["pills"][0]["color"] == "green"

    co = main_module.generate_consistency_meaning({"topological_consistency": 0.30})
    assert "unstable" in co["takeaway"].lower() and co["pills"][0]["color"] == "red"
    co1 = main_module.generate_consistency_meaning({"topological_consistency": 0.9})
    assert co1["pills"][0]["color"] == "green"

    pa = main_module.generate_pathology_meaning({
        "active_keys": ["sycophancy", "rationalized_minimization"],
        "details": {"sycophancy": {"fired": True, "signature": "A-fidelity 0.00"},
                    "rationalized_minimization": {"fired": True, "signature": "B-coverage 0.00"}}})
    labels = [p["label"] for p in pa["pills"]]
    assert "Sycophancy" in labels and "Rationalized Minimization" in labels
    assert all(p["color"] == "red" for p in pa["pills"])
    assert "A-fidelity" in pa["pills"][0]["tooltip"]
    pa0 = main_module.generate_pathology_meaning({})
    assert pa0["pills"][0]["color"] == "green"

    acc = main_module.generate_accuracy_meaning({"b_correctness_topo": 0.2}, {"by_rule": {"may_harm_hazardous_target": 1}})
    assert "associative" in acc["takeaway"].lower()
    accng = main_module.generate_accuracy_meaning({"reason": "no verified GT"}, {})
    assert accng["pills"][0]["color"] == "grey"


# Q8 — render_meaning_header emits pill spans carrying a title (the hover popup).
@pytest.mark.blocking
def test_q8_pills_have_tooltip(main_module):
    m = main_module.generate_conformance_meaning({"by_rule": {"smoke_superset_violation": 1}})
    rendered = main_module.render_meaning_header(m)
    # walk for a span with a non-empty title attribute
    def walk(n):
        yield n
        ch = getattr(n, "children", None)
        if isinstance(ch, (list, tuple)):
            for c in ch: yield from walk(c)
        elif ch is not None:
            yield ch
    titles = [getattr(n, "title", None) for node in rendered for n in walk(node)]
    assert any(t for t in titles if t), "no pill carried a title/tooltip"
