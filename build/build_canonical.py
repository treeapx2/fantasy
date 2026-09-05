"""
Builds data/canonical/players.json from all sources under data/sources/*/players_raw.json,
using each source's field_mapping.json to translate raw fields to canonical names.

Safe to re-run any time a source is re-extracted or a new source is added:
- Raw fields with no entry in a source's field_mapping.json are reported (not hidden) and
  excluded from canonical output until someone adds a mapping entry.
- Re-running never touches data/user/* (your rank overrides and notes) — those live outside
  this build entirely and are merged in at read-time by the app, not baked into this file.
- This script DOES touch data/user/notes_staging.json and risk_upside_notes.json only to the
  extent of ensuring every current player_id has an (empty, if new) entry — it never removes
  or overwrites existing note content.

## The spine

SPINE_SOURCE ('udk', the ranked draft board) defines which players exist. Every other
source may only *attach* to a player the spine already knows about. A supplemental source
row that matches nobody falls out and is reported — it is not promoted into the dataset.

This is deliberate. The supplemental UDK reports cover the full statistical population
(304 WRs in the consistency data vs 131 ranked WRs), and even in a 12-team league the
tail is not draftable. Letting any source mint players would quietly inflate the board with
players UDK itself does not rank.

## Matching

player_id is a stable slug: lowercase name (punctuation stripped) + team + position, minted
from the spine.

Supplemental sources are matched on NAME + POSITION, not on player_id, because the slug
embeds team and team is not stable across these sources: the 2026 ranking board lists
players on their 2026 teams while the historical stat reports list the team the player
produced those stats for (A.J. Brown ranks as NE but has his market share under PHI). A
team-bearing key would drop every player who changed teams in the offseason.

Names are matched accent- and punctuation-insensitively, which is what handles the known
'Audric Estimé' -> 'Audric Estime' case. NAME_ALIASES below is for genuine spelling
differences that folding cannot reach (e.g. ESPN's "Kenneth Walker III" vs UDK's
"Kenneth Walker"), and grows as mismatches are found.
"""

import json
import os
import re
import unicodedata

BASE = os.path.join(os.path.dirname(__file__), "..")
SOURCES_DIR = os.path.join(BASE, "data", "sources")
CANONICAL_DIR = os.path.join(BASE, "data", "canonical")
USER_DIR = os.path.join(BASE, "data", "user")

SPINE_SOURCE = "udk"

# Sources whose rows are team-grain and must never be forced into the player canonical.
# They live under data/sources/_team/ and carry team_raw.json, so they are skipped
# structurally too; this list is documentation and a second line of defence.
TEAM_GRAIN_DIRS = {"_team"}

# (source, raw_name) -> the spelling to match against the spine. Accent/punctuation
# folding is automatic and does NOT need an entry here; this is for real differences.
# 'Audric Estimé' is listed because BUILD_SPEC calls for it explicitly, though folding
# already resolves it — an entry here is harmless and self-documenting.
# ESPN spells suffixes differently from UDK. Each pair below was verified to resolve to
# an existing canonical player AT THE SAME POSITION before being added — a loose
# last-name match proposes plenty of false pairs (ESPN's "Brian Robinson Jr." is not
# Bijan Robinson; "Jalon Daniels" is not Jayden Daniels), and a wrong alias silently
# welds two players together.
_ESPN_ALIASES = {
    "Kenneth Walker III": "Kenneth Walker", "Ken Walker III": "Kenneth Walker",
    "James Cook": "James Cook III", "Travis Etienne": "Travis Etienne Jr.",
    "Aaron Jones": "Aaron Jones Sr.", "Kenneth Gainwell": "Kenny Gainwell",
    "Chris Rodriguez": "Chris Rodriguez Jr.", "LeQuint Allen": "LeQuint Allen Jr.",
    "Chris Godwin": "Chris Godwin Jr.", "Deebo Samuel": "Deebo Samuel Sr.",
    "Marvin Mims": "Marvin Mims Jr.", "Ted Hurst": "Ted Hurst III",
    "Kyle Pitts": "Kyle Pitts Sr.", "Chigoziem Okonkwo": "Chig Okonkwo",
    "Oronde Gadsden II": "Oronde Gadsden", "Cameron Ward": "Cam Ward",
}

NAME_ALIASES = {
    **{(src, k): v for src in ("espn_ppr300", "espn_clay", "espn_depth")
       for k, v in _ESPN_ALIASES.items()},
    ("udk_consistency_charts", "Audric Estimé"): "Audric Estime",
    ("udk_consistency_pct", "Audric Estimé"): "Audric Estime",
    ("udk_market_share", "Audric Estimé"): "Audric Estime",
    ("udk_red_zone", "Audric Estimé"): "Audric Estime",
    ("udk_value_scout", "Audric Estimé"): "Audric Estime",
}


