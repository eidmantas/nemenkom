"""
Tests for in-place calendar updates when dates change
Ensures that when dates are updated (same months), events update in place
"""

from datetime import date
from unittest.mock import MagicMock, patch

from services.calendar import sync_calendar_for_calendar_stream
from services.common.db_helpers import update_calendar_stream_calendar_id
from services.scraper.core.db_writer import (
    find_or_create_calendar_stream,
    find_or_create_schedule_group,
    upsert_group_calendar_link,
)


def test_in_place_update_some_dates_change(temp_db):
    """Test that when some dates change, only changed dates are updated"""
    conn, _db_path = temp_db

    kaimai_hash = "k1_test_inplace"
    waste_type = "bendros"
    calendar_id = "test_calendar@google.com"

    # Current dates for the stream
    dates_current = [date(2026, 1, 8), date(2026, 1, 29), date(2026, 2, 12)]
    schedule_group_id = find_or_create_schedule_group(conn, dates_current, waste_type, kaimai_hash)
    calendar_stream_id = find_or_create_calendar_stream(conn, dates_current, waste_type)
    upsert_group_calendar_link(conn, schedule_group_id, calendar_stream_id)

    # Create location
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO locations (seniunija, village, street, kaimai_hash)
        VALUES (?, ?, ?, ?)
    """,
        ("Test", "Village", "Street", kaimai_hash),
    )
    conn.commit()

    # Set calendar_id
    update_calendar_stream_calendar_id(calendar_stream_id, calendar_id)

    # Pre-populate calendar_stream_events with outdated dates
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
    mock_event_new = {"id": "event_new"}
    mock_service.events().insert().execute.return_value = mock_event_new

    with patch("services.calendar.get_google_calendar_service", return_value=mock_service):
        # Sync events
        result = sync_calendar_for_calendar_stream(calendar_stream_id)

        assert result["success"] is True
        assert result["events_deleted"] == 2, "Should delete 2 old events (1-22 and 2-5)"
        assert result["events_added"] == 2, "Should add 2 new events (1-29 and 2-12)"

        # Verify calendar_stream_events table
        cursor.execute(
            """
            SELECT date, event_id, status FROM calendar_stream_events
            WHERE calendar_stream_id = ? ORDER BY date
        """,
            (calendar_stream_id,),
        )
        events = cursor.fetchall()

        event_dates = {e[0] for e in events}
        assert event_dates == {"2026-01-08", "2026-01-29", "2026-02-12"}, (
            "Should have updated dates"
        )

        # Verify event1 (2026-01-08) is still there (unchanged)
        event_1_8 = [e for e in events if e[0] == "2026-01-08"][0]
        assert event_1_8[1] == "event1", "Event for 2026-01-08 should remain unchanged"
        assert event_1_8[2] == "created", "Status should be 'created'"


def test_in_place_update_all_dates_change(temp_db):
    """Test that when all dates change, all events are updated"""
    conn, _db_path = temp_db

    kaimai_hash = "k1_test_inplace_all"
    waste_type = "bendros"
    calendar_id = "test_calendar@google.com"

    # Current dates for the stream
    dates_current = [date(2026, 2, 5), date(2026, 2, 19)]
    schedule_group_id = find_or_create_schedule_group(conn, dates_current, waste_type, kaimai_hash)
    calendar_stream_id = find_or_create_calendar_stream(conn, dates_current, waste_type)
    upsert_group_calendar_link(conn, schedule_group_id, calendar_stream_id)

    # Create location
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO locations (seniunija, village, street, kaimai_hash)
        VALUES (?, ?, ?, ?)
    """,
        ("Test", "Village", "Street", kaimai_hash),
    )
    conn.commit()

    # Set calendar_id
    update_calendar_stream_calendar_id(calendar_stream_id, calendar_id)

    # Pre-populate calendar_stream_events with outdated dates
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
    mock_event_new = {"id": "event_new"}
    mock_service.events().insert().execute.return_value = mock_event_new

    with patch("services.calendar.get_google_calendar_service", return_value=mock_service):
        # Sync events
        result = sync_calendar_for_calendar_stream(calendar_stream_id)

        assert result["success"] is True
        assert result["events_deleted"] == 2, "Should delete 2 old events"
        assert result["events_added"] == 2, "Should add 2 new events"

        # Verify calendar_stream_events table has new dates
        cursor.execute(
            """
            SELECT date FROM calendar_stream_events
            WHERE calendar_stream_id = ? ORDER BY date
        """,
            (calendar_stream_id,),
        )
        events = cursor.fetchall()

        event_dates = {e[0] for e in events}
        assert event_dates == {"2026-02-05", "2026-02-19"}, "Should have new dates"


