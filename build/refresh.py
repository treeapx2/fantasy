"""
Refreshes a volatile source from a freshly downloaded file, safely (BUILD_SPEC Phase 6).

    python3 build/refresh.py --source value_scout --file ~/Downloads/UDK_-_Value_Scout...csv
    python3 build/refresh.py --source value_scout --file <path> --dry-run   # report only
    python3 build/refresh.py --source value_scout --file <path> --commit    # + git commit

## Two-speed design

Only the VOLATILE tier refreshes through here: ADP, TrueValue, adp_edge — a clean CSV
re-ingest, cheap enough to run daily in the days before a draft.

The STABLE tier (tiers, risk/upside scores, projections, blurb-derived notes) lives as
hand-transcribed Python tuples in build/extract_udk.py and is expensive to redo. It is
deliberately NOT coupled to this path and only changes on a real UDK republish.

## The change report is the point

A silently updated file is worthless the week of a draft. What matters is "Ashton Jeanty's
ADP moved a round". Nothing is promoted until the report has been printed, and --dry-run
prints it while promoting nothing at all.

Where a dimension the spec asks for cannot be computed from the incoming file, this script
says so explicitly rather than printing an empty section that reads like "no changes".
"""

import argparse
import datetime
import hashlib
import json
import os
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ingest_supplemental import (  # noqa: E402  (reuse the validated ingest path)
    GateFailure, H_VS, build_value_scout, read_csv, write_source, PLAYER_SOURCES,
)

BASE = os.path.join(os.path.dirname(__file__), "..")
SOURCES = os.path.join(BASE, "data", "sources")
STAGING = os.path.join(SOURCES, "_staging")
USER_DIR = os.path.join(BASE, "data", "user")
CANONICAL = os.path.join(BASE, "data", "canonical", "players.json")

# The league and UDK's Value Scout board are both 12-team, so a full round is 12 picks.
LEAGUE_TEAMS = 12
TOP_N = 200

# Gate tolerances.
ROW_COUNT_TOLERANCE = 0.10   # +/- 10% of the prior row count
MIN_KEY_RETENTION = 0.95     # >= 95% of prior players must still be present

REFRESHABLE = {
    "value_scout": {
        "dir": "udk_value_scout",
        "header": H_VS,
        "builder": build_value_scout,
        "spec": PLAYER_SOURCES["udk_value_scout"],
    },
}


def md5(path):
    with open(path, "rb") as f:
        return hashlib.md5(f.read()).hexdigest()


def user_hashes():
    return {f: md5(os.path.join(USER_DIR, f))
            for f in sorted(os.listdir(USER_DIR)) if f.endswith(".json")}


def overall(rp):
    """'3.05' -> overall pick on a LEAGUE_TEAMS-wide board. None for 'Undrafted'."""
    if not rp or "." not in rp:
        return None
    r, k = rp.split(".")
    return (int(r) - 1) * LEAGUE_TEAMS + int(k)


def key(rec):
    return rec["name"]


# ---------------------------------------------------------------------------
# Gates — all run against staging, before anything is promoted.
# ---------------------------------------------------------------------------

def run_gates(prior, new):
    p_rows, n_rows = len(prior), len(new)
    lo = int(p_rows * (1 - ROW_COUNT_TOLERANCE))
    hi = int(p_rows * (1 + ROW_COUNT_TOLERANCE))
    if not lo <= n_rows <= hi:
        raise GateFailure(
            f"row count {n_rows} is outside +/-{int(ROW_COUNT_TOLERANCE * 100)}% of the "
            f"prior {p_rows} (allowed {lo}-{hi}). Refusing to promote."
        )

    p_keys = {key(r) for r in prior}
    n_keys = {key(r) for r in new}
    retained = len(p_keys & n_keys) / len(p_keys) if p_keys else 1.0
    if retained < MIN_KEY_RETENTION:
        missing = sorted(p_keys - n_keys)[:10]
        raise GateFailure(
            f"only {retained:.1%} of prior players are still present (need "
            f">={MIN_KEY_RETENTION:.0%}). Missing e.g. {missing}. Refusing to promote."
        )

    for field in sorted({f for r in prior for f in r}):
        p_vals = [r.get(field) for r in prior if r.get(field) is not None]
        n_vals = [r.get(field) for r in new if r.get(field) is not None]
        if p_vals and not n_vals:
            raise GateFailure(f"field {field!r} went wholly null. Refusing to promote.")
        # A field can lose all its real content without going null: every TrueValue
        # arriving as the literal 'Undrafted' is null-flooding by another name. Catch
        # any field that had real variation and has collapsed to a single constant.
        if len(set(map(str, p_vals))) > 1 and len(set(map(str, n_vals))) <= 1:
            got = next(iter(set(map(str, n_vals))), "nothing")
            raise GateFailure(
                f"field {field!r} collapsed from {len(set(map(str, p_vals)))} distinct "
                f"values to the single constant {got!r}. Refusing to promote."
            )

    return {"rows_prior": p_rows, "rows_new": n_rows, "retention": retained}


