# Build Spec — Phases 2–6

Read `README.md` first for schema and the source→canonical build pattern. Phase 1
(mechanical UDK rankings extraction, 312 players) is complete and committed.

League context that drives every scoping decision below: **12-team, PPR, 4pt passing TD,
ESPN standard roster, user drafts at pick #5.** Draft is within days. Only ~200 players are
realistically draftable or streamable; the tail exists in the data but is not worth
analysis spend.

> **Corrected 2026-09-01.** This line originally read "10-team". The league is 12-team.
> Consequences: a full round of ADP drift is **12 picks** (Phase 6), and UDK's Value Scout
> ADP board — which is also 12-team — aligns with the league exactly, so `adp_edge` needs
> no conversion. Roughly 192 players go in a 16-round draft.

---

---

## Phase 0 — Repo state reconciliation (DO THIS FIRST)

The working tree may be in a messy state from manual zip-extraction over the repo. Sort
this out before any other phase. Do not skip to Phase 2 assuming the tree is clean.

### Known situation

The user's real repo is at `~/projects/fantasy/football_draft_app` — it has the correct
git remote (`https://github.com/treeapx2/fantasy`), is on branch `main`, and has these
commits already pushed:

```
2e7a7a0  Remove stray empty directory from shell brace-expansion quirk
9fb1bfb  Phase 1: UDK mechanical extraction + canonical build pipeline (312 players)
```

macOS refused to overwrite during extraction and created a **duplicate directory**,
likely `~/projects/fantasy/football_draft_app 2` (note the space — quote it in all shell
commands). That duplicate contains the newer files but carries a throwaway `.git` from a
sandbox with no remote and branch `master`. There may be more than one such duplicate
(`... 3`, etc.).

### What to do

1. **Inventory before changing anything.** List everything under `~/projects/fantasy/`.
   Identify which directory is the real repo (`git remote -v` returns origin) and which
   are duplicates.
2. **Identify the delta.** The files that need to reach the real repo are:
   - `BUILD_SPEC.md` (this file) at repo root
   - `data/sources/_incoming/` — 20 UDK supplemental CSVs
   Everything else should already match; verify rather than assume.
3. **Copy the delta into the real repo.** Do not copy any `.git` directory from a
   duplicate — that would clobber the remote config.
4. **Validate** before committing:
   - `git remote -v` shows the correct origin
   - `git branch --show-current` is `main`
   - `git log --oneline` bottoms out at `9fb1bfb`
   - `data/sources/_incoming/` contains exactly 20 `.csv` files
   - `python3 build/extract_udk.py && python3 build/build_canonical.py` both run clean
     and `data/canonical/players.json` reports 312 players
5. **Commit and push** as one commit:
   `"Add build spec for Phases 2-6 + stage 20 supplemental UDK CSVs"`
6. **Delete the duplicate directories** only after the push succeeds and is verified on
   the remote.

If anything contradicts the above — different hashes, missing remote, more duplicates than
expected, unexpected diffs in files that should match — **stop and report to the user
rather than guessing.** A wrong guess here can lose work or detach the repo from its remote.

### Going forward

Never ask the user to hand-place files again. All file changes happen in-repo via Claude
Code, committed and pushed from here. If the user brings artifacts from a chat session,
treat them as content to be reproduced by a script in-repo, not as files to be shuffled
between directories.

---

## Global rules

These come from a prior project that broke repeatedly. Follow them.

1. **Validation gates before writing any file.** Every script validates before it writes,
   never after. Minimum gates: expected row counts, no unintended key removals, no silent
   null-flooding of a previously-populated field. If a gate fails, abort with a message —
   do not write a partial file.
2. **Exact string replacement over regex sweeps** when editing existing code. Regex
   sweeps clip adjacent code.
3. **Never hand-edit generated files.** `data/canonical/players.json` and
   `data/sources/*/players_raw.json` are build outputs. Fix the script, re-run.
4. **`data/user/*` is sacred.** User rank overrides and notes must survive every rebuild.
   Any script that touches them may only *add* missing keys, never remove or overwrite.
5. **Unmapped fields get reported, not dropped silently.** Existing behavior in
   `build_canonical.py` — preserve it.
6. Prefer rebuilding correctly over iterating fast.

---

## Phase 2 — Supplemental UDK ingest

20 CSVs are staged in `data/sources/_incoming/`. Filenames are ambiguous browser downloads
(`_1_`, `_2_`, `_3_` suffixes). **This mapping is verified — do not re-derive it:**

| File suffix | Consistency Charts | Consistency % | Market Share | Red Zone | SOS |
|---|---|---|---|---|---|
| *(base)* | QB (34) | QB (93) | **RB** (128) | QB/passing (77) | QB (32) |
| `_1_` | RB (82) | RB (196) | **WR** (202) | RB/rushing (184) | RB (32) |
| `_2_` | WR (108) | WR (304) | **TE** (112) | WR+TE/receiving (334) | WR (32) |
| `_3_` | TE (48) | TE (170) | — | — | TE (32) |

