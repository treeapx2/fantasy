"""
Ingests ESPN's 2026 draft-kit PDFs into three sources under data/sources/.

    .venv/bin/python build/ingest_espn.py

Inputs (paid ESPN content — read from disk, never committed):
    data/sources/_pdf/NFL26_CS_PPR300.pdf              top-300 PPR board + auction values
    data/sources/_pdf/NFLDK2026_CS_ClayProjections2026.pdf   Mike Clay's projection guide
    data/sources/_pdf/NFL26_CS_Depth.pdf               fantasy-value depth charts

Outputs:
    data/sources/espn_ppr300/   rank, positional rank, auction value, bye
    data/sources/espn_clay/     per-player statistical projections
    data/sources/espn_depth/    ESPN's fantasy depth slot

NFL26_CS_ULTIMATE.pdf is deliberately not ingested — 4.9k characters of prose targets
and avoids, nothing tabular worth joining.

## Two things worth knowing about these files

ESPN's team codes differ from UDK's (BLT/ARZ/HST vs BAL/ARI/HOU). Irrelevant to the join,
which is on name + position, but the raw team is normalised on the way in so the canonical
record does not end up with two spellings of the same franchise.

The depth chart has NO team names in its text layer — they render as logos. It does not
need them: every entry carries its slot and ESPN's overall rank, and the team comes from
the canonical spine. ESPN also states these charts reflect *fantasy* value rather than a
club's actual depth chart, so the field is named accordingly.
"""

import json
import os
import re
import sys
import unicodedata
from collections import Counter

try:
    from pypdf import PdfReader
except ImportError:
    sys.exit("pypdf required:  python3 -m venv .venv && .venv/bin/pip install pypdf")

BASE = os.path.join(os.path.dirname(__file__), "..")
PDF = os.path.join(BASE, "data", "sources", "_pdf")
SOURCES = os.path.join(BASE, "data", "sources")
CANONICAL = os.path.join(BASE, "data", "canonical", "players.json")
SOURCE_DATE = "2026-08-31"          # Clay's stated update date

FILES = {"ppr300": "NFL26_CS_PPR300.pdf",
         "clay": "NFLDK2026_CS_ClayProjections2026.pdf",
         "depth": "NFL26_CS_Depth.pdf"}

# ESPN abbreviation -> the spelling already in the canonical dataset.
TEAM_FIX = {"BLT": "BAL", "ARZ": "ARI", "HST": "HOU", "CLV": "CLE",
            "JAC": "JAX", "LAR": "LAR", "WSH": "WAS", "SL": "LAR"}

POS = ("QB", "RB", "WR", "TE")


class GateFailure(Exception):
    pass


def fold(n):
    n = unicodedata.normalize("NFKD", n)
    n = "".join(c for c in n if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "", n.lower())


def team(t):
    t = (t or "").strip().upper()
    return TEAM_FIX.get(t, t)


def flat(path, page=None, pages=None):
    r = PdfReader(path)
    idx = [page] if page is not None else (pages or range(len(r.pages)))
    return re.sub(r"\s+", " ", " ".join((r.pages[i].extract_text() or "") for i in idx))


def num(s):
    s = str(s).strip().rstrip("%")
    if s in ("", "-"):
        return None
    return int(s) if re.fullmatch(r"-?\d+", s) else float(s)


# ---------------------------------------------------------------------------

PPR_RX = re.compile(
    r"(\d{1,3})\.\s*\((QB|RB|WR|TE|K|DST)(\d{1,3})\)\s*(.+?),\s*([A-Z]{2,3})\s*\$(\d+)\s*(\d{1,2})(?=\s|$)")


def parse_ppr300():
    rows, seen = [], set()
    for rank, pos, prk, name, tm, val, bye in PPR_RX.findall(flat(os.path.join(PDF, FILES["ppr300"]))):
        r = int(rank)
        if r in seen:
            continue                      # the sheet repeats one line
        seen.add(r)
        if pos not in POS:
            continue                      # K and DST are not in the canonical universe
        rows.append({"name": name.strip(), "team": team(tm), "position": pos,
                     "espn_rank": r, "espn_pos_rank": int(prk),
                     "auction_value": int(val), "bye": int(bye)})
    missing = [n for n in range(1, 301) if n not in seen]
    if missing:
        raise GateFailure(f"PPR300: ranks not found: {missing[:12]}")
    return rows


