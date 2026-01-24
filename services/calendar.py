"""
Google Calendar service - shared business logic
Handles calendar creation and event management for schedule groups
Used by both API (read) and Scraper (write) services
Uses Service Account for headless authentication (standard Gmail, no Workspace)
"""

import datetime
import logging
import os.path
import random

# Import configuration
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

sys.path.insert(0, str(Path(__file__).parent.parent))
import config
from api.db import (
    get_schedule_group_info,
    get_schedule_groups_needing_sync,
    update_schedule_group_calendar_id,
    update_schedule_group_calendar_synced,
)
from database.init import get_db_connection

# Setup logging
logging.basicConfig(
    level=logging.DEBUG, format="[%(asctime)s] %(levelname)s: %(message)s"
)
logger = logging.getLogger(__name__)


def get_google_calendar_service():
    """
    Get authenticated Google Calendar service using Service Account
    Fully headless authentication - no tokens needed
    """
    credentials_file = config.GOOGLE_CALENDAR_CREDENTIALS_FILE

    if not os.path.exists(credentials_file):
        raise FileNotFoundError(
            f"Google Calendar credentials file not found: {credentials_file}\n"
            f"Please create a Service Account JSON key file at this path.\n"
            f"See INSTALL.md for detailed setup instructions."
        )

    # Verify file is not empty
    if os.path.getsize(credentials_file) == 0:
        raise ValueError(
            f"Google Calendar credentials file is empty: {credentials_file}\n"
            f"Please add your Service Account JSON credentials.\n"
            f"See INSTALL.md for detailed setup instructions."
        )

    try:
        # Service Account: Direct authentication, fully headless
        creds = service_account.Credentials.from_service_account_file(
            credentials_file, scopes=config.GOOGLE_CALENDAR_SCOPES
        )
        return build("calendar", "v3", credentials=creds)
    except Exception as e:
        raise Exception(
            f"Failed to authenticate with Google Calendar: {e}\n"
            f"Make sure {credentials_file} is a valid Service Account JSON key file"
        )


