"""
Shared DB helper functions used by API, scraper, and calendar services.
"""

import json

from services.common.db import get_db_connection


def get_schedule_group_info(schedule_group_id: str) -> dict | None:
    """
    Get metadata about a schedule group.
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT id, waste_type, kaimai_hash, first_date, last_date, date_count, dates, dates_hash,
               calendar_id, calendar_synced_at, created_at, updated_at
        FROM schedule_groups
        WHERE id = ?
    """,
        (schedule_group_id,),
    )

    row = cursor.fetchone()
    conn.close()

    if not row:
        return None

    dates = json.loads(row[6] or "[]")

    return {
        "id": row[0],
        "waste_type": row[1],
        "kaimai_hash": row[2],  # Single value, not JSON array
        "first_date": row[3],
        "last_date": row[4],
        "date_count": row[5],
        "dates": dates,
        "dates_hash": row[7],
        "calendar_id": row[8],
        "calendar_synced_at": row[9],
        "created_at": row[10],
        "updated_at": row[11],
    }


def get_calendar_status(calendar_id: str | None, calendar_synced_at: str | None) -> dict:
    """
    Determine calendar status based on calendar_id and calendar_synced_at.
    """
    if not calendar_id:
        return {"status": "pending", "calendar_id": None}
    if not calendar_synced_at:
        return {"status": "needs_update", "calendar_id": calendar_id}
    return {"status": "synced", "calendar_id": calendar_id}


def get_calendar_stream_info(calendar_stream_id: str) -> dict | None:
    """
    Get metadata about a calendar stream.
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT id, waste_type, dates_hash, dates, first_date, last_date, date_count,
               calendar_id, calendar_synced_at, pending_clean_started_at,
               pending_clean_until, pending_clean_notice_sent_at, created_at, updated_at
        FROM calendar_streams
        WHERE id = ?
    """,
        (calendar_stream_id,),
    )

    row = cursor.fetchone()
    conn.close()

    if not row:
        return None

    dates = json.loads(row[3] or "[]")

    return {
        "id": row[0],
        "waste_type": row[1],
        "dates_hash": row[2],
        "dates": dates,
        "first_date": row[4],
        "last_date": row[5],
        "date_count": row[6],
        "calendar_id": row[7],
        "calendar_synced_at": row[8],
        "pending_clean_started_at": row[9],
        "pending_clean_until": row[10],
        "pending_clean_notice_sent_at": row[11],
        "created_at": row[12],
        "updated_at": row[13],
    }


def get_calendar_streams_needing_sync() -> list[dict]:
    """
    Get calendar streams that need calendar creation or sync.
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT id, waste_type, dates_hash, calendar_id, calendar_synced_at
        FROM calendar_streams
        WHERE (calendar_id IS NULL OR calendar_synced_at IS NULL)
          AND pending_clean_started_at IS NULL
        ORDER BY updated_at DESC
    """
    )

    results = []
    for row in cursor.fetchall():
        results.append(
            {
                "id": row[0],
                "waste_type": row[1],
                "dates_hash": row[2],
                "calendar_id": row[3],
                "calendar_synced_at": row[4],
            }
        )

    conn.close()
    return results


def get_calendar_streams_pending_cleanup() -> list[dict]:
    """
    Get calendar streams that are pending cleanup (notice + delete).
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT id, waste_type, calendar_id, pending_clean_started_at,
               pending_clean_until, pending_clean_notice_sent_at
        FROM calendar_streams
        WHERE pending_clean_started_at IS NOT NULL
        ORDER BY pending_clean_started_at ASC
    """
    )

    results = []
    for row in cursor.fetchall():
        results.append(
            {
                "id": row[0],
                "waste_type": row[1],
                "calendar_id": row[2],
                "pending_clean_started_at": row[3],
                "pending_clean_until": row[4],
                "pending_clean_notice_sent_at": row[5],
            }
        )

    conn.close()
    return results


def get_calendar_stream_id_for_schedule_group(schedule_group_id: str) -> str | None:
    """
    Get calendar stream id linked to a schedule group.
    """
    conn = get_db_connection()
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
    conn.close()
    return row[0] if row else None


def update_calendar_stream_calendar_id(calendar_stream_id: str, calendar_id: str) -> bool:
    """
    Update calendar_streams.calendar_id for a stream.
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        UPDATE calendar_streams
        SET calendar_id = ?, updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
    """,
        (calendar_id, calendar_stream_id),
    )

    conn.commit()
    rows_affected = cursor.rowcount
    conn.close()
    return rows_affected > 0


def update_calendar_stream_calendar_synced(calendar_stream_id: str) -> bool:
    """
    Mark calendar_stream as synced (calendar_synced_at = CURRENT_TIMESTAMP).
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        UPDATE calendar_streams
        SET calendar_synced_at = CURRENT_TIMESTAMP,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
    """,
        (calendar_stream_id,),
    )

    conn.commit()
    rows_affected = cursor.rowcount
    conn.close()
    return rows_affected > 0
