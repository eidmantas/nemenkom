"""
Database query functions for API
Updated for new schema: hash-based schedule_groups, dates in JSON, no pickup_dates table
"""

import json
import sqlite3

from services.common.db import get_db_connection
from services.common.db_helpers import (
    get_calendar_status,
    get_schedule_group_info,
)


def get_all_locations() -> list[dict]:
    """
    Get all locations (street/village combos)

    Returns:
        List of dictionaries with id, village, street, kaimai_hash
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, seniunija, village, street, house_numbers, kaimai_hash
        FROM locations
        ORDER BY seniunija, village, street
    """)

    results = []
    for row in cursor.fetchall():
        results.append(
            {
                "id": row[0],
                "seniunija": row[1],
                "village": row[2],
                "street": row[3],
                "house_numbers": row[4],
                "kaimai_hash": row[5],
            }
        )

    conn.close()
    return results


def get_location_schedule(
    location_id: int | None = None,
    seniunija: str | None = None,
    village: str | None = None,
    street: str | None = None,
    waste_type: str = "bendros",
) -> dict | None:
    """
    Get schedule for a specific location

    Args:
        location_id: Location ID (preferred)
        seniunija: Seniūnija name (required if using village/street)
        village: Village name
        street: Street name
        waste_type: Waste type ('bendros', 'plastikas', etc.)

    Returns:
        Dictionary with location info and dates, or None if not found
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    # Build query based on provided parameters
    if location_id:
        cursor.execute(
            """
            SELECT id, seniunija, village, street, house_numbers, kaimai_hash
            FROM locations
            WHERE id = ?
        """,
            (location_id,),
        )
    elif seniunija and village and street is not None:
        cursor.execute(
            """
            SELECT id, seniunija, village, street, house_numbers, kaimai_hash
            FROM locations
            WHERE seniunija = ? AND village = ? AND street = ?
        """,
            (seniunija, village, street),
        )
    else:
        conn.close()
        return None

    location_row = cursor.fetchone()
    if not location_row:
        conn.close()
        return None

    location_id = location_row[0]
    kaimai_hash = location_row[5]

    # Get dates from schedule_groups and calendar info via calendar streams
    cursor.execute(
        """
        SELECT sg.id, sg.dates, cs.calendar_id, cs.calendar_synced_at
        FROM schedule_groups sg
        LEFT JOIN group_calendar_links gcl ON gcl.schedule_group_id = sg.id
        LEFT JOIN calendar_streams cs ON cs.id = gcl.calendar_stream_id
        WHERE sg.kaimai_hash = ?
          AND sg.waste_type = ?
        LIMIT 1
    """,
        (kaimai_hash, waste_type),
    )

    schedule_row = cursor.fetchone()
    dates = []
    schedule_group_id = None
    calendar_id = None
    calendar_synced_at = None

    if schedule_row:
        schedule_group_id = schedule_row[0]
        dates_json = schedule_row[1]
        calendar_id = schedule_row[2]
        calendar_synced_at = schedule_row[3]
        if dates_json:
            date_list = json.loads(dates_json)
            dates = [{"date": d, "waste_type": waste_type} for d in date_list]

    conn.close()

    result = {
        "id": location_row[0],
        "seniunija": location_row[1],
        "village": location_row[2],
        "street": location_row[3],
        "house_numbers": location_row[4],
        "kaimai_hash": location_row[5],
        "schedule_group_id": schedule_group_id,
        "waste_type": waste_type,
        "dates": dates,
    }

    # Add calendar_id and subscription_link if calendar exists
    if calendar_id:
        result["calendar_id"] = calendar_id
        result["subscription_link"] = (
            f"https://calendar.google.com/calendar/render?cid={calendar_id}"
        )

    # Add calendar_status
    result["calendar_status"] = get_calendar_status(calendar_id, calendar_synced_at)

    return result


def get_schedule_group_schedule(schedule_group_id: str, waste_type: str = "bendros") -> dict:
    """
    Get schedule for a schedule group (all locations with same schedule)

    Args:
        schedule_group_id: Schedule group ID (hash-based string)
        waste_type: Waste type to filter by

    Returns:
        Dictionary with schedule group info, locations, and dates
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    # Get schedule group metadata
    group_info = get_schedule_group_info(schedule_group_id)
    if not group_info:
        conn.close()
        return {
            "schedule_group_id": schedule_group_id,
            "error": "Schedule group not found",
            "locations": [],
            "dates": [],
        }

    # Filter by waste_type if provided
    if group_info["waste_type"] != waste_type:
        conn.close()
        return {
            "schedule_group_id": schedule_group_id,
            "error": f'Schedule group is for waste_type "{group_info["waste_type"]}", not "{waste_type}"',
            "locations": [],
            "dates": [],
        }

    # Get all locations in this group (by matching kaimai_hash directly)
    kaimai_hash = group_info["kaimai_hash"]
    if not kaimai_hash:
        conn.close()
        return {
            "schedule_group_id": schedule_group_id,
            "metadata": group_info,
            "location_count": 0,
            "locations": [],
            "dates": group_info["dates"],
        }

    # Direct lookup by kaimai_hash (single value, not JSON array)
    cursor.execute(
        """
        SELECT id, seniunija, village, street, house_numbers
        FROM locations
        WHERE kaimai_hash = ?
        ORDER BY seniunija, village, street
    """,
        (kaimai_hash,),
    )

    locations = []
    for row in cursor.fetchall():
        locations.append(
            {
                "id": row[0],
                "seniunija": row[1],
                "village": row[2],
                "street": row[3],
                "house_numbers": row[4],
            }
        )

    # Dates are already in group_info
    dates = [{"date": d, "waste_type": waste_type} for d in group_info["dates"]]

    # Calendar info comes from calendar_streams
    cursor.execute(
        """
        SELECT cs.calendar_id, cs.calendar_synced_at
        FROM group_calendar_links gcl
        JOIN calendar_streams cs ON cs.id = gcl.calendar_stream_id
        WHERE gcl.schedule_group_id = ?
        LIMIT 1
    """,
        (schedule_group_id,),
    )
    calendar_row = cursor.fetchone()
    calendar_id = calendar_row[0] if calendar_row else None

    conn.close()

    return {
        "schedule_group_id": schedule_group_id,
        "metadata": {
            "waste_type": group_info["waste_type"],
            "first_date": group_info["first_date"],
            "last_date": group_info["last_date"],
            "date_count": group_info["date_count"],
            "calendar_id": calendar_id,
        },
        "location_count": len(locations),
        "locations": locations,
        "dates": dates,
    }


