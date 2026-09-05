"""
Derives the comparable-across-players metrics layer (BUILD_SPEC Phase 3) and writes it
into a `derived` block on each player in data/canonical/players.json.

Run AFTER build_canonical.py — that script fully regenerates players.json and will drop
the derived block, by design:

    python3 build/build_canonical.py && python3 build/derive_metrics.py

Raw source columns are not comparable across players; these are. Each dimension is kept
separate and visible — there is deliberately no composite score, because the weighing is
the user's job, not this script's.

## The sample-size rule

floor_rate / ceiling_rate / bust_rate are rates over a 3-season window whose length varies
enormously (8 games to 51). A rate on 8 games is not the same kind of number as a rate on
41, and sorting as if it were is the specific failure this project exists to avoid: Cam
Skattebo posts a higher Top-24 rate than Jonathan Taylor on a fifth of the sample.

sample_confidence is therefore emitted alongside those three rates for every player that
has them, and a gate below refuses to write the file if any player carries a rate without
it. Consumers must surface it.
"""

import json
import os
import statistics
import sys

BASE = os.path.join(os.path.dirname(__file__), "..")
CANONICAL = os.path.join(BASE, "data", "canonical", "players.json")

CURRENT_SEASON = 2025
CHART_YEARS = list(range(2016, 2026))

# BUILD_SPEC Phase 3: high >=34 GP, medium 17-33, low <17.
CONF_HIGH, CONF_MED = 34, 17

# Value Scout's board is 12-team — verified at ingest: under 12-team pick math,
# (ADP - TrueValue) reproduces the source's own Diff column for all 246 rows that
# carry both values, and pick numbers in the data run to 12. See adp_edge below.
VALUE_SCOUT_TEAMS = 12


class GateFailure(Exception):
    pass


def _get(p, source, field, default=None):
    return p["sources"].get(source, {}).get(field, default)


# ---------------------------------------------------------------------------
# Consistency Percentages -> floor / ceiling / bust / sample
# ---------------------------------------------------------------------------

def consistency(p):
    s = p["sources"].get("udk_consistency_pct")
    if not s:
        return {"floor_rate": None, "ceiling_rate": None, "bust_rate": None,
                "sample_gp": None, "sample_confidence": None}
    gp = s.get("sample_gp")
    if gp is None:
        conf = None
    elif gp >= CONF_HIGH:
        conf = "high"
    elif gp >= CONF_MED:
        conf = "medium"
    else:
        conf = "low"
    return {
        "floor_rate": s.get("floor_pct"),
        "ceiling_rate": s.get("ceiling_pct"),
        "bust_rate": s.get("bust_pct"),
        "sample_gp": gp,
        "sample_confidence": conf,
    }


# ---------------------------------------------------------------------------
# Consistency Charts -> trajectory / peak / volatility
# ---------------------------------------------------------------------------

def _played(p):
    """[(year, finish), ...] oldest->newest, only seasons actually played."""
    s = p["sources"].get("udk_consistency_charts")
    if not s:
        return []
    out = []
    for y in CHART_YEARS:
        v = s.get(f"finish_{y}")
        if v is not None:
            out.append((y, v))
    return out


def _slope(points):
    """Least-squares slope of finish rank over year. Finish rank is 'lower is better',
    so a NEGATIVE slope means the player is improving."""
    xs = [x for x, _ in points]
    ys = [y for _, y in points]
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    denom = sum((x - mx) ** 2 for x in xs)
    if denom == 0:
        return None
    return sum((x - mx) * (y - my) for x, y in points) / denom


def charts(p):
    pts = _played(p)
    out = {
        "trajectory_3yr": None, "trajectory_seasons": None,
        "peak_finish": None, "peak_finish_year": None, "years_since_peak": None,
        "finish_volatility": None, "finish_volatility_n": 0,
        "seasons_played": len(pts),
    }
    if not pts:
        return out

    # Trajectory over the last 3 PLAYED seasons. The x axis is the real year, so a
    # missed season widens the gap rather than being silently collapsed.
    if len(pts) >= 3:
        last3 = pts[-3:]
        sl = _slope(last3)
        if sl is not None:
            out["trajectory_3yr"] = round(sl, 3)
            out["trajectory_seasons"] = [y for y, _ in last3]

    best = min(v for _, v in pts)
    # On a tie, credit the most recent year — the kinder reading of "years since peak".
    best_year = max(y for y, v in pts if v == best)
    out["peak_finish"] = best
    out["peak_finish_year"] = best_year
    out["years_since_peak"] = CURRENT_SEASON - best_year

    last5 = [v for _, v in pts[-5:]]
    out["finish_volatility_n"] = len(last5)
    if len(last5) >= 2:
        out["finish_volatility"] = round(statistics.stdev(last5), 2)
    return out


