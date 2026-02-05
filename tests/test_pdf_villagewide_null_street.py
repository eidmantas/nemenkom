import json
import sqlite3
from datetime import date

from services.scraper.core.db_writer import write_location_schedule
from services.scraper_pdf.parser import ensure_pdf_parsed_rows_table


def _insert_schedule_group(
    conn: sqlite3.Connection,
    *,
    schedule_group_id: str,
    waste_type: str,
    kaimai_hash: str,
    dates: list[date],
) -> None:
    dates_iso = [d.isoformat() for d in dates]
    conn.execute(
        """
        INSERT INTO schedule_groups (id, waste_type, kaimai_hash, dates, dates_hash, first_date, last_date, date_count)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            schedule_group_id,
            waste_type,
            kaimai_hash,
            json.dumps(dates_iso, ensure_ascii=False),
            "dh_test",
            min(dates_iso),
            max(dates_iso),
            len(dates_iso),
        ),
    )


def test_schedule_multi_includes_pdf_types_for_villagewide_null_street(temp_db):
    """
    Regression test for villages without explicit streets.

    If pdf_parsed_rows contains village-wide rows with street/mapped_street = NULL, the API should
    still treat that as "whole village" and surface plastikas/stiklas availability + schedule.
    """
    conn, _db_path = temp_db
    ensure_pdf_parsed_rows_table(conn)

    seniunija = "Test"
    village = "Kirzine"

    # Ensure the selection is treated as "village without streets" (locations has only street='').
    write_location_schedule(
        conn,
        seniunija,
        village,
        "",
        [date(2026, 1, 1)],
        "Kirzine",
        None,
        "bendros",
    )
    conn.commit()

    # Insert a plastikas schedule group that the PDF row will map to by kaimai_hash.
    kaimai_hash = "kh_kirzine_plastikas"
    plastikas_dates = [date(2026, 2, 2)]
    _insert_schedule_group(
        conn,
        schedule_group_id="sg_test_plastikas_kirzine",
        waste_type="plastikas",
        kaimai_hash=kaimai_hash,
        dates=plastikas_dates,
    )

    # Insert a PDF row with street/mapped_street NULL (the problematic case).
    conn.execute(
        """
        INSERT INTO pdf_parsed_rows (
            source_file, source_year, waste_type, kaimai_hash, kaimai_str,
            seniunija, mapped_seniunija, village, mapped_village,
            street, mapped_street, house_numbers,
            exclude_streets_json, dates_json, dates_hash, mapping_method
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "test.pdf",
            2026,
            "plastikas",
            kaimai_hash,
            "Kirzine",
            seniunija,
            seniunija,
            village,
            village,
            None,
            None,
            None,
            "[]",
            json.dumps([d.isoformat() for d in plastikas_dates], ensure_ascii=False),
            "dh_pdf_test",
            "test",
        ),
    )
    conn.commit()

    from services.api.app import app

    with app.test_client() as client:
        # For villages without streets, the UI calls schedule-multi without a `street` param.
        resp = client.get(f"/api/v1/schedule-multi?seniunija={seniunija}&village={village}")
        assert resp.status_code == 200
        payload = resp.get_json()
        assert payload["selection"]["street"] == ""
        assert "plastikas" in (payload.get("available_waste_types") or [])
        assert "plastikas" in (payload.get("schedules") or {})
        assert (payload["schedules"]["plastikas"].get("dates") or [])[0]["date"] == "2026-02-02"
