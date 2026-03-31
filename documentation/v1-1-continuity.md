# v1.1 Continuity Notes

Target release: `1.1.0-rc1`

## Goal

Make quarter-to-quarter PDF updates safe for existing Google Calendar subscribers:

- keep existing calendar-backed streams alive when the provider only changes raw PDF wording
- let genuinely new villages / streets / house-number buckets create new groups safely
- avoid silently merging two different future schedules back into one old calendar
- show better scope/change context inside calendar and event descriptions

This document captures the implementation and the local Q2 verification for `feat/q2-check`.

## The Underlying Issue

Before this work, PDF continuity was too dependent on the raw provider cell text:

- `schedule_group_id = hash(waste_type + kaimai_hash)`
- `kaimai_hash = hash(raw kaimai_str from PDF)`

That breaks as soon as the provider changes grouping or wording between quarters.

Real Q1 -> Q2 drift from `nemenkom.lt` included:

- `Didžiosios Riešės k.` -> `Didžiosios Riešės mstl.`
- `Blūdikalnio k.` -> `Blūdikalnio vs.`
- `Jonėnų 6 d. k.` -> `Jonėnų k.`
- `2 d. Šiaurinės g.` -> `Šiaurinės g.`

Those are usually the same real places, but they produce different raw hashes.

There was a second issue too: some historical `pdf_parsed_rows` were saved without `seniūnija`,
so exact matching would miss them later even when the provider finally included the admin name.

The third issue was month inference for Q2-style PDFs. Some glass tables arrived as headerless
`location | waste | date` blocks, and the parser could previously drift toward January when the
table context did not carry the visible months strongly enough.

## Implemented Approach

### 1. Continuity is based on canonical parsed selections

We still use AI JSON parsing for the PDF cells. The difference is what happens after parsing.

Each parsed selection is normalized into this canonical key:

- `seniūnija`
- `village`
- `street`
- `house_numbers`

The normalization removes drift that should not matter for continuity:

- village suffix noise like `k.` / `vs.` / `mstl.` / `m.`
- street suffix formatting noise like `g.` / `al.` / `tak.`
- diacritic-only differences
- punctuation / spacing noise
- `all` house-number sentinels

This lets us answer:

- “Is this the same real selection as before?”

instead of only:

- “Is this the same raw provider sentence as before?”

### 2. Exact match first, conservative fallback second

The continuity rule is intentionally conservative:

1. Reuse continuity on exact canonical match.
2. Allow admin-less fallback only when the historical row itself was saved without `seniūnija`.
3. If a whole new provider group clearly maps to one old historical group, let that old group win.
4. If the match is ambiguous, create a new raw group instead of guessing.

That means:

- street-level rows need an exact canonical `seniūnija + village + street (+ house_numbers)` match
- village-wide rows need an exact canonical `seniūnija + village` match
- real new places naturally fall back to new groups

### 3. Group reuse exists for provider regrouping, not fuzzy magic

The “best group winner” logic is there for cases like this:

- old group A = `Akmenų g., Gėlių g.`
- old group B = `Gėlių g.`
- new group = `Akmenų g., Gėlių g., Kaštonų g.`

If we only reused per-row hashes, `Gėlių g.` would look ambiguous and we would often fragment
the existing calendar unnecessarily.

So the code lets one historical group win only when it clearly dominates the new group:

- it matches more selections than the runner-up
- it covers a meaningful share of the new group
- and it gets an extra preference if it already owns a real calendar-backed stream

If there is no clear winner, the code does not force continuity.

### 4. Real future schedule splits degrade safely

This was the last important safety fix.

Problem case:

- old group = `Akmenų g., Gėlių g.` on one schedule
- provider later moves `Gėlių g.` to another schedule

Without a conflict guard, both new rows could reuse the same old hash and collapse back into one
schedule group, which would be wrong.

Now the continuity pass resolves conflicts after matching:

- if one old hash is being reused by multiple new date patterns, we inspect the whole import
- if one successor clearly dominates, only that successor keeps the old hash
- the competing rows fall back to another safe historical hash or their new raw hash

So if the provider truly splits a schedule, we prefer creating a new group over silently merging
two distinct schedules into one old calendar.

### 5. Calendar-bearing streams survive stream splits

Even with correct hash reuse, regrouping can still fan one old stream out into multiple date
patterns.

`reconcile_calendar_streams()` now preserves the existing calendar-bearing stream on the best
successor instead of always abandoning it and moving everything to new streams.

That is what keeps the real Google `calendar_id` attached to the continuing stream.

### 6. Month inference is now driven by visible month context

PDF month assignment is no longer tied to a January-first assumption.

The parser now uses:

- months inferred from the PDF file name
- neighboring table context
- generalized month shifting over the visible month set
- embedded `16 d.` style tokens repeated across visible months when that is clearly the table pattern

This is what made the Q2 glass/plastic imports safe for April-June style PDFs, including the
“1679-1680-1683 should support annual months” concern.

## Why This Works

