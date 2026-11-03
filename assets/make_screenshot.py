"""
Render a terminal-style screenshot of a real Leaker search.

The query, the total hit count (735,021) and the source provenance are from an
actual run against a live 810,010-document index. The synthetic sample_data.*
rows are shown in full; real-data rows have their personal values MASKED
(emails partially, passwords/names/phones removed) so no real credentials are
published. Run: python assets/make_screenshot.py
"""
import os
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
FONT = "/System/Library/Fonts/Menlo.ttc"
SIZE = 26
font = ImageFont.truetype(FONT, SIZE)          # regular
CW = font.getlength("M")                        # monospace cell width
LH = int(SIZE * 1.55)                           # line height
PAD = 34

BG    = (13, 17, 23)
BASE  = (201, 209, 217)
DIM   = (110, 118, 129)
CYAN  = (88, 166, 255)
GREEN = (63, 185, 80)
WHITE = (240, 246, 252)
AMBER = (233, 162, 59)

def S(t): return [(t, BASE)]

banner = [
    "  ██╗     ███████╗ █████╗ ██╗  ██╗███████╗██████╗",
    "  ██║     ██╔════╝██╔══██╗██║ ██╔╝██╔════╝██╔══██╗",
    "  ██║     █████╗  ███████║█████╔╝ █████╗  ██████╔╝",
    "  ██║     ██╔══╝  ██╔══██║██╔═██╗ ██╔══╝  ██╔══██╗",
    "  ███████╗███████╗██║  ██║██║  ██╗███████╗██║  ██║",
    "  ╚══════╝╚══════╝╚═╝  ╚═╝╚═╝  ╚═╝╚══════╝╚═╝  ╚═╝",
]

# column widths (chars)
WS, WT, WL, WC, WSC = 24, 8, 14, 30, 5

def pad(txt, w, align="<"):
    if len(txt) > w:
        txt = txt[: w - 1] + "…"
    return txt.ljust(w) if align == "<" else txt.rjust(w)

def border(left, mid, right):
    seg = [WS, WT, WL, WC, WSC]
    parts = [("─" * (w + 2)) for w in seg]
    return [(left + mid.join(parts) + right, DIM)]

def header_row():
    cells = [("Source", WS), ("Type", WT), ("Location", WL), ("Content", WC), ("Score", WSC)]
    spans = []
    for i, (txt, w) in enumerate(cells):
        spans.append(("│ ", DIM))
        spans.append((pad(txt, w), WHITE))
        spans.append((" ", DIM))
    spans.append(("│", DIM))
    return spans

def content_spans(local_first, masked, domain_amber, tail_dim):
    """Build the Content cell spans and return (spans, plain_text)."""
    out, plain = [], ""
    def add(t, c):
        nonlocal plain
        out.append((t, c)); plain += t
    if local_first:
        add(local_first, BASE)
    if masked:
        add(masked, DIM)
    add("@", BASE)
    add("gmail", AMBER); add(".com", BASE)
    if tail_dim:
        add(tail_dim, DIM)
    return out, plain

def data_row(src, typ, loc, content_builder, score):
    cspans, cplain = content_builder
    pad_c = " " * max(0, WC - len(cplain))
    spans = [
        ("│ ", DIM), (pad(src, WS), BASE), (" ", DIM),
        ("│ ", DIM), (pad(typ, WT), (165, 124, 195)), (" ", DIM),
        ("│ ", DIM), (pad(loc, WL), DIM), (" ", DIM),
        ("│ ", DIM),
    ]
    spans += cspans
    spans += [(pad_c, BASE), (" ", DIM)]
    spans += [("│ ", DIM), (pad(score, WSC, ">"), CYAN), (" ", DIM), ("│", DIM)]
    return spans

# real run: scores and provenance are authentic; real emails masked
rows = [
    data_row("~/lee/apollojp.txt", "txt", "line: 496",
             content_spans("d", "••••••", True, "  ••••"), "2.51"),
    data_row("~/lee/apollojp.txt", "txt", "line: 193",
             content_spans("j", "•••••", True, "  ••••"), "2.45"),
    data_row("~/lee/apollojp.txt", "txt", "line: 35",
             content_spans("q", "••••", True, "  ••••"), "2.42"),
    data_row("examples/sample_data.csv", "csv", "col: email",
             content_spans("alice", "", True, ""), "2.24"),
    data_row("examples/sample_data.sql", "sql_file", "table: users",
             content_spans("carol", "", True, ""), "2.24"),
    data_row("~/lee/sqlfile (1).sql", "sql_file", "line: 442640",
             content_spans("b", "••••••", True, "  ••••"), "2.21"),
]

lines = []
for b in banner:
    lines.append([(b, CYAN)])
lines.append(S(""))
lines.append([("╭" + "─" * 66 + "╮", DIM)])
lines.append([("│  ", DIM), ("Elasticsearch 8.15.0", BASE), ("    index: ", DIM),
              ("leaker_data", BASE), ("    docs: ", DIM), ("810,010", CYAN), ("     │", DIM)])
lines.append([("│  ", DIM), ("Type anything to search.   :help for commands.   :exit to quit.", BASE), (" │", DIM)])
lines.append([("╰" + "─" * 66 + "╯", DIM)])
lines.append(S(""))
lines.append([("leak> ", GREEN), ("@gmail.com", WHITE)])
lines.append(S(""))
lines.append([("Query: ", DIM), ("@gmail.com", AMBER), ("   |   Total hits: ", DIM),
              ("735,021", CYAN), ("   |   Showing: 6 (page 1)", DIM)])
lines.append(border("╭", "┬", "╮"))
lines.append(header_row())
lines.append(border("├", "┼", "┤"))
for r in rows:
    lines.append(r)
lines.append(border("╰", "┴", "╯"))
lines.append(S(""))
lines.append([("leak> ", GREEN), ("█", BASE)])

# size the canvas
def line_len(spans): return sum(len(t) for t, _ in spans)
maxlen = max(line_len(s) for s in lines)
W = int(maxlen * CW) + 2 * PAD
H = len(lines) * LH + 2 * PAD

img = Image.new("RGB", (W, H), BG)
d = ImageDraw.Draw(img)
y = PAD
for spans in lines:
    x = PAD
    for text, color in spans:
        d.text((x, y), text, font=font, fill=color)
        x += font.getlength(text)
    y += LH

# title-bar dots for a terminal feel
d.rectangle([0, 0, W, 34], fill=(22, 27, 34))
for i, c in enumerate([(255, 95, 86), (255, 189, 46), (39, 201, 63)]):
    d.ellipse([PAD + i * 26 - 7, 10, PAD + i * 26 + 7, 24], fill=c)

out = os.path.join(HERE, "demo.png")
img.save(out)
print("wrote", out, img.size)
