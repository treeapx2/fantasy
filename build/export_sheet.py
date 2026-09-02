"""
Writes a portable plain-text draft sheet — the board in a form you can attach to a
chat, print, or read offline. Artifact URLs are private and cannot be fetched by an
external tool, so this is how the board travels.

    python3 build/export_sheet.py [out_path]      # default: draft_sheet.md at repo root

Rates are printed as "UDK -> adjusted" because the adjusted figure is what the rank is
built from, and a reader given only the raw number will misread every short sample.
"""
import json, os, statistics, sys

BASE = os.path.join(os.path.dirname(__file__), "..")
OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(BASE, "draft_sheet.md")
K = 17
LBL = {"QB": ("Top12", "QB1-6", "QB3+"), "TE": ("Top12", "TE1-6", "TE3+"),
       "RB": ("Top24", "RB1", "RB4+"), "WR": ("Top24", "WR1", "WR4+")}

doc = json.load(open(os.path.join(BASE, "data/canonical/players.json")))
notes = json.load(open(os.path.join(BASE, "data/user/risk_upside_notes.json")))
players = doc["players"]

pri = {}
for pos in ("QB", "RB", "WR", "TE"):
    g = [p for p in players if p["position"] == pos]
    pri[pos] = {k: statistics.mean([p["derived"][k] for p in g if p["derived"][k] is not None])
                for k in ("floor_rate", "ceiling_rate", "bust_rate")}


def sh(r, gp, prior):
    return None if (r is None or gp is None) else round((r * gp + prior * K) / (gp + K), 1)


def f(v, suf=""):
    return "-" if v is None else f"{v}{suf}"


L = []
L.append("# Draft sheet — 12-team PPR, 4pt passing TD, ESPN standard, drafting at pick #5")
L.append("")
L.append("## How to read this")
L.append("")
L.append("**Claude rank** is my board; **UDK rank** is the Ultimate Draft Kit's. Both are raw ranks.")
L.append("**Value** = projected points over positional replacement (QB12/RB30/WR36/TE12 in a "
         "12-team lineup), adjusted by a four-pillar score (production 35%, reliability 25%, "
         "upside 25%, market 15%).")
L.append("")
L.append("**Rates read `UDK -> adjusted`.** The left figure is what UDK recorded over the last 3 "
         "seasons; the right is that figure weighted against the positional average by games "
         f"played (prior weight K={K} games). A player's own record carries `gp/(gp+{K})` of the "
         "weight. **The rank is built from the adjusted figure** — a rate on 8 games is mostly "
         "noise, so quoting the raw number for a short sample is misleading.")
L.append("")
L.append("**The rate buckets differ by position**, so ceilings are NOT comparable across "
         "positions: RB/WR floor is a top-24 week and ceiling is a top-12 (RB1/WR1) week; QB/TE "
         "floor is top-12 and ceiling is top-6.")
L.append("")
L.append("Positional averages (floor / ceiling / bust): " + " · ".join(
    f"**{k}** {v['floor_rate']:.1f} / {v['ceiling_rate']:.1f} / {v['bust_rate']:.1f}"
    for k, v in sorted(pri.items())))
L.append("")
L.append("**Other fields.** `opp share` = rush-attempt + target share (RB) or target share "
         "(WR/TE); no QB market-share file exists. `i10` = inside-10 scoring touches. "
         "`TD dep` = TD share minus yardage share — large positive means TD-dependent and due "
         "regression, large negative means TD-unlucky. `ADP edge` = picks between UDK's TrueValue "
         "and market ADP on a 12-team board; positive = market discount.")
L.append("")
L.append("**Notes** paraphrase UDK's analyst write-ups. Arrows are severity: `^^`/`vv` move the "
         "player's value materially, `^`/`v` are secondary. Some notes flag that the source blurb "
         "was missing or misattributed in extraction — those reads lean on metrics.")
L.append("")
L.append("Your picks (snake, 12 teams, slot 5): " +
         ", ".join(str((r - 1) * 12 + (5 if r % 2 else 8)) for r in range(1, 17)))
L.append("")
L.append("---")
L.append("")

for p in sorted(players, key=lambda x: x["evaluation"]["claude_rank"]):
    e, d, u = p["evaluation"], p["derived"], p["sources"]["udk"]
    n = notes.get(p["player_id"], {})
    up = sorted(n.get("upside", {}).get("udk", []), key=lambda x: -x["severity"])
    rk = sorted(n.get("risk", {}).get("udk", []), key=lambda x: -x["severity"])
    if not (up or rk):
        continue
    lb = LBL[p["position"]]
    L.append(f"## {e['claude_rank']}. {p['name']} — {p['position']}{e['claude_pos_rank']} · "
             f"{p['team']} · bye {f(u.get('bye'))}")
    L.append(f"Claude **{e['claude_rank']}** | UDK **{f(e['market_rank'])}** | "
             f"value {e['claude_value']} (vorp {e['vorp']}, opinion {e['opinion_pts']:+}) | "
             f"proj {f(u.get('proj_pts'))} | tier {f(u.get('tier'))} | confidence {e['rank_confidence']}")
    if d["floor_rate"] is not None:
        gp = d["sample_gp"]
        w = round(100 * gp / (gp + K))
        L.append(f"Sample **{gp} gp ({d['sample_confidence']})** — his record carries {w}% of the "
                 f"weight, the {p['position']} average {100 - w}%.")
        L.append(f"- {lb[0]} floor: {d['floor_rate']}% -> **{sh(d['floor_rate'], gp, pri[p['position']]['floor_rate'])}%**")
        L.append(f"- {lb[1]} ceiling: {d['ceiling_rate']}% -> **{sh(d['ceiling_rate'], gp, pri[p['position']]['ceiling_rate'])}%**")
        L.append(f"- {lb[2]} bust: {d['bust_rate']}% -> **{sh(d['bust_rate'], gp, pri[p['position']]['bust_rate'])}%**")
    else:
        L.append("Sample: **none** — no consistency record, so the rank leans on projection and role.")
    L.append(f"opp share {f(d['opportunity_share'], '%')} | i10 {f(d['rz_volume_i10'])} | "
             f"TD dep {f(d['td_dependency'])} | trajectory {f(d['trajectory_3yr'])} "
             f"(neg = improving) | volatility {f(d['finish_volatility'])} | "
             f"ADP edge {f(d['adp_edge'])}")
    if up:
        L.append("")
        L.append("**Pros**")
        for i in up:
            L.append(f"- {'^' * i['severity']} {i['note']}" + (f" _({', '.join(i['cites'])})_" if i["cites"] else ""))
    if rk:
        L.append("")
        L.append("**Cons**")
        for i in rk:
            L.append(f"- {'v' * i['severity']} {i['note']}" + (f" _({', '.join(i['cites'])})_" if i["cites"] else ""))
    L.append("")

open(OUT, "w").write("\n".join(L))
n = sum(1 for p in players if notes.get(p["player_id"], {}).get("upside", {}).get("udk")
        or notes.get(p["player_id"], {}).get("risk", {}).get("udk"))
print(f"Wrote {OUT} — {n} players, {os.path.getsize(OUT):,} bytes "
      f"(~{os.path.getsize(OUT)//4:,} tokens)")
