# Waste Schedule System

A system for scraping, storing, and displaying waste pickup schedules from `nemenkom.lt` (Nemenčinės komunalininkas, Lithuania).

## Why this exists

I’m trying to make waste pickup calendars **usable for day‑to‑day life** — by turning the schedules from `nemenkom.lt`
into something you can subscribe to (Google Calendar) and then stop thinking about.

It’s an **unofficial** community project and it may be done in a **very, very, very wrong way** 


## License

Licensed under the **PolyForm Noncommercial License 1.0.0** (source-available, non-commercial).
Commercial use requires permission. See `LICENSE`.

## Quick Start

https://nemenkom.eidmantas.lt

## This Project

### Docker/Podman (Recommended)

**Microservice Architecture:**

- `web` service: Flask API and web interface (port 3333)
- `scraper` service: Scheduled scraper (runs at 11:00 and 18:00 daily)
- `calendar` service: Calendar creation + event sync worker

**Using Makefile (recommended):**

```bash
make up              # Start all services
make down            # Stop services
make restart         # Restart services
make build           # Build images
make clean           # Stop and remove containers/images
make clean-podman    # Clean all podman containers/images
make clean-all       # Full cleanup (podman + database)
make clean-calendars-dry-run # Check for orphaned calendars (dry run)
make clean-calendars # Delete orphaned calendars (requires confirmation)
make db-reset        # Delete database file
```

**Testing (Makefile):**

```bash
make test     # Unit + integration tests (skips AI Agent + Google Calendar API)
make test-ai  # AI Agent tests only (uses tokens)
make test-calendar # Google Calendar API tests only
make test-all # Tests including AI Agent (skips Google Calendar API)
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

For local development, `docker-compose.override.yaml` is automatically used (if it exists) to override the external Caddy network with a local default network. On RPI/production, the external Caddy network will be used from `docker-compose.yaml`.

**Important:** Before running, ensure you have:

- Set up secrets in `secrets/` directory (see [INSTALL.md](INSTALL.md))
- Created `config.py` from `config.example.py` (config is mounted as volume, not baked into image)

Web server: **http://localhost:3333**

The database is stored in `./services/database/` and persists between restarts. The scraper automatically updates it twice daily.

### Option 2: Manual Setup

```bash
# Create virtual environment and install dependencies
make venv-install  # Or: python3 -m venv venv && venv/bin/pip install -r requirements.txt

# Activate venv (optional - make commands use venv automatically)
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Initialize database
python services/database/init.py
```

### Pre-commit (Optional)

```bash
pip install -r requirements-dev.txt
pre-commit install
```

Or (recommended), using the project venv + Makefile:

```bash
make pre-commit-install
```

This runs before each commit:

- **Gitleaks** - blocks secrets from entering git history
- **Ruff** - linting and formatting
- **Prettier** - formats markdown/yaml/json
- **Pyright** - type checking
- **pip-audit** - security vulnerabilities

### Run Scraper

```bash
# Simple subset only (traditional parser, no AI needed)
python services/scraper/main.py --simple-subset

# Full parsing (traditional + AI parser) - processes all entries
python services/scraper/main.py
```

### Run PDF Scraper (MVP)

```bash
# Default: AI disabled (no token usage)
python services/scraper_pdf/main.py /path/to/file.pdf

# Enable AI parsing explicitly
python services/scraper_pdf/main.py /path/to/file.pdf --use-ai

# Production-style: download from URL and skip re-parse if the PDF content hash is unchanged
python services/scraper_pdf/main.py --url 'https://example.com/plastic.pdf' --use-ai

# Shortcut (uses config.PDF_PLASTIKAS_URL / config.PDF_STIKLAS_URL)
python services/scraper_pdf/main.py --source plastikas --use-ai
python services/scraper_pdf/main.py --source stiklas --use-ai
```

Outputs:
- `*.rows.csv` — row-level normalized output before splitting/AI (phase 1)
- `*.parsed.csv` — split output (village/street rows)
- `*.raw.csv` — raw marker-pdf rows for debugging

Marker cache:
- Cached HTML under `tmp/marker_cache` (override with `MARKER_CACHE_DIR`)
- Clear cache with `--clear-marker-cache`

Note: `marker-pdf==1.10.1` currently declares `openai<2.0.0`. We pin `openai>=2.16.0`
for other components, so pip may warn about a dependency conflict. This does not affect
PDF table extraction, but keep it in mind if installing dependencies strictly.

### Run Web Server

```bash
python services/api/app.py
```

Server runs on **http://localhost:3333**

### Run Calendar Worker

```bash
python services/calendar/worker.py
```

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

## Security

Repository scanned for secrets before going public (January 30, 2026) using [Gitleaks](https://github.com/gitleaks/gitleaks) and [TruffleHog](https://github.com/trufflesecurity/trufflehog). All 8 branches, 56 commits — no secrets found.

GitHub Actions run Gitleaks, Ruff, Pyright, and pip-audit on every push.