# ---------------------------------------------------------------------------
# Market Share -> opportunity_share / td_dependency
# ---------------------------------------------------------------------------

def market(p):
    pos = p["position"]
    s = p["sources"].get("udk_market_share")
    out = {"opportunity_share": None, "opportunity_share_parts": None,
           "td_dependency": None, "td_dependency_basis": None,
           "td_dependency_rush": None, "td_dependency_rec": None}
    if not s:
        return out

    att, tgt = s.get("att_share_rush"), s.get("tgt_share")
    if pos == "RB":
        parts = {"att_share_rush": att, "tgt_share": tgt}
        if att is not None or tgt is not None:
            out["opportunity_share"] = round((att or 0) + (tgt or 0), 1)
            out["opportunity_share_parts"] = parts
    else:
        if tgt is not None:
            out["opportunity_share"] = tgt
            out["opportunity_share_parts"] = {"tgt_share": tgt}

    def dep(td, yd):
        return None if (td is None or yd is None) else round(td - yd, 1)

    out["td_dependency_rush"] = dep(s.get("td_share_rush"), s.get("yd_share_rush"))
    out["td_dependency_rec"] = dep(s.get("td_share_rec"), s.get("yd_share_rec"))

    # Position-appropriate primary: RBs score on the ground, receivers through the air.
    # Both blocks stay exposed above so a receiving back is not misread.
    if pos == "RB" and out["td_dependency_rush"] is not None:
        out["td_dependency"], out["td_dependency_basis"] = out["td_dependency_rush"], "rushing"
    elif pos in ("WR", "TE") and out["td_dependency_rec"] is not None:
        out["td_dependency"], out["td_dependency_basis"] = out["td_dependency_rec"], "receiving"
    return out


# ---------------------------------------------------------------------------
# Red Zone -> rz_volume
# ---------------------------------------------------------------------------

def red_zone(p):
    s = p["sources"].get("udk_red_zone")
    out = {"rz_volume_i10": None, "rz_volume_i20": None, "rz_pass_att_i10": None}
    if not s:
        return out
    for depth in ("i10", "i20"):
        rush, rec = s.get(f"rush_att_{depth}"), s.get(f"rec_tgt_{depth}")
        if rush is not None or rec is not None:
            # A player's own scoring touches inside the marker: carries + targets.
            out[f"rz_volume_{depth}"] = (rush or 0) + (rec or 0)
    out["rz_pass_att_i10"] = s.get("pass_att_i10")
    return out


# ---------------------------------------------------------------------------
# Value Scout -> adp_edge
# ---------------------------------------------------------------------------

def _overall(rp):
    """'3.05' -> overall pick number on a VALUE_SCOUT_TEAMS-wide board."""
    if not rp or "." not in rp:
        return None          # 'Undrafted'
    r, k = rp.split(".")
    return (int(r) - 1) * VALUE_SCOUT_TEAMS + int(k)


def value_scout(p):
    s = p["sources"].get("udk_value_scout")
    out = {"adp_edge": None, "adp_edge_teams": None,
           "true_value_pick": None, "avg_adp_pick": None, "adp_edge_status": None}
    if not s:
        return out
    tv, adp = _overall(s.get("true_value")), _overall(s.get("avg_adp"))
    out["true_value_pick"], out["avg_adp_pick"] = tv, adp
    if tv is None or adp is None:
        out["adp_edge_status"] = "undrafted_in_source"
        return out
    # Sign follows the source's own Diff column: POSITIVE = TrueValue is earlier than
    # the market's ADP = the market is discounting this player.
    out["adp_edge"] = adp - tv
    out["adp_edge_teams"] = VALUE_SCOUT_TEAMS
    out["adp_edge_status"] = "ok"
    return out


# ---------------------------------------------------------------------------

