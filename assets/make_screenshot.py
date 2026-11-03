"""
Render a Leaker search screenshot using Leaker's OWN renderer (functions.py),
so the image matches exactly what the tool prints in a real terminal.

The header and provenance mirror a real run against a live 810,010-document
index (735,021 hits for @gmail.com). Real personal values are masked with
block dots; the synthetic sample_data.* rows are shown in full. No real
credentials are published.

Output: assets/demo.svg  (a terminal-window SVG, convert to PNG for the README)
Run:    python assets/make_screenshot.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)

import functions as fn                      # Leaker's own code
from rich.console import Console

O, C = fn.HL_OPEN, fn.HL_CLOSE              # highlight sentinels
def hl(s):                                  # wrap the matched term
    return s.replace("gmail", f"{O}gmail{C}")

SR = fn.SearchResult
TAB = "\t"

# Built from a real run; real emails/names/phones masked, sample_data shown full.
results = [
    SR(content=TAB.join(["•••••• ••••••", hl("d••••••@gmail.com"), "Health", "Japan  Toba"]),
       source="~/lee/apollojp.txt", source_type="txt",
       line_number=496, column_name=None, table_name=None, page_number=None, score=2.508),
    SR(content=TAB.join(["••••• ••••", hl("j•••••@gmail.com"), "Japan"]),
       source="~/lee/apollojp.txt", source_type="txt",
       line_number=193, column_name=None, table_name=None, page_number=None, score=2.445),
    SR(content=hl("alice@gmail.com"),
       source="examples/sample_data.csv", source_type="csv",
       line_number=2, column_name="email", table_name=None, page_number=None, score=2.236),
    SR(content=hl("carol@gmail.com"),
       source="examples/sample_data.sql", source_type="sql_file",
       line_number=1, column_name=None, table_name="users", page_number=None, score=2.236),
    SR(content=TAB.join(["Mr.", hl("b••••••@gmail.com"), "••••••••", "•••• (EUR) (English)"]),
       source="~/lee/sqlfile (1).sql", source_type="sql_file",
       line_number=442640, column_name=None, table_name=None, page_number=None, score=2.213),
]

# render through Leaker's real display_results, into a recording console
fn.console = Console(record=True, width=100)
fn.console.print("[green]leak>[/] @gmail.com")
fn.display_results(results, "@gmail.com", total=735021, page=1)

svg = os.path.join(HERE, "demo.svg")
fn.console.save_svg(svg, title="leak  ·  Leaker search")
print("wrote", svg)

# best-effort PNG if a converter is present (optional)
try:
    import cairosvg
    cairosvg.svg2png(url=svg, write_to=os.path.join(HERE, "demo.png"), scale=2)
    print("wrote demo.png via cairosvg")
except Exception:
    print("no cairosvg; convert demo.svg -> demo.png with a browser or rsvg-convert")
