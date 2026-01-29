"""
Tests for stable ID generation and date change detection (Option B)
Tests that schedule_group_id remains stable when dates change
"""

import json
from datetime import date

from services.scraper.core.db_writer import (
    find_or_create_schedule_group,
    generate_dates_hash,
    generate_kaimai_hash,
    generate_schedule_group_id,
)


def test_stable_schedule_group_id():
    """Test that schedule_group_id is stable (based on kaimai_hash + waste_type, not dates)"""
    kaimai_hash = "k1_abc123def456"
    waste_type = "bendros"

    # Generate ID with dates
    _dates1 = [date(2026, 1, 8), date(2026, 1, 22)]
    id1 = generate_schedule_group_id(kaimai_hash, waste_type)

    # Generate ID with different dates (same kaimai_hash + waste_type)
    _dates2 = [date(2026, 2, 5), date(2026, 2, 19)]
    id2 = generate_schedule_group_id(kaimai_hash, waste_type)

    # IDs should be the same (stable!)
    assert id1 == id2, "Schedule group ID should be stable regardless of dates"
    assert id1.startswith("sg_"), "ID should start with 'sg_' prefix"
    assert len(id1) == 15, f"ID should be 15 chars (sg_ + 12 hex), got {len(id1)}"


def test_different_kaimai_hash_different_id():
    """Test that different kaimai_hash produces different schedule_group_id"""
    waste_type = "bendros"

    id1 = generate_schedule_group_id("k1_abc123", waste_type)
    id2 = generate_schedule_group_id("k1_def456", waste_type)

    assert id1 != id2, "Different kaimai_hash should produce different IDs"


def test_different_waste_type_different_id():
    """Test that different waste_type produces different schedule_group_id"""
    kaimai_hash = "k1_abc123"

    id1 = generate_schedule_group_id(kaimai_hash, "bendros")
    id2 = generate_schedule_group_id(kaimai_hash, "plastikas")

    assert id1 != id2, "Different waste_type should produce different IDs"


def test_dates_hash_changes_with_dates():
    """Test that dates_hash changes when dates change"""
    dates1 = [date(2026, 1, 8), date(2026, 1, 22)]
    dates2 = [date(2026, 2, 5), date(2026, 2, 19)]

    hash1 = generate_dates_hash(dates1)
    hash2 = generate_dates_hash(dates2)

    assert hash1 != hash2, "Different dates should produce different dates_hash"
    assert len(hash1) == 16, f"dates_hash should be 16 chars, got {len(hash1)}"


def test_dates_hash_same_for_same_dates():
    """Test that dates_hash is same for same dates (even if order differs)"""
    dates1 = [date(2026, 1, 8), date(2026, 1, 22)]
    dates2 = [date(2026, 1, 22), date(2026, 1, 8)]  # Different order

    hash1 = generate_dates_hash(dates1)
    hash2 = generate_dates_hash(dates2)

    assert hash1 == hash2, "Same dates (different order) should produce same dates_hash"


def test_dates_hash_empty():
    """Test dates_hash for empty dates"""
    hash_empty = generate_dates_hash([])
    assert hash_empty == "", "Empty dates should produce empty dates_hash"


def test_find_or_create_schedule_group_stable_id(temp_db):
    """Test that find_or_create_schedule_group uses stable ID"""
    conn, db_path = temp_db

    kaimai_hash = "k1_test123"
    waste_type = "bendros"
    dates1 = [date(2026, 1, 8), date(2026, 1, 22)]

    # Create schedule group
    id1 = find_or_create_schedule_group(conn, dates1, waste_type, kaimai_hash)
    conn.commit()

    # Update with different dates (same kaimai_hash + waste_type)
    dates2 = [date(2026, 2, 5), date(2026, 2, 19)]
    id2 = find_or_create_schedule_group(conn, dates2, waste_type, kaimai_hash)
    conn.commit()

    # IDs should be the same (stable!)
    assert id1 == id2, "Schedule group ID should remain stable when dates change"

    # Verify in database
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, dates, dates_hash, calendar_synced_at FROM schedule_groups WHERE id = ?", (id1,)
    )
    row = cursor.fetchone()

    assert row is not None, "Schedule group should exist"
    assert row[0] == id1, "ID should match"

    # Dates should be updated
    stored_dates = json.loads(row[1])
    assert stored_dates == ["2026-02-05", "2026-02-19"], "Dates should be updated"

    # calendar_synced_at should be NULL (marked for re-sync)
    assert row[3] is None, "calendar_synced_at should be NULL when dates change (triggers re-sync)"


