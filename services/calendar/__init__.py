"""
Google Calendar service - shared business logic
Handles calendar creation and event management for schedule groups
Used by both API (read) and Scraper (write) services
Uses Service Account for headless authentication (standard Gmail, no Workspace)
"""

import datetime
import logging

# Import configuration
import sys
import time
from pathlib import Path

from googleapiclient.errors import HttpError

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
import config
from services.common.calendar_client import (
    generate_calendar_subscription_link,
    get_existing_calendar_info,
    get_google_calendar_service,
    throttle_calendar,
)
from services.common.db import get_db_connection
from services.common.db_helpers import (
    get_calendar_stream_id_for_schedule_group,
    get_calendar_stream_info,
    get_calendar_stream_scope,
    update_calendar_stream_calendar_id,
    update_calendar_stream_calendar_synced,
)
from services.common.logging_utils import setup_logging
from services.common.throttle import backoff

setup_logging()
logger = logging.getLogger(__name__)

WASTE_TYPE_DISPLAY = {
    "bendros": "Bendros atliekos",
    "plastikas": "Plastikas",
    "stiklas": "Stiklas",
}

WASTE_EVENT_SUMMARY = {
    "bendros": "Buitinių atliekų surinkimas",
    "plastikas": "Plastikinių atliekų surinkimas",
    "stiklas": "Stiklinių atliekų surinkimas",
}

WASTE_EVENT_DESCRIPTION = {
    "bendros": "Išvežkite bendrų atliekų konteinerį.",
    "plastikas": "Išvežkite plastiko ir pakuočių atliekų konteinerį.",
    "stiklas": "Išvežkite stiklo atliekų konteinerį.",
}


def _preview_values(values: list[str], *, limit: int = 4) -> str:
    if not values:
        return ""
    shown = values[:limit]
    if len(values) <= limit:
        return ", ".join(shown)
    return f"{', '.join(shown)} ir dar {len(values) - limit}"


def _finish_sentence(text: str) -> str:
    return text.rstrip(". ") + "."


def _format_scope_line(scope: dict, *, detailed: bool) -> str:
    parts: list[str] = []
    seniunijos = scope.get("seniunijos") or []
    villages = scope.get("villages") or []
    street_labels = scope.get("street_labels") or []

    if seniunijos:
        if len(seniunijos) == 1:
            parts.append(f"{seniunijos[0]} seniūnija")
        else:
            parts.append(f"{len(seniunijos)} seniūnijos: {_preview_values(seniunijos, limit=3)}")

    if villages:
        village_limit = 6 if detailed else 3
        if len(villages) == 1:
            parts.append(f"gyvenvietė: {villages[0]}")
        else:
            parts.append(f"gyvenvietės: {_preview_values(villages, limit=village_limit)}")

    if street_labels:
        street_limit = 8 if detailed else 4
        if len(street_labels) == 1:
            parts.append(f"gatvė: {street_labels[0]}")
        else:
            parts.append(f"gatvės: {_preview_values(street_labels, limit=street_limit)}")

    return "; ".join(parts) if parts else "aprėptis nenustatyta"


def _format_date_range(dates: list[str]) -> str:
    if not dates:
        return "nėra datų"
    ordered = sorted(dates)
    if len(ordered) == 1:
        return ordered[0]
    return f"{ordered[0]} -> {ordered[-1]}"


def _build_change_note(
    *,
    stream_info: dict,
    previous_dates: list[str] | None,
    events_added: int,
    events_deleted: int,
) -> str:
    current_dates = list(stream_info.get("dates") or [])
    if previous_dates is None:
        if stream_info.get("calendar_synced_at"):
            return "Pokytis: aprašas atnaujintas."
        return "Pokytis: pradinis publikavimas."

    if events_added == 0 and events_deleted == 0:
        return "Pokytis: grafikas nepasikeitė."

    return (
        f"Pokytis: +{events_added}, -{events_deleted}; "
        f"laikotarpis {_format_date_range(previous_dates)} -> {_format_date_range(current_dates)}."
    )


