"""
Generate the Leaker flow diagram as a clean SVG (assets/flow.svg).
Convert to assets/flow.png with a browser (or the project's render step).

Flow:  Sources (drag & drop / link DB)  ->  Extract + Normalize  ->  Index  ->  Search
"""
import os

HERE = os.path.dirname(os.path.abspath(__file__))

INK   = "#172036"
SLATE = "#5b6b84"
BG    = "#ffffff"
STAGES = [
    dict(key="1", title="SOURCES", accent="#2f6fed", fill="#eef3fe",
         sub="Drag &amp; drop into  dropzone/",
         lines=["Stealer logs  .txt / .log", "CSV · TSV · Excel",
                "PDF · DOCX", "JSON · JSONL · XML",
                "SQLite · SQL dumps", "Archives  .zip · .tar · .7z"],
         foot="or link a live DB:\nPostgres · MySQL · Mongo · Redis"),
    dict(key="2", title="EXTRACT + NORMALIZE", accent="#17a398", fill="#e7f6f3",
         sub="watcher.py, auto",
         lines=["New files detected on drop", "Archives auto-unpacked",
                "Per-format parser + regex", "Pulls emails, user:pass, phones",
                "Normalized to one record"],
         foot=None),
    dict(key="3", title="INDEX", accent="#8e7cc3", fill="#f1edf8",
         sub="Elasticsearch",
         lines=["Bulk index", "Keeps provenance:", "source · line · column",
                "· table · page", "SHA-256 dedup"],
         foot=None),
    dict(key="4", title="SEARCH", accent="#e9a23b", fill="#fdf3e2",
         sub="leak>",
         lines=["Full-text or exact", "Filter by type / source",
                "Paged results", "Every hit shows", "where it came from"],
         foot=None),
]

# layout
W, H = 1460, 560
pad = 34
gap = 44
xs = []
widths = [350, 320, 290, 300]
x = pad
for wd in widths:
    xs.append(x); x += wd + gap

def esc(s): return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;") if "&amp;" not in s else s

parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" font-family="Inter, Helvetica, Arial, sans-serif">']
parts.append(f'<rect width="{W}" height="{H}" fill="{BG}"/>')
# title
parts.append(f'<text x="{W/2}" y="52" text-anchor="middle" font-size="27" font-weight="700" fill="{INK}">Leaker: ingest once, search everything</text>')
parts.append(f'<text x="{W/2}" y="80" text-anchor="middle" font-size="14.5" fill="{SLATE}">clone → launch → drag your data into the drop zone (or link a database) → search from the terminal</text>')

box_top = 110
box_bottom = 478
for i, st in enumerate(STAGES):
    bx, bw = xs[i], widths[i]
    by, bh = box_top, box_bottom - box_top
    acc = st["accent"]
    # card
    parts.append(f'<rect x="{bx}" y="{by}" width="{bw}" height="{bh}" rx="16" fill="{st["fill"]}" stroke="{acc}" stroke-opacity="0.25" stroke-width="1.5"/>')
    # accent header strip
    parts.append(f'<rect x="{bx}" y="{by}" width="{bw}" height="46" rx="16" fill="{acc}"/>')
    parts.append(f'<rect x="{bx}" y="{by+26}" width="{bw}" height="20" fill="{acc}"/>')  # square off bottom of strip
    parts.append(f'<text x="{bx+20}" y="{by+30}" font-size="17" font-weight="700" fill="#ffffff">{st["key"]}  ·  {st["title"]}</text>')
    # sub (mono-ish)
    ty = by + 78
    parts.append(f'<text x="{bx+20}" y="{ty}" font-size="14.5" font-weight="700" fill="{acc}" font-family="Menlo, monospace">{st["sub"]}</text>')
    ty += 30
    for ln in st["lines"]:
        parts.append(f'<text x="{bx+20}" y="{ty}" font-size="14.5" fill="{INK}">{ln}</text>')
        ty += 29
    if st["foot"]:
        ty += 8
        parts.append(f'<line x1="{bx+20}" y1="{ty-18}" x2="{bx+bw-20}" y2="{ty-18}" stroke="{acc}" stroke-opacity="0.3"/>')
        for fl in st["foot"].split("\n"):
            parts.append(f'<text x="{bx+20}" y="{ty}" font-size="13.5" fill="{SLATE}">{fl}</text>')
            ty += 22

# arrows between cards
ay = (box_top + box_bottom) / 2
for i in range(len(STAGES) - 1):
    x1 = xs[i] + widths[i] + 6
    x2 = xs[i+1] - 6
    parts.append(f'<line x1="{x1}" y1="{ay}" x2="{x2-12}" y2="{ay}" stroke="{SLATE}" stroke-width="3"/>')
    parts.append(f'<path d="M{x2-14},{ay-9} L{x2},{ay} L{x2-14},{ay+9} Z" fill="{SLATE}"/>')

# footer tagline
parts.append(f'<text x="{W/2}" y="{H-24}" text-anchor="middle" font-size="14.5" fill="{SLATE}" font-style="italic">No LLM · no API keys · offline · deterministic · exact provenance on every match</text>')
parts.append('</svg>')

svg = "\n".join(parts)
open(os.path.join(HERE, "flow.svg"), "w").write(svg)
print("wrote", os.path.join(HERE, "flow.svg"))
