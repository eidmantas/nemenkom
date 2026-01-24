"""
Google Calendar integration for waste schedule system
Handles calendar creation and event management for schedule groups
"""
import datetime
import os.path
import json
from typing import Optional, Dict, List

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# Import configuration
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
import config

def get_google_calendar_service():
    """
    Get authenticated Google Calendar service
    Uses pre-authorized token file for headless operation
    """
    creds = None

    # The file token.json stores the user's access and refresh tokens
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', config.GOOGLE_CALENDAR_SCOPES)
    
    # If no valid credentials, raise error (headless backend - no interactive auth)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            raise Exception("No valid Google Calendar credentials found. Please authenticate first.")

    # Build the Calendar API service
    return build('calendar', 'v3', credentials=creds)

def authenticate_and_save_token():
    """
    Authenticate using client secrets and save token.json
    This is for initial setup only - should be run manually
    """
    try:
        flow = InstalledAppFlow.from_client_secrets_file(
            'config-gcp-creds.json', config.GOOGLE_CALENDAR_SCOPES
        )
        creds = flow.run_local_server(port=0)
        
        # Save the credentials for the next run
        with open('token.json', 'w') as token:
            token.write(creds.to_json())
        
        print("✅ Authentication successful! Token saved to token.json")
        return True
        
    except Exception as e:
        print(f"❌ Authentication failed: {e}")
        return False

def ensure_token_exists():
    """
    Ensure token.json exists, create it if needed
    """
    if not os.path.exists('token.json'):
        print("⚠️  No token.json found. Running authentication...")
        if not authenticate_and_save_token():
            raise Exception("Failed to create authentication token")

def create_calendar_for_schedule_group(
    schedule_group_id: str,
    location_name: str,
    dates: List[str],
    waste_type: str = "bendros"
) -> Optional[Dict]:
    """
    Create a Google Calendar with events for a schedule group

    Args:
        schedule_group_id: Unique identifier for the schedule group
        location_name: Human-readable location name (village/street)
        dates: List of date strings in YYYY-MM-DD format
        waste_type: Type of waste (bendros, plastikas, stiklas)

    Returns:
        Dictionary with calendar info and subscription link, or None if failed
    """
    try:
        service = get_google_calendar_service()

        # Create calendar name
        calendar_name = f"Nemenčinė Atliekos - {location_name} - {waste_type}"
        calendar_description = f"Buitinių atliekų surinkimo grafikas: {location_name}"

        # Create the calendar
        calendar = {
            'summary': calendar_name,
            'description': calendar_description,
            'timeZone': config.GOOGLE_CALENDAR_TIMEZONE
        }

        created_calendar = service.calendars().insert(body=calendar).execute()
        calendar_id = created_calendar['id']

        # Add events for each date
        for date_str in dates:
            try:
                date_obj = datetime.datetime.strptime(date_str, "%Y-%m-%d")
                event_date = date_obj.date()

                # Create event with proper timing (07:00-09:00)
                event = {
                    'summary': f"Buitinių atliekų surinkimas - {location_name}",
                    'description': "Išvežkite bendrų šiukšlių dėžę",
                    'start': {
                        'dateTime': datetime.datetime(
                            event_date.year,
                            event_date.month,
                            event_date.day,
                            config.GOOGLE_CALENDAR_EVENT_START_HOUR,
                            0
                        ).isoformat(),
                        'timeZone': config.GOOGLE_CALENDAR_TIMEZONE,
                    },
                    'end': {
                        'dateTime': datetime.datetime(
                            event_date.year,
                            event_date.month,
                            event_date.day,
                            config.GOOGLE_CALENDAR_EVENT_END_HOUR,
                            0
                        ).isoformat(),
                        'timeZone': config.GOOGLE_CALENDAR_TIMEZONE,
                    },
                    'reminders': {
                        'useDefault': False,
                        'overrides': config.GOOGLE_CALENDAR_REMINDERS,
                    },
                }

                # Add event to calendar
                service.events().insert(
                    calendarId=calendar_id,
                    body=event
                ).execute()

            except Exception as e:
                print(f"⚠️  Failed to create event for {date_str}: {e}")
                continue

        # Return calendar info with subscription link
        return {
            'calendar_id': calendar_id,
            'calendar_name': calendar_name,
            'subscription_link': f"https://calendar.google.com/calendar/render?cid={calendar_id}",
            'events_created': len(dates),
            'success': True
        }

    except HttpError as error:
        print(f"❌ Google Calendar API error: {error}")
        return None
    except Exception as e:
        print(f"❌ Unexpected error creating calendar: {e}")
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
            'calendar_id': calendar['id'],
            'calendar_name': calendar['summary'],
            'description': calendar.get('description', ''),
            'subscription_link': f"https://calendar.google.com/calendar/render?cid={calendar['id']}",
            'timeZone': calendar['timeZone']
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
        calendars = calendars_result.get('items', [])

        # Filter for our waste schedule calendars
        waste_calendars = []
        for calendar in calendars:
            if 'Nemenčinė Atliekos' in calendar.get('summary', ''):
                waste_calendars.append({
                    'calendar_id': calendar['id'],
                    'calendar_name': calendar['summary'],
                    'description': calendar.get('description', ''),
                    'subscription_link': f"https://calendar.google.com/calendar/render?cid={calendar['id']}",
                    'timeZone': calendar['timeZone']
                })

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
