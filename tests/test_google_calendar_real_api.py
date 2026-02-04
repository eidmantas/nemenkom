"""
Real API tests for Google Calendar integration
These tests make actual Google Calendar API calls
Run with: pytest tests/test_google_calendar_real_api.py -v
"""

import datetime
import os
import sys
from pathlib import Path

import pytest

from services.calendar import (
    create_calendar_for_schedule_group,
    sync_calendar_for_schedule_group,
)
from services.common.calendar_client import (
    generate_calendar_subscription_link,
    get_existing_calendar_info,
    list_available_calendars,
)
from services.scraper.core.db_writer import (
    find_or_create_calendar_stream,
    find_or_create_schedule_group,
    upsert_group_calendar_link,
)

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))
from services.common.db import get_db_connection

# Test configuration
TEST_PREFIX = "[TEST] "  # Prefix for all test calendars
TEST_SCHEDULE_GROUP_ID = "test_real_api_sg"
TEST_SENIUNIJA_NAME = f"{TEST_PREFIX}Test Seniunija"
TEST_DATES = ["2026-01-15", "2026-01-29", "2026-02-12"]
TEST_WASTE_TYPE = "bendros"
WASTE_TYPE_DISPLAY = {
    "bendros": "Bendros atliekos",
    "plastikas": "Plastikas",
    "stiklas": "Stiklas",
}

# Calendar cleanup
created_calendar_ids = []
created_schedule_group_ids = []
created_calendar_stream_ids = []


def require_calendar_result(result):
    """Skip real API tests when calendar creation fails (quota, auth, etc.)."""
    if not result:
        pytest.skip("Calendar creation failed (quota or auth issue)")


def create_test_schedule_group(
    kaimai_hash: str, waste_type: str = "bendros", dates: list = None
) -> str:
    """Create a test schedule group and link it to a calendar stream"""
    if dates is None:
        dates = TEST_DATES

    conn = get_db_connection()
    cursor = conn.cursor()

    # Create schedule group and calendar stream link
    schedule_group_id = find_or_create_schedule_group(conn, dates, waste_type, kaimai_hash)
    calendar_stream_id = find_or_create_calendar_stream(conn, dates, waste_type)
    upsert_group_calendar_link(conn, schedule_group_id, calendar_stream_id)

    # Create test location
    cursor.execute(
        """
        INSERT OR REPLACE INTO locations
        (seniunija, village, street, kaimai_hash)
        VALUES (?, ?, ?, ?)
    """,
        (TEST_SENIUNIJA_NAME, "Test Village", "Test Street", kaimai_hash),
    )

    conn.commit()
    conn.close()
    created_schedule_group_ids.append(schedule_group_id)
    if calendar_stream_id:
        created_calendar_stream_ids.append(calendar_stream_id)
    return schedule_group_id


def cleanup_test_calendars():
    """Remove all calendars with TEST_PREFIX (cleanup from previous interrupted runs)

    Calendar names are formatted as: "{seniunija} - {waste_type_display} - {short_hash}"
    So we check if the calendar name contains TEST_PREFIX via seniunija.
    """
    try:
        from services.calendar import get_google_calendar_service

        service = get_google_calendar_service()

        # Get all calendars
        calendars_result = service.calendarList().list().execute()
        calendars = calendars_result.get("items", [])

        # Find and delete all test calendars (check if TEST_PREFIX is in the name)
        deleted_count = 0
        for calendar in calendars:
            calendar_name = calendar.get("summary", "")
            # Calendar names are: "[TEST] Test Seniunija - Bendros atliekos - cs_123abc"
            if TEST_PREFIX in calendar_name:
                try:
                    service.calendars().delete(calendarId=calendar["id"]).execute()
                    deleted_count += 1
                    print(f"  Cleaned up old test calendar: {calendar_name}")
                except Exception as e:
                    print(f"  Failed to delete test calendar {calendar_name}: {e}")

        if deleted_count > 0:
            print(f" Cleaned up {deleted_count} old test calendar(s)")
        else:
            print(" No old test calendars found")

    except Exception as e:
        print(f"  Cleanup warning: {e}")


