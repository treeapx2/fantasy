"""
UDK expert-list tags and injury report -> data/sources/udk_tags/players_raw.json

    python3 build/extract_udk_tags.py

This closes the Phase 4 gap. BUILD_SPEC anticipated reading tag *glyphs* off the rankings
page, which the PDF text layer drops. That turned out to be unnecessary: UDK publishes each
tag as its own page, in plain HTML, so the tags were read from the list pages in the user's
own logged-in session rather than guessed from images. robots.txt was checked first and
disallows nothing.

The data is transcribed here as literals — versioned and diffable, the same pattern as
build/extract_udk.py — rather than being re-scraped on every build.

## Two things the source itself gets wrong

UDK's "Values" and "My Guys" pages serve the IDENTICAL 13 players. Different titles,
different canonical URLs, same roster, verified by fetching each alone. Both tags are
recorded because the source asserts both, but they are NOT two independent endorsements
and must not be counted as such.

The Value Scout "Markers" column remains ignored per BUILD_SPEC — it is unclicked UI
buttons on a shared account. These tags come from the editorial lists instead, which are
the analysts' actual picks.
"""

import json
import os
import re
import unicodedata

BASE = os.path.join(os.path.dirname(__file__), "..")
OUT = os.path.join(BASE, "data", "sources", "udk_tags")
CANONICAL = os.path.join(BASE, "data", "canonical", "players.json")
SOURCE_DATE = "2026-09-03"

# tag -> [(name, position, team), ...]
LISTS = {
    "sleeper": [
        ("Malik Willis","QB","MIA"),("Tyler Shough","QB","NO"),("Rico Dowdle","RB","PIT"),
        ("Jonathon Brooks","RB","CAR"),("Blake Corum","RB","LAR"),
        ("Jacory Croskey-Merritt","RB","WAS"),("Jordan Mason","RB","MIN"),
        ("Quentin Johnston","WR","LAC"),("Josh Downs","WR","IND"),
        ("De'Zhaun Stribling","WR","SF"),("Isaiah Likely","TE","NYG"),
        ("Chig Okonkwo","TE","WAS"),("Terrance Ferguson","TE","LAR"),
        ("Greg Dulcich","TE","MIA"),
    ],
    "breakout": [
        ("Jaxson Dart","QB","NYG"),("Trevor Lawrence","QB","JAX"),
        ("Kenneth Walker","RB","KC"),("Omarion Hampton","RB","LAC"),
        ("Bhayshul Tuten","RB","JAX"),("Christian Watson","WR","GB"),
        ("Carnell Tate","WR","TEN"),("Tetairoa McMillan","WR","CAR"),
        ("Colston Loveland","TE","CHI"),("Harold Fannin Jr.","TE","CLE"),
    ],
    "bust": [
        ("Matthew Stafford","QB","LAR"),("Patrick Mahomes","QB","KC"),
        ("Chuba Hubbard","RB","CAR"),("RJ Harvey","RB","DEN"),
        ("Malik Nabers","WR","NYG"),("DJ Moore","WR","BUF"),
        ("Courtland Sutton","WR","DEN"),("Oronde Gadsden","TE","LAC"),
        ("Jake Ferguson","TE","DAL"),
    ],
    # Values and My Guys are the same 13 players on the source — see module docstring.
    "value": [
        ("Brock Purdy","QB","SF"),("Dak Prescott","QB","DAL"),("Derrick Henry","RB","BAL"),
        ("Javonte Williams","RB","DAL"),("Cam Skattebo","RB","NYG"),
        ("D'Andre Swift","RB","CHI"),("J.K. Dobbins","RB","DEN"),
        ("Jaylen Waddle","WR","DEN"),("Parker Washington","WR","JAX"),
        ("Terry McLaurin","WR","WAS"),("Chris Godwin Jr.","WR","TB"),
        ("Brenton Strange","TE","JAX"),("Sam LaPorta","TE","DET"),
    ],
}
LISTS["my_guy"] = list(LISTS["value"])