def test_find_or_create_schedule_group_date_change_detection(temp_db):
    """Test that date changes are detected and calendar is marked for re-sync"""
    conn, db_path = temp_db

    kaimai_hash = "k1_test456"
    waste_type = "bendros"
    dates1 = [date(2026, 1, 8), date(2026, 1, 22)]

    # Create schedule group
    schedule_group_id = find_or_create_schedule_group(conn, dates1, waste_type, kaimai_hash)
    conn.commit()

    # Set calendar_synced_at (simulate calendar already synced)
    cursor = conn.cursor()
    cursor.execute(
        """
        UPDATE schedule_groups
        SET calendar_id = 'test_calendar@google.com',
            calendar_synced_at = CURRENT_TIMESTAMP
        WHERE id = ?
    """,
        (schedule_group_id,),
    )
    conn.commit()

    # Update with different dates
    dates2 = [date(2026, 2, 5), date(2026, 2, 19)]
    find_or_create_schedule_group(conn, dates2, waste_type, kaimai_hash)
    conn.commit()

    # Verify calendar_synced_at is NULL (marked for re-sync)
    cursor.execute(
        """
        SELECT calendar_id, calendar_synced_at, dates_hash
        FROM schedule_groups WHERE id = ?
    """,
        (schedule_group_id,),
    )
    row = cursor.fetchone()

    assert row[0] == "test_calendar@google.com", "Calendar ID should remain (stable calendar)"
    assert row[1] is None, "calendar_synced_at should be NULL (triggers re-sync)"
    assert row[2] == generate_dates_hash(dates2), "dates_hash should be updated"


def test_find_or_create_schedule_group_no_change(temp_db):
    """Test that no update happens when dates don't change"""
    conn, db_path = temp_db

    kaimai_hash = "k1_test789"
    waste_type = "bendros"
    dates = [date(2026, 1, 8), date(2026, 1, 22)]

    # Create schedule group
    schedule_group_id = find_or_create_schedule_group(conn, dates, waste_type, kaimai_hash)
    conn.commit()

    # Set calendar_synced_at
    cursor = conn.cursor()
    cursor.execute(
        """
        UPDATE schedule_groups
        SET calendar_synced_at = CURRENT_TIMESTAMP
        WHERE id = ?
    """,
        (schedule_group_id,),
    )
    conn.commit()

    cursor.execute(
        "SELECT calendar_synced_at FROM schedule_groups WHERE id = ?", (schedule_group_id,)
    )
    row = cursor.fetchone()

    # Call again with same dates
    find_or_create_schedule_group(conn, dates, waste_type, kaimai_hash)
    conn.commit()

    # calendar_synced_at should remain set (no change detected)
    cursor.execute(
        "SELECT calendar_synced_at FROM schedule_groups WHERE id = ?", (schedule_group_id,)
    )
    row = cursor.fetchone()
    synced_at_after = row[0]

    assert synced_at_after is not None, (
        "calendar_synced_at should remain set when dates don't change"
    )


def test_kaimai_hash_generation():
    """Test kaimai_hash generation"""
    kaimai_str1 = "Avižienių, Pikutiškės, Vanaginės g."
    kaimai_str2 = "Avižienių, Pikutiškės, Vanaginės g."  # Same
    kaimai_str3 = "Avižienių, Pikutiškės, Durpių g."  # Different

    hash1 = generate_kaimai_hash(kaimai_str1)
    hash2 = generate_kaimai_hash(kaimai_str2)
    hash3 = generate_kaimai_hash(kaimai_str3)

    assert hash1 == hash2, "Same kaimai_str should produce same hash"
    assert hash1 != hash3, "Different kaimai_str should produce different hash"
    assert hash1.startswith("k1_"), "Hash should start with 'k1_' prefix"
    assert len(hash1) == 15, f"Hash should be 15 chars (k1_ + 12 hex), got {len(hash1)}"
