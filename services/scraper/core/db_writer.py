"""
Database writer module - Writes validated data to SQLite
"""

import hashlib
import json
import sqlite3
from datetime import date, datetime
from typing import Dict, List, Optional

from services.common.db import get_db_connection


def generate_kaimai_hash(kaimai_str: str) -> str:
    """Generate hash for Kaimai column"""
    hash_obj = hashlib.sha256(kaimai_str.encode())
    return f"k1_{hash_obj.hexdigest()[:12]}"


def generate_schedule_group_id(kaimai_hash: str, waste_type: str = "bendros") -> str:
    """
    Generate STABLE schedule group ID from kaimai_hash + waste_type

    This ID NEVER changes, even when dates change.
    This ensures calendar IDs remain stable for users.
    """
    combined = f"{waste_type}:{kaimai_hash}"
    hash_obj = hashlib.sha256(combined.encode())
    hash_hex = hash_obj.hexdigest()[:12]
    return f"sg_{hash_hex}"


def generate_dates_hash(dates: List[date]) -> str:
    """
    Generate hash of sorted dates for change detection

    Used to detect when schedule dates have changed and calendar needs re-sync
    """
    if not dates:
        return ""
    date_str = ",".join(
        sorted([d.isoformat() if isinstance(d, date) else str(d) for d in dates])
    )
    hash_obj = hashlib.sha256(date_str.encode())
    return hash_obj.hexdigest()[:16]


def find_or_create_schedule_group(
    conn: sqlite3.Connection, dates: List, waste_type: str, kaimai_hash: str
) -> str:
    """
    Find existing schedule group by stable ID (kaimai_hash + waste_type), or create new one.

    OPTION B: Uses stable ID that never changes, even when dates change.
    Detects date changes via dates_hash and marks calendar for re-sync.

    Args:
        conn: Database connection
        dates: List of date objects
        waste_type: Waste type ('bendros', 'plastikas', etc.)
        kaimai_hash: Hash of original Kaimai string (single value, not JSON array)

    Returns:
        schedule_group_id (stable hash-based string like "sg_a3f8b2c1d4e5")
    """
    # Generate STABLE ID (based on kaimai_hash + waste_type, NOT dates!)
    schedule_group_id = generate_schedule_group_id(kaimai_hash, waste_type)
    new_dates_hash = generate_dates_hash(dates)
    cursor = conn.cursor()

    # Check if schedule group exists (by stable ID)
    cursor.execute(
        "SELECT dates_hash FROM schedule_groups WHERE id = ?", (schedule_group_id,)
    )
    row = cursor.fetchone()

    if row:
        # Schedule group exists - check if dates changed
        existing_dates_hash = row[0]

        if existing_dates_hash != new_dates_hash:
            # Dates changed! Update dates and mark calendar for re-sync
            if not dates:
                first_date = None
                last_date = None
                date_count = 0
            else:
                first_date = min(dates).isoformat()
                last_date = max(dates).isoformat()
                date_count = len(dates)

            # Convert dates to JSON array
            dates_json = json.dumps(
                [
                    d.isoformat() if isinstance(d, date) else str(d)
                    for d in sorted(dates)
                ]
            )

            cursor.execute(
                """
                UPDATE schedule_groups 
                SET dates = ?, dates_hash = ?, 
                    first_date = ?, last_date = ?, date_count = ?,
                    calendar_synced_at = NULL,  -- Trigger re-sync!
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """,
                (
                    dates_json,
                    new_dates_hash,
                    first_date,
                    last_date,
                    date_count,
                    schedule_group_id,
                ),
            )
    else:
        # Create new schedule group
        if not dates:
            first_date = None
            last_date = None
            date_count = 0
        else:
            first_date = min(dates).isoformat()
            last_date = max(dates).isoformat()
            date_count = len(dates)

        # Convert dates to JSON array
        dates_json = json.dumps(
            [d.isoformat() if isinstance(d, date) else str(d) for d in sorted(dates)]
        )

        cursor.execute(
            """
            INSERT INTO schedule_groups (id, waste_type, kaimai_hash, dates, dates_hash, first_date, last_date, date_count, calendar_synced_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL)
        """,
            (
                schedule_group_id,
                waste_type,
                kaimai_hash,
                dates_json,
                new_dates_hash,
                first_date,
                last_date,
                date_count,
            ),
        )

    return schedule_group_id  # Always stable!


