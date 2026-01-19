# Waste Schedule System

A system for scraping, storing, and displaying waste pickup schedules from `nemenkom.lt` (Nemenčinė municipality, Lithuania).

## Features

- **XLSX Scraper**: Downloads and parses waste schedule spreadsheets
- **Hybrid Parser**: Traditional regex parser + AI (Groq) for complex location patterns
- **SQLite Database**: Efficient storage with hash-based schedule grouping
- **REST API**: Flask-based API for data access
- **Web Interface**: User-friendly interface for viewing schedules
- **Google Calendar Integration**: (Planned) Generate calendar events

## Quick Start

### Docker/Podman (Recommended)

**Microservice Architecture:**
- `web` service: Flask API and web interface (port 3333)
- `scraper` service: Scheduled scraper (runs at 11:00 and 18:00 daily)

**Using Makefile (recommended):**
```bash
make up      # Start all services
make down    # Stop services
make restart # Restart services
make build   # Build images
make clean   # Stop and remove everything
make test    # Run tests (automatically uses venv)
```

**Or directly with podman-compose:**
```bash
# Start all services
podman-compose up -d

# View logs (all services)
podman-compose logs -f

# View logs (specific service)
podman-compose logs -f scraper
podman-compose logs -f web

# Stop all services
podman-compose down
```

**Note:** For local development, `docker-compose.override.yaml` is automatically used (if it exists) to override the external Caddy network with a local default network. On RPI/production, the external Caddy network will be used from `docker-compose.yaml`.

Web server: **http://localhost:3333**

The database is stored in `./database/` and persists between restarts. The scraper automatically updates it twice daily.

### Option 2: Manual Setup

```bash
# Create virtual environment and install dependencies
make venv-install  # Or: python3 -m venv venv && venv/bin/pip install -r requirements.txt

# Activate venv (optional - make commands use venv automatically)
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Initialize database
python database/init.py
```

### Run Scraper

```bash
# Simple subset only (traditional parser, no AI needed)
python scraper/main.py --simple-subset

# Full parsing (traditional + AI parser) - processes all entries
python scraper/main.py
```

### Run Web Server

```bash
python api/app.py
```

Server runs on **http://localhost:3333**

## API Testing

### List All Locations
```bash
curl http://localhost:3333/api/v1/locations
```

### Search Locations
```bash
curl "http://localhost:3333/api/v1/locations?q=Aleksandravas"
```

### Get Schedule for Location
```bash
curl "http://localhost:3333/api/v1/schedule?location_id=1"
```

### Get Schedule Group Info
```bash
curl "http://localhost:3333/api/v1/schedule-group/sg_f5f4eff319af?waste_type=bendros"
```

## Website Design

### Current Structure

```
┌─────────────────────────────────────────┐
│  Buitinių atliekų surinkimo grafikas    │
│  Cascading Selection + Calendar View     │
├──────────────────┬──────────────────────┤
│  Selection UI     │   Kalendorius        │
│  (Left Panel)    │   (Right Panel)      │
│                   │                      │
│  [Village Search] │   [Selected Location]│
│  [Street Search]  │   [Calendar View]    │
│  [House # Search]│   [Pickup Dates]     │
└──────────────────┴──────────────────────┘
```

### Features
- **Searchable Dropdowns**: Type to search villages, streets, and house numbers
  - Partial matching: Type "Riese" to find "Riešė"
  - Lithuanian character normalization: Works with or without Lithuanian letters (š, ž, ą, etc.)
  - Scrollable lists: Browse all options when focused
  - Keyboard support: Enter to select first match
- **Cascading Selection**: Village → Street → House Number
  - Auto-populating: Select village → streets filter → house numbers filter
  - Smart validation: Requires street/house numbers only when they exist
  - "Visiems" (All) option when no specific house numbers exist
- **Calendar View**: Displays pickup dates for selected location
- **Responsive**: Basic responsive design (mobile improvements planned)

### Future Enhancements
- Google Calendar export button
- Multi-waste-type selection (general, plastic, glass)
- Improved mobile UI

## Project Structure