def search_locations(query: str) -> list[dict]:
    """
    Search locations by village or street name

    Args:
        query: Search query

    Returns:
        List of matching locations
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    search_term = f"%{query}%"
    cursor.execute(
        """
        SELECT id, seniunija, village, street, house_numbers, kaimai_hash
        FROM locations
        WHERE seniunija LIKE ? OR village LIKE ? OR street LIKE ?
        ORDER BY seniunija, village, street
        LIMIT 50
    """,
        (search_term, search_term, search_term),
    )

    results = []
    for row in cursor.fetchall():
        results.append(
            {
                "id": row[0],
                "seniunija": row[1],
                "village": row[2],
                "street": row[3],
                "house_numbers": row[4],
                "kaimai_hash": row[5],
            }
        )

    conn.close()
    return results


def get_unique_villages() -> list[dict]:
    """Get list of unique villages with seniunija and village as separate keys"""
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT DISTINCT seniunija, village
        FROM locations
        WHERE village != ''
        ORDER BY seniunija, village
    """)

    results = [{"seniunija": row[0], "village": row[1]} for row in cursor.fetchall()]

    # Enrich villages with aggregated waste-type availability so the UI can render chips already at
    # the "Kaimas/Miestas" level.
    #
    # Semantics:
    # - scope "all": applies to whole village (no street needed)
    # - scope "some": exists in this village but only for some streets / buckets
    # - scope "none": not present
    bendros_scope: dict[tuple[str, str], str] = {}
    try:
        rows = cursor.execute(
            """
            SELECT
              l.seniunija,
              l.village,
              MAX(CASE WHEN COALESCE(l.street, '') = '' THEN 1 ELSE 0 END) as has_villagewide
            FROM locations l
            JOIN schedule_groups sg
              ON sg.kaimai_hash = l.kaimai_hash
             AND sg.waste_type = 'bendros'
            WHERE l.village != ''
            GROUP BY l.seniunija, l.village
            """
        ).fetchall()
        for s, v, has_villagewide in rows:
            bendros_scope[(s, v)] = "all" if (has_villagewide or 0) == 1 else "some"
    except sqlite3.OperationalError:
        # Minimal DBs might not include schedule_groups yet.
        pass

    pdf_scope: dict[tuple[str, str, str], str] = {}
    try:
        rows = cursor.execute(
            """
            SELECT
              COALESCE(mapped_seniunija, seniunija) as s,
              COALESCE(mapped_village, village) as v,
              waste_type,
              MAX(
                CASE
                  WHEN COALESCE(COALESCE(mapped_street, street), '') = '' THEN 1
                  ELSE 0
                END
              ) as has_villagewide
            FROM pdf_parsed_rows
            WHERE waste_type IN ('plastikas', 'stiklas')
              AND COALESCE(mapped_village, village) != ''
            GROUP BY s, v, waste_type
            """
        ).fetchall()
        for s, v, wt, has_villagewide in rows:
            pdf_scope[(s, v, wt)] = "all" if (has_villagewide or 0) == 1 else "some"
    except sqlite3.OperationalError as e:
        # Test DBs / minimal deployments may not include PDF tables.
        if "no such table: pdf_parsed_rows" not in str(e):
            raise

    for entry in results:
        key = (entry["seniunija"], entry["village"])
        scopes = {
            "bendros": bendros_scope.get(key, "none"),
            "plastikas": pdf_scope.get((key[0], key[1], "plastikas"), "none"),
            "stiklas": pdf_scope.get((key[0], key[1], "stiklas"), "none"),
        }
        entry["waste_type_scopes"] = scopes
        entry["available_waste_types"] = sorted(
            [wt for wt, scope in scopes.items() if scope != "none"]
        )

    conn.close()
    return results


