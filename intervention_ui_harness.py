"""Dev render harness for the Intervention tab candidates card in main.py.

Renders the REDESIGNED make_candidates_panel from a REAL saved run: it loads the
original run's structured_response, rebuilds the image data URL from the scene image,
computes the intervention baseline + candidates LIVE (via intervention.py), and mounts
the panel with every piece it needs (detected_objects for bbox lookup, image data URL
for the hover crops, framework_suppression_picks for the algorithm pick, and
graph_b.suppression_pick for the VLM pick). The scene image is shown above the card.

Run: python intervention_ui_harness.py   (port 8051)
Switch scene via env SCENE=push_34|push_06 (default push_34), or override the run JSON
directly with INTERV_JSON=<path to a run's structured_response.json>.
"""
import os, glob, json
import dash
from dash import html
import main
import intervention

ROOT = os.path.dirname(os.path.abspath(__file__))

# ── Scene registry: original run JSON + scene image ──────────────────────────
_SCENES = {
    "push_34": {
        "json": os.path.join(
            ROOT,
            "exports/batches/batch_20260629T022646/runs/"
            "run_20260629T025302_push_34_apartment_collapse_rescue/structured_response.json"),
        "img": os.path.join(
            ROOT,
            "exports/ground_truth/candidates/push_test/push_34_apartment_collapse_rescue.jpg"),
    },
    "push_06": {
        "json": os.path.join(
            ROOT,
            "exports/batches/batch_20260629T023129_push_06_drowning_pool/structured_response.json"),
        "img": os.path.join(
            ROOT,
            "exports/ground_truth/candidates/push_test/push_06_drowning_pool.jpg"),
    },
}


def _resolve_run_json(scene: str) -> str:
    """Return the run's structured_response.json path, globbing if the canonical one
    is missing (push_06's exact path can vary batch-to-batch)."""
    override = os.environ.get("INTERV_JSON")
    if override:
        return override
    entry = _SCENES[scene]
    if os.path.exists(entry["json"]):
        return entry["json"]
    hits = glob.glob(os.path.join(
        ROOT, f"exports/batches/*/runs/*{scene}_*/structured_response.json"))
    if not hits:
        raise FileNotFoundError(f"no run JSON found for scene {scene}")
    return sorted(hits)[0]


SCENE = os.environ.get("SCENE", "push_34")
if SCENE not in _SCENES:
    SCENE = "push_34"

run_json = _resolve_run_json(SCENE)
img_path = _SCENES[SCENE]["img"]

# ── Load the run + rebuild the image data URL ────────────────────────────────
payload = json.load(open(run_json))
result = payload.get("structured_response", payload)
with open(img_path, "rb") as fh:
    data_url = main.image_bytes_to_data_url(fh.read(), "image/jpeg")

# ── Compute the intervention baseline + candidates LIVE ──────────────────────
baseline = intervention.intervention_baseline(result, data_url, gt_dir=main.GT_VERIFIED_DIR)
candidates = intervention.enumerate_candidates(baseline)

detected_objects = result.get("detected_objects") or []
framework_picks = result.get("framework_suppression_picks") or []
vlm_pick = (result.get("graph_b", {}) or {}).get("suppression_pick") or {}

candidates_panel = main.make_candidates_panel(
    candidates,
    baseline.get("trust", {}) or {},
    detected_objects,
    data_url,
    framework_picks,
    vlm_pick,
)

# ── Scene image (with bboxes drawn) above the card ───────────────────────────
overlay = main.make_overlay_preview(data_url, detected_objects) or data_url

app = dash.Dash(__name__)
# Reuse the real app's stylesheet so the harness renders faithfully (pills, hover
# tooltips hidden until hover, card styles) — otherwise hazard-tooltip shows inline.
app.index_string = main.app.index_string
app.layout = html.Div(
    [
        html.H3(f"Candidates card harness — {SCENE} ({os.path.basename(run_json)})",
                style={"fontFamily": "system-ui", "color": "#0f172a", "margin": "16px 24px 0"}),
        html.Img(src=overlay,
                 style={"maxWidth": "680px", "width": "100%", "display": "block",
                        "margin": "16px 24px", "border": "1px solid #e2e8f0",
                        "borderRadius": "8px"}),
        html.Div(candidates_panel,
                 style={"fontFamily": "system-ui, sans-serif", "maxWidth": "680px",
                        "margin": "16px 24px", "background": "#fff", "border": "1px solid #e2e8f0",
                        "borderRadius": "8px", "padding": "14px 16px"}),
    ],
    style={"background": "#f8fafc", "minHeight": "100vh"},
)

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8051, debug=False)