def setup_module(_module):
    """Setup for real API tests"""
    print("\nSetting up real Google Calendar API tests...")

    # Verify Service Account credentials exist
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).parent.parent))
    import config

    if not os.path.exists(config.GOOGLE_CALENDAR_CREDENTIALS_FILE):
        pytest.skip(
            f"Service Account credentials not found: {config.GOOGLE_CALENDAR_CREDENTIALS_FILE}"
        )

    # Test authentication
    try:
        from services.calendar import get_google_calendar_service

        service = get_google_calendar_service()
        # Try a simple API call to verify authentication works
        service.calendarList().list(maxResults=1).execute()
        print(" Service Account authentication verified")
    except Exception as e:
        pytest.skip(f"Service Account authentication failed: {e}")

    # Clean up any leftover test calendars from previous runs
    print("\nCleaning up old test calendars...")
    cleanup_test_calendars()

    # Ensure migrations are applied for real DB
    from services.common.migrations import init_database

    scraper_migrations = Path(__file__).parent.parent / "services" / "scraper" / "migrations"
    calendar_migrations = Path(__file__).parent.parent / "services" / "calendar" / "migrations"
    init_database(migrations_dir=scraper_migrations)
    init_database(migrations_dir=calendar_migrations)


def teardown_module(_module):
    """Cleanup after real API tests"""
    print("\nCleaning up test calendars...")

    # Delete all test calendars created during tests
    for calendar_id in created_calendar_ids:
        try:
            from services.calendar import get_google_calendar_service

            service = get_google_calendar_service()
            print(f"  Deleting calendar: {calendar_id}")
            service.calendars().delete(calendarId=calendar_id).execute()
        except Exception as e:
            print(f"  Failed to delete calendar {calendar_id}: {e}")

    # Clean up test schedule groups and streams from database
    if created_schedule_group_ids:
        conn = get_db_connection()
        cursor = conn.cursor()
        for sg_id in created_schedule_group_ids:
            cursor.execute("DELETE FROM schedule_groups WHERE id = ?", (sg_id,))
        for stream_id in created_calendar_stream_ids:
            cursor.execute("DELETE FROM calendar_streams WHERE id = ?", (stream_id,))
        conn.commit()
        conn.close()
        print(f"  Cleaned up {len(created_schedule_group_ids)} test schedule groups")

    print(" Cleanup complete")


