# v1.1 Continuity Notes

Target release: `1.1.0-rc1`

This is the canonical document for the Q2 PDF continuity rollout.

## Goal

Make quarterly plastic/glass updates safe for existing subscribers:

- existing Google calendars must stay attached to the same stream
- new quarter dates must replace the stream data in place
- harmless PDF wording drift must not create duplicate calendars
- genuinely new data must still be allowed to create new groups

## Root Cause

The original PDF continuity key was too raw:

```text
schedule_group_id = hash(waste_type + kaimai_hash)
kaimai_hash       = hash(raw PDF kaimai_str)
```

That means the provider could keep the same real-world area but change the wording and still
accidentally force a new `kaimai_hash`.

Real Q1 -> Q2 drift from `nemenkom.lt` included:

- `Didžiosios Riešės k.` -> `Didžiosios Riešės mstl.`
- `Blūdikalnio k.` -> `Blūdikalnio vs.`
- `Jonėnų 6 d. k.` -> `Jonėnų k.`
- `2 d. Šiaurinės g.` -> `Šiaurinės g.`

There were two related issues too:

- some historical PDF rows were saved without `seniūnija`
- some Q2-style PDFs needed month inference from visible month context and filename, not a fixed January-first assumption

## Final Implementation

### 1. Keep using AI JSON, but stop trusting raw text for continuity

The PDF pipeline still uses AI to turn complex provider cells into structured JSON.

What changed is the key used after parsing.

Each parsed selection is normalized into a canonical key:

- `seniūnija`
- `village`
- `street`
- `house_numbers`

Normalization removes harmless drift:

- village suffix noise like `k.` / `vs.` / `mstl.` / `m.`
- street suffix formatting noise like `g.` / `al.` / `tak.`
- punctuation / spacing / diacritic noise
- `house_numbers = all`

Implementation: `services/scraper_pdf/continuity.py`

### 2. Match conservatively

The matching order is:

1. exact canonical match
2. admin-less fallback only when the historical row itself was saved without `seniūnija`
3. historical-group reuse only when one old group clearly dominates the new parsed group
4. otherwise keep the new raw hash

This is intentionally conservative. We prefer a new group over a wrong reuse.

### 3. Protect against future provider splits

The dangerous case is:

- old group: `Akmenų g. + Gėlių g.` on one schedule
- new provider data moves `Gėlių g.` to another schedule

Without a conflict guard, both new rows could reuse one old hash and collapse back into one
group. The continuity pass now prevents that:

- if one old hash is claimed by multiple incompatible new date sets
- only the safest dominant successor keeps it
- the rest fall back to another safe candidate or a new raw hash

So the failure mode becomes `new group` instead of `wrong old calendar`.

### 4. Preserve the actual calendar-bearing stream

`services/scraper/core/db_writer.py` now preserves an existing calendar-bearing stream on the best
successor during stream splits.

That is what keeps the real Google `calendar_id` stable even when grouping changes around it.

### 5. Refresh calendar descriptions for reused calendars too

`services/calendar/__init__.py` now rebuilds descriptions from stream scope and change metadata:

- waste type
- seniūnija / village / street context
- current date range
- change note

This happens both:

- when a brand-new calendar is created
- when an old existing calendar is reused and resynced

## Why It Works

### Same area, new quarter

If the provider only moves Jan-Mar to Apr-Jun:

- canonical selections match historical selections
- historical `kaimai_hash` is reused
- same `schedule_group` survives
- same `calendar_stream_id` survives
- same `calendar_id` survives
- `calendar_synced_at` is cleared so the worker updates the existing Google calendar

### Empty database

If the DB is empty:

- no historical candidates exist
- every row keeps its raw new hash
- groups and streams are created normally

So there is no weird continuity behavior on first import.

### Genuine new places

If there is a truly new village, street, or bucket:

- there is no exact canonical match
- no safe fallback applies
- a new group is created

### Genuine provider regrouping

If the provider really moves one street into a different schedule:

- ambiguity stays conservative
- conflict resolution stops incompatible rows from sharing one old hash

That preserves correctness better than forcing continuity.

## Worked Examples

### Example A: harmless rename

Q1:

- `Riešės sen. Didžiosios Riešės k. (Akmenų g.)`

Q2:

- `Riešės sen. Didžiosios Riešės mstl. (Akmenų g.)`

Outcome:

- village suffix normalizes away
- old hash is reused
- old calendar stream continues

### Example B: missing historical `seniūnija`

Historical row was stored as:

- `Platiniškių k. / Adomo Mickevičiaus g.`

New row becomes:

- `Zujūnų sen. / Platiniškių k. / Adomo Mickevičiaus g.`

Outcome:

- exact match would fail
- admin-less fallback is allowed because the historical row lacked `seniūnija`
- continuity is recovered safely

### Example C: real split

Old group:

- `Akmenų g. + Gėlių g.` with one date pattern

New provider data:

- `Akmenų g.` keeps old pattern
- `Gėlių g.` moves to a different pattern

Outcome:

- one successor may keep the old hash
- the conflicting row gets a new safe group
- we do not silently merge the two schedules back together

## Local Q2 Verification

Starting from the original `1.0` DB snapshot and replaying current code against live Q2 sources:

- `bendros`: `10 -> 10` existing calendar-backed streams preserved
- `plastikas`: `3 -> 3` preserved
- `stiklas`: `26 -> 26` preserved
- no existing `calendar_id` was orphaned

Observed in-place updates:

- plastics moved from Q1 ranges onto Apr-Jun Q2 ranges while keeping the same streams
- all `26` glass calendar-backed streams also moved to Q2 dates in place

## Operational Consequence

For the `1.1 RC` rollout, production should receive:

- the updated code
- the prepared `services/database/waste_schedule.db`

After restart, the calendar worker should update those same existing calendars without requiring
manual calendar recreation.

## Related Files

- `services/scraper_pdf/continuity.py`
- `services/scraper/core/db_writer.py`
- `services/calendar/__init__.py`
- `tests/test_pdf_continuity.py`
- `tests/test_calendar_ux_flow.py`