```
nemenkom/
├── scraper/          # Data scraping and parsing
│   ├── fetcher.py    # Download XLSX from URL
│   ├── parser.py     # Parse XLSX (traditional + AI router)
│   ├── parser_router.py  # Decide traditional vs AI parsing
│   ├── validator.py  # Validate data structure
│   ├── db_writer.py  # Write to SQLite
│   └── main.py       # CLI entry point
├── api/              # Flask REST API
│   ├── app.py        # Flask application
│   └── db.py         # Database queries
├── web/              # Web interface
│   ├── templates/    # HTML templates
│   └── static/       # CSS, JS
├── database/         # Database schema and init
│   ├── schema.sql    # SQLite schema
│   └── init.py       # Database initialization
└── documentation/    # Project documentation
```

## Database Schema

### Key Tables

- **`schedule_groups`**: Hash-based groups with JSON dates and kaimai_hashes
- **`locations`**: Village/street combinations with kaimai_hash
- **`data_fetches`**: Track scraping runs

See `database/schema.sql` for full schema.

## Next Steps

### 1. Implement AI Parser (Groq) ✅ **COMPLETE**
- ✅ Created `scraper/ai/parser.py` with Groq API integration
- ✅ Integrates Groq API for complex "Kaimai" patterns
- ✅ Rate limiting (`scraper/ai/rate_limiter.py`) - respects 15 RPM, 14,400 RPD free tier
- ✅ Caching (`scraper/ai/cache.py`) - SQLite-based, avoids re-parsing
- ✅ Full validation and error handling
- ✅ Updated `parser.py` to use AI parser via router
- ✅ Test coverage: 59 tests (including 5 AI integration tests with real API calls)

### 2. Add Scraper Service to Docker Compose ✅
- ✅ Separate service with dedicated Dockerfile.scraper
- ✅ Runs at 11:00 and 18:00 daily via cron
- ✅ Microservice architecture: web + scraper services

### 3. Google Calendar Integration
- Refactor `google_calendar.py`
- Add API endpoint: `POST /api/v1/generate-calendars`
- Generate events per schedule group

### 4. Multi-Waste-Type Support
- Handle separate XLSX files for plastic, glass waste
- Update parser to accept `waste_type` parameter
- Update API to filter by waste type

### 5. Enhanced Web Interface (House Numbers Support)
- **Cascading Selection**: Village → Street → House Number
  - Step 1: Select City/Village (dropdown)
  - Step 2: Select Street (filtered by selected village, auto-populated)
  - Step 3: Select House Number (filtered by selected street, auto-populated)
  - Show "Visiems" (All) option when no specific house numbers exist
- Update API to support filtering by house numbers
- Update database queries to handle house number filtering

### 6. Testing & Deployment
- Test AI parser with full dataset
- Verify date accuracy across all locations
- Production deployment

## Documentation

- **`documentation/ARCHITECTURE.md`** - System architecture and design
- **`documentation/HYBRID_PARSER.md`** - Hybrid parser implementation (traditional + AI)
- **`documentation/AI-AGENT.md`** - Full context for AI agents (for continuation)
- **`documentation/DECISION_SCHEDULE_GROUPS.md`** - Database schema decisions
- **`documentation/TESTING.md`** - Testing strategy and setup
- **`documentation/AI_COST_ANALYSIS.md`** - Historical: AI options analysis (we chose Groq)

## Development Notes

### Current Status
- ✅ Database schema implemented (hash-based IDs, JSON dates)
- ✅ Traditional parser working (simple patterns)
- ✅ Parser router implemented
- ✅ AI parser implemented (Groq LLM integration)
  - Automatic routing for complex patterns
  - Caching and rate limiting
  - Full validation and error handling
- ✅ API and web interface functional
- ✅ Seniūnija support: API returns separate seniūnija/village keys, handles duplicate village names
- ✅ House number normalization: Compact format (spaces removed, ranges normalized)
- 🚧 Google Calendar integration
- 🚧 Multi-waste-type support

### Testing
- Comprehensive test suite: 59 tests (parser, router, AI parser, API, E2E)
  - 54 regular tests (`make test`) - unit, integration, E2E tests (no AI tokens used)
  - 5 AI integration tests (`make test-ai`) - make real Groq API calls, test current code
  - **Note:** `make test` skips AI integration tests by default (they require `--use-ai-tokens` flag)
  - All tests automatically use venv (no manual activation needed)
- Use `--simple-subset` flag to test traditional parser only (skips AI-needed entries)
- Without flag: Full hybrid parsing (traditional + AI parser)
- Database currently has 900 locations, 10 schedule groups (simple subset)
- Verify dates match XLSX source data

