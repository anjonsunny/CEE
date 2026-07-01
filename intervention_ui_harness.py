"""Dev render harness for the Intervention tab UI, built incrementally by the
agentic UI workflow. Mounts the intervention panel fed a SAVED intervention JSON
(no live VLM), so each UI part can be rendered and screenshotted for reflection.

Run: python intervention_ui_harness.py   (port 8051)
Pick the scene via env INTERV_JSON=<path to a *_intervention.json>.
Once intervention UI builders exist in main.py, this imports and mounts them;
until then it renders a spike placeholder proving data -> component -> screenshot.
"""
import os, json
import dash
from dash import html
import main

SCRATCH = "/private/tmp/claude-501/-Users-sunny-Documents-CEE-/c97ec532-4800-4911-b105-0989381f984b/scratchpad"
INTERV_JSON = os.environ.get("INTERV_JSON", f"{SCRATCH}/push_34_apartment_collapse_rescue_intervention.json")

data = json.load(open(INTERV_JSON))
verdict = data.get("verdict", {}) or {}
signals = data.get("signals", {}) or {}
u = data.get("u_check", {}) or {}

app = dash.Dash(__name__)

_CELL_COLOR = {"grounded": "#16a34a", "masquerade": "#dc2626", "spurious_grounding": "#dc2626",
               "correctly_ignored": "#16a34a", "u_leaked": "#6b7280", "gt_core_unobserved": "#b45309",
               "not_adjudicable": "#6b7280"}

def spike_card():
    cell = verdict.get("cell", "?")
    return html.Div([
        html.Div("Intervention verdict (SPIKE placeholder)", style={"fontWeight": 700, "fontSize": "13px", "color": "#334155"}),
        html.Div(cell, style={"fontSize": "22px", "fontWeight": 800, "color": _CELL_COLOR.get(cell, "#111"), "margin": "6px 0"}),
        html.Div(verdict.get("explanation", ""), style={"fontSize": "12px", "color": "#475569", "marginBottom": "8px"}),
        html.Div(f"U: overlap {u.get('object_overlap')} · leaked {u.get('leaked')} · "
                 f"state_stability {u.get('state_stability')} · topology_stability {u.get('topology_stability')}",
                 style={"fontSize": "11px", "color": "#64748b"}),
        html.Div(f"shifts: total {signals.get('total_shift')} · rec {signals.get('recommendation_shift')} · "
                 f"graph {signals.get('graph_shift')} · hazard {signals.get('hazard_shift')}",
                 style={"fontSize": "11px", "color": "#64748b"}),
    ], style={"border": "1px solid #e2e8f0", "borderLeft": f"6px solid {_CELL_COLOR.get(verdict.get('cell'), '#94a3b8')}",
              "borderRadius": "8px", "padding": "14px 16px", "maxWidth": "620px", "margin": "24px",
              "fontFamily": "system-ui, sans-serif", "background": "#fff"})

candidates_panel = main.make_candidates_panel(
    data.get("candidates", {}) or {},
    (data.get("baseline", {}) or {}).get("trust", {}) or {},
)

app.layout = html.Div(
    [
        html.H3(f"Intervention UI harness — {os.path.basename(INTERV_JSON)}",
                style={"fontFamily": "system-ui", "color": "#0f172a", "margin": "16px 24px 0"}),
        html.Div(candidates_panel,
                 style={"fontFamily": "system-ui, sans-serif", "maxWidth": "680px",
                        "margin": "16px 24px", "background": "#fff", "border": "1px solid #e2e8f0",
                        "borderRadius": "8px", "padding": "14px 16px"}),
        spike_card(),
    ],
    style={"background": "#f8fafc", "minHeight": "100vh"},
)

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8051, debug=False)
