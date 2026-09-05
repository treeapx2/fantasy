"""
Rewrites data/sources/udk_value_scout/players_raw.json from the live scan.

    python3 build/refresh_value_scout.py

Value Scout is the OTHER half of the UDK board: the position rankings give tier and
projection, Value Scout gives TrueValue and market ADP, and the two are published
separately. Refreshing only one leaves the board internally inconsistent — which is
exactly what happened when the 9/5 rankings refresh landed against an 8/30 Value Scout
and tiers stopped lining up with overall rank.

Gated and reported like the other refreshes: row-count tolerance, retention of prior
players, and a full accounting of what moved.
"""

import json
import os
import re
import sys
import unicodedata

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from udk_value_scout_live import ROWS, SCAN_DATE  # noqa: E402

BASE = os.path.join(os.path.dirname(__file__), "..")
RAW = os.path.join(BASE, "data", "sources", "udk_value_scout", "players_raw.json")
LEAGUE_TEAMS = 12
TOLERANCE = 0.10
MIN_RETENTION = 0.90


class GateFailure(Exception):
    pass


def fold(n):
    n = unicodedata.normalize("NFKD", n)
    n = "".join(c for c in n if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "", n.lower())


def overall(rp):
    if not rp or "." not in rp:
        return None
    r, k = rp.split(".")
    return (int(r) - 1) * LEAGUE_TEAMS + int(k)


def main():
    doc = json.load(open(RAW))
    prior = {fold(p["name"]): p for p in doc["players"]}

    lo, hi = len(prior) * (1 - TOLERANCE), len(prior) * (1 + TOLERANCE)
    if not lo <= len(ROWS) <= hi:
        raise GateFailure(f"{len(ROWS)} rows against a prior {len(prior)} — outside "
                          f"+/-{int(TOLERANCE*100)}%, refusing to promote")

    out, adp_moves, tv_moves, added = [], [], [], []
    seen = set()
    for name, pos, tv, adp in ROWS:
        k = fold(name)
        seen.add(k)
        old = prior.get(k)
        tvo, adpo = overall(tv), overall(adp)
        diff = (adpo - tvo) if (tvo is not None and adpo is not None) else 0
        rec = {"name": name, "team": old["team"] if old else None, "position": pos,
               "true_value": tv, "avg_adp": adp,
               "diff_raw": (f"+{diff}Picks" if diff > 0 else
                            f"{diff}Picks" if diff < 0 else "-"),
               "diff_picks": diff}
        out.append(rec)
        if old is None:
            added.append(f"{pos} {name}")
            continue
        a, b = overall(old.get("avg_adp")), adpo
        if a is not None and b is not None and abs(b - a) >= LEAGUE_TEAMS:
            adp_moves.append((abs(b - a), pos, name, old["avg_adp"], adp))
        a, b = overall(old.get("true_value")), tvo
        if a is not None and b is not None and abs(b - a) >= LEAGUE_TEAMS:
            tv_moves.append((abs(b - a), pos, name, old["true_value"], tv))

    retained = len(seen & set(prior)) / len(prior)
    if retained < MIN_RETENTION:
        raise GateFailure(f"only {retained:.0%} of prior players retained")

    dropped = [prior[k]["name"] for k in prior if k not in seen]
    doc["players"] = out
    doc["source_date"] = SCAN_DATE
    doc["extracted"] = "read from the published Value Scout page (build/refresh_value_scout.py)"
    with open(RAW, "w") as f:
        json.dump(doc, f, indent=2, ensure_ascii=False)

    print(f"Value Scout refreshed to {SCAN_DATE} — {len(out)} rows "
          f"(was {len(prior)}, {retained:.0%} retained)\n")
    print(f"  new to the list ({len(added)}): {', '.join(added[:10]) or 'none'}")
    print(f"  dropped ({len(dropped)}): {', '.join(dropped[:10]) or 'none'}")
    print(f"\n  ADP moved a full round or more ({len(adp_moves)}):")
    for d, pos, name, a, b in sorted(adp_moves, reverse=True)[:14]:
        arrow = "RISING " if overall(b) < overall(a) else "falling"
        print(f"    {arrow} {pos} {name:<24}{a} -> {b}  ({d} picks)")
    print(f"\n  TrueValue moved a full round or more ({len(tv_moves)}):")
    for d, pos, name, a, b in sorted(tv_moves, reverse=True)[:8]:
        print(f"    {pos} {name:<24}{a} -> {b}  ({d} picks)")


if __name__ == "__main__":
    sys.exit(main())