def derive(p):
    d = {}
    d.update(consistency(p))
    d.update(charts(p))
    d.update(market(p))
    d.update(red_zone(p))
    d.update(value_scout(p))
    return d


SPINE_RAW = os.path.join(BASE, "data", "sources", "udk", "players_raw.json")


def spine_count():
    """The expected player count is whatever the spine source currently holds — not a
    number frozen in the code. The board grew from 312 to 316 when UDK added players,
    and a hardcoded gate turns that into a false failure."""
    with open(SPINE_RAW) as f:
        return len(json.load(f)["players"])


def gates(players):
    """Validate before writing (Global rule 1)."""
    expected = spine_count()
    if len(players) != expected:
        raise GateFailure(f"expected {expected} canonical players (the spine's count), "
                          f"got {len(players)}")

    for p in players:
        d = p["derived"]
        rates = [d["floor_rate"], d["ceiling_rate"], d["bust_rate"]]
        if any(r is not None for r in rates) and d["sample_confidence"] is None:
            raise GateFailure(
                f"{p['name']}: carries a consistency rate with no sample_confidence — "
                f"this is the non-negotiable in BUILD_SPEC Phase 3."
            )
        if d["sample_gp"] is not None and d["sample_confidence"] is None:
            raise GateFailure(f"{p['name']}: sample_gp present but no sample_confidence")
        if d["trajectory_3yr"] is not None and len(d["trajectory_seasons"] or []) != 3:
            raise GateFailure(f"{p['name']}: trajectory_3yr without exactly 3 seasons")

    # No silent null-flooding: each metric must be populated wherever its source is.
    for metric, source in [("floor_rate", "udk_consistency_pct"),
                           ("peak_finish", "udk_consistency_charts"),
                           ("adp_edge", "udk_value_scout")]:
        have_src = [p for p in players if source in p["sources"]]
        got = [p for p in have_src if p["derived"][metric] is not None]
        if source == "udk_value_scout":
            have_src = [p for p in have_src
                        if p["derived"]["adp_edge_status"] == "ok"]
            got = [p for p in have_src if p["derived"][metric] is not None]
        if have_src and len(got) != len(have_src):
            missing = [p["name"] for p in have_src if p["derived"][metric] is None][:5]
            raise GateFailure(
                f"{metric}: {len(have_src) - len(got)} players have {source} but no value "
                f"(e.g. {missing})"
            )


def coverage(players):
    keys = ["adj_risk", "adj_upside", "games_available_pct", "weekly_start_pct", "floor_rate", "trajectory_3yr", "peak_finish", "finish_volatility",
            "opportunity_share", "td_dependency", "rz_volume_i10", "adp_edge"]
    return {k: sum(1 for p in players if p["derived"][k] is not None) for k in keys}


def adjust_rates(players):
    """Sample-weight every consistency rate toward its positional mean, and expose the
    result as a first-class field rather than leaving it implicit inside the ranking.

    weekly_start_pct is the one a manager actually asks for: how often does this player
    finish a week as someone you would have started. UDK's floor bucket already IS that
    question — Top-12 for QB/TE (one starter each) and Top-24 for RB/WR (two each) — so
    the adjusted floor rate is the answer, with one caveat recorded in the output: a
    12-team lineup also has a flex, so roughly 30 RB/WR are startable in a given week and
    Top-24 therefore understates RB and WR slightly.
    """
    for pos in sorted({p["position"] for p in players}):
        grp = [p for p in players if p["position"] == pos]
        for key in ("floor_rate", "ceiling_rate", "bust_rate"):
            vals = [p["derived"][key] for p in grp if p["derived"][key] is not None]
            prior = statistics.mean(vals) if vals else 0.0
            for p in grp:
                gp, r = p["derived"]["sample_gp"], p["derived"][key]
                p["derived"][key + "_adj"] = (
                    None if (r is None or gp is None)
                    else round((r * gp + prior * CONF_MED) / (gp + CONF_MED), 1))
                p["derived"][key + "_prior"] = round(prior, 1)
    for p in players:
        d = p["derived"]
        # Trajectory as a word, because a slope of -3.0 means nothing at a glance and
        # "Rising" does. Thresholds are in finish-places per year.
        tj = d.get("trajectory_3yr")
        if tj is None:
            d["trend_label"], d["trend_dir"] = ("No history", "flat")
        elif tj <= -2:
            d["trend_label"], d["trend_dir"] = ("Rising", "good")
        elif tj >= 2:
            d["trend_label"], d["trend_dir"] = ("Falling", "bad")
        else:
            d["trend_label"], d["trend_dir"] = ("Steady", "flat")
        # Share of the games he was eligible for that he actually played. Expected games
        # are capped at the 3-season window and floored at one season, so a rookie is not
        # punished for not yet having a history — only for missing what he could have played.
        gp, exp = d["sample_gp"], p["sources"]["udk"].get("exp")
        seasons = min(max(exp if exp else 1, 1), 3)
        d["games_expected"] = 17 * seasons
        d["games_available_pct"] = (None if gp is None
                                    else round(min(100 * gp / (17 * seasons), 100), 1))
        d["weekly_start_pct"] = d["floor_rate_adj"]
        d["weekly_start_pct_raw"] = d["floor_rate"]
        d["sample_weight_own"] = (None if d["sample_gp"] is None
                                  else round(100 * d["sample_gp"] / (d["sample_gp"] + CONF_MED)))


