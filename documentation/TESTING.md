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
```bash
# Using Makefile (recommended)
make test              # Run all tests
make test-verbose      # Verbose output
make test-coverage     # With coverage report
make prepare-fixture   # Regenerate test fixture

# Or directly with pytest
source venv/bin/activate
pytest tests/ -v
pytest tests/test_e2e_xlsx_to_api.py  # Specific test file
```

### Docker Build (Tests Run Automatically)
Tests run during Docker build - build fails if tests fail.

```bash
# Build (tests run automatically)
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
- ✅ Parser functions (`parse_village_and_streets`, `extract_dates_from_cell`)
- ✅ Parser router (`should_use_ai_parser` logic)
- ✅ Database operations (hash generation, schedule grouping)
- ✅ API endpoints (`/api/v1/locations`, `/api/v1/schedule`)
- ✅ End-to-end flow (XLSX → DB → API)

## Test Data

- **Sample XLSX**: `tests/fixtures/sample_schedule.xlsx` (first 100 rows from real XLSX)
  - Generated using existing project functions (`scraper.fetcher.fetch_xlsx`)
  - Regenerate with: `python tests/prepare_fixture.py`
- **Test Database**: Created in-memory or temporary file (isolated per test)

## Future: GitHub Actions

TODO: Add GitHub Actions workflow to run tests on every push/PR.
(When CI is added, we may drop the Docker test stage to speed up builds)
