"""
Shared, read-only Google Calendar helpers for API usage.
"""
import logging
import os.path
from typing import Dict, List, Optional

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

import config
from services.common.logging_utils import setup_logging
from services.common.throttle import throttle

setup_logging()
logger = logging.getLogger(__name__)


def _throttle_calendar() -> None:
    throttle("calendar")


def get_google_calendar_service():
    """
    Get authenticated Google Calendar service using Service Account.
    Fully headless authentication - no tokens needed.
    """
    credentials_file = config.GOOGLE_CALENDAR_CREDENTIALS_FILE

    if not os.path.exists(credentials_file):
        raise FileNotFoundError(
            f"Google Calendar credentials file not found: {credentials_file}\n"
            f"Please create a Service Account JSON key file at this path.\n"
            f"See INSTALL.md for detailed setup instructions."
        )

    if os.path.getsize(credentials_file) == 0:
        raise ValueError(
            f"Google Calendar credentials file is empty: {credentials_file}\n"
            f"Please add your Service Account JSON credentials.\n"
            f"See INSTALL.md for detailed setup instructions."
        )

    try:
        creds = service_account.Credentials.from_service_account_file(
            credentials_file, scopes=config.GOOGLE_CALENDAR_SCOPES
        )
        return build("calendar", "v3", credentials=creds)
    except Exception as e:
        raise Exception(
            f"Failed to authenticate with Google Calendar: {e}\n"
            f"Make sure {credentials_file} is a valid Service Account JSON key file"
        )


def get_existing_calendar_info(calendar_id: str) -> Optional[Dict]:
    """
    Get information about an existing calendar.
    """
    try:
        service = get_google_calendar_service()
        _throttle_calendar()
        calendar = service.calendars().get(calendarId=calendar_id).execute()

        return {
            "calendar_id": calendar["id"],
            "calendar_name": calendar["summary"],
            "description": calendar.get("description", ""),
            "subscription_link": f"https://calendar.google.com/calendar/render?cid={calendar['id']}",
            "timeZone": calendar["timeZone"],
        }
    except HttpError as error:
        logger.warning("Error getting calendar info: %s", error)
        return None
    except Exception as e:
        logger.exception("Unexpected error getting calendar info: %s", e)
        return None


def list_available_calendars() -> List[Dict]:
    """
    List calendars created by this application.
    """
    try:
        service = get_google_calendar_service()
        _throttle_calendar()
        calendars_result = service.calendarList().list().execute()
        calendars = calendars_result.get("items", [])

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
        logger.warning("Error listing calendars: %s", error)
        return []
    except Exception as e:
        logger.exception("Unexpected error listing calendars: %s", e)
        return []


def generate_calendar_subscription_link(calendar_id: str) -> str:
    """
    Generate a subscription link for a calendar.
    """
    return f"https://calendar.google.com/calendar/render?cid={calendar_id}"
