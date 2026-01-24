"""
Example configuration file
Copy this to config.py and fill in your API keys
DO NOT COMMIT config.py - it contains sensitive information
"""
import os.path

def _read_secret_file(filename: str) -> str:
    """Read a secret from the secrets/ folder"""
    secrets_path = os.path.join("secrets", filename)
    if not os.path.exists(secrets_path):
        raise FileNotFoundError(
            f"Secret file not found: {secrets_path}\n"
            f"Please create this file with your API key/secret."
        )
    with open(secrets_path, 'r') as f:
        return f.read().strip()

# Groq API Configuration
GROQ_API_KEY = _read_secret_file("groq_api_key.txt")  # Read from secrets/groq_api_key.txt
GROQ_MODEL = "llama-3.3-70b-versatile"  # Higher quality model for better parsing of complex cases
# Alternative: "llama-3.1-8b-instant" for faster processing with better rate limits (14.4k RPD, 6k TPM, 500k TPD)
# Note: Instant model can be used temporarily for bug fixing to save tokens
GROQ_BASE_URL = "https://api.groq.com/openai/v1"

# Rate Limiting (Groq free tier limits)
# Conservative: Using 50% §of free tier limits for safety
GROQ_RATE_LIMIT_RPM = 15  # Requests per minute (reduced from 30 for safety)
GROQ_RATE_LIMIT_RPD = 14400  # Requests per day
GROQ_RATE_LIMIT_TPM = 6000  # Tokens per minute
GROQ_RATE_LIMIT_TPD = 500000  # Tokens per day

# Safety margin (use 90% of limits to avoid hitting them)
GROQ_SAFETY_MARGIN = 0.9

# Google Calendar API Configuration
GOOGLE_CALENDAR_CREDENTIALS_FILE = "secrets/credentials.json"  # Path to Service Account JSON key file
GOOGLE_CALENDAR_SCOPES = [
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/calendar"
]
GOOGLE_CALENDAR_TIMEZONE = "Europe/Vilnius"  # Timezone for calendar events
GOOGLE_CALENDAR_EVENT_START_HOUR = 7  # Collection starts at 07:00
GOOGLE_CALENDAR_EVENT_END_HOUR = 9   # Collection ends at 09:00
GOOGLE_CALENDAR_REMINDERS = [
    {'method': 'email', 'minutes': 720},    # 12 hours before (19:00 previous evening)
    {'method': 'popup', 'minutes': 10}     # 10 minutes before
]

# API Authentication
API_KEY = _read_secret_file("api_key.txt")  # Read from secrets/api_key.txt
API_KEY_HEADER = "X-API-KEY"  # Custom header for API key authentication