# ---------------------------------------------------------------------------
# Change report
# ---------------------------------------------------------------------------

def rank_by_true_value(recs):
    """The source file is ordered by TrueValue; rank on that, ties by file order."""
    ordered = sorted(
        enumerate(recs),
        key=lambda t: (overall(t[1].get("true_value")) or 10 ** 6, t[0]),
    )
    return {key(r): i + 1 for i, (_, r) in enumerate(ordered)}


def change_report(prior, new, source):
    p = {key(r): r for r in prior}
    n = {key(r): r for r in new}
    p_rank, n_rank = rank_by_true_value(prior), rank_by_true_value(new)

    print("\n" + "=" * 72)
    print(f"CHANGE REPORT — {source}   ({len(prior)} -> {len(new)} rows)")
    print("=" * 72)

    # --- ADP movement -----------------------------------------------------
    moves = []
    for k in sorted(p.keys() & n.keys()):
        a, b = overall(p[k].get("avg_adp")), overall(n[k].get("avg_adp"))
        if a is None or b is None:
            continue
        if abs(b - a) >= LEAGUE_TEAMS:
            moves.append((b - a, k, p[k]["avg_adp"], n[k]["avg_adp"], n[k].get("position")))
    print(f"\nADP moved >= 1 full round ({LEAGUE_TEAMS} picks):")
    if moves:
        for delta, k, a, b, pos in sorted(moves, key=lambda m: m[0]):
            arrow = "RISING" if delta < 0 else "falling"
            print(f"  {arrow:>7}  {k:<24}{pos or '':<3} {a} -> {b}  ({delta:+d} picks)")
    else:
        print("  none")

    # --- top 200 churn ----------------------------------------------------
    p_top = {k for k, r in p_rank.items() if r <= TOP_N}
    n_top = {k for k, r in n_rank.items() if r <= TOP_N}
    print(f"\nTop {TOP_N} by TrueValue — entrants:")
    ent = sorted(n_top - p_top, key=lambda k: n_rank[k])
    print("  " + (", ".join(f"{k} (#{n_rank[k]})" for k in ent) if ent else "none"))
    print(f"Top {TOP_N} by TrueValue — dropped out:")
    out = sorted(p_top - n_top, key=lambda k: p_rank[k])
    print("  " + (", ".join(f"{k} (was #{p_rank[k]})" for k in out) if out else "none"))

    # --- brand new / departed rows ---------------------------------------
    added, removed = sorted(n.keys() - p.keys()), sorted(p.keys() - n.keys())
    print(f"\nNew to the file ({len(added)}):")
    print("  " + (", ".join(added) if added else "none"))
    print(f"No longer in the file ({len(removed)}):")
    print("  " + (", ".join(removed) if removed else "none"))

    # --- dimensions the spec asks for that this source cannot supply ------
    print("\nNOT AVAILABLE from this source:")
    print("  Tier changes      — Value Scout has no tier column. Tiers are the STABLE tier,")
    print("                      carried in build/extract_udk.py, and do not move on a")
    print("                      Value Scout refresh by design.")
    print("  Injury Concerns   — tags are empty for all players until Phase 4. The Value")
    print("                      Scout 'Markers' column is deliberately ignored (unclicked")
    print("                      UI buttons on a shared account, not the user's judgement),")
    print("                      so a newly-flagged injury cannot be detected here yet.")
    print("=" * 72)

    return {"adp_moves": len(moves), "entrants": len(ent), "dropped": len(out),
            "added": len(added), "removed": len(removed)}


# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="Refresh a volatile source safely.")
    ap.add_argument("--source", required=True, choices=sorted(REFRESHABLE))
    ap.add_argument("--file", required=True, help="path to the newly downloaded file")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the change report and promote nothing")
    ap.add_argument("--commit", action="store_true",
                    help="git-commit the promoted refresh (off by default)")
    args = ap.parse_args()

    cfg = REFRESHABLE[args.source]
    src_dir = os.path.join(SOURCES, cfg["dir"])
    stage_dir = os.path.join(STAGING, cfg["dir"])

    if not os.path.exists(args.file):
        print(f"No such file: {args.file}", file=sys.stderr)
        return 1

    before = user_hashes()

    # 1. Parse and validate the incoming file INTO STAGING. The live source is not
    #    touched until every gate has passed.
    try:
        hdr, rows = read_csv(args.file)
        if hdr != cfg["header"]:
            raise GateFailure(
                f"header mismatch — this does not look like a {args.source} export.\n"
                f"  expected {cfg['header']}\n  got      {hdr}"
            )
        new = cfg["builder"](rows, None)
    except GateFailure as e:
        print(f"GATE FAILED — nothing staged, nothing promoted.\n  {e}", file=sys.stderr)
        return 1

    with open(os.path.join(src_dir, "players_raw.json")) as f:
        prior_doc = json.load(f)
    prior = prior_doc["players"]

    os.makedirs(STAGING, exist_ok=True)
    write_source(stage_dir, cfg["dir"], cfg["spec"], new, "player")
    print(f"Staged {len(new)} rows -> {os.path.relpath(stage_dir, BASE)}", flush=True)

    # 2. Gates.
    try:
        stats = run_gates(prior, new)
    except GateFailure as e:
        print(f"\nGATE FAILED — staging kept for inspection, source NOT promoted.\n  {e}",
              file=sys.stderr)
        return 1
    print(f"  gates ok: rows {stats['rows_prior']} -> {stats['rows_new']}, "
          f"{stats['retention']:.1%} of prior players retained")

    # 3. Report BEFORE promoting anything.
    summary = change_report(prior, new, args.source)

    if args.dry_run:
        print("\n--dry-run: nothing promoted. Staging left at "
              f"{os.path.relpath(stage_dir, BASE)}")
        return 0

    # 4. Promote, then rebuild.
    shutil.copy(os.path.join(stage_dir, "players_raw.json"),
                os.path.join(src_dir, "players_raw.json"))
    shutil.rmtree(STAGING, ignore_errors=True)
    print(f"\nPromoted staging -> data/sources/{cfg['dir']}/players_raw.json")

    for script in ("build_canonical.py", "derive_metrics.py", "claude_rank.py"):
        r = subprocess.run([sys.executable, os.path.join(BASE, "build", script)],
                           capture_output=True, text=True)
        if r.returncode != 0:
            print(f"\n{script} FAILED after promotion:\n{r.stdout}\n{r.stderr}",
                  file=sys.stderr)
            return 1
        print(f"  re-ran {script}")

    # 5. data/user/* must be untouched throughout (Global rule 4).
    after = user_hashes()
    if before != after:
        changed = [f for f in after if before.get(f) != after[f]]
        print(f"\n!! data/user/ CHANGED during the refresh: {changed}\n"
              f"   This must never happen. Investigate before trusting this run.",
              file=sys.stderr)
        return 1
    print(f"  data/user/* unchanged ({len(after)} files hash-verified)")

    today = datetime.date.today().isoformat()
    msg = f"refresh: {args.source} {today}"
    if args.commit:
        subprocess.run(["git", "-C", os.path.abspath(BASE), "add", "-A"], check=True)
        subprocess.run(["git", "-C", os.path.abspath(BASE), "commit", "-m", msg], check=True)
        print(f"\nCommitted: {msg}")
    else:
        print(f"\nNot committed. To record this refresh as its own reviewable commit:\n"
              f"  git add -A && git commit -m {msg!r}")

    print(f"\nSummary: {summary['adp_moves']} full-round ADP moves, "
          f"{summary['entrants']} entrants / {summary['dropped']} dropped from the top "
          f"{TOP_N}, {summary['added']} new rows / {summary['removed']} gone.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
