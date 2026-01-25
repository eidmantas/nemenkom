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

from services.api.db import (
    get_all_locations, get_location_schedule, search_locations,
    village_has_streets, street_has_house_numbers
)
from services.scraper.core.db_writer import write_location_schedule
from services.common.migrations import apply_migrations


@pytest.fixture
def test_db_with_data():
    """Create test database with sample data"""
    db_fd, db_path = tempfile.mkstemp(suffix='.db')
    
    # Initialize schema
    conn = sqlite3.connect(db_path)
    apply_migrations(conn, Path(__file__).parent.parent / "services" / "scraper" / "migrations")
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
    import services.api.db as api_db_module
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
    import services.api.db as api_db_module
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
    import services.api.db as api_db_module
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
    apply_migrations(conn, Path(__file__).parent.parent / "services" / "scraper" / "migrations")
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
    import services.api.db as api_db_module
    original_get_conn = api_db_module.get_db_connection
    
    def mock_get_conn():
        return sqlite3.connect(db_path, check_same_thread=False)
    
    api_db_module.get_db_connection = mock_get_conn
    
    try:
        # Village without streets should return False
        assert village_has_streets('Test', 'SimpleVillage') is False
        
        # Village with streets should return True
        assert village_has_streets('Test', 'VillageWithStreets') is True
        
        # Non-existent village should return False
        assert village_has_streets('Test', 'NonExistent') is False
    finally:
        api_db_module.get_db_connection = original_get_conn


def test_street_has_house_numbers(test_db_with_village_and_streets):
    """Test street_has_house_numbers helper function"""
    db_path = test_db_with_village_and_streets
    
    # Mock get_db_connection
    import services.api.db as api_db_module
    original_get_conn = api_db_module.get_db_connection
    
    def mock_get_conn():
        return sqlite3.connect(db_path, check_same_thread=False)
    
    api_db_module.get_db_connection = mock_get_conn
    
    try:
        # Street without house numbers should return False
        assert street_has_house_numbers('Test', 'VillageWithStreets', 'Main Street') is False
        
        # Street with house numbers should return True
        assert street_has_house_numbers('Test', 'VillageWithStreets', 'Second Street') is True
        
        # Empty street (whole village) should return False
        assert street_has_house_numbers('Test', 'SimpleVillage', '') is False
    finally:
        api_db_module.get_db_connection = original_get_conn


def test_api_schedule_village_without_streets(test_db_with_village_and_streets):
    """Test API schedule endpoint for village without streets (no street parameter needed)"""
    db_path = test_db_with_village_and_streets
    
    # Mock get_db_connection
    import services.api.db as api_db_module
    original_get_conn = api_db_module.get_db_connection
    
    def mock_get_conn():
        return sqlite3.connect(db_path, check_same_thread=False)
    
    api_db_module.get_db_connection = mock_get_conn
    
    try:
        from services.api.app import app
        with app.test_client() as client:
            # Should work without street parameter (requires seniunija)
            response = client.get('/api/v1/schedule?seniunija=Test&village=SimpleVillage')
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
    import services.api.db as api_db_module
    original_get_conn = api_db_module.get_db_connection
    
    def mock_get_conn():
        return sqlite3.connect(db_path, check_same_thread=False)
    
    api_db_module.get_db_connection = mock_get_conn
    
    try:
        from services.api.app import app
        with app.test_client() as client:
            # Should fail without street parameter (requires seniunija)
            response = client.get('/api/v1/schedule?seniunija=Test&village=VillageWithStreets')
            assert response.status_code == 400
            data = response.get_json()
            assert 'error' in data
            assert 'streets' in data['error'].lower() or 'street' in data['error'].lower()
            
            # Should work with street parameter
            response = client.get('/api/v1/schedule?seniunija=Test&village=VillageWithStreets&street=Main Street')
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
    import services.api.db as api_db_module
    original_get_conn = api_db_module.get_db_connection
    
    def mock_get_conn():
        return sqlite3.connect(db_path, check_same_thread=False)
    
    api_db_module.get_db_connection = mock_get_conn
    
    try:
        from services.api.app import app
        with app.test_client() as client:
            # Should fail without house_numbers parameter (requires seniunija)
            response = client.get('/api/v1/schedule?seniunija=Test&village=VillageWithStreets&street=Second Street')
            assert response.status_code == 400
            data = response.get_json()
            assert 'error' in data
            assert 'house' in data['error'].lower() or 'number' in data['error'].lower()
            
            # Should work with house_numbers parameter
            response = client.get('/api/v1/schedule?seniunija=Test&village=VillageWithStreets&street=Second Street&house_numbers=1, 2, 3')
            assert response.status_code == 200
            data = response.get_json()
            assert data['village'] == 'VillageWithStreets'
            assert data['street'] == 'Second Street'
            assert data['house_numbers'] == '1, 2, 3'
    finally:
        api_db_module.get_db_connection = original_get_conn


