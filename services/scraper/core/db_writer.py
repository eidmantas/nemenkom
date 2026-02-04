"""
Database writer module - Writes validated data to SQLite
"""

import hashlib
import json
import sqlite3
import uuid
from datetime import date, datetime

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


def generate_dates_hash(dates: list[date]) -> str:
    """
    Generate hash of sorted dates for change detection

    Used to detect when schedule dates have changed and calendar needs re-sync
    """
    if not dates:
        return ""
    date_str = ",".join(sorted(d.isoformat() for d in dates))
    hash_obj = hashlib.sha256(date_str.encode())
    return hash_obj.hexdigest()[:16]


def normalize_dates(dates: list[date | str] | None) -> list[date]:
    """
    Normalize date inputs to date objects (accepts ISO date strings).
    """
    normalized = []
    for value in dates or []:
        if isinstance(value, date):
            normalized.append(value)
        else:
            normalized.append(datetime.fromisoformat(str(value)).date())
    return normalized


def generate_calendar_stream_id() -> str:
    """
    Generate a stable calendar stream ID (random, stored in DB).
    """
    return f"cs_{uuid.uuid4().hex[:12]}"


def find_or_create_calendar_stream(
    conn: sqlite3.Connection, dates: list, waste_type: str, exclude_stream_id: str | None = None
) -> str | None:
    """
    Find or create calendar stream for a date pattern + waste_type.

    Returns:
        calendar_stream_id or None if no dates provided.
    """
    dates = normalize_dates(dates)
    if not dates:
        return None

    dates_hash = generate_dates_hash(dates)
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT id FROM calendar_streams
        WHERE waste_type = ?
          AND dates_hash = ?
          AND pending_clean_started_at IS NULL
          AND (? IS NULL OR id != ?)
        ORDER BY created_at ASC
        LIMIT 1
    """,
        (waste_type, dates_hash, exclude_stream_id, exclude_stream_id),
    )
    row = cursor.fetchone()
    if row:
        return row[0]

    calendar_stream_id = generate_calendar_stream_id()
    first_date = min(dates).isoformat()
    last_date = max(dates).isoformat()
    date_count = len(dates)
    dates_json = json.dumps(
        [d.isoformat() if isinstance(d, date) else str(d) for d in sorted(dates)]
    )

    cursor.execute(
        """
        INSERT INTO calendar_streams (
            id, waste_type, dates_hash, dates, first_date, last_date, date_count, calendar_synced_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, NULL)
    """,
        (
            calendar_stream_id,
            waste_type,
            dates_hash,
            dates_json,
            first_date,
            last_date,
            date_count,
        ),
    )

    return calendar_stream_id


def upsert_group_calendar_link(
    conn: sqlite3.Connection, schedule_group_id: str, calendar_stream_id: str | None
) -> None:
    """
    Ensure schedule_group_id is linked to the correct calendar stream.
    """
    cursor = conn.cursor()
    cursor.execute(
        "DELETE FROM group_calendar_links WHERE schedule_group_id = ?",
        (schedule_group_id,),
    )

    if calendar_stream_id:
        cursor.execute(
            """
            INSERT INTO group_calendar_links (schedule_group_id, calendar_stream_id, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
        """,
            (schedule_group_id, calendar_stream_id),
        )


def get_calendar_stream_id_for_schedule_group(
    conn: sqlite3.Connection, schedule_group_id: str
) -> str | None:
    """
    Fetch existing calendar stream link for a schedule group.
    """
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT calendar_stream_id
        FROM group_calendar_links
        WHERE schedule_group_id = ?
        LIMIT 1
    """,
        (schedule_group_id,),
    )
    row = cursor.fetchone()
    return row[0] if row else None


