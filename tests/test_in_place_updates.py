"""
Tests for in-place calendar updates when dates change
Ensures that when dates are updated (same months), events update in place
"""
import pytest
import sqlite3
from datetime import date, datetime
import json
from unittest.mock import patch, MagicMock
from services.common.db import get_db_connection
from services.scraper.core.db_writer import (
    generate_schedule_group_id,
    generate_dates_hash,
    find_or_create_schedule_group,
    generate_kaimai_hash
)
from services.calendar import sync_calendar_for_schedule_group
from services.api.db import (
    get_schedule_group_info,
    update_schedule_group_calendar_id,
    update_schedule_group_calendar_synced
)


def test_in_place_update_some_dates_change(temp_db):
    """Test that when some dates change, only changed dates are updated"""
    conn, db_path = temp_db
    
    kaimai_hash = "k1_test_inplace"
    waste_type = "bendros"
    calendar_id = "test_calendar@google.com"
    
    # Initial dates
    dates1 = [date(2026, 1, 8), date(2026, 1, 22), date(2026, 2, 5)]
    schedule_group_id = find_or_create_schedule_group(conn, dates1, waste_type, kaimai_hash)
    
    # Create location
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO locations (seniunija, village, street, kaimai_hash)
        VALUES (?, ?, ?, ?)
    """, ("Test", "Village", "Street", kaimai_hash))
    conn.commit()
    
    # Set calendar_id
    update_schedule_group_calendar_id(schedule_group_id, calendar_id)
    
    # Pre-populate calendar_events (simulate existing events)
    cursor.execute("""
        INSERT INTO calendar_events (schedule_group_id, date, event_id, status)
        VALUES (?, ?, ?, 'created'),
               (?, ?, ?, 'created'),
               (?, ?, ?, 'created')
    """, (
        schedule_group_id, "2026-01-08", "event1",
        schedule_group_id, "2026-01-22", "event2",
        schedule_group_id, "2026-02-05", "event3"
    ))
    conn.commit()
    
    # Update dates: keep one, change two
    dates2 = [date(2026, 1, 8), date(2026, 1, 29), date(2026, 2, 12)]  # 1-8 stays, others change
    find_or_create_schedule_group(conn, dates2, waste_type, kaimai_hash)
    conn.commit()
    
    # Update schedule group dates
    cursor.execute("""
        UPDATE schedule_groups 
        SET dates = ?, dates_hash = ?, calendar_synced_at = NULL
        WHERE id = ?
    """, (json.dumps([d.isoformat() for d in dates2]), generate_dates_hash(dates2), schedule_group_id))
    conn.commit()
    
    # Mock Google Calendar service
    mock_service = MagicMock()
    mock_event_new = {'id': 'event_new'}
    mock_service.events().insert().execute.return_value = mock_event_new
    
    with patch('services.calendar.get_google_calendar_service', return_value=mock_service):
        # Sync events
        result = sync_calendar_for_schedule_group(schedule_group_id)
        
        assert result['success'] is True
        assert result['events_deleted'] == 2, "Should delete 2 old events (1-22 and 2-5)"
        assert result['events_added'] == 2, "Should add 2 new events (1-29 and 2-12)"
        
        # Verify calendar_events table
        cursor.execute("""
            SELECT date, event_id, status FROM calendar_events 
            WHERE schedule_group_id = ? ORDER BY date
        """, (schedule_group_id,))
        events = cursor.fetchall()
        
        event_dates = {e[0] for e in events}
        assert event_dates == {"2026-01-08", "2026-01-29", "2026-02-12"}, "Should have updated dates"
        
        # Verify event1 (2026-01-08) is still there (unchanged)
        event_1_8 = [e for e in events if e[0] == "2026-01-08"][0]
        assert event_1_8[1] == "event1", "Event for 2026-01-08 should remain unchanged"
        assert event_1_8[2] == 'created', "Status should be 'created'"


def test_in_place_update_all_dates_change(temp_db):
    """Test that when all dates change, all events are updated"""
    conn, db_path = temp_db
    
    kaimai_hash = "k1_test_inplace_all"
    waste_type = "bendros"
    calendar_id = "test_calendar@google.com"
    
    # Initial dates
    dates1 = [date(2026, 1, 8), date(2026, 1, 22)]
    schedule_group_id = find_or_create_schedule_group(conn, dates1, waste_type, kaimai_hash)
    
    # Create location
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO locations (seniunija, village, street, kaimai_hash)
        VALUES (?, ?, ?, ?)
    """, ("Test", "Village", "Street", kaimai_hash))
    conn.commit()
    
    # Set calendar_id
    update_schedule_group_calendar_id(schedule_group_id, calendar_id)
    
    # Pre-populate calendar_events
    cursor.execute("""
        INSERT INTO calendar_events (schedule_group_id, date, event_id, status)
        VALUES (?, ?, ?, 'created'),
               (?, ?, ?, 'created')
    """, (
        schedule_group_id, "2026-01-08", "event1",
        schedule_group_id, "2026-01-22", "event2"
    ))
    conn.commit()
    
    # Update all dates
    dates2 = [date(2026, 2, 5), date(2026, 2, 19)]
    find_or_create_schedule_group(conn, dates2, waste_type, kaimai_hash)
    conn.commit()
    
    # Update schedule group dates
    cursor.execute("""
        UPDATE schedule_groups 
        SET dates = ?, dates_hash = ?, calendar_synced_at = NULL
        WHERE id = ?
    """, (json.dumps([d.isoformat() for d in dates2]), generate_dates_hash(dates2), schedule_group_id))
    conn.commit()
    
    # Mock Google Calendar service
    mock_service = MagicMock()
    mock_event_new = {'id': 'event_new'}
    mock_service.events().insert().execute.return_value = mock_event_new
    
    with patch('services.calendar.get_google_calendar_service', return_value=mock_service):
        # Sync events
        result = sync_calendar_for_schedule_group(schedule_group_id)
        
        assert result['success'] is True
        assert result['events_deleted'] == 2, "Should delete 2 old events"
        assert result['events_added'] == 2, "Should add 2 new events"
        
        # Verify calendar_events table has new dates
        cursor.execute("""
            SELECT date FROM calendar_events 
            WHERE schedule_group_id = ? ORDER BY date
        """, (schedule_group_id,))
        events = cursor.fetchall()
        
        event_dates = {e[0] for e in events}
        assert event_dates == {"2026-02-05", "2026-02-19"}, "Should have new dates"


