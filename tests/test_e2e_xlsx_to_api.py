"""
Critical End-to-End Test: XLSX → Database → API

This test ensures the core functionality works:
1. Parse sample XLSX file
2. Write to database
3. Query API
4. Verify dates match expected values

This protects against regressions when adding AI parser, etc.
"""
import pytest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from scraper.core.validator import validate_file_and_data
from api.db import get_location_schedule, search_locations
import sqlite3
import tempfile
import os


@pytest.fixture
def test_db():
    """Create isolated test database"""
    db_fd, db_path = tempfile.mkstemp(suffix='.db')
    
    # Initialize schema
    conn = sqlite3.connect(db_path)
    schema_path = Path(__file__).parent.parent / 'database' / 'schema.sql'
    with open(schema_path, 'r', encoding='utf-8') as f:
        schema_sql = f.read()
    conn.executescript(schema_sql)
    conn.commit()
    conn.close()
    
    yield db_path
    
    # Cleanup
    os.unlink(db_path)


def test_xlsx_to_api_end_to_end(sample_xlsx_path, test_db):
    """
    Critical E2E test: Parse XLSX → Write to DB → Query API → Verify dates
    
    This is the most important test - it protects the core functionality.
    """
    # Expected results from sample XLSX (known good data)
    expected_results = {
        'Aleksandravas': {
            'village': 'Aleksandravas',
            'street': '',
            'dates': [
                '2026-01-08', '2026-01-22',
                '2026-02-05', '2026-02-19',
                '2026-03-05', '2026-03-19',
                '2026-04-02', '2026-04-16', '2026-04-30',
                '2026-05-14', '2026-05-28',
                '2026-06-11', '2026-06-25'
            ]
        },
        'Tarandė': {
            'village': 'Tarandė',
            'street': '',
            'dates': [
                '2026-01-13', '2026-01-27',
                '2026-02-10', '2026-02-24',
                '2026-03-10', '2026-03-24',
                '2026-04-07', '2026-04-21',
                '2026-05-05', '2026-05-19',
                '2026-06-02', '2026-06-16', '2026-06-30'
            ]
        }
    }
    
    # Step 1: Parse XLSX
    assert sample_xlsx_path.exists(), f"Sample XLSX not found: {sample_xlsx_path}"
    
    is_valid, errors, parsed_data = validate_file_and_data(
        sample_xlsx_path, 
        year=2026, 
        simple_subset=True
    )
    
    assert is_valid, f"Validation failed: {errors}"
    assert len(parsed_data) > 0, "No data parsed from XLSX"
    
    # Step 2: Write to test database
    # We need to temporarily use the test database
    # For now, we'll use the actual database path override
    conn = sqlite3.connect(test_db)
    
    # Write data using db_writer
    from scraper.core.db_writer import write_location_schedule
    
    locations_written = 0
    for item in parsed_data:
        kaimai_str = item.get('original_kaimai_str', '')
        if not kaimai_str:
            # Reconstruct from village/street
            if item['street']:
                kaimai_str = f"{item['village']} ({item['street']})"
            else:
                kaimai_str = item['village']
        
        location_id = write_location_schedule(
            conn,
            item['seniūnija'],
            item['village'],
            item['street'],
            item['dates'],
            kaimai_str,
            item.get('house_numbers'),
            'bendros'
        )
        if location_id:
            locations_written += 1
    
    conn.commit()
    assert locations_written > 0, "No locations written to database"
    
    # Step 3: Query API (using api/db functions with test DB)
    # We need to mock get_db_connection to use test DB
    import api.db as api_db_module
    original_get_conn = api_db_module.get_db_connection
    
    def mock_get_conn():
        return sqlite3.connect(test_db, check_same_thread=False)
    
    api_db_module.get_db_connection = mock_get_conn
    
    try:
        # Test: Search for locations
        locations = search_locations('Aleksandravas')
        assert len(locations) > 0, "Location not found in API"
        
        aleksandravas = None
        for loc in locations:
            if loc['village'] == 'Aleksandravas' and loc['street'] == '':
                aleksandravas = loc
                break
        
        assert aleksandravas is not None, "Aleksandravas location not found"
        
        # Test: Get schedule
        schedule = get_location_schedule(location_id=aleksandravas['id'])
        assert schedule is not None, "Schedule not found"
        
        # Step 4: Verify dates match expected
        # API returns single schedule with dates list
        assert 'dates' in schedule, "Schedule missing 'dates' key"
        assert len(schedule['dates']) > 0, "No dates found in schedule"
        assert schedule['waste_type'] == 'bendros', "Expected general waste schedule"
        
        # Extract date strings from API response
        api_dates = sorted([d['date'] for d in schedule['dates']])
        expected_dates = sorted(expected_results['Aleksandravas']['dates'])
        
        assert api_dates == expected_dates, \
            f"Dates don't match!\nExpected: {expected_dates}\nGot: {api_dates}"
        
        # Test another location
        locations = search_locations('Tarandė')
        tarande = None
        for loc in locations:
            if loc['village'] == 'Tarandė' and loc['street'] == '':
                tarande = loc
                break
        
        if tarande:
            schedule = get_location_schedule(location_id=tarande['id'])
            if schedule and len(schedule.get('dates', [])) > 0:
                api_dates = sorted([d['date'] for d in schedule['dates']])
                expected_dates = sorted(expected_results['Tarandė']['dates'])
                assert api_dates == expected_dates, \
                    f"Tarandė dates don't match!\nExpected: {expected_dates}\nGot: {api_dates}"
    
    finally:
        # Restore original function
        api_db_module.get_db_connection = original_get_conn
        conn.close()
