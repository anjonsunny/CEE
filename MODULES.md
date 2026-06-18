# CEE+ Module Map (everything before Stage 1)

One page to keep the system sane. Each module: what it is, what it does, and
the one question it answers about the model's causal groundedness. Read top
to bottom: each level builds on the one above. Go deep only where you need.

```
LEVEL 0  The shared language        (rulebook + tests that guard it)
LEVEL 1  The answer key             (ground truth + its protections)
LEVEL 2  Model checks WITHOUT GT    (cheap, run on any answer)
LEVEL 3  Model checks WITH GT       (need the answer key)
LEVEL 4  The aggregate              (one trust reading per scene)
   ...   Stage 1 intervention sits on top of all of this (not built yet)
```

---

## LEVEL 0: The shared language

### M1. Schema rulebook (the two prompts in main.py)
- **What:** The vocabulary (states, effects) and the rules (distance
  thresholds, label triad, mutual hazard, provenance, obstruction coupling,
  occupancy rubric, instancing).
- **Does:** Tells the model AND the human annotator how to describe a scene,
  in the same words.
- **Groundedness question it serves:** none directly. It makes the question
  ASKABLE. Without a shared language, "is the model right?" has no meaning.
  Bonus: every rule forces looking, so the rulebook doubles as a set of lie
  detectors (see M7).

### M2. Test suite (tests/, ~1750 checks)
- **What:** Automated checks that the rulebook is self-consistent (both
  prompts agree, code matches prompts) and the answer key obeys it.
- **Does:** Grades OUR work, never the model's.
- **Groundedness question:** none. It guarantees the measuring stick is not
  bent. A bent stick blames the model for our mistakes.

---

## LEVEL 1: The answer key

### M3. Ground truth + human verification (UI, GT tab)
- **What:** 70 scenes, each with a hand-checked causal graph built from the
  image under the same rulebook.
- **Does:** Defines "correct" per scene.
- **Groundedness question:** none by itself. It is the reference that Level 3
  compares against.

### M4. Golden scenes (15 frozen anchors)
- **What:** The best example scene for each rule, frozen with a fingerprint.
  Any change to a frozen scene fails a test until a human re-approves.
- **Does:** Stops the answer key from drifting silently.

### M5. Schema version stamps
- **What:** Every GT file records which rulebook version it was checked under.
- **Does:** When rules change, outdated files raise their hands automatically.

---

## LEVEL 2: Model checks that need NO answer key

These run on any model answer, cheaply, per scene. They are the "column one"
shallow checks.

### M6. Internal alignment (built, part of trust score)
- **What:** Does the model agree with ITSELF? Sentence says person_1, triple
  says person_2: contradiction.
- **Groundedness question:** "Is there one coherent picture in the model's
  head, or several?" A self-contradicting answer cannot come from a single
  causal model of the scene.

### M7. Rule conformance checker (built; Graph B's conformance now feeds trust)
- **What:** Does the model's answer obey the rulebook? Example: water
  may_harm an already-flooded house breaks the label triad.
- **Groundedness question:** "Did it look, or did it guess from habit?"
  Following the rules requires checking each target, each position, each
  feeding relationship in the image. Violations are caught lies. This is
  Layer 2 of the failure taxonomy, given teeth.

### M8. Pathology detectors (partially built)
- **What:** Characteristic bias patterns: softening danger near institutions,
  agreeing with the caption against the image, safety theater.
- **Groundedness question:** "Is the answer shaped by social habits instead
  of physics?" A grounded model treats a clinic and a house the same when
  the same fire approaches both.

---

## LEVEL 3: Model checks that NEED the answer key

### M9. Test 1 graph comparison (built: strict / soft / topological tiers)
- **What:** Compares the model's graph to the verified GT. Produces
  similarity numbers.
- **Groundedness question:** "How close is the model's picture of the scene
  to a careful human's?" Note the limit: it gives a distance, not a
  diagnosis. Two models can get the same 0.71 for opposite reasons (one has
  bad eyesight, one has bad reasoning). M7 supplies the diagnosis.

### M10. Graph A vs Graph B consistency (built)
- **What:** The same scene asked two ways: once through recommendations
  (Graph A), once as a pure causal-graph question (Graph B). Compare.
- **Groundedness question:** "Does the model's causal picture survive being
  asked differently?" A grounded picture is stable across phrasings. A
  guesser drifts, because each phrasing pulls different habits.

---

## LEVEL 4: The aggregate

### M11. Trust score (built)
- **What:** Combines fidelity, coverage, internal alignment, and pathology
  penalties into one per-scene reading. (Rule conformance is surface-only
  for now; wiring it into the score is a pending decision.)
- **Groundedness question:** "All things considered, how much should an
  operator trust this answer?"

---

## What sits on top: Stage 1 intervention (not built)

Change the world (put the fire out) and check whether the model's answer
changes the right way. This is the only module that tests imagination of
change; everything above tests reading of the present. The two-column result
(design note 11): column one = M7 violations, column two = intervention
shifts. The paper hunts the well-behaved guesser: clean column one, failing
column two.

## Known debt

- ~~Single-scene results tab is getting crowded; needs a layout pass.~~ Done
  2026-06-11: grouped into five collapsible sections following the module
  levels (scene reading → graphs → self-checks → GT checks → trust). Test H5
  pins the ids and ordering.
- Rule conformance now feeds the trust score on the GRAPH B side: B's
  conformance validity is one input to Graph B's validity weight (β), which
  discounts the A-vs-B agreement terms (2026-06-18, resolves O12). Graph A's
  conformance is still surface-only. Its BATCH tally exists (P-series): the
  Test 1 report sums violations per rule across all runs and counts close-pair
  vocabulary swaps per matched pair. The batch worker recomputes gt_validation
  against the real Graph B and passes threats + gt_validation to trust, so batch
  trust equals single-run trust (guarded by test F9). The batch REPORT now
  surfaces a Graph B validity (β) rollup — median β, weak-β run count, and
  Test 1 availability / companion divergence — in both the markdown export and
  the report panel (P5). Batch trust still aggregates the headline (deployment)
  score; the companion 'with Test 1' variant is reported as a divergence count,
  not a separate aggregate. The batch report also rolls rule violations up into
  the Meaning Generator's cognitive failure families (`family_rollup`, P6):
  dominant family + authored meaning/impact at the corpus level, matching the
  single-run takeaway.
- K-series behavioral tests await captured model outputs against goldens.
