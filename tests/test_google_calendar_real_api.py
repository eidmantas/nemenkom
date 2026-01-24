"""
Real API tests for Google Calendar integration
These tests make actual Google Calendar API calls
Run with: pytest tests/test_google_calendar_real_api.py -v
"""
import pytest
import datetime
import os
import tempfile
import sqlite3
from unittest.mock import patch
from api.google_calendar import (
    create_calendar_for_schedule_group,
    get_existing_calendar_info,
    list_available_calendars,
    generate_calendar_subscription_link
)

# Test configuration
TEST_SCHEDULE_GROUP_ID = "test_real_api_sg"
TEST_LOCATION_NAME = "Test Real API Village"
TEST_DATES = [
    "2026-01-15",
    "2026-01-29",
    "2026-02-12"
]
TEST_WASTE_TYPE = "bendros"

# Calendar cleanup
created_calendar_ids = []

def setup_module(module):
    """Setup for real API tests"""
    print("\n🔄 Setting up real Google Calendar API tests...")

def teardown_module(module):
    """Cleanup after real API tests"""
    print("\n🧹 Cleaning up test calendars...")

    # Delete all test calendars created during tests
    for calendar_id in created_calendar_ids:
        try:
            from api.google_calendar import get_google_calendar_service
            service = get_google_calendar_service()
            print(f"🗑️  Deleting calendar: {calendar_id}")
            service.calendars().delete(calendarId=calendar_id).execute()
        except Exception as e:
            print(f"⚠️  Failed to delete calendar {calendar_id}: {e}")

    print("✅ Cleanup complete")

@pytest.mark.real_api
def test_real_calendar_creation_and_cleanup():
    """
    Test complete calendar lifecycle with real Google Calendar API
    1. Create real calendar with events
    2. Verify calendar exists and has correct events
    3. Get calendar info
    4. Clean up by deleting calendar
    """
    # Create real calendar
    result = create_calendar_for_schedule_group(
        schedule_group_id=TEST_SCHEDULE_GROUP_ID,
        location_name=TEST_LOCATION_NAME,
        dates=TEST_DATES,
        waste_type=TEST_WASTE_TYPE
    )

    # Verify calendar was created
    assert result is not None, "Calendar creation failed"
    assert result['success'] is True, "Calendar creation was not successful"
    assert result['calendar_id'] is not None, "Calendar ID is missing"
    assert result['events_created'] == len(TEST_DATES), f"Expected {len(TEST_DATES)} events, got {result['events_created']}"

    calendar_id = result['calendar_id']
    created_calendar_ids.append(calendar_id)  # Track for cleanup

    print(f"📅 Created real calendar: {result['calendar_name']}")
    print(f"🔗 Subscription link: {result['subscription_link']}")

    # Verify calendar info
    calendar_info = get_existing_calendar_info(calendar_id)
    assert calendar_info is not None, "Failed to get calendar info"
    assert calendar_info['calendar_id'] == calendar_id, "Calendar ID mismatch"
    assert "Nemenčinė Atliekos" in calendar_info['calendar_name'], "Calendar name format incorrect"

    # Verify subscription link format
    subscription_link = generate_calendar_subscription_link(calendar_id)
    assert subscription_link.startswith("https://calendar.google.com/calendar/render?cid="), "Invalid subscription link format"

    # Verify calendar appears in list
    calendars = list_available_calendars()
    calendar_names = [cal['calendar_name'] for cal in calendars]
    assert any(TEST_LOCATION_NAME in name for name in calendar_names), "Calendar not found in list"

    print(f"✅ Real calendar test passed: {calendar_info['calendar_name']}")

@pytest.mark.real_api
def test_real_calendar_with_different_waste_types():
    """Test creating calendars for different waste types"""
    waste_types = ['bendros', 'plastikas', 'stiklas']

    for waste_type in waste_types:
        result = create_calendar_for_schedule_group(
            schedule_group_id=f"{TEST_SCHEDULE_GROUP_ID}_{waste_type}",
            location_name=f"{TEST_LOCATION_NAME} - {waste_type}",
            dates=TEST_DATES[:2],  # Use fewer dates for this test
            waste_type=waste_type
        )

        assert result is not None
        assert result['success'] is True
        assert waste_type in result['calendar_name']

        created_calendar_ids.append(result['calendar_id'])
        print(f"📅 Created {waste_type} calendar: {result['calendar_name']}")

    print(f"✅ Multiple waste type test passed")

