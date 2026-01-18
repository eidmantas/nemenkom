"""
Integration tests for API endpoints
"""
import pytest
from pathlib import Path
import sys
import sqlite3
import tempfile
import os

sys.path.insert(0, str(Path(__file__).parent.parent))

from api.db import get_all_locations, get_location_schedule, search_locations
from scraper.db_writer import write_location_schedule
from database.init import get_db_connection


@pytest.fixture
def test_db_with_data():
    """Create test database with sample data"""
    db_fd, db_path = tempfile.mkstemp(suffix='.db')
    
    # Initialize schema
    conn = sqlite3.connect(db_path)
    schema_path = Path(__file__).parent.parent / 'database' / 'schema.sql'
    with open(schema_path, 'r', encoding='utf-8') as f:
        schema_sql = f.read()
    conn.executescript(schema_sql)
    conn.commit()
    
    # Add test data
    from datetime import date
    test_kaimai_str = "Aleksandravas"
    test_dates = [date(2026, 1, 8), date(2026, 1, 22), date(2026, 2, 5)]
    
    location_id = write_location_schedule(
        conn,
        "Avižienių",
        "Aleksandravas",
        "",
        test_dates,
        test_kaimai_str,
        None,
        'bendros'
    )
    conn.commit()
    
    yield db_path, location_id
    
    conn.close()
    os.unlink(db_path)


def test_get_all_locations(test_db_with_data):
    """Test get_all_locations API function"""
    db_path, location_id = test_db_with_data
    
    # Mock get_db_connection
    import api.db as api_db_module
    original_get_conn = api_db_module.get_db_connection
    
    def mock_get_conn():
        return sqlite3.connect(db_path, check_same_thread=False)
    
    api_db_module.get_db_connection = mock_get_conn
    
    try:
        locations = get_all_locations()
        assert len(locations) > 0
        assert any(loc['village'] == 'Aleksandravas' for loc in locations)
    finally:
        api_db_module.get_db_connection = original_get_conn


def test_get_location_schedule(test_db_with_data):
    """Test get_location_schedule API function"""
    db_path, location_id = test_db_with_data
    
    # Mock get_db_connection
    import api.db as api_db_module
    original_get_conn = api_db_module.get_db_connection
    
    def mock_get_conn():
        return sqlite3.connect(db_path, check_same_thread=False)
    
    api_db_module.get_db_connection = mock_get_conn
    
    try:
        schedule = get_location_schedule(location_id=location_id)
        assert schedule is not None
        assert schedule['village'] == 'Aleksandravas'
        assert len(schedule['dates']) == 3
        assert schedule['dates'][0]['date'] == '2026-01-08'
    finally:
        api_db_module.get_db_connection = original_get_conn


def test_search_locations(test_db_with_data):
    """Test search_locations API function"""
    db_path, location_id = test_db_with_data
    
    # Mock get_db_connection
    import api.db as api_db_module
    original_get_conn = api_db_module.get_db_connection
    
    def mock_get_conn():
        return sqlite3.connect(db_path, check_same_thread=False)
    
    api_db_module.get_db_connection = mock_get_conn
    
    try:
        results = search_locations('Aleksandravas')
        assert len(results) > 0
        assert any(loc['village'] == 'Aleksandravas' for loc in results)
        
        results = search_locations('nonexistent')
        assert len(results) == 0
    finally:
        api_db_module.get_db_connection = original_get_conn
