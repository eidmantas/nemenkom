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
CREATE TABLE IF NOT EXISTS schedule_groups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Table for locations (streets/villages)
CREATE TABLE IF NOT EXISTS locations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    village TEXT NOT NULL,
    street TEXT NOT NULL,
    schedule_group_id INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (schedule_group_id) REFERENCES schedule_groups(id),
    UNIQUE(village, street)
);

-- Table for pickup dates
CREATE TABLE IF NOT EXISTS pickup_dates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    location_id INTEGER NOT NULL,
    date DATE NOT NULL,
    waste_type TEXT DEFAULT 'bendros', -- 'bendros', 'plastikas', 'stiklas' (for V2)
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (location_id) REFERENCES locations(id),
    UNIQUE(location_id, date, waste_type)
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_locations_schedule_group ON locations(schedule_group_id);
CREATE INDEX IF NOT EXISTS idx_pickup_dates_location ON pickup_dates(location_id);
CREATE INDEX IF NOT EXISTS idx_pickup_dates_date ON pickup_dates(date);
CREATE INDEX IF NOT EXISTS idx_locations_village_street ON locations(village, street);
