"""
Ingests the 20 supplemental UDK CSVs staged in data/sources/_incoming/ into stable
per-report-type sources under data/sources/.

Follows the existing source pattern: each report type gets its own directory with
players_raw.json + field_mapping.json, and position lives as a *field on each row*
rather than as a separate source.

Grain matters here. Player-grain reports join to canonical on player_id. Team-grain
reports (Strength of Schedule, Target Share Breakdown) do NOT join on player_id and are
written to data/sources/_team/ — which build_canonical.py skips, because those
directories deliberately contain team_raw.json rather than players_raw.json.

Validation gates run over every file BEFORE anything is written (Global rule 1): exact
row counts and exact header signatures per the verified mapping in BUILD_SPEC.md Phase 2.
If any gate fails the script aborts having written nothing.

Safe to re-run while data/sources/_incoming/ still exists. Once _incoming/ is deleted
(the Phase 2 deliverable), the generated sources stand on their own and this script is a
historical record of how they were produced — the CSVs remain in git history.
"""

import csv
import json
import os
import re
import sys

BASE = os.path.join(os.path.dirname(__file__), "..")
INCOMING = os.path.join(BASE, "data", "sources", "_incoming")
SOURCES = os.path.join(BASE, "data", "sources")
TEAM_DIR = os.path.join(SOURCES, "_team")

SOURCE_DATE = "2026-08-30"
FF = "_-_Fantasy_Footballers_Podcast"


def fn(stem, suffix=""):
    return f"UDK_-_{stem}{FF}{suffix}.csv"


# ---------------------------------------------------------------------------
# Expected header signatures. These are the validation gate for "did the browser
# hand us the file we think it did" — filenames are ambiguous, headers are not.
# ---------------------------------------------------------------------------

H_CHARTS = ["Player", "Rank", "Total Points", "Team",
            "2025", "2024", "2023", "2022", "2021", "2020", "2019", "2018", "2017", "2016"]
H_PCT = {
    "QB": ["Name", "Team", "GP", "Top 12", "QB 1-6", "QB 7-12", "QB2", "QB3+"],
    "RB": ["Name", "Team", "GP", "Top 24", "RB1", "RB2", "RB3", "RB4+"],
    "WR": ["Name", "Team", "GP", "Top 24", "WR1", "WR2", "WR3", "WR4+"],
    "TE": ["Name", "Team", "GP", "Top 12", "TE 1-6", "TE 7-12", "TE2", "TE3+"],
}
H_MS = {
    "RB": ["Name", "Team", "Games Played", "RB PTS%",
           "ATT%", "YD%", "TD%", "TGT%", "REC%", "YD%", "TD%"],
    "WR": ["Name", "Team", "Games Played", "WR PTS%", "TGT%", "REC%", "YD%", "TD%"],
    "TE": ["Name", "Team", "Games Played", "TE PTS%", "TGT%", "REC%", "YD%", "TD%"],
}
H_RZ = {
    "passing": ["Name", "Team"] + ["ATT", "ATT%", "CMP", "CMP%", "TDS", "TD%"] * 2,
    "rushing": ["Name", "Team"] + ["ATT", "ATT%", "TDS", "TD%", "TEAM%"] * 2,
    "receiving": ["Name", "Team"] + ["TGT", "TGT%", "REC", "REC%", "CATCH%", "TDS", "TD%"] * 2,
}
H_VS = ["Name", "Team", "Pos", "Pos", "TrueValue", "Diff", "Average ADP", "Markers"]
H_TS = ["Name", "Team", "TGT%", "CMP%", "TGT%", "CMP%", "TGT%", "CMP%"]
H_SOS = ["Team", "Rank", "Team"] + [
    x for w in range(1, 19)
    for x in (f"Week {w} Opp", f"Week {w} Opp Pts Allowed", f"Week {w} Rank")
]

