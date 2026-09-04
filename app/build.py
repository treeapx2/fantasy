"""
Assembles the draft board into a single self-contained HTML file.

    python3 build/export_board.py && python3 app/build.py

app/head.html  <title>, fonts, the whole stylesheet
app/body.html  markup and application script
data/app/board.json  the payload, inlined at build time

Output app/draft-board.html is one file with no external requests beyond Google Fonts,
so it works offline and can be published as-is.
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.join(HERE, "..")
DATA = os.path.join(BASE, "data", "app", "board.json")
OUT = os.path.join(HERE, "draft-board.html")

for part in ("head.html", "body.html"):
    if not os.path.exists(os.path.join(HERE, part)):
        raise SystemExit(f"missing {part}")
if not os.path.exists(DATA):
    raise SystemExit("missing data/app/board.json — run build/export_board.py first")

head = open(os.path.join(HERE, "head.html")).read()
body = open(os.path.join(HERE, "body.html")).read()
data = open(DATA).read()
json.loads(data)  # refuse to ship a payload that will not parse in the browser

with open(OUT, "w") as f:
    f.write(head)
    f.write("<script>window.__BOARD__=" + data + ";</script>\n")
    f.write(body)

print(f"Wrote {os.path.relpath(OUT, BASE)} — {os.path.getsize(OUT):,} bytes")
