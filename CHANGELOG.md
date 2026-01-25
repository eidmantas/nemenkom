# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

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
