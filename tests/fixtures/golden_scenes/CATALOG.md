# Golden Scene Catalog

Curated regression anchors for the CEE+ test suite. Each scene is the canonical
exercise of one or more schema rules. Once a scene is human-verified in the UI,
it is **frozen** here (image + verified GT + content hash in `MANIFEST.json`)
via `freeze_golden.py`. A frozen GT changing in any way fails the GOLD tests
until someone deliberately re-freezes — golden edits are an explicit reviewed
act, never a silent side effect of a sweep.

## Workflow

1. Verify the scene in the UI (GT validation tab → Accept). This writes
   `exports/ground_truth/verified/<scene>.gt.json`.
2. Freeze it: `python tests/fixtures/golden_scenes/freeze_golden.py push_02`
   (copies verified GT + image here, records sha256 in MANIFEST.json).
3. To deliberately update a golden after a schema change: re-verify in the UI,
   then re-run the freeze script with `--force`.

## Status legend

- **pending** — selected, not yet verified/frozen
- **frozen** — verified copy + hash recorded in MANIFEST.json

## The 15 golden scenes

| Scene | Status | Rules exercised |
|---|---|---|
| push_02_multi_fire_cascade | frozen | Mutual-hazard rule (same-class, dense adjacency); self-loops; fluid provenance (house_2 → smoke) |
| push_05_armed_robbery | frozen | Human threat (aiming); synonym preservation (surrendering, crouching); at-risk Distress |
| push_06_drowning_pool | frozen | Engulfing truth condition; edge-severance intervention semantics; at-risk Distress without propagating hazard |
| push_09_tanker_near_fire | frozen | Mutual-hazard rule (cross-class: fire ↔ leaking flammable); distance rule on driver |
| push_11_mixed_neighborhood | frozen | Distance rule (distant fire, no direct person edges); fluid provenance joining disjoint components; Truth Suppression probe (uniform effects across building types); ambient-haze borderline (verifier judgment recorded) |
| push_14_first_responder | frozen | Independent harm channels (heat + smoke per person); smoke-reach superset; fluid provenance |
| push_22_mudslide_buried_cars | frozen | Fluid shared-cause exception (mud → each victim, no mutual worsens between victims); rare fluid (mud, seeping) |
| push_24_flooded_gas_station_sparks | frozen | hazardous_in_context (electrified water); cross-class mutual hazard (wiring ↔ water) |
| push_41_storm_surge_coast_overview | frozen | Damage gradient; aerial POV; distance rule (entities dropped when unidentifiable at altitude) |
| push_42_wildfire_across_road | frozen | Distance rule; blocks_access_to (fire on the only access route) |
| push_61_park_saturday | frozen | Negative control — empty graph is correct; running children must NOT be fleeing |
| push_63_school_recess | frozen | Negative control + Truth Suppression false-fire test (school setting, no hazard) |
| push_64_construction_site | frozen | Negative control that LOOKS damage-like (partial structures ≠ collapsed; workers at height ≠ at-risk) |
| push_69_collapsed_confined_space | frozen | Engulfing (dust in confined void); suffocating state; fluid provenance (building → dust); collapsing-vs-collapsed visual evidence |
| push_70_charging_bull | frozen | Charging state (not rabid); running_away synonym; spectator hazard (broken fence self-loop); distance rule on distant bystanders |

Selection can change — swap a scene by editing this table and MANIFEST.json
together (test GOLD1 enforces they stay coherent).

## Coverage map (rule → golden)

- Mutual-hazard same-class → push_02
- Mutual-hazard cross-class → push_09, push_24
- Shared-cause exception → push_22
- Engulfing → push_06, push_69
- hazardous_in_context → push_24
- Distance / contiguity rule → push_11, push_41, push_42, push_70
- Independent harm channels + smoke superset → push_14
- Fluid provenance → push_02, push_11, push_14, push_69
- Self-loops / spectator hazard → push_02, push_70
- Synonym preservation → push_05, push_70
- collapsing vs collapsed → push_69
- Negative controls → push_61, push_63, push_64
- Truth Suppression probe → push_11 (positive setting), push_63 (false-fire)
- Aerial POV / entity identifiability → push_41
