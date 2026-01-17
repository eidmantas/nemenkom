# Schedule Groups: Final Decision

## The Problem

1. **Current `schedule_group_id` is unclear**: Auto-increment integers (1, 2, 3...) - can't tell what they represent
2. **Need multi-waste-type support**: General waste, plastic, glass, etc. (each has separate XLSX files)
3. **One location → multiple schedules**: Same location needs different schedule groups for different waste types
4. **Keep it simple**: Avoid complex SQL JOINs, make it human-readable

## UX Flow (What We're Building For)

1. User enters: "Avižieniai, Durpių g., house 5"
2. System finds location → shows schedules for all waste types
3. User clicks "Get Calendar" → generates Google Calendar for that schedule_group
4. **Goal**: Keep number of calendars manageable (group locations with identical schedules)

## Decision: Simple Denormalized Design ⭐

### Schema (Simplified)

```sql
-- Schedule groups (per waste type, with dates and Kaimai hashes stored as JSON)
CREATE TABLE schedule_groups (
    id TEXT PRIMARY KEY,  -- Hash-based: "sg_a3f8b2c1d4e5" (hash of waste_type + sorted_dates)
    waste_type TEXT NOT NULL DEFAULT 'bendros',  -- 'bendros', 'plastikas', 'stiklas'
    first_date DATE,
    last_date DATE,
    date_count INTEGER,
    dates TEXT,  -- JSON array: '["2026-01-08", "2026-01-22", ...]' - actual pickup dates
    kaimai_hashes TEXT,  -- JSON array stored as TEXT: '["k1_abc123", "k1_def456", ...]'
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    -- Note: SQLite stores JSON as TEXT but has JSON functions (json(), json_extract(), etc.)
);

-- Locations (simple, no FKs - query schedule_groups by kaimai_hash match)
CREATE TABLE locations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    seniūnija TEXT NOT NULL,
    village TEXT NOT NULL,
    street TEXT NOT NULL,
    house_numbers TEXT,
    kaimai_hash TEXT NOT NULL,  -- Hash of original Kaimai column (used to find schedule_group)
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(seniūnija, village, street, house_numbers)
);

-- NOTE: pickup_dates table was removed - dates are now stored in schedule_groups.dates (JSON)
-- This eliminates 95% data duplication since all locations in a schedule_group share the same dates
-- Old schema (for reference):
-- CREATE TABLE pickup_dates (
--     id INTEGER PRIMARY KEY AUTOINCREMENT,
--     location_id INTEGER NOT NULL,
    date DATE NOT NULL,
    waste_type TEXT NOT NULL DEFAULT 'bendros',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (location_id) REFERENCES locations(id),
    UNIQUE(location_id, date, waste_type)
);

-- Indexes
CREATE INDEX idx_schedule_groups_waste_type ON schedule_groups(waste_type);
CREATE INDEX idx_locations_kaimai_hash ON locations(kaimai_hash);
-- Note: We query schedule_groups by matching kaimai_hash in kaimai_hashes JSON array
```

### How It Works

1. **Grouping**: Locations with identical dates + same waste_type → same schedule_group_id
2. **Kaimai hash**: Each location stores its `kaimai_hash` (hash of original Kaimai string)
3. **Denormalization**: `schedule_groups.kaimai_hashes` stores JSON array of all Kaimai hashes in that group
4. **No FKs**: Query schedule_groups by matching `kaimai_hash` in `kaimai_hashes` JSON array

### Example Data

```sql
-- Schedule group
schedule_groups:
id: "sg_a3f8b2c1d4e5"
waste_type: "bendros"
first_date: "2026-01-02"
last_date: "2026-06-30"
date_count: 12
kaimai_hashes: '["k1_abc123", "k1_def456", "k1_ghi789"]'  -- All locations in this group

-- Locations
locations:
id: 1, kaimai_hash: "k1_abc123", general_waste_schedule_group_id: "sg_a3f8b2c1d4e5", ...
id: 2, kaimai_hash: "k1_def456", general_waste_schedule_group_id: "sg_a3f8b2c1d4e5", ...
id: 3, kaimai_hash: "k1_ghi789", general_waste_schedule_group_id: "sg_a3f8b2c1d4e5", ...
```