CLAY_COLS = {
    "QB": ["pass_att", "completions", "pass_yds", "pass_td", "int", "sacks",
           "carries", "rush_yds", "rush_td"],
    "SKILL": ["carries", "rush_yds", "rush_td", "targets", "receptions",
              "rec_yds", "rec_td", "carry_share", "target_share"],
}
# The column-name row sits in the body, not the header line, so it must be consumed
# explicitly — otherwise the first player's name absorbs the trailing "Ru TD".
CLAY_HDR = re.compile(
    r"(Quarterback|Running Back|Wide Receiver|Tight End)\s+Team\s+Pos Rk\s+FF Pt\s+G\s+"
    r"(?:P Att\s+Comp\s+P Yds\s+P TD\s+INT\s+Sk\s+Carry\s+Ru Yds\s+Ru TD"
    r"|Carry\s+Ru Yds\s+Ru TD\s+Targ\s+Rec\s+Re Yd\s+Re TD\s+Car%\s+Targ%)\s")
SECTION_POS = {"Quarterback": "QB", "Running Back": "RB",
               "Wide Receiver": "WR", "Tight End": "TE"}


def parse_clay():
    reader = PdfReader(os.path.join(PDF, FILES["clay"]))
    rows = []
    for i in range(len(reader.pages)):
        t = re.sub(r"\s+", " ", reader.pages[i].extract_text() or "")
        m = CLAY_HDR.search(t)
        if not m:
            continue
        pos = SECTION_POS[m.group(1)]
        cols = CLAY_COLS["QB"] if pos == "QB" else CLAY_COLS["SKILL"]
        body = t[m.end():]
        # Name Team PosRk FFPt G <cols...>, percentages only on the skill tables.
        rx = re.compile(r"([A-Z][A-Za-z'’.\-]*(?:\s+[A-Z][A-Za-z'’.\-]*){0,3})\s+"
                        r"([A-Z]{2,3})\s+(\d{1,3})\s+(\d{1,3})\s+(\d{1,2})\s+"
                        + r"\s+".join([r"(-?[\d.]+%?)"] * len(cols)))
        for g in rx.finditer(body):
            rec = {"name": g.group(1).strip(), "team": team(g.group(2)), "position": pos,
                   "clay_pos_rank": int(g.group(3)), "proj_pts": int(g.group(4)),
                   "proj_games": int(g.group(5))}
            for k, v in zip(cols, g.groups()[5:]):
                rec[k] = num(v)
            rows.append(rec)
    # de-dupe: the guide repeats leaders in a summary section
    best = {}
    for r in rows:
        best.setdefault((fold(r["name"]), r["position"]), r)
    return list(best.values())


DEPTH_RX = re.compile(r"\b(QB|RB|WR|TE)([1-5])\s+([A-Z][^()]*?)\s*\((\d{1,3})\)")


def parse_depth():
    out = []
    for pos, slot, name, rank in DEPTH_RX.findall(flat(os.path.join(PDF, FILES["depth"]))):
        out.append({"name": name.strip(), "team": None, "position": pos,
                    "depth_slot": int(slot),
                    "depth_label": f"{pos}{slot}",
                    "espn_rank_on_chart": int(rank)})
    counts = Counter(r["depth_label"] for r in out)
    for p in POS:
        if counts.get(f"{p}1", 0) != 32:
            raise GateFailure(f"depth: expected 32 {p}1 slots, got {counts.get(p+'1', 0)}")
    return out


# ---------------------------------------------------------------------------

