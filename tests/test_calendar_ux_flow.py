"""
UX-focused tests for calendar subscription stability.
"""

from datetime import date

from services.api.db import get_location_schedule
from services.scraper.core.db_writer import (
    find_or_create_calendar_stream,
    find_or_create_schedule_group,
    reconcile_calendar_streams,
    upsert_group_calendar_link,
)


def test_subscription_calendar_stays_stable_on_date_change(temp_db):
    """
    A user subscribes by address; the calendar link must remain stable
    when dates update, and the calendar should be marked for re-sync.
    """
    conn, _ = temp_db

    kaimai_hash = "k1_test_ux_stable"
    waste_type = "bendros"
    dates1 = [date(2026, 1, 8), date(2026, 1, 22)]
    dates2 = [date(2026, 2, 5), date(2026, 2, 19)]

    # Create schedule group + stream and link
    schedule_group_id = find_or_create_schedule_group(conn, dates1, waste_type, kaimai_hash)
    calendar_stream_id = find_or_create_calendar_stream(conn, dates1, waste_type)
    upsert_group_calendar_link(conn, schedule_group_id, calendar_stream_id)

    # Create location
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO locations (seniunija, village, street, house_numbers, kaimai_hash)
        VALUES (?, ?, ?, ?, ?)
    """,
        ("Test", "Village", "Street", "1-10", kaimai_hash),
    )
    location_id = cursor.lastrowid

    # Set calendar_id and mark synced
    cursor.execute(
        """
        UPDATE calendar_streams
        SET calendar_id = 'ux_calendar@google.com',
            calendar_synced_at = CURRENT_TIMESTAMP
        WHERE id = ?
    """,
        (calendar_stream_id,),
    )
    conn.commit()

    # User sees subscription link
    schedule = get_location_schedule(location_id=location_id, waste_type=waste_type)
    assert schedule["calendar_id"] == "ux_calendar@google.com"
    assert schedule["calendar_status"]["status"] == "synced"

    # Dates change for this address group
    schedule_group_id = find_or_create_schedule_group(conn, dates2, waste_type, kaimai_hash)
    reconcile_calendar_streams(conn)
    conn.commit()

    # Calendar link remains stable, but needs update
    schedule = get_location_schedule(location_id=location_id, waste_type=waste_type)
    assert schedule["calendar_id"] == "ux_calendar@google.com"
    assert schedule["calendar_status"]["status"] == "needs_update"
