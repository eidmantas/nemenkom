"""
Tests to ensure one calendar per schedule group (stable calendar IDs)
Tests that calendar IDs remain stable when dates change
"""
import pytest
import sqlite3
from datetime import date, datetime
import json
from services.common.db import get_db_connection
from services.scraper.core.db_writer import (
    generate_schedule_group_id,
    generate_dates_hash,
    find_or_create_schedule_group,
    generate_kaimai_hash
)
from services.calendar import create_calendar_for_schedule_group
from services.api.db import get_schedule_group_info, update_schedule_group_calendar_id
from unittest.mock import patch, MagicMock


def test_one_calendar_per_schedule_group(temp_db):
    """Test that one schedule group always has one calendar (stable ID)"""
    conn, db_path = temp_db
    
    kaimai_hash = "k1_test_one_calendar"
    waste_type = "bendros"
    dates1 = [date(2026, 1, 8), date(2026, 1, 22)]
    
    # Create schedule group
    schedule_group_id = find_or_create_schedule_group(conn, dates1, waste_type, kaimai_hash)
    conn.commit()
    
    # Create location
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO locations (seniunija, village, street, kaimai_hash)
        VALUES (?, ?, ?, ?)
    """, ("Test", "Village", "Street", kaimai_hash))
    conn.commit()
    
    # Mock calendar creation
    mock_service = MagicMock()
    mock_calendar = {'id': 'stable_calendar@google.com', 'summary': 'Test Calendar'}
    mock_service.calendars().insert().execute.return_value = mock_calendar
    
    existing_info = {
        "calendar_id": mock_calendar["id"],
        "calendar_name": mock_calendar["summary"],
        "description": "",
        "subscription_link": f"https://calendar.google.com/calendar/render?cid={mock_calendar['id']}",
        "timeZone": "Europe/Vilnius",
    }

    with patch('services.calendar.get_google_calendar_service', return_value=mock_service), \
         patch('services.calendar.get_existing_calendar_info', return_value=existing_info):
        # Create calendar first time
        result1 = create_calendar_for_schedule_group(schedule_group_id)
        assert result1['success'] is True
        calendar_id1 = result1['calendar_id']
        
        # Verify calendar_id is stored
        group_info = get_schedule_group_info(schedule_group_id)
        assert group_info['calendar_id'] == calendar_id1
        
        # Try to create calendar again (should return existing)
        result2 = create_calendar_for_schedule_group(schedule_group_id)
        assert result2['success'] is True
        assert result2['calendar_id'] == calendar_id1, "Should return same calendar ID"
        assert result2.get('existing') is True, "Should indicate existing calendar"
        
        # Verify calendar creation was only called once
        assert mock_service.calendars().insert().execute.call_count == 1, "Calendar should be created only once"


def test_calendar_id_stable_when_dates_change(temp_db):
    """Test that calendar_id remains stable when dates change"""
    conn, db_path = temp_db
    
    kaimai_hash = "k1_test_stable_calendar"
    waste_type = "bendros"
    dates1 = [date(2026, 1, 8), date(2026, 1, 22)]
    dates2 = [date(2026, 2, 5), date(2026, 2, 19)]  # Different dates
    
    # Create schedule group with initial dates
    schedule_group_id = find_or_create_schedule_group(conn, dates1, waste_type, kaimai_hash)
    conn.commit()
    
    # Create location
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO locations (seniunija, village, street, kaimai_hash)
        VALUES (?, ?, ?, ?)
    """, ("Test", "Village", "Street", kaimai_hash))
    conn.commit()
    
    # Create calendar
    mock_service = MagicMock()
    mock_calendar = {'id': 'stable_calendar@google.com', 'summary': 'Test Calendar'}
    mock_service.calendars().insert().execute.return_value = mock_calendar
    
    existing_info = {
        "calendar_id": mock_calendar["id"],
        "calendar_name": mock_calendar["summary"],
        "description": "",
        "subscription_link": f"https://calendar.google.com/calendar/render?cid={mock_calendar['id']}",
        "timeZone": "Europe/Vilnius",
    }

    with patch('services.calendar.get_google_calendar_service', return_value=mock_service), \
         patch('services.calendar.get_existing_calendar_info', return_value=existing_info):
        result = create_calendar_for_schedule_group(schedule_group_id)
        calendar_id = result['calendar_id']
    
    # Update dates (same kaimai_hash + waste_type = same schedule_group_id)
    find_or_create_schedule_group(conn, dates2, waste_type, kaimai_hash)
    conn.commit()
    
    # Verify calendar_id is still the same (stable!)
    group_info = get_schedule_group_info(schedule_group_id)
    assert group_info['calendar_id'] == calendar_id, "Calendar ID should remain stable when dates change"
    assert group_info['calendar_synced_at'] is None, "Should be marked for re-sync"


