-- Waste Schedule Database Schema

-- Table to track data fetches
CREATE TABLE IF NOT EXISTS data_fetches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fetch_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    source_url TEXT NOT NULL,
    status TEXT NOT NULL, -- 'success', 'failed', 'validation_error'
    validation_errors TEXT, -- JSON string of validation errors
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Table to group locations with the same schedule
-- Multiple locations can share the same schedule_group_id if they have identical pickup dates
-- Uses hash-based ID for deterministic grouping
-- Each waste type has separate schedule groups
CREATE TABLE IF NOT EXISTS schedule_groups (
    id TEXT PRIMARY KEY,  -- Hash-based: "sg_a3f8b2c1d4e5"
    waste_type TEXT NOT NULL DEFAULT 'bendros',  -- 'bendros', 'plastikas', 'stiklas'
    first_date DATE,                  -- First pickup date in schedule
    last_date DATE,                   -- Last pickup date in schedule
    date_count INTEGER,               -- Number of pickup dates
    dates TEXT,                       -- JSON array: '["2026-01-08", "2026-01-22", ...]' - actual pickup dates
    kaimai_hashes TEXT,               -- JSON array: '["k1_abc123", "k1_def456", ...]' - all Kaimai hashes in this group
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Table for locations (streets/villages)
-- No FK to schedule_groups - query by matching kaimai_hash in schedule_groups.kaimai_hashes JSON
CREATE TABLE IF NOT EXISTS locations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    seniūnija TEXT NOT NULL,  -- County/municipality
    village TEXT NOT NULL,     -- Village/city name
    street TEXT NOT NULL,      -- Street name (empty string if whole village)
    house_numbers TEXT,        -- House number restrictions (e.g., "nuo Nr. 1 iki 31A", "2, 4, 6")
    kaimai_hash TEXT NOT NULL, -- Hash of original Kaimai column (used to find schedule_group)
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(seniūnija, village, street, house_numbers)
);

-- Pickup dates are stored in schedule_groups.dates (JSON array)
-- No separate pickup_dates table needed:
--   - All locations with same kaimai_hash + waste_type share same schedule_group
--   - Query: location.kaimai_hash → schedule_groups (by waste_type) → dates JSON
--   - This eliminates 95% data duplication since locations in same group have identical dates

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_schedule_groups_waste_type ON schedule_groups(waste_type);
CREATE INDEX IF NOT EXISTS idx_locations_kaimai_hash ON locations(kaimai_hash);
CREATE INDEX IF NOT EXISTS idx_locations_seniūnija ON locations(seniūnija);
CREATE INDEX IF NOT EXISTS idx_locations_village_street ON locations(village, street);
CREATE INDEX IF NOT EXISTS idx_locations_full ON locations(seniūnija, village, street);
CREATE INDEX IF NOT EXISTS idx_schedule_groups_dates ON schedule_groups(first_date, last_date, date_count);
