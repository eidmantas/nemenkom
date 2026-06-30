"""
UX-focused tests for calendar subscription stability.
"""

from datetime import date

from services.api.db import get_location_schedule
from services.scraper.core.db_writer import (
    cleanup_orphan_schedule_group_links,
    find_or_create_calendar_stream,
    find_or_create_schedule_group,
    generate_dates_hash,
    reconcile_calendar_streams,
    repair_duplicate_location_hashes,
    upsert_group_calendar_link,
    write_location_schedule,
)


def test_subscription_calendar_stays_stable_on_date_change(temp_db):
    """
    A user subscribes by address; the calendar link must remain stable
    when dates update, and the calendar should be marked for re-sync.
    """
    conn, _ = temp_db

    kaimai_hash = "k1_test_ux_stable"
    waste_type = "bendros"
    dates1 = [date(2026, 1, 8), date(2026, 1, 22)]
    dates2 = [date(2026, 2, 5), date(2026, 2, 19)]

    # Create schedule group + stream and link
    schedule_group_id = find_or_create_schedule_group(conn, dates1, waste_type, kaimai_hash)
    calendar_stream_id = find_or_create_calendar_stream(conn, dates1, waste_type)
    upsert_group_calendar_link(conn, schedule_group_id, calendar_stream_id)

    # Create location
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO locations (seniunija, village, street, house_numbers, kaimai_hash)
        VALUES (?, ?, ?, ?, ?)
    """,
        ("Test", "Village", "Street", "1-10", kaimai_hash),
    )
    location_id = cursor.lastrowid

    # Set calendar_id and mark synced
    cursor.execute(
        """
        UPDATE calendar_streams
        SET calendar_id = 'ux_calendar@google.com',
            calendar_synced_at = CURRENT_TIMESTAMP
        WHERE id = ?
    """,
        (calendar_stream_id,),
    )
    conn.commit()

    # User sees subscription link
    schedule = get_location_schedule(location_id=location_id, waste_type=waste_type)
    assert schedule["calendar_id"] == "ux_calendar@google.com"
    assert schedule["calendar_status"]["status"] == "synced"

    # Dates change for this address group
    schedule_group_id = find_or_create_schedule_group(conn, dates2, waste_type, kaimai_hash)
    reconcile_calendar_streams(conn)
    conn.commit()

    # Calendar link remains stable, but needs update
    schedule = get_location_schedule(location_id=location_id, waste_type=waste_type)
    assert schedule["calendar_id"] == "ux_calendar@google.com"
    assert schedule["calendar_status"]["status"] == "needs_update"


def test_calendar_stream_updates_in_place_for_new_xlsx_window(temp_db):
    """
    When a new XLSX drops old months and provides new ones for the same locations,
    we should update the existing calendar stream in place (stable calendar link).
    """
    conn, _ = temp_db

    kaimai_hash = "k1_test_ux_window"
    waste_type = "bendros"
    dates_current = [date(2026, 1, 8), date(2026, 1, 22), date(2026, 2, 5)]
    dates_next = [date(2026, 3, 5), date(2026, 3, 19), date(2026, 4, 2)]

    schedule_group_id = find_or_create_schedule_group(conn, dates_current, waste_type, kaimai_hash)
    calendar_stream_id = find_or_create_calendar_stream(conn, dates_current, waste_type)
    upsert_group_calendar_link(conn, schedule_group_id, calendar_stream_id)

    cursor = conn.cursor()
    cursor.execute(
        """
        UPDATE calendar_streams
        SET calendar_id = 'ux_window_calendar@google.com',
            calendar_synced_at = CURRENT_TIMESTAMP
        WHERE id = ?
    """,
        (calendar_stream_id,),
    )
    conn.commit()

    # New XLSX window replaces old months with new ones.
    schedule_group_id = find_or_create_schedule_group(conn, dates_next, waste_type, kaimai_hash)
    reconcile_calendar_streams(conn)
    conn.commit()

    cursor.execute(
        "SELECT calendar_stream_id FROM group_calendar_links WHERE schedule_group_id = ?",
        (schedule_group_id,),
    )
    row = cursor.fetchone()
    assert row is not None
    assert row[0] == calendar_stream_id, "Calendar stream should remain stable"

    cursor.execute(
        "SELECT dates_hash, dates, calendar_id, calendar_synced_at FROM calendar_streams WHERE id = ?",
        (calendar_stream_id,),
    )
    stream_row = cursor.fetchone()
    assert stream_row is not None
    assert stream_row[0] == generate_dates_hash(dates_next)
    assert stream_row[1] is not None and "2026-03-05" in stream_row[1]
    assert stream_row[2] == "ux_window_calendar@google.com"
    assert stream_row[3] is None, "Stream should be marked for re-sync"


def test_same_address_null_house_numbers_reuses_existing_hash(temp_db):
    """
    SQLite allows duplicate NULL values in UNIQUE constraints. The writer should still
    treat a repeated address with NULL house_numbers as one location and keep its hash stable.
    """
    conn, _ = temp_db

    dates_old = [date(2026, 1, 14), date(2026, 6, 17)]
    dates_new = [date(2026, 7, 1), date(2026, 12, 30)]

    location_id = write_location_schedule(
        conn,
        "Avižienių",
        "Avižieniai",
        "Riešutų g.",
        dates_old,
        "Avižieniai (Riešutų g.)",
        None,
        "bendros",
    )
    conn.commit()
    old_hash = conn.execute(
        "SELECT kaimai_hash FROM locations WHERE id = ?",
        (location_id,),
    ).fetchone()[0]

    write_location_schedule(
        conn,
        "Avižienių",
        "Avižieniai",
        "Riešutų g.",
        dates_new,
        "Avižieniai (Durpių g., Riešutų g.)",
        None,
        "bendros",
    )
    reconcile_calendar_streams(conn)
    conn.commit()

    rows = conn.execute(
        """
        SELECT id, kaimai_hash
        FROM locations
        WHERE seniunija = ? AND village = ? AND street = ? AND house_numbers IS NULL
        """,
        ("Avižienių", "Avižieniai", "Riešutų g."),
    ).fetchall()
    assert rows == [(location_id, old_hash)]

    schedule = get_location_schedule(location_id=location_id, waste_type="bendros")
    assert [d["date"] for d in schedule["dates"]] == ["2026-07-01", "2026-12-30"]


def test_repair_duplicate_address_hashes_keeps_subscribed_hash_with_fresh_dates(temp_db):
    """
    Existing prod data may already have the same address pointing at an old subscribed
    hash and a new fresh-date hash. Repair should merge them without losing the calendar.
    """
    conn, _ = temp_db

    old_hash = "k1_old_riesutu"
    new_hash = "k1_new_riesutu"
    dates_old = [date(2026, 1, 14), date(2026, 6, 17)]
    dates_new = [date(2026, 7, 1), date(2026, 12, 30)]

    old_group = find_or_create_schedule_group(conn, dates_old, "bendros", old_hash)
    old_stream = find_or_create_calendar_stream(conn, dates_old, "bendros")
    upsert_group_calendar_link(conn, old_group, old_stream)
    find_or_create_schedule_group(conn, dates_new, "bendros", new_hash)

    conn.execute(
        """
        UPDATE calendar_streams
        SET calendar_id = 'riesutu@google.com',
            calendar_synced_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (old_stream,),
    )
    conn.executemany(
        """
        INSERT INTO locations (seniunija, village, street, house_numbers, kaimai_hash)
        VALUES (?, ?, ?, ?, ?)
        """,
        [
            ("Avižienių", "Avižieniai", "Riešutų g.", None, old_hash),
            ("Avižienių", "Avižieniai", "Riešutų g.", None, new_hash),
        ],
    )
    conn.commit()

    assert repair_duplicate_location_hashes(conn, waste_type="bendros") == 1
    cleanup_orphan_schedule_group_links(conn, waste_type="bendros")
    reconcile_calendar_streams(conn)
    conn.commit()

    hashes = {
        row[0]
        for row in conn.execute(
            """
            SELECT kaimai_hash
            FROM locations
            WHERE seniunija = ? AND village = ? AND street = ? AND house_numbers IS NULL
            """,
            ("Avižienių", "Avižieniai", "Riešutų g."),
        ).fetchall()
    }
    assert hashes == {old_hash}

    schedule = get_location_schedule(
        seniunija="Avižienių",
        village="Avižieniai",
        street="Riešutų g.",
        waste_type="bendros",
    )
    assert schedule["calendar_id"] == "riesutu@google.com"
    assert [d["date"] for d in schedule["dates"]] == ["2026-07-01", "2026-12-30"]
    assert schedule["calendar_status"]["status"] == "needs_update"


