"""
Builds the board payload the app reads: data/app/board.json

    python3 build/export_board.py

Run after claude_rank.py. Everything here is projection — no metric is invented, it is
the canonical dataset reshaped and abbreviated for the browser.

The one piece of judgement is `sig`: which of the deeper stats are actually moving a
player's rating. The UI colours only those, so a tint means something rather than
decorating every cell. A stat qualifies at a standard deviation from its positional
mean, or — for the two projections — a 12% disagreement.
"""

import json
import os
import statistics
from collections import Counter

BASE = os.path.join(os.path.dirname(__file__), "..")
CANONICAL = os.path.join(BASE, "data", "canonical", "players.json")
NOTES = os.path.join(BASE, "data", "user", "risk_upside_notes.json")
OUT_DIR = os.path.join(BASE, "data", "app")
OUT = os.path.join(OUT_DIR, "board.json")

SIG_Z = 1.0
PROJ_GAP = 0.12
BUCKETS = {"QB": ("Top12", "QB1-6", "QB3+"), "TE": ("Top12", "TE1-6", "TE3+"),
           "RB": ("Top24", "RB1", "RB4+"), "WR": ("Top24", "WR1", "WR4+")}
# metric key -> (canonical field, higher_is_better)
SIG_METRICS = {"os": ("opportunity_share", True), "rz": ("rz_volume_i10", True),
               "td": ("td_dependency", False), "vol": ("finish_volatility", False),
               "tj": ("trajectory_3yr", False), "ed": ("adp_edge", True)}


def significance(players):
    sig = {}
    for pos in sorted({p["position"] for p in players}):
        grp = [p for p in players if p["position"] == pos]
        for key, (field, higher_better) in SIG_METRICS.items():
            vals = [p["derived"].get(field) for p in grp if p["derived"].get(field) is not None]
            if len(vals) < 3:
                continue
            mu, sd = statistics.mean(vals), statistics.pstdev(vals)
            if sd == 0:
                continue
            for p in grp:
                v = p["derived"].get(field)
                if v is None:
                    continue
                z = (v - mu) / sd
                if abs(z) >= SIG_Z:
                    good = (z > 0) if higher_better else (z < 0)
                    sig.setdefault(p["player_id"], {})[key] = "g" if good else "b"
        for p in grp:
            a = p["sources"]["udk"].get("proj_pts")
            b = p["evaluation"].get("clay_proj_pts")
            if a and b and abs(b - a) / a >= PROJ_GAP:
                sig.setdefault(p["player_id"], {})["clay"] = "g" if b > a else "b"
    return sig


def main():
    doc = json.load(open(CANONICAL))
    notes = json.load(open(NOTES))
    players = doc["players"]
    sig = significance(players)

    out = []
    for p in players:
        d, e, u = p["derived"], p["evaluation"], p["sources"]["udk"]
        n = notes.get(p["player_id"], {})
        tg = p["sources"].get("udk_tags", {})
        ch = p["sources"].get("udk_consistency_charts", {})

        def side(which):
            items = [{"t": i["note"], "s": i["severity"], "g": i["src_label"]}
                     for b in ("udk", "espn") for i in n.get(which, {}).get(b, [])]
            return sorted(items, key=lambda x: -x["s"])

        out.append({
            "id": p["player_id"], "n": p["name"], "p": p["position"], "tm": p["team"],
            "bye": u.get("bye"), "tier": u.get("tier"),
            "br": e.get("board_rank"), "bpr": e.get("board_pos_rank"),
            "bs": e.get("board_score"),
            "udk": e.get("udk_rank"), "espn": e.get("espn_rank"), "adp": e.get("adp_rank"),
            "epr": e.get("espn_pos_rank"), "auc": e.get("auction_value"), "dep": e.get("depth_label"),
            "cr": e["claude_rank"], "cpr": e["claude_pos_rank"], "cv": e["claude_value"],
            "tag": e.get("claude_tag"), "why": e.get("claude_tag_why"),
            "cons": e.get("consensus_rank"), "cdl": e.get("consensus_delta"),
            "proj": u.get("proj_pts"), "clay": e.get("clay_proj_pts"),
            "sp": d.get("weekly_start_pct"), "sw": d.get("sample_weight_own"),
            "av": d.get("games_available_pct"), "ge": d.get("games_expected"),
            "ar": d.get("adj_risk"), "au": d.get("adj_upside"),
            "fl": d["floor_rate"], "ce": d["ceiling_rate"], "bu": d["bust_rate"],
            "fa": d.get("floor_rate_adj"), "ca": d.get("ceiling_rate_adj"), "ba": d.get("bust_rate_adj"),
            "lb": BUCKETS[p["position"]], "gp": d["sample_gp"], "sc": d["sample_confidence"],
            "os": d["opportunity_share"], "td": d["td_dependency"], "rz": d["rz_volume_i10"],
            "tj": d["trajectory_3yr"], "vol": d["finish_volatility"], "ed": d["adp_edge"],
            "trend": d.get("trend_label"), "tdir": d.get("trend_dir"),
            "sig": sig.get(p["player_id"], {}),
            "sr": [[y, ch.get(f"finish_{y}")] for y in range(2016, 2026)
                   if ch.get(f"finish_{y}") is not None],
            "tags": tg.get("tags", []), "inj": tg.get("injury"),
            "injt": tg.get("injury_timeline"), "injo": tg.get("injury_out"),
            "up": side("upside"), "rk": side("risk"),
        })

    out.sort(key=lambda x: x["br"])
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(OUT, "w") as f:
        json.dump({"players": out}, f, separators=(",", ":"), ensure_ascii=False)

    c = Counter(k for x in out for k in x["sig"])
    print(f"Wrote {os.path.relpath(OUT, BASE)} — {len(out)} players, "
          f"{os.path.getsize(OUT):,} bytes")
    print(f"  significant-stat flags: {dict(c)}")
    print(f"  players carrying at least one: {sum(1 for x in out if x['sig'])}")


if __name__ == "__main__":
    main()
