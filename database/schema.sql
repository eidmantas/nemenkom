-- Waste Schedule Database Schema
-- Version 2: Option B - Stable IDs (kaimai_hash + waste_type)
-- Calendar sync tracking with dates_hash and calendar_events table

-- Table to track data fetches
CREATE TABLE IF NOT EXISTS data_fetches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fetch_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    source_url TEXT NOT NULL,
    status TEXT NOT NULL,
    validation_errors TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Table to group locations with the same schedule
-- OPTION B: Stable IDs based on kaimai_hash + waste_type (NOT dates!)
CREATE TABLE IF NOT EXISTS schedule_groups (
    id TEXT PRIMARY KEY,
    waste_type TEXT NOT NULL DEFAULT 'bendros',
    kaimai_hash TEXT NOT NULL,
    dates TEXT,
    dates_hash TEXT,
    first_date DATE,
    last_date DATE,
    date_count INTEGER,
    calendar_id TEXT,
    calendar_synced_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(kaimai_hash, waste_type)
);

-- Table for locations (streets/villages)
CREATE TABLE IF NOT EXISTS locations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    seniunija TEXT NOT NULL,
    village TEXT NOT NULL,
    street TEXT NOT NULL,
    house_numbers TEXT,
    kaimai_hash TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(seniunija, village, street, house_numbers)
);

-- Calendar events: track each date's event for resume & sync
CREATE TABLE IF NOT EXISTS calendar_events (
    schedule_group_id TEXT NOT NULL,
    date DATE NOT NULL,
    event_id TEXT,
    status TEXT DEFAULT 'pending',
    error_message TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (schedule_group_id, date),
    FOREIGN KEY (schedule_group_id) REFERENCES schedule_groups(id) ON DELETE CASCADE
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_schedule_groups_waste_type ON schedule_groups(waste_type);
CREATE INDEX IF NOT EXISTS idx_schedule_groups_calendar_id ON schedule_groups(calendar_id);
CREATE INDEX IF NOT EXISTS idx_schedule_groups_dates_hash ON schedule_groups(dates_hash);
CREATE INDEX IF NOT EXISTS idx_schedule_groups_kaimai_hash ON schedule_groups(kaimai_hash);
CREATE INDEX IF NOT EXISTS idx_locations_kaimai_hash ON locations(kaimai_hash);
CREATE INDEX IF NOT EXISTS idx_locations_seniunija ON locations(seniunija);
CREATE INDEX IF NOT EXISTS idx_locations_village_street ON locations(village, street);
CREATE INDEX IF NOT EXISTS idx_locations_full ON locations(seniunija, village, street);
CREATE INDEX IF NOT EXISTS idx_schedule_groups_dates ON schedule_groups(first_date, last_date, date_count);
CREATE INDEX IF NOT EXISTS idx_calendar_events_status ON calendar_events(status);
CREATE INDEX IF NOT EXISTS idx_calendar_events_event_id ON calendar_events(event_id);