### Same calendar, new months

If the provider only rolls the quarter forward:

- the parsed selections still canonically match the historical selections
- the old `kaimai_hash` is reused
- the existing `schedule_group` is updated in place
- the linked `calendar_stream_id` survives
- the same `calendar_id` remains attached
- `calendar_synced_at` is cleared so the sync worker refreshes the real calendar

### Empty database

If the DB is empty:

- there are no historical candidates
- every row falls back to a raw new hash
- new `schedule_groups` and `calendar_streams` are created normally

So there is no strange continuity behavior on first import.

### Genuine new areas

If there is really a new village, a new street, or a new bucket:

- there is no exact canonical match
- there is no safe admin-less recovery
- the row keeps its raw new hash

So new data becomes new groups instead of stealing an old calendar.

### Genuine provider regrouping

If the provider changes the structure enough that the old grouping really no longer exists:

- ambiguous rows stay conservative
- conflict resolution prevents different date sets from sharing the same old hash

That means the failure mode is “create a new group” rather than “silently keep the wrong old
calendar”.

## Worked Examples

### Example A: harmless raw rename

Q1:

- `Riešės sen. Didžiosios Riešės k. (Akmenų g.)`

Q2:

- `Riešės sen. Didžiosios Riešės mstl. (Akmenų g.)`

Canonical result:

- same `seniūnija`
- same village after suffix normalization
- same street

Outcome:

- reuse old hash
- update old group
- keep old calendar stream

### Example B: historical row missing `seniūnija`

Historical Q1 saved:

- `Platiniškių k. / Adomo Mickevičiaus g.`
- no stored `seniūnija`

Q2 arrives as:

- `Zujūnų sen. Platiniškių k. tik Adomo Mickevičiaus g.`

Exact canonical match fails because the historical admin is blank, but admin-less fallback is
allowed here because the historical row itself was incomplete.

Outcome:

- reuse the historical hash
- keep stream `cs_3e5c8fbacfa1`
- continue the same glass calendar to `2026-06-26`

### Example C: true future split

Q1:

- `Akmenų g., Gėlių g.` on one schedule

Q2:

- `Akmenų g.` on schedule A
- `Gėlių g.` on schedule B

Outcome:

- the old hash cannot safely own both date sets
- only a dominant successor may keep it
- the other row falls back to a new group

This prevents the “one street moved to another schedule” bug.

## User-Facing Calendar Metadata

The Google calendar/event metadata is now more useful too.

Calendar descriptions now include:

- waste type
- scope summary from `seniūnija`, villages, streets, and specific house-number buckets when present
- current date range
- last update timestamp
- change note (`pradinis publikavimas`, `grafikas nepasikeitė`, or `+N / -N` diff)

Event descriptions now include:

- waste-specific instruction
- short scope summary
- note that the calendar is updated automatically

These descriptions are refreshed for both:

- newly created calendars
- already-existing calendars when they are reused or synced again

This is intentionally scope-aware, so it can describe:

- `seniūnija + village`
- `seniūnija + village + street`
- `seniūnija + village + street + house_numbers`

without dumping raw internal sentinels like `(all)` or `(null)`.

## Local Verification

### Focused regression suite

Ran:

```bash
source venv/bin/activate
pytest -q tests/test_pdf_continuity.py tests/test_calendar_sync.py tests/test_one_calendar_per_group.py
```

Result:

- `28 passed`

Broader regression sweep run earlier on this branch:

- `49 passed`

### Plastics

Re-applied the real parsed plastics rows into the active local DB with the final continuity fix.

Result:

- existing calendar-backed streams preserved: `3 / 3`
- orphaned existing streams: `0`

Active local DB now shows:

- `cs_67abadf5620c` -> `2026-04-01 .. 2026-06-01`
- `cs_cfd369c84e65` -> `2026-04-02 .. 2026-06-02`
- `cs_db08c63912b3` -> `2026-04-01 .. 2026-06-01`

### Glass

Replayed the real parsed Q2 glass rows into a clean pre-Q2 snapshot and then aligned the active
local DB to the fixed result.

Result:

- existing calendar-backed streams preserved: `26 / 26`
- orphaned existing streams: `0`

The previously failing stream now continues correctly:

- `cs_3e5c8fbacfa1` -> `2026-06-26`

## Rollout Guidance

For production `1.1.0-rc1` / Q2 rollover:

1. Update the plastics and glass PDF links.
2. Run the PDF imports.
3. Verify that the existing calendar-backed stream IDs remain attached and now point at Q2 dates.
4. Run the normal calendar sync worker.

Expected result:

- old calendars remain
- new Q2 dates continue on those calendars when the real area is the same
- genuinely new selections create new groups/streams safely
- genuine provider-side schedule splits create new groups instead of silently corrupting old ones

## Tradeoff

This stays conservative on purpose.

Some highly ambiguous regroupings will still create new groups instead of forcing continuity. That
is the right failure mode for this system: correctness is more important than overly aggressive
calendar preservation.