### Benefits

✅ **Simple queries**: Query by kaimai_hash match
```sql
-- Find schedule_group for a location (by kaimai_hash)
SELECT id, waste_type FROM schedule_groups
WHERE json_extract(kaimai_hashes, '$') LIKE '%"k1_abc123"%'
  AND waste_type = 'bendros';

-- Better: Use json_each to find exact match
SELECT DISTINCT sg.id, sg.waste_type 
FROM schedule_groups sg, json_each(sg.kaimai_hashes)
WHERE json_each.value = 'k1_abc123'
  AND sg.waste_type = 'bendros';

-- Get all locations in a schedule group (by matching kaimai_hash)
SELECT l.* FROM locations l
JOIN schedule_groups sg ON json_extract(sg.kaimai_hashes, '$') LIKE '%' || l.kaimai_hash || '%'
WHERE sg.id = 'sg_a3f8b2c1d4e5';

-- Or simpler: just get kaimai_hashes from schedule_group (human-readable!)
SELECT kaimai_hashes FROM schedule_groups WHERE id = 'sg_a3f8b2c1d4e5';
-- Returns: '["k1_abc123", "k1_def456", "k1_ghi789"]' (JSON as TEXT)
```

✅ **Human-readable**: Can see which locations are in a group by looking at `kaimai_hashes`
✅ **Direct FKs**: No junction table complexity
✅ **Easy debugging**: Can trace by Kaimai hash

### Trade-offs

✅ **No schema changes for new waste types**: Just create new schedule_groups rows with different waste_type
- No need to add columns to locations table

⚠️ **Query performance**: Need to query JSON array to find schedule_group for a location
- But: Can use indexes on kaimai_hash in locations table
- Alternative: Add FK columns back if queries are too slow

⚠️ **Denormalization**: `kaimai_hashes` in schedule_groups must be kept in sync
- But: Updated only when creating/updating schedule groups (not frequent)

---

## Implementation Details

### Hash Generation

```python
import hashlib
import json

def generate_kaimai_hash(kaimai_str: str) -> str:
    """Generate hash for Kaimai column"""
    hash_obj = hashlib.sha256(kaimai_str.encode())
    return f"k1_{hash_obj.hexdigest()[:12]}"

def generate_schedule_group_id(dates: List[date], waste_type: str) -> str:
    """Generate hash-based schedule group ID"""
    date_str = ','.join(sorted([d.isoformat() for d in dates]))
    combined = f"{waste_type}:{date_str}"
    hash_obj = hashlib.sha256(combined.encode())
    hash_hex = hash_obj.hexdigest()[:12]
    return f"sg_{hash_hex}"
```

### Creating Schedule Group

```python
def find_or_create_schedule_group(conn, dates: List[date], waste_type: str, kaimai_hash: str) -> str:
    """Find existing group or create new one, updating kaimai_hashes using SQLite JSON functions"""
    schedule_group_id = generate_schedule_group_id(dates, waste_type)
    
    cursor = conn.cursor()
    
    # Check if exists
    cursor.execute("SELECT kaimai_hashes FROM schedule_groups WHERE id = ?", (schedule_group_id,))
    row = cursor.fetchone()
    
    if row:
        # Update kaimai_hashes using SQLite JSON functions
        # json_insert() adds value if not present, or use Python json for simplicity
        existing_hashes = json.loads(row[0] or '[]')
        if kaimai_hash not in existing_hashes:
            existing_hashes.append(kaimai_hash)
            # Use SQLite's json() function to ensure valid JSON
            cursor.execute("""
                UPDATE schedule_groups 
                SET kaimai_hashes = json(?)
                WHERE id = ?
            """, (json.dumps(existing_hashes), schedule_group_id))
    else:
        # Create new using SQLite json() function
        first_date = min(dates).isoformat() if dates else None
        last_date = max(dates).isoformat() if dates else None
        date_count = len(dates)
        
        cursor.execute("""
            INSERT INTO schedule_groups (id, waste_type, first_date, last_date, date_count, kaimai_hashes)
            VALUES (?, ?, ?, ?, ?, json(?))
        """, (schedule_group_id, waste_type, first_date, last_date, date_count, json.dumps([kaimai_hash])))
    
    return schedule_group_id
```

