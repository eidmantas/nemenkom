"""
Tests for calendar status tracking and API responses
Tests that calendar_status is correctly returned in API endpoints
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
from services.api.db import (
    get_location_schedule,
    get_calendar_status,
    get_schedule_groups_needing_sync,
    update_schedule_group_calendar_id,
    update_schedule_group_calendar_synced
)


def test_calendar_status_pending():
    """Test calendar_status when calendar doesn't exist yet"""
    status = get_calendar_status(None, None)
    
    assert status['status'] == 'pending'
    assert status['calendar_id'] is None


def test_calendar_status_needs_update():
    """Test calendar_status when calendar exists but dates changed"""
    calendar_id = "test_calendar@google.com"
    status = get_calendar_status(calendar_id, None)
    
    assert status['status'] == 'needs_update'
    assert status['calendar_id'] == calendar_id


def test_calendar_status_synced():
    """Test calendar_status when calendar is synced"""
    calendar_id = "test_calendar@google.com"
    status = get_calendar_status(calendar_id, "2026-01-01 12:00:00")
    
    assert status['status'] == 'synced'
    assert status['calendar_id'] == calendar_id


def test_get_location_schedule_includes_calendar_status(temp_db):
    """Test that get_location_schedule returns calendar_status"""
    conn, db_path = temp_db
    
    # Create location and schedule group
    kaimai_hash = "k1_test_status"
    waste_type = "bendros"
    dates = [date(2026, 1, 8), date(2026, 1, 22)]
    
    schedule_group_id = find_or_create_schedule_group(conn, dates, waste_type, kaimai_hash)
    
    # Create location
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO locations (seniunija, village, street, kaimai_hash)
        VALUES (?, ?, ?, ?)
    """, ("Test", "Village", "Street", kaimai_hash))
    location_id = cursor.lastrowid
    conn.commit()
    
    # Test without calendar (pending)
    schedule = get_location_schedule(location_id=location_id, waste_type=waste_type)
    
    assert schedule is not None
    assert 'calendar_status' in schedule
    assert schedule['calendar_status']['status'] == 'pending'
    assert schedule['calendar_status']['calendar_id'] is None
    
    # Add calendar_id but not synced (needs_update)
    update_schedule_group_calendar_id(schedule_group_id, "test_calendar@google.com")
    schedule = get_location_schedule(location_id=location_id, waste_type=waste_type)
    
    assert schedule['calendar_status']['status'] == 'needs_update'
    assert schedule['calendar_status']['calendar_id'] == "test_calendar@google.com"
    
    # Mark as synced
    update_schedule_group_calendar_synced(schedule_group_id)
    schedule = get_location_schedule(location_id=location_id, waste_type=waste_type)
    
    assert schedule['calendar_status']['status'] == 'synced'
    assert schedule['calendar_status']['calendar_id'] == "test_calendar@google.com"
    assert 'subscription_link' in schedule
    assert schedule['subscription_link'].startswith("https://calendar.google.com/calendar/render?cid=")


def test_get_schedule_groups_needing_sync(temp_db):
    """Test that get_schedule_groups_needing_sync returns correct groups"""
    conn, db_path = temp_db
    
    # Create groups with different states
    kaimai_hash1 = "k1_test_sync1"
    kaimai_hash2 = "k1_test_sync2"
    kaimai_hash3 = "k1_test_sync3"
    waste_type = "bendros"
    dates = [date(2026, 1, 8)]
    
    # Group 1: No calendar (needs sync)
    schedule_group_id1 = find_or_create_schedule_group(conn, dates, waste_type, kaimai_hash1)
    
    # Group 2: Calendar exists but not synced (needs sync)
    schedule_group_id2 = find_or_create_schedule_group(conn, dates, waste_type, kaimai_hash2)
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE schedule_groups 
        SET calendar_id = 'test_calendar2@google.com'
        WHERE id = ?
    """, (schedule_group_id2,))
    
    # Group 3: Calendar synced (doesn't need sync)
    schedule_group_id3 = find_or_create_schedule_group(conn, dates, waste_type, kaimai_hash3)
    cursor.execute("""
        UPDATE schedule_groups 
        SET calendar_id = 'test_calendar3@google.com',
            calendar_synced_at = CURRENT_TIMESTAMP
        WHERE id = ?
    """, (schedule_group_id3,))
    
    conn.commit()
    
    # Get groups needing sync
    groups = get_schedule_groups_needing_sync()
    
    group_ids = [g['id'] for g in groups]
    assert schedule_group_id1 in group_ids, "Group 1 should need sync (no calendar)"
    assert schedule_group_id2 in group_ids, "Group 2 should need sync (not synced)"
    assert schedule_group_id3 not in group_ids, "Group 3 should not need sync (already synced)"


