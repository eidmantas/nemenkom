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
make test    # Run tests locally
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

Web server: **http://localhost:3333**

The database is stored in `./database/` and persists between restarts. The scraper automatically updates it twice daily.

### Option 2: Manual Setup

```bash
# Create virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Initialize database
python database/init.py
```

### Run Scraper

```bash
# Simple subset only (traditional parser, no AI needed)
python scraper/main.py --simple-subset

# Full parsing (when AI parser is implemented)
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
│  [Search: Ieškoti gatvės ar kaimo...]  │
├──────────────────┬──────────────────────┤
│  Gatvės ir kaimai │   Kalendorius        │
│  (Left Panel)     │   (Right Panel)      │
│                   │                      │
│  • Aleksandravas  │   [Selected Location]│
│  • Aukštadvaris   │   [Calendar View]    │
│  • ...            │   [Pickup Dates]     │
└──────────────────┴──────────────────────┘
```

### Features
- **Search**: Filter locations by village/street name
- **Location List**: Click to select and view schedule
- **Calendar View**: Displays pickup dates for selected location
- **Responsive**: Basic responsive design (mobile improvements planned)

### Future Enhancements
- **Cascading Selection UI**: Village → Street → House Number (when house numbers are in DB)
  - Auto-populating dropdowns: Select village → streets filter → house numbers filter
  - "Visiems" (All) option when no specific house numbers exist
- Google Calendar export button
- Multi-waste-type selection (general, plastic, glass)
- Address input with autocomplete
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

### 1. Implement AI Parser (Groq)
- Create `scraper/ai_parser.py`
- Integrate Groq API for complex "Kaimai" patterns
- Add rate limiting (30 RPM, 14,400 RPD free tier)
- Update `parser.py` to use AI parser via router

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
- **`documentation/HYBRID_PARSER.md`** - Parser implementation details
- **`documentation/AI_COST_ANALYSIS.md`** - AI options cost analysis
- **`documentation/DECISION_SCHEDULE_GROUPS.md`** - Database schema decisions
- **`documentation/AI-AGENT.md`** - Full context for AI agents

## Development Notes

### Current Status
- ✅ Database schema implemented (hash-based IDs, JSON dates)
- ✅ Traditional parser working (simple patterns)
- ✅ Parser router implemented
- ✅ API and web interface functional
- 🚧 AI parser (next step)
- 🚧 Google Calendar integration
- 🚧 Multi-waste-type support

### Testing
- Use `--simple-subset` flag to test traditional parser only
- Database currently has 900 locations, 10 schedule groups (simple subset)
- Verify dates match XLSX source data