def test_in_place_update_no_dates_change(temp_db):
    """Test that when dates don't change, no events are updated"""
    conn, db_path = temp_db
    
    kaimai_hash = "k1_test_inplace_none"
    waste_type = "bendros"
    calendar_id = "test_calendar@google.com"
    
    # Initial dates
    dates = [date(2026, 1, 8), date(2026, 1, 22)]
    schedule_group_id = find_or_create_schedule_group(conn, dates, waste_type, kaimai_hash)
    
    # Create location
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO locations (seniunija, village, street, kaimai_hash)
        VALUES (?, ?, ?, ?)
    """, ("Test", "Village", "Street", kaimai_hash))
    conn.commit()
    
    # Set calendar_id and mark as synced
    update_schedule_group_calendar_id(schedule_group_id, calendar_id)
    update_schedule_group_calendar_synced(schedule_group_id)
    
    # Pre-populate calendar_events
    cursor.execute("""
        INSERT INTO calendar_events (schedule_group_id, date, event_id, status)
        VALUES (?, ?, ?, 'created'),
               (?, ?, ?, 'created')
    """, (
        schedule_group_id, "2026-01-08", "event1",
        schedule_group_id, "2026-01-22", "event2"
    ))
    conn.commit()
    
    # Call find_or_create again with same dates (should not trigger update)
    find_or_create_schedule_group(conn, dates, waste_type, kaimai_hash)
    conn.commit()
    
    # Verify calendar_synced_at is still set (no change detected)
    cursor.execute("SELECT calendar_synced_at FROM schedule_groups WHERE id = ?", (schedule_group_id,))
    row = cursor.fetchone()
    assert row[0] is not None, "calendar_synced_at should remain set (no change)"
    
    # Mock Google Calendar service (should not be called)
    mock_service = MagicMock()
    
    with patch('services.calendar.get_google_calendar_service', return_value=mock_service):
        # Sync events (should do nothing since dates didn't change)
        result = sync_calendar_for_schedule_group(schedule_group_id)
        
        assert result['success'] is True
        assert result['events_deleted'] == 0, "Should not delete any events"
        assert result['events_added'] == 0, "Should not add any events"
        
        # Verify no API calls were made
        assert mock_service.events().delete.call_count == 0, "Should not call delete"
        assert mock_service.events().insert.call_count == 0, "Should not call insert"


def test_in_place_update_calendar_id_stable(temp_db):
    """Test that calendar_id remains stable when dates are updated"""
    conn, db_path = temp_db
    
    kaimai_hash = "k1_test_stable_calendar"
    waste_type = "bendros"
    calendar_id = "stable_calendar@google.com"
    
    # Initial dates
    dates1 = [date(2026, 1, 8)]
    schedule_group_id = find_or_create_schedule_group(conn, dates1, waste_type, kaimai_hash)
    
    # Set calendar_id directly in the same connection
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE schedule_groups
        SET calendar_id = ?
        WHERE id = ?
    """, (calendar_id, schedule_group_id))
    conn.commit()
    
    # Update dates
    dates2 = [date(2026, 2, 5)]
    find_or_create_schedule_group(conn, dates2, waste_type, kaimai_hash)
    conn.commit()
    
    # Verify calendar_id is still the same (stable!)
    group_info = get_schedule_group_info(schedule_group_id)
    assert group_info['calendar_id'] == calendar_id, "Calendar ID should remain stable when dates change"
    assert group_info['calendar_synced_at'] is None, "Should be marked for re-sync"