# (file, report, scope, expected_rows, expected_header)
MANIFEST = [
    (fn("Consistency_Charts"),                  "charts", "QB", 34,  H_CHARTS),
    (fn("Consistency_Charts", "_1_"),           "charts", "RB", 82,  H_CHARTS),
    (fn("Consistency_Charts", "_2_"),           "charts", "WR", 108, H_CHARTS),
    (fn("Consistency_Charts", "_3_"),           "charts", "TE", 48,  H_CHARTS),

    (fn("Consistency_Percentages"),             "pct", "QB", 93,  H_PCT["QB"]),
    (fn("Consistency_Percentages", "_1_"),      "pct", "RB", 196, H_PCT["RB"]),
    (fn("Consistency_Percentages", "_2_"),      "pct", "WR", 304, H_PCT["WR"]),
    (fn("Consistency_Percentages", "_3_"),      "pct", "TE", 170, H_PCT["TE"]),

    (fn("Market_Share_Report"),                 "market_share", "RB", 128, H_MS["RB"]),
    (fn("Market_Share_Report", "_1_"),          "market_share", "WR", 202, H_MS["WR"]),
    (fn("Market_Share_Report", "_2_"),          "market_share", "TE", 112, H_MS["TE"]),

    (fn("Red_Zone_Report"),                     "red_zone", "passing",   77,  H_RZ["passing"]),
    (fn("Red_Zone_Report", "_1_"),              "red_zone", "rushing",   184, H_RZ["rushing"]),
    (fn("Red_Zone_Report", "_2_"),              "red_zone", "receiving", 334, H_RZ["receiving"]),

    (fn("Value_Scout"),                         "value_scout", None, 250, H_VS),

    (fn("Strength_of_Schedule_by_Position"),        "sos", "QB", 32, H_SOS),
    (fn("Strength_of_Schedule_by_Position", "_1_"), "sos", "RB", 32, H_SOS),
    (fn("Strength_of_Schedule_by_Position", "_2_"), "sos", "WR", 32, H_SOS),
    (fn("Strength_of_Schedule_by_Position", "_3_"), "sos", "TE", 32, H_SOS),

    (fn("Target_Share_Breakdown"),              "target_share", None, 32, H_TS),
]


class GateFailure(Exception):
    pass


def num(v):
    """Parse a numeric cell. '' -> None. Strips % and thousands separators."""
    if v is None:
        return None
    s = str(v).strip().replace(",", "")
    if s in ("", "-", "--"):
        return None
    pct = s.endswith("%")
    if pct:
        s = s[:-1]
    try:
        f = float(s)
    except ValueError:
        raise GateFailure(f"non-numeric value {v!r}")
    return int(f) if (not pct and f.is_integer() and "." not in s) else f


def read_csv(path):
    with open(path, newline="", encoding="utf-8-sig") as fh:
        rows = list(csv.reader(fh))
    return rows[0], [r for r in rows[1:]]


# ---------------------------------------------------------------------------
# Gate 1: every manifest file exists, row count and header match exactly, and
# _incoming contains nothing we are not accounting for.
# ---------------------------------------------------------------------------

def validate_all():
    if not os.path.isdir(INCOMING):
        raise GateFailure(
            f"{INCOMING} does not exist. The CSVs are already ingested (and live in git "
            f"history); nothing to do."
        )

    on_disk = sorted(f for f in os.listdir(INCOMING) if not f.startswith("."))
    expected = sorted(m[0] for m in MANIFEST)
    if on_disk != expected:
        extra = set(on_disk) - set(expected)
        missing = set(expected) - set(on_disk)
        raise GateFailure(
            f"_incoming/ contents do not match the manifest. "
            f"missing={sorted(missing)} unexpected={sorted(extra)}"
        )

    loaded = {}
    for name, report, scope, exp_rows, exp_hdr in MANIFEST:
        hdr, rows = read_csv(os.path.join(INCOMING, name))
        label = f"{report}/{scope}"
        if hdr != exp_hdr:
            raise GateFailure(
                f"{label} ({name}): header mismatch.\n  expected {exp_hdr}\n  got      {hdr}"
            )
        if len(rows) != exp_rows:
            raise GateFailure(
                f"{label} ({name}): expected {exp_rows} content rows, got {len(rows)}"
            )
        loaded[(report, scope)] = rows
        print(f"  gate ok  {label:<24} {len(rows):>4} rows, {len(hdr)} cols")
    return loaded


