"""
Shared DB connection helpers.
"""

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "database" / "waste_schedule.db"


def get_db_connection():
    """Get a database connection."""
    if not DB_PATH.exists():
        raise FileNotFoundError(
            f"Database not found at {DB_PATH}. Run the scraper or apply migrations."
        )
    return sqlite3.connect(str(DB_PATH), check_same_thread=False)
