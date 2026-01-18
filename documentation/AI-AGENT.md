# AI Agent Context Dump

This document contains the full context of the project for AI agents to continue development.

## Project Overview

**Waste Schedule System** - A system for scraping, storing, and displaying waste pickup schedules from `nemenkom.lt` (Nemenčinė municipality, Lithuania). The system handles inconsistent, human-written location data in the "Kaimai" column and provides a web interface with Google Calendar integration.

## Current Status

### ✅ Completed
- **Database Schema**: Hash-based `schedule_groups` with JSON dates, `locations` with `kaimai_hash`
- **Traditional Parser**: Handles simple village/street patterns
- **Parser Router**: Logic to decide between traditional and AI parsing (detects streets without parentheses)
- **API**: Flask REST API with endpoints for locations and schedules, smart validation (requires street/house_numbers when they exist)
- **Web Interface**: Searchable dropdowns with Lithuanian character normalization, cascading selection (Village → Street → House Number)
- **Database**: SQLite with 900 locations, 10 schedule groups (simple subset only)
- **Testing**: Comprehensive test suite (29 tests) covering parser, router, API endpoints, and E2E flows

### 🚧 In Progress / Next Steps
- **AI Parser**: Groq LLM integration for complex "Kaimai" patterns
- **Google Calendar Integration**: Generate calendar events per schedule group
- **Multi-Waste-Type Support**: Handle plastic, glass waste types (separate XLSX files)

## Architecture

### Components

1. **Scraper** (`scraper/`)
   - `fetcher.py` - Downloads XLSX from URL
   - `parser.py` - Parses XLSX, extracts locations and dates
   - `parser_router.py` - Decides traditional vs AI parsing
   - `validator.py` - Validates data structure
   - `db_writer.py` - Writes to SQLite with hash-based grouping
   - `main.py` - CLI entry point with `--simple-subset` flag

2. **API** (`api/`)
   - `app.py` - Flask application
   - `db.py` - Database queries (uses JSON functions for schedule_groups)

3. **Web** (`web/`)
   - `templates/index.html` - Main page
   - `static/css/style.css` - Styling
   - `static/js/calendar.js` - Calendar rendering

4. **Database** (`database/`)
   - `schema.sql` - SQLite schema
   - `init.py` - Database initialization

### Database Schema

```sql
-- Schedule groups (per waste type, with dates in JSON)
CREATE TABLE schedule_groups (
    id TEXT PRIMARY KEY,  -- Hash: "sg_{hash}" (hash of waste_type + sorted_dates)
    waste_type TEXT NOT NULL DEFAULT 'bendros',
    first_date DATE,
    last_date DATE,
    date_count INTEGER,
    dates TEXT,  -- JSON array: '["2026-01-08", "2026-01-22", ...]'
    kaimai_hashes TEXT,  -- JSON array: '["k1_abc123", "k1_def456", ...]'
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Locations (no FKs - query schedule_groups by kaimai_hash match)
CREATE TABLE locations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    seniūnija TEXT NOT NULL,
    village TEXT NOT NULL,
    street TEXT NOT NULL,
    house_numbers TEXT,
    kaimai_hash TEXT NOT NULL,  -- Hash of original Kaimai column
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(seniūnija, village, street, house_numbers)
);

-- Data fetches (tracking)
CREATE TABLE data_fetches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fetch_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    source_url TEXT NOT NULL,
    status TEXT NOT NULL,
    validation_errors TEXT
);
```

**Key Design Decisions:**
- No `pickup_dates` table - dates stored in `schedule_groups.dates` JSON (eliminates 95% duplication)
- Hash-based `schedule_group_id` for deterministic grouping
- `kaimai_hash` in `locations` for linking to `schedule_groups` via JSON match
- SQLite JSON functions (`json_each()`, `json_extract()`) for queries

## The "Kaimai" Parsing Challenge

The "Kaimai" column in the XLSX is **highly inconsistent** - human-written with no standard format:

### Simple Patterns (Traditional Parser)
- `"Aleksandravas"` - Simple village
- `"Aukštadvaris"` - Simple village
- `"Avižieniai (Akacijų aklg., Avižų g., ...)"` - Village with streets in parentheses

### Complex Patterns (AI Parser Needed)
- `"Pikutiškės (Braškių g., Kalvių 1-oji, 2-oji, 3-oji, 4-oji, 5-oji g., Sudervės g. 26, 28, Žolynų g.)"`
  - Mix of ordinal street names ("1-oji g.") and explicit house numbers ("26, 28")