def test_different_waste_types_different_calendars(temp_db):
    """Test that different waste types get different calendars"""
    conn, db_path = temp_db
    
    kaimai_hash = "k1_test_waste_types"
    dates = [date(2026, 1, 8)]
    
    # Create location
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO locations (seniunija, village, street, kaimai_hash)
        VALUES (?, ?, ?, ?)
    """, ("Test", "Village", "Street", kaimai_hash))
    conn.commit()
    
    # Create schedule groups for different waste types
    schedule_group_id1 = find_or_create_schedule_group(conn, dates, "bendros", kaimai_hash)
    schedule_group_id2 = find_or_create_schedule_group(conn, dates, "plastikas", kaimai_hash)
    conn.commit()
    
    # Verify different schedule_group_ids
    assert schedule_group_id1 != schedule_group_id2, "Different waste types should have different schedule_group_ids"
    
    # Create calendars
    mock_service = MagicMock()
    mock_calendar1 = {'id': 'calendar_bendros@google.com', 'summary': 'Bendros Calendar'}
    mock_calendar2 = {'id': 'calendar_plastikas@google.com', 'summary': 'Plastikas Calendar'}
    mock_service.calendars().insert().execute.side_effect = [mock_calendar1, mock_calendar2]
    
    with patch('services.calendar.get_google_calendar_service', return_value=mock_service):
        result1 = create_calendar_for_schedule_group(schedule_group_id1)
        result2 = create_calendar_for_schedule_group(schedule_group_id2)
        
        assert result1['calendar_id'] != result2['calendar_id'], "Different waste types should have different calendars"


def test_same_location_different_streets_same_calendar_if_same_schedule(temp_db):
    """Test that same location with same schedule shares calendar"""
    conn, db_path = temp_db
    
    # Same kaimai_hash = same schedule group = same calendar
    kaimai_hash = "k1_test_shared"
    waste_type = "bendros"
    dates = [date(2026, 1, 8)]
    
    # Create schedule group
    schedule_group_id = find_or_create_schedule_group(conn, dates, waste_type, kaimai_hash)
    conn.commit()
    
    # Create multiple locations with same kaimai_hash
    cursor = conn.cursor()
    for i in range(3):
        cursor.execute("""
            INSERT INTO locations (seniunija, village, street, kaimai_hash)
            VALUES (?, ?, ?, ?)
        """, ("Test", "Village", f"Street {i}", kaimai_hash))
    conn.commit()
    
    # Create calendar (one calendar for all locations with same schedule)
    mock_service = MagicMock()
    mock_calendar = {'id': 'shared_calendar@google.com', 'summary': 'Shared Calendar'}
    mock_service.calendars().insert().execute.return_value = mock_calendar
    
    with patch('services.calendar.get_google_calendar_service', return_value=mock_service):
        result = create_calendar_for_schedule_group(schedule_group_id)
        calendar_id = result['calendar_id']
    
    # Verify all locations share the same calendar
    cursor.execute("""
        SELECT l.id FROM locations l
        JOIN schedule_groups sg ON l.kaimai_hash = sg.kaimai_hash
        WHERE sg.id = ?
    """, (schedule_group_id,))
    location_ids = [row[0] for row in cursor.fetchall()]
    
    for location_id in location_ids:
        from services.api.db import get_location_schedule
        schedule = get_location_schedule(location_id=location_id, waste_type=waste_type)
        if schedule and schedule.get('calendar_id'):
            assert schedule['calendar_id'] == calendar_id, "All locations should share same calendar"


def test_calendar_not_recreated_on_date_change(temp_db):
    """Test that calendar is not recreated when dates change (only events updated)"""
    conn, db_path = temp_db
    
    kaimai_hash = "k1_test_no_recreate"
    waste_type = "bendros"
    dates1 = [date(2026, 1, 8)]
    dates2 = [date(2026, 2, 5)]  # Different dates
    
    # Create schedule group
    schedule_group_id = find_or_create_schedule_group(conn, dates1, waste_type, kaimai_hash)
    conn.commit()
    
    # Create location
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO locations (seniunija, village, street, kaimai_hash)
        VALUES (?, ?, ?, ?)
    """, ("Test", "Village", "Street", kaimai_hash))
    conn.commit()
    
    # Create calendar
    mock_service = MagicMock()
    mock_calendar = {'id': 'stable_calendar@google.com', 'summary': 'Test Calendar'}
    mock_service.calendars().insert().execute.return_value = mock_calendar
    
    existing_info = {
        "calendar_id": mock_calendar["id"],
        "calendar_name": mock_calendar["summary"],
        "description": "",
        "subscription_link": f"https://calendar.google.com/calendar/render?cid={mock_calendar['id']}",
        "timeZone": "Europe/Vilnius",
    }

    with patch('services.calendar.get_google_calendar_service', return_value=mock_service), \
         patch('services.calendar.get_existing_calendar_info', return_value=existing_info):
        result1 = create_calendar_for_schedule_group(schedule_group_id)
        calendar_id1 = result1['calendar_id']
        
        # Change dates
        find_or_create_schedule_group(conn, dates2, waste_type, kaimai_hash)
        conn.commit()
        
        # Try to create calendar again (should return existing, not create new)
        result2 = create_calendar_for_schedule_group(schedule_group_id)
        calendar_id2 = result2['calendar_id']
        
        assert calendar_id1 == calendar_id2, "Calendar ID should remain the same"
        assert result2.get('existing') is True, "Should return existing calendar"
        
        # Verify calendar creation was only called once
        assert mock_service.calendars().insert().execute.call_count == 1, "Calendar should not be recreated"


