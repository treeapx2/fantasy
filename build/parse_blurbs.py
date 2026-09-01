"""
Extracts the UDK analyst blurbs from the source PDF for the Phase 5 notes pass.

    python3 build/parse_blurbs.py            # -> data/sources/_pdf/blurbs.json

## What this does and does not write

Input and output BOTH live under data/sources/_pdf/, which is gitignored. The PDF is paid
Fantasy Footballers subscription content: it is read from disk, and neither it nor its
prose is ever committed. Only the paraphrased notes in data/user/risk_upside_notes.json —
authored from these blurbs, never quoting them — reach git.

## Dependency

Needs `pypdf`, which is not a system package here. It is the only third-party dependency
in the repo, and only this script needs it:

    python3 -m venv .venv && .venv/bin/pip install pypdf
    .venv/bin/python build/parse_blurbs.py

## Parsing notes

Entries look like `RANK Name (TEAM) AGE EXP BYE ADP RISK UP PTS GMS '25` followed by prose.
Four variants in the text layer had to be handled, each found by validating coverage
against the canonical 312 rather than by eyeballing:

  - age is sometimes an integer (`24`) rather than `24.0`
  - bye and ADP are `-` for free agents
  - the `(TEAM)` parenthetical is absent for a few players
  - names carry accents (Audric Estimé)

Position is taken from the canonical dataset by name match, NOT from the PDF's section
headers — those strings also occur inside blurb prose and mis-assign wholesale.
"""

import json
import os
import re
import sys
import unicodedata

try:
    from pypdf import PdfReader
except ImportError:
    sys.exit("pypdf is required: python3 -m venv .venv && .venv/bin/pip install pypdf\n"
             "then run this script with .venv/bin/python")

BASE = os.path.join(os.path.dirname(__file__), "..")
PDF = os.path.join(BASE, "data", "sources", "_pdf", "UDK.pdf")
OUT = os.path.join(BASE, "data", "sources", "_pdf", "blurbs.json")
CANONICAL = os.path.join(BASE, "data", "canonical", "players.json")

# The text layer drops this surname entirely; everything else matches on name.
PDF_NAME_FIXES = {"jordyn": "Jordyn Tyson"}

ENTRY = re.compile(
    r"(?<![\d.])(?P<rank>\d{1,3})\s+"
    r"(?P<name>[A-Z][A-Za-zÀ-ɏ'’.\-]*"
    r"(?:\s+[A-Z][A-Za-zÀ-ɏ'’.\-]*){0,3})\s*"
    r"(?:\((?P<team>[A-Z]{2,3}|FA)\)\s+)?"
    r"(?P<age>\d{1,2}(?:\.\d)?)\s+(?P<exp>\d{1,2})\s+(?P<bye>\d{1,2}|-)\s+"
    r"(?P<adp>\d{1,2}\.\d{2}|-)(?=\s)"
)

FOOTER = re.compile(
    r"My Guy\s+Value\s+Bust\s+Sleeper\s+Rookie\s+Injury Concerns\s+Breakout"
    r"|PPR \(4pt QB\) Redraft Rankings\s+\d+/\d+/\d+"
    r"|Ultimate Draft Kit\s*\d*")


def fold(n):
    n = unicodedata.normalize("NFKD", n)
    n = "".join(c for c in n if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "", n.lower())


def main():
    if not os.path.exists(PDF):
        sys.exit(f"{os.path.relpath(PDF, BASE)} is absent.\n"
                 f"BUILD_SPEC Phase 5: stop and ask the user for it rather than attempting "
                 f"this phase from the tabular data alone.")

    reader = PdfReader(PDF)
    flat = re.sub(r"\s*\n\s*", " ",
                  "\n".join((p.extract_text() or "") for p in reader.pages))
    flat = re.sub(r"TIER \d+", " ", flat)
    flat = re.sub(r"(Quarterbacks|Running Backs|Wide Receivers|Tight Ends|Kickers|"
                  r"Team Defense)?\s*AGE EXP BYE ADP RISK UP PTS GMS\s*[’']25", " ", flat)
    flat = FOOTER.sub(" ", flat)

    canon = {fold(p["name"]): p for p in json.load(open(CANONICAL))["players"]}

    hits = [{"rank": int(m.group("rank")), "name": m.group("name").strip(),
             "team": m.group("team"), "s": m.start(), "e": m.end()}
            for m in ENTRY.finditer(flat)]

    for i, h in enumerate(hits):
        nxt = hits[i + 1]["s"] if i + 1 < len(hits) else len(flat)
        blurb = re.sub(r"^[\s\d.\-]+", "", flat[h["e"]:nxt])
        h["blurb"] = re.sub(r"\s+", " ", blurb).strip()
        lookup = PDF_NAME_FIXES.get(fold(h["name"]), h["name"])
        c = canon.get(fold(lookup))
        h["name"] = lookup
        h["position"] = c["position"] if c else None
        h["player_id"] = c["player_id"] if c else None
        del h["s"], h["e"]

    matched = [h for h in hits if h["player_id"]]
    thin = [h["name"] for h in matched if len(h["blurb"]) < 120]

    with open(OUT, "w") as f:
        json.dump({"source_pdf": os.path.basename(PDF), "entries": hits}, f, indent=1,
                  ensure_ascii=False)

    print(f"Parsed {len(hits)} entries; {len(matched)} matched to the canonical 312.")
    print(f"Unmatched are the PDF's kicker section, which canonical does not carry: "
          f"{len(hits) - len(matched)}")
    missing = [p["name"] for k, p in canon.items()
               if p["player_id"] not in {h["player_id"] for h in matched}]
    print(f"Canonical players with no entry: {len(missing)} {missing}")
    if thin:
        print(f"\n{len(thin)} entries parsed but with a missing/truncated blurb — the text "
              f"layer drops prose at some column and section breaks:")
        print(f"  {thin}")
        print("  Notes for these must lean on the derived metrics, and should say so.")
    print(f"\nWrote {os.path.relpath(OUT, BASE)} (gitignored — never commit it).")


if __name__ == "__main__":
    main()