def fold(name):
    """Accent- and punctuation-insensitive form used for cross-source name matching."""
    n = unicodedata.normalize("NFKD", name)
    n = "".join(c for c in n if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "", n.lower())


def slugify(name, team, position):
    # A player can reach the board before a team is known for him. Slug him as "fa"
    # rather than crashing the build; report_gaps.py surfaces the missing team.
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return f"{s}-{(team or 'fa').lower()}-{position.lower()}"


def load_source(source_name):
    src_dir = os.path.join(SOURCES_DIR, source_name)
    raw_path = os.path.join(src_dir, "players_raw.json")
    map_path = os.path.join(src_dir, "field_mapping.json")
    if not os.path.exists(raw_path) or not os.path.exists(map_path):
        return None, None
    with open(raw_path) as f:
        raw = json.load(f)
    with open(map_path) as f:
        mapping = json.load(f)["mapping"]
    return raw, mapping


def player_sources():
    """Source directory names that are player-grain, spine first."""
    names = []
    for name in sorted(os.listdir(SOURCES_DIR)):
        if name in TEAM_GRAIN_DIRS or name.startswith("."):
            continue
        if not os.path.exists(os.path.join(SOURCES_DIR, name, "players_raw.json")):
            continue
        names.append(name)
    if SPINE_SOURCE not in names:
        raise SystemExit(
            f"Spine source '{SPINE_SOURCE}' not found under {SOURCES_DIR} — refusing to "
            f"build a canonical dataset with no ranked player universe."
        )
    return [SPINE_SOURCE] + [n for n in names if n != SPINE_SOURCE]


def build():
    if not os.path.isdir(SOURCES_DIR):
        print(f"No sources directory at {SOURCES_DIR}")
        return

    canonical = {}          # player_id -> record
    by_name_pos = {}        # (folded_name, position) -> player_id
    by_name = {}            # folded_name -> [player_id, ...]
    unmapped_report = {}    # source -> sorted unmapped raw fields
    match_report = {}       # source -> {matched, unmatched, unmatched_names, team_diffs}

    for source_name in player_sources():
        raw, mapping = load_source(source_name)
        if raw is None:
            continue
        is_spine = source_name == SPINE_SOURCE

        unmapped_fields = set()
        matched = 0
        unmatched_names = []
        team_diffs = 0

        for idx, p in enumerate(raw["players"]):
            alias = NAME_ALIASES.get((source_name, p["name"]), p["name"])
            folded = fold(alias)

            if is_spine:
                pid = slugify(p["name"], p["team"], p["position"])
                canonical[pid] = {
                    "player_id": pid,
                    "name": p["name"],
                    "team": p["team"],
                    "position": p["position"],
                    "sources": {},
                }
                by_name_pos[(folded, p["position"])] = pid
                by_name.setdefault(folded, []).append(pid)
                matched += 1
            else:
                pid = _resolve(p, folded, by_name_pos, by_name)
                if pid is None:
                    unmatched_names.append((idx, p["name"], p.get("team")))
                    continue
                matched += 1
                if p.get("team") and p["team"] != canonical[pid]["team"]:
                    team_diffs += 1

            mapped = {}
            for raw_field, value in p.items():
                if raw_field in ("name", "team", "position"):
                    continue  # identity fields, already set at top level
                if raw_field not in mapping:
                    unmapped_fields.add(raw_field)
                    continue
                mapped[mapping[raw_field]] = value

            canonical[pid]["sources"][source_name] = mapped

        if unmapped_fields:
            unmapped_report[source_name] = sorted(unmapped_fields)
        match_report[source_name] = {
            "rows": len(raw["players"]),
            "matched": matched,
            "unmatched": len(unmatched_names),
            "unmatched_names": unmatched_names,
            "team_diffs": team_diffs,
        }

    _write_canonical(canonical)
    _report_unmapped(unmapped_report)
    _report_matching(match_report, canonical)
    _scaffold_user_files(canonical.keys())


def _resolve(p, folded, by_name_pos, by_name):
    """Match a supplemental row to a spine player. Name+position when the source knows
    the position; name alone when it doesn't (the Red Zone reports are split by play
    type, so their rushing file contains QBs and their receiving file contains RBs).
    An ambiguous name-only match is refused rather than guessed."""
    pos = p.get("position")
    if pos:
        return by_name_pos.get((folded, pos))
    candidates = by_name.get(folded, [])
    return candidates[0] if len(candidates) == 1 else None


