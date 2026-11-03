"""
Single flow diagram for Leaker: what it ingests, how it processes it, and how
you search it. Run: python assets/make_diagram.py  ->  assets/flow.png
"""
import os
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch

HERE = os.path.dirname(os.path.abspath(__file__))
plt.rcParams.update({"figure.dpi": 150, "savefig.dpi": 150, "font.family": "DejaVu Sans"})

INK   = "#12203a"
BLUE  = "#2f6fed"
TEAL  = "#17a398"
AMBER = "#e9a23b"
SLATE = "#5b6b84"
PANEL = "#eef2fb"
PTEAL = "#e6f6f3"
PAMB  = "#fdf2e0"

fig, ax = plt.subplots(figsize=(13, 6.2))
ax.set_xlim(0, 13); ax.set_ylim(0, 6.2); ax.axis("off")

def panel(x, y, w, h, fc, ec="none"):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.02,rounding_size=0.08",
                                fc=fc, ec=ec, lw=1.4, zorder=1))

def title(x, y, text, color):
    ax.text(x, y, text, fontsize=12.5, fontweight="bold", color=color, zorder=3)

def line(x, y, text, color=INK, size=10.5, weight="normal"):
    ax.text(x, y, text, fontsize=size, color=color, zorder=3, fontweight=weight)

def arrow(x1, x2, y):
    ax.add_patch(FancyArrowPatch((x1, y), (x2, y), arrowstyle="-|>", mutation_scale=22,
                                 color=SLATE, lw=2.2, zorder=2))

# ---- Stage 1: SOURCES + document types -------------------------------------
panel(0.3, 0.5, 3.5, 5.2, PANEL)
title(0.6, 5.25, "1 · SOURCES", BLUE)
doc_types = [
    ("Stealer logs", ".txt / .log, combolists"),
    ("Delimited", "CSV · TSV · Excel"),
    ("Documents", "PDF · DOCX"),
    ("Structured", "JSON · JSONL · XML"),
    ("Databases on disk", "SQLite · SQL dumps"),
    ("Live databases", "Postgres · MySQL\nMongo · Redis"),
]
yy = 4.6
for name, detail in doc_types:
    line(0.65, yy, "•  " + name, INK, 10.5, "bold")
    dy = detail.split("\n")
    line(0.95, yy - 0.3, dy[0], SLATE, 9.3)
    if len(dy) > 1:
        line(0.95, yy - 0.6, dy[1], SLATE, 9.3)
        yy -= 0.9
    else:
        yy -= 0.68

# ---- Stage 2: EXTRACT + NORMALIZE ------------------------------------------
panel(4.5, 1.4, 3.3, 3.4, PTEAL)
title(4.75, 4.35, "2 · EXTRACT +", TEAL)
title(4.75, 4.02, "     NORMALIZE", TEAL)
for i, t in enumerate([
    "Per-format parser",
    "reads each source.",
    "",
    "Regex pulls out",
    "emails, user:pass,",
    "phones, hashes.",
    "",
    "Every value becomes",
    "one flat record.",
]):
    line(4.75, 3.55 - i * 0.3, t, INK, 10)

# ---- Stage 3: ELASTICSEARCH ------------------------------------------------
panel(8.5, 1.4, 2.0, 3.4, "#e9edf6")
title(8.7, 4.35, "3 · INDEX", INK)
for i, t in enumerate([
    "Elasticsearch",
    "bulk index.",
    "",
    "Each record keeps",
    "source + line +",
    "column + table +",
    "page.",
    "",
    "SHA-256 dedup.",
]):
    line(8.7, 3.95 - i * 0.3, t, INK, 9.3)

# ---- Stage 4: SEARCH -------------------------------------------------------
panel(11.0, 1.4, 1.7, 3.4, PAMB)
title(11.2, 4.35, "4 · SEARCH", AMBER)
for i, t in enumerate([
    "leak>",
    "",
    "full-text",
    "or exact",
    "",
    "filter by",
    "type /",
    "source",
    "",
    "every hit",
    "shows where",
    "it came from",
]):
    line(11.2, 3.95 - i * 0.28, t, INK, 9.2,
         "bold" if t == "leak>" else "normal")

arrow(3.9, 4.45, 3.1)
arrow(7.85, 8.45, 3.1)
arrow(10.55, 10.95, 3.1)

ax.text(6.5, 5.75, "Leaker:  index many messy formats once, search all of it from the terminal",
        ha="center", fontsize=14, fontweight="bold", color=INK)
ax.text(6.5, 0.2, "No LLM · no API keys · offline · deterministic · exact provenance on every match",
        ha="center", fontsize=10.5, color=SLATE, style="italic")

fig.tight_layout()
out = os.path.join(HERE, "flow.png")
fig.savefig(out, bbox_inches="tight", facecolor="white")
print("wrote", out)