### Querying (Simple! Using SQLite JSON functions)

```python
# Get schedule group info (including which locations are in it)
def get_schedule_group_info(schedule_group_id: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Use SQLite json_extract() to get array length and validate JSON
    cursor.execute("""
        SELECT 
            id, waste_type, first_date, last_date, date_count,
            kaimai_hashes,
            json_array_length(kaimai_hashes) as hash_count
        FROM schedule_groups 
        WHERE id = ?
    """, (schedule_group_id,))
    row = cursor.fetchone()
    
    if row:
        kaimai_hashes = json.loads(row[5] or '[]')  # Parse JSON array
        return {
            'id': row[0],
            'waste_type': row[1],
            'first_date': row[2],
            'last_date': row[3],
            'date_count': row[4],
            'kaimai_hashes': kaimai_hashes,  # Human-readable list!
            'hash_count': row[6]  # Number of locations in this group
        }
    
    return None

# Get all locations in a schedule group (query by kaimai_hash match)
def get_locations_in_group(schedule_group_id: str, waste_type: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Get kaimai_hashes from schedule_group
    cursor.execute("""
        SELECT kaimai_hashes FROM schedule_groups 
        WHERE id = ? AND waste_type = ?
    """, (schedule_group_id, waste_type))
    row = cursor.fetchone()
    
    if not row or not row[0]:
        return []
    
    # Parse JSON array
    kaimai_hashes = json.loads(row[0])
    
    # Find all locations with matching kaimai_hash
    placeholders = ','.join(['?'] * len(kaimai_hashes))
    cursor.execute(f"""
        SELECT * FROM locations 
        WHERE kaimai_hash IN ({placeholders})
    """, kaimai_hashes)
    
    return cursor.fetchall()

# Find schedule_group for a location (by kaimai_hash)
def get_schedule_group_for_location(kaimai_hash: str, waste_type: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Use json_each to find exact match
    cursor.execute("""
        SELECT DISTINCT sg.id, sg.waste_type, sg.first_date, sg.last_date
        FROM schedule_groups sg, json_each(sg.kaimai_hashes)
        WHERE json_each.value = ?
          AND sg.waste_type = ?
    """, (kaimai_hash, waste_type))
    
    return cursor.fetchone()

# Query using SQLite JSON functions directly (optional)
def get_kaimai_hashes_for_group(schedule_group_id: str):
    """Get Kaimai hashes using SQLite JSON functions"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Use json_each() to iterate over JSON array
    cursor.execute("""
        SELECT value 
        FROM schedule_groups, json_each(schedule_groups.kaimai_hashes)
        WHERE schedule_groups.id = ?
    """, (schedule_group_id,))
    
    return [row[0] for row in cursor.fetchall()]
```

---

## Alternative: JSON Column for Schedule Groups (Even More Flexible)

If you want to avoid schema changes for new waste types:

```sql
CREATE TABLE locations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    seniūnija TEXT NOT NULL,
    village TEXT NOT NULL,
    street TEXT NOT NULL,
    house_numbers TEXT,
    kaimai_hash TEXT NOT NULL,
    schedule_group_ids TEXT,  -- JSON: {"bendros": "sg_...", "plastikas": "sg_...", ...}
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(seniūnija, village, street, house_numbers)
);
```

**Pros**: No schema changes needed for new waste types
**Cons**: Slightly more complex queries (need JSON functions)

---

## Summary

✅ **Simple**: Direct FKs, no junction tables
✅ **Human-readable**: `kaimai_hashes` in schedule_groups shows which locations are in group
✅ **Easy queries**: No complex JOINs
✅ **Debuggable**: Can trace by Kaimai hash

**Your choice**: 
- Option A: Separate columns per waste type (explicit, simple)
- Option B: JSON column for schedule_group_ids (flexible, no schema changes)
