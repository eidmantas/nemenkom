"""
Example configuration file. Copy to config.py and fill secrets.
"""
import os
import os.path


def _read_secret_file(filename: str) -> str:
    """Read a secret from the secrets/ folder."""
    secrets_path = os.path.join("secrets", filename)
    if not os.path.exists(secrets_path):
        raise FileNotFoundError(
            f"Secret file not found: {secrets_path}
"
            f"Please create this file with your API key/secret.
"
            f"See INSTALL.md for setup instructions."
        )
    with open(secrets_path, "r") as f:
        content = f.read().strip()
        if not content:
            raise ValueError(
                f"Secret file is empty: {secrets_path}
"
                f"Please add your API key/secret to this file.
"
                f"See INSTALL.md for setup instructions."
            )
        return content


def _validate_secret_file(filename: str, description: str | None = None) -> None:
    """
    Validate that a secret file exists and is not empty.
    Raises FileNotFoundError or ValueError if validation fails.
    """
    secrets_path = os.path.join("secrets", filename)
    if not os.path.exists(secrets_path):
        desc = f" ({description})" if description else ""
        raise FileNotFoundError(
            f"Secret file not found: {secrets_path}{desc}
"
            f"Please create this file with your API key/secret.
"
            f"See INSTALL.md for setup instructions."
        )
    if os.path.getsize(secrets_path) == 0:
        desc = f" ({description})" if description else ""
        raise ValueError(
            f"Secret file is empty: {secrets_path}{desc}
"
            f"Please add your API key/secret to this file.
"
            f"See INSTALL.md for setup instructions."
        )


# ---------------------------------------------------------------------------
# Logging Configuration
# ---------------------------------------------------------------------------
DEBUG = os.getenv("DEBUG", "1") == "1"
LOG_LEVEL = os.getenv("LOG_LEVEL", "DEBUG" if DEBUG else "INFO")


# ---------------------------------------------------------------------------
# Groq API Configuration
# ---------------------------------------------------------------------------
GROQ_API_KEY = _read_secret_file("groq_api_key.txt")
GROQ_MODEL = "llama-3.1-8b-instant"
GROQ_BASE_URL = "https://api.groq.com/openai/v1"

# Rate Limiting (Groq free tier limits for llama-3.1-8b-instant)
GROQ_RATE_LIMIT_RPM = 15   # Requests per minute
GROQ_RATE_LIMIT_RPD = 14400  # Requests per day
GROQ_RATE_LIMIT_TPM = 6000   # Tokens per minute
GROQ_RATE_LIMIT_TPD = 500000  # Tokens per day
GROQ_SAFETY_MARGIN = 0.9


# ---------------------------------------------------------------------------
# Google Calendar API Configuration
# ---------------------------------------------------------------------------
GOOGLE_CALENDAR_CREDENTIALS_FILE = "secrets/credentials.json"
GOOGLE_CALENDAR_SCOPES = [
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/calendar",
]
GOOGLE_CALENDAR_TIMEZONE = "Europe/Vilnius"
GOOGLE_CALENDAR_EVENT_START_HOUR = 7
GOOGLE_CALENDAR_EVENT_END_HOUR = 9
GOOGLE_CALENDAR_REMINDERS = [
    {"method": "email", "minutes": 720},
    {"method": "popup", "minutes": 10},
]


# ---------------------------------------------------------------------------
# API Authentication
# ---------------------------------------------------------------------------
API_KEY = _read_secret_file("api_key.txt")
API_KEY_HEADER = "X-API-KEY"


# ---------------------------------------------------------------------------
# Secrets Validation
# ---------------------------------------------------------------------------
try:
    _validate_secret_file("api_key.txt", "API authentication key")
    _validate_secret_file("groq_api_key.txt", "Groq API key")
    _validate_secret_file("credentials.json", "Google Calendar Service Account credentials")
except (FileNotFoundError, ValueError) as e:
    raise RuntimeError(
        f"Configuration validation failed:
{e}

"
        f"Please ensure all required secret files exist and are not empty.
"
        f"See INSTALL.md for detailed setup instructions."
    ) from e
