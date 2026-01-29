"""
Tests for calendar event synchronization
Tests adding, deleting, and updating events when dates change
"""

import json
from datetime import date
from unittest.mock import MagicMock, patch

from services.calendar import sync_calendar_for_calendar_stream
from services.common.db_helpers import update_calendar_stream_calendar_id
from services.scraper.core.db_writer import (
    find_or_create_calendar_stream,
    find_or_create_schedule_group,
    upsert_group_calendar_link,
)


def create_test_calendar_stream_with_calendar(
    temp_db, kaimai_hash: str, waste_type: str, dates: list, calendar_id: str
):
    """Helper to create schedule group + calendar stream with calendar_id set"""
    conn, db_path = temp_db

    schedule_group_id = find_or_create_schedule_group(conn, dates, waste_type, kaimai_hash)
    calendar_stream_id = find_or_create_calendar_stream(conn, dates, waste_type)
    upsert_group_calendar_link(conn, schedule_group_id, calendar_stream_id)

    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT OR REPLACE INTO locations
        (seniunija, village, street, kaimai_hash)
        VALUES (?, ?, ?, ?)
    """,
        ("Test", "Village", "Street", kaimai_hash),
    )
    conn.commit()

    update_calendar_stream_calendar_id(calendar_stream_id, calendar_id)
    return calendar_stream_id


def test_sync_adds_new_events(temp_db):
    """Test that sync adds new events for new dates"""
    conn, db_path = temp_db

    kaimai_hash = "k1_test_sync_add"
    waste_type = "bendros"
    calendar_id = "test_calendar_add@google.com"

    # Current stream dates (3 dates)
    dates_current = [date(2026, 1, 8), date(2026, 1, 22), date(2026, 2, 5)]
    calendar_stream_id = create_test_calendar_stream_with_calendar(
        temp_db, kaimai_hash, waste_type, dates_current, calendar_id
    )

    # Mock Google Calendar service
    mock_service = MagicMock()
    mock_event = {"id": "event123"}
    mock_service.events().insert().execute.return_value = mock_event

    with patch("services.calendar.get_google_calendar_service", return_value=mock_service):
        # Pre-populate calendar_stream_events with existing events (simulate previous sync)
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO calendar_stream_events (calendar_stream_id, date, event_id, status)
            VALUES (?, ?, ?, 'created'),
                   (?, ?, ?, 'created')
        """,
            (
                calendar_stream_id,
                "2026-01-08",
                "event1",
                calendar_stream_id,
                "2026-01-22",
                "event2",
            ),
        )
        conn.commit()

        # Sync events
        result = sync_calendar_for_calendar_stream(calendar_stream_id)

        assert result["success"] is True
        assert result["events_added"] == 1, "Should add 1 new event"
        assert result["events_deleted"] == 0, "Should not delete any events"

        # Verify calendar_stream_events table
        cursor.execute(
            """
            SELECT date, event_id, status FROM calendar_stream_events
            WHERE calendar_stream_id = ? ORDER BY date
        """,
            (calendar_stream_id,),
        )
        events = cursor.fetchall()

        assert len(events) == 3, "Should have 3 events in calendar_stream_events"
        assert all(e[2] == "created" for e in events), "All events should be 'created'"


def test_sync_deletes_old_events(temp_db):
    """Test that sync deletes events for removed dates"""
    conn, db_path = temp_db

    kaimai_hash = "k1_test_sync_delete"
    waste_type = "bendros"
    calendar_id = "test_calendar_delete@google.com"

    # Current stream dates (2 dates)
    dates_current = ["2026-01-08", "2026-01-22"]
    calendar_stream_id = create_test_calendar_stream_with_calendar(
        temp_db, kaimai_hash, waste_type, dates_current, calendar_id
    )

    # Pre-populate calendar_stream_events (simulate existing events)
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO calendar_stream_events (calendar_stream_id, date, event_id, status)
        VALUES (?, ?, ?, 'created'),
               (?, ?, ?, 'created'),
               (?, ?, ?, 'created')
    """,
        (
            calendar_stream_id,
            "2026-01-08",
            "event1",
            calendar_stream_id,
            "2026-01-22",
            "event2",
            calendar_stream_id,
            "2026-02-05",
            "event3",
        ),
    )
    conn.commit()

    # Mock Google Calendar service
    mock_service = MagicMock()

    with patch("services.calendar.get_google_calendar_service", return_value=mock_service):
        # Sync events
        result = sync_calendar_for_calendar_stream(calendar_stream_id)

        assert result["success"] is True
        assert result["events_deleted"] == 1, "Should delete 1 old event"
        assert result["events_added"] == 0, "Should not add any events"

        # Verify calendar_stream_events table (should have 2 events)
        cursor.execute(
            """
            SELECT date, event_id FROM calendar_stream_events
            WHERE calendar_stream_id = ? ORDER BY date
        """,
            (calendar_stream_id,),
        )
        events = cursor.fetchall()

        assert len(events) == 2, "Should have 2 events remaining"
        assert all(d[0] in dates_current for d in events), (
            "Remaining events should match current dates"
        )

        # Verify delete was called
        assert mock_service.events().delete.call_count == 1, "Should call delete once"


def test_sync_updates_mixed_changes(temp_db):
    """Test sync with both additions and deletions"""
    conn, db_path = temp_db

    kaimai_hash = "k1_test_sync_mixed"
    waste_type = "bendros"
    calendar_id = "test_calendar_mixed@google.com"

    # Current stream dates
    dates_current = ["2026-01-22", "2026-02-05"]
    calendar_stream_id = create_test_calendar_stream_with_calendar(
        temp_db, kaimai_hash, waste_type, dates_current, calendar_id
    )

    # Pre-populate calendar_stream_events
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO calendar_stream_events (calendar_stream_id, date, event_id, status)
        VALUES (?, ?, ?, 'created'),
               (?, ?, ?, 'created')
    """,
        (calendar_stream_id, "2026-01-08", "event1", calendar_stream_id, "2026-01-22", "event2"),
    )
    conn.commit()

    # Mock Google Calendar service
    mock_service = MagicMock()
    mock_event = {"id": "event_new"}
    mock_service.events().insert().execute.return_value = mock_event

    with patch("services.calendar.get_google_calendar_service", return_value=mock_service):
        # Sync events
        result = sync_calendar_for_calendar_stream(calendar_stream_id)

        assert result["success"] is True
        assert result["events_deleted"] == 1, "Should delete 1 old event"
        assert result["events_added"] == 1, "Should add 1 new event"

        # Verify calendar_stream_events table
        cursor.execute(
            """
            SELECT date, event_id, status FROM calendar_stream_events
            WHERE calendar_stream_id = ? ORDER BY date
        """,
            (calendar_stream_id,),
        )
        events = cursor.fetchall()

        assert len(events) == 2, "Should have 2 events"
        assert all(e[0] in dates_current for e in events), "Events should match current dates"


