# Option B: Stable Calendar IDs Design

## The Problem with Option A

**Option A (Rejected)**: `schedule_group_id` = hash of `waste_type + dates`

**Critical UX Issue**: When dates change (e.g., municipality updates schedule mid-year), the `schedule_group_id` changes, creating a **new calendar ID**. Users who subscribed to the old calendar lose their subscription and must re-subscribe. This is terrible UX.

**Example of the problem:**
```
Initial state:
- Location: "Vanaginės g. 25"
- schedule_group_id: sg_abc123 (hash of dates: [2026-01-08, 2026-01-22, ...])
- calendar_id: calendar123@google.com
- User subscribes to calendar123@google.com ✅

After date update:
- Same location: "Vanaginės g. 25"
- schedule_group_id: sg_def456 (NEW hash because dates changed!)
- calendar_id: calendar789@google.com (NEW calendar!)
- User's old subscription is now broken ❌
```

## Option B: Stable IDs (Chosen Solution)

**Core Principle**: `schedule_group_id` = hash of `kaimai_hash + waste_type` (NOT dates!)

This ensures:
- ✅ Calendar ID remains stable even when dates change
- ✅ Users keep their subscriptions
- ✅ Calendar events are updated in-place (delete old, add new)
- ✅ Better UX: "Subscribe once, always updated"

## Schema Design

### schedule_groups Table

```sql
CREATE TABLE schedule_groups (
    id TEXT PRIMARY KEY,                    -- STABLE: hash(kaimai_hash + waste_type)
    waste_type TEXT NOT NULL DEFAULT 'bendros',
    kaimai_hash TEXT NOT NULL,              -- Single hash (not JSON array!)
    dates TEXT,                             -- JSON array of pickup dates
    dates_hash TEXT,                        -- Hash of sorted dates (for change detection)
    first_date DATE,
    last_date DATE,
    date_count INTEGER,
    calendar_id TEXT,                       -- Google Calendar ID (stable!)
    calendar_synced_at TIMESTAMP,           -- NULL = needs sync, timestamp = synced
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(kaimai_hash, waste_type)         -- One schedule group per location+waste_type
);
```

**Key Changes from Option A:**
- `id` is now based on `kaimai_hash + waste_type` (stable, never changes)
- `kaimai_hash` is a single TEXT value (not JSON array)
- `dates_hash` added for efficient change detection
- `calendar_id` and `calendar_synced_at` added for sync tracking

### locations Table

```sql
CREATE TABLE locations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    seniunija TEXT NOT NULL,               -- ASCII: "seniunija" (not "seniūnija")
    village TEXT NOT NULL,
    street TEXT NOT NULL,
    house_numbers TEXT,
    kaimai_hash TEXT NOT NULL,              -- Links to schedule_groups.kaimai_hash
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(seniunija, village, street, house_numbers)
);
```

### calendar_events Table (New)

```sql
CREATE TABLE calendar_events (
    schedule_group_id TEXT NOT NULL,
    date DATE NOT NULL,
    event_id TEXT,                          -- Google Calendar event ID
    status TEXT DEFAULT 'pending',          -- 'pending', 'created', 'error'
    error_message TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (schedule_group_id, date),
    FOREIGN KEY (schedule_group_id) REFERENCES schedule_groups(id) ON DELETE CASCADE
);
```

**Purpose**: Track each date's Google Calendar event for:
- Resume-on-failure (if sync is interrupted)
- Granular error tracking
- Efficient updates (know which events to delete/add)

## ID Generation Logic

### schedule_group_id (Stable)

```python
def generate_schedule_group_id(kaimai_hash: str, waste_type: str) -> str:
    """
    Generate STABLE schedule group ID from kaimai_hash + waste_type
    
    This ID NEVER changes, even when dates change.
    """
    combined = f"{waste_type}:{kaimai_hash}"
    hash_hex = hashlib.sha256(combined.encode()).hexdigest()[:12]
    return f"sg_{hash_hex}"
```

