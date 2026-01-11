# Waste Schedule System Architecture

## System Overview

A modular system for fetching, storing, and displaying waste pickup schedules from nemenkom.lt for multiple streets/villages.

## Architecture Components

### 1. Data Scraper Module (`scraper/`)

- **Purpose**: Daily fetch of xlsx schedule from nemenkom.lt
- **Files**:
  - `scraper/fetcher.py` - Downloads xlsx from URL (direct link for now, web scraping later)
  - `scraper/parser.py` - Parses xlsx and extracts all street/village combos with dates
  - `scraper/validator.py` - Validates data structure and format
  - `scraper/db_writer.py` - Writes validated data to SQLite
- **Database Schema** (SQLite):
  - `locations` table: `id`, `village`, `street`, `schedule_group_id` (for grouping same schedules)
  - `pickup_dates` table: `id`, `location_id`, `date`, `waste_type` (default: 'bendros')
  - `data_fetches` table: `id`, `fetch_date`, `source_url`, `status`, `validation_errors`

### 2. API Module (`api/`)

- **Purpose**: REST API for data ingestion and public queries
- **Files**:
  - `api/app.py` - Flask application with routes
  - `api/db.py` - Database connection and queries
- **Endpoints**:
  - `POST /api/v1/data` - Accept scraped data from fetcher (internal)
  - `GET /api/v1/locations` - List all street/village combos
  - `GET /api/v1/schedule?street=X&village=Y` - Get schedule for specific location
  - `GET /api/v1/schedule-group/:id` - Get schedule for a schedule group

### 3. Web Interface (`web/`)

- **Purpose**: User-facing website for viewing schedules
- **Files**:
  - `web/templates/index.html` - Main page with street/village selector and calendar view
  - `web/static/css/style.css` - Styling
  - `web/static/js/calendar.js` - Calendar rendering logic
- **Features**:
  - Dropdown/table to select street/village combo
  - Calendar view showing pickup dates
  - Responsive design

### 4. Calendar Generator (`calendar/`)

- **Purpose**: Generate Google Calendar events for all locations
- **Files**:
  - `calendar/generator.py` - Reads from DB and creates calendar events
  - `calendar/google_calendar.py` - Google Calendar API integration (refactored from existing)
- **API Endpoint**:
  - `POST /api/v1/generate-calendars` - Generate calendars for all schedule groups

### 5. Database (`database/`)

- **File**: `database/schema.sql` - SQLite schema definition
- **File**: `database/init.py` - Database initialization script

## Data Flow

```
Scraper (daily cron) → Validator → SQLite DB → API → Web Interface
                                              ↓
                                         Calendar Generator
```

## Module Dependencies

- `scraper/` → `database/` (writes data)
- `api/` → `database/` (reads data)
- `web/` → `api/` (via HTTP requests or shared Flask app)
- `calendar/` → `database/` (reads data), `google_calendar.py` (creates events)

## Key Design Decisions

1. **SQLite for simplicity**: Single-file database, easy to backup and deploy
2. **Schedule groups**: Multiple streets can share the same schedule (reduces calendar generation)
3. **Validation layer**: Separate validator to catch xlsx format changes early
4. **Modular structure**: Each component can be developed/tested independently
5. **Lithuanian-first**: All UI text in Lithuanian, multi-language support later

## File Structure

```
nemenkom/
├── scraper/
│   ├── __init__.py
│   ├── fetcher.py
│   ├── parser.py
│   ├── validator.py
│   └── db_writer.py
├── api/
│   ├── __init__.py
│   ├── app.py
│   └── db.py
├── web/
│   ├── templates/
│   │   └── index.html
│   └── static/
│       ├── css/
│       │   └── style.css
│       └── js/
│           └── calendar.js
├── calendar/
│   ├── __init__.py
│   ├── generator.py
│   └── google_calendar.py
├── database/
│   ├── schema.sql
│   ├── init.py
│   └── waste_schedule.db (generated)
├── main.py (legacy - to be deprecated)
├── api-test.py (legacy - to be deprecated)
├── google_calendar.py (legacy - move to calendar/)
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
└── architecture.md
```

## Implementation Phases

1. **Phase 1**: Database schema + scraper module (fetcher, parser, validator, db_writer)
2. **Phase 2**: API module (POST/GET endpoints)
3. **Phase 3**: Web interface (Flask templates with calendar)
4. **Phase 4**: Calendar generator (batch generation for all locations)
5. **Phase 5**: Web scraping for dynamic URL discovery (V1.1)

## Data Validation Strategy

- Check required columns exist in xlsx
- Validate date formats and ranges
- Ensure street/village names are non-empty
- Log validation errors to `data_fetches` table
- Alert on format changes (future: email/notification)