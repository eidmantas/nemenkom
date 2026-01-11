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
    first_date DATE,                  -- First pickup date in schedule
    last_date DATE,                   -- Last pickup date in schedule
    date_count INTEGER,               -- Number of pickup dates
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Table for locations (streets/villages)
CREATE TABLE IF NOT EXISTS locations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    seniūnija TEXT NOT NULL,  -- County/municipality
    village TEXT NOT NULL,     -- Village/city name
    street TEXT NOT NULL,      -- Street name (empty string if whole village)
    house_numbers TEXT,        -- House number restrictions (e.g., "nuo Nr. 1 iki 31A", "2, 4, 6")
    schedule_group_id INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (schedule_group_id) REFERENCES schedule_groups(id),
    UNIQUE(seniūnija, village, street, house_numbers)
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
CREATE INDEX IF NOT EXISTS idx_locations_seniūnija ON locations(seniūnija);
CREATE INDEX IF NOT EXISTS idx_locations_village_street ON locations(village, street);
CREATE INDEX IF NOT EXISTS idx_locations_full ON locations(seniūnija, village, street);
CREATE INDEX IF NOT EXISTS idx_schedule_groups_dates ON schedule_groups(first_date, last_date, date_count);
