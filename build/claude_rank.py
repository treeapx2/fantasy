"""
Claude Rank — a single sortable evaluation per player, written to players[].evaluation.

    python3 build/claude_rank.py     # run after derive_metrics.py

## Why this exists despite BUILD_SPEC saying not to blend

BUILD_SPEC Phase 3 says "do not blend these into a single composite score... the user does
the weighing." The user has since asked for exactly such a score. This does NOT replace
that rule — every separate dimension stays in `derived`, untouched and visible. This is an
additional, fully auditable opinion sitting beside them: `evaluation.parts` shows each
pillar's contribution, so any ranking can be traced back to the inputs that produced it.

## The sample-size trap, handled properly

The project's founding failure is treating a rate on 8 games as equal to one on 41. A
naive composite reproduces it instantly. So every rate is shrunk toward its positional
mean before use, weighted by the games behind it:

    shrunk = (rate * gp + positional_mean * K) / (gp + K),  K = 17 (one season)

Cam Skattebo's 87.5% top-24 rate on 8 games shrinks to roughly the positional average;
Christian McCaffrey's 91.9% on 37 barely moves. The flag stays too, but the arithmetic no
longer needs it to avoid the mistake.

## Structure

Four pillars, each a weighted blend of within-position z-scores:

  production   35%  the volume and usage behind the projection
  reliability  25%  how often he actually delivers, and how steady
  upside       25%  the top end, and whether he is trending toward it
  market       15%  where he can be had relative to that

Scores are within-position (a TE's 150 projected points is not worse than a QB's 300).
Cross-position ordering is then done in POINTS, not z-scores:

    claude_value = vorp + claude_score * 20

where `vorp` is projected points above replacement level for that position — the last
startable player in a 12-team ESPN lineup, with RB/WR run deeper to account for the flex.
This is what lets an elite TE outrank a mid RB honestly: the TE12 fallback is so much worse
than the RB30 fallback that the same raw projection is worth more. It also correctly pushes
QBs down in a 1QB league, where the QB12 fallback is nearly as good as the QB3.

`claude_value` is the sortable number. `rank_delta` against the market is the actionable
part — where this disagrees with ADP.

Players missing whole pillars have them imputed neutral, and the total is damped by how
complete their data is — a thin profile should not move a full round on half the evidence.
"""

import json
import os
import statistics
import sys

BASE = os.path.join(os.path.dirname(__file__), "..")
CANONICAL = os.path.join(BASE, "data", "canonical", "players.json")

SHRINK_K = 17                 # one season of games as the prior's weight
LEAGUE_TEAMS = 12
POINTS_PER_Z = 20             # how many projected points one standard deviation is worth

# Replacement level: the last player at each position you could plausibly start in a
# 12-team ESPN standard lineup (QB1/RB2/WR2/TE1/FLEX). RB and WR run deeper than their
# nominal starter count because the flex is filled from them. This is what makes points
# comparable ACROSS positions: an elite TE is worth more than his raw projection suggests
# because the TE12 alternative is so much worse, while QB depth makes QB points cheap.
REPLACEMENT_SLOT = {"QB": 12, "RB": 30, "WR": 36, "TE": 12}

PILLARS = {
    "production":  (0.35, [("proj_pts", 0.55), ("opportunity_share", 0.25),
                           ("rz_volume_i10", 0.20)]),
    "reliability": (0.25, [("floor_s", 0.45), ("bust_s_neg", 0.35),
                           ("volatility_neg", 0.20)]),
    "upside":      (0.25, [("ceiling_s", 0.50), ("trajectory_neg", 0.25),
                           ("udk_upside", 0.25)]),
    "market":      (0.15, [("adp_edge", 0.65), ("td_dependency_neg", 0.35)]),
}


class GateFailure(Exception):
    pass


def shrink(rate, gp, prior):
    if rate is None or gp is None:
        return None
    return (rate * gp + prior * SHRINK_K) / (gp + SHRINK_K)


def zmap(values):
    """value -> z, computed only over players who actually have the metric."""
    vals = [v for v in values.values() if v is not None]
    if len(vals) < 2:
        return {k: 0.0 for k in values}
    mu = statistics.mean(vals)
    sd = statistics.pstdev(vals)
    if sd == 0:
        return {k: 0.0 for k in values}
    return {k: ((v - mu) / sd if v is not None else None) for k, v in values.items()}


