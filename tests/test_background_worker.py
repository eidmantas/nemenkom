"""
Tests for background calendar sync worker
Tests that worker correctly identifies and processes schedule groups needing sync
"""
import pytest
import sqlite3
from datetime import date, datetime
import json
import time
from unittest.mock import patch, MagicMock, call
from services.common.db import get_db_connection
from services.scraper.core.db_writer import (
    find_or_create_schedule_group,
    find_or_create_calendar_stream,
    upsert_group_calendar_link,
)
from services.common.db_helpers import (
    get_calendar_streams_needing_sync,
    update_calendar_stream_calendar_id,
    update_calendar_stream_calendar_synced,
)
from services.calendar import (
    create_calendar_for_calendar_stream,
    sync_calendar_for_calendar_stream,
)


def test_get_schedule_groups_needing_sync_filters_correctly(temp_db):
    """Test that get_calendar_streams_needing_sync returns only streams needing sync"""
    conn, db_path = temp_db
    
    # Create groups with different states
    kaimai_hash1 = "k1_test_worker1"
    kaimai_hash2 = "k1_test_worker2"
    kaimai_hash3 = "k1_test_worker3"
    waste_type = "bendros"
    dates1 = [date(2026, 1, 8)]
    dates2 = [date(2026, 1, 15)]
    dates3 = [date(2026, 1, 22)]
    
    # Stream 1: No calendar (needs sync)
    schedule_group_id1 = find_or_create_schedule_group(conn, dates1, waste_type, kaimai_hash1)
    calendar_stream_id1 = find_or_create_calendar_stream(conn, dates1, waste_type)
    upsert_group_calendar_link(conn, schedule_group_id1, calendar_stream_id1)
    
    # Stream 2: Calendar exists but not synced (needs sync)
    schedule_group_id2 = find_or_create_schedule_group(conn, dates2, waste_type, kaimai_hash2)
    calendar_stream_id2 = find_or_create_calendar_stream(conn, dates2, waste_type)
    upsert_group_calendar_link(conn, schedule_group_id2, calendar_stream_id2)
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE calendar_streams
        SET calendar_id = 'test_calendar2@google.com'
        WHERE id = ?
    """, (calendar_stream_id2,))
    
    # Stream 3: Calendar synced (doesn't need sync)
    schedule_group_id3 = find_or_create_schedule_group(conn, dates3, waste_type, kaimai_hash3)
    calendar_stream_id3 = find_or_create_calendar_stream(conn, dates3, waste_type)
    upsert_group_calendar_link(conn, schedule_group_id3, calendar_stream_id3)
    cursor.execute("""
        UPDATE calendar_streams 
        SET calendar_id = 'test_calendar3@google.com',
            calendar_synced_at = CURRENT_TIMESTAMP
        WHERE id = ?
    """, (calendar_stream_id3,))
    
    conn.commit()
    
    # Get groups needing sync
    groups = get_calendar_streams_needing_sync()
    
    group_ids = [g['id'] for g in groups]
    assert calendar_stream_id1 in group_ids, "Stream 1 should need sync (no calendar)"
    assert calendar_stream_id2 in group_ids, "Stream 2 should need sync (not synced)"
    assert calendar_stream_id3 not in group_ids, "Stream 3 should not need sync (already synced)"


def test_worker_creates_calendar_for_new_groups(temp_db):
    """Test that worker creates calendar for groups without calendar_id"""
    conn, db_path = temp_db
    
    kaimai_hash = "k1_test_worker_create"
    waste_type = "bendros"
    dates = [date(2026, 1, 8)]
    
    schedule_group_id = find_or_create_schedule_group(conn, dates, waste_type, kaimai_hash)
    calendar_stream_id = find_or_create_calendar_stream(conn, dates, waste_type)
    upsert_group_calendar_link(conn, schedule_group_id, calendar_stream_id)
    
    # Create location
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO locations (seniunija, village, street, kaimai_hash)
        VALUES (?, ?, ?, ?)
    """, ("Test", "Village", "Street", kaimai_hash))
    conn.commit()
    
    # Mock calendar creation
    mock_service = MagicMock()
    mock_calendar = {'id': 'worker_calendar@google.com', 'summary': 'Worker Calendar'}
    mock_service.calendars().insert().execute.return_value = mock_calendar
    
    with patch('services.calendar.get_google_calendar_service', return_value=mock_service):
        # Simulate worker processing
        streams = get_calendar_streams_needing_sync()
        for stream in streams:
            if stream['id'] == calendar_stream_id:
                if stream['calendar_id'] is None:
                    result = create_calendar_for_calendar_stream(stream['id'])
                    assert result['success'] is True
                    assert result['calendar_id'] == 'worker_calendar@google.com'
    
    # Verify calendar_id is stored
    cursor.execute("SELECT calendar_id FROM calendar_streams WHERE id = ?", (calendar_stream_id,))
    row = cursor.fetchone()
    assert row[0] == 'worker_calendar@google.com', "Calendar ID should be stored"


