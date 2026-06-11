"""Build a one-page, non-technical PDF overview of CEE+ for the intern.

Sections:
  1. What is CEE+
  2. Why care
  3. What already exists
  4. What the intern does

Run:
  python build_intern_overview.py
Output:
  CEE_plus_intern_overview.pdf
"""

from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.patches import FancyBboxPatch

OUT = Path(__file__).resolve().parent / "CEE_plus_intern_overview.pdf"

# Letter-size page
FIG_W, FIG_H = 8.5, 11.0

# Color palette: muted, professional, readable.
COL_TITLE = "#0f172a"        # near-black
COL_SUB = "#475569"          # slate
COL_ACCENT = "#7f1d1d"       # deep red, section bars
COL_BODY = "#1f2933"         # body text
COL_FOOTER = "#94a3b8"
COL_BG_CARD = "#f8fafc"
COL_BG_CARD_BORDER = "#e2e8f0"


def section_header(ax, x, y, text):
    """Draw a coloured pill behind the section header.

    Width is fixed wide enough to fit the longest title; eyeballed at 0.30
    of axes width so all four section labels render without clipping.
    """
    width = 0.32
    pill = FancyBboxPatch(
        (x - 0.005, y - 0.014),
        width + 0.01,
        0.038,
        boxstyle="round,pad=0.002,rounding_size=0.006",
        linewidth=0,
        facecolor=COL_ACCENT,
        transform=ax.transAxes,
        clip_on=False,
    )
    ax.add_patch(pill)
    ax.text(
        x + 0.014,
        y + 0.005,
        text.upper(),
        transform=ax.transAxes,
        fontsize=10,
        weight="bold",
        color="white",
        ha="left",
        va="center",
        family="DejaVu Sans",
    )


def body(ax, x, y, text, fontsize=10, width=0.92, color=COL_BODY, weight="normal", style="normal"):
    ax.text(
        x,
        y,
        text,
        transform=ax.transAxes,
        fontsize=fontsize,
        color=color,
        ha="left",
        va="top",
        wrap=True,
        weight=weight,
        style=style,
        family="DejaVu Sans",
        linespacing=1.35,
    )


def main():
    fig = plt.figure(figsize=(FIG_W, FIG_H))
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")

    # Top accent bar
    ax.add_patch(plt.Rectangle((0, 0.97), 1, 0.03, color=COL_ACCENT, transform=ax.transAxes, clip_on=False))

    # Title block: CEE+ on its own line, subtitle below it (avoids overlap).
    ax.text(
        0.05, 0.945,
        "CEE+",
        transform=ax.transAxes,
        fontsize=30, weight="bold", color=COL_TITLE,
        ha="left", va="top", family="DejaVu Sans",
    )
    ax.text(
        0.05, 0.905,
        "Causal Explanation Engine",
        transform=ax.transAxes,
        fontsize=14, color=COL_SUB,
        ha="left", va="top", family="DejaVu Sans",
    )
    ax.text(
        0.05, 0.880,
        "Project overview for intern   ·   U.S. Army Research Laboratory   ·   Lead: Sunny Anjon",
        transform=ax.transAxes,
        fontsize=9.5, color=COL_SUB,
        ha="left", va="top", family="DejaVu Sans",
    )

    # Section pill y positions, eyeballed to leave breathing room between
    # each section's body and the next pill. Body height per section is
    # roughly 0.15 (4 lines + blank + 4 lines at fontsize 10, linespacing 1.35).
    Y_S1, Y_S2, Y_S3, Y_S4 = 0.83, 0.62, 0.41, 0.20

    # ----- Section 1: What is CEE+ -----
    section_header(ax, 0.05, Y_S1, "What is CEE+")
    body(
        ax, 0.05, Y_S1 - 0.040,
        "AI models can look at an image and write confident reports about what is happening, what the dangers "
        "are, and what to do about it. CEE+ is a research project that checks whether those reports are actually "
        "grounded in the AI's reasoning, or whether they only sound right on the surface.\n\n"
        "We work with disaster scenes (mostly fires) and use the AI's recommendations as the test case. If the "
        "AI wrote a recommendation because of a fire, then removing the fire from the scene should change the "
        "recommendation. If the recommendation does not change, the AI was not really reasoning about the fire.",
    )

    # ----- Section 2: Why care -----
    section_header(ax, 0.05, Y_S2, "Why this matters")
    body(
        ax, 0.05, Y_S2 - 0.040,
        "AI tools are being used to support real decisions in emergency response, military operations, and other "
        "settings where being wrong has serious consequences. The output of a modern AI can look completely "
        "trustworthy while being only loosely connected to the actual scene. Operators acting on those reports "
        "can be misled in ways that are hard to catch.\n\n"
        "CEE+ gives an honest way to check whether a particular AI report is grounded in real reasoning or only "
        "in plausible-sounding language. That tells the operator when to trust the report and when to take a "
        "second look before acting.",
    )

    # ----- Section 3: What already exists -----
    section_header(ax, 0.05, Y_S3, "What already exists")
    body(
        ax, 0.05, Y_S3 - 0.040,
        "A working pipeline that takes an image and a short caption, runs them through the AI, and produces:",
    )
    body(
        ax, 0.07, Y_S3 - 0.072,
        "•  a structured analysis of the scene (objects, threats, recommendations, reasoning)\n"
        "•  a trust score with Low / Moderate / High bands\n"
        "•  flags for known AI failure patterns (model agreeing too quickly, hedging real threats, etc.)\n"
        "•  a batch report that summarizes results across many scenes",
        fontsize=9.5,
    )
    body(
        ax, 0.05, Y_S3 - 0.155,
        "All of the above is the baseline pass. It tells us what the AI thinks. It does not tell us whether the "
        "AI was actually reasoning about the scene. That is the part you will build.",
    )

    # ----- Section 4: What you do -----
    section_header(ax, 0.05, Y_S4, "What you will work on")
    body(
        ax, 0.05, Y_S4 - 0.040,
        "You will build the intervention step. The idea is to take a scene, remove one hazard (either by editing "
        "the caption to remove the mention, or by editing the image to remove the visual evidence, or both), and "
        "run the AI again on the modified scene. We then compare the two outputs to see what changed.\n\n"
        "If the AI's reasoning was real, removing the hazard should change the report in predictable ways. If the "
        "report stays the same, the original reasoning was not grounded. This is the core experiment of the "
        "project.",
    )

    # Footer
    ax.text(
        0.5, 0.020,
        "CEE_plus_intern_overview.pdf  ·  See INTERN_BRIEF.md for the full project plan.",
        transform=ax.transAxes,
        fontsize=8, color=COL_FOOTER,
        ha="center", va="bottom", family="DejaVu Sans",
    )

    with PdfPages(OUT) as pdf:
        pdf.savefig(fig, bbox_inches=None)
    plt.close(fig)
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    main()