# ---------------------------------------------------------------------------
# Per-report row builders. Each returns a dict of raw fields for one row.
# Duplicated source columns get an explicit suffix, per BUILD_SPEC Phase 2:
#   Red Zone   -> first block is inside-20, second inside-10  (_i20 / _i10)
#   Market RB  -> first YD%/TD% block is rushing, second receiving (_rush / _rec)
#   Target Share -> the three TGT%/CMP% pairs are WR, RB, TE in that order
# ---------------------------------------------------------------------------

def build_charts(rows, pos):
    YEARS = [2025, 2024, 2023, 2022, 2021, 2020, 2019, 2018, 2017, 2016]
    out = []
    for r in rows:
        rec = {
            "name": r[0],
            "team": r[3].strip() or None,
            "position": pos,
            "report_rank": num(r[1]),
            "total_points_3yr": num(r[2]),
        }
        for i, y in enumerate(YEARS):
            rec[f"finish_{y}"] = num(r[4 + i])
        out.append(rec)
    return out


def build_pct(rows, pos):
    hdr = H_PCT[pos]
    out = []
    for r in rows:
        rec = {"name": r[0], "team": r[1].strip() or None, "position": pos,
               "GP": num(r[2])}
        for i in range(3, 8):
            rec[hdr[i]] = num(r[i])
        out.append(rec)
    return out


def build_market_share(rows, pos):
    out = []
    for r in rows:
        rec = {"name": r[0], "team": r[1].strip() or None, "position": pos,
               "games_played": num(r[2]), "pos_pts_pct": num(r[3])}
        if pos == "RB":
            rec.update({
                "ATT%_rush": num(r[4]), "YD%_rush": num(r[5]), "TD%_rush": num(r[6]),
                "TGT%_rec": num(r[7]), "REC%_rec": num(r[8]),
                "YD%_rec": num(r[9]), "TD%_rec": num(r[10]),
            })
        else:
            rec.update({
                "TGT%_rec": num(r[4]), "REC%_rec": num(r[5]),
                "YD%_rec": num(r[6]), "TD%_rec": num(r[7]),
            })
        out.append(rec)
    return out


RZ_BLOCKS = {
    "passing":   ("pass", ["att", "att_pct", "cmp", "cmp_pct", "tds", "td_pct"]),
    "rushing":   ("rush", ["att", "att_pct", "tds", "td_pct", "team_pct"]),
    "receiving": ("rec",  ["tgt", "tgt_pct", "rec", "rec_pct", "catch_pct", "tds", "td_pct"]),
}


def build_red_zone(rows, block):
    prefix, cols = RZ_BLOCKS[block]
    n = len(cols)
    out = []
    for r in rows:
        # position is deliberately NOT taken from the file: the rushing report
        # includes QBs and the receiving report includes RBs. It is resolved
        # against canonical at merge time instead.
        rec = {"name": r[0], "team": r[1].strip() or None, "rz_block": block}
        for i, c in enumerate(cols):
            rec[f"{prefix}_{c}_i20"] = num(r[2 + i])
            rec[f"{prefix}_{c}_i10"] = num(r[2 + n + i])
        out.append(rec)
    return out


PICKS_RE = re.compile(r"^([+-])(\d+)\s*Picks?$")


def parse_diff(s):
    """'+9Picks' -> 9, '-1Pick' -> -1, '-' -> 0. Sign follows the source: positive
    means the player's TrueValue is earlier than the market's ADP (a discount)."""
    s = (s or "").strip()
    if s in ("", "-", "--"):
        return 0
    m = PICKS_RE.match(s)
    if not m:
        raise GateFailure(f"unparseable Value Scout Diff {s!r}")
    return int(m.group(2)) * (1 if m.group(1) == "+" else -1)


