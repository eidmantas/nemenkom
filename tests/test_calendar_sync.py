"""
Tests for calendar event synchronization
Tests adding, deleting, and updating events when dates change
"""
import pytest
import sqlite3
from datetime import date, datetime
from unittest.mock import Mock, patch, MagicMock
import json
from database.init import get_db_connection
from scraper.core.db_writer import (
    generate_schedule_group_id,
    generate_dates_hash,
    find_or_create_schedule_group,
    generate_kaimai_hash
)
from services.calendar import sync_calendar_for_schedule_group
from api.db import get_schedule_group_info, update_schedule_group_calendar_id


def create_test_schedule_group_with_calendar(temp_db, kaimai_hash: str, waste_type: str, dates: list, calendar_id: str):
    """Helper to create schedule group with calendar_id set"""
    conn, db_path = temp_db
    
    schedule_group_id = generate_schedule_group_id(kaimai_hash, waste_type)
    # Convert string dates to date objects if needed
    date_objects = [datetime.strptime(d, "%Y-%m-%d").date() if isinstance(d, str) else d for d in dates]
    dates_hash = generate_dates_hash(date_objects)
    
    cursor = conn.cursor()
    cursor.execute("""
        INSERT OR REPLACE INTO schedule_groups 
        (id, waste_type, kaimai_hash, dates, dates_hash, first_date, last_date, date_count, calendar_id, calendar_synced_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
    """, (
        schedule_group_id,
        waste_type,
        kaimai_hash,
        json.dumps([d.isoformat() if isinstance(d, date) else d for d in dates]),
        dates_hash,
        dates[0] if dates else None,
        dates[-1] if dates else None,
        len(dates),
        calendar_id
    ))
    
    # Create location
    cursor.execute("""
        INSERT OR REPLACE INTO locations 
        (seniunija, village, street, kaimai_hash)
        VALUES (?, ?, ?, ?)
    """, ("Test", "Village", "Street", kaimai_hash))
    
    conn.commit()
    return schedule_group_id