@pytest.mark.real_api
def test_real_calendar_event_details():
    """Test that events have correct timing and descriptions"""
    result = create_calendar_for_schedule_group(
        schedule_group_id=f"{TEST_SCHEDULE_GROUP_ID}_events",
        location_name=f"{TEST_LOCATION_NAME} Events Test",
        dates=["2026-03-10"],  # Single date for detailed testing
        waste_type=TEST_WASTE_TYPE
    )

    assert result is not None
    assert result['success'] is True

    calendar_id = result['calendar_id']
    created_calendar_ids.append(calendar_id)

    # Get the actual event from Google Calendar to verify details
    from api.google_calendar import get_google_calendar_service
    service = get_google_calendar_service()

    # Get events from the calendar
    events_result = service.events().list(
        calendarId=calendar_id,
        timeMin='2026-01-01T00:00:00Z',
        timeMax='2026-12-31T23:59:59Z',
        singleEvents=True,
        orderBy='startTime'
    ).execute()

    events = events_result.get('items', [])

    assert len(events) == 1, f"Expected 1 event, got {len(events)}"

    event = events[0]

    # Verify event timing (07:00-09:00)
    start_time = datetime.datetime.fromisoformat(event['start']['dateTime'].replace('Z', '+00:00'))
    end_time = datetime.datetime.fromisoformat(event['end']['dateTime'].replace('Z', '+00:00'))

    assert start_time.hour == 7 and start_time.minute == 0, f"Start time should be 07:00, got {start_time}"
    assert end_time.hour == 9 and end_time.minute == 0, f"End time should be 09:00, got {end_time}"

    # Verify event description
    assert event['description'] == "Išvežkite bendrų šiukšlių dėžę", "Event description incorrect"

    # Verify reminders
    assert 'reminders' in event, "Event should have reminders"
    overrides = event['reminders']['overrides']
    reminder_minutes = [r['minutes'] for r in overrides]
    assert 720 in reminder_minutes, "Should have 12-hour (720 minutes) reminder"
    assert 10 in reminder_minutes, "Should have 10-minute reminder"

    print(f"✅ Event details test passed: {event['summary']}")

@pytest.mark.real_api
def test_real_calendar_duplicate_prevention():
    """Test that creating the same calendar twice doesn't create duplicates"""
    # Create calendar first time
    result1 = create_calendar_for_schedule_group(
        schedule_group_id=f"{TEST_SCHEDULE_GROUP_ID}_dup",
        location_name=f"{TEST_LOCATION_NAME} Duplicate Test",
        dates=TEST_DATES,
        waste_type=TEST_WASTE_TYPE
    )

    assert result1 is not None
    assert result1['success'] is True

    calendar_id = result1['calendar_id']
    created_calendar_ids.append(calendar_id)

    # Try to create the same calendar again (should still succeed but not create duplicate)
    result2 = create_calendar_for_schedule_group(
        schedule_group_id=f"{TEST_SCHEDULE_GROUP_ID}_dup",  # Same ID
        location_name=f"{TEST_LOCATION_NAME} Duplicate Test",  # Same name
        dates=TEST_DATES,
        waste_type=TEST_WASTE_TYPE
    )

    # Should still return success (idempotent)
    assert result2 is not None
    assert result2['success'] is True
    assert result2['calendar_id'] == calendar_id, "Should return same calendar ID"

    print(f"✅ Duplicate prevention test passed")

@pytest.mark.real_api
def test_real_calendar_listing():
    """Test listing all available calendars"""
    # Create a few test calendars first
    for i in range(3):
        result = create_calendar_for_schedule_group(
            schedule_group_id=f"{TEST_SCHEDULE_GROUP_ID}_list_{i}",
            location_name=f"{TEST_LOCATION_NAME} List {i}",
            dates=TEST_DATES[:1],  # Single date
            waste_type=TEST_WASTE_TYPE
        )

        if result and result['success']:
            created_calendar_ids.append(result['calendar_id'])

    # List all calendars
    calendars = list_available_calendars()

    # Filter for our test calendars
    test_calendars = [cal for cal in calendars if TEST_LOCATION_NAME in cal['calendar_name']]

    assert len(test_calendars) >= 3, f"Expected at least 3 test calendars, found {len(test_calendars)}"

    # Verify each calendar has required fields
    for cal in test_calendars:
        assert 'calendar_id' in cal
        assert 'calendar_name' in cal
        assert 'subscription_link' in cal
        assert cal['subscription_link'].startswith('https://calendar.google.com/calendar/render?cid=')

    print(f"✅ Calendar listing test passed: Found {len(test_calendars)} test calendars")

if __name__ == '__main__':
    # Run only real API tests
    pytest.main([__file__, '-v', '-m', 'real_api'])