- `"Bendoriai (..., Žemaitukų 1-oji g., ...)"` - Ordinal street names
- House number ranges: `"nuo 18 iki 18U"` (from 18 to 18U, inclusive)
- Hyphenated ranges: `"18-18U"` (18, 18A, 18B, ..., 18U)

### Parser Router Logic

`scraper/parser_router.py` - `should_use_ai_parser(kaimai_str: str) -> bool`:
- Returns `True` if:
  - Has house numbers (regex patterns for "nuo...iki", "Nr.", numbers after street)
  - Has missing commas (complex nested structures)
  - Has streets outside parentheses (when parentheses exist)

## Implementation Plan (Hybrid Parser - Option 2)

### Phase 1: Traditional Parser ✅
- Handles simple patterns
- `--simple-subset` flag for testing

### Phase 2: AI Parser (Next)
- **Groq API** integration (`scraper/ai_parser.py`)
- **Rate Limiting**: 30 RPM, 14,400 RPD (free tier)
- **Batching**: Group complex entries, process in batches
- **Error Handling**: Fallback to traditional parser if AI fails

### Phase 3: Full Integration
- Update `parser.py` to use router → AI parser
- Test with full dataset
- Deploy

## API Endpoints

- `GET /` - Web interface
- `GET /api/v1/locations?q=<query>` - Search locations
- `GET /api/v1/schedule?location_id=<id>` - Get schedule for location
- `GET /api/v1/schedule-group/<id>?waste_type=<type>` - Get schedule group info
- `POST /api/v1/data` - Accept scraped data (internal)

## Running the System

### Setup
```bash
# Create virtual environment
python3 -m venv venv
source venv/bin/activate  # or `venv\Scripts\activate` on Windows

# Install dependencies
pip install -r requirements.txt

# Initialize database
python database/init.py
```

### Run Scraper
```bash
# Simple subset only (traditional parser)
python scraper/main.py --simple-subset

# Full parsing (when AI parser is ready)
python scraper/main.py
```

### Run API/Web Server
```bash
python api/app.py
# Server runs on http://localhost:3333
```

### Test API
```bash
# List locations
curl http://localhost:3333/api/v1/locations

# Search
curl "http://localhost:3333/api/v1/locations?q=Aleksandravas"

# Get schedule
curl "http://localhost:3333/api/v1/schedule?location_id=1"
```

## Website Design

### Current Structure
- **Left Panel**: List of locations (searchable)
- **Right Panel**: Calendar view (shows dates when location selected)
- **Features**: Search, location selection, date display

### Future Enhancements
- Google Calendar export button
- Multi-waste-type selection
- Address input with autocomplete
- Mobile-responsive improvements

## Next Steps

1. **Implement AI Parser** (`scraper/ai_parser.py`)
   - Groq API client
   - Prompt engineering for Lithuanian location parsing
   - Rate limiting and batching
   - Error handling

2. **Google Calendar Integration**
   - Use existing `google_calendar.py` (needs refactoring)
   - Generate events per schedule group
   - API endpoint: `POST /api/v1/generate-calendars`

3. **Multi-Waste-Type Support**
   - Handle separate XLSX files for plastic, glass
   - Update parser to accept `waste_type` parameter
   - Update API to filter by waste type

4. **Testing**
   - Test AI parser with complex patterns
   - Verify date accuracy across all locations
   - Test Google Calendar generation

## Key Files Reference

- **Schema**: `database/schema.sql`
- **Parser Router**: `scraper/parser_router.py`
- **DB Writer**: `scraper/db_writer.py` (hash generation, schedule grouping)
- **API DB**: `api/db.py` (JSON queries for schedule_groups)
- **Documentation**: `documentation/` folder

## Important Notes

- **Lithuanian Language**: All location data is in Lithuanian
- **Date Format**: ISO format (YYYY-MM-DD) in database
- **Hash Format**: `k1_{12-char-hex}` for kaimai_hash, `sg_{12-char-hex}` for schedule_group_id
- **Waste Types**: 'bendros' (general), 'plastikas' (plastic), 'stiklas' (glass)
- **Current Data**: 900 locations, 10 schedule groups (simple subset only)

## Cost Considerations

- **Groq Free Tier**: 30 RPM, 14,400 RPD
- **Estimated Usage**: ~700 rows/day (some need AI parsing)
- **Strategy**: Batch processing, rate limiting, fallback to traditional parser
