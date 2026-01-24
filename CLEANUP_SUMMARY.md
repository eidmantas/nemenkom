# Code Cleanup Summary

## Redundant Code Found

### 1. **Redundant Calendar Creation** (`scraper/main.py`)
- `create_calendars_for_schedule_groups()` is called immediately after scraping (line 74)
- BUT: Background worker `calendar_sync_worker()` in `scraper/scheduler.py` already handles calendar creation
- **Recommendation**: Remove the immediate calendar creation call since background worker handles it asynchronously

### 2. **Unused Helper Functions** (`scraper/main.py`)
- `get_all_schedule_groups()` (line 108) - only used by `create_calendars_for_schedule_groups()`
- `get_location_from_kaimai_hash()` (line 140) - only used by `get_all_schedule_groups()`
- **Recommendation**: Remove these if removing `create_calendars_for_schedule_groups()`

### 3. **Unused Import** (`scraper/main.py`)
- `import json` (line 6) - only used in `get_all_schedule_groups()` for parsing dates JSON
- **Recommendation**: Remove if removing `get_all_schedule_groups()`

## All Imports Are Used ✅
- `os.path` in `services/calendar.py` - used for file checks
- `datetime` in `services/calendar.py` - used for date operations
- `tempfile` in `scraper/main.py` - used for cleanup check

## No Dead Code Found ✅
- All functions are either used or part of the API
- No commented-out code blocks
- No temporary files (.pyc, .py~, .bak, .tmp)

## TODO Comments
- Dockerfiles have TODO comments about CI/CD - these are fine to keep
- Documentation has notes - these are fine to keep