def test_sync_adds_new_events(temp_db):
    """Test that sync adds new events for new dates"""
    conn, db_path = temp_db
    
    kaimai_hash = "k1_test_sync_add"
    waste_type = "bendros"
    calendar_id = "test_calendar_add@google.com"
    
    # Create schedule group with initial dates
    dates1 = [date(2026, 1, 8), date(2026, 1, 22)]
    schedule_group_id = create_test_schedule_group_with_calendar(
        temp_db, kaimai_hash, waste_type, dates1, calendar_id
    )
    
    # Mock Google Calendar service
    mock_service = MagicMock()
    mock_event = {'id': 'event123'}
    mock_service.events().insert().execute.return_value = mock_event
    
    with patch('services.calendar.get_google_calendar_service', return_value=mock_service):
        # Sync with new dates (add one more)
        dates2 = [date(2026, 1, 8), date(2026, 1, 22), date(2026, 2, 5)]
        find_or_create_schedule_group(conn, dates2, waste_type, kaimai_hash)
        conn.commit()
        
        # Update schedule group dates
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE schedule_groups 
            SET dates = ?, dates_hash = ?, calendar_synced_at = NULL
            WHERE id = ?
        """, (json.dumps([d.isoformat() for d in dates2]), generate_dates_hash(dates2), schedule_group_id))
        
        # Pre-populate calendar_events with existing events (simulate previous sync)
        cursor.execute("""
            INSERT INTO calendar_events (schedule_group_id, date, event_id, status)
            VALUES (?, ?, ?, 'created'),
                   (?, ?, ?, 'created')
        """, (
            schedule_group_id, "2026-01-08", "event1",
            schedule_group_id, "2026-01-22", "event2"
        ))
        conn.commit()
        
        # Sync events
        result = sync_calendar_for_schedule_group(schedule_group_id)
        
        assert result['success'] is True
        assert result['events_added'] == 1, "Should add 1 new event"
        assert result['events_deleted'] == 0, "Should not delete any events"
        
        # Verify calendar_events table
        cursor.execute("""
            SELECT date, event_id, status FROM calendar_events 
            WHERE schedule_group_id = ? ORDER BY date
        """, (schedule_group_id,))
        events = cursor.fetchall()
        
        assert len(events) == 3, "Should have 3 events in calendar_events"
        assert all(e[2] == 'created' for e in events), "All events should be 'created'"


def test_sync_deletes_old_events(temp_db):
    """Test that sync deletes events for removed dates"""
    conn, db_path = temp_db
    
    kaimai_hash = "k1_test_sync_delete"
    waste_type = "bendros"
    calendar_id = "test_calendar_delete@google.com"
    
    # Create schedule group with initial dates
    dates1 = ["2026-01-08", "2026-01-22", "2026-02-05"]
    schedule_group_id = create_test_schedule_group_with_calendar(
        temp_db, kaimai_hash, waste_type, dates1, calendar_id
    )
    
    # Pre-populate calendar_events (simulate existing events)
    cursor = conn.cursor()
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
    
    # Mock Google Calendar service
    mock_service = MagicMock()
    
    with patch('services.calendar.get_google_calendar_service', return_value=mock_service):
        # Update with fewer dates (remove one)
        dates2 = ["2026-01-08", "2026-01-22"]
        cursor.execute("""
            UPDATE schedule_groups 
            SET dates = ?, dates_hash = ?, calendar_synced_at = NULL
            WHERE id = ?
        """, (json.dumps(dates2), generate_dates_hash([datetime.strptime(d, "%Y-%m-%d").date() for d in dates2]), schedule_group_id))
        conn.commit()
        
        # Sync events
        result = sync_calendar_for_schedule_group(schedule_group_id)
        
        assert result['success'] is True
        assert result['events_deleted'] == 1, "Should delete 1 old event"
        assert result['events_added'] == 0, "Should not add any events"
        
        # Verify calendar_events table (should have 2 events)
        cursor.execute("""
            SELECT date, event_id FROM calendar_events 
            WHERE schedule_group_id = ? ORDER BY date
        """, (schedule_group_id,))
        events = cursor.fetchall()
        
        assert len(events) == 2, "Should have 2 events remaining"
        assert all(d[0] in dates2 for d in events), "Remaining events should match new dates"
        
        # Verify delete was called
        assert mock_service.events().delete.call_count == 1, "Should call delete once"


def test_sync_updates_mixed_changes(temp_db):
    """Test sync with both additions and deletions"""
    conn, db_path = temp_db
    
    kaimai_hash = "k1_test_sync_mixed"
    waste_type = "bendros"
    calendar_id = "test_calendar_mixed@google.com"
    
    # Create schedule group with initial dates
    dates1 = ["2026-01-08", "2026-01-22"]
    schedule_group_id = create_test_schedule_group_with_calendar(
        temp_db, kaimai_hash, waste_type, dates1, calendar_id
    )
    
    # Pre-populate calendar_events
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO calendar_events (schedule_group_id, date, event_id, status)
        VALUES (?, ?, ?, 'created'),
               (?, ?, ?, 'created')
    """, (
        schedule_group_id, "2026-01-08", "event1",
        schedule_group_id, "2026-01-22", "event2"
    ))
    conn.commit()
    
    # Mock Google Calendar service
    mock_service = MagicMock()
    mock_event = {'id': 'event_new'}
    mock_service.events().insert().execute.return_value = mock_event
    
    with patch('services.calendar.get_google_calendar_service', return_value=mock_service):
        # Update with different dates (remove one, add one)
        dates2 = ["2026-01-22", "2026-02-05"]
        cursor.execute("""
            UPDATE schedule_groups 
            SET dates = ?, dates_hash = ?, calendar_synced_at = NULL
            WHERE id = ?
        """, (json.dumps(dates2), generate_dates_hash([datetime.strptime(d, "%Y-%m-%d").date() for d in dates2]), schedule_group_id))
        conn.commit()
        
        # Sync events
        result = sync_calendar_for_schedule_group(schedule_group_id)
        
        assert result['success'] is True
        assert result['events_deleted'] == 1, "Should delete 1 old event"
        assert result['events_added'] == 1, "Should add 1 new event"
        
        # Verify calendar_events table
        cursor.execute("""
            SELECT date, event_id, status FROM calendar_events 
            WHERE schedule_group_id = ? ORDER BY date
        """, (schedule_group_id,))
        events = cursor.fetchall()
        
        assert len(events) == 2, "Should have 2 events"
        assert all(e[0] in dates2 for e in events), "Events should match new dates"