**Example:**
- `kaimai_hash`: `k1_abc123def456`
- `waste_type`: `bendros`
- `schedule_group_id`: `sg_7f3a9b2c1d4e` (always the same for this location+waste_type)

### dates_hash (Change Detection)

```python
def generate_dates_hash(dates: List[date]) -> str:
    """
    Generate hash of sorted dates for change detection
    
    Used to detect when schedule dates have changed and calendar needs re-sync
    """
    if not dates:
        return ""
    date_str = ','.join(sorted([d.isoformat() for d in dates]))
    return hashlib.sha256(date_str.encode()).hexdigest()[:16]
```

**Example:**
- Dates: `[2026-01-08, 2026-01-22, 2026-02-05]`
- `dates_hash`: `a3f8b2c1d4e5f6g7` (changes if dates change)

## Schedule Group Lifecycle

### State Machine

```
┌─────────────────────────────────────────────────────────────┐
│ 1. CREATED (calendar_id = NULL, calendar_synced_at = NULL)   │
│    ↓                                                          │
│    Background worker creates Google Calendar                 │
│    ↓                                                          │
│ 2. CALENDAR_CREATED (calendar_id set, calendar_synced_at = NULL) │
│    ↓                                                          │
│    Background worker syncs events (adds all dates)           │
│    ↓                                                          │
│ 3. SYNCED (calendar_id set, calendar_synced_at = timestamp) │
│    ↓                                                          │
│    [Dates change detected via dates_hash]                    │
│    ↓                                                          │
│ 4. NEEDS_UPDATE (calendar_id set, calendar_synced_at = NULL) │
│    ↓                                                          │
│    Background worker syncs events (deletes old, adds new)    │
│    ↓                                                          │
│ 3. SYNCED (calendar_id set, calendar_synced_at = timestamp) │
└─────────────────────────────────────────────────────────────┘
```

### Date Change Detection

When `find_or_create_schedule_group()` is called:

1. **Check if schedule group exists** (by `kaimai_hash + waste_type`)
2. **Compare `dates_hash`**:
   - If `dates_hash` matches → No change, return existing ID
   - If `dates_hash` differs → Dates changed!
     - Update `dates`, `dates_hash`, `first_date`, `last_date`, `date_count`
     - **Set `calendar_synced_at = NULL`** (triggers re-sync)
     - Return existing `schedule_group_id` (stable!)

```python
def find_or_create_schedule_group(conn, dates, waste_type, kaimai_hash):
    schedule_group_id = generate_schedule_group_id(kaimai_hash, waste_type)
    new_dates_hash = generate_dates_hash(dates)
    
    # Check if exists
    cursor.execute("SELECT dates_hash FROM schedule_groups WHERE id = ?", 
                   (schedule_group_id,))
    row = cursor.fetchone()
    
    if row:
        existing_dates_hash = row[0]
        if existing_dates_hash != new_dates_hash:
            # Dates changed! Update and mark for re-sync
            cursor.execute("""
                UPDATE schedule_groups 
                SET dates = ?, dates_hash = ?, 
                    first_date = ?, last_date = ?, date_count = ?,
                    calendar_synced_at = NULL,  -- Trigger re-sync!
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (dates_json, new_dates_hash, first_date, last_date, 
                  date_count, schedule_group_id))
    else:
        # Create new schedule group
        cursor.execute("""
            INSERT INTO schedule_groups 
            (id, waste_type, kaimai_hash, dates, dates_hash, ...)
            VALUES (?, ?, ?, ?, ?, ...)
        """, (schedule_group_id, waste_type, kaimai_hash, dates_json, 
              new_dates_hash, ...))
    
    return schedule_group_id  # Always stable!
```

## Calendar Synchronization

### Background Worker

**Location**: `scraper/scheduler.py`

**Purpose**: Continuously check for schedule groups needing calendar creation or sync