def test_split_keeps_existing_calendar_on_dominant_successor(temp_db):
    """
    If a shared stream splits into multiple date patterns, keep the existing calendar on the
    successor used by the most current selections instead of abandoning it immediately.
    """
    conn, _ = temp_db

    waste_type = "bendros"
    dates_initial = [date(2026, 1, 8), date(2026, 1, 22)]
    dates_group_a = [date(2026, 2, 5), date(2026, 2, 19)]
    dates_group_b = [date(2026, 3, 5), date(2026, 3, 19)]
    kaimai_hash_a = "k1_split_keep_a"
    kaimai_hash_b = "k1_split_keep_b"

    schedule_group_a = find_or_create_schedule_group(conn, dates_initial, waste_type, kaimai_hash_a)
    schedule_group_b = find_or_create_schedule_group(conn, dates_initial, waste_type, kaimai_hash_b)
    calendar_stream_id = find_or_create_calendar_stream(conn, dates_initial, waste_type)
    upsert_group_calendar_link(conn, schedule_group_a, calendar_stream_id)
    upsert_group_calendar_link(conn, schedule_group_b, calendar_stream_id)

    cursor = conn.cursor()
    cursor.executemany(
        """
        INSERT INTO locations (seniunija, village, street, house_numbers, kaimai_hash)
        VALUES (?, ?, ?, ?, ?)
        """,
        [
            ("Test", "VillageA", "Street 1", None, kaimai_hash_a),
            ("Test", "VillageA", "Street 2", None, kaimai_hash_a),
            ("Test", "VillageA", "Street 3", None, kaimai_hash_a),
            ("Test", "VillageB", "Street 9", None, kaimai_hash_b),
        ],
    )
    conn.commit()

    cursor.execute(
        """
        UPDATE calendar_streams
        SET calendar_id = 'split_keep@google.com',
            calendar_synced_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (calendar_stream_id,),
    )
    conn.commit()

    # The dominant successor is group A because more locations currently point at it.
    find_or_create_schedule_group(conn, dates_group_a, waste_type, kaimai_hash_a)
    find_or_create_schedule_group(conn, dates_group_b, waste_type, kaimai_hash_b)
    reconcile_calendar_streams(conn)
    conn.commit()

    cursor.execute(
        "SELECT calendar_stream_id FROM group_calendar_links WHERE schedule_group_id = ?",
        (schedule_group_a,),
    )
    group_a_stream = cursor.fetchone()[0]
    cursor.execute(
        "SELECT calendar_stream_id FROM group_calendar_links WHERE schedule_group_id = ?",
        (schedule_group_b,),
    )
    group_b_stream = cursor.fetchone()[0]

    assert group_a_stream == calendar_stream_id
    assert group_b_stream != calendar_stream_id

    cursor.execute(
        """
        SELECT calendar_id, calendar_synced_at, dates
        FROM calendar_streams
        WHERE id = ?
        """,
        (calendar_stream_id,),
    )
    stream_row = cursor.fetchone()
    assert stream_row[0] == "split_keep@google.com"
    assert stream_row[1] is None
    assert "2026-02-05" in stream_row[2]