def get_streets_for_village(seniunija: str, village: str) -> list[str]:
    """Get list of unique streets for a village in a specific seniunija (includes empty string for whole village)"""
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT DISTINCT street
        FROM locations
        WHERE seniunija = ? AND village = ?
        ORDER BY CASE WHEN street = '' THEN 0 ELSE 1 END, street
    """,
        (seniunija, village),
    )

    results = [row[0] for row in cursor.fetchall()]
    conn.close()
    return results


def get_house_numbers_for_street(seniunija: str, village: str, street: str) -> list[str]:
    """Get list of unique house numbers for a street in a specific seniunija/village (street can be empty string for whole village)"""
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT DISTINCT house_numbers
        FROM locations
        WHERE seniunija = ? AND village = ? AND street = ?
        ORDER BY house_numbers
    """,
        (seniunija, village, street),
    )

    # Filter out None values, but keep empty strings if they exist
    results = [row[0] for row in cursor.fetchall() if row[0] is not None]
    conn.close()
    return results


def village_has_streets(seniunija: str, village: str) -> bool:
    """Check if a village in a specific seniunija has any non-empty streets"""
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT COUNT(*)
        FROM locations
        WHERE seniunija = ? AND village = ? AND street != '' AND street IS NOT NULL
        LIMIT 1
    """,
        (seniunija, village),
    )

    count = cursor.fetchone()[0]
    conn.close()
    return count > 0


def street_has_house_numbers(seniunija: str, village: str, street: str) -> bool:
    """Check if a street in a specific seniunija/village has any house numbers"""
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT COUNT(*)
        FROM locations
        WHERE seniunija = ? AND village = ? AND street = ? AND house_numbers IS NOT NULL AND house_numbers != ''
        LIMIT 1
    """,
        (seniunija, village, street),
    )

    count = cursor.fetchone()[0]
    conn.close()
    return count > 0


def get_location_by_selection(
    seniunija: str, village: str, street: str, house_numbers: str | None = None
) -> dict | None:
    """Get location by seniunija, village, street, and optionally house_numbers"""
    conn = get_db_connection()
    cursor = conn.cursor()

    if house_numbers:
        cursor.execute(
            """
            SELECT id, seniunija, village, street, house_numbers, kaimai_hash
            FROM locations
            WHERE seniunija = ? AND village = ? AND street = ? AND house_numbers = ?
            LIMIT 1
        """,
            (seniunija, village, street, house_numbers),
        )
    else:
        # If no house_numbers specified, get first match (or one with NULL house_numbers)
        cursor.execute(
            """
            SELECT id, seniunija, village, street, house_numbers, kaimai_hash
            FROM locations
            WHERE seniunija = ? AND village = ? AND street = ?
            ORDER BY CASE WHEN house_numbers IS NULL THEN 0 ELSE 1 END
            LIMIT 1
        """,
            (seniunija, village, street),
        )

    row = cursor.fetchone()
    conn.close()

    if not row:
        return None

    return {
        "id": row[0],
        "seniunija": row[1],
        "village": row[2],
        "street": row[3],
        "house_numbers": row[4],
        "kaimai_hash": row[5],
    }