**Logic**:
```python
def create_calendar_background_worker():
    while True:
        # Get groups needing sync
        groups = get_schedule_groups_needing_sync()
        # Conditions: calendar_id IS NULL OR calendar_synced_at IS NULL
        
        for group in groups:
            if group['calendar_id'] is None:
                # Create calendar
                calendar = create_calendar_for_schedule_group(...)
                update_schedule_group_calendar_id(group['id'], calendar['id'])
            
            # Sync events (add new, delete old)
            sync_calendar_for_schedule_group(group['id'])
            
            # Mark as synced
            update_schedule_group_calendar_synced(group['id'])
        
        time.sleep(60)  # Check every minute
```

### Calendar Creation

**Function**: `services/calendar.py::create_calendar_for_schedule_group()`

**Steps**:
1. Get location names from `locations` table (by `kaimai_hash`)
2. Create Google Calendar with name: `"[Waste Type] - [Location Names]"`
3. Store `calendar_id` in `schedule_groups.calendar_id`
4. Set `calendar_synced_at = NULL` (triggers initial event sync)

**Note**: Calendar creation is separate from event sync (two-phase process)

### Event Synchronization

**Function**: `services/calendar.py::sync_calendar_for_schedule_group()`

**Steps**:
1. Get current dates from `schedule_groups.dates` (JSON)
2. Get existing events from `calendar_events` table
3. **Delete old events**: Dates in DB but not in current schedule
4. **Add new events**: Dates in current schedule but not in DB
5. **Retry failed events**: Events with `status = 'error'`
6. Update `calendar_events` table for each operation
7. Set `calendar_synced_at = CURRENT_TIMESTAMP` when complete

**Example Flow**:
```
Current dates: [2026-01-08, 2026-01-22, 2026-02-05]
Existing events in calendar_events:
  - 2026-01-08: event_id=evt123, status='created'
  - 2026-01-22: event_id=evt456, status='created'
  - 2026-01-15: event_id=evt789, status='created'  (OLD - not in current dates!)

Actions:
1. Delete event evt789 from Google Calendar (date 2026-01-15 removed)
2. Add event for 2026-02-05 (new date)
3. Update calendar_events table:
   - Delete row (schedule_group_id, 2026-01-15)
   - Insert row (schedule_group_id, 2026-02-05, event_id=evt999, status='created')
```

## API Endpoints

### GET /api/v1/schedule

**Returns**:
```json
{
  "id": 123,
  "seniunija": "Avižienių",
  "village": "Pikutiškės",
  "street": "Vanaginės g.",
  "house_numbers": "25",
  "kaimai_hash": "k1_abc123",
  "schedule_group_id": "sg_7f3a9b2c1d4e",
  "waste_type": "bendros",
  "dates": [
    {"date": "2026-01-08", "waste_type": "bendros"},
    {"date": "2026-01-22", "waste_type": "bendros"}
  ],
  "calendar_id": "calendar123@google.com",
  "subscription_link": "https://calendar.google.com/calendar/render?cid=calendar123@google.com",
  "calendar_status": {
    "status": "synced",  // or "pending", "needs_update", "not_available"
    "calendar_id": "calendar123@google.com"
  }
}
```

**Calendar Status Values**:
- `"synced"`: Calendar exists and is up-to-date (`calendar_synced_at` is set)
- `"pending"`: Calendar doesn't exist yet (`calendar_id` is NULL)
- `"needs_update"`: Calendar exists but dates changed (`calendar_synced_at` is NULL)
- `"not_available"`: No schedule group found

## Web GUI Integration

**File**: `web/templates/index.html`

**Display Logic**:
```javascript
if (schedule.calendar_status.status === 'synced') {
    // Show "Subscribe to Google Calendar" button
    showSubscribeButton(schedule.subscription_link);
} else if (schedule.calendar_status.status === 'pending') {
    // Show "System pending sync - check later" message
    showPendingMessage();
} else if (schedule.calendar_status.status === 'needs_update') {
    // Show "Updating calendar..." message
    showUpdatingMessage();
}
```

## Benefits of Option B