def test_calendar_status_transitions(temp_db):
    """Test calendar status transitions through lifecycle"""
    conn, db_path = temp_db
    
    kaimai_hash = "k1_test_transitions"
    waste_type = "bendros"
    dates = [date(2026, 1, 8)]
    
    schedule_group_id = find_or_create_schedule_group(conn, dates, waste_type, kaimai_hash)
    conn.commit()
    
    # State 1: CREATED (pending)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT calendar_id, calendar_synced_at FROM schedule_groups WHERE id = ?
    """, (schedule_group_id,))
    row = cursor.fetchone()
    assert row[0] is None, "calendar_id should be NULL"
    assert row[1] is None, "calendar_synced_at should be NULL"
    
    status = get_calendar_status(row[0], row[1])
    assert status['status'] == 'pending'
    
    # State 2: CALENDAR_CREATED (needs_update)
    update_schedule_group_calendar_id(schedule_group_id, "test_calendar@google.com")
    cursor.execute("""
        SELECT calendar_id, calendar_synced_at FROM schedule_groups WHERE id = ?
    """, (schedule_group_id,))
    row = cursor.fetchone()
    assert row[0] is not None, "calendar_id should be set"
    assert row[1] is None, "calendar_synced_at should still be NULL"
    
    status = get_calendar_status(row[0], row[1])
    assert status['status'] == 'needs_update'
    
    # State 3: SYNCED
    update_schedule_group_calendar_synced(schedule_group_id)
    cursor.execute("""
        SELECT calendar_id, calendar_synced_at FROM schedule_groups WHERE id = ?
    """, (schedule_group_id,))
    row = cursor.fetchone()
    assert row[0] is not None, "calendar_id should be set"
    assert row[1] is not None, "calendar_synced_at should be set"
    
    status = get_calendar_status(row[0], row[1])
    assert status['status'] == 'synced'
    
    # State 4: NEEDS_UPDATE (dates changed)
    dates2 = [date(2026, 2, 5)]
    find_or_create_schedule_group(conn, dates2, waste_type, kaimai_hash)
    conn.commit()
    
    cursor.execute("""
        SELECT calendar_id, calendar_synced_at FROM schedule_groups WHERE id = ?
    """, (schedule_group_id,))
    row = cursor.fetchone()
    assert row[0] is not None, "calendar_id should remain (stable calendar)"
    assert row[1] is None, "calendar_synced_at should be NULL (triggers re-sync)"
    
    status = get_calendar_status(row[0], row[1])
    assert status['status'] == 'needs_update'


def test_api_response_includes_subscription_link(temp_db):
    """Test that API response includes subscription_link when calendar exists"""
    conn, db_path = temp_db
    
    kaimai_hash = "k1_test_subscription"
    waste_type = "bendros"
    dates = [date(2026, 1, 8)]
    
    schedule_group_id = find_or_create_schedule_group(conn, dates, waste_type, kaimai_hash)
    
    # Create location
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO locations (seniunija, village, street, kaimai_hash)
        VALUES (?, ?, ?, ?)
    """, ("Test", "Village", "Street", kaimai_hash))
    location_id = cursor.lastrowid
    conn.commit()
    
    # Without calendar
    schedule = get_location_schedule(location_id=location_id, waste_type=waste_type)
    assert 'subscription_link' not in schedule or schedule.get('subscription_link') is None
    
    # With calendar
    calendar_id = "test_calendar@google.com"
    update_schedule_group_calendar_id(schedule_group_id, calendar_id)
    update_schedule_group_calendar_synced(schedule_group_id)
    
    schedule = get_location_schedule(location_id=location_id, waste_type=waste_type)
    assert 'subscription_link' in schedule
    assert schedule['subscription_link'] == f"https://calendar.google.com/calendar/render?cid={calendar_id}"