def build_value_scout(rows, _):
    out = []
    for r in rows:
        if r[2] != r[3]:
            raise GateFailure(f"Value Scout duplicate Pos columns disagree for {r[0]!r}")
        # r[7] "Markers" is deliberately dropped — see excluded_fields in the source
        # header. It is unclicked UI buttons on a shared account, not user judgment.
        out.append({
            "name": r[0], "team": r[1].strip() or None, "position": r[2],
            "true_value": r[4].strip() or None,
            "avg_adp": r[6].strip() or None,
            "diff_raw": r[5].strip() or None,
            "diff_picks": parse_diff(r[5]),
        })
    return out


def build_sos(rows, pos):
    out = []
    for r in rows:
        weeks = []
        for w in range(18):
            o = 3 + w * 3
            weeks.append({
                "week": w + 1,
                "opp": r[o].strip() or None,
                "opp_pts_allowed": num(r[o + 1]),
                "opp_rank": num(r[o + 2]),
            })
        out.append({
            "team": r[2].strip(), "team_name": r[0], "position": pos,
            "sos_rank": num(r[1]), "weeks": weeks,
        })
    return out


def build_target_share(rows, _):
    out = []
    for r in rows:
        out.append({
            "team": r[1].strip(), "team_name": r[0],
            "wr_tgt_pct": num(r[2]), "wr_cmp_pct": num(r[3]),
            "rb_tgt_pct": num(r[4]), "rb_cmp_pct": num(r[5]),
            "te_tgt_pct": num(r[6]), "te_cmp_pct": num(r[7]),
        })
    return out


# ---------------------------------------------------------------------------
# Source assembly. One directory per report type; the position/scope that was
# encoded in the ambiguous filename becomes a field on each row.
# ---------------------------------------------------------------------------

def key_of(rec):
    n = re.sub(r"[^a-z0-9]+", "", rec["name"].lower())
    return (n, rec.get("team"))


def merge_rows(groups, report):
    """Combine the per-file row lists of one report into one record per player.

    Only Red Zone actually overlaps across its files (a player can have both rushing
    and receiving red-zone usage). For the others an overlap would mean the same
    player was listed under two positions, which is a gate failure.
    """
    merged = {}
    for scope, rows in groups:
        for rec in rows:
            k = key_of(rec)
            if k not in merged:
                merged[k] = dict(rec)
                if report == "red_zone":
                    merged[k]["rz_blocks"] = [rec["rz_block"]]
                    del merged[k]["rz_block"]
                continue
            if report != "red_zone":
                raise GateFailure(
                    f"{report}: {rec['name']} ({rec.get('team')}) appears in more than one "
                    f"positional file — the verified file→position mapping would be wrong."
                )
            tgt = merged[k]
            tgt["rz_blocks"].append(rec["rz_block"])
            for f, v in rec.items():
                if f in ("name", "team", "rz_block"):
                    continue
                if f in tgt and tgt[f] != v:
                    raise GateFailure(f"red_zone: conflicting {f} for {rec['name']}")
                tgt[f] = v
    return list(merged.values())