# name -> (injury, return timeline)
INJURIES = [
    ("Patrick Mahomes","ACL + LCL","Limited throughout the offseason, Likely ready for Week 1"),
    ("Bo Nix","Right Ankle Fracture","Cleared for Training Camp, Ready for Week 1"),
    ("Daniel Jones","Achilles","Cleared for Week 1"),
    ("Michael Penix Jr.","ACL","Limited throughout the offseason, Could be ready for Week 1"),
    ("Ashton Jeanty","Right Ankle Sprain","Questionable for Week 1"),
    ("Jeremiyah Love","Left High Ankle Sprain","Questionable for Week 1"),
    ("Breece Hall","Groin Strain","Likely out of practice 1-2 weeks; Probable for Week 1"),
    ("Zach Charbonnet","ACL","Will begin regular season on PUP"),
    ("Cam Skattebo","Ankle Fracture-Dislocation","Limited early in the offseason; Ready for Week 1"),
    ("Quinshon Judkins","Ankle Fracture-Dislocation","Limited throughout the offseason, Likely ready for Week 1"),
    ("Alvin Kamara","MCL Sprain","Doubtful for Week 1"),
    ("Chuba Hubbard","Hamstring Strain","Week-to-week, Likely to play Week 1"),
    ("Kyle Monangai","Hyperextended Right Knee","Questionable for Week 1"),
    ("Isiah Pacheco","MCL Sprain, Back Injury","Beginning Season on IR"),
    ("Josh Jacobs","Groin Strain","Will be healthy for Week 1"),
    ("Bucky Irving","Labrum Repair","Cleared for Training Camp"),
    ("J.K. Dobbins","Lisfranc Surgery","Limited in OTAs and Training Camp"),
    ("RJ Harvey","Shoulder Labrum Repair","Training Camp"),
    ("Chris Rodriguez Jr.","Foot Surgery","Training Camp"),
    ("Joe Mixon","Right Ankle and Foot Injuries","TBD"),
    ("Najee Harris","Achilles","Limited throughout the offseason, Cleared for Week 1"),
    ("Jordyn Tyson","Hamstring Strain","Likely to miss 3+ regular season games; Could begin season on IR"),
    ("Puka Nacua","Hip Flexor Strain","Likely to play Week 1"),
    ("Mike Evans","Groin Strain","Likely to play Week 1"),
    ("Malik Nabers","ACL + Meniscus","Limited in Training Camp, Questionable for Week 1"),
    ("Rashee Rice",'Right Knee "Clean up" Procedure',"Likely limited to begin Training Camp; Cleared for Week 1"),
    ("Alec Pierce","Left Ankle Surgery","Limited to begin the regular season"),
    ("Emeka Egbuka","Turf Toe","Situation to Monitor; Questionable for Week 1"),
    ("Makai Lemon","Hamstring Strain","Limited throughout Training Camp, Ready for Week 1"),
    ("Luther Burden III","Groin Strain","Probable for Week 1"),
    ("Chris Bell","ACL","Limited in Training Camp; Could be cleared for Week 1"),
    ("Ricky Pearsall","PCL Reconstruction","Will miss entire 2026 season"),
    ("Chris Brazzell II","LCL Sprain","Out for the year"),
    ("Tyreek Hill","Partial Knee Dislocation","May not play in 2026"),
    ("Travis Hunter","LCL","Cleared for Training Camp"),
    ("Sam LaPorta","Low Back Surgery / Hip Injury","Likely to play Week 1"),
    ("George Kittle","Achilles","Limited throughout the offseason, Questionable for Week 1"),
    ("Tucker Kraft","ACL","Limited in Training Camp, Likely cleared for Week 1"),
    ("Kenyon Sadiq","Core Muscle Repair","Questionable for Week 1"),
]

# Timelines that mean the player is not a Week 1 asset, in severity order.
OUT_MARKERS = ("miss entire", "out for the year", "may not play", "on IR", "on PUP")


def fold(n):
    n = unicodedata.normalize("NFKD", n)
    n = "".join(c for c in n if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "", n.lower())


def main():
    canon = {(fold(p["name"]), p["position"]): p
             for p in json.load(open(CANONICAL))["players"]}
    by_name = {}
    for p in json.load(open(CANONICAL))["players"]:
        by_name.setdefault(fold(p["name"]), p)

    rec = {}
    unmatched = []
    for tag, rows in LISTS.items():
        for name, pos, team in rows:
            p = canon.get((fold(name), pos))
            if not p:
                unmatched.append((tag, name, pos))
                continue
            r = rec.setdefault(p["player_id"], {"name": p["name"], "team": p["team"],
                                                "position": p["position"], "tags": []})
            if tag not in r["tags"]:
                r["tags"].append(tag)

    inj_unmatched = []
    for name, injury, timeline in INJURIES:
        p = by_name.get(fold(name))
        if not p:
            inj_unmatched.append(name)
            continue
        r = rec.setdefault(p["player_id"], {"name": p["name"], "team": p["team"],
                                            "position": p["position"], "tags": []})
        if "injury_concern" not in r["tags"]:
            r["tags"].append("injury_concern")
        r["injury"] = injury
        r["injury_timeline"] = timeline
        r["injury_out"] = any(m.lower() in timeline.lower() for m in OUT_MARKERS)

    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, "players_raw.json"), "w") as f:
        json.dump({
            "source": "udk_tags", "source_date": SOURCE_DATE, "grain": "player",
            "source_label": "UDK expert lists (My Guys / Values / Sleepers / Breakouts / "
                            "Busts) and the UDK injury report",
            "extracted": "read from the published list pages in the user's logged-in "
                         "session; transcribed here as literals (build/extract_udk_tags.py)",
            "notes": [
                "UDK's Values and My Guys pages serve the identical 13 players — different "
                "titles and canonical URLs, same roster, verified by fetching each alone. "
                "Both tags are recorded because the source asserts both, but they are not "
                "two independent endorsements.",
                "The Value Scout 'Markers' column stays ignored per BUILD_SPEC; these tags "
                "come from the editorial lists, which are the analysts' actual picks.",
                "injury_out is true when the stated return timeline rules the player out of "
                "Week 1 or the season (IR, PUP, 'out for the year', 'may not play').",
            ],
            "players": list(rec.values()),
        }, f, indent=2, ensure_ascii=False)

    with open(os.path.join(OUT, "field_mapping.json"), "w") as f:
        json.dump({"source": "udk_tags",
                   "_comment": "Raw field -> canonical field.",
                   "mapping": {"tags": "tags", "injury": "injury",
                               "injury_timeline": "injury_timeline",
                               "injury_out": "injury_out"}}, f, indent=2)

    from collections import Counter
    c = Counter(t for r in rec.values() for t in r["tags"])
    print(f"Wrote data/sources/udk_tags/ — {len(rec)} tagged players")
    for k, v in c.most_common():
        print(f"   {k:<16}{v:>4}")
    if unmatched:
        print(f"\n  not in the ranked 312 (expected for deep sleepers): "
              f"{[f'{n} ({t})' for t, n, _ in unmatched]}")
    if inj_unmatched:
        print(f"  injured players not in the 312: {inj_unmatched}")


if __name__ == "__main__":
    main()