def test_sync_retries_failed_events(temp_db):
    """Test that sync retries events with status='error'"""
    conn, db_path = temp_db

    kaimai_hash = "k1_test_sync_retry"
    waste_type = "bendros"
    calendar_id = "test_calendar_retry@google.com"

    # Create stream
    dates = ["2026-01-08", "2026-01-22"]
    calendar_stream_id = create_test_calendar_stream_with_calendar(
        temp_db, kaimai_hash, waste_type, dates, calendar_id
    )

    # Pre-populate calendar_stream_events with one failed event
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO calendar_stream_events (calendar_stream_id, date, event_id, status, error_message)
        VALUES (?, ?, NULL, 'error', 'Previous error'),
               (?, ?, ?, 'created', NULL)
    """,
        (calendar_stream_id, "2026-01-08", calendar_stream_id, "2026-01-22", "event2"),
    )
    conn.commit()

    # Mock Google Calendar service
    mock_service = MagicMock()
    mock_event = {"id": "event_retried"}
    mock_service.events().insert().execute.return_value = mock_event

    with patch("services.calendar.get_google_calendar_service", return_value=mock_service):
        # Sync events
        result = sync_calendar_for_calendar_stream(calendar_stream_id)

        assert result["success"] is True
        assert result["events_retried"] == 1, "Should retry 1 failed event"

        # Verify calendar_stream_events table
        cursor.execute(
            """
            SELECT date, event_id, status, error_message FROM calendar_stream_events
            WHERE calendar_stream_id = ? AND date = ?
        """,
            (calendar_stream_id, "2026-01-08"),
        )
        event = cursor.fetchone()

        assert event[1] == "event_retried", "Event ID should be updated"
        assert event[2] == "created", "Status should be 'created'"
        assert event[3] is None, "Error message should be cleared"


def test_sync_handles_errors_gracefully(temp_db):
    """Test that sync handles API errors gracefully"""
    conn, db_path = temp_db

    kaimai_hash = "k1_test_sync_error"
    waste_type = "bendros"
    calendar_id = "test_calendar_error@google.com"

    # Create stream
    dates = ["2026-01-08"]
    calendar_stream_id = create_test_calendar_stream_with_calendar(
        temp_db, kaimai_hash, waste_type, dates, calendar_id
    )

    # Mock Google Calendar service to raise error
    mock_service = MagicMock()
    mock_service.events().insert().execute.side_effect = Exception("API Error")

    with patch("services.calendar.get_google_calendar_service", return_value=mock_service):
        # Sync events
        result = sync_calendar_for_calendar_stream(calendar_stream_id)

        assert result["success"] is True, "Sync should complete (with errors logged)"
        assert result["events_added"] == 0, "Should not add any events due to error"

        # Verify error is stored in calendar_stream_events
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT status, error_message FROM calendar_stream_events
            WHERE calendar_stream_id = ? AND date = ?
        """,
            (calendar_stream_id, "2026-01-08"),
        )
        event = cursor.fetchone()

        assert event[0] == "error", "Status should be 'error'"
        assert event[1] is not None, "Error message should be stored"


def test_sync_empty_dates(temp_db):
    """Test sync with empty dates list"""
    conn, db_path = temp_db

    waste_type = "bendros"
    calendar_id = "test_calendar_empty@google.com"

    calendar_stream_id = f"{waste_type}:empty"
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO calendar_streams (id, waste_type, dates_hash, dates, calendar_id)
        VALUES (?, ?, ?, ?, ?)
    """,
        (calendar_stream_id, waste_type, "empty", json.dumps([]), calendar_id),
    )
    conn.commit()

    result = sync_calendar_for_calendar_stream(calendar_stream_id)

    assert result["success"] is True
    assert result["events_added"] == 0
    assert result["events_deleted"] == 0

    # Verify calendar_synced_at is set (empty schedule is valid)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT calendar_synced_at FROM calendar_streams WHERE id = ?", (calendar_stream_id,)
    )
    row = cursor.fetchone()
    assert row[0] is not None, "calendar_synced_at should be set even for empty schedule"
