# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]
- PDF scraper (`services/scraper_pdf`) remains in development (prototype/MVP).
- TODO: Expand house numbers into per-address ranges/sets to enable cross-waste-type calendar matching.
- TODO: De-duplicate PDF/XLSX parsing helpers into a shared module once stable.

## [0.1.2a] - 2026-01-28
### Added
- Calendar streams (`calendar_streams`) and links (`group_calendar_links`) for shared date-based calendars.
- Stream-level event tracking via `calendar_stream_events`.
- Calendar deprecation notices and pending cleanup workflow for outdated calendars.
- UX-focused calendar stability test covering subscription behavior on date changes.
- PDF scraper prototype under `services/scraper_pdf` using `camelot` (in development).
- `camelot-py[cv]>=0.11.0` in `requirements.txt` and PDF parsing MVP output files.

### Changed
- Calendar worker now creates/syncs calendars per date stream, not per location group.
- Scraper now links schedule groups to date-based calendar streams.
- API calendar metadata now resolves through calendar streams.
- Tests updated to use stream-based calendar sync logic.
- Calendar streams now reconcile in place when all linked groups change together; split when they diverge.
- Calendar worker retry interval increased to 30 minutes.
- PDF parser output matches sample month columns and supports `--skip-ai`.
- PDF parser fallbacks, row repairs, and info-row filtering improved for inconsistent layouts.


## [0.1.0a] - 2026-01-25
### Added
- Yoyo migrations as the SQLite migration runner.
- `services/common/calendar_client.py` for shared, read-only calendar helpers.
- Logging configuration (`DEBUG`, `LOG_LEVEL`) and shared logging setup.

### Changed
- Service migrations moved to yoyo `step` files.
- Web API now imports calendar helpers from `services/common`.
- Scraper applies its migrations on container startup.
- Service entrypoints now use shared logging setup.
- Tidied `config.py` and `config.example.py` into clear sections.
- Verified runtime stability: scraper + API OK; calendar retries blocked only by API quota.
- Fixed multiline f-strings in config templates.

## [0.0.4a] - 2026-01-25
### Added
- Services layout under `services/` (api, scraper, calendar, common, database, web).
- Calendar worker service container and `Dockerfile.calendar`.
- SQLite migrations runner with per-service migrations under each service.
- `CHANGELOG.md`.

### Changed
- Dockerfiles now copy only required service code (cleaner images).
- `docker-compose.yaml` mounts `services/web` and database under `services/database`.
- Shared DB helpers moved to `services/common`.
- Throttling simplified with global throttle and backoff; disabled in tests.

### Removed
- `schema.sql` in favor of per-service migrations.
- Redundant documentation files (design/AI parser/agent notes).

## [0.0.3a] - 2026-01-18
### Added
- Enhanced AI parser prompt handling for trailing comma patterns.
- Docker compose override example for local vs Caddy network.

### Fixed
- House number assignment bug for parentheses cases.

## [0.0.2a]
### Added
- Hybrid parser (traditional + AI) support.
- API endpoints for locations and schedules.

## [0.0.1a]
### Added
- Initial scraper and SQLite storage.
- Basic API and web UI.