def write_location_schedule(
    conn: sqlite3.Connection,
    seniunija: str,
    village: str,
    street: str,
    dates: List,
    kaimai_str: str,
    house_numbers: Optional[str] = None,
    waste_type: str = "bendros",
) -> int:
    """
    Write or update location and its pickup dates

    Args:
        conn: Database connection
        seniunija: County/municipality name
        village: Village name
        street: Street name (empty string if whole village)
        dates: List of date objects
        kaimai_str: Original Kaimai string (for hash generation)
        house_numbers: Optional house number restrictions
        waste_type: Waste type ('bendros', 'plastikas', etc.)

    Returns:
        location_id
    """
    cursor = conn.cursor()

    # Generate kaimai_hash
    kaimai_hash = generate_kaimai_hash(kaimai_str)

    # Find or create schedule group (updates kaimai_hash)
    find_or_create_schedule_group(conn, dates, waste_type, kaimai_hash)

    # Normalize house_numbers (None -> NULL in DB)
    house_nums_str = house_numbers if house_numbers else None

    # Insert or update location (no FK to schedule_group, just store kaimai_hash)
    # Convert datetime to ISO format string to avoid deprecation warning (Python 3.12+)
    now_str = datetime.now().isoformat()
    cursor.execute(
        """
        INSERT INTO locations (seniunija, village, street, house_numbers, kaimai_hash, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(seniunija, village, street, house_numbers) 
        DO UPDATE SET kaimai_hash = ?, updated_at = ?
    """,
        (
            seniunija,
            village,
            street,
            house_nums_str,
            kaimai_hash,
            now_str,
            kaimai_hash,
            now_str,
        ),
    )

    # Dates are now stored in schedule_groups, not in pickup_dates table
    # No need to insert pickup_dates - just return location_id
    location_id = cursor.lastrowid
    if location_id == 0:
        # Location already exists, get its ID
        cursor.execute(
            "SELECT id FROM locations WHERE seniunija = ? AND village = ? AND street = ? AND (house_numbers = ? OR (house_numbers IS NULL AND ? IS NULL))",
            (seniunija, village, street, house_nums_str, house_nums_str),
        )
        location_id = cursor.fetchone()[0]

    return location_id


def log_fetch(
    conn: sqlite3.Connection,
    source_url: str,
    status: str,
    validation_errors: Optional[List[str]] = None,
) -> int:
    """
    Log a data fetch attempt

    Args:
        conn: Database connection
        source_url: URL that was fetched
        status: 'success', 'failed', or 'validation_error'
        validation_errors: Optional list of validation error messages

    Returns:
        fetch_id
    """
    cursor = conn.cursor()
    errors_json = json.dumps(validation_errors) if validation_errors else None

    cursor.execute(
        """
        INSERT INTO data_fetches (source_url, status, validation_errors)
        VALUES (?, ?, ?)
    """,
        (source_url, status, errors_json),
    )

    return cursor.lastrowid


def write_parsed_data(
    parsed_data: List[Dict],
    source_url: str,
    validation_errors: Optional[List[str]] = None,
) -> bool:
    """
    Write all parsed data to database

    Args:
        parsed_data: List of location dictionaries from parser
        source_url: URL that was fetched
        validation_errors: Optional list of validation errors

    Returns:
        True if successful, False otherwise
    """
    conn = get_db_connection()
    conn.cursor()

    try:
        # Start transaction
        conn.execute("BEGIN TRANSACTION")

        # Log fetch
        status = "success" if not validation_errors else "validation_error"
        log_fetch(conn, source_url, status, validation_errors)

        # Check if validation errors indicate parsing failures that should prevent writing
        # Only block writing if there are critical parsing errors (not just warnings)
        critical_parsing_errors = [
            err
            for err in (validation_errors or [])
            if "invalid village format" in err.lower()
            or "parsing failure" in err.lower()
            or "missing required key" in err.lower()
            or "empty village" in err.lower()
            or "empty seniunija" in err.lower()
        ]

        if critical_parsing_errors:
            print(
                f"❌ Found {len(critical_parsing_errors)} critical parsing errors - not writing to database"
            )
            print(f"   Errors: {critical_parsing_errors[:3]}...")  # Show first 3
            conn.commit()
            return False

        # Write each location
        for item in parsed_data:
            write_location_schedule(
                conn,
                item.get("seniunija", ""),
                item.get("village", ""),
                item.get("street", ""),
                item.get("dates", []),
                item.get("kaimai_str", ""),  # Original Kaimai string for hash
                item.get("house_numbers"),
                waste_type="bendros",  # Default for now
            )

        conn.commit()
        print(f"Successfully wrote {len(parsed_data)} locations to database")
        return True

    except Exception as e:
        conn.rollback()
        print(f"Error writing to database: {e}")
        # Log failed fetch
        try:
            log_fetch(conn, source_url, "failed", [str(e)])
            conn.commit()
        except:
            pass
        return False
    finally:
        conn.close()


if __name__ == "__main__":
    # Test db writer
    from fetcher import fetch_xlsx
    from validator import validate_file_and_data

    file_path = fetch_xlsx()
    source_url = "https://www.nemenkom.lt/uploads/failai/atliekos/Buitini%C5%B3%20atliek%C5%B3%20surinkimo%20grafikai/2026%20m-%20sausio-bir%C5%BEelio%20m%C4%97n%20%20Buitini%C5%B3%20atliek%C5%B3%20surinkimo%20grafikas.xlsx"
    is_valid, errors, data = validate_file_and_data(file_path)

    if is_valid:
        success = write_parsed_data(data, source_url)
        print(f"Write successful: {success}")
    else:
        print(f"Validation failed: {errors}")