Note Market Share has **no QB file** and its base file is RB, unlike the others.
Red Zone `_2_` covers WR **and** TE together (receiving). Row counts above are content
rows excluding header — use them as validation gates.

Two singletons: `Value_Scout` (250 rows, player-grain) and `Target_Share_Breakdown`
(32 rows, **team**-grain).

### Column disambiguation (confirmed by the user — do not guess)

- **Red Zone** files: two identical column blocks = **inside-20 first, inside-10 second**.
  Suffix them `_i20` / `_i10`.
- **Market Share RB**: duplicate `YD%`/`TD%` = **rushing block first, receiving second**.
  Suffix `_rush` / `_rec`.
- **Target Share Breakdown**: three unlabeled `TGT%`/`CMP%` pairs = **WR, RB, TE** in
  that order.
- **Consistency Charts** year columns (2016–2025) = **end-of-season positional finish
  rank** for that year. Blank = did not play / not in league.
- **Consistency Percentages** = **last 3 seasons cumulative** (Josh Allen 51 GP = 17×3).
  `GP` is the sample size and is critical — see Phase 3.

### Deliverable

Rename into stable paths (`data/sources/udk_consistency_charts/`, etc. — one directory per
report type, position as a field on each row, not as separate sources). Each gets
`players_raw.json` + `field_mapping.json` following the existing UDK pattern. Team-grain
files (`Target_Share_Breakdown`, all SOS) go to `data/sources/_team/` — they do not join on
`player_id` and must not be forced into the player canonical.

Delete `data/sources/_incoming/` once ingested; keep the originals in git history.

### Name matching

Verified ~99% exact match against the existing canonical 312. Unmatched rows are genuinely
deeper players not in UDK's top-312 rankings (Tyreek Hill, Amari Cooper, etc.) — **do not
force-match them**; let them fall out, they aren't draftable at this depth.

One known alias needed in `NAME_ALIASES`: `Audric Estimé` → `Audric Estime`.

Report any *new* unmatched name that is inside a source's top-100 — that would indicate a
real normalization bug rather than a depth-chart tail.

---

## Phase 3 — Derived metrics layer

This is the actual product. Raw columns are not comparable across players; these are.

Write `build/derive_metrics.py` → outputs into a `derived` block on each canonical player.

| Metric | Source | Definition |
|---|---|---|
| `floor_rate` | Consistency % | Top-24 (RB/WR) or Top-12 (QB/TE) % |
| `ceiling_rate` | Consistency % | RB1 / WR1 / QB1-6 / TE1-6 % |
| `bust_rate` | Consistency % | RB4+ / WR4+ / QB3+ / TE3+ % |
| `sample_gp` | Consistency % | Raw GP over the 3-year window |
| `sample_confidence` | derived | `high` ≥34 GP, `medium` 17–33, `low` <17 |
| `trajectory_3yr` | Consistency Charts | Linear slope of finish rank across last 3 played seasons. **Negative = improving.** Null if <3 seasons. |
| `peak_finish` | Consistency Charts | Best finish rank in the series |
| `years_since_peak` | Consistency Charts | 2025 minus the year of `peak_finish` |
| `finish_volatility` | Consistency Charts | Stdev of last 5 played finishes |
| `opportunity_share` | Market Share | Position-appropriate composite: RB = `ATT%` + `TGT%`; WR/TE = `TGT%` |
| `td_dependency` | Red Zone + Market Share | `TD%` share minus `YD%` share. Large positive = TD-dependent, regression risk. |
| `rz_volume_i10` | Red Zone | Absolute inside-10 opportunities (the sticky part of TD production) |
| `adp_edge` | Value Scout | TrueValue − Average ADP, in picks. Positive = market discount. Parse `Diff` (`+9Picks`) or compute from the two round.pick strings. |

### Non-negotiable on sample size

`sample_confidence` must be carried everywhere `floor_rate` / `ceiling_rate` /
`bust_rate` appear, and the UI must visually flag `low`. Cam Skattebo posts an 87.5%
Top-24 rate on **8 games**; CMC posts 91.9% on **37**. A naive sort ranks Skattebo above
Jonathan Taylor. This exact failure — treating small samples as equivalent to large ones —
is the mistake being corrected from the prior project. Do not let a sort surface it.

Do not blend these into a single composite score. Keep the dimensions separate and
visible; the user does the weighing.

---

## Phase 4 — Tag icons (browser-assisted)