def _build_calendar_description(
    *,
    calendar_stream_id: str,
    stream_info: dict,
    previous_dates: list[str] | None = None,
    events_added: int = 0,
    events_deleted: int = 0,
) -> str:
    scope = get_calendar_stream_scope(calendar_stream_id)
    updated_at = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    waste_type_display = WASTE_TYPE_DISPLAY.get(stream_info["waste_type"], stream_info["waste_type"])

    lines = [
        "Nemenkom atliekų surinkimo kalendorius.",
        f"Tipas: {waste_type_display}.",
        _finish_sentence(f"Aprėptis: {_format_scope_line(scope, detailed=True)}"),
    ]

    if stream_info.get("first_date") and stream_info.get("last_date"):
        lines.append(
            "Dabartinis grafikas: "
            f"{stream_info['first_date']} -> {stream_info['last_date']} "
            f"({stream_info.get('date_count') or 0} datos)."
        )

    lines.append(f"Paskutinis atnaujinimas: {updated_at}.")
    lines.append(
        _build_change_note(
            stream_info=stream_info,
            previous_dates=previous_dates,
            events_added=events_added,
            events_deleted=events_deleted,
        )
    )

    return "\n".join(lines)


def _build_event_description(calendar_stream_id: str, waste_type: str) -> str:
    scope = get_calendar_stream_scope(calendar_stream_id)
    return "\n".join(
        [
            WASTE_EVENT_DESCRIPTION.get(waste_type, "Išvežkite atliekų konteinerį."),
            _finish_sentence(f"Taikoma: {_format_scope_line(scope, detailed=False)}"),
            "Kalendorius automatiškai atnaujinamas.",
        ]
    )


def _refresh_calendar_metadata(
    *,
    service,
    calendar_id: str,
    calendar_stream_id: str,
    stream_info: dict,
    previous_dates: list[str] | None = None,
    events_added: int = 0,
    events_deleted: int = 0,
) -> None:
    description = _build_calendar_description(
        calendar_stream_id=calendar_stream_id,
        stream_info=stream_info,
        previous_dates=previous_dates,
        events_added=events_added,
        events_deleted=events_deleted,
    )
    throttle_calendar()
    service.calendars().patch(
        calendarId=calendar_id,
        body={"description": description},
    ).execute()