@pytest.mark.real_api
def test_real_calendar_creation_and_cleanup():
    """
    Test complete calendar lifecycle with real Google Calendar API
    1. Create real calendar with events
    2. Verify calendar exists and has correct events
    3. Get calendar info
    4. Clean up by deleting calendar
    """
    # Create test schedule group in database (Option B)
    test_kaimai_hash = f"test_kaimai_{TEST_SCHEDULE_GROUP_ID}_creation"
    test_sg_id = create_test_schedule_group(test_kaimai_hash, TEST_WASTE_TYPE, TEST_DATES)

    # Create real calendar (phase 1: calendar only)
    result = create_calendar_for_schedule_group(schedule_group_id=test_sg_id)

    # Verify calendar was created
    require_calendar_result(result)
    assert result["success"] is True, "Calendar creation was not successful"
    assert result["calendar_id"] is not None, "Calendar ID is missing"

    # Sync events (phase 2: events)
    sync_result = sync_calendar_for_schedule_group(test_sg_id)
    assert sync_result["success"] is True, "Event sync failed"
    assert sync_result["events_added"] == len(TEST_DATES), (
        f"Expected {len(TEST_DATES)} events, got {sync_result['events_added']}"
    )

    calendar_id = result["calendar_id"]
    created_calendar_ids.append(calendar_id)  # Track for cleanup

    print(f" Created real calendar: {result['calendar_name']}")
    print(f"🔗 Subscription link: {result['subscription_link']}")

    # Verify calendar_id is stored in calendar_streams
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT cs.calendar_id
        FROM group_calendar_links gcl
        JOIN calendar_streams cs ON cs.id = gcl.calendar_stream_id
        WHERE gcl.schedule_group_id = ?
        LIMIT 1
    """,
        (test_sg_id,),
    )
    row = cursor.fetchone()
    conn.close()
    assert row and row[0] == calendar_id, "Calendar ID not stored in database"

    # Verify calendar info
    calendar_info = get_existing_calendar_info(calendar_id)
    assert calendar_info is not None, "Failed to get calendar info"
    assert calendar_info["calendar_id"] == calendar_id, "Calendar ID mismatch"
    assert TEST_SENIUNIJA_NAME in calendar_info["calendar_name"], "Calendar name format incorrect"
    assert "Bendros atliekos" in calendar_info["calendar_name"], "Calendar waste type missing"

    # Verify subscription link format
    subscription_link = generate_calendar_subscription_link(calendar_id)
    assert subscription_link.startswith("https://calendar.google.com/calendar/render?cid="), (
        "Invalid subscription link format"
    )

    # Verify calendar appears in list
    calendars = list_available_calendars()
    calendar_names = [cal["calendar_name"] for cal in calendars]
    assert any(TEST_SENIUNIJA_NAME in name for name in calendar_names), "Calendar not found in list"

    print(f" Real calendar test passed: {calendar_info['calendar_name']}")


@pytest.mark.real_api
def test_real_calendar_with_different_waste_types():
    """Test creating calendars for different waste types"""
    waste_types = ["bendros", "plastikas", "stiklas"]

    for waste_type in waste_types:
        test_kaimai_hash = f"test_kaimai_{TEST_SCHEDULE_GROUP_ID}_{waste_type}"
        test_sg_id = create_test_schedule_group(test_kaimai_hash, waste_type, TEST_DATES[:2])

        result = create_calendar_for_schedule_group(schedule_group_id=test_sg_id)
        require_calendar_result(result)
        assert result["success"] is True
        expected_label = WASTE_TYPE_DISPLAY.get(waste_type, waste_type)
        assert expected_label in result["calendar_name"]

        created_calendar_ids.append(result["calendar_id"])
        print(f" Created {waste_type} calendar: {result['calendar_name']}")

    print(" Multiple waste type test passed")


@pytest.mark.real_api
def test_real_calendar_event_details():
    """Test that events have correct timing and descriptions"""
    test_kaimai_hash = f"test_kaimai_{TEST_SCHEDULE_GROUP_ID}_events"
    test_sg_id = create_test_schedule_group(test_kaimai_hash, TEST_WASTE_TYPE, ["2026-03-10"])

    result = create_calendar_for_schedule_group(schedule_group_id=test_sg_id)
    require_calendar_result(result)
    sync_result = sync_calendar_for_schedule_group(test_sg_id)
    if not sync_result.get("success"):
        pytest.skip("Calendar sync failed (quota or auth issue)")

    assert result is not None
    assert result["success"] is True

    calendar_id = result["calendar_id"]
    created_calendar_ids.append(calendar_id)

    # Get the actual event from Google Calendar to verify details
    from services.calendar import get_google_calendar_service

    service = get_google_calendar_service()

    # Get events from the calendar
    events_result = (
        service.events()
        .list(
            calendarId=calendar_id,
            timeMin="2026-01-01T00:00:00Z",
            timeMax="2026-12-31T23:59:59Z",
            singleEvents=True,
            orderBy="startTime",
        )
        .execute()
    )

    events = events_result.get("items", [])

    assert len(events) == 1, f"Expected 1 event, got {len(events)}"

    event = events[0]

    # Verify event timing (07:00-09:00)
    start_time = datetime.datetime.fromisoformat(event["start"]["dateTime"].replace("Z", "+00:00"))
    end_time = datetime.datetime.fromisoformat(event["end"]["dateTime"].replace("Z", "+00:00"))

    assert start_time.hour == 7 and start_time.minute == 0, (
        f"Start time should be 07:00, got {start_time}"
    )
    assert end_time.hour == 9 and end_time.minute == 0, f"End time should be 09:00, got {end_time}"

    # Verify event description
    assert event["description"] == "Išvežkite bendrų šiukšlių dėžę", "Event description incorrect"

    # Verify reminders
    assert "reminders" in event, "Event should have reminders"
    overrides = event["reminders"]["overrides"]
    reminder_minutes = [r["minutes"] for r in overrides]
    assert 720 in reminder_minutes, "Should have 12-hour (720 minutes) reminder"
    assert 10 in reminder_minutes, "Should have 10-minute reminder"

    print(f" Event details test passed: {event['summary']}")


@pytest.mark.real_api
def test_real_calendar_duplicate_creation():
    """Test that creating calendars with the same name creates separate calendars"""
    test_kaimai_hash = f"test_kaimai_{TEST_SCHEDULE_GROUP_ID}_dup"
    test_sg_id = create_test_schedule_group(test_kaimai_hash, TEST_WASTE_TYPE, TEST_DATES)

    # Create calendar first time
    result1 = create_calendar_for_schedule_group(schedule_group_id=test_sg_id)
    require_calendar_result(result1)
    assert result1["success"] is True

    calendar_id1 = result1["calendar_id"]
    created_calendar_ids.append(calendar_id1)

    # Try to create the same calendar again (should return existing calendar - one per schedule group)
    result2 = create_calendar_for_schedule_group(schedule_group_id=test_sg_id)

    # Should return existing calendar (idempotent - one calendar per schedule group)
    assert result2 is not None
    assert result2["success"] is True
    assert result2["calendar_id"] == calendar_id1, (
        "Should return same calendar ID (one per schedule group)"
    )
    assert result2.get("existing") is True, "Should indicate this is an existing calendar"

    print(" Duplicate creation test passed: Returns existing calendar (idempotent)")


@pytest.mark.real_api
def test_real_calendar_listing():
    """Test listing all available calendars"""
    # Create a few test calendars first
    for i in range(3):
        test_kaimai_hash = f"test_kaimai_{TEST_SCHEDULE_GROUP_ID}_list_{i}"
        test_sg_id = create_test_schedule_group(test_kaimai_hash, TEST_WASTE_TYPE, TEST_DATES[:1])

        result = create_calendar_for_schedule_group(schedule_group_id=test_sg_id)
        if not result:
            pytest.skip("Calendar creation failed (quota or auth issue)")
        if result["success"]:
            created_calendar_ids.append(result["calendar_id"])

    # List all calendars
    calendars = list_available_calendars()

    # Filter for our test calendars
    test_calendars = [cal for cal in calendars if TEST_SENIUNIJA_NAME in cal["calendar_name"]]

    if len(created_calendar_ids) < 3:
        pytest.skip("Not enough calendars created due to quota limits")
    assert len(test_calendars) >= 3, (
        f"Expected at least 3 test calendars, found {len(test_calendars)}"
    )

    # Verify each calendar has required fields
    for cal in test_calendars:
        assert "calendar_id" in cal
        assert "calendar_name" in cal
        assert "subscription_link" in cal
        assert cal["subscription_link"].startswith(
            "https://calendar.google.com/calendar/render?cid="
        )

    print(f" Calendar listing test passed: Found {len(test_calendars)} test calendars")


@pytest.mark.real_api
def test_real_calendar_empty_dates():
    """Test creating calendar with empty dates list"""
    test_kaimai_hash = f"test_kaimai_{TEST_SCHEDULE_GROUP_ID}_empty"
    test_sg_id = create_test_schedule_group(test_kaimai_hash, TEST_WASTE_TYPE, [])

    result = create_calendar_for_schedule_group(schedule_group_id=test_sg_id)
    require_calendar_result(result)
    sync_result = sync_calendar_for_schedule_group(test_sg_id)
    assert result["success"] is True
    assert sync_result["events_added"] == 0, "Should create 0 events for empty dates"

    created_calendar_ids.append(result["calendar_id"])
    print(" Empty dates test passed: Calendar created with 0 events")


@pytest.mark.real_api
def test_real_calendar_service_account_auth():
    """Test that Service Account authentication works"""
    from services.calendar import get_google_calendar_service

    service = get_google_calendar_service()

    # Try to list calendars (requires authentication)
    calendars_result = service.calendarList().list(maxResults=1).execute()

    assert calendars_result is not None, "Failed to authenticate with Service Account"
    print(" Service Account authentication test passed")


if __name__ == "__main__":
    # Run only real API tests
    pytest.main([__file__, "-v", "-m", "real_api"])
