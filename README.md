# Waste Schedule System

Unofficial `nemenkom.lt` waste calendar project for Nemenčinė region.

The goal is simple: turn provider schedules into something people can actually subscribe to and
trust, instead of manually re-checking PDFs and spreadsheets every few months.

Public instance: https://nemenkom.eidmantas.lt

## Current Release Track

Current branch work targets `1.1.0-rc1`.

The important change in this release is quarter-to-quarter PDF continuity:

- existing plastic/glass Google calendars keep the same `calendar_id`
- raw PDF wording drift no longer creates accidental duplicate calendars
- real new villages / streets / house-number buckets still create new groups safely
- calendar descriptions now refresh automatically with scope and change notes

See:

- [documentation/v1-1-continuity.md](documentation/v1-1-continuity.md)
- [services/ARCHITECTURE.md](services/ARCHITECTURE.md)
- [documentation/TESTING.md](documentation/TESTING.md)

## Service Layout

- `services/scraper`: XLSX ingestion for general waste
- `services/scraper_pdf`: PDF ingestion for plastic and glass
- `services/api` + `services/web`: read API and website
- `services/calendar`: Google Calendar creation and sync worker
- `services/database`: active SQLite database used by the app

Important: the app uses `services/database/waste_schedule.db`.
The root `waste_schedule.db` is only a manual snapshot / migration helper when we explicitly use it.

## Quick Start

### Docker / Podman

```bash
make build
make up
```

Useful commands:

```bash
make up
make down
make restart
make test
make test-ai
make test-calendar
```

Web UI: `http://localhost:3333`

### Local Development

```bash
make venv-install
source venv/bin/activate
python services/database/init.py
python services/api/app.py
```

In separate shells:

```bash
source venv/bin/activate
python services/scraper/main.py --force
python services/scraper_pdf/main.py --source plastikas --force
python services/scraper_pdf/main.py --source stiklas --force
python services/calendar/worker.py
```

## Configuration and Secrets

- Copy `config.example.py` to `config.py`.
- Put local secrets into `secrets/`.
- `secrets/` is ignored by git by default; only `.example` templates and `.gitkeep` stay tracked.

Setup details live in [INSTALL.md](INSTALL.md).

## Main Operational Flows

### XLSX refresh

```bash
python services/scraper/main.py --force
```

Use this when the general-waste spreadsheet changed or when you want to rebuild from source.

### PDF refresh

```bash
python services/scraper_pdf/main.py --source plastikas --force
python services/scraper_pdf/main.py --source stiklas --force
```

The PDF flow uses:

- marker-pdf for table extraction
- AI providers for complex location splitting
- canonical continuity matching to preserve old schedule groups and calendars when safe

### Calendar sync

```bash
python services/calendar/worker.py
```

The worker creates new Google calendars when needed and updates existing ones in place when
`calendar_synced_at` is cleared by a data refresh.

## Docs Map

- [INSTALL.md](INSTALL.md): setup, secrets, local and container runbook
- [RELEASE.md](RELEASE.md): deployment checklist for `1.1.0-rc1`
- [services/ARCHITECTURE.md](services/ARCHITECTURE.md): current service and data-flow model
- [documentation/v1-1-continuity.md](documentation/v1-1-continuity.md): PDF continuity design and Q2 verification
- [documentation/TESTING.md](documentation/TESTING.md): test strategy and focused regression commands
- [CHANGELOG.md](CHANGELOG.md): release history

## Security

- `config.py` is local-only and ignored by git.
- `secrets/` is ignored by git.
- Pre-commit and CI can run Gitleaks to block accidental secret commits.

## License

Licensed under the **PolyForm Noncommercial License 1.0.0**.
Commercial use requires permission. See `LICENSE`.
