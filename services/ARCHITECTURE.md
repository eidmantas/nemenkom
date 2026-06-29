# Services Architecture

This file describes the current `1.1.0-rc1` architecture, not the original v1.0 draft.

## Service Boundaries

```text
                nemenkom.lt
        ┌────────────┴────────────┐
        │                         │
        ▼                         ▼
  XLSX source                PDF sources
  (bendros)             (plastikas / stiklas)
        │                         │
        ▼                         ▼
┌────────────────┐      ┌─────────────────────┐
│ services/      │      │ services/           │
│ scraper        │      │ scraper_pdf         │
│                │      │                     │
│ - fetch XLSX   │      │ - fetch PDF         │
│ - parse rows   │      │ - marker extract    │
│ - write DB     │      │ - AI split/mapping  │
└───────┬────────┘      │ - continuity reuse  │
        │               │ - write DB          │
        └───────┬───────┴──────────┬──────────┘
                │                  │
                ▼                  ▼
              ┌──────────────────────┐
              │ SQLite               │
              │ services/database/   │
              │ waste_schedule.db    │
              └───────┬──────────────┘
                      │
          ┌───────────┴────────────┐
          │                        │
          ▼                        ▼
┌──────────────────┐      ┌──────────────────┐
│ services/api     │      │ services/        │
│ + services/web   │      │ calendar         │
│                  │      │                  │
│ - read schedules │      │ - create/update  │
│ - UI             │      │   Google cal     │
│ - subscribe URLs │      │ - sync events    │
└──────────────────┘      └──────────────────┘
```

- `services/scraper`: general-waste XLSX ingestion
- `services/scraper_pdf`: plastic/glass PDF ingestion, AI splitting, continuity reuse
- `services/api` + `services/web`: read API, website, subscription links
- `services/calendar`: Google Calendar creation and event sync

The active application DB is `services/database/waste_schedule.db`.

## Logical Data Flow

```text
locations / pdf_parsed_rows
            │
            ▼
      schedule_groups
            │
            ▼
    group_calendar_links
            │
            ▼
      calendar_streams
            │
            ▼
   calendar_stream_events
```

```text
User selects address in UI
        │
        ▼
API resolves matching schedule_groups
        │
        ▼
API resolves linked calendar_stream
        │
        ▼
UI shows dates + subscription link
        │
        ▼
Calendar worker syncs that stream to Google Calendar
```

## Core Model

### `locations`

Canonical address rows used mostly by the XLSX flow and UI selection.

Key fields:

- `seniunija`
- `village`
- `street`
- `house_numbers`
- `kaimai_hash`

### `pdf_parsed_rows`

Structured PDF output after extraction, AI splitting, and mapping.

This is the important bridge for quarter-to-quarter continuity because it stores parsed selections:

- `mapped_seniunija`
- `mapped_village`
- `mapped_street`
- `house_numbers`
- `kaimai_hash`
- `dates_json`

### `schedule_groups`

Logical waste schedule groups keyed by:

```text
schedule_group_id = hash(waste_type + kaimai_hash)
```

Each group owns:

- one waste type
- one stable `kaimai_hash`
- one active date set

### `calendar_streams`

Shared Google-calendar streams keyed by identical date pattern within one waste type.

Multiple `schedule_groups` may point to one `calendar_stream`.

### `group_calendar_links`

Explicit link table from `schedule_group` to `calendar_stream`.

### `calendar_stream_events`

Persisted Google event state for each date in a stream.

## Main Invariants

- `schedule_group_id` stays stable as long as continuity decides the new data is still the same real selection.
- `calendar_stream_id` stays stable when the same calendar-bearing stream can be preserved through a date refresh.
- `calendar_id` belongs to `calendar_streams`, not directly to addresses.
- `calendar_synced_at IS NULL` means the worker must create or refresh that calendar.

## XLSX Flow

```text
XLSX row
  -> parsed address + dates
  -> kaimai_hash from source grouping
  -> schedule_group upsert
  -> calendar_stream reconcile
  -> locations write/update
```

This is used for `bendros`.

## PDF Flow

```text
PDF
  -> marker-pdf extraction
  -> row cleanup
  -> AI JSON split for complex cells
  -> mapped selections
  -> continuity reuse against historical parsed rows
  -> schedule_group upsert
  -> calendar_stream reconcile
```

This is used for `plastikas` and `stiklas`.

## Continuity Model

The old problem was raw-text continuity:

```text
same real place, different provider wording -> new kaimai_hash -> new calendar
```

Current `1.1 RC` behavior:

- build canonical selection keys from parsed PDF rows
- match historical rows by normalized `seniūnija`, `village`, `street`, `house_numbers`
- allow admin-less fallback only for historical rows that were actually saved without `seniūnija`
- if matching is ambiguous, create a new group instead of guessing
- if one old hash would be reused by multiple incompatible new date sets, resolve the conflict conservatively

Implementation lives in `services/scraper_pdf/continuity.py`.

## Stream Reconciliation

`services/scraper/core/db_writer.py` keeps stream-level stability after writes.

Important cases:

### Same group, new dates

- update the existing `schedule_group`
- preserve the existing `calendar_stream`
- clear `calendar_synced_at`

### One old stream splits into multiple date patterns

- preserve the old calendar-bearing stream on the best successor
- move the other groups onto new streams
- avoid abandoning the existing Google calendar when one clear continuation exists

### Stream becomes orphaned

- mark pending clean
- do not auto-delete calendars immediately

## Calendar Metadata Refresh

`services/calendar/__init__.py` now rebuilds descriptions from DB scope:

- waste type
- seniūnija / village / street coverage
- current date range
- change note

This refresh happens:

- when an existing calendar is reused
- after event sync

So existing subscribed calendars get updated descriptions automatically, not only newly created ones.

## Current Safety Model

Safe to preserve continuity:

- harmless raw renames like `k.` -> `mstl.`
- provider formatting drift in the same real place
- quarter rollover where only dates move forward

Safe to create a new group instead:

- genuinely new villages / streets / house-number buckets
- ambiguous historical overlap
- future provider regrouping where one old schedule splits into multiple different date sets

## Related Docs

- [../documentation/v1-1-continuity.md](../documentation/v1-1-continuity.md)
- [../documentation/TESTING.md](../documentation/TESTING.md)
- [../RELEASE.md](../RELEASE.md)