# Adjusted risk / upside. UDK publishes its own 0-10 risk and upside scores, but they
# predate the consistency data, the injury report and the second source — so these blend
# UDK's read with everything the project has since gathered, and are scored as a
# percentile WITHIN POSITION so a 7.5 means the same thing for a TE as for a WR.
# 'sample' is statistical confidence — how much evidence there is. 'availability' is
# durability — what share of the games he was eligible for he actually played. They are
# different questions and were previously conflated: a player clearing the 34-game
# confidence bar scored zero risk even if he had missed a quarter of the window.
RISK_W = {"bust": .24, "injury": .21, "availability": .20,
          "volatility": .13, "sample": .12, "udk": .10}
UPSIDE_W = {"ceiling": .35, "udk": .25, "trajectory": .20, "opportunity": .20}


def _z(vals):
    good = [v for v in vals.values() if v is not None]
    if len(good) < 2:
        return {k: 0.0 for k in vals}
    mu = statistics.mean(good)
    sd = statistics.pstdev(good)
    if sd == 0:
        return {k: 0.0 for k in vals}
    return {k: (None if v is None else (v - mu) / sd) for k, v in vals.items()}


def _blend(feats, weights):
    num = den = 0.0
    parts = {}
    for name, w in weights.items():
        z = feats.get(name)
        if z is None:
            continue
        num += z * w
        den += w
        parts[name] = round(z, 2)
    return (num / den if den else None), parts, den


def score_risk_upside(players):
    for pos in sorted({p["position"] for p in players}):
        grp = [p for p in players if p["position"] == pos]
        ids = [p["player_id"] for p in grp]
        d = {p["player_id"]: p["derived"] for p in grp}
        u = {p["player_id"]: p["sources"]["udk"] for p in grp}
        tags = {p["player_id"]: p["sources"].get("udk_tags", {}) for p in grp}

        def injury_load(pid):
            t = tags[pid]
            if t.get("injury_out"):
                return 1.0
            if "injury_concern" in (t.get("tags") or []):
                return 0.55
            return 0.0

        def sample_load(pid):
            c = d[pid]["sample_confidence"]
            return {"low": 1.0, "medium": 0.45, "high": 0.0}.get(c, 0.8)

        zr = {
            "bust": _z({i: d[i].get("bust_rate_adj") for i in ids}),
            # more missed games = more risk, so flip it
            "availability": _z({i: (None if d[i].get("games_available_pct") is None
                                    else -d[i]["games_available_pct"]) for i in ids}),
            "volatility": _z({i: d[i].get("finish_volatility") for i in ids}),
            "injury": _z({i: injury_load(i) for i in ids}),
            "sample": _z({i: sample_load(i) for i in ids}),
            "udk": _z({i: u[i].get("risk") for i in ids}),
        }
        zu = {
            "ceiling": _z({i: d[i].get("ceiling_rate_adj") for i in ids}),
            # negative slope = improving, so flip it to make "more is better"
            "trajectory": _z({i: (None if d[i].get("trajectory_3yr") is None
                                  else -d[i]["trajectory_3yr"]) for i in ids}),
            "opportunity": _z({i: d[i].get("opportunity_share") for i in ids}),
            "udk": _z({i: u[i].get("upside") for i in ids}),
        }

        raw = {}
        for i in ids:
            r, rp, rden = _blend({k: zr[k][i] for k in zr}, RISK_W)
            up, upp, uden = _blend({k: zu[k][i] for k in zu}, UPSIDE_W)
            raw[i] = (r, rp, rden, up, upp, uden)

        # Percentile within position -> 0-10, so the number is readable without a scale.
        def pct(vals):
            have = sorted([(v, i) for i, v in vals.items() if v is not None])
            out = {}
            for rank, (_, i) in enumerate(have):
                out[i] = round(10 * rank / max(len(have) - 1, 1), 1)
            return out

        pr = pct({i: raw[i][0] for i in ids})
        pu = pct({i: raw[i][3] for i in ids})
        for i in ids:
            r, rp, rden, up, upp, uden = raw[i]
            d[i]["adj_risk"] = pr.get(i)
            d[i]["adj_risk_parts"] = rp
            d[i]["adj_risk_coverage"] = round(rden, 2)
            d[i]["adj_upside"] = pu.get(i)
            d[i]["adj_upside_parts"] = upp
            d[i]["adj_upside_coverage"] = round(uden, 2)


