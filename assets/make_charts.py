"""
Generate showcase diagrams for Leaker.

  architecture.png  — the index-once / search-everything data flow
  sources.png       — the 18 supported source types, grouped by family

Run:  python assets/make_charts.py
"""
import os
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch

HERE = os.path.dirname(os.path.abspath(__file__))

plt.rcParams.update({
    "figure.dpi": 130, "savefig.dpi": 130, "font.size": 11,
    "axes.titlesize": 15, "axes.titleweight": "bold",
})
INK, BLUE, TEAL, AMBER, SLATE = "#12203a", "#2f6fed", "#17a398", "#e9a23b", "#5b6b84"


def _box(ax, x, y, w, h, text, fc, tc="white", fs=10, bold=True):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.015,rounding_size=0.02",
                                fc=fc, ec="none", zorder=2))
    ax.text(x + w / 2, y + h / 2, text, ha="center", va="center",
            color=tc, fontsize=fs, fontweight="bold" if bold else "normal", zorder=3)


def _arrow(ax, p1, p2, color=SLATE):
    ax.add_patch(FancyArrowPatch(p1, p2, arrowstyle="-|>", mutation_scale=16,
                                 color=color, lw=1.8, zorder=1))


def chart_architecture():
    fig, ax = plt.subplots(figsize=(11, 5.4))
    ax.set_xlim(0, 11); ax.set_ylim(0, 5.4); ax.axis("off")
    ax.set_title("Leaker — Index Once, Search Everything", pad=14)

    # column 1: sources
    files = ["CSV · TSV", "PDF · DOCX", "JSON · XML", "Excel · SQLite", "SQL dumps · TXT"]
    for i, t in enumerate(files):
        _box(ax, 0.3, 4.4 - i * 0.62, 2.0, 0.5, t, "#e8eefc", INK, 9)
    dbs = ["PostgreSQL", "MySQL", "MongoDB", "Redis"]
    for i, t in enumerate(dbs):
        _box(ax, 0.3, 1.1 - i * 0.0 - i * 0.0, 2.0, 0.5, t, "#e6f6f3", INK, 9) if False else None
    _box(ax, 0.3, 0.2, 2.0, 0.78, "Live DBs\nPostgres · MySQL\nMongo · Redis", "#e6f6f3", INK, 9)
    ax.text(1.3, 5.05, "SOURCES", ha="center", color=SLATE, fontweight="bold", fontsize=10)

    # column 2: extractors
    _box(ax, 3.1, 1.9, 1.9, 1.5, "Extractors\n(per format)\nparse → rows", BLUE, fs=10)
    # column 3: normalizer
    _box(ax, 5.5, 1.9, 2.0, 1.5, "LeakerRecord\ncontent +\nprovenance\n(source, line,\ncol, table, page)", TEAL, fs=9)
    # column 4: ES
    _box(ax, 8.1, 1.9, 2.2, 1.5, "Elasticsearch\nbulk index\nSHA-256 dedup", INK, fs=10)
    # bottom: search
    _box(ax, 5.5, 0.2, 4.8, 0.95, "leak>  interactive REPL\nfull-text · exact · type filter · sources", AMBER, INK, 10)

    _arrow(ax, (2.35, 2.9), (3.05, 2.65))
    _arrow(ax, (2.35, 0.6), (3.05, 2.35))
    _arrow(ax, (5.05, 2.65), (5.45, 2.65))
    _arrow(ax, (7.55, 2.65), (8.05, 2.65))
    _arrow(ax, (9.2, 1.85), (8.6, 1.2), BLUE)
    ax.text(7.2, 1.45, "query", color=BLUE, fontsize=9, fontweight="bold")

    fig.tight_layout()
    out = os.path.join(HERE, "architecture.png")
    fig.savefig(out); plt.close(fig); print("wrote", out)


def chart_sources():
    families = {
        "Tabular / sheets": ["CSV", "TSV", "PSV", "Excel (xlsx/xls/ods)"],
        "Documents": ["PDF", "DOCX", "TXT / LOG"],
        "Structured text": ["JSON / JSONL", "XML"],
        "Files · DB": ["SQLite", "SQL dump"],
        "Live databases": ["PostgreSQL", "MySQL / MariaDB", "MongoDB", "Redis"],
    }
    colors = {"Tabular / sheets": BLUE, "Documents": TEAL, "Structured text": AMBER,
              "Files · DB": "#8e7cc3", "Live databases": "#e05d5d"}

    labels, bars, cols = [], [], []
    for fam, items in families.items():
        for it in items:
            labels.append(it); bars.append(1); cols.append(colors[fam])

    fig, ax = plt.subplots(figsize=(9, 6))
    y = range(len(labels))
    ax.barh(list(y), bars, color=cols, edgecolor="white")
    ax.set_yticks(list(y)); ax.set_yticklabels(labels)
    ax.invert_yaxis()
    ax.set_xticks([])
    for sp in ["top", "right", "bottom"]:
        ax.spines[sp].set_visible(False)
    ax.set_title(f"Supported Sources — {len(labels)} formats, one search interface", pad=12)
    handles = [plt.Rectangle((0, 0), 1, 1, color=c) for c in colors.values()]
    ax.legend(handles, colors.keys(), frameon=False, loc="lower right", fontsize=9)
    fig.tight_layout()
    out = os.path.join(HERE, "sources.png")
    fig.savefig(out); plt.close(fig); print("wrote", out)


if __name__ == "__main__":
    chart_architecture()
    chart_sources()