def test_get_unique_villages_format(test_db_with_village_and_streets):
    """Test get_unique_villages returns correct format with seniūnija and village"""
    db_path = test_db_with_village_and_streets
    
    # Mock get_db_connection
    import services.api.db as api_db_module
    original_get_conn = api_db_module.get_db_connection
    
    def mock_get_conn():
        return sqlite3.connect(db_path, check_same_thread=False)
    
    api_db_module.get_db_connection = mock_get_conn
    
    try:
        from services.api.db import get_unique_villages
        villages = get_unique_villages()
        
        # Should return list of dicts
        assert isinstance(villages, list)
        assert len(villages) > 0
        
        # Each village should be a dict with seniunija and village keys
        for village in villages:
            assert isinstance(village, dict)
            assert 'seniunija' in village
            assert 'village' in village
            assert isinstance(village['seniunija'], str)
            assert isinstance(village['village'], str)
        
        # Should contain our test villages
        village_names = [v['village'] for v in villages]
        assert 'SimpleVillage' in village_names
        assert 'VillageWithStreets' in village_names
        
        # Should have correct seniunija
        test_villages = [v for v in villages if v['village'] in ['SimpleVillage', 'VillageWithStreets']]
        assert all(v['seniunija'] == 'Test' for v in test_villages)
    finally:
        api_db_module.get_db_connection = original_get_conn


def test_api_villages_endpoint(test_db_with_village_and_streets):
    """Test /api/v1/villages endpoint returns correct format"""
    db_path = test_db_with_village_and_streets
    
    # Mock get_db_connection
    import services.api.db as api_db_module
    original_get_conn = api_db_module.get_db_connection
    
    def mock_get_conn():
        return sqlite3.connect(db_path, check_same_thread=False)
    
    api_db_module.get_db_connection = mock_get_conn
    
    try:
        from services.api.app import app
        with app.test_client() as client:
            response = client.get('/api/v1/villages')
            assert response.status_code == 200
            data = response.get_json()
            assert 'villages' in data
            assert isinstance(data['villages'], list)
            
            # Check format
            if len(data['villages']) > 0:
                village = data['villages'][0]
                assert isinstance(village, dict)
                assert 'seniunija' in village
                assert 'village' in village
    finally:
        api_db_module.get_db_connection = original_get_conn


def test_api_streets_endpoint_requires_seniūnija(test_db_with_village_and_streets):
    """Test /api/v1/streets endpoint requires seniūnija parameter"""
    db_path = test_db_with_village_and_streets
    
    # Mock get_db_connection
    import services.api.db as api_db_module
    original_get_conn = api_db_module.get_db_connection
    
    def mock_get_conn():
        return sqlite3.connect(db_path, check_same_thread=False)
    
    api_db_module.get_db_connection = mock_get_conn
    
    try:
        from services.api.app import app
        with app.test_client() as client:
            # Should fail without seniunija
            response = client.get('/api/v1/streets?village=VillageWithStreets')
            assert response.status_code == 400
            
            # Should work with seniunija
            response = client.get('/api/v1/streets?seniunija=Test&village=VillageWithStreets')
            assert response.status_code == 200
            data = response.get_json()
            assert 'streets' in data
            assert 'Main Street' in data['streets']
    finally:
        api_db_module.get_db_connection = original_get_conn


def test_duplicate_village_names_different_seniūnija(test_db_with_village_and_streets):
    """Test that villages with same name in different seniūnija are handled correctly"""
    db_path = test_db_with_village_and_streets
    
    # Add duplicate village name in different seniūnija
    conn = sqlite3.connect(db_path, check_same_thread=False)
    from datetime import date
    from services.scraper.core.db_writer import write_location_schedule
    
    # Add same village name in different seniūnija
    write_location_schedule(
        conn,
        "Other",
        "SimpleVillage",  # Same name, different seniūnija
        "",
        [date(2026, 1, 15)],
        "SimpleVillage",
        None,
        'bendros'
    )
    conn.commit()
    conn.close()
    
    # Mock get_db_connection
    import services.api.db as api_db_module
    original_get_conn = api_db_module.get_db_connection
    
    def mock_get_conn():
        return sqlite3.connect(db_path, check_same_thread=False)
    
    api_db_module.get_db_connection = mock_get_conn
    
    try:
        from services.api.db import get_unique_villages
        villages = get_unique_villages()
        
        # Should have both SimpleVillage entries (different seniunija)
        simple_villages = [v for v in villages if v['village'] == 'SimpleVillage']
        assert len(simple_villages) == 2
        assert {v['seniunija'] for v in simple_villages} == {'Test', 'Other'}
        
        # Each should have correct seniunija
        test_village = next(v for v in simple_villages if v['seniunija'] == 'Test')
        other_village = next(v for v in simple_villages if v['seniunija'] == 'Other')
        assert test_village['village'] == 'SimpleVillage'
        assert other_village['village'] == 'SimpleVillage'
    finally:
        api_db_module.get_db_connection = original_get_conn
