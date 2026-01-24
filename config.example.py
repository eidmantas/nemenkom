"""
Example configuration file
Copy this to config.py and fill in your API keys
DO NOT COMMIT config.py - it contains sensitive information
"""

# Groq API Configuration
GROQ_API_KEY = ""  # Add your Groq API key here
GROQ_MODEL = "llama-3.3-70b-versatile"  # Higher quality model for better parsing of complex cases
# Alternative: "llama-3.1-8b-instant" for faster processing with better rate limits (14.4k RPD, 6k TPM, 500k TPD)
# Note: Instant model can be used temporarily for bug fixing to save tokens
GROQ_BASE_URL = "https://api.groq.com/openai/v1"

# Rate Limiting (Groq free tier limits)
# Conservative: Using 50% of free tier limits for safety
GROQ_RATE_LIMIT_RPM = 15  # Requests per minute (reduced from 30 for safety)
GROQ_RATE_LIMIT_RPD = 14400  # Requests per day
GROQ_RATE_LIMIT_TPM = 6000  # Tokens per minute
GROQ_RATE_LIMIT_TPD = 500000  # Tokens per day

# Safety margin (use 90% of limits to avoid hitting them)
GROQ_SAFETY_MARGIN = 0.9

# Google Calendar API Configuration
GOOGLE_CALENDAR_CREDENTIALS_FILE = "credentials.json"  # Path to Google OAuth credentials file
GOOGLE_CALENDAR_TOKEN_FILE = "token.json"  # Path to store OAuth tokens
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
API_KEY = "your_secure_api_key_here"  # Generate a strong random key for production
API_KEY_HEADER = "X-API-KEY"  # Custom header for API key authentication