PLAYER_SOURCES = {
    "udk_consistency_charts": dict(
        report="charts", builder=build_charts,
        label="UDK Consistency Charts — end-of-season positional finish rank by year",
        notes=[
            "Year columns are that season's end-of-season POSITIONAL finish rank, not points.",
            "A null year means the player did not play / was not in the league that season.",
            "'report_rank' is the player's rank within this report only (by total_points_3yr) "
            "and is unrelated to the UDK draft ranking in the 'udk' source.",
        ],
        mapping={
            "report_rank": "cons_charts_rank",
            "total_points_3yr": "cons_total_points",
            **{f"finish_{y}": f"finish_{y}" for y in range(2016, 2026)},
        },
    ),
    "udk_consistency_pct": dict(
        report="pct", builder=build_pct,
        label="UDK Consistency Percentages — last 3 seasons cumulative",
        notes=[
            "Cumulative over the last 3 seasons (Josh Allen 51 GP = 17x3). GP is the sample "
            "size and is required context for every rate below it — see BUILD_SPEC Phase 3.",
            "Positional column names differ per file (Top 12 vs Top 24, QB 1-6 vs RB1, ...) "
            "and are normalised to floor/ceiling/tier2/tier3/bust in field_mapping.json.",
            "Values are percentages expressed as numbers (69.6 means 69.6%).",
        ],
        mapping={
            "GP": "sample_gp",
            "Top 12": "floor_pct", "Top 24": "floor_pct",
            "QB 1-6": "ceiling_pct", "RB1": "ceiling_pct",
            "WR1": "ceiling_pct", "TE 1-6": "ceiling_pct",
            "QB 7-12": "tier2_pct", "RB2": "tier2_pct",
            "WR2": "tier2_pct", "TE 7-12": "tier2_pct",
            "QB2": "tier3_pct", "RB3": "tier3_pct",
            "WR3": "tier3_pct", "TE2": "tier3_pct",
            "QB3+": "bust_pct", "RB4+": "bust_pct",
            "WR4+": "bust_pct", "TE3+": "bust_pct",
        },
    ),
    "udk_market_share": dict(
        report="market_share", builder=build_market_share,
        label="UDK Market Share Report — share of team production",
        notes=[
            "There is no QB file for this report; the base file is RB, unlike every other "
            "UDK report where the base file is QB.",
            "The RB file carries duplicate YD%/TD% columns: the first block is rushing, the "
            "second receiving (confirmed by the user). Suffixed _rush / _rec here.",
            "WR/TE files have receiving columns only; they map to the same canonical "
            "receiving names as the RB file's second block.",
        ],
        mapping={
            "games_played": "ms_games_played",
            "pos_pts_pct": "pos_pts_share",
            "ATT%_rush": "att_share_rush",
            "YD%_rush": "yd_share_rush",
            "TD%_rush": "td_share_rush",
            "TGT%_rec": "tgt_share",
            "REC%_rec": "rec_share",
            "YD%_rec": "yd_share_rec",
            "TD%_rec": "td_share_rec",
        },
    ),
    "udk_red_zone": dict(
        report="red_zone", builder=build_red_zone,
        label="UDK Red Zone Report — inside-20 and inside-10 opportunity",
        notes=[
            "Each source file has two identical column blocks: the first is inside-20, the "
            "second inside-10 (confirmed by the user). Suffixed _i20 / _i10 here.",
            "These files are split by PLAY TYPE, not by position: the rushing file includes "
            "QBs (Josh Allen, Justin Fields) and the receiving file includes RBs (Christian "
            "McCaffrey) and fullbacks. Position is therefore NOT taken from the file — it is "
            "resolved against the canonical rankings at merge time.",
            "A player with both rushing and receiving red-zone usage carries both blocks; "
            "'rz_blocks' lists which are populated.",
        ],
        mapping={
            "rz_blocks": "rz_blocks",
            **{f"{p}_{c}_{d}": f"{p}_{c}_{d}"
               for p, cols in RZ_BLOCKS.values()
               for c in cols for d in ("i20", "i10")},
        },
    ),
    "udk_value_scout": dict(
        report="value_scout", builder=build_value_scout,
        label="UDK Value Scout — TrueValue vs market ADP (top 250)",
        notes=[
            "true_value and avg_adp are round.pick strings (e.g. '1.02' = round 1, pick 2).",
            "diff_picks is the source's own Diff column parsed to an integer. Sign follows "
            "the source: POSITIVE means TrueValue is earlier than ADP, i.e. a market "
            "discount. '-' in the source means no difference and parses to 0.",
            "This is the volatile tier per BUILD_SPEC Phase 6 — re-ingested daily.",
        ],
        mapping={
            "true_value": "true_value",
            "avg_adp": "avg_adp",
            "diff_raw": "adp_diff_raw",
            "diff_picks": "adp_diff_picks",
        },
        excluded_fields={
            "Markers": "Dropped deliberately per BUILD_SPEC Phase 4: these are unclicked UI "
                       "buttons on a shared account, not the user's judgement. Confirmed "
                       "identical for all 250 rows at ingest."
        },
    ),
}

