"""
Applies the live UDK board (build/udk_live_board.py) over the PDF-derived extraction.

    python3 build/extract_udk.py && python3 build/refresh_udk_live.py

The 8/30 PDF is a snapshot; the site keeps moving. This layers the current published
board — positional rank, projection and tier — on top of the PDF's bio and analytic
columns (age, exp, bye, risk, upside, games, 2025 finish), which the site's ranking view
does not expose.

Gated like every other write here: it validates before it writes, reports every rank,
tier and projection move, and never silently drops a player.

Players newly on the board carry live fields with the PDF-only fields null, and are
reported so the gap is visible rather than looking like complete records.
"""

import json
import os
import re
import sys
import unicodedata

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from udk_live_board import BOARD, SCAN_DATE  # noqa: E402

BASE = os.path.join(os.path.dirname(__file__), "..")
RAW = os.path.join(BASE, "data", "sources", "udk", "players_raw.json")
MIN_RETENTION = 0.95

# The ranking view does not carry a team column, so players new to the board need one.
# Only teams confirmed from another source in the repo are listed; anything absent stays
# None and is reported as a gap rather than guessed.
NEW_PLAYER_TEAMS = {
    "Najee Harris": "NYG",     # ESPN PPR300 and the UDK injury report agree
    "Malik Davis": "DAL",      # UDK rankings row
}


class GateFailure(Exception):
    pass


def fold(n):
    n = unicodedata.normalize("NFKD", n)
    n = "".join(c for c in n if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "", n.lower())


def main():
    doc = json.load(open(RAW))
    prior = doc["players"]
    idx = {(fold(p["name"]), p["position"]): p for p in prior}

    live_total = sum(len(v) for v in BOARD.values())
    if live_total < len(prior) * MIN_RETENTION:
        raise GateFailure(f"live board has {live_total} players against {len(prior)} — "
                          f"too few to be a refresh rather than a bad scrape")

    out, added, rank_moves, tier_moves, proj_moves = [], [], [], [], []
    seen = set()
    for pos, rows in BOARD.items():
        for rank, name, proj, tier in rows:
            key = (fold(name), pos)
            seen.add(key)
            old = idx.get(key)
            if old is None:
                out.append({"rank": rank, "name": name,
                            "team": NEW_PLAYER_TEAMS.get(name), "tier": tier,
                            "age": None, "exp": None, "bye": None, "adp_positional": None,
                            "risk": None, "upside": None, "proj_pts": proj,
                            "games": None, "finish_2025": None,
                            "position": pos, "tags": []})
                added.append(f"{pos}{rank} {name}"
                         + ("" if name in NEW_PLAYER_TEAMS else " [team unknown]"))
                continue
            new = dict(old)
            if old["rank"] != rank:
                rank_moves.append((abs(old["rank"] - rank), pos, name, old["rank"], rank))
            if old.get("tier") != tier:
                tier_moves.append(f"{pos} {name}: T{old.get('tier')} -> T{tier}")
            if old.get("proj_pts") is not None and abs(old["proj_pts"] - proj) > 0.05:
                proj_moves.append((abs(old["proj_pts"] - proj), pos, name,
                                   old["proj_pts"], proj))
            new.update(rank=rank, tier=tier, proj_pts=proj)
            out.append(new)

    dropped = [f"{p['position']} {p['name']}" for k, p in idx.items() if k not in seen]
    if len(out) < len(prior) * MIN_RETENTION:
        raise GateFailure(f"only {len(out)} players survive against {len(prior)} prior")

    for pos in BOARD:
        ranks = sorted(p["rank"] for p in out if p["position"] == pos)
        if ranks != list(range(1, len(ranks) + 1)):
            raise GateFailure(f"{pos} ranks are not contiguous after merge")

    doc["players"] = out
    doc["source_date"] = SCAN_DATE
    doc["extracted"] = ("mechanical PDF extraction (build/extract_udk.py) with the live "
                        "published board layered over it (build/refresh_udk_live.py)")
    doc.setdefault("known_gaps", []).append(
        f"Rank, tier and projection are from the live site as of {SCAN_DATE}. Age, exp, "
        f"bye, risk, upside, games and 2025 finish remain from the 8/30 PDF — the site's "
        f"ranking view does not publish them. Players new to the board since the PDF have "
        f"those fields null.")
    with open(RAW, "w") as f:
        json.dump(doc, f, indent=2, ensure_ascii=False)

    print(f"Applied the {SCAN_DATE} board -> {len(out)} players "
          f"(was {len(prior)})\n")
    print(f"  new to the board ({len(added)}): {', '.join(added) or 'none'}")
    print(f"  no longer ranked ({len(dropped)}): {', '.join(dropped) or 'none'}")
    print(f"  tier changes ({len(tier_moves)})")
    for t in tier_moves[:12]:
        print(f"    {t}")
    print(f"\n  biggest rank moves ({len(rank_moves)} total):")
    for d, pos, name, a, b in sorted(rank_moves, reverse=True)[:12]:
        arrow = "up" if b < a else "down"
        print(f"    {pos} {name:<24}{a:>4} -> {b:<4} ({arrow} {d})")
    print(f"\n  biggest projection moves ({len(proj_moves)} total):")
    for d, pos, name, a, b in sorted(proj_moves, reverse=True)[:10]:
        print(f"    {pos} {name:<24}{a:>7} -> {b:<7} ({b - a:+.1f})")


if __name__ == "__main__":
    sys.exit(main())
