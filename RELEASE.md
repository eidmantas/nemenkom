# Release Runbook

Current target: `1.1.0-rc1`

This runbook is for the Q2 continuity rollout where existing plastic/glass calendars must keep
their current Google `calendar_id` and only receive updated dates.

## Goal

Deploy:

- the current application code
- the prepared `services/database/waste_schedule.db`

So that after restart the calendar worker updates existing calendars in place.

## Preconditions

- production `config.py` points at the current Q2 source URLs
- production `secrets/credentials.json` is a valid Google service account JSON
- production has at least one live AI provider key in `secrets/`
- the DB being copied is the prepared app DB, not the old root snapshot

Correct DB file:

- `services/database/waste_schedule.db`

Do not deploy the old rehearsal snapshot unless you intentionally want to rerun the import:

- `waste_schedule.db`

## Recommended Deployment Flow

1. Stop the running services.
2. Back up the current production DB.
3. Copy the prepared `services/database/waste_schedule.db` into the production app DB location.
4. Deploy the current `feat/q2-check` code as the release candidate build.
5. Restart API/web, scraper services, and calendar worker.
6. Watch calendar worker logs until the unsynced Q2 streams are processed.

## Expected Calendar Behavior

After restart:

- `bendros` should remain unchanged if already synced
- `plastikas` existing calendars should keep the same `calendar_id` and update to Q2 dates
- `stiklas` existing calendars should keep the same `calendar_id` and update to Q2 dates

The worker picks this up because the refreshed streams have `calendar_synced_at IS NULL`.

## Local Rehearsal Result

Starting from the original `1.0` DB snapshot and running the current code against live sources:

- `bendros`: `10 -> 10` calendar-backed streams preserved
- `plastikas`: `3 -> 3` preserved, same stream IDs, same `calendar_id`s
- `stiklas`: `26 -> 26` preserved, same stream IDs, same `calendar_id`s

Key Q2 in-place updates seen locally:

- plastics:
  - `2026-01-02..2026-03-02` -> `2026-04-01..2026-06-01`
  - `2026-01-05..2026-03-03` -> `2026-04-02..2026-06-02`
- glass:
  - `26/26` existing calendar-backed streams moved to Q2 dates

## Post-Deploy Checks

Verify in logs / DB that:

- the calendar worker does not create replacement calendars for the old Q1 streams
- updated streams receive fresh `calendar_synced_at`
- existing `calendar_id`s stay attached

Useful checks:

```sql
SELECT waste_type, COUNT(*)
FROM calendar_streams
WHERE calendar_id IS NOT NULL
GROUP BY waste_type;
```

```sql
SELECT waste_type, COUNT(*)
FROM calendar_streams
WHERE calendar_id IS NOT NULL
  AND calendar_synced_at IS NULL
GROUP BY waste_type;
```

## Rollback

If something goes wrong:

1. stop services
2. restore the DB backup
3. redeploy the previous code version
4. restart services

## Related Docs

- [README.md](README.md)
- [INSTALL.md](INSTALL.md)
- [documentation/v1-1-continuity.md](documentation/v1-1-continuity.md)