TEAM_SOURCES = {
    "udk_sos": dict(
        report="sos", builder=build_sos, grain="team",
        label="UDK Strength of Schedule by Position — 18-week opponent schedule",
        notes=[
            "TEAM-grain, not player-grain: these rows do not join on player_id and are "
            "deliberately kept out of the player canonical.",
            "One row per team per position (32 teams x 4 positions = 128 rows).",
            "'opp_pts_allowed' is the opponent's points allowed to this position. A BYE week "
            "is recorded as opp='BYE' with 0 values.",
        ],
        mapping={"team_name": "team_name", "position": "position",
                 "sos_rank": "sos_rank", "weeks": "weeks"},
    ),
    "udk_target_share": dict(
        report="target_share", builder=build_target_share, grain="team",
        label="UDK Target Share Breakdown — team target/completion split by position",
        notes=[
            "TEAM-grain, not player-grain.",
            "The three unlabelled TGT%/CMP% pairs in the source are WR, RB, TE in that "
            "order (confirmed by the user); named explicitly here.",
        ],
        mapping={"team_name": "team_name",
                 "wr_tgt_pct": "wr_tgt_pct", "wr_cmp_pct": "wr_cmp_pct",
                 "rb_tgt_pct": "rb_tgt_pct", "rb_cmp_pct": "rb_cmp_pct",
                 "te_tgt_pct": "te_tgt_pct", "te_cmp_pct": "te_cmp_pct"},
    ),
}


def write_source(dirpath, source_name, spec, records, grain):
    os.makedirs(dirpath, exist_ok=True)
    payload = {
        "source": source_name,
        "source_label": spec["label"],
        "source_date": SOURCE_DATE,
        "grain": grain,
        "extracted": "mechanical CSV ingest from UDK site exports "
                     "(build/ingest_supplemental.py)",
        "notes": spec["notes"],
    }
    if spec.get("excluded_fields"):
        payload["excluded_fields"] = spec["excluded_fields"]
    payload["players" if grain == "player" else "teams"] = records

    with open(os.path.join(dirpath, "players_raw.json" if grain == "player"
                           else "team_raw.json"), "w") as f:
        json.dump(payload, f, indent=2)

    with open(os.path.join(dirpath, "field_mapping.json"), "w") as f:
        json.dump({
            "source": source_name,
            "_comment": "Maps this source's raw field names to canonical field names. Any "
                        "raw field NOT listed here is left unmapped: build_canonical.py "
                        "reports it and it will not reach the canonical dataset until "
                        "deliberately added below.",
            "mapping": spec["mapping"],
        }, f, indent=2)


def main():
    print("Validating all 20 staged CSVs before writing anything...", flush=True)
    try:
        loaded = validate_all()
    except GateFailure as e:
        print(f"\nGATE FAILED — nothing written.\n  {e}", file=sys.stderr)
        return 1

    built = {}
    try:
        for name, spec in {**PLAYER_SOURCES, **TEAM_SOURCES}.items():
            groups = [(scope, spec["builder"](rows, scope))
                      for (rep, scope), rows in loaded.items() if rep == spec["report"]]
            recs = merge_rows(groups, spec["report"]) if spec["report"] == "red_zone" \
                else [r for _, rows in groups for r in rows]
            built[name] = recs
    except GateFailure as e:
        print(f"\nGATE FAILED during row build — nothing written.\n  {e}", file=sys.stderr)
        return 1

    print("\nWriting sources:")
    for name, spec in PLAYER_SOURCES.items():
        write_source(os.path.join(SOURCES, name), name, spec, built[name], "player")
        print(f"  data/sources/{name:<26} {len(built[name]):>4} player rows")
    for name, spec in TEAM_SOURCES.items():
        write_source(os.path.join(TEAM_DIR, name), name, spec, built[name], "team")
        print(f"  data/sources/_team/{name:<20} {len(built[name]):>4} team rows")

    print("\nDone. Next: python3 build/build_canonical.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