def _write_canonical(canonical):
    os.makedirs(CANONICAL_DIR, exist_ok=True)
    out_path = os.path.join(CANONICAL_DIR, "players.json")
    with open(out_path, "w") as f:
        json.dump(
            {
                "player_count": len(canonical),
                "spine_source": SPINE_SOURCE,
                "sources_included": player_sources(),
                "players": list(canonical.values()),
            },
            f,
            indent=2,
        )
    print(f"Wrote {len(canonical)} players to {out_path}")


def _report_unmapped(unmapped_report):
    if unmapped_report:
        print("\nUNMAPPED FIELDS (present in raw data, not in canonical output yet):")
        for source, fields in unmapped_report.items():
            print(f"  {source}: {fields}")
        print("  -> Add these to the relevant field_mapping.json to promote them, then re-run.")
    else:
        print("No unmapped fields.")


def _report_matching(match_report, canonical):
    """Report how each supplemental source joined to the spine.

    Unmatched rows are expected and healthy — the stat reports cover the whole league
    while the spine is only the ranked, draftable players. What is NOT healthy is a row
    that UDK's own Value Scout considers draftable failing to match, so those are called
    out separately.
    """
    draftable = set()
    for rec in canonical.values():
        if "udk_value_scout" in rec["sources"]:
            draftable.add(fold(rec["name"]))

    print("\nSOURCE JOIN REPORT (spine = %s, %d players):" % (SPINE_SOURCE, len(canonical)))
    print(f"  {'source':<26}{'rows':>6}{'matched':>9}{'fell out':>10}{'team differs':>14}")
    for source, r in match_report.items():
        if source == SPINE_SOURCE:
            print(f"  {source:<26}{r['rows']:>6}{r['matched']:>9}{'-':>10}{'-':>14}")
        else:
            print(f"  {source:<26}{r['rows']:>6}{r['matched']:>9}"
                  f"{r['unmatched']:>10}{r['team_diffs']:>14}")

    vs = match_report.get("udk_value_scout")
    if vs and vs["unmatched_names"]:
        print("\n  !! DRAFTABLE PLAYERS MISSING FROM THE SPINE")
        print("     These are in UDK's own Value Scout top-250 but absent from the ranked")
        print("     board, so nothing can attach to them. Likely a gap in the Phase 1")
        print("     rankings extraction rather than a matching bug:")
        for idx, name, team in vs["unmatched_names"]:
            print(f"       row {idx + 1:>4}  {name} ({team})")

    print("\n  Unmatched rows inside each source's first 100 (BUILD_SPEC Phase 2 asks for")
    print("  these; note these reports are ordered by historical production, not draft")
    print("  value, so a high row number here is ordinary depth, not a normalisation bug):")
    for source, r in match_report.items():
        if source == SPINE_SOURCE:
            continue
        top = [n for i, n, t in r["unmatched_names"] if i < 100]
        if top:
            shown = ", ".join(top[:8])
            more = f" (+{len(top) - 8} more)" if len(top) > 8 else ""
            print(f"    {source}: {len(top)} — {shown}{more}")


def _scaffold_user_files(player_ids):
    """Ensure every current player has an entry in the user-editable files, without
    ever overwriting existing content."""
    os.makedirs(USER_DIR, exist_ok=True)

    my_ranks_path = os.path.join(USER_DIR, "my_ranks.json")
    my_ranks = json.load(open(my_ranks_path)) if os.path.exists(my_ranks_path) else {}
    for pid in player_ids:
        my_ranks.setdefault(pid, {"my_rank": None, "my_tier": None})
    with open(my_ranks_path, "w") as f:
        json.dump(my_ranks, f, indent=2, ensure_ascii=False)

    notes_path = os.path.join(USER_DIR, "risk_upside_notes.json")
    notes = json.load(open(notes_path)) if os.path.exists(notes_path) else {}
    for pid in player_ids:
        notes.setdefault(pid, {
            "risk": {"udk": [], "espn": [], "user": []},
            "upside": {"udk": [], "espn": [], "user": []},
        })
    with open(notes_path, "w") as f:
        # ensure_ascii=False so authored notes round-trip byte-stable. Without it every
        # rebuild re-escapes non-ASCII (em-dashes, accents) and the file churns — which
        # would trip refresh.py's data/user hash assertion on every single run.
        json.dump(notes, f, indent=2, ensure_ascii=False)

    staging_path = os.path.join(USER_DIR, "notes_staging.json")
    if not os.path.exists(staging_path):
        with open(staging_path, "w") as f:
            json.dump([], f, indent=2, ensure_ascii=False)

    print(f"\nScaffolded/updated user files in {USER_DIR} (existing content preserved).")


if __name__ == "__main__":
    build()
