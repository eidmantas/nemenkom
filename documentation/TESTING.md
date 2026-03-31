# Testing Guide

This project has three risk areas and the tests reflect that:

1. parsing source data correctly
2. preserving DB/calendar continuity correctly
3. keeping API/UI behavior stable for real address selections

## Recommended Test Layers

### Fast local confidence

```bash
make test
```

This is the default day-to-day suite.

### Focused `1.1 RC` continuity suite

Run this whenever touching PDF rollover, stream reconciliation, or calendar descriptions:

```bash
source venv/bin/activate
pytest -q \
  tests/test_pdf_continuity.py \
  tests/test_calendar_sync.py \
  tests/test_one_calendar_per_group.py \
  tests/test_calendar_ux_flow.py
```

This suite protects:

- raw-text rename continuity
- missing historical `seniūnija` recovery
- conservative fallback on ambiguous overlap
- future schedule split safety
- in-place stream preservation on new date windows
- description refresh for reused calendars

### Full local sweep

```bash
source venv/bin/activate
pytest tests/ -v
```

## Important Test Files

- `tests/test_e2e_xlsx_to_api.py`: XLSX -> DB -> API flow
- `tests/test_pdf_continuity.py`: canonical PDF continuity rules
- `tests/test_calendar_sync.py`: calendar worker sync behavior
- `tests/test_one_calendar_per_group.py`: stream/calendar reuse expectations
- `tests/test_calendar_ux_flow.py`: subscription stability and new-window behavior
- `tests/test_api_endpoints.py`: API contracts

## AI Tests

AI integration tests make real provider calls and use tokens.

Use them when changing:

- prompts
- provider rotation
- response-shape coercion
- marker/AI handoff logic

Typical command:

```bash
make test-ai
```

## Calendar Tests

Google Calendar API tests require valid credentials and should be treated as integration tests.

Typical command:

```bash
make test-calendar
```

## Release-Critical Reality Check

For `1.1.0-rc1`, automated tests are necessary but not sufficient. Before deploying a quarter
rollover:

1. start from a known DB snapshot
2. run XLSX + PDF imports on current code
3. compare calendar-backed stream IDs and `calendar_id`s before/after
4. confirm `calendar_synced_at` is cleared only on the streams that truly need updates

That manual rehearsal is documented in:

- [v1-1-continuity.md](./v1-1-continuity.md)
- [../RELEASE.md](../RELEASE.md)

## Notes

- The project uses `services/database/waste_schedule.db` as the active DB.
- The root `waste_schedule.db` is only a manual snapshot/helper unless explicitly copied over.
- PDF imports can be slow; that is normal for AI-heavy cells.
