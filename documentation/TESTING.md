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
make test              # Run all tests (skips AI integration tests - no tokens used)
make test-verbose      # Verbose output (skips AI integration tests)
make test-coverage     # With coverage report (skips AI integration tests)
make test-ai           # Run AI integration tests ONLY (uses real Groq tokens)
make prepare-fixture   # Regenerate test fixture
```

**Or directly with pytest (requires venv activation):**
```bash
source venv/bin/activate  # Activate venv first
pytest tests/ -v
pytest tests/test_e2e_xlsx_to_api.py  # Specific test file
pytest tests/ --use-ai-tokens -m ai_integration  # AI integration tests
```

**Note:** The Makefile automatically checks for venv and uses it. If venv doesn't exist, test commands will prompt you to run `make venv-install` first.

### Docker Build (Tests Run Automatically)
Tests run during Docker build - build fails if tests fail.

**Note:** Docker builds run `pytest -v` without the `--use-ai-tokens` flag, so:
- ✅ All regular tests run (54 tests)
- ⏭️ AI integration tests are **skipped** (no API tokens used during builds)
- This is intentional - we don't want to use real API tokens during Docker builds

```bash
# Build (tests run automatically, AI integration tests skipped)
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
- ✅ AI parser integration (Groq API calls, validation, format conversion)
- ✅ Database operations (hash generation, schedule grouping)
- ✅ API endpoints (`/api/v1/locations`, `/api/v1/schedule`)
- ✅ End-to-end flow (XLSX → DB → API)

### AI Integration Tests

**Important:** AI integration tests are **skipped** by default in `make test`, `make test-verbose`, and `make test-coverage`. Only `make test-ai` runs them.

AI integration tests (`make test-ai`) make real Groq API calls and use tokens:
- Tests use temporary cache databases (fresh API calls every time)
- Tests current code and prompt logic, not cached results
- Marked with `@pytest.mark.ai_integration`
- Require `--use-ai-tokens` flag to run (automatically set by `make test-ai`)
- Test complex parsing patterns from real CSV data
- **Only `make test-ai` uses real API tokens** - other test commands skip these tests

## Test Data

- **Sample XLSX**: `tests/fixtures/sample_schedule.xlsx` (first 100 rows from real XLSX)
  - Generated using existing project functions (`scraper.fetcher.fetch_xlsx`)
  - Regenerate with: `python tests/prepare_fixture.py`
- **Test Database**: Created in-memory or temporary file (isolated per test)

## Future: GitHub Actions

TODO: Add GitHub Actions workflow to run tests on every push/PR.
(When CI is added, we may drop the Docker test stage to speed up builds)
