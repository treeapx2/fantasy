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

player_id is a stable slug: lowercase name (punctuation stripped) + team + position. If UDK
and a later source (e.g. ESPN) spell a name differently, that reconciliation happens here,
in one place — see NAME_ALIASES below, which starts empty and grows as mismatches are found.
"""

import json
import os
import re

BASE = os.path.join(os.path.dirname(__file__), "..")
SOURCES_DIR = os.path.join(BASE, "data", "sources")
CANONICAL_DIR = os.path.join(BASE, "data", "canonical")
USER_DIR = os.path.join(BASE, "data", "user")

# Populate as cross-source name mismatches are discovered (e.g. ESPN "Kenneth Walker III"
# vs UDK "Kenneth Walker"). Key = (source, raw_name) -> canonical_name to use for slugging.
NAME_ALIASES = {}


def slugify(name, team, position):
    canonical_name = NAME_ALIASES.get(("udk", name), name)
    s = re.sub(r"[^a-z0-9]+", "-", canonical_name.lower()).strip("-")
    return f"{s}-{team.lower()}-{position.lower()}"


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


def build():
    if not os.path.isdir(SOURCES_DIR):
        print(f"No sources directory at {SOURCES_DIR}")
        return

    canonical = {}  # player_id -> record
    unmapped_report = {}  # source -> set of unmapped raw fields seen

    for source_name in sorted(os.listdir(SOURCES_DIR)):
        raw, mapping = load_source(source_name)
        if raw is None:
            continue

        unmapped_fields = set()
        for p in raw["players"]:
            pid = slugify(p["name"], p["team"], p["position"])
            if pid not in canonical:
                canonical[pid] = {
                    "player_id": pid,
                    "name": p["name"],
                    "team": p["team"],
                    "position": p["position"],
                    "sources": {},
                }

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

    os.makedirs(CANONICAL_DIR, exist_ok=True)
    out_path = os.path.join(CANONICAL_DIR, "players.json")
    with open(out_path, "w") as f:
        json.dump(
            {
                "player_count": len(canonical),
                "sources_included": sorted(
                    s for s in os.listdir(SOURCES_DIR)
                    if os.path.exists(os.path.join(SOURCES_DIR, s, "players_raw.json"))
                ),
                "players": list(canonical.values()),
            },
            f,
            indent=2,
        )
    print(f"Wrote {len(canonical)} players to {out_path}")

    if unmapped_report:
        print("\nUNMAPPED FIELDS (present in raw data, not in canonical output yet):")
        for source, fields in unmapped_report.items():
            print(f"  {source}: {fields}")
        print("  -> Add these to the relevant field_mapping.json to promote them, then re-run.")
    else:
        print("No unmapped fields.")

    _scaffold_user_files(canonical.keys())


def _scaffold_user_files(player_ids):
    """Ensure every current player has an entry in the user-editable files, without
    ever overwriting existing content."""
    os.makedirs(USER_DIR, exist_ok=True)

    my_ranks_path = os.path.join(USER_DIR, "my_ranks.json")
    my_ranks = json.load(open(my_ranks_path)) if os.path.exists(my_ranks_path) else {}
    for pid in player_ids:
        my_ranks.setdefault(pid, {"my_rank": None, "my_tier": None})
    with open(my_ranks_path, "w") as f:
        json.dump(my_ranks, f, indent=2)

    notes_path = os.path.join(USER_DIR, "risk_upside_notes.json")
    notes = json.load(open(notes_path)) if os.path.exists(notes_path) else {}
    for pid in player_ids:
        notes.setdefault(pid, {
            "risk": {"udk": [], "espn": [], "user": []},
            "upside": {"udk": [], "espn": [], "user": []},
        })
    with open(notes_path, "w") as f:
        json.dump(notes, f, indent=2)

    staging_path = os.path.join(USER_DIR, "notes_staging.json")
    if not os.path.exists(staging_path):
        with open(staging_path, "w") as f:
            json.dump([], f, indent=2)

    print(f"Scaffolded/updated user files in {USER_DIR} (existing content preserved).")


if __name__ == "__main__":
    build()