def test_calendar_creation_only_for_schedule_groups_not_villages(temp_db):
    """Test that calendars are created per schedule_group_id, not per village"""
    conn, db_path = temp_db
    
    # Same kaimai_hash = same schedule group = ONE calendar
    kaimai_hash = "k1_test_one_calendar_multiple_villages"
    waste_type = "bendros"
    dates = [date(2026, 1, 8)]
    
    # Create schedule group (one per kaimai_hash + waste_type)
    schedule_group_id = find_or_create_schedule_group(conn, dates, waste_type, kaimai_hash)
    conn.commit()
    
    # Create multiple villages with SAME kaimai_hash (they share the schedule)
    cursor = conn.cursor()
    villages = ["Village1", "Village2", "Village3"]
    for village in villages:
        cursor.execute("""
            INSERT INTO locations (seniunija, village, street, kaimai_hash)
            VALUES (?, ?, ?, ?)
        """, ("Test", village, "", kaimai_hash))
    conn.commit()
    
    # Create calendar (should be ONE calendar for all villages)
    mock_service = MagicMock()
    mock_calendar = {'id': 'one_calendar@google.com', 'summary': 'One Calendar'}
    mock_service.calendars().insert().execute.return_value = mock_calendar
    
    with patch('services.calendar.get_google_calendar_service', return_value=mock_service):
        result = create_calendar_for_schedule_group(schedule_group_id)
        calendar_id = result['calendar_id']
    
    # Verify only ONE calendar was created (not one per village)
    assert mock_service.calendars().insert().execute.call_count == 1, "Should create only ONE calendar for all villages with same schedule"
    
    # Verify all villages share the same calendar_id
    group_info = get_schedule_group_info(schedule_group_id)
    assert group_info['calendar_id'] == calendar_id, "All villages should share the same calendar"