def test_in_place_update_no_dates_change(temp_db):
    """Test that when dates don't change, no events are updated"""
    conn, _db_path = temp_db

    kaimai_hash = "k1_test_inplace_none"
    waste_type = "bendros"
    calendar_id = "test_calendar@google.com"

    # Current dates
    dates = [date(2026, 1, 8), date(2026, 1, 22)]
    schedule_group_id = find_or_create_schedule_group(conn, dates, waste_type, kaimai_hash)
    calendar_stream_id = find_or_create_calendar_stream(conn, dates, waste_type)
    upsert_group_calendar_link(conn, schedule_group_id, calendar_stream_id)

    # Create location
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO locations (seniunija, village, street, kaimai_hash)
        VALUES (?, ?, ?, ?)
    """,
        ("Test", "Village", "Street", kaimai_hash),
    )
    conn.commit()

    # Set calendar_id for stream
    update_calendar_stream_calendar_id(calendar_stream_id, calendar_id)

    # Pre-populate calendar_stream_events
    cursor.execute(
        """
        INSERT INTO calendar_stream_events (calendar_stream_id, date, event_id, status)
        VALUES (?, ?, ?, 'created'),
               (?, ?, ?, 'created')
    """,
        (calendar_stream_id, "2026-01-08", "event1", calendar_stream_id, "2026-01-22", "event2"),
    )
    conn.commit()

    # Call find_or_create again with same dates (should not trigger update)
    find_or_create_schedule_group(conn, dates, waste_type, kaimai_hash)
    conn.commit()

    # Verify stream still has calendar_id
    cursor.execute("SELECT calendar_id FROM calendar_streams WHERE id = ?", (calendar_stream_id,))
    row = cursor.fetchone()
    assert row[0] == calendar_id

    # Mock Google Calendar service (should not be called)
    mock_service = MagicMock()

    with patch("services.calendar.get_google_calendar_service", return_value=mock_service):
        # Sync events (should do nothing since dates didn't change)
        result = sync_calendar_for_calendar_stream(calendar_stream_id)

        assert result["success"] is True
        assert result["events_deleted"] == 0, "Should not delete any events"
        assert result["events_added"] == 0, "Should not add any events"

        # Verify no API calls were made
        assert mock_service.events().delete.call_count == 0, "Should not call delete"
        assert mock_service.events().insert.call_count == 0, "Should not call insert"


def test_in_place_update_calendar_id_stable(temp_db):
    """Test that calendar_id stays with the original stream when dates change"""
    conn, _db_path = temp_db

    kaimai_hash = "k1_test_stable_calendar"
    waste_type = "bendros"
    calendar_id = "stable_calendar@google.com"

    # Initial dates
    dates1 = [date(2026, 1, 8)]
    schedule_group_id = find_or_create_schedule_group(conn, dates1, waste_type, kaimai_hash)
    calendar_stream_id1 = find_or_create_calendar_stream(conn, dates1, waste_type)
    upsert_group_calendar_link(conn, schedule_group_id, calendar_stream_id1)

    # Set calendar_id on the original stream
    cursor = conn.cursor()
    cursor.execute(
        """
        UPDATE calendar_streams
        SET calendar_id = ?
        WHERE id = ?
    """,
        (calendar_id, calendar_stream_id1),
    )
    conn.commit()

    # Update dates -> new stream
    dates2 = [date(2026, 2, 5)]
    schedule_group_id = find_or_create_schedule_group(conn, dates2, waste_type, kaimai_hash)
    calendar_stream_id2 = find_or_create_calendar_stream(conn, dates2, waste_type)
    upsert_group_calendar_link(conn, schedule_group_id, calendar_stream_id2)
    conn.commit()

    # Old stream keeps its calendar_id
    cursor = conn.cursor()
    cursor.execute("SELECT calendar_id FROM calendar_streams WHERE id = ?", (calendar_stream_id1,))
    assert cursor.fetchone()[0] == calendar_id

    # New stream has no calendar_id yet
    cursor.execute("SELECT calendar_id FROM calendar_streams WHERE id = ?", (calendar_stream_id2,))
    assert cursor.fetchone()[0] is None
