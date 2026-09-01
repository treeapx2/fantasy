"""
Merges an authored notes batch into data/user/risk_upside_notes.json (BUILD_SPEC Phase 5).

    python3 build/apply_notes.py build/notes/udk_rankings_top15.json
    python3 build/apply_notes.py build/notes/*.json --dry-run

data/user/ is sacred (Global rule 4): this script may only ADD notes. It never removes or
rewrites an existing note, never touches the `user` sub-list, and never drops a player.
Re-applying the same batch is a no-op — notes are de-duplicated on (src, note), so a batch
can be corrected and re-run without piling up duplicates.

Each note is an object rather than a bare string:

    {"note": "...", "src": "udk_rankings", "src_label": "UDK Rankings 8/30",
     "cites": ["td_dependency"]}

so that a pro/con can be displayed with its source beside it, and so later batches (UDK
sleepers/busts/values, ESPN) drop in as more entries with a different `src` rather than
forcing a schema migration of notes already written.
"""

import argparse
import json
import os
import sys

BASE = os.path.join(os.path.dirname(__file__), "..")
NOTES = os.path.join(BASE, "data", "user", "risk_upside_notes.json")
CANONICAL = os.path.join(BASE, "data", "canonical", "players.json")

SIDES = ("risk", "upside")
REQUIRED = {"note", "src", "src_label"}


class GateFailure(Exception):
    pass


def validate_batch(batch, valid_ids):
    if "notes" not in batch:
        raise GateFailure("batch has no 'notes' key")
    for pid, blocks in batch["notes"].items():
        if pid not in valid_ids:
            raise GateFailure(f"{pid} is not a canonical player_id")
        for side, items in blocks.items():
            if side not in SIDES:
                raise GateFailure(f"{pid}: unexpected side {side!r} (expected risk/upside)")
            if not 1 <= len(items) <= 6:
                raise GateFailure(
                    f"{pid}/{side}: {len(items)} notes — BUILD_SPEC asks for terse lists "
                    f"of about 2-4, and this is outside a sane range."
                )
            for it in items:
                if not REQUIRED <= set(it):
                    raise GateFailure(f"{pid}/{side}: note missing {REQUIRED - set(it)}")
                if not it["note"].strip():
                    raise GateFailure(f"{pid}/{side}: empty note text")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("batches", nargs="+")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    valid_ids = {p["player_id"] for p in json.load(open(CANONICAL))["players"]}
    with open(NOTES) as f:
        notes = json.load(f)
    before_players = set(notes)
    before_user = {pid: json.dumps(v["risk"]["user"]) + json.dumps(v["upside"]["user"])
                   for pid, v in notes.items()}

    added = skipped = 0
    try:
        for path in args.batches:
            batch = json.load(open(path))
            validate_batch(batch, valid_ids)
            for pid, blocks in batch["notes"].items():
                for side, items in blocks.items():
                    bucket = notes[pid][side].setdefault("udk", [])
                    have = {(n.get("src"), n.get("note")) for n in bucket
                            if isinstance(n, dict)}
                    for it in items:
                        if (it["src"], it["note"]) in have:
                            skipped += 1
                            continue
                        bucket.append(it)
                        added += 1
            print(f"  {os.path.relpath(path, BASE)}: {len(batch['notes'])} players")
    except GateFailure as e:
        print(f"GATE FAILED — {NOTES} not modified.\n  {e}", file=sys.stderr)
        return 1

    # Post-merge gates: nothing lost, user sub-lists untouched.
    if set(notes) != before_players:
        print("GATE FAILED — player set changed. Not written.", file=sys.stderr)
        return 1
    for pid, v in notes.items():
        sig = json.dumps(v["risk"]["user"]) + json.dumps(v["upside"]["user"])
        if sig != before_user[pid]:
            print(f"GATE FAILED — {pid}'s 'user' notes were modified. Not written.",
                  file=sys.stderr)
            return 1

    if args.dry_run:
        print(f"\n--dry-run: would add {added} notes, skip {skipped} already present. "
              f"Nothing written.")
        return 0

    with open(NOTES, "w") as f:
        json.dump(notes, f, indent=2, ensure_ascii=False)

    covered = sum(1 for v in notes.values()
                  if v["risk"].get("udk") or v["upside"].get("udk"))
    print(f"\nAdded {added} notes ({skipped} already present) -> "
          f"{os.path.relpath(NOTES, BASE)}")
    print(f"Players with notes: {covered} of {len(notes)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
