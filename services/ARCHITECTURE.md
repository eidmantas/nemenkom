# Services Architecture

## 1. Service Boundaries and Responsibilities

```
┌─────────────┐     ┌───────────────┐     ┌───────────────┐
│  Scraper    │ --> │ SQLite DB     │ <-- │ API + Web     │
│ (services/  │     │ (services/    │     │ (services/    │
│  scraper)   │     │  database)    │     │  api, web)    │
└─────┬───────┘     └──────┬────────┘     └──────┬────────┘
      │                   │                      │
      │                   │                      │
      ▼                   ▼                      ▼
┌─────────────────────────────────────────────────────────┐
│ Calendar Worker (services/calendar)                     │
│ - Creates Google Calendars for streams                  │
│ - Syncs events in place                                 │
│ - Handles pending clean + deletion workflow             │
└─────────────────────────────────────────────────────────┘
```

### Scraper (services/scraper)
- Ingests XLSX, validates, parses, and writes normalized records into SQLite.
- Owns stream reconciliation and link updates after data refresh.

### API + Web (services/api, services/web)
- Read-only access to schedules and calendar metadata.
- Produces subscription URLs and status.

### Calendar Worker (services/calendar)
- Creates calendars and syncs events for streams.
- Handles pending-clean notices and deletion for obsolete calendars.

## 2. Key Identifiers and Invariants

```
Schedule Group ID  = stable hash(kaimai_hash + waste_type)
Calendar Stream ID = random stable id (cs_xxx)
dates_hash         = hash(sorted dates)
```

**Invariants**
- schedule_group_id is stable for `(kaimai_hash, waste_type)` across date changes.
- calendar_stream_id groups identical `(dates_hash, waste_type)` patterns.
- N schedule_groups → 1 calendar_stream; link is explicit in `group_calendar_links`.
- When a schedule_group diverges, it re-links to another stream or creates a new one.

## 3. Database Schema (Logical Model)

### Core Tables

```
data_fetches
┌───────────────┬─────────────────────────────────────────┐
│ id            │ integer PK                              │
│ fetch_date    │ timestamp (default now)                 │
│ source_url    │ text                                    │
│ status        │ text                                    │
│ validation_errors │ text (json)                         │
│ created_at    │ timestamp                               │
└───────────────┴─────────────────────────────────────────┘
```

```
locations
┌───────────────┬─────────────────────────────────────────┐
│ id            │ integer PK                              │
│ seniunija     │ text                                    │
│ village       │ text                                    │
│ street        │ text                                    │
│ house_numbers │ text (nullable)                         │
│ kaimai_hash   │ text                                    │
│ created_at    │ timestamp                               │
│ updated_at    │ timestamp                               │
│ UNIQUE(seniunija, village, street, house_numbers)       │
└───────────────┴─────────────────────────────────────────┘
```

```
schedule_groups
┌───────────────┬─────────────────────────────────────────┐
│ id            │ text PK (sg_*)                           │
│ waste_type    │ text                                    │
│ kaimai_hash   │ text                                    │
│ dates         │ text (json array of ISO dates)          │
│ dates_hash    │ text                                    │
│ first_date    │ date                                    │
│ last_date     │ date                                    │
│ date_count    │ int                                     │
│ calendar_id   │ text                                    │
│ calendar_synced_at │ timestamp                          │
│ created_at    │ timestamp                               │
│ updated_at    │ timestamp                               │
│ UNIQUE(kaimai_hash, waste_type)                         │
└───────────────┴─────────────────────────────────────────┘
```

### Calendar Streams

```
calendar_streams
┌───────────────┬─────────────────────────────────────────┐
│ id            │ text PK (cs_*)                           │
│ waste_type    │ text                                    │
│ dates_hash    │ text                                    │
│ dates         │ text (json array of ISO dates)          │
│ first_date    │ date                                    │
│ last_date     │ date                                    │
│ date_count    │ int                                     │
│ calendar_id   │ text                                    │
│ calendar_synced_at │ timestamp                          │
│ pending_clean_started_at │ timestamp (nullable)         │
│ pending_clean_until │ timestamp (nullable)              │
│ pending_clean_notice_sent_at │ timestamp (nullable)     │
│ created_at    │ timestamp                               │
│ updated_at    │ timestamp                               │
└───────────────┴─────────────────────────────────────────┘
```

```
group_calendar_links
┌───────────────┬─────────────────────────────────────────┐
│ schedule_group_id │ text PK (FK → schedule_groups)      │
│ calendar_stream_id │ text FK → calendar_streams         │
│ created_at     │ timestamp                              │
│ updated_at     │ timestamp                              │
└───────────────┴─────────────────────────────────────────┘
```

### Calendar Events

```
calendar_stream_events
┌───────────────┬─────────────────────────────────────────┐
│ calendar_stream_id │ text FK → calendar_streams         │
│ date          │ date                                    │
│ event_id      │ text (Google event id)                  │
│ status        │ text (pending|created|error)            │
│ error_message │ text (nullable)                         │
│ created_at    │ timestamp                               │
│ updated_at    │ timestamp                               │
│ PK(calendar_stream_id, date)                            │
└───────────────┴─────────────────────────────────────────┘
```