Current gap: `tags` is empty for all 312 players except `Rookie` (derived from `exp == 0`).
The UDK PDF renders My Guy / Value / Sleeper / Breakout / Bust / Injury Concerns as small
glyphs that don't survive text extraction. These are real risk/upside signal — "Bust" and
"Injury Concerns" are risk flags, "Breakout" and "Sleeper" are upside flags.

Approach: the **user logs into UDK themselves** in their browser; the session is then read
to pull per-player tags from the rankings page. Never handle credentials.

Before doing this, check UDK's terms of service regarding automated access. If the tags
turn out to be image glyphs in the DOM with no accessible text or class hints, stop and
report rather than guessing — an empty tag is better than a wrong one.

Output: `data/sources/udk_tags/players_raw.json` (`player_id` → tag list) merged as its own
source. **Ignore the Value Scout `Markers` column entirely** — it's unclicked UI buttons on
a shared account, not the user's judgment.

---

## Phase 5 — Risk/upside notes synthesis

### Input dependency — read this first

The UDK analyst blurbs are not in the repo and never will be. Phase 1 extracted only the
tabular columns; the prose was deliberately excluded. The blurbs exist only in the source
PDF.

The user places it at `data/sources/_pdf/UDK.pdf`, which is gitignored. It is paid
subscription content from Fantasy Footballers — read it from disk, never commit it, never
copy its text into any tracked file. Only the paraphrased derived notes get committed.

If `data/sources/_pdf/UDK.pdf` is absent, stop and ask the user for it rather than
attempting this phase from the tabular data alone.

Scope: **top 200 players by UDK overall value**, not all 312.

For each, produce two concise bullet lists in
`data/user/risk_upside_notes.json` under the `udk` sub-list:

- `risk[]` — injury history, small sample size, TD-regression exposure, target-competition
  uncertainty, age-curve position, situation volatility, legal/suspension risk
- `upside[]` — target-share ceiling, efficiency trajectory, scheme/coaching change,
  opportunity vacated by departures, positive trajectory

Rules:
- **Paraphrase the UDK blurbs — never quote them.** They're copyrighted analyst prose.
  Compress to the risk/upside implication, drop the voice and jokes.
- Bullets are terse — a clause each, not sentences. Target 2–4 per list.
- **Cite the derived metric where one supports the point** (e.g. "42% bust rate on 37 GP"
  beats "inconsistent"). Phase 3 must be complete first — this is why it's sequenced after.
- The `user` sub-list stays empty here. It is populated only from `notes_staging.json`,
  and stays separately attributed so the user can tell their own read from the source's.

---

## Phase 6 — Refresh workflow

Rankings will move over the next few days (injury news, ADP drift, depth-chart changes).
The refresh path must be fast, must not clobber user edits, and must **report what changed**.

### Two-speed design

| Tier | Fields | Refresh via | Cadence |
|---|---|---|---|
| **Volatile** | ADP, TrueValue, `adp_edge`, injury tags | Re-download **Value Scout CSV** (tabular, cheap) | Daily |
| **Stable** | Tiers, risk/upside scores, projections, blurb-derived notes | Re-extract rankings PDF | Only on a real UDK republish |

This split matters because the volatile tier is a clean CSV re-ingest, while the stable
tier currently lives as hand-transcribed Python tuples in `build/extract_udk.py` and is
expensive to redo. Do not couple them.

### Deliverable: `build/refresh.py`

```
python3 build/refresh.py --source value_scout --file <path-to-new-csv>
```

Behavior:
1. Ingest the new file to a **staging** location — never overwrite the current source
   in place until validation passes.
2. Run validation gates: row count within tolerance of prior, ≥95% of prior `player_id`s
   still present, no field going wholly null.
3. **Emit a change report before committing anything:**
   - Players whose ADP moved ≥ 1 full round
   - Players who changed tier
   - New entrants to the top 200 / players who dropped out
   - Players newly carrying an `Injury Concerns` tag
4. On pass, promote staging → source, re-run `build_canonical.py` and
   `derive_metrics.py`.
5. `data/user/*` untouched throughout. Verify by asserting the file hash of
   `my_ranks.json` is unchanged across the run.

The change report is the point. Days before a draft, "Ashton Jeanty's ADP moved a round
and he picked up an injury flag" is the actionable output — not a silently updated file.

Write each refresh as its own commit (`refresh: value_scout YYYY-MM-DD`) so the pre-draft
drift is reviewable in git history.

---

## Suggested sequencing

Phase **0** → 2 → 3 → 6 → 5 → 4.

Phase 0 is a hard prerequisite — nothing else is safe until the repo state is verified
and pushed.

Rationale: metrics (3) need ingest (2). Notes (5) should cite metrics, so they follow 3.
The refresh harness (6) is worth having **before** the notes pass, so that when rankings
move you re-run rather than redo. Tags (4) is last — it's the only phase with an external
dependency that might not pan out, and nothing else blocks on it.