def get_available_waste_types_for_selection(
    *,
    seniunija: str,
    village: str,
    street: str,
    house_numbers: str | None,
) -> dict:
    """
    Returns waste-type availability for a specific selection.

    - bendros availability comes from schedule_groups joined via locations.kaimai_hash
    - plastikas/stiklas availability comes from pdf_parsed_rows (mapped fields)

    This is intentionally conservative: it does not try to "contain" user-entered house numbers.
    It only matches exact house-number buckets or the street-level (house_numbers is None).
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    bendros_requires_house_numbers = street_has_house_numbers(seniunija, village, street)
    available: set[str] = set()

    # 1) bendros: if selecting a bucket (house_numbers provided), check that exact bucket exists and has a group.
    #    if selecting street-level, only allow bendros when the street does NOT require house buckets.
    if house_numbers is not None:
        row = cursor.execute(
            """
            SELECT 1
            FROM locations l
            JOIN schedule_groups sg ON sg.kaimai_hash = l.kaimai_hash
            WHERE l.seniunija = ? AND l.village = ? AND l.street = ? AND l.house_numbers = ?
              AND sg.waste_type = 'bendros'
            LIMIT 1
            """,
            (seniunija, village, street, house_numbers),
        ).fetchone()
        if row:
            available.add("bendros")
    else:
        if not bendros_requires_house_numbers:
            row = cursor.execute(
                """
                SELECT 1
                FROM locations l
                JOIN schedule_groups sg ON sg.kaimai_hash = l.kaimai_hash
                WHERE l.seniunija = ? AND l.village = ? AND l.street = ?
                  AND sg.waste_type = 'bendros'
                LIMIT 1
                """,
                (seniunija, village, street),
            ).fetchone()
            if row:
                available.add("bendros")
        else:
            # Street requires house-number buckets. Still mark bendros as available at street-level
            # so the UI can show a (disabled) chip indicating it exists but needs a bucket.
            row = cursor.execute(
                """
                SELECT 1
                FROM locations l
                JOIN schedule_groups sg ON sg.kaimai_hash = l.kaimai_hash
                WHERE l.seniunija = ? AND l.village = ? AND l.street = ?
                  AND sg.waste_type = 'bendros'
                LIMIT 1
                """,
                (seniunija, village, street),
            ).fetchone()
            if row:
                available.add("bendros")

    # 2) pdf-derived waste types: check presence in pdf_parsed_rows for the same (mapped) address.
    #    Inheritance rules (v1.0):
    #    - Street-level selection also inherits village-wide PDF rows where street is '' (meaning "all streets").
    #    - Bucket-level selection inherits street-wide PDF rows where house_numbers is NULL/''/'all'.
    params = {
        "seniunija": seniunija,
        "village": village,
        "street": street,
    }
    try:
        if house_numbers is None:
            rows = cursor.execute(
                """
                SELECT DISTINCT waste_type
                FROM pdf_parsed_rows
                WHERE COALESCE(mapped_seniunija, seniunija) = :seniunija
                  AND COALESCE(mapped_village, village) = :village
                  AND (
                    COALESCE(mapped_street, street) = :street
                    OR COALESCE(mapped_street, street) = ''
                  )
                  AND waste_type IN ('plastikas', 'stiklas')
                """,
                params,
            ).fetchall()
        else:
            params["house_numbers"] = house_numbers
            rows = cursor.execute(
                """
                SELECT DISTINCT waste_type
                FROM pdf_parsed_rows
                WHERE COALESCE(mapped_seniunija, seniunija) = :seniunija
                  AND COALESCE(mapped_village, village) = :village
                  AND (
                    COALESCE(mapped_street, street) = :street
                    OR COALESCE(mapped_street, street) = ''
                  )
                  AND (
                    COALESCE(house_numbers, '') = :house_numbers
                    OR LOWER(COALESCE(house_numbers, '')) IN ('', 'all')
                  )
                  AND waste_type IN ('plastikas', 'stiklas')
                """,
                params,
            ).fetchall()
        for r in rows:
            available.add(r[0])
    except sqlite3.OperationalError as e:
        # Test DBs / minimal deployments may not include PDF tables.
        if "no such table: pdf_parsed_rows" not in str(e):
            raise

    conn.close()
    return {
        "available_waste_types": sorted(available),
        "bendros_requires_house_numbers": bendros_requires_house_numbers,
    }


def get_pdf_streetwide_waste_types_for_selection(
    *,
    seniunija: str,
    village: str,
    street: str,
) -> set[str]:
    """
    Return waste types that apply street-wide in PDF data (house_numbers is NULL/''/'all').

    This is used to decide whether a synthetic 'Visiems' option is semantically valid when bendros
    is bucket-split: if plastikas/stiklas is street-wide, 'Visiems' still makes sense for those
    waste types even though bendros needs a bucket.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    types: set[str] = set()
    try:
        rows = cursor.execute(
            """
            SELECT DISTINCT waste_type
            FROM pdf_parsed_rows
            WHERE COALESCE(mapped_seniunija, seniunija) = :seniunija
              AND COALESCE(mapped_village, village) = :village
              AND COALESCE(mapped_street, street) = :street
              AND LOWER(COALESCE(house_numbers, '')) IN ('', 'all')
              AND waste_type IN ('plastikas', 'stiklas')
            """,
            {"seniunija": seniunija, "village": village, "street": street},
        ).fetchall()
        for r in rows:
            types.add(r[0])
    except sqlite3.OperationalError as e:
        if "no such table: pdf_parsed_rows" not in str(e):
            raise
    finally:
        conn.close()
    return types


