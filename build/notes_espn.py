"""
Generates ESPN-derived notes into build/notes/espn_derived.json.

These are mechanical, not written prose: every one is a statement the ESPN data supports
directly, and each fires only on a threshold worth a manager's attention. A note that says
"ESPN has him 40 spots higher than UDK" is worth reading; one that says "3 spots higher"
is noise, so the thresholds are set at a round (12 picks) or better.

Run, then merge and cap:
    python3 build/notes_espn.py
    python3 build/apply_notes.py build/notes/espn_derived.json --reconcile --cap 3
"""

import json
import os

BASE = os.path.join(os.path.dirname(__file__), "..")
CANONICAL = os.path.join(BASE, "data", "canonical", "players.json")
OUT = os.path.join(BASE, "build", "notes", "espn_derived.json")

SRC, LABEL = "espn", "ESPN 8/31"
ROUND = 12
BIG_RANK_GAP = 2 * ROUND       # two rounds apart is a real disagreement
PROJ_GAP = 0.12                # 12% projection difference


def note(t, sev, cites):
    return {"note": t, "src": SRC, "src_label": LABEL, "severity": sev, "cites": cites}


def main():
    doc = json.load(open(CANONICAL))
    payload = {}

    for p in doc["players"]:
        e = p["evaluation"]
        up, rk = [], []
        udk, espn = e.get("udk_rank"), e.get("espn_rank")
        udk_proj = p["sources"]["udk"].get("proj_pts")
        clay = e.get("clay_proj_pts")
        depth = e.get("depth_label")
        slot = p["sources"].get("espn_depth", {}).get("depth_slot")

        # --- board disagreement -------------------------------------------
        if udk and espn:
            gap = udk - espn                      # positive: ESPN likes him more
            if gap >= BIG_RANK_GAP:
                up.append(note(f"ESPN ranks him {gap} spots above UDK (#{espn} vs #{udk}) — "
                               f"a two-board disagreement in his favour", 2, ["espn_rank"]))
            elif -gap >= BIG_RANK_GAP:
                rk.append(note(f"ESPN ranks him {-gap} spots below UDK (#{espn} vs #{udk}) — "
                               f"the two boards do not agree he is this good", 2, ["espn_rank"]))
        elif udk and udk <= 150 and not espn:
            rk.append(note("Absent from ESPN's top 300 entirely despite a top-150 UDK rank — "
                           "one of the two boards is badly wrong about him", 2, ["espn_rank"]))

        # --- independent projection ---------------------------------------
        if udk_proj and clay:
            d = (clay - udk_proj) / udk_proj
            if d >= PROJ_GAP:
                up.append(note(f"Clay projects {clay} pts against UDK's {udk_proj} — "
                               f"{round(d * 100)}% more, from an independent model",
                               2, ["clay_proj_pts"]))
            elif d <= -PROJ_GAP:
                rk.append(note(f"Clay projects only {clay} pts against UDK's {udk_proj} — "
                               f"{round(-d * 100)}% less, from an independent model",
                               2, ["clay_proj_pts"]))

        # --- role, per ESPN's fantasy depth chart -------------------------
        if slot and depth:
            pos = p["position"]
            if slot >= 3 and pos in ("RB", "WR"):
                rk.append(note(f"ESPN slots him {depth} — third or deeper in his own room, "
                               f"so the touches have to come from someone else's injury",
                               2, ["depth_slot"]))
            elif slot == 1 and (p["sources"]["udk"].get("tier") or 0) >= 6:
                up.append(note(f"ESPN has him as his team's {depth} despite a tier "
                               f"{p['sources']['udk']['tier']} UDK grade — the role is "
                               f"better than the ranking implies", 1, ["depth_slot"]))

        if up or rk:
            payload[p["player_id"]] = {k: v for k, v in (("upside", up), ("risk", rk)) if v}

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump({"source": SRC, "source_label": LABEL, "batch": "espn_derived",
               "notes": payload}, open(OUT, "w"), indent=2, ensure_ascii=False)
    n = sum(len(v.get("upside", [])) + len(v.get("risk", [])) for v in payload.values())
    print(f"Wrote {os.path.relpath(OUT, BASE)} — {len(payload)} players, {n} notes")
    from collections import Counter
    c = Counter(x["note"].split("—")[0][:26].strip()
                for v in payload.values() for s in v.values() for x in s)
    for k, v in c.most_common():
        print(f"   {v:>4}  {k}…")


if __name__ == "__main__":
    main()