def post_cleanup_notice_for_stream(calendar_stream_id: str) -> None:
    """
    Post a 3-day cleanup notice to a deprecated calendar stream.
    """
    stream_info = get_calendar_stream_info(calendar_stream_id)
    if not stream_info or not stream_info.get("calendar_id"):
        return

    calendar_id = stream_info["calendar_id"]
    service = get_google_calendar_service()
    now = datetime.datetime.now()

    notice_summary = "Svarbu: atnaujinkite kalendoriaus prenumeratą"
    notice_description = (
        "Dėl techninės klaidos šis kalendorius nebesusisyncino su adresu. "
        "Prašome svetainėje rankiniu būdu įsidėti atnaujintą kalendorių "
        "(nemenkom.eidmantas.lt). "
        "Šis kalendorius bus pašalintas po 4 dienų."
    )

    for day_offset in range(3):
        event_date = (now + datetime.timedelta(days=day_offset)).date()
        event = {
            "summary": notice_summary,
            "description": notice_description,
            "start": {
                "dateTime": datetime.datetime(
                    event_date.year,
                    event_date.month,
                    event_date.day,
                    9,
                    0,
                ).isoformat(),
                "timeZone": config.GOOGLE_CALENDAR_TIMEZONE,
            },
            "end": {
                "dateTime": datetime.datetime(
                    event_date.year,
                    event_date.month,
                    event_date.day,
                    11,
                    0,
                ).isoformat(),
                "timeZone": config.GOOGLE_CALENDAR_TIMEZONE,
            },
        }

        throttle_calendar()
        service.events().insert(calendarId=calendar_id, body=event).execute()

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        UPDATE calendar_streams
        SET pending_clean_notice_sent_at = CURRENT_TIMESTAMP,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
    """,
        (calendar_stream_id,),
    )
    conn.commit()
    conn.close()


def delete_calendar_for_stream(calendar_stream_id: str) -> None:
    """
    Delete deprecated calendar for a stream if it has no linked groups.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT calendar_id
        FROM calendar_streams
        WHERE id = ?
    """,
        (calendar_stream_id,),
    )
    row = cursor.fetchone()
    if not row:
        conn.close()
        return

    cursor.execute(
        """
        SELECT COUNT(*) FROM group_calendar_links
        WHERE calendar_stream_id = ?
    """,
        (calendar_stream_id,),
    )
    linked_count = cursor.fetchone()[0]
    if linked_count > 0:
        conn.close()
        return

    calendar_id = row[0]
    conn.close()

    if calendar_id:
        service = get_google_calendar_service()
        throttle_calendar()
        service.calendars().delete(calendarId=calendar_id).execute()

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM calendar_stream_events WHERE calendar_stream_id = ?", (calendar_stream_id,))
    cursor.execute("DELETE FROM group_calendar_links WHERE calendar_stream_id = ?", (calendar_stream_id,))
    cursor.execute("DELETE FROM calendar_streams WHERE id = ?", (calendar_stream_id,))
    conn.commit()
    conn.close()


def create_calendar_for_schedule_group(schedule_group_id: str) -> dict | None:
    """
    Create a Google Calendar for a schedule group via its calendar stream.
    """
    calendar_stream_id = get_calendar_stream_id_for_schedule_group(schedule_group_id)
    if not calendar_stream_id:
        logger.warning(
            "No calendar stream linked for schedule_group_id=%s; skipping calendar creation",
            schedule_group_id,
        )
        return None

    return create_calendar_for_calendar_stream(calendar_stream_id)


def create_calendar_for_calendar_stream(calendar_stream_id: str) -> dict | None:
    """
    Create a Google Calendar for a calendar stream (date pattern + waste type).
    """
    start_time = time.time()
    logger.debug("Creating calendar for calendar_stream_id=%s", calendar_stream_id)
    print(
        f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] "
        f"Creating calendar for calendar_stream_id={calendar_stream_id}"
    )

    try:
        stream_info = get_calendar_stream_info(calendar_stream_id)
        if not stream_info:
            logger.error("Calendar stream not found: %s", calendar_stream_id)
            print(f" Calendar stream not found: {calendar_stream_id}")
            return None

        existing_calendar_id = stream_info.get("calendar_id")
        if existing_calendar_id:
            logger.debug(
                "Calendar already exists in DB for %s: %s",
                calendar_stream_id,
                existing_calendar_id,
            )
            try:
                calendar_info = get_existing_calendar_info(existing_calendar_id)
                if calendar_info:
                    try:
                        service = get_google_calendar_service()
                        acl_rule = {"scope": {"type": "default"}, "role": "reader"}
                        try:
                            throttle_calendar()
                            service.acl().get(
                                calendarId=existing_calendar_id, ruleId="default"
                            ).execute()
                        except HttpError:
                            throttle_calendar()
                            service.acl().insert(
                                calendarId=existing_calendar_id, body=acl_rule
                            ).execute()
                            logger.info(
                                "Made existing calendar public: %s",
                                existing_calendar_id,
                            )
                            print(f" Made existing calendar public: {existing_calendar_id}")
                    except Exception as e:
                        logger.warning("Could not ensure calendar is public: %s", e)

                    if not update_calendar_stream_calendar_id(
                        calendar_stream_id, existing_calendar_id
                    ):
                        logger.warning(
                            "Failed to update calendar_id in database for %s, but calendar exists",
                            calendar_stream_id,
                        )

                    try:
                        _refresh_calendar_metadata(
                            service=service,
                            calendar_id=existing_calendar_id,
                            calendar_stream_id=calendar_stream_id,
                            stream_info=stream_info,
                        )
                    except Exception as e:
                        logger.warning(
                            "Could not refresh existing calendar description for %s: %s",
                            existing_calendar_id,
                            e,
                        )

                    return {
                        "calendar_id": existing_calendar_id,
                        "calendar_name": calendar_info["calendar_name"],
                        "subscription_link": calendar_info["subscription_link"],
                        "success": True,
                        "existing": True,
                    }
            except Exception as e:
                logger.warning(
                    "Existing calendar %s for %s invalid, creating new one: %s",
                    existing_calendar_id,
                    calendar_stream_id,
                    e,
                )
                print(
                    f"  Existing calendar {existing_calendar_id} for "
                    f"{calendar_stream_id} invalid, creating new one: {e}"
                )

        scope = get_calendar_stream_scope(calendar_stream_id)
        seniunija = scope["seniunijos"][0] if scope["seniunijos"] else "Nemenčinė"

        waste_type = stream_info["waste_type"]
        waste_type_display = WASTE_TYPE_DISPLAY.get(waste_type, waste_type)

        short_hash = calendar_stream_id[:6] if len(calendar_stream_id) >= 6 else calendar_stream_id

        calendar_name = f"{seniunija} - {waste_type_display} - {short_hash}"
        calendar_description = _build_calendar_description(
            calendar_stream_id=calendar_stream_id,
            stream_info=stream_info,
        )

        logger.debug("Getting Google Calendar service for %s", calendar_stream_id)
        service = get_google_calendar_service()

        logger.debug(
            "Creating calendar '%s' for calendar_stream_id=%s",
            calendar_name,
            calendar_stream_id,
        )
        calendar = {
            "summary": calendar_name,
            "description": calendar_description,
            "timeZone": config.GOOGLE_CALENDAR_TIMEZONE,
        }

        throttle_calendar()
        created_calendar = service.calendars().insert(body=calendar).execute()
        calendar_id = created_calendar["id"]
        logger.debug(
            "Calendar created: %s for calendar_stream_id=%s",
            calendar_id,
            calendar_stream_id,
        )

        try:
            logger.debug("Making calendar public: %s", calendar_id)
            acl_rule = {"scope": {"type": "default"}, "role": "reader"}
            throttle_calendar()
            service.acl().insert(calendarId=calendar_id, body=acl_rule).execute()
            logger.info("Calendar made public: %s", calendar_id)
            print(f" Calendar made public: {calendar_id}")
        except Exception as e:
            logger.warning("Failed to make calendar public (may need manual sharing): %s", e)
            print(f"  Failed to make calendar public (may need manual sharing): {e}")

        if not update_calendar_stream_calendar_id(calendar_stream_id, calendar_id):
            logger.error(
                "CRITICAL: Failed to store calendar_id for calendar_stream_id=%s. "
                "Calendar %s was created but won't be tracked.",
                calendar_stream_id,
                calendar_id,
            )
            print(
                f" CRITICAL: Failed to store calendar_id in database for calendar_stream_id={calendar_stream_id}"
            )
            return {
                "calendar_id": calendar_id,
                "calendar_name": calendar_name,
                "subscription_link": generate_calendar_subscription_link(calendar_id),
                "success": True,
                "existing": False,
                "warning": "Calendar created but database update failed - may cause duplicates",
            }

        logger.info(
            "Calendar created successfully for calendar_stream_id=%s: %s",
            calendar_stream_id,
            calendar_id,
        )
        print(f" Calendar created for calendar_stream_id={calendar_stream_id}: {calendar_id}")

        return {
            "calendar_id": calendar_id,
            "calendar_name": calendar_name,
            "subscription_link": generate_calendar_subscription_link(calendar_id),
            "success": True,
            "existing": False,
        }

    except HttpError as error:
        logger.error(
            "Google Calendar API error for calendar_stream_id=%s: %s",
            calendar_stream_id,
            error,
        )
        print(f" Google Calendar API error for calendar_stream_id={calendar_stream_id}: {error}")
        if "rateLimitExceeded" in str(error) or "quotaExceeded" in str(error):
            backoff("calendar_rate_limit")
        return None
    except Exception as e:
        logger.error(
            "Unexpected error creating calendar for calendar_stream_id=%s: %s",
            calendar_stream_id,
            e,
            exc_info=True,
        )
        print(
            f" Unexpected error creating calendar for calendar_stream_id={calendar_stream_id}: {e}"
        )
        import traceback

        traceback.print_exc()
        return None
    finally:
        end_time = time.time()
        logger.debug(
            "Calendar creation for %s took %.2fs",
            calendar_stream_id,
            end_time - start_time,
        )


def cleanup_orphaned_calendars(dry_run: bool = True) -> list[dict]:
    """
    Find and optionally delete calendars that exist in Google Calendar but not in database

    Orphaned calendars are those that:
    - Exist in Google Calendar (created by our service account)
    - Do NOT have a corresponding entry in calendar_streams.calendar_id

    Args:
        dry_run: If True, only list orphaned calendars without deleting (default: True)

    Returns:
        List of orphaned calendar dictionaries with calendar_id and calendar_name
    """
    try:
        service = get_google_calendar_service()

        # Get all calendars from Google Calendar that the service account can access
        throttle_calendar()
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
            FROM calendar_streams
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
                print(f"\n Found {len(orphaned)} orphaned calendar(s):")
                for cal in orphaned:
                    print(f"   - {cal['calendar_name']} ({cal['calendar_id'][:30]}...)")
                print("\n  This is a DRY RUN - no calendars were deleted")
                print("   Run 'make clean-calendars' to actually delete them")
            else:
                print(
                    " No orphaned calendars found - all calendars in Google Calendar have corresponding database entries"
                )
        else:
            # Actually delete orphaned calendars
            deleted_count = 0
            error_count = 0
            for _idx, cal in enumerate(orphaned):
                try:
                    throttle_calendar()
                    service.calendars().delete(calendarId=cal["calendar_id"]).execute()
                    deleted_count += 1
                    print(f"  Deleted orphaned calendar: {cal['calendar_name']}")

                except HttpError as e:
                    if "rateLimitExceeded" in str(e) or "quotaExceeded" in str(e):
                        error_count += 1
                        print(f"  Rate limit hit - will retry later: {cal['calendar_name']}")
                        backoff("calendar_rate_limit")
                    else:
                        error_count += 1
                        print(f" Failed to delete calendar {cal['calendar_name']}: {e}")
                except Exception as e:
                    error_count += 1
                    print(f" Failed to delete calendar {cal['calendar_name']}: {e}")

            print(f"\n Cleanup complete: {deleted_count} deleted, {error_count} errors")
            if error_count > 0:
                print("   Run 'make clean-calendars' again to retry failed deletions")

        return orphaned

    except HttpError as error:
        print(f" Error during calendar cleanup: {error}")
        return []
    except Exception as e:
        print(f" Unexpected error during calendar cleanup: {e}")
        return []


def sync_calendar_for_schedule_group(schedule_group_id: str) -> dict:
    """
    Sync calendar events for a schedule group via its calendar stream.
    """
    calendar_stream_id = get_calendar_stream_id_for_schedule_group(schedule_group_id)
    if not calendar_stream_id:
        logger.error(
            "No calendar stream linked for schedule_group_id=%s",
            schedule_group_id,
        )
        return {"success": False, "error": "Calendar stream not linked"}

    return sync_calendar_for_calendar_stream(calendar_stream_id)


def sync_calendar_for_calendar_stream(calendar_stream_id: str) -> dict:
    """
    Sync calendar events for a calendar stream (add new, delete old, retry failed).
    """
    start_time = time.time()
    logger.debug("Syncing calendar events for calendar_stream_id=%s", calendar_stream_id)

    try:
        stream_info = get_calendar_stream_info(calendar_stream_id)
        if not stream_info:
            logger.error("Calendar stream not found: %s", calendar_stream_id)
            return {"success": False, "error": "Calendar stream not found"}

        calendar_id = stream_info.get("calendar_id")
        if not calendar_id:
            logger.error("No calendar_id for calendar_stream_id: %s", calendar_stream_id)
            return {"success": False, "error": "Calendar not created yet"}

        dates = stream_info.get("dates", [])
        if not dates:
            logger.warning("No dates for calendar_stream_id: %s", calendar_stream_id)
            update_calendar_stream_calendar_synced(calendar_stream_id)
            return {
                "success": True,
                "events_added": 0,
                "events_deleted": 0,
                "events_retried": 0,
            }

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT date, event_id, status
            FROM calendar_stream_events
            WHERE calendar_stream_id = ?
        """,
            (calendar_stream_id,),
        )

        existing_events = {
            row[0]: {"event_id": row[1], "status": row[2]} for row in cursor.fetchall()
        }
        conn.close()

        current_dates = set(dates)
        existing_dates = set(existing_events.keys())

        dates_to_add = current_dates - existing_dates
        dates_to_delete = existing_dates - current_dates
        dates_to_retry = {
            date
            for date, info in existing_events.items()
            if info["status"] == "error" and date in current_dates
        }

        logger.info(
            "In-place update for %s: add %s, delete %s, retry %s, keep %s unchanged",
            calendar_stream_id,
            len(dates_to_add),
            len(dates_to_delete),
            len(dates_to_retry),
            len(current_dates & existing_dates),
        )

        service = get_google_calendar_service()
        waste_type = stream_info["waste_type"]

        waste_type_display = WASTE_EVENT_SUMMARY.get(waste_type, f"{waste_type} surinkimas")
        event_description = _build_event_description(calendar_stream_id, waste_type)

        events_added = 0
        events_deleted = 0
        events_retried = 0
        previous_dates = sorted(existing_dates)

        for date_str in dates_to_delete:
            event_id = existing_events[date_str]["event_id"]
            if event_id:
                try:
                    throttle_calendar()
                    service.events().delete(calendarId=calendar_id, eventId=event_id).execute()
                    events_deleted += 1
                    logger.debug("Deleted event %s for date %s", event_id, date_str)
                except Exception as e:
                    logger.error(
                        "Failed to delete event %s for date %s: %s",
                        event_id,
                        date_str,
                        e,
                    )

            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute(
                """
                DELETE FROM calendar_stream_events
                WHERE calendar_stream_id = ? AND date = ?
            """,
                (calendar_stream_id, date_str),
            )
            conn.commit()
            conn.close()

        for date_str in dates_to_add:
            try:
                date_obj = datetime.datetime.strptime(date_str, "%Y-%m-%d")
                event_date = date_obj.date()

                event = {
                    "summary": waste_type_display,
                    "description": event_description,
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

                throttle_calendar()
                created_event = (
                    service.events().insert(calendarId=calendar_id, body=event).execute()
                )

                event_id = created_event["id"]
                events_added += 1

                conn = get_db_connection()
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO calendar_stream_events (calendar_stream_id, date, event_id, status)
                    VALUES (?, ?, ?, 'created')
                    ON CONFLICT(calendar_stream_id, date) DO UPDATE SET
                        event_id = ?, status = 'created', updated_at = CURRENT_TIMESTAMP
                """,
                    (calendar_stream_id, date_str, event_id, event_id),
                )
                conn.commit()
                conn.close()

                logger.debug("Created event %s for date %s", event_id, date_str)

            except Exception as e:
                logger.error("Failed to create event for %s: %s", date_str, e)
                conn = get_db_connection()
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO calendar_stream_events (calendar_stream_id, date, status, error_message)
                    VALUES (?, ?, 'error', ?)
                    ON CONFLICT(calendar_stream_id, date) DO UPDATE SET
                        status = 'error', error_message = ?, updated_at = CURRENT_TIMESTAMP
                """,
                    (calendar_stream_id, date_str, str(e), str(e)),
                )
                conn.commit()
                conn.close()

        for date_str in dates_to_retry:
            try:
                date_obj = datetime.datetime.strptime(date_str, "%Y-%m-%d")
                event_date = date_obj.date()

                event = {
                    "summary": waste_type_display,
                    "description": event_description,
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

                throttle_calendar()
                created_event = (
                    service.events().insert(calendarId=calendar_id, body=event).execute()
                )

                event_id = created_event["id"]
                events_retried += 1

                conn = get_db_connection()
                cursor = conn.cursor()
                cursor.execute(
                    """
                    UPDATE calendar_stream_events
                    SET event_id = ?, status = 'created', error_message = NULL, updated_at = CURRENT_TIMESTAMP
                    WHERE calendar_stream_id = ? AND date = ?
                """,
                    (event_id, calendar_stream_id, date_str),
                )
                conn.commit()
                conn.close()

                logger.debug("Retried event %s for date %s", event_id, date_str)

            except Exception as e:
                logger.error("Failed to retry event for %s: %s", date_str, e)
                conn = get_db_connection()
                cursor = conn.cursor()
                cursor.execute(
                    """
                    UPDATE calendar_stream_events
                    SET status = 'error', error_message = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE calendar_stream_id = ? AND date = ?
                """,
                    (str(e), calendar_stream_id, date_str),
                )
                conn.commit()
                conn.close()

        update_calendar_stream_calendar_synced(calendar_stream_id)
        stream_info = get_calendar_stream_info(calendar_stream_id)
        if stream_info:
            try:
                _refresh_calendar_metadata(
                    service=service,
                    calendar_id=calendar_id,
                    calendar_stream_id=calendar_stream_id,
                    stream_info=stream_info,
                    previous_dates=previous_dates,
                    events_added=events_added,
                    events_deleted=events_deleted,
                )
            except Exception as e:
                logger.warning(
                    "Could not refresh calendar description for %s: %s",
                    calendar_stream_id,
                    e,
                )

        total_time = time.time() - start_time
        logger.info(
            "Calendar sync complete for %s in %.2fs: added=%s, deleted=%s, retried=%s",
            calendar_stream_id,
            total_time,
            events_added,
            events_deleted,
            events_retried,
        )

        return {
            "success": True,
            "events_added": events_added,
            "events_deleted": events_deleted,
            "events_retried": events_retried,
        }

    except HttpError as error:
        logger.error("Google Calendar API error: %s", error)
        return {"success": False, "error": str(error)}
    except Exception as e:
        logger.error("Unexpected error syncing calendar: %s", e, exc_info=True)
        return {"success": False, "error": str(e)}
