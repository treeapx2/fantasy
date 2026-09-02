"""
Inventories every known data gap into data/gaps.json (tracked) so nothing is quietly lost.

    python3 build/report_gaps.py

Two kinds of gap, and the distinction matters for what you do about them:

  retrievable  — the datum exists somewhere we can go and get (a blurb the PDF text layer
                 dropped, a tag that needs Phase 4's visual pass). Worth a retrieval trip.
  source_gap   — the datum does not exist in the source at all (UDK publishes no QB market
                 share file; a player is absent from the rankings). No amount of re-parsing
                 will produce it, and pretending otherwise wastes a trip.

Records names only, never source prose — safe to commit.
"""

import json
import os
from collections import Counter

BASE = os.path.join(os.path.dirname(__file__), "..")
CANONICAL = os.path.join(BASE, "data", "canonical", "players.json")
BLURBS = os.path.join(BASE, "data", "sources", "_pdf", "blurbs.json")
OUT = os.path.join(BASE, "data", "gaps.json")
NOTES = os.path.join(BASE, "data", "user", "risk_upside_notes.json")

PRIORITY_CUTOFF = 200   # inside the draftable universe = worth retrieving


def main():
    doc = json.load(open(CANONICAL))
    players = doc["players"]
    by_id = {p["player_id"]: p for p in players}

    def tv(p):
        v = p["derived"].get("true_value_pick")
        return v if v is not None else 10 ** 6
    value_order = sorted(players, key=lambda p: (tv(p), p["sources"]["udk"]["rank"]))
    overall = {p["player_id"]: i + 1 for i, p in enumerate(value_order)}

    def entry(p, why):
        return {"player_id": p["player_id"], "name": p["name"],
                "position": p["position"], "value_rank": overall[p["player_id"]],
                "in_top_200": overall[p["player_id"]] <= PRIORITY_CUTOFF, "detail": why}

    gaps = {}

    # --- blurbs -----------------------------------------------------------
    if os.path.exists(BLURBS):
        entries = json.load(open(BLURBS))["entries"]
        thin = [by_id[e["player_id"]] for e in entries
                if e["player_id"] and len(e["blurb"]) < 120]
        trunc = [by_id[e["player_id"]] for e in entries
                 if e["player_id"] and 120 <= len(e["blurb"]) < 330]
        gaps["blurb_missing"] = {
            "kind": "retrievable",
            "why": "PDF text layer drops prose at some column and section breaks. Recover "
                   "by reading those pages visually, or with a layout-aware extractor.",
            "players": sorted([entry(p, "no usable blurb") for p in thin],
                              key=lambda e: e["value_rank"]),
        }
        gaps["blurb_possibly_truncated"] = {
            "kind": "retrievable",
            "why": "Unusually short blurb — may be cut off mid-sentence at a page break. "
                   "Chase Brown is the confirmed case. Worth spot-checking against the PDF.",
            "players": sorted([entry(p, "short blurb, verify") for p in trunc],
                              key=lambda e: e["value_rank"])[:25],
        }
    else:
        gaps["blurb_missing"] = {"kind": "retrievable",
                                 "why": "blurbs.json absent — run build/parse_blurbs.py",
                                 "players": []}

    # --- per-source coverage ---------------------------------------------
    for src, label, kind, why in [
        ("udk_consistency_pct", "consistency percentages", "source_gap",
         "Player has fewer than the reporting threshold of games in the 3-year window, or "
         "is absent from UDK's consistency report. Not retrievable from this source."),
        ("udk_consistency_charts", "consistency charts", "source_gap",
         "Absent from UDK's historical finish table."),
        ("udk_market_share", "market share", "source_gap",
         "UDK publishes NO QB market share file, so all 36 QBs are structurally absent. "
         "Non-QBs here are simply outside the report."),
        ("udk_red_zone", "red zone", "source_gap",
         "No red-zone usage recorded in the source."),
        ("udk_value_scout", "value scout", "source_gap",
         "Outside UDK's top-250 value list."),
    ]:
        missing = [p for p in players if src not in p["sources"]]
        gaps[f"no_{src}"] = {
            "kind": kind, "why": why, "count": len(missing),
            "in_top_200": sum(1 for p in missing if overall[p["player_id"]] <= PRIORITY_CUTOFF),
            "players": sorted([entry(p, f"no {label} data") for p in missing
                               if overall[p["player_id"]] <= PRIORITY_CUTOFF],
                              key=lambda e: e["value_rank"]),
        }

    # --- known source defects --------------------------------------------
    gaps["tags_unpopulated"] = {
        "kind": "retrievable",
        "why": "My Guy / Value / Sleeper / Breakout / Bust / Injury Concerns render as glyphs "
               "the text layer drops. Only Rookie is derived (from exp == 0). This is Phase 4.",
        "count": sum(1 for p in players if not p["sources"]["udk"].get("tags")),
        "players": [],
    }
    te_null = [p for p in players if p["position"] == "TE"
               and p["sources"]["udk"].get("games_2025") is None]
    gaps["te_games_and_finish_null"] = {
        "kind": "retrievable",
        "why": "Cropped out of the source page layout for every TE — a layout gap, not a "
               "sampling gap. Recoverable with a visual pass over the TE pages.",
        "count": len(te_null),
        "players": [entry(p, "games_2025 / finish_2025 null") for p in te_null
                    if overall[p["player_id"]] <= PRIORITY_CUTOFF][:15],
    }
    gaps["absent_from_rankings"] = {
        "kind": "source_gap",
        "why": "Present in UDK's own Value Scout top-250 but with no row in the rankings "
               "PDF — confirmed by searching the PDF text, where the name appears only "
               "inside other players' blurbs. UDK is inconsistent with itself here; this is "
               "NOT an extraction defect. Nothing can attach to these players.",
        "players": [{"name": "Najee Harris", "position": "RB", "team": "NYG",
                     "detail": "Value Scout TrueValue 17.10 / ADP 19.04, no rankings row"}],
    }
    shaheed = [p for p in players if p["name"].startswith("Rashid Shaheed")]
    gaps["impossible_value"] = {
        "kind": "source_gap",
        "why": "Source lists a games total above the 17-game maximum. Kept as-is rather "
               "than silently corrected.",
        "players": [entry(p, f"games_2025 = {p['sources']['udk'].get('games_2025')}")
                    for p in shaheed],
    }
    undrafted = [p for p in players
                 if p["derived"].get("adp_edge_status") == "undrafted_in_source"]
    gaps["adp_edge_uncomputable"] = {
        "kind": "source_gap",
        "why": "TrueValue or Average ADP is the literal string 'Undrafted' in Value Scout, "
               "so no pick differential exists.",
        "players": [entry(p, "Undrafted in one ADP column") for p in undrafted],
    }

    # --- notes coverage ---------------------------------------------------
    if os.path.exists(NOTES):
        n = json.load(open(NOTES))
        done = {pid for pid, v in n.items()
                if v["risk"].get("udk") or v["upside"].get("udk")}
        todo = [p for p in value_order[:PRIORITY_CUTOFF] if p["player_id"] not in done]
        gaps["notes_not_yet_written"] = {
            "kind": "retrievable",
            "why": "Phase 5 scope is the top 200 by UDK overall value. These remain.",
            "count": len(todo),
            "players": [entry(p, "no notes yet") for p in todo][:250],
        }

    payload = {
        "generated_from": {"player_count": doc["player_count"],
                           "blurbs_present": os.path.exists(BLURBS)},
        "legend": {"retrievable": "the datum exists and can be fetched — worth a trip",
                   "source_gap": "the datum does not exist in the source — do not re-parse"},
        "gaps": gaps,
    }
    with open(OUT, "w") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)

    print(f"Wrote {os.path.relpath(OUT, BASE)}\n")
    print(f"  {'gap':<34}{'kind':<13}{'count':>7}{'top-200':>9}")
    for k, v in gaps.items():
        cnt = v.get("count", len(v.get("players", [])))
        t200 = v.get("in_top_200", sum(1 for p in v.get("players", [])
                                       if p.get("in_top_200")))
        print(f"  {k:<34}{v['kind']:<13}{cnt:>7}{t200:>9}")
    retr = [k for k, v in gaps.items() if v["kind"] == "retrievable"
            and (v.get("count") or len(v.get("players", [])))]
    print(f"\n  Retrievable (worth a trip): {', '.join(retr)}")


if __name__ == "__main__":
    main()
