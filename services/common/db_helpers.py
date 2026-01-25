"""
Shared DB helper functions used by API, scraper, and calendar services.
"""

import json
from typing import Dict, List, Optional

from services.common.db import get_db_connection


def get_schedule_group_info(schedule_group_id: str) -> Optional[Dict]:
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


def get_calendar_status(calendar_id: Optional[str], calendar_synced_at: Optional[str]) -> Dict:
    """
    Determine calendar status based on calendar_id and calendar_synced_at.
    """
    if not calendar_id:
        return {"status": "pending", "calendar_id": None}
    if not calendar_synced_at:
        return {"status": "needs_update", "calendar_id": calendar_id}
    return {"status": "synced", "calendar_id": calendar_id}


def get_schedule_groups_needing_sync() -> List[Dict]:
    """
    Get schedule groups that need calendar creation or sync.
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT id, waste_type, kaimai_hash, calendar_id, calendar_synced_at
        FROM schedule_groups
        WHERE calendar_id IS NULL OR calendar_synced_at IS NULL
        ORDER BY updated_at DESC
    """
    )

    results = []
    for row in cursor.fetchall():
        results.append(
            {
                "id": row[0],
                "waste_type": row[1],
                "kaimai_hash": row[2],
                "calendar_id": row[3],
                "calendar_synced_at": row[4],
            }
        )

    conn.close()
    return results


def update_schedule_group_calendar_id(schedule_group_id: str, calendar_id: str) -> bool:
    """
    Update schedule_groups.calendar_id for a schedule group.
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        UPDATE schedule_groups
        SET calendar_id = ?, updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
    """,
        (calendar_id, schedule_group_id),
    )

    conn.commit()
    rows_affected = cursor.rowcount
    conn.close()
    return rows_affected > 0


def update_schedule_group_calendar_synced(schedule_group_id: str) -> bool:
    """
    Mark schedule_group as synced (calendar_synced_at = CURRENT_TIMESTAMP).
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        UPDATE schedule_groups
        SET calendar_synced_at = CURRENT_TIMESTAMP,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
    """,
        (schedule_group_id,),
    )

    conn.commit()
    rows_affected = cursor.rowcount
    conn.close()
    return rows_affected > 0