def create_calendar_for_schedule_group(schedule_group_id: str) -> Optional[Dict]:
    """
    Create a Google Calendar for a schedule group (calendar only, no events)
    This is phase 1 of the two-phase process (calendar creation, then event sync)

    Args:
        schedule_group_id: Schedule group ID (stable hash-based string)

    Returns:
        Dictionary with calendar info, or None if failed
    """
    start_time = time.time()
    logger.debug(f"Creating calendar for schedule_group_id={schedule_group_id}")
    print(f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Creating calendar for schedule_group_id={schedule_group_id}")

    try:
        # Get schedule group info
        logger.debug(f"Getting schedule group info for {schedule_group_id}")
        group_info = get_schedule_group_info(schedule_group_id)

        if not group_info:
            logger.error(f"Schedule group not found: {schedule_group_id}")
            print(f"❌ Schedule group not found: {schedule_group_id}")
            return None

        # CRITICAL FIX: Double-check calendar_id wasn't just set (race condition protection)
        existing_calendar_id = group_info.get("calendar_id")
        if existing_calendar_id:
            logger.debug(f"Calendar already exists in DB for {schedule_group_id}: {existing_calendar_id}")
            # Verify the calendar still exists in Google Calendar
            try:
                calendar_info = get_existing_calendar_info(existing_calendar_id)
                if calendar_info:
                    # Ensure calendar is public
                    try:
                        service = get_google_calendar_service()
                        acl_rule = {"scope": {"type": "default"}, "role": "reader"}
                        try:
                            service.acl().get(
                                calendarId=existing_calendar_id, ruleId="default"
                            ).execute()
                            logger.debug(f"Calendar already public: {existing_calendar_id}")
                        except HttpError:
                            # Public ACL doesn't exist, add it
                            service.acl().insert(
                                calendarId=existing_calendar_id, body=acl_rule
                            ).execute()
                            logger.info(f"Made existing calendar public: {existing_calendar_id}")
                            print(f"✅ Made existing calendar public: {existing_calendar_id}")
                    except Exception as e:
                        logger.warning(f"Could not ensure calendar is public: {e}")

                    logger.info(f"Using existing calendar for {schedule_group_id}: {existing_calendar_id}")
                    print(f"✅ Using existing calendar for schedule_group_id={schedule_group_id}: {existing_calendar_id}")
                    
                    # CRITICAL FIX: Ensure calendar_id is stored in database
                    if not update_schedule_group_calendar_id(schedule_group_id, existing_calendar_id):
                        logger.warning(f"Failed to update calendar_id in database for {schedule_group_id}, but calendar exists")
                    
                    return {
                        "calendar_id": existing_calendar_id,
                        "calendar_name": calendar_info["calendar_name"],
                        "subscription_link": calendar_info["subscription_link"],
                        "success": True,
                        "existing": True,
                    }
            except Exception as e:
                logger.warning(
                    f"Existing calendar {existing_calendar_id} for {schedule_group_id} invalid, creating new one: {e}"
                )
                print(f"⚠️  Existing calendar {existing_calendar_id} for {schedule_group_id} invalid, creating new one: {e}")

        # SIMPLIFIED: Get just seniunija (no village logic)
        kaimai_hash = group_info["kaimai_hash"]
        waste_type = group_info["waste_type"]
        conn = get_db_connection()
        cursor = conn.cursor()

        try:
            # Get seniunija (simplified - just get first one)
            cursor.execute(
                """
                SELECT DISTINCT seniunija
                FROM locations
                WHERE kaimai_hash = ?
                LIMIT 1
            """,
                (kaimai_hash,),
            )
            row = cursor.fetchone()
            seniunija = row[0] if row else "Nemenčinė"
        finally:
            conn.close()

        waste_type_display = {
            "bendros": "Bendros atliekos",
            "plastikas": "Plastikas",
            "stiklas": "Stiklas",
        }.get(waste_type, waste_type)

        # Generate short hash from schedule_group_id for internal identification (first 6 chars)
        short_hash = (
            schedule_group_id[:6] if len(schedule_group_id) >= 6 else schedule_group_id
        )

        # SIMPLIFIED: Calendar name is just seniunija - waste_type - hash
        calendar_name = f"{seniunija} - {waste_type_display} - {short_hash}"
        calendar_description = f"Buitinių atliekų surinkimo grafikas: {seniunija} seniūnija, {waste_type_display}. Automatiškai atnaujinamas."

        # Create new calendar
        logger.debug(f"Getting Google Calendar service for {schedule_group_id}")
        service = get_google_calendar_service()

        # Create the calendar
        logger.debug(f"Creating calendar '{calendar_name}' for schedule_group_id={schedule_group_id}")
        calendar = {
            "summary": calendar_name,
            "description": calendar_description,
            "timeZone": config.GOOGLE_CALENDAR_TIMEZONE,
        }

        created_calendar = service.calendars().insert(body=calendar).execute()
        calendar_id = created_calendar["id"]
        logger.debug(f"Calendar created: {calendar_id} for schedule_group_id={schedule_group_id}")

        # Make calendar publicly accessible (required for subscription links to work)
        try:
            logger.debug(f"Making calendar public: {calendar_id}")
            acl_rule = {
                "scope": {"type": "default"},
                "role": "reader",  # Public read access
            }
            service.acl().insert(calendarId=calendar_id, body=acl_rule).execute()
            logger.info(f"Calendar made public: {calendar_id}")
            print(f"✅ Calendar made public: {calendar_id}")
        except Exception as e:
            logger.warning(
                f"Failed to make calendar public (may need manual sharing): {e}"
            )
            print(f"⚠️  Failed to make calendar public (may need manual sharing): {e}")
            # Continue anyway - calendar is created, just not public yet

        # CRITICAL FIX: Store calendar_id in database (calendar_synced_at stays NULL - triggers event sync)
        if not update_schedule_group_calendar_id(schedule_group_id, calendar_id):
            logger.error(
                f"CRITICAL: Failed to store calendar_id in database for schedule_group_id={schedule_group_id}. "
                f"Calendar {calendar_id} was created but won't be tracked. This will cause duplicate creation attempts!"
            )
            print(
                f"❌ CRITICAL: Failed to store calendar_id in database for schedule_group_id={schedule_group_id}"
            )
            # Don't return None - the calendar exists, we should still return it
            # But log this as a critical error
            return {
                "calendar_id": calendar_id,
                "calendar_name": calendar_name,
                "subscription_link": f"https://calendar.google.com/calendar/render?cid={calendar_id}",
                "success": True,
                "existing": False,
                "warning": "Calendar created but database update failed - may cause duplicates"
            }

        logger.info(f"Calendar created successfully for schedule_group_id={schedule_group_id}: {calendar_id}")
        print(f"✅ Calendar created for schedule_group_id={schedule_group_id}: {calendar_id}")

        # Return calendar info (events will be synced separately)
        return {
            "calendar_id": calendar_id,
            "calendar_name": calendar_name,
            "subscription_link": f"https://calendar.google.com/calendar/render?cid={calendar_id}",
            "success": True,
            "existing": False,
        }

    except HttpError as error:
        logger.error(f"Google Calendar API error for schedule_group_id={schedule_group_id}: {error}")
        print(f"❌ Google Calendar API error for schedule_group_id={schedule_group_id}: {error}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error creating calendar for schedule_group_id={schedule_group_id}: {e}", exc_info=True)
        print(f"❌ Unexpected error creating calendar for schedule_group_id={schedule_group_id}: {e}")
        import traceback
        traceback.print_exc()
        return None


def get_existing_calendar_info(calendar_id: str) -> Optional[Dict]:
    """
    Get information about an existing calendar

    Args:
        calendar_id: Google Calendar ID

    Returns:
        Dictionary with calendar info, or None if not found
    """
    try:
        service = get_google_calendar_service()
        calendar = service.calendars().get(calendarId=calendar_id).execute()

        return {
            "calendar_id": calendar["id"],
            "calendar_name": calendar["summary"],
            "description": calendar.get("description", ""),
            "subscription_link": f"https://calendar.google.com/calendar/render?cid={calendar['id']}",
            "timeZone": calendar["timeZone"],
        }

    except HttpError as error:
        print(f"❌ Error getting calendar info: {error}")
        return None
    except Exception as e:
        print(f"❌ Unexpected error getting calendar info: {e}")
        return None


def list_available_calendars() -> List[Dict]:
    """
    List all calendars created by this application

    Returns:
        List of calendar dictionaries
    """
    try:
        service = get_google_calendar_service()

        # Get all calendars
        calendars_result = service.calendarList().list().execute()
        calendars = calendars_result.get("items", [])

        # Filter for our waste schedule calendars
        waste_calendars = []
        for calendar in calendars:
            summary = calendar.get("summary", "")
            if "Atliekų surinkimas" in summary or "Nemenčinė Atliekos" in summary:
                waste_calendars.append(
                    {
                        "calendar_id": calendar["id"],
                        "calendar_name": calendar["summary"],
                        "description": calendar.get("description", ""),
                        "subscription_link": f"https://calendar.google.com/calendar/render?cid={calendar['id']}",
                        "timeZone": calendar["timeZone"],
                    }
                )

        return waste_calendars

    except HttpError as error:
        print(f"❌ Error listing calendars: {error}")
        return []
    except Exception as e:
        print(f"❌ Unexpected error listing calendars: {e}")
        return []


def generate_calendar_subscription_link(calendar_id: str) -> str:
    """
    Generate a subscription link for a calendar

    Args:
        calendar_id: Google Calendar ID

    Returns:
        Subscription URL
    """
    return f"https://calendar.google.com/calendar/render?cid={calendar_id}"


def cleanup_orphaned_calendars(dry_run: bool = True) -> List[Dict]:
    """
    Find and optionally delete calendars that exist in Google Calendar but not in database

    Orphaned calendars are those that:
    - Exist in Google Calendar (created by our service account)
    - Do NOT have a corresponding entry in schedule_groups.calendar_id

    Args:
        dry_run: If True, only list orphaned calendars without deleting (default: True)

    Returns:
        List of orphaned calendar dictionaries with calendar_id and calendar_name
    """
    try:
        service = get_google_calendar_service()

        # Get all calendars from Google Calendar that the service account can access
        calendars_result = service.calendarList().list().execute()
        all_calendars = calendars_result.get("items", [])

        # Include ALL calendars (don't filter by naming pattern)
        # We'll check against database to find orphans
        our_calendars = []
        for calendar in all_calendars:
            # Skip primary calendar (usually the service account's main calendar)
            # This is the default calendar and shouldn't be deleted
            if calendar.get("primary", False):
                continue
            our_calendars.append(
                {
                    "calendar_id": calendar["id"],
                    "calendar_name": calendar.get("summary", ""),
                    "description": calendar.get("description", ""),
                }
            )

        # Get all calendar_ids from database
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT DISTINCT calendar_id
            FROM schedule_groups
            WHERE calendar_id IS NOT NULL
        """)
        db_calendar_ids = {row[0] for row in cursor.fetchall()}
        conn.close()

        # Find orphaned calendars (exist in Google but not in DB)
        orphaned = []
        for cal in our_calendars:
            if cal["calendar_id"] not in db_calendar_ids:
                orphaned.append(cal)

        if dry_run:
            if orphaned:
                print(f"\n🔍 Found {len(orphaned)} orphaned calendar(s):")
                for cal in orphaned:
                    print(f"   - {cal['calendar_name']} ({cal['calendar_id'][:30]}...)")
                print(f"\n⚠️  This is a DRY RUN - no calendars were deleted")
                print(f"   Run 'make clean-calendars' to actually delete them")
            else:
                print(
                    f"✅ No orphaned calendars found - all calendars in Google Calendar have corresponding database entries"
                )
        else:
            # Actually delete orphaned calendars
            deleted_count = 0
            error_count = 0
            for idx, cal in enumerate(orphaned):
                try:
                    service.calendars().delete(calendarId=cal["calendar_id"]).execute()
                    deleted_count += 1
                    print(f"🗑️  Deleted orphaned calendar: {cal['calendar_name']}")

                    # Add delay between deletions to avoid rate limits (2-3 seconds)
                    if idx < len(orphaned) - 1:  # Don't delay after last calendar
                        delay = random.uniform(2.0, 3.0)
                        time.sleep(delay)
                except HttpError as e:
                    if "rateLimitExceeded" in str(e) or "quotaExceeded" in str(e):
                        error_count += 1
                        print(
                            f"⚠️  Rate limit hit - will retry later: {cal['calendar_name']}"
                        )
                        # Wait longer on rate limit (5 seconds)
                        time.sleep(5)
                    else:
                        error_count += 1
                        print(
                            f"❌ Failed to delete calendar {cal['calendar_name']}: {e}"
                        )
                except Exception as e:
                    error_count += 1
                    print(f"❌ Failed to delete calendar {cal['calendar_name']}: {e}")

            print(
                f"\n✅ Cleanup complete: {deleted_count} deleted, {error_count} errors"
            )
            if error_count > 0:
                print(f"   Run 'make clean-calendars' again to retry failed deletions")

        return orphaned

    except HttpError as error:
        print(f"❌ Error during calendar cleanup: {error}")
        return []
    except Exception as e:
        print(f"❌ Unexpected error during calendar cleanup: {e}")
        return []
def sync_calendar_for_schedule_group(schedule_group_id: str) -> Dict:
    """
    Sync calendar events for a schedule group (add new, delete old, retry failed)

    This is phase 2 of the two-phase process (calendar creation, then event sync)

    Steps:
    1. Get current dates from schedule_groups.dates
    2. Get existing events from calendar_events table
    3. Delete old events (dates in DB but not in current schedule)
    4. Add new events (dates in current schedule but not in DB)
    5. Retry failed events (status='error')
    6. Update calendar_events table
    7. Mark as synced when complete

    Args:
        schedule_group_id: Schedule group ID

    Returns:
        Dictionary with sync results
    """
    start_time = time.time()
    logger.debug(f"Syncing calendar events for schedule_group_id={schedule_group_id}")

    try:
        # Get schedule group info
        group_info = get_schedule_group_info(schedule_group_id)
        if not group_info:
            logger.error(f"Schedule group not found: {schedule_group_id}")
            return {"success": False, "error": "Schedule group not found"}

        calendar_id = group_info.get("calendar_id")
        if not calendar_id:
            logger.error(f"No calendar_id for schedule_group_id: {schedule_group_id}")
            return {"success": False, "error": "Calendar not created yet"}

        dates = group_info.get("dates", [])
        if not dates:
            logger.warning(f"No dates for schedule_group_id: {schedule_group_id}")
            # Mark as synced anyway (empty schedule)
            update_schedule_group_calendar_synced(schedule_group_id)
            return {
                "success": True,
                "events_added": 0,
                "events_deleted": 0,
                "events_retried": 0,
            }

        # Get existing events from calendar_events table
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT date, event_id, status
            FROM calendar_events
            WHERE schedule_group_id = ?
        """,
            (schedule_group_id,),
        )

        existing_events = {
            row[0]: {"event_id": row[1], "status": row[2]} for row in cursor.fetchall()
        }
        conn.close()

        # Convert dates to set for comparison
        current_dates = set(dates)
        existing_dates = set(existing_events.keys())

        # Find dates to add and delete (in-place update strategy)
        # - Dates that stay the same are NOT touched (preserves existing events)
        # - Only dates that changed are updated (delete old, add new)
        dates_to_add = current_dates - existing_dates  # New dates not in calendar
        dates_to_delete = (
            existing_dates - current_dates
        )  # Old dates no longer in schedule
        dates_to_retry = {
            date
            for date, info in existing_events.items()
            if info["status"] == "error" and date in current_dates
        }  # Failed events to retry

        logger.info(
            f"In-place update for {schedule_group_id}: "
            f"add {len(dates_to_add)}, delete {len(dates_to_delete)}, "
            f"retry {len(dates_to_retry)}, keep {len(current_dates & existing_dates)} unchanged"
        )

        # Get Google Calendar service
        service = get_google_calendar_service()
        waste_type = group_info["waste_type"]
        
        # SIMPLIFIED: Event title is just waste type message (no village name)
        waste_type_display = {
            "bendros": "Buitinių atliekų surinkimas",
            "plastikas": "Plastikinių atliekų surinkimas",
            "stiklas": "Stiklinių atliekų surinkimas",
        }.get(waste_type, f"{waste_type} surinkimas")

        events_added = 0
        events_deleted = 0
        events_retried = 0

        # Delete old events
        for date_str in dates_to_delete:
            event_id = existing_events[date_str]["event_id"]
            if event_id:
                try:
                    service.events().delete(
                        calendarId=calendar_id, eventId=event_id
                    ).execute()
                    events_deleted += 1
                    logger.debug(f"Deleted event {event_id} for date {date_str}")
                except Exception as e:
                    logger.error(
                        f"Failed to delete event {event_id} for date {date_str}: {e}"
                    )
                    # Error stored in calendar_events, will retry next time

            # Remove from calendar_events table
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute(
                """
                DELETE FROM calendar_events
                WHERE schedule_group_id = ? AND date = ?
            """,
                (schedule_group_id, date_str),
            )
            conn.commit()
            conn.close()

        # Add new events
        for date_str in dates_to_add:
            try:
                date_obj = datetime.datetime.strptime(date_str, "%Y-%m-%d")
                event_date = date_obj.date()

                event = {
                    "summary": waste_type_display,  # SIMPLIFIED: Just waste type, no village
                    "description": "Išvežkite bendrų šiukšlių dėžę",
                    "start": {
                        "dateTime": datetime.datetime(
                            event_date.year,
                            event_date.month,
                            event_date.day,
                            config.GOOGLE_CALENDAR_EVENT_START_HOUR,
                            0,
                        ).isoformat(),
                        "timeZone": config.GOOGLE_CALENDAR_TIMEZONE,
                    },
                    "end": {
                        "dateTime": datetime.datetime(
                            event_date.year,
                            event_date.month,
                            event_date.day,
                            config.GOOGLE_CALENDAR_EVENT_END_HOUR,
                            0,
                        ).isoformat(),
                        "timeZone": config.GOOGLE_CALENDAR_TIMEZONE,
                    },
                    "reminders": {
                        "useDefault": False,
                        "overrides": config.GOOGLE_CALENDAR_REMINDERS,
                    },
                }

                created_event = (
                    service.events()
                    .insert(calendarId=calendar_id, body=event)
                    .execute()
                )

                event_id = created_event["id"]
                events_added += 1

                # Store in calendar_events table
                conn = get_db_connection()
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO calendar_events (schedule_group_id, date, event_id, status)
                    VALUES (?, ?, ?, 'created')
                    ON CONFLICT(schedule_group_id, date) DO UPDATE SET
                        event_id = ?, status = 'created', updated_at = CURRENT_TIMESTAMP
                """,
                    (schedule_group_id, date_str, event_id, event_id),
                )
                conn.commit()
                conn.close()

                logger.debug(f"Created event {event_id} for date {date_str}")

                # Add delay between event creations (2-3 seconds)
                if date_str != list(dates_to_add)[-1]:  # Don't delay after last event
                    delay = random.uniform(2.0, 3.0)
                    time.sleep(delay)

            except Exception as e:
                logger.error(f"Failed to create event for {date_str}: {e}")
                # Store error in calendar_events
                conn = get_db_connection()
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO calendar_events (schedule_group_id, date, status, error_message)
                    VALUES (?, ?, 'error', ?)
                    ON CONFLICT(schedule_group_id, date) DO UPDATE SET
                        status = 'error', error_message = ?, updated_at = CURRENT_TIMESTAMP
                """,
                    (schedule_group_id, date_str, str(e), str(e)),
                )
                conn.commit()
                conn.close()

        # Retry failed events
        for date_str in dates_to_retry:
            try:
                date_obj = datetime.datetime.strptime(date_str, "%Y-%m-%d")
                event_date = date_obj.date()

                event = {
                    "summary": waste_type_display,  # SIMPLIFIED: Just waste type, no village
                    "description": "Išvežkite bendrų šiukšlių dėžę",
                    "start": {
                        "dateTime": datetime.datetime(
                            event_date.year,
                            event_date.month,
                            event_date.day,
                            config.GOOGLE_CALENDAR_EVENT_START_HOUR,
                            0,
                        ).isoformat(),
                        "timeZone": config.GOOGLE_CALENDAR_TIMEZONE,
                    },
                    "end": {
                        "dateTime": datetime.datetime(
                            event_date.year,
                            event_date.month,
                            event_date.day,
                            config.GOOGLE_CALENDAR_EVENT_END_HOUR,
                            0,
                        ).isoformat(),
                        "timeZone": config.GOOGLE_CALENDAR_TIMEZONE,
                    },
                    "reminders": {
                        "useDefault": False,
                        "overrides": config.GOOGLE_CALENDAR_REMINDERS,
                    },
                }

                created_event = (
                    service.events()
                    .insert(calendarId=calendar_id, body=event)
                    .execute()
                )

                event_id = created_event["id"]
                events_retried += 1

                # Update calendar_events table
                conn = get_db_connection()
                cursor = conn.cursor()
                cursor.execute(
                    """
                    UPDATE calendar_events
                    SET event_id = ?, status = 'created', error_message = NULL, updated_at = CURRENT_TIMESTAMP
                    WHERE schedule_group_id = ? AND date = ?
                """,
                    (event_id, schedule_group_id, date_str),
                )
                conn.commit()
                conn.close()

                logger.debug(f"Retried event {event_id} for date {date_str}")

                # Add delay between event retries (2-3 seconds)
                retry_list = list(dates_to_retry)
                if date_str != retry_list[-1]:  # Don't delay after last event
                    delay = random.uniform(2.0, 3.0)
                    time.sleep(delay)

            except Exception as e:
                logger.error(f"Failed to retry event for {date_str}: {e}")
                # Update error message
                conn = get_db_connection()
                cursor = conn.cursor()
                cursor.execute(
                    """
                    UPDATE calendar_events
                    SET status = 'error', error_message = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE schedule_group_id = ? AND date = ?
                """,
                    (str(e), schedule_group_id, date_str),
                )
                conn.commit()
                conn.close()

        # Mark as synced
        update_schedule_group_calendar_synced(schedule_group_id)

        total_time = time.time() - start_time
        logger.info(
            f"Calendar sync complete for {schedule_group_id} in {total_time:.2f}s: "
            f"added={events_added}, deleted={events_deleted}, retried={events_retried}"
        )

        return {
            "success": True,
            "events_added": events_added,
            "events_deleted": events_deleted,
            "events_retried": events_retried,
        }

    except HttpError as error:
        logger.error(f"Google Calendar API error: {error}")
        return {"success": False, "error": str(error)}
    except Exception as e:
        logger.error(f"Unexpected error syncing calendar: {e}", exc_info=True)
        return {"success": False, "error": str(e)}