✅ **Stable Calendar Links**: Users subscribe once, link never breaks
✅ **Automatic Updates**: When dates change, calendar events update automatically
✅ **Resume-on-Failure**: `calendar_events` table allows resuming interrupted syncs
✅ **Granular Tracking**: Know exactly which events succeeded/failed
✅ **Efficient Queries**: Direct lookup by `kaimai_hash` (no JSON array searching)
✅ **Simple Schema**: Single `kaimai_hash` column (not JSON array)

## Migration from Option A

**Note**: User opted to "nuke the database" rather than implement migrations.

**Process**:
1. Drop existing database
2. Run `database/schema.sql` (Option B schema)
3. Re-run scraper to populate with new schema

**If migration were needed**:
- Map old `schedule_group_id` (date-based) to new `schedule_group_id` (kaimai_hash-based)
- Re-create all Google Calendars (old calendar IDs are invalid)
- Notify users to re-subscribe (one-time migration cost)

## Implementation Files

### Core Logic
- `database/schema.sql`: Option B schema definition
- `scraper/core/db_writer.py`: `generate_schedule_group_id()`, `generate_dates_hash()`, `find_or_create_schedule_group()`
- `api/db.py`: Query functions using Option B schema

### Calendar Sync
- `services/calendar.py`: `create_calendar_for_schedule_group()`, `sync_calendar_for_schedule_group()`
- `scraper/scheduler.py`: Background worker for continuous sync

### API & Web
- `api/app.py`: Endpoints returning `calendar_status` and `subscription_link`
- `web/templates/index.html`: GUI displaying calendar status

### Tests
- `tests/test_stable_ids.py`: Unit tests for ID generation and date hash logic
- `tests/test_google_calendar_real_api.py`: Integration tests for calendar sync

## Calendar Naming & Public Access

### Calendar Naming Strategy
- **Format**: `[Seniūnija] - [Waste Type Display]`
- **Example**: "Avižienių - Bendros atliekos"
- **Rationale**: All locations in a schedule group share the same seniunija, making it the most stable and meaningful identifier
- **Description**: Includes location count and auto-update notice

### Public Access
- **Automatic**: All calendars are automatically made publicly readable via ACL
- **ACL Rule**: `scope: {type: 'default'}, role: 'reader'`
- **Existing Calendars**: Automatically checked and made public if needed
- **Subscription Links**: Work immediately after calendar creation

## Rate Limiting & Error Handling

### Google Calendar API Limits
- **Quota**: 1,000,000 queries per day (free tier)
- **Rate Limit**: ~100 requests/second
- **Strategy**: Background worker processes one group at a time with 5-minute retry intervals

### Error Handling
- **Failed Event Creation**: Store in `calendar_events` with `status='error'`
- **Retry Logic**: Background worker retries failed events on next cycle
- **Rate Limit Errors**: 5-minute retry interval, resume later

## Calendar Cleanup

### Orphaned Calendar Cleanup
- **Function**: `services/calendar.py::cleanup_orphaned_calendars()`
- **Purpose**: Delete calendars that exist in Google Calendar but not in database
- **Use Cases**: 
  - Clean up test calendars before release
  - Remove calendars from deleted schedule groups
  - Maintenance after database resets
- **Makefile Targets**:
  - `make clean-calendars-dry-run`: Check what would be deleted (safe)
  - `make clean-calendars`: Actually delete orphaned calendars (requires confirmation)

### Cleanup Process
1. List all calendars in Google Calendar (filtered by naming pattern)
2. Get all `calendar_id`s from `schedule_groups` table
3. Identify orphaned calendars (exist in Google but not in DB)
4. Delete orphaned calendars with error handling
5. Report statistics (total, orphaned, deleted, errors)

## Future Enhancements

1. **Multi-Waste-Type Calendars**: Combine general/plastic/glass into single calendar (V2)
2. **Calendar Sharing**: Allow users to share calendars with family
3. **Notifications**: Email users when their calendar is updated
4. **Calendar Analytics**: Track subscription counts per calendar