def main():
    with open(CANONICAL) as f:
        doc = json.load(f)
    players = doc["players"]

    for p in players:
        p["derived"] = derive(p)
    adjust_rates(players)
    score_risk_upside(players)

    try:
        gates(players)
    except GateFailure as e:
        print(f"GATE FAILED — data/canonical/players.json not modified.\n  {e}",
              file=sys.stderr)
        return 1

    cov = coverage(players)
    doc["derived_coverage"] = cov
    doc["derived_notes"] = {
        "sample_confidence": f"high >= {CONF_HIGH} GP, medium {CONF_MED}-{CONF_HIGH - 1}, "
                             f"low < {CONF_MED}. Always present when a consistency rate is.",
        "trajectory_3yr": "Least-squares slope of positional finish rank over the last 3 "
                          "PLAYED seasons, x = real year. NEGATIVE = improving.",
        "adp_edge": f"(Average ADP - TrueValue) in picks on the source's "
                    f"{VALUE_SCOUT_TEAMS}-team board. POSITIVE = market discount. The board "
                    f"and the league are both {VALUE_SCOUT_TEAMS}-team, so this is directly "
                    f"actionable and a 'full round' of drift is {VALUE_SCOUT_TEAMS} picks.",
        "td_dependency": "TD share minus yardage share, position-appropriate block. Large "
                         "positive = TD-dependent, i.e. regression exposure.",
        "weekly_start_pct": "How often he finishes a week as a startable player at his "
                            "position, sample-adjusted. Derived from UDK's floor bucket "
                            "(Top-12 QB/TE, Top-24 RB/WR). The Top-24 buckets slightly "
                            "understate RB/WR because a 12-team lineup also starts a flex.",
        "composite": "Deliberately absent. The dimensions stay separate and visible.",
    }

    with open(CANONICAL, "w") as f:
        json.dump(doc, f, indent=2)

    print(f"Derived metrics for {len(players)} players -> {CANONICAL}\n")
    print("  coverage of the 312:")
    for k, v in cov.items():
        print(f"    {k:<22}{v:>4}")

    conf = {}
    for p in players:
        c = p["derived"]["sample_confidence"]
        conf[c] = conf.get(c, 0) + 1
    print("\n  sample_confidence distribution:")
    for c in ("high", "medium", "low", None):
        if c in conf:
            print(f"    {str(c):<22}{conf[c]:>4}")
    low = [p for p in players if p["derived"]["sample_confidence"] == "low"
           and (p["derived"]["floor_rate"] or 0) >= 70]
    if low:
        print(f"\n  {len(low)} players post a >=70% floor rate on a LOW sample — these are")
        print("  the ones a naive sort would surface wrongly. UI must flag them:")
        for p in sorted(low, key=lambda x: -x["derived"]["floor_rate"])[:8]:
            d = p["derived"]
            print(f"    {p['name']:<24}{p['position']}  floor {d['floor_rate']}%  "
                  f"on {d['sample_gp']} GP")
    return 0


if __name__ == "__main__":
    sys.exit(main())
