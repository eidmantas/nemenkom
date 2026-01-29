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
            f"Secret file not found: {secrets_path}\n"
            f"Please create this file with your API key/secret.\n"
            f"See INSTALL.md for setup instructions."
        )
    with open(secrets_path) as f:
        content = f.read().strip()
        if not content:
            raise ValueError(
                f"Secret file is empty: {secrets_path}\n"
                f"Please add your API key/secret to this file.\n"
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
            f"Secret file not found: {secrets_path}{desc}\n"
            f"Please create this file with your API key/secret.\n"
            f"See INSTALL.md for setup instructions."
        )
    if os.path.getsize(secrets_path) == 0:
        desc = f" ({description})" if description else ""
        raise ValueError(
            f"Secret file is empty: {secrets_path}{desc}\n"
            f"Please add your API key/secret to this file.\n"
            f"See INSTALL.md for setup instructions."
        )


def _read_secret_file_optional(filename: str) -> str | None:
    """Read a secret file if it exists and is not empty; return None otherwise."""
    secrets_path = os.path.join("secrets", filename)
    if not os.path.exists(secrets_path):
        return None
    with open(secrets_path) as f:
        content = f.read().strip()
        return content or None


DEBUG = os.getenv("DEBUG", "1") == "1"
LOG_LEVEL = os.getenv("LOG_LEVEL", "DEBUG" if DEBUG else "INFO")


AI_PROVIDERS = [
    {
        "name": "openrouter",
        "base_url": "https://openrouter.ai/api/v1",
        "api_key": _read_secret_file_optional("openrouter_api_key.txt"),
    },
    {
        "name": "groq",
        "base_url": "https://api.groq.com/openai/v1",
        "api_key": _read_secret_file_optional("groq_api_key.txt"),
    },
]

# Rotation order: providers/models are tried in this sequence across retries.
AI_MODEL_ROTATION = [
    {"provider": "openrouter", "model": "openai/gpt-oss-120b:free"},
    {"provider": "openrouter", "model": "google/gemini-2.0-flash-exp:free"},
    {"provider": "openrouter", "model": "google/gemma-3-27b-it:free"},
    {"provider": "openrouter", "model": "qwen/qwen3-coder:free"},
    {"provider": "groq", "model": "llama-3.3-70b-versatile"},
    {"provider": "groq", "model": "llama-3.1-8b-instant"},
]


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


API_KEY = _read_secret_file("api_key.txt")
API_KEY_HEADER = "X-API-KEY"


try:
    _validate_secret_file("api_key.txt", "API authentication key")
    _validate_secret_file("credentials.json", "Google Calendar Service Account credentials")
    if not any(provider.get("api_key") for provider in AI_PROVIDERS):
        raise ValueError(
            "No AI provider API keys found. Add at least one of: "
            "secrets/openrouter_api_key.txt or secrets/groq_api_key.txt"
        )
except (FileNotFoundError, ValueError) as e:
    raise RuntimeError(
        f"Configuration validation failed:\n{e}\n\n"
        f"Please ensure all required secret files exist and are not empty.\n"
        f"See INSTALL.md for detailed setup instructions."
    ) from e