def build_features(players):
    """Per position: raw feature dict -> z-scores. Returns {pid: {feature: z}}."""
    out = {p["player_id"]: {} for p in players}
    for pos in sorted({p["position"] for p in players}):
        grp = [p for p in players if p["position"] == pos]

        # Positional priors for shrinkage, from players who have real rates.
        def prior(key):
            vals = [p["derived"][key] for p in grp if p["derived"][key] is not None]
            return statistics.mean(vals) if vals else 0.0

        pf, pc, pb = prior("floor_rate"), prior("ceiling_rate"), prior("bust_rate")

        raw = {}
        for p in grp:
            d, u = p["derived"], p["sources"]["udk"]
            gp = d["sample_gp"]
            raw[p["player_id"]] = {
                "proj_pts": u.get("proj_pts"),
                "opportunity_share": d["opportunity_share"],
                "rz_volume_i10": d["rz_volume_i10"],
                "floor_s": shrink(d["floor_rate"], gp, pf),
                "bust_s_neg": (-shrink(d["bust_rate"], gp, pb)
                               if d["bust_rate"] is not None else None),
                "volatility_neg": (-d["finish_volatility"]
                                   if d["finish_volatility"] is not None else None),
                "ceiling_s": shrink(d["ceiling_rate"], gp, pc),
                "trajectory_neg": (-d["trajectory_3yr"]
                                   if d["trajectory_3yr"] is not None else None),
                "udk_upside": u.get("upside"),
                "adp_edge": d["adp_edge"],
                "td_dependency_neg": (-d["td_dependency"]
                                      if d["td_dependency"] is not None else None),
            }
        for feat in next(iter(raw.values())):
            for pid, z in zmap({pid: r[feat] for pid, r in raw.items()}).items():
                out[pid][feat] = z
    return out