def reconcile_calendar_streams(conn: sqlite3.Connection) -> None:
    """
    Reconcile calendar streams after all schedule groups are updated.
    - If all linked groups share the same dates_hash, update the stream in place.
    - If linked groups diverge, split into new streams and mark the old stream pending clean.
    - If a stream has no linked groups, mark pending clean.
    """
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT gcl.calendar_stream_id, sg.dates_hash, sg.dates, sg.waste_type
        FROM group_calendar_links gcl
        JOIN schedule_groups sg ON sg.id = gcl.schedule_group_id
    """
    )

    stream_map: dict[str, dict[str, dict[str, str]]] = {}
    for stream_id, dates_hash, dates_json, waste_type in cursor.fetchall():
        stream_map.setdefault(stream_id, {})
        stream_map[stream_id][dates_hash] = {
            "dates_json": dates_json,
            "waste_type": waste_type,
        }

    for stream_id, hashes in stream_map.items():
        if len(hashes) == 1:
            dates_hash, payload = next(iter(hashes.items()))
            dates_list = json.loads(payload["dates_json"] or "[]")
            if dates_list:
                first_date = min(dates_list)
                last_date = max(dates_list)
                date_count = len(dates_list)
            else:
                first_date = None
                last_date = None
                date_count = 0

            cursor.execute(
                """
                UPDATE calendar_streams
                SET dates_hash = ?, dates = ?, first_date = ?, last_date = ?, date_count = ?,
                    calendar_synced_at = CASE WHEN dates_hash != ? THEN NULL ELSE calendar_synced_at END,
                    updated_at = CURRENT_TIMESTAMP,
                    pending_clean_started_at = NULL,
                    pending_clean_until = NULL,
                    pending_clean_notice_sent_at = NULL
                WHERE id = ?
            """,
                (
                    dates_hash,
                    payload["dates_json"],
                    first_date,
                    last_date,
                    date_count,
                    dates_hash,
                    stream_id,
                ),
            )
        else:
            # Split: move all groups to new streams (one per hash)
            for dates_hash, payload in hashes.items():
                dates_list = json.loads(payload["dates_json"] or "[]")
                new_stream_id = find_or_create_calendar_stream(
                    conn,
                    dates_list,
                    payload["waste_type"],
                    exclude_stream_id=stream_id,
                )
                cursor.execute(
                    """
                    UPDATE group_calendar_links
                    SET calendar_stream_id = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE schedule_group_id IN (
                        SELECT id FROM schedule_groups
                        WHERE dates_hash = ? AND waste_type = ?
                    )
                """,
                    (new_stream_id, dates_hash, payload["waste_type"]),
                )

            # Mark old stream pending clean
            cursor.execute(
                """
                UPDATE calendar_streams
                SET pending_clean_started_at = CURRENT_TIMESTAMP,
                    pending_clean_until = DATETIME(CURRENT_TIMESTAMP, '+4 days'),
                    pending_clean_notice_sent_at = NULL
                WHERE id = ?
            """,
                (stream_id,),
            )

    # Mark orphaned streams pending clean
    cursor.execute(
        """
        UPDATE calendar_streams
        SET pending_clean_started_at = CURRENT_TIMESTAMP,
            pending_clean_until = DATETIME(CURRENT_TIMESTAMP, '+4 days'),
            pending_clean_notice_sent_at = NULL
        WHERE id NOT IN (SELECT DISTINCT calendar_stream_id FROM group_calendar_links)
          AND pending_clean_started_at IS NULL
    """
    )


def find_or_create_schedule_group(
    conn: sqlite3.Connection, dates: list, waste_type: str, kaimai_hash: str
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
    dates = normalize_dates(dates)
    # Generate STABLE ID (based on kaimai_hash + waste_type, NOT dates!)
    schedule_group_id = generate_schedule_group_id(kaimai_hash, waste_type)
    new_dates_hash = generate_dates_hash(dates)
    cursor = conn.cursor()

    # Check if schedule group exists (by stable ID)
    cursor.execute("SELECT dates_hash FROM schedule_groups WHERE id = ?", (schedule_group_id,))
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
                [d.isoformat() if isinstance(d, date) else str(d) for d in sorted(dates)]
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
    dates: list,
    kaimai_str: str,
    house_numbers: str | None = None,
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
    schedule_group_id = find_or_create_schedule_group(conn, dates, waste_type, kaimai_hash)
    existing_stream_id = get_calendar_stream_id_for_schedule_group(conn, schedule_group_id)
    if not existing_stream_id:
        calendar_stream_id = find_or_create_calendar_stream(conn, dates, waste_type)
        upsert_group_calendar_link(conn, schedule_group_id, calendar_stream_id)

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
        row = cursor.fetchone()
        if row is None:
            raise ValueError("Location insert/update failed to return an id")
        location_id = row[0]

    if location_id is None:
        raise ValueError("Location insert/update failed to return an id")

    return location_id


def log_fetch(
    conn: sqlite3.Connection,
    source_url: str,
    status: str,
    validation_errors: list[str] | None = None,
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

    fetch_id = cursor.lastrowid
    if fetch_id is None:
        raise ValueError("Fetch insert failed to return an id")
    return fetch_id


def write_parsed_data(
    parsed_data: list[dict],
    source_url: str,
    validation_errors: list[str] | None = None,
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
                f" Found {len(critical_parsing_errors)} critical parsing errors - not writing to database"
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

        # Reconcile calendar streams after all groups are updated
        reconcile_calendar_streams(conn)

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
        except Exception:
            pass
        return False
    finally:
        conn.close()


if __name__ == "__main__":
    # Test db writer
    from services.scraper.core.fetcher import fetch_xlsx
    from services.scraper.core.validator import validate_file_and_data

    file_path, _headers, _byte_len = fetch_xlsx()
    source_url = "https://www.nemenkom.lt/uploads/failai/atliekos/Buitini%C5%B3%20atliek%C5%B3%20surinkimo%20grafikai/2026%20m-%20sausio-bir%C5%BEelio%20m%C4%97n%20%20Buitini%C5%B3%20atliek%C5%B3%20surinkimo%20grafikas.xlsx"
    is_valid, errors, data = validate_file_and_data(file_path)

    if is_valid:
        success = write_parsed_data(data, source_url)
        print(f"Write successful: {success}")
    else:
        print(f"Validation failed: {errors}")
