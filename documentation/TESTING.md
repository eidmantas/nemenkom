# Testing Guide

## Overview

Tests protect core functionality: **XLSX parsing → Database → API**. Ensures future changes (AI parser, etc.) don't break existing working code.

## Test Structure

```
tests/
├── __init__.py
├── conftest.py              # Shared fixtures (test DB, sample data)
├── test_parser.py           # Unit tests: parser functions
├── test_parser_router.py    # Unit tests: AI parser routing logic
├── test_api_endpoints.py    # Integration tests: API endpoints
└── test_e2e_xlsx_to_api.py  # Critical E2E: XLSX → DB → API
```

## Running Tests

### Local Development

**Using Makefile (recommended - automatically uses venv):**

```bash
# First time setup: create venv and install dependencies
make venv-install

# Run tests (automatically uses venv, no manual activation needed)
make test              # Run tests (skips AI Agent + Google Calendar API)
make test-ai           # Run AI Agent tests only
make test-calendar     # Google Calendar API tests only
make test-all          # Tests including AI Agent (skips Google Calendar API)
```

**Or directly with pytest (requires venv activation):**

```bash
source venv/bin/activate  # Activate venv first
pytest tests/ -v
pytest tests/test_e2e_xlsx_to_api.py  # Specific test file
```

The Makefile automatically checks for venv and uses it. If venv doesn't exist, test commands will prompt you to run `make venv-install` first.

### Docker Build (Tests Run Automatically)

Docker builds do not run the full test suite automatically by default. For release confidence,
run tests locally with `make test` (and optionally `make lint` / `make typecheck`) before building.

```bash
# Build images
podman-compose build

# Or build specific service
podman-compose build web
```

## Test Coverage

### Critical Tests (Must Pass)

1. **E2E Test**: Sample XLSX → Database → API returns correct dates
2. **Parser Unit Tests**: Traditional parser handles known patterns correctly
3. **API Integration Tests**: Endpoints return expected data structure

### What's Tested

- Parser functions (`parse_village_and_streets`, `extract_dates_from_cell`)
- Parser router (`should_use_ai_parser` logic)
- AI parser integration (OpenAI-compatible API calls, validation, format conversion)
- Database operations (hash generation, schedule grouping)
- API endpoints (`/api/v1/locations`, `/api/v1/schedule`)
- End-to-end flow (XLSX → DB → API)

### AI Integration Tests

AI integration tests make real OpenAI-compatible API calls and use tokens:

- Tests use temporary cache databases (fresh API calls every time)
- Tests current code and prompt logic, not cached results
- Marked with `@pytest.mark.ai_integration`
- Test complex parsing patterns from real CSV data

## Test Data

- **Sample XLSX**: `tests/fixtures/sample_schedule.xlsx` (first 100 rows from real XLSX)
  - Generated using existing project functions (`scraper.fetcher.fetch_xlsx`)
- **Test Database**: Created in-memory or temporary file (isolated per test)

## Future: GitHub Actions
