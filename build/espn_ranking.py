"""
Produces a single ordered draft list for entering into ESPN's custom pre-draft rankings.

    python3 build/espn_ranking.py [out_path]

## Why not just sort by tier, or by value

Tier groupings mapped to target rounds cause reaching: inside a tier there is no ordering
signal, so you take whoever is tier-eligible at your target round rather than the best
player left. A single ordered list removes that failure mode — the rule becomes "take the
top name still on the board", with nothing to interpret at 60 seconds a pick.

But ordering by raw value repeats a different mistake. claude_value is dominated by
projected points over replacement, and a player with a high projection and no weekly floor
still sorts high. Carnell Tate (value 40.1, risk 7.4, no consistency record at all) ranks
above Terry McLaurin (33.5, risk 1.2, 43.2% weekly start rate) on value alone.

So this prices risk into the ordering.

## The availability trap, handled

A naive `value - k*risk` over-punishes young players. Risk includes an availability term —
games played over games eligible — and for a second-year player that measures "was not the
starter yet", not "gets injured". Jaxson Dart's risk is 7.7 almost entirely from that term
plus small sample; he is not fragile, he is new.

So for players with two seasons or fewer, the availability component is dropped from the
penalty and the remaining components are reweighted. Their thin record still costs them
through the sample term, which is the honest charge.
"""

import json
import os
import sys

BASE = os.path.join(os.path.dirname(__file__), "..")
CANONICAL = os.path.join(BASE, "data", "canonical", "players.json")
OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(BASE, "data", "app", "espn_ranking.md")

RISK_WEIGHT = 3.0        # points of value surrendered per point of adjusted risk
UNKNOWN_FLOOR = 12.0     # extra charge for having no weekly consistency record at all
YOUNG_EXP = 2            # at or below this, availability measures opportunity not durability


def fair_risk(p):
    """adj_risk, but with the availability term removed for players too young for it to
    mean durability. Returns the 0-10 score rescaled over the components that apply."""
    d = p["derived"]
    parts = d.get("adj_risk_parts") or {}
    base = d.get("adj_risk")
    if base is None or not parts:
        return base, False
    exp = p["sources"]["udk"].get("exp")
    if exp is None or exp > YOUNG_EXP or "availability" not in parts:
        return base, False
    # Re-blend without availability, using the same weights the metric was built on.
    from derive_metrics import RISK_W
    keep = {k: v for k, v in parts.items() if k != "availability"}
    den = sum(RISK_W[k] for k in keep)
    if den == 0:
        return base, False
    z = sum(parts[k] * RISK_W[k] for k in keep) / den
    # map the reweighted z back onto the 0-10 scale using the original as anchor
    z_all = sum(parts[k] * RISK_W[k] for k in parts) / sum(RISK_W[k] for k in parts)
    adjusted = base + (z - z_all) * 2.2      # ~2.2 points of the 0-10 scale per z
    return max(0.0, min(10.0, adjusted)), True


def main():
    players = json.load(open(CANONICAL))["players"]
    rows = []
    for p in players:
        d, e, u = p["derived"], p["evaluation"], p["sources"]["udk"]
        risk, adjusted = fair_risk(p)
        risk = 5.0 if risk is None else risk
        unknown = d.get("weekly_start_pct") is None
        score = e["claude_value"] - RISK_WEIGHT * risk - (UNKNOWN_FLOOR if unknown else 0)
        rows.append({
            "name": p["name"], "pos": p["position"], "team": p["team"] or "FA",
            "tier": u.get("tier"), "bye": u.get("bye"),
            "score": round(score, 1), "value": e["claude_value"],
            "risk": round(risk, 1), "risk_adjusted": adjusted,
            "start": d.get("weekly_start_pct"), "avail": d.get("games_available_pct"),
            "upside": d.get("adj_upside"),
            "udk": e.get("udk_rank"), "espn": e.get("espn_rank"), "adp": e.get("adp_rank"),
            "tags": p["sources"].get("udk_tags", {}).get("tags", []),
        })
    rows.sort(key=lambda r: -r["score"])
    for i, r in enumerate(rows, 1):
        r["rank"] = i

    L = ["# ESPN pre-draft ranking — one ordered list",
         "",
         "Enter these in order in ESPN's custom rankings. The rule at the table is simply",
         "**take the highest name still on the board** — no tier lookup, no round targets.",
         "",
         f"Ordering: Claude value minus {RISK_WEIGHT} points per point of adjusted risk,",
         f"minus {UNKNOWN_FLOOR} for having no weekly consistency record at all.",
         "For players with 2 seasons or fewer the availability term is dropped from risk,",
         "because for them it measures opportunity rather than durability.",
         "",
         "`!` marks a player whose risk was adjusted for youth. `?` marks no weekly record.",
         "",
         "| # | player | pos | tm | T | bye | score | value | risk | start% | UDK | labels |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows[:220]:
        flags = ("!" if r["risk_adjusted"] else "") + ("?" if r["start"] is None else "")
        L.append(f"| {r['rank']} | {r['name']}{flags} | {r['pos']} | {r['team']} | "
                 f"{r['tier'] or '-'} | {r['bye'] or '-'} | {r['score']} | {r['value']} | "
                 f"{r['risk']} | {r['start'] if r['start'] is not None else '-'} | "
                 f"{r['udk'] or '-'} | {', '.join(r['tags']) or ''} |")
    # --- the back half wants the opposite bias -------------------------------
    # A risk-adjusted list optimises FLOOR, which is right for starters and wrong for
    # bench picks: there the whole point is that one of seven hits, so upside and
    # opportunity beat reliability. Ordering the tail by floor would systematically
    # rank away exactly the players worth a dart.
    L += ["", "---", "", "## Bench board — order these by upside instead",
          "",
          "From roughly pick 90 on you are not buying a starter, you are buying lottery",
          "tickets: one of seven bench picks hitting pays for the rest. So this section is",
          "ordered by **upside**, not by the risk-adjusted score above. Deliberately the",
          "opposite bias to the main list.",
          "",
          "| # | player | pos | tm | T | upside | risk | start% | value | labels |",
          "|---|---|---|---|---|---|---|---|---|---|"]
    tail = [r for r in rows if r["rank"] > 88]
    tail.sort(key=lambda r: -(r["upside"] if r["upside"] is not None else -1))
    for i, r in enumerate(tail[:60], 1):
        L.append(f"| {i} | {r['name']} | {r['pos']} | {r['team']} | {r['tier'] or '-'} | "
                 f"{r['upside']} | {r['risk']} | "
                 f"{r['start'] if r['start'] is not None else '-'} | {r['value']} | "
                 f"{', '.join(r['tags']) or ''} |")

    open(OUT, "w").write("\n".join(L))
    print(f"Wrote {os.path.relpath(OUT, BASE)} — {len(rows)} ranked, top 220 tabled\n")
    print(f"  {'#':>3} {'player':<22}{'pos':<5}{'T':<3}{'score':>7}{'value':>8}{'risk':>6}{'start':>7}")
    for r in rows[:20]:
        print(f"  {r['rank']:>3} {r['name']:<22}{r['pos']:<5}{str(r['tier']):<3}"
              f"{r['score']:>7.1f}{r['value']:>8.1f}{r['risk']:>6.1f}"
              f"{str(r['start'] if r['start'] is not None else '-'):>7}")
    print("\n  youth-adjusted risk applied to "
          f"{sum(1 for r in rows if r['risk_adjusted'])} players")


if __name__ == "__main__":
    main()