def evaluate(players):
    feats = build_features(players)

    def tv(p):
        v = p["derived"].get("true_value_pick")
        return v if v is not None else None

    for p in players:
        f = feats[p["player_id"]]
        parts, present, total_feats = {}, 0, 0
        score = 0.0
        for pillar, (w, members) in PILLARS.items():
            num = den = 0.0
            got = 0
            for feat, fw in members:
                total_feats += 1
                z = f.get(feat)
                if z is None:
                    continue
                num += z * fw
                den += fw
                got += 1
                present += 1
            # Missing features inside a pillar are dropped and the rest reweighted,
            # rather than imputed as zero, which would drag every partial player to
            # the middle and hide the difference between "average" and "unknown".
            pv = (num / den) if den else 0.0
            parts[pillar] = round(pv, 3)
            score += pv * w

        completeness = present / total_feats
        # Damp the opinion by how much evidence is behind it: a half-populated profile
        # should not move a player a full round.
        damped = score * (0.5 + 0.5 * completeness)

        # A rank built on a third of the inputs is not the same claim as one built on
        # all of them. Say so, rather than letting a thin profile look authoritative.
        if completeness >= 0.85 and p["derived"]["sample_confidence"] == "high":
            flag = "solid"
        elif completeness >= 0.6:
            flag = "moderate"
        else:
            flag = "thin"

        p["evaluation"] = {
            "claude_score": round(damped, 4),
            "rank_confidence": flag,
            "claude_score_raw": round(score, 4),
            "parts": parts,
            "data_completeness": round(completeness, 3),
            "sample_confidence": p["derived"]["sample_confidence"],
            "market_pick": tv(p),
        }

    # Cross-position ordering. Raw projected points are not comparable across positions,
    # so everything is measured against replacement level: how many points this player
    # gives you over the best guy you could have had for free at his position. Then the
    # composite opinion is added, priced in points.
    repl = {}
    for pos, slot in REPLACEMENT_SLOT.items():
        pts = sorted((p["sources"]["udk"].get("proj_pts") or 0
                      for p in players if p["position"] == pos), reverse=True)
        repl[pos] = pts[slot - 1] if len(pts) >= slot else (pts[-1] if pts else 0.0)

    for p in players:
        e = p["evaluation"]
        proj = p["sources"]["udk"].get("proj_pts") or 0.0
        e["replacement_pts"] = round(repl[p["position"]], 1)
        e["vorp"] = round(proj - repl[p["position"]], 1)
        e["opinion_pts"] = round(e["claude_score"] * POINTS_PER_Z, 1)
        # The sortable evaluation: replacement-adjusted value, moved by the opinion.
        e["claude_value"] = round(e["vorp"] + e["opinion_pts"], 1)

    order = sorted(players, key=lambda p: -p["evaluation"]["claude_value"])
    ranked = [p for p in players if p["evaluation"]["market_pick"] is not None]
    market_order = sorted(ranked, key=lambda p: p["evaluation"]["market_pick"])
    market_rank = {p["player_id"]: i + 1 for i, p in enumerate(market_order)}

    for i, p in enumerate(order):
        e = p["evaluation"]
        e["claude_rank"] = i + 1
        e["market_rank"] = market_rank.get(p["player_id"])
        e["rank_delta"] = (e["market_rank"] - e["claude_rank"]
                           if e["market_rank"] is not None else None)
        e["claude_round_pick"] = "%d.%02d" % (i // LEAGUE_TEAMS + 1, i % LEAGUE_TEAMS + 1)

    for pos in sorted({p["position"] for p in players}):
        grp = sorted([p for p in players if p["position"] == pos],
                     key=lambda p: p["evaluation"]["claude_rank"])
        for i, p in enumerate(grp):
            p["evaluation"]["claude_pos_rank"] = i + 1


def gates(players):
    if len(players) != 312:
        raise GateFailure(f"expected 312 players, got {len(players)}")
    ranks = [p["evaluation"]["claude_rank"] for p in players]
    if sorted(ranks) != list(range(1, len(players) + 1)):
        raise GateFailure("claude_rank is not a clean 1..N permutation")
    # The founding failure, asserted directly: a low-sample player must not out-rank a
    # high-sample player who beats him on every underlying rate.
    by_name = {p["name"]: p for p in players}
    a, b = by_name.get("Cam Skattebo"), by_name.get("Jonathan Taylor")
    if a and b and a["evaluation"]["claude_rank"] < b["evaluation"]["claude_rank"]:
        raise GateFailure(
            "Cam Skattebo out-ranks Jonathan Taylor — the exact small-sample failure this "
            "project exists to prevent. Shrinkage is not working."
        )


def repl_report(players):
    return {p["position"]: p["evaluation"]["replacement_pts"] for p in players}


def main():
    doc = json.load(open(CANONICAL))
    players = doc["players"]
    if "derived" not in players[0]:
        print("Run build/derive_metrics.py first.", file=sys.stderr)
        return 1

    evaluate(players)
    try:
        gates(players)
    except GateFailure as e:
        print(f"GATE FAILED — players.json not modified.\n  {e}", file=sys.stderr)
        return 1

    doc["evaluation_notes"] = {
        "what": "Claude Rank — an opinion, not a source. Every input dimension remains "
                "separately visible under `derived`; this only blends them.",
        "pillars": {k: v[0] for k, v in PILLARS.items()},
        "shrinkage": f"Rates are shrunk toward the positional mean with K={SHRINK_K} games "
                     f"of prior weight, so a rate on a small sample cannot outrank a "
                     f"better-evidenced one.",
        "ordering": f"claude_value = vorp + claude_score * {POINTS_PER_Z}, where vorp is "
                    f"projected points over positional replacement "
                    f"({', '.join(f'{k}{v}' for k, v in sorted(REPLACEMENT_SLOT.items()))}) "
                    f"in a 12-team ESPN lineup. rank_delta is the disagreement with the "
                    f"market.",
        "damping": "Score is scaled by data completeness so a thin profile moves less.",
    }
    with open(CANONICAL, "w") as f:
        json.dump(doc, f, indent=2, ensure_ascii=False)

    print(f"Evaluated {len(players)} players -> {os.path.relpath(CANONICAL, BASE)}\n")
    top = sorted(players, key=lambda p: p["evaluation"]["claude_rank"])[:15]
    print("  Claude Rank top 15")
    print(f"  {'#':>3} {'player':<24}{'pos':<4}{'value':>8}{'vorp':>8}{'opin':>7}"
          f"{'mkt':>5}{'delta':>7}")
    for p in top:
        e = p["evaluation"]
        mk = e["market_rank"] if e["market_rank"] is not None else "-"
        dl = f"{e['rank_delta']:+d}" if e["rank_delta"] is not None else "-"
        print(f"  {e['claude_rank']:>3} {p['name']:<24}{p['position']:<4}"
              f"{e['claude_value']:>8.1f}{e['vorp']:>8.1f}{e['opinion_pts']:>7.1f}"
              f"{str(mk):>5}{dl:>7}")
    print("\n  replacement level (proj pts): " +
          ", ".join(f"{k} {v:.1f}" for k, v in sorted(repl_report(players).items())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
