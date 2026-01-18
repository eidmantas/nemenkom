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
  - `schedule_groups` table: `id` (hash-based), `waste_type`, `dates` (JSON), `kaimai_hashes` (JSON)
  - `locations` table: `id`, `village`, `street`, `kaimai_hash` (no FK - query by hash match)
  - `data_fetches` table: `id`, `fetch_date`, `source_url`, `status`, `validation_errors`
  - **Note**: No `pickup_dates` table - dates stored in `schedule_groups.dates` JSON (eliminates 95% duplication)

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
  - `web/templates/index.html` - Main page with cascading searchable selectors and calendar view
  - `web/static/css/style.css` - Styling
  - `web/static/js/calendar.js` - Calendar rendering logic
- **Features**:
  - **Searchable Dropdowns**: Type-to-search with partial matching and Lithuanian character normalization
  - **Cascading Selection**: Village → Street → House Number with smart validation
  - **Calendar View**: Displays pickup dates for selected location
  - **Responsive Design**: Basic responsive layout

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
└── documentation/
    ├── ARCHITECTURE.md
    ├── HYBRID_PARSER.md
    └── AI_COST_ANALYSIS.md
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

## Parsing Strategy Options

### Option 1: Raw Data Storage (Future/Backup)
- Store full `Kaimai` column content as-is in database
- Use distributed SQL table logic to prevent bugs
- Parse on-demand or incrementally
- **Status**: Documented, not implemented

### Option 2: Hybrid Parser (Current Implementation)
- **Traditional parser**: Handles simple cases (village names, standard street lists)
- **AI parser (Groq)**: Handles complex cases (house numbers, missing commas, nested structures)
- **Decision logic**: `should_use_ai_parser()` function determines which parser to use
- **Cost**: Free tier Groq API (30 RPM, 14,400 RPD) - sufficient for ~700 rows/day
- **See**: `documentation/HYBRID_PARSER.md` for parsing examples and implementation details

## Option 2: Hybrid Parser Architecture & Wireframes

### Data Flow Diagram

```
┌─────────────┐
│   xlsx      │
│   File      │
└──────┬──────┘
       │
       ▼
┌─────────────────────────────────────┐
│      Parser Router                  │
│  (should_use_ai_parser?)            │
└──────┬───────────────────┬─────────┘
       │                   │
       │ Simple            │ Complex
       │ (80%)             │ (20%)
       ▼                   ▼
┌──────────────┐    ┌──────────────┐
│ Traditional  │    │  AI Parser   │
│   Parser     │    │   (Groq)     │
│              │    │              │
│ - Regex      │    │ - LLM API    │
│ - Rules      │    │ - JSON parse │
└──────┬───────┘    └──────┬───────┘
       │                   │
       └─────────┬─────────┘
                 │
                 ▼
        ┌─────────────────────────────┐
        │   Parsed Location Object    │
        │                             │
        │ - seniūnija: str           │
        │ - village: str             │
        │ - street: str              │
        │ - house_numbers: str|null  │
        │ - dates: date[] (from schedule_group) │
        │   (from xlsx month cols)   │
        └────────┬────────────────────┘
                 │
                 ▼
        ┌─────────────────────────────────────┐
        │   SQLite Database (waste_schedule)  │
        │                                     │
        │ locations (id, seniūnija, village, │
        │            street, house_numbers,   │
        │            kaimai_hash)            │
        │                                     │
        │ schedule_groups (id TEXT,          │
        │                  waste_type,       │
        │                  dates JSON,       │
        │                  kaimai_hashes JSON)│
        └─────────────────────────────────────┘
```

### Parser Router Decision Flow

```
Input: "Kaimai" column string
       │
       ▼
┌──────────────────────────────┐
│ Check for complex patterns:  │
│                              │
│ ✓ House numbers?             │
│   - nuo...iki                │
│   - Nr. X                    │
│   - X-Y (hyphenated)         │
│   - Numbers after street     │
│                              │
│ ✓ Missing commas?            │
│                              │
│ ✓ Streets outside parens?    │
│                              │
│ ✓ Nested structures?        │
└──────┬───────────────────────┘
       │
       ├─ No  → Traditional Parser
       │        (Fast, reliable)
       │
       └─ Yes → AI Parser (Groq)
                (Handles complexity)
```

### Output Structure (Option 2)

The hybrid parser generates structured location data:

```json
{
  "seniūnija": "Avižienių",
  "village": "Pikutiškės",
  "street": "Sudervės g.",
  "house_numbers": "26, 28",
  "dates": ["2026-01-02", "2026-01-16", "2026-01-30", ...]  // from schedule_groups.dates JSON
}
```

**Note**: `dates` are extracted from the xlsx month columns (Sausio, Vasario, etc.) and stored in `schedule_groups.dates` JSON (shared by all locations in same group).

**Database schema**:
- `locations` table: 
  - Columns: `id`, `seniūnija`, `village`, `street`, `house_numbers`, `schedule_group_id`
  - One row per unique (seniūnija, village, street, house_numbers) combination
- `schedule_groups` table (dates stored as JSON):
  - Columns: `id`, `location_id`, `date`, `waste_type`
  - One row per pickup date for each location
- `schedule_groups` table:
  - Columns: `id`, `first_date`, `last_date`, `date_count`
  - Groups locations with identical pickup date schedules

### Location Hierarchy (Option 2 Output)

```
Seniūnija (County)
  └── Village/City
        └── Street
              └── House Numbers (optional)
                    └── Pickup Dates
```

**Example database records**:

`locations` table:
```
id | seniūnija  | village     | street          | house_numbers | schedule_group_id
1  | Avižienių  | Pikutiškės  | Sudervės g.    | 26, 28       | 1
2  | Avižienių  | Pikutiškės  | Braškių g.     | NULL         | 1
3  | Avižienių  | Pikutiškės  | Kalvių 1-oji g.| NULL         | 1
4  | Avižienių  | Pikutiškės  | Kalvių 2-oji g.| NULL         | 1
...
```

`schedule_groups` table (dates stored as JSON, shared by all locations in group):
```
id | location_id | date       | waste_type
1  | 1           | 2026-01-02 | bendros
2  | 1           | 2026-01-16 | bendros
3  | 1           | 2026-01-30 | bendros
...
```

This structure allows:
- Users to search by village, street, or house number
- Filtering by specific house numbers
- Grouping locations with same schedules
- Generating calendars per location