def _get_pdf_kaimai_hash_for_selection(
    *,
    waste_type: str,
    seniunija: str,
    village: str,
    street: str,
    house_numbers: str | None,
    cursor: sqlite3.Cursor,
) -> str | None:
    """
    Find the best matching pdf_parsed_rows.kaimai_hash for a selection.

    Matching rules:
    - Match on mapped_seniunija/village/street when present, else fallback to raw columns.
    - If house_numbers is provided (bendros bucket selection), prefer exact match.
    - Otherwise, prefer street-wide rows where house_numbers is NULL/''/'all'.
    """
    # Street inheritance:
    # - Prefer exact street matches.
    # - Fall back to village-wide rows where street is '' (meaning "all streets").
    base_sql = """
        SELECT
          kaimai_hash,
          COALESCE(house_numbers, '') as hn,
          CASE
            WHEN COALESCE(mapped_street, street) = :street THEN 0
            WHEN COALESCE(mapped_street, street) = '' THEN 1
            ELSE 2
          END as street_rank
        FROM pdf_parsed_rows
        WHERE waste_type = :waste_type
          AND COALESCE(mapped_seniunija, seniunija) = :seniunija
          AND COALESCE(mapped_village, village) = :village
          AND (
            COALESCE(mapped_street, street) = :street
            OR COALESCE(mapped_street, street) = ''
          )
    """
    params = {
        "waste_type": waste_type,
        "seniunija": seniunija,
        "village": village,
        "street": street,
        "bucket": house_numbers or "",
    }

    if house_numbers is not None:
        sql = (
            base_sql
            + """
            ORDER BY
              street_rank ASC,
              CASE
                WHEN COALESCE(house_numbers, '') = :bucket THEN 0
                WHEN LOWER(COALESCE(house_numbers, '')) IN ('', 'all') THEN 1
                ELSE 2
              END,
              id ASC
            LIMIT 1
            """
        )
    else:
        sql = (
            base_sql
            + """
            ORDER BY
              street_rank ASC,
              CASE
                WHEN LOWER(COALESCE(house_numbers, '')) IN ('', 'all') THEN 0
                ELSE 1
              END,
              id ASC
            LIMIT 1
            """
        )

    try:
        row = cursor.execute(sql, params).fetchone()
    except sqlite3.OperationalError as e:
        if "no such table: pdf_parsed_rows" in str(e):
            return None
        raise
    if not row:
        return None
    return row[0]