Stream-based sync uses `calendar_streams` and `calendar_stream_events`.

## 4. Entity Relationships (ER-style view)

```
locations (kaimai_hash)
        │
        │ 1..N
        ▼
schedule_groups (id, kaimai_hash, waste_type, dates_hash)
        │ 1..1
        ▼
group_calendar_links (schedule_group_id → calendar_stream_id)
        │ N..1
        ▼
calendar_streams (id, dates_hash, calendar_id, sync state)
        │ 1..N
        ▼
calendar_stream_events (calendar_stream_id, date, event_id)
```

## 5. Scraper → Database Flow

```
XLSX → parse rows → (seniunija, village, street, house_numbers, dates, kaimai_str)
                 ↓
generate kaimai_hash (stable for same kaimai_str)
                 ↓
find_or_create_schedule_group(kaimai_hash + waste_type)
                 ↓
find_or_create_calendar_stream(dates_hash + waste_type)
                 ↓
upsert_group_calendar_link(schedule_group_id → calendar_stream_id)
                 ↓
write locations table (deduped by UNIQUE)
                 ↓
reconcile_calendar_streams()
```

Calendar consistency path (read + sync):

```
locations(kaimai_hash)
        │
        ▼
schedule_groups(id, dates_hash, waste_type)
        │
        ▼
group_calendar_links(schedule_group_id → calendar_stream_id)
        │
        ▼
calendar_streams(id, dates_hash, calendar_id)
        │
        ▼
calendar_stream_events(calendar_stream_id, date, event_id, status)
```

Key functions:
- `services/scraper/core/db_writer.py`
  - `find_or_create_schedule_group`
  - `find_or_create_calendar_stream`
  - `upsert_group_calendar_link`
  - `reconcile_calendar_streams`

## 6. Calendar Stream Reconciliation

Reconciliation happens after all rows are written.

### Case A: Single dates_hash
All linked groups share the same `dates_hash`:
- update `calendar_streams.dates` and `dates_hash`
- set `calendar_synced_at` to NULL if dates changed
- clear pending-clean flags

### Case B: Divergent dates_hash
Linked groups diverge:
- create new stream(s) per dates_hash
- relink groups
- mark the old stream pending clean

### Case C: Orphaned stream
No linked groups remain:
- mark pending clean immediately

## 7. Calendar Creation and Sync

### Creation (per stream)
`create_calendar_for_calendar_stream(calendar_stream_id)`:
- resolve a representative `seniunija` via linked locations
- create a Google Calendar and store `calendar_id`
- enforce public read ACL

### Sync (per stream)
`sync_calendar_for_calendar_stream(calendar_stream_id)`:
- load desired dates from `calendar_streams`
- load existing events from `calendar_stream_events`
- compute deltas: add/delete/retry
- update Google Calendar and persist event state
- set `calendar_synced_at`

### Cleanup Workflow (deprecation)
When a stream is superseded:
- set `pending_clean_started_at` and `pending_clean_until` (+4 days)
- post 3 notice events in the old calendar
- delete calendar if still orphaned after `pending_clean_until`

## 8. API Read Path

### /api/v1/schedule
Lookup by location:
```
locations → kaimai_hash
schedule_groups (by kaimai_hash + waste_type)
group_calendar_links → calendar_streams
```

Response includes:
- location metadata
- schedule_group_id
- dates (from schedule_groups)
- calendar_id + subscription_link (from calendar_streams)
- calendar_status derived from calendar_streams.calendar_id + calendar_synced_at

### /api/v1/schedule-group/<id>
Lookup by schedule group:
```
schedule_groups → locations (by kaimai_hash)
group_calendar_links → calendar_streams (calendar_id)
```

## 9. Why Both schedule_groups and calendar_streams?

This is the core UX vs scalability compromise:

- **schedule_groups** keep IDs stable per address + waste type.
- **calendar_streams** keep calendar counts low by sharing identical date patterns.

If dates for a schedule group change, the group is re-linked to a new stream:
- If the new pattern is shared → join existing stream
- If not shared → create new stream

Old streams are not deleted immediately; they enter pending clean, post user notices, then delete once they are orphaned.

## 10. Services (Detailed)

### services/scraper
- `core/fetcher.py` downloads XLSX.
- `core/parser.py` parses rows (AI-assisted when needed).
- `core/validator.py` validates structure and parsed rows.
- `core/db_writer.py` writes data, updates streams, and reconciles.

### services/api
- `api/app.py` exposes read-only endpoints.
- `api/db.py` joins locations → schedule_groups → calendar_streams.

### services/calendar
- `calendar/__init__.py` creates calendars, syncs events, and cleans up.
- `calendar/worker.py` polls for unsynced streams and pending cleanup.

### services/scraper_pdf (unreleased)
- Prototype parser for PDF schedules.
- Not part of the production ingest path.

## 11. Operational Concerns

- **Idempotency**: calendar sync is designed to be safe to retry; deltas are computed.
- **Rate limiting**: throttling handled in calendar client utilities (calendar APIs only).
- **Concurrency**: calendar worker is single-threaded polling.
- **Observability**: logs in worker and scraper; DB retains fetch history in `data_fetches`.

