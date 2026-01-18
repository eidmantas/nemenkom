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

from api.db import (
    get_all_locations, get_location_schedule, search_locations,
    village_has_streets, street_has_house_numbers, get_location_by_selection
)
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


@pytest.fixture
def test_db_with_village_and_streets():
    """Create test database with village that has streets and house numbers"""
    db_fd, db_path = tempfile.mkstemp(suffix='.db')
    
    # Initialize schema
    conn = sqlite3.connect(db_path)
    schema_path = Path(__file__).parent.parent / 'database' / 'schema.sql'
    with open(schema_path, 'r', encoding='utf-8') as f:
        schema_sql = f.read()
    conn.executescript(schema_sql)
    conn.commit()
    
    # Add test data: village with streets
    from datetime import date
    test_dates = [date(2026, 1, 8), date(2026, 1, 22)]
    
    # Village without streets (whole village)
    write_location_schedule(
        conn,
        "Test",
        "SimpleVillage",
        "",
        test_dates,
        "SimpleVillage",
        None,
        'bendros'
    )
    
    # Village with streets
    write_location_schedule(
        conn,
        "Test",
        "VillageWithStreets",
        "Main Street",
        test_dates,
        "VillageWithStreets (Main Street)",
        None,
        'bendros'
    )
    
    # Street with house numbers
    write_location_schedule(
        conn,
        "Test",
        "VillageWithStreets",
        "Second Street",
        test_dates,
        "VillageWithStreets (Second Street 1, 2, 3)",
        "1, 2, 3",
        'bendros'
    )
    
    conn.commit()
    
    yield db_path
    
    conn.close()
    os.unlink(db_path)


def test_village_has_streets(test_db_with_village_and_streets):
    """Test village_has_streets helper function"""
    db_path = test_db_with_village_and_streets
    
    # Mock get_db_connection
    import api.db as api_db_module
    original_get_conn = api_db_module.get_db_connection
    
    def mock_get_conn():
        return sqlite3.connect(db_path, check_same_thread=False)
    
    api_db_module.get_db_connection = mock_get_conn
    
    try:
        # Village without streets should return False
        assert village_has_streets('SimpleVillage') is False
        
        # Village with streets should return True
        assert village_has_streets('VillageWithStreets') is True
        
        # Non-existent village should return False
        assert village_has_streets('NonExistent') is False
    finally:
        api_db_module.get_db_connection = original_get_conn


def test_street_has_house_numbers(test_db_with_village_and_streets):
    """Test street_has_house_numbers helper function"""
    db_path = test_db_with_village_and_streets
    
    # Mock get_db_connection
    import api.db as api_db_module
    original_get_conn = api_db_module.get_db_connection
    
    def mock_get_conn():
        return sqlite3.connect(db_path, check_same_thread=False)
    
    api_db_module.get_db_connection = mock_get_conn
    
    try:
        # Street without house numbers should return False
        assert street_has_house_numbers('VillageWithStreets', 'Main Street') is False
        
        # Street with house numbers should return True
        assert street_has_house_numbers('VillageWithStreets', 'Second Street') is True
        
        # Empty street (whole village) should return False
        assert street_has_house_numbers('SimpleVillage', '') is False
    finally:
        api_db_module.get_db_connection = original_get_conn


def test_api_schedule_village_without_streets(test_db_with_village_and_streets):
    """Test API schedule endpoint for village without streets (no street parameter needed)"""
    db_path = test_db_with_village_and_streets
    
    # Mock get_db_connection
    import api.db as api_db_module
    import api.app as app_module
    original_get_conn = api_db_module.get_db_connection
    
    def mock_get_conn():
        return sqlite3.connect(db_path, check_same_thread=False)
    
    api_db_module.get_db_connection = mock_get_conn
    
    try:
        from api.app import app
        with app.test_client() as client:
            # Should work without street parameter
            response = client.get('/api/v1/schedule?village=SimpleVillage')
            assert response.status_code == 200
            data = response.get_json()
            assert data['village'] == 'SimpleVillage'
            assert 'dates' in data
    finally:
        api_db_module.get_db_connection = original_get_conn


def test_api_schedule_village_with_streets_requires_street(test_db_with_village_and_streets):
    """Test API schedule endpoint for village with streets (requires street parameter)"""
    db_path = test_db_with_village_and_streets
    
    # Mock get_db_connection
    import api.db as api_db_module
    original_get_conn = api_db_module.get_db_connection
    
    def mock_get_conn():
        return sqlite3.connect(db_path, check_same_thread=False)
    
    api_db_module.get_db_connection = mock_get_conn
    
    try:
        from api.app import app
        with app.test_client() as client:
            # Should fail without street parameter
            response = client.get('/api/v1/schedule?village=VillageWithStreets')
            assert response.status_code == 400
            data = response.get_json()
            assert 'error' in data
            assert 'streets' in data['error'].lower() or 'street' in data['error'].lower()
            
            # Should work with street parameter
            response = client.get('/api/v1/schedule?village=VillageWithStreets&street=Main Street')
            assert response.status_code == 200
            data = response.get_json()
            assert data['village'] == 'VillageWithStreets'
            assert data['street'] == 'Main Street'
    finally:
        api_db_module.get_db_connection = original_get_conn


def test_api_schedule_street_with_house_numbers_requires_house_numbers(test_db_with_village_and_streets):
    """Test API schedule endpoint for street with house numbers (requires house_numbers parameter)"""
    db_path = test_db_with_village_and_streets
    
    # Mock get_db_connection
    import api.db as api_db_module
    original_get_conn = api_db_module.get_db_connection
    
    def mock_get_conn():
        return sqlite3.connect(db_path, check_same_thread=False)
    
    api_db_module.get_db_connection = mock_get_conn
    
    try:
        from api.app import app
        with app.test_client() as client:
            # Should fail without house_numbers parameter
            response = client.get('/api/v1/schedule?village=VillageWithStreets&street=Second Street')
            assert response.status_code == 400
            data = response.get_json()
            assert 'error' in data
            assert 'house' in data['error'].lower() or 'number' in data['error'].lower()
            
            # Should work with house_numbers parameter
            response = client.get('/api/v1/schedule?village=VillageWithStreets&street=Second Street&house_numbers=1, 2, 3')
            assert response.status_code == 200
            data = response.get_json()
            assert data['village'] == 'VillageWithStreets'
            assert data['street'] == 'Second Street'
            assert data['house_numbers'] == '1, 2, 3'
    finally:
        api_db_module.get_db_connection = original_get_conn
