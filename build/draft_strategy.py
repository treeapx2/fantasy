"""
Positional scarcity and tier-cliff analysis — the reference for in-draft advice.

    python3 build/draft_strategy.py [--teams 12] [--rounds 16]

The question this answers is not "who is the best player left" — the board already
sorts for that. It is "which POSITION should the next pick come from", which depends on
what falls off a cliff soonest.

Three things drive that:

  cliff      the value gap between one tier and the next at a position. A big gap means
             the tier is worth reaching for; a flat run means you can wait.
  depth      how many startable players remain at the position. Twelve teams needing a
             starter against fourteen candidates is scarce; against forty it is not.
  fungibility how much you lose by taking the Nth-best rather than the best. This is
             replacement thinking applied within the draft rather than across the season.

Nothing here is league-slot specific beyond the team count and the standard lineup, so
it holds for any season the data is refreshed for.
"""

import argparse
import json
import os
import statistics
from collections import defaultdict

BASE = os.path.join(os.path.dirname(__file__), "..")
CANONICAL = os.path.join(BASE, "data", "canonical", "players.json")

# ESPN standard starting lineup, per team.
STARTERS = {"QB": 1, "RB": 2, "WR": 2, "TE": 1}
FLEX_FROM = ("RB", "WR", "TE")
FLEX_SLOTS = 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--teams", type=int, default=12)
    ap.add_argument("--rounds", type=int, default=16)
    args = ap.parse_args()
    T = args.teams

    players = json.load(open(CANONICAL))["players"]
    byp = defaultdict(list)
    for p in players:
        byp[p["position"]].append(p)
    for pos in byp:
        byp[pos].sort(key=lambda p: -p["evaluation"]["claude_value"])

    print(f"Draft strategy reference — {T} teams, {args.rounds} rounds, "
          f"{T * args.rounds} total picks\n")

    # ---- demand vs supply -------------------------------------------------
    print("POSITIONAL DEMAND")
    print(f"  {'pos':<5}{'starters':>9}{'+flex':>7}{'startable left':>16}{'ratio':>8}")
    demand = {}
    for pos in ("QB", "RB", "WR", "TE"):
        need = STARTERS[pos] * T
        flex = FLEX_SLOTS * T if pos in FLEX_FROM else 0
        # startable = above the replacement line the ranking already uses
        startable = sum(1 for p in byp[pos] if p["evaluation"]["vorp"] > 0)
        demand[pos] = (need, flex, startable)
        ratio = startable / need if need else 0
        print(f"  {pos:<5}{need:>9}{flex:>7}{startable:>16}{ratio:>8.2f}")
    print("  ratio = startable bodies per required starter. Under ~1.5 is genuinely thin;")
    print("  the flex column is extra competition RB/WR/TE face that QB does not.\n")

    # ---- tier cliffs ------------------------------------------------------
    print("TIER CLIFFS  (mean Claude value by tier, and the drop to the next tier)")
    cliffs = []
    for pos in ("QB", "RB", "WR", "TE"):
        tiers = defaultdict(list)
        for p in byp[pos]:
            t = p["sources"]["udk"].get("tier")
            if t is not None:
                tiers[t].append(p["evaluation"]["claude_value"])
        ks = sorted(tiers)
        print(f"\n  {pos}")
        for i, t in enumerate(ks):
            mean = statistics.mean(tiers[t])
            nxt = statistics.mean(tiers[ks[i + 1]]) if i + 1 < len(ks) else None
            drop = (mean - nxt) if nxt is not None else None
            bar = "#" * max(0, min(28, int((drop or 0) / 6)))
            if drop is not None and len(tiers[t]) <= 6:
                cliffs.append((drop, pos, t, len(tiers[t])))
            print(f"    T{t:<3}n={len(tiers[t]):<3}mean {mean:>7.1f}"
                  + (f"   drop {drop:>6.1f}  {bar}" if drop is not None else "   —"))

    print("\nSTEEPEST CLIFFS worth reaching for (small tier, big drop after it)")
    for drop, pos, t, n in sorted(cliffs, reverse=True)[:8]:
        left = [p["name"] for p in byp[pos]
                if p["sources"]["udk"].get("tier") == t][:n]
        print(f"  {pos} tier {t:<3}{n} player(s), {drop:>6.1f} value drops after: "
              f"{', '.join(left)}")

    # ---- fungibility ------------------------------------------------------
    print("\nFUNGIBILITY  (value lost taking the Nth best instead of the best)")
    print(f"  {'pos':<5}" + "".join(f"{'#'+str(n):>9}" for n in (1, 6, 12, 24, 36)))
    for pos in ("QB", "RB", "WR", "TE"):
        row = f"  {pos:<5}"
        top = byp[pos][0]["evaluation"]["claude_value"]
        for n in (1, 6, 12, 24, 36):
            if len(byp[pos]) >= n:
                row += f"{top - byp[pos][n-1]['evaluation']['claude_value']:>9.1f}"
            else:
                row += f"{'—':>9}"
        print(row)
    print("  A flat row means waiting costs little. A steep one means the position is")
    print("  top-heavy and the early names are the whole reason to draft it.\n")

    # ---- what the shape implies ------------------------------------------
    print("SHAPE OF THE BOARD")
    qb_flat = (byp["QB"][0]["evaluation"]["claude_value"]
               - byp["QB"][11]["evaluation"]["claude_value"])
    te_cliff = (byp["TE"][0]["evaluation"]["claude_value"]
                - byp["TE"][5]["evaluation"]["claude_value"])
    rb_cliff = (byp["RB"][0]["evaluation"]["claude_value"]
                - byp["RB"][23]["evaluation"]["claude_value"])
    print(f"  QB1 to QB12 spans {qb_flat:.0f} value  -> "
          f"{'wait, the position is flat' if qb_flat < 80 else 'the top QBs are worth paying for'}")
    print(f"  TE1 to TE6 spans {te_cliff:.0f} value  -> "
          f"{'the elite TEs are a real edge' if te_cliff > 45 else 'TE is fungible early'}")
    print(f"  RB1 to RB24 spans {rb_cliff:.0f} value -> "
          f"{'RB decays fast, get yours early' if rb_cliff > 120 else 'RB holds its value'}")


if __name__ == "__main__":
    main()