def test_worker_syncs_events_for_unsynced_calendars(temp_db):
    """Test that worker syncs events for calendars with calendar_id but no calendar_synced_at"""
    conn, db_path = temp_db
    
    kaimai_hash = "k1_test_worker_sync"
    waste_type = "bendros"
    dates = [date(2026, 1, 8), date(2026, 1, 22)]
    
    schedule_group_id = find_or_create_schedule_group(conn, dates, waste_type, kaimai_hash)
    calendar_stream_id = find_or_create_calendar_stream(conn, dates, waste_type)
    upsert_group_calendar_link(conn, schedule_group_id, calendar_stream_id)
    
    # Set calendar_id but not calendar_synced_at
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE calendar_streams 
        SET calendar_id = 'test_calendar@google.com'
        WHERE id = ?
    """, (calendar_stream_id,))
    conn.commit()
    
    # Create location
    cursor.execute("""
        INSERT INTO locations (seniunija, village, street, kaimai_hash)
        VALUES (?, ?, ?, ?)
    """, ("Test", "Village", "Street", kaimai_hash))
    conn.commit()
    
    # Mock calendar service
    mock_service = MagicMock()
    mock_event = {'id': 'event123'}
    mock_service.events().insert().execute.return_value = mock_event
    
    with patch('services.calendar.get_google_calendar_service', return_value=mock_service):
        # Simulate worker processing
        streams = get_calendar_streams_needing_sync()
        for stream in streams:
            if stream['id'] == calendar_stream_id:
                if stream['calendar_id'] is not None:
                    result = sync_calendar_for_calendar_stream(stream['id'])
                    assert result['success'] is True
                    assert result['events_added'] == 2, "Should add 2 events"
    
    # Verify calendar_synced_at is set
    cursor.execute("SELECT calendar_synced_at FROM calendar_streams WHERE id = ?", (calendar_stream_id,))
    row = cursor.fetchone()
    assert row[0] is not None, "calendar_synced_at should be set after sync"


def test_worker_handles_date_changes(temp_db):
    """Test that worker detects date changes and re-syncs events"""
    conn, db_path = temp_db
    
    kaimai_hash = "k1_test_worker_changes"
    waste_type = "bendros"
    dates1 = [date(2026, 1, 8), date(2026, 1, 22)]
    dates2 = [date(2026, 2, 5), date(2026, 2, 19)]  # Different dates
    
    # Create schedule group and calendar stream
    schedule_group_id = find_or_create_schedule_group(conn, dates1, waste_type, kaimai_hash)
    calendar_stream_id1 = find_or_create_calendar_stream(conn, dates1, waste_type)
    upsert_group_calendar_link(conn, schedule_group_id, calendar_stream_id1)
    
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE calendar_streams 
        SET calendar_id = 'test_calendar@google.com',
            calendar_synced_at = CURRENT_TIMESTAMP
        WHERE id = ?
    """, (calendar_stream_id1,))
    conn.commit()
    
    # Create location
    cursor.execute("""
        INSERT INTO locations (seniunija, village, street, kaimai_hash)
        VALUES (?, ?, ?, ?)
    """, ("Test", "Village", "Street", kaimai_hash))
    conn.commit()
    
    # Pre-populate calendar_stream_events (simulate existing events)
    cursor.execute("""
        INSERT INTO calendar_stream_events (calendar_stream_id, date, event_id, status)
        VALUES (?, ?, ?, 'created'),
               (?, ?, ?, 'created')
    """, (
        calendar_stream_id1, "2026-01-08", "event1",
        calendar_stream_id1, "2026-01-22", "event2"
    ))
    conn.commit()
    
    # Change dates (new calendar stream)
    schedule_group_id = find_or_create_schedule_group(conn, dates2, waste_type, kaimai_hash)
    calendar_stream_id2 = find_or_create_calendar_stream(conn, dates2, waste_type)
    upsert_group_calendar_link(conn, schedule_group_id, calendar_stream_id2)
    conn.commit()
    
    # Verify new stream has no sync timestamp
    cursor.execute("SELECT calendar_synced_at FROM calendar_streams WHERE id = ?", (calendar_stream_id2,))
    row = cursor.fetchone()
    assert row[0] is None, "calendar_synced_at should be NULL for new stream"
    
    # Mock calendar service
    mock_service = MagicMock()
    mock_event = {'id': 'event_new'}
    mock_service.events().insert().execute.return_value = mock_event
    
    with patch('services.calendar.get_google_calendar_service', return_value=mock_service):
        # Worker should detect and sync
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE calendar_streams
            SET calendar_id = 'test_calendar_new@google.com'
            WHERE id = ?
        """, (calendar_stream_id2,))
        conn.commit()

        streams = get_calendar_streams_needing_sync()
        for stream in streams:
            if stream['id'] == calendar_stream_id2:
                result = sync_calendar_for_calendar_stream(stream['id'])
                assert result['success'] is True
                assert result['events_added'] == 2, "Should add 2 new events"
    
    # Verify calendar_synced_at is set again
    cursor.execute("SELECT calendar_synced_at FROM calendar_streams WHERE id = ?", (calendar_stream_id2,))
    row = cursor.fetchone()
    assert row[0] is not None, "calendar_synced_at should be set after re-sync"


def test_worker_processes_multiple_groups(temp_db):
    """Test that worker can process multiple groups needing sync"""
    conn, db_path = temp_db
    
    # Create multiple groups needing sync
    groups_to_create = [
        ("k1_test_worker_multi1", "bendros", [date(2026, 1, 8)]),
        ("k1_test_worker_multi2", "plastikas", [date(2026, 1, 15)]),
        ("k1_test_worker_multi3", "bendros", [date(2026, 1, 22)]),
    ]
    
    schedule_group_ids = []
    calendar_stream_ids = []
    for kaimai_hash, waste_type, dates in groups_to_create:
        schedule_group_id = find_or_create_schedule_group(conn, dates, waste_type, kaimai_hash)
        calendar_stream_id = find_or_create_calendar_stream(conn, dates, waste_type)
        upsert_group_calendar_link(conn, schedule_group_id, calendar_stream_id)
        schedule_group_ids.append(schedule_group_id)
        calendar_stream_ids.append(calendar_stream_id)
        
        # Create location
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO locations (seniunija, village, street, kaimai_hash)
            VALUES (?, ?, ?, ?)
        """, ("Test", "Village", f"Street {kaimai_hash}", kaimai_hash))
    
    conn.commit()
    
    # Mock calendar service
    mock_service = MagicMock()
    mock_calendar = {'id': 'multi_calendar@google.com', 'summary': 'Multi Calendar'}
    mock_service.calendars().insert().execute.return_value = mock_calendar
    mock_event = {'id': 'event_multi'}
    mock_service.events().insert().execute.return_value = mock_event
    
    with patch('services.calendar.get_google_calendar_service', return_value=mock_service):
        # Simulate worker processing all groups
        streams = get_calendar_streams_needing_sync()
        processed = 0

        for stream in streams:
            if stream['id'] in calendar_stream_ids:
                if stream['calendar_id'] is None:
                    result = create_calendar_for_calendar_stream(stream['id'])
                    assert result['success'] is True

                result = sync_calendar_for_calendar_stream(stream['id'])
                assert result['success'] is True
                processed += 1

        assert processed == len(calendar_stream_ids), f"Should process {len(calendar_stream_ids)} streams"
    
    # Verify all groups are synced
    cursor = conn.cursor()
    cursor.execute("""
        SELECT COUNT(*) FROM calendar_streams 
        WHERE id IN ({}) AND calendar_synced_at IS NOT NULL
    """.format(','.join(['?'] * len(calendar_stream_ids))), calendar_stream_ids)
    
    count = cursor.fetchone()[0]
    assert count == len(calendar_stream_ids), "All streams should be synced"