def test_sync_retries_failed_events(temp_db):
    """Test that sync retries events with status='error'"""
    conn, db_path = temp_db
    
    kaimai_hash = "k1_test_sync_retry"
    waste_type = "bendros"
    calendar_id = "test_calendar_retry@google.com"
    
    # Create schedule group
    dates = ["2026-01-08", "2026-01-22"]
    schedule_group_id = create_test_schedule_group_with_calendar(
        temp_db, kaimai_hash, waste_type, dates, calendar_id
    )
    
    # Pre-populate calendar_events with one failed event
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO calendar_events (schedule_group_id, date, event_id, status, error_message)
        VALUES (?, ?, NULL, 'error', 'Previous error'),
               (?, ?, ?, 'created', NULL)
    """, (
        schedule_group_id, "2026-01-08",
        schedule_group_id, "2026-01-22", "event2"
    ))
    conn.commit()
    
    # Mock Google Calendar service
    mock_service = MagicMock()
    mock_event = {'id': 'event_retried'}
    mock_service.events().insert().execute.return_value = mock_event
    
    with patch('services.calendar.get_google_calendar_service', return_value=mock_service):
        # Sync events
        result = sync_calendar_for_schedule_group(schedule_group_id)
        
        assert result['success'] is True
        assert result['events_retried'] == 1, "Should retry 1 failed event"
        
        # Verify calendar_events table
        cursor.execute("""
            SELECT date, event_id, status, error_message FROM calendar_events 
            WHERE schedule_group_id = ? AND date = ?
        """, (schedule_group_id, "2026-01-08"))
        event = cursor.fetchone()
        
        assert event[1] == 'event_retried', "Event ID should be updated"
        assert event[2] == 'created', "Status should be 'created'"
        assert event[3] is None, "Error message should be cleared"


def test_sync_handles_errors_gracefully(temp_db):
    """Test that sync handles API errors gracefully"""
    conn, db_path = temp_db
    
    kaimai_hash = "k1_test_sync_error"
    waste_type = "bendros"
    calendar_id = "test_calendar_error@google.com"
    
    # Create schedule group
    dates = ["2026-01-08"]
    schedule_group_id = create_test_schedule_group_with_calendar(
        temp_db, kaimai_hash, waste_type, dates, calendar_id
    )
    
    # Mock Google Calendar service to raise error
    mock_service = MagicMock()
    mock_service.events().insert().execute.side_effect = Exception("API Error")
    
    with patch('services.calendar.get_google_calendar_service', return_value=mock_service):
        # Sync events
        result = sync_calendar_for_schedule_group(schedule_group_id)
        
        assert result['success'] is True, "Sync should complete (with errors logged)"
        assert result['events_added'] == 0, "Should not add any events due to error"
        
        # Verify error is stored in calendar_events
        cursor = conn.cursor()
        cursor.execute("""
            SELECT status, error_message FROM calendar_events 
            WHERE schedule_group_id = ? AND date = ?
        """, (schedule_group_id, "2026-01-08"))
        event = cursor.fetchone()
        
        assert event[0] == 'error', "Status should be 'error'"
        assert event[1] is not None, "Error message should be stored"


def test_sync_empty_dates(temp_db):
    """Test sync with empty dates list"""
    conn, db_path = temp_db
    
    kaimai_hash = "k1_test_sync_empty"
    waste_type = "bendros"
    calendar_id = "test_calendar_empty@google.com"
    
    # Create schedule group with empty dates
    schedule_group_id = create_test_schedule_group_with_calendar(
        temp_db, kaimai_hash, waste_type, [], calendar_id
    )
    
    # Sync events
    result = sync_calendar_for_schedule_group(schedule_group_id)
    
    assert result['success'] is True
    assert result['events_added'] == 0
    assert result['events_deleted'] == 0
    
    # Verify calendar_synced_at is set (empty schedule is valid)
    cursor = conn.cursor()
    cursor.execute("SELECT calendar_synced_at FROM schedule_groups WHERE id = ?", (schedule_group_id,))
    row = cursor.fetchone()
    assert row[0] is not None, "calendar_synced_at should be set even for empty schedule"