def _get_schedule_for_kaimai_hash(
    *,
    waste_type: str,
    kaimai_hash: str,
    cursor: sqlite3.Cursor,
) -> dict | None:
    """
    Lightweight schedule lookup by (waste_type, kaimai_hash), including calendar stream status.
    """
    row = cursor.execute(
        """
        SELECT sg.id, sg.dates, cs.calendar_id, cs.calendar_synced_at
        FROM schedule_groups sg
        LEFT JOIN group_calendar_links gcl ON gcl.schedule_group_id = sg.id
        LEFT JOIN calendar_streams cs ON cs.id = gcl.calendar_stream_id
        WHERE sg.kaimai_hash = ?
          AND sg.waste_type = ?
        LIMIT 1
        """,
        (kaimai_hash, waste_type),
    ).fetchone()
    if not row:
        return None

    schedule_group_id = row[0]
    dates_json = row[1]
    calendar_id = row[2]
    calendar_synced_at = row[3]
    date_list = json.loads(dates_json) if dates_json else []
    dates = [{"date": d, "waste_type": waste_type} for d in date_list]

    result = {
        "schedule_group_id": schedule_group_id,
        "waste_type": waste_type,
        "dates": dates,
    }
    if calendar_id:
        result["calendar_id"] = calendar_id
        result["subscription_link"] = (
            f"https://calendar.google.com/calendar/render?cid={calendar_id}"
        )
    result["calendar_status"] = get_calendar_status(calendar_id, calendar_synced_at)
    return result


def get_multi_waste_schedule_for_selection(
    *,
    seniunija: str,
    village: str,
    street: str,
    house_numbers: str | None,
) -> dict:
    """
    Get schedules for all waste types relevant to the selection and return a combined date list.

    Notes:
    - bendros is resolved via locations (canonical dataset).
    - plastikas/stiklas are resolved via pdf_parsed_rows -> kaimai_hash -> schedule_groups.
    - If bendros requires buckets, and house_numbers is None, bendros schedule may be omitted.
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    availability = get_available_waste_types_for_selection(
        seniunija=seniunija, village=village, street=street, house_numbers=house_numbers
    )
    available_waste_types: list[str] = availability.get("available_waste_types") or []
    bendros_requires_house_numbers = bool(availability.get("bendros_requires_house_numbers"))

    schedules: dict[str, dict] = {}

    # bendros schedule (only when resolvable)
    if "bendros" in available_waste_types:
        if (not bendros_requires_house_numbers) or (house_numbers is not None):
            location = get_location_by_selection(seniunija, village, street, house_numbers)
            if location:
                sched = get_location_schedule(location_id=location["id"], waste_type="bendros")
                if sched:
                    schedules["bendros"] = sched

    # plastikas/stiklas schedules via pdf_parsed_rows kaimai_hash mapping
    for wt in ("plastikas", "stiklas"):
        if wt not in available_waste_types:
            continue
        kaimai_hash = _get_pdf_kaimai_hash_for_selection(
            waste_type=wt,
            seniunija=seniunija,
            village=village,
            street=street,
            house_numbers=house_numbers,
            cursor=cursor,
        )
        if not kaimai_hash:
            continue
        sched = _get_schedule_for_kaimai_hash(waste_type=wt, kaimai_hash=kaimai_hash, cursor=cursor)
        if sched:
            schedules[wt] = sched

    # Flatten combined dates
    combined_dates: list[dict[str, str]] = []
    for wt, sched in schedules.items():
        for d in sched.get("dates") or []:
            # d already has waste_type for schedule_group-based schedules; for bendros it does too
            combined_dates.append(
                {"date": str(d["date"]), "waste_type": str(d.get("waste_type", wt))}
            )

    # Sort by date then waste_type for stable UI
    def _combined_date_sort_key(item: dict[str, str]) -> tuple[str, str]:
        return (item["date"], item.get("waste_type", ""))

    combined_dates.sort(key=_combined_date_sort_key)

    conn.close()
    return {
        "selection": {
            "seniunija": seniunija,
            "village": village,
            "street": street,
            "house_numbers": house_numbers,
        },
        "available_waste_types": available_waste_types,
        "bendros_requires_house_numbers": bendros_requires_house_numbers,
        "schedules": schedules,
        "dates": combined_dates,
    }