def test_no_duplicate_calendar_creation_on_retry(temp_db):
    """Test that retrying calendar creation doesn't create duplicates"""
    conn, db_path = temp_db
    
    kaimai_hash = "k1_test_no_duplicates"
    waste_type = "bendros"
    dates = [date(2026, 1, 8)]
    
    # Create schedule group
    schedule_group_id = find_or_create_schedule_group(conn, dates, waste_type, kaimai_hash)
    conn.commit()
    
    # Create location
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO locations (seniunija, village, street, kaimai_hash)
        VALUES (?, ?, ?, ?)
    """, ("Test", "Village", "Street", kaimai_hash))
    conn.commit()
    
    # Mock calendar creation
    mock_service = MagicMock()
    mock_calendar = {'id': 'stable_calendar@google.com', 'summary': 'Test Calendar'}
    mock_service.calendars().insert().execute.return_value = mock_calendar
    
    existing_info = {
        "calendar_id": mock_calendar["id"],
        "calendar_name": mock_calendar["summary"],
        "description": "",
        "subscription_link": f"https://calendar.google.com/calendar/render?cid={mock_calendar['id']}",
        "timeZone": "Europe/Vilnius",
    }

    with patch('services.calendar.get_google_calendar_service', return_value=mock_service), \
         patch('services.calendar.get_existing_calendar_info', return_value=existing_info):
        # Create calendar first time
        result1 = create_calendar_for_schedule_group(schedule_group_id)
        assert result1['success'] is True
        calendar_id1 = result1['calendar_id']
        
        # Simulate multiple retry attempts (e.g., from background worker)
        for i in range(5):
            result = create_calendar_for_schedule_group(schedule_group_id)
            assert result['success'] is True
            assert result['calendar_id'] == calendar_id1, f"Retry {i+1} should return same calendar"
            assert result.get('existing') is True, f"Retry {i+1} should indicate existing calendar"
        
        # Verify calendar was created only ONCE (not 6 times)
        assert mock_service.calendars().insert().execute.call_count == 1, "Calendar should be created only once, even with multiple retries"


def test_calendar_creation_handles_database_update_failure(temp_db):
    """Test that calendar creation handles database update failures gracefully"""
    conn, db_path = temp_db
    
    kaimai_hash = "k1_test_db_failure"
    waste_type = "bendros"
    dates = [date(2026, 1, 8)]
    
    # Create schedule group
    schedule_group_id = find_or_create_schedule_group(conn, dates, waste_type, kaimai_hash)
    conn.commit()
    
    # Create location
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO locations (seniunija, village, street, kaimai_hash)
        VALUES (?, ?, ?, ?)
    """, ("Test", "Village", "Street", kaimai_hash))
    conn.commit()
    
    # Mock calendar creation
    mock_service = MagicMock()
    mock_calendar = {'id': 'calendar_created@google.com', 'summary': 'Test Calendar'}
    mock_service.calendars().insert().execute.return_value = mock_calendar
    
    # Mock database update failure
    with patch('services.calendar.get_google_calendar_service', return_value=mock_service):
        with patch('services.calendar.update_schedule_group_calendar_id', return_value=False):
            result = create_calendar_for_schedule_group(schedule_group_id)
            
            # Should still return success (calendar was created)
            assert result['success'] is True
            assert result['calendar_id'] == 'calendar_created@google.com'
            assert 'warning' in result, "Should include warning about database update failure"
            
            # Calendar should still be created in Google Calendar
            assert mock_service.calendars().insert().execute.call_count == 1