SPECS = {
    "espn_ppr300": dict(
        parser=parse_ppr300,
        label="ESPN 2026 Top 300 PPR cheat sheet (rank, positional rank, auction value)",
        notes=["ESPN's own board — the independent cross-check on UDK's ranking.",
               "auction_value is ESPN's suggested $ in a standard budget auction.",
               "Kickers and team defenses appear on the sheet and are dropped here: the "
               "canonical universe is QB/RB/WR/TE only."],
        mapping={"espn_rank": "espn_rank", "espn_pos_rank": "espn_pos_rank",
                 "auction_value": "auction_value", "bye": "bye"}),
    "espn_clay": dict(
        parser=parse_clay,
        label="Mike Clay 2026 NFL Projection Guide — per-player statistical projections",
        notes=["Independent projections: an alternative to UDK's proj_pts, and the only "
               "source giving projected carry share and target share directly.",
               "QB rows carry passing columns; RB/WR/TE rows carry the rushing/receiving "
               "set plus carry_share and target_share.",
               "carry_share / target_share are percentages expressed as numbers."],
        mapping={"clay_pos_rank": "clay_pos_rank", "proj_pts": "clay_proj_pts",
                 "proj_games": "clay_proj_games", "pass_att": "clay_pass_att",
                 "completions": "clay_completions", "pass_yds": "clay_pass_yds",
                 "pass_td": "clay_pass_td", "int": "clay_int", "sacks": "clay_sacks",
                 "carries": "clay_carries", "rush_yds": "clay_rush_yds",
                 "rush_td": "clay_rush_td", "targets": "clay_targets",
                 "receptions": "clay_receptions", "rec_yds": "clay_rec_yds",
                 "rec_td": "clay_rec_td", "carry_share": "clay_carry_share",
                 "target_share": "clay_target_share"}),
    "espn_depth": dict(
        parser=parse_depth,
        label="ESPN 2026 fantasy-value depth charts",
        notes=["ESPN states these reflect FANTASY value, not a club's official depth "
               "chart — the field is named depth_slot for that reason.",
               "The PDF has no team names in its text layer (they render as logos); the "
               "team comes from the canonical spine via the name match.",
               "A slot of 3+ at RB or WR is a genuine opportunity risk signal."],
        mapping={"depth_slot": "depth_slot", "depth_label": "depth_label"}),
}


def main():
    for k, f in FILES.items():
        p = os.path.join(PDF, f)
        if not os.path.exists(p):
            sys.exit(f"missing input: {os.path.relpath(p, BASE)}\n"
                     f"Place the ESPN PDFs in data/sources/_pdf/ (gitignored).")

    canon = {}
    for p in json.load(open(CANONICAL))["players"]:
        canon[(fold(p["name"]), p["position"])] = p

    built = {}
    try:
        for name, spec in SPECS.items():
            built[name] = spec["parser"]()
    except GateFailure as e:
        print(f"GATE FAILED — nothing written.\n  {e}", file=sys.stderr)
        return 1

    print("Parsed:")
    for name, rows in built.items():
        matched = sum(1 for r in rows if (fold(r["name"]), r["position"]) in canon)
        print(f"  {name:<14}{len(rows):>5} rows   {matched:>4} match the canonical 312")

    for name, spec in SPECS.items():
        d = os.path.join(SOURCES, name)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "players_raw.json"), "w") as f:
            json.dump({"source": name, "source_label": spec["label"],
                       "source_date": SOURCE_DATE, "grain": "player",
                       "extracted": "mechanical PDF ingest (build/ingest_espn.py)",
                       "notes": spec["notes"], "players": built[name]}, f, indent=2,
                      ensure_ascii=False)
        with open(os.path.join(d, "field_mapping.json"), "w") as f:
            json.dump({"source": name,
                       "_comment": "Raw ESPN field -> canonical field. Unlisted raw fields "
                                   "are reported by build_canonical.py and excluded.",
                       "mapping": spec["mapping"]}, f, indent=2)
        print(f"  wrote data/sources/{name}/")

    print("\nNext: python3 build/build_canonical.py && python3 build/derive_metrics.py "
          "&& python3 build/claude_rank.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
