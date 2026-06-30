from datetime import date
from pathlib import Path

import pandas as pd

import services.scraper_pdf.parser as pdf_parser
from services.api.db import get_multi_waste_schedule_for_selection
from services.scraper.core.db_writer import (
    generate_kaimai_hash,
    generate_schedule_group_id,
    get_calendar_stream_id_for_schedule_group,
    write_location_schedule,
)
from services.scraper_pdf.parser import (
    PdfParsedCell,
    PdfParsedGroup,
    PdfParsedStreet,
    save_pdf_parsed_rows,
)


def _seed_bendros_location(
    conn,
    *,
    seniunija: str,
    village: str,
    street: str,
    house_numbers: str | None = None,
) -> None:
    write_location_schedule(
        conn,
        seniunija,
        village,
        street,
        [date(2026, 1, 1)],
        f"{village} ({street})" if street else village,
        house_numbers,
        waste_type="bendros",
    )
    conn.commit()


def _pdf_item(
    *,
    waste_type: str,
    seniunija: str,
    village: str,
    street: str,
    dates: list[date],
    kaimai_str: str,
    house_numbers: str | None = "all",
) -> dict:
    return {
        "waste_type": waste_type,
        "seniunija": seniunija,
        "mapped_seniunija": seniunija,
        "village": village,
        "mapped_village": village,
        "street": street,
        "mapped_street": street,
        "house_numbers": house_numbers,
        "exclude_streets": [],
        "dates": dates,
        "kaimai_str": kaimai_str,
        "mapping_method": "test",
    }


def _fake_pdf_cell(seniunija: str, village: str, street: str) -> PdfParsedCell:
    return PdfParsedCell(
        seniunija=seniunija,
        groups=[
            PdfParsedGroup(
                village=village,
                include_streets=[PdfParsedStreet(street=street)],
            )
        ],
    )


def test_pdf_rollover_reuses_existing_calendar_hash_when_raw_text_changes(temp_db):
    conn, _ = temp_db

    seniunija = "Riešės"
    village = "Didžioji Riešė"
    street = "Akmenų g."
    waste_type = "plastikas"
    old_source = "plastic-q1.pdf"
    new_source = "plastic-q2.pdf"
    old_raw = "Riešės sen. Didžiosios Riešės k. (Akmenų g.)"
    new_raw = "Riešės sen. Didžiosios Riešės mstl. (Akmenų g.)"
    dates_q1 = [date(2026, 1, 2), date(2026, 2, 2), date(2026, 3, 2)]
    dates_q2 = [date(2026, 4, 1), date(2026, 5, 1), date(2026, 6, 1)]

    _seed_bendros_location(
        conn,
        seniunija=seniunija,
        village=village,
        street=street,
    )

    save_pdf_parsed_rows(
        [
            _pdf_item(
                waste_type=waste_type,
                seniunija=seniunija,
                village=village,
                street=street,
                dates=dates_q1,
                kaimai_str=old_raw,
            )
        ],
        source_file=old_source,
        source_year=2026,
    )

    old_hash = generate_kaimai_hash(old_raw)
    schedule_group_id = generate_schedule_group_id(old_hash, waste_type)
    calendar_stream_id = get_calendar_stream_id_for_schedule_group(conn, schedule_group_id)
    assert calendar_stream_id is not None

    conn.execute(
        """
        UPDATE calendar_streams
        SET calendar_id = 'plastikas_existing@group.calendar.google.com',
            calendar_synced_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (calendar_stream_id,),
    )
    conn.commit()

    save_pdf_parsed_rows(
        [
            _pdf_item(
                waste_type=waste_type,
                seniunija=seniunija,
                village=village,
                street=street,
                dates=dates_q2,
                kaimai_str=new_raw,
            )
        ],
        source_file=new_source,
        source_year=2026,
    )

    rows = conn.execute(
        """
        SELECT source_file, kaimai_hash
        FROM pdf_parsed_rows
        WHERE waste_type = 'plastikas'
        """
    ).fetchall()
    assert rows == [(new_source, old_hash)]

    schedule_group = conn.execute(
        """
        SELECT dates, first_date, last_date
        FROM schedule_groups
        WHERE id = ?
        """,
        (schedule_group_id,),
    ).fetchone()
    assert schedule_group is not None
    assert "2026-04-01" in schedule_group[0]
    assert schedule_group[1] == "2026-04-01"
    assert schedule_group[2] == "2026-06-01"

    relinked_stream_id = get_calendar_stream_id_for_schedule_group(conn, schedule_group_id)
    assert relinked_stream_id == calendar_stream_id

    stream_row = conn.execute(
        """
        SELECT calendar_id, calendar_synced_at, dates
        FROM calendar_streams
        WHERE id = ?
        """,
        (calendar_stream_id,),
    ).fetchone()
    assert stream_row is not None
    assert stream_row[0] == "plastikas_existing@group.calendar.google.com"
    assert stream_row[1] is None
    assert "2026-06-01" in stream_row[2]

    payload = get_multi_waste_schedule_for_selection(
        seniunija=seniunija,
        village=village,
        street=street,
        house_numbers=None,
    )
    assert "plastikas" in payload["schedules"]
    plastikas = payload["schedules"]["plastikas"]
    assert plastikas["calendar_id"] == "plastikas_existing@group.calendar.google.com"
    assert [row["date"] for row in plastikas["dates"]] == [d.isoformat() for d in dates_q2]


def test_pdf_rollover_reuses_single_historical_group_for_expanded_raw_group(temp_db):
    conn, _ = temp_db

    seniunija = "Riešės"
    village = "Didžioji Riešė"
    waste_type = "plastikas"
    old_source = "plastic-q1.pdf"
    new_source = "plastic-q2.pdf"
    old_raw = "Riešės sen. Didžiosios Riešės k. (Akmenų g., Gėlyno g.)"
    new_raw = "Riešės sen. Didžiosios Riešės mstl. (Akmenų g., Gėlyno g., Kaštonų g.)"
    dates_q1 = [date(2026, 1, 2), date(2026, 2, 2), date(2026, 3, 2)]
    dates_q2 = [date(2026, 4, 1), date(2026, 5, 1), date(2026, 6, 1)]

    save_pdf_parsed_rows(
        [
            _pdf_item(
                waste_type=waste_type,
                seniunija=seniunija,
                village=village,
                street="Akmenų g.",
                dates=dates_q1,
                kaimai_str=old_raw,
            ),
            _pdf_item(
                waste_type=waste_type,
                seniunija=seniunija,
                village=village,
                street="Gėlyno g.",
                dates=dates_q1,
                kaimai_str=old_raw,
            ),
        ],
        source_file=old_source,
        source_year=2026,
    )

    old_hash = generate_kaimai_hash(old_raw)
    schedule_group_id = generate_schedule_group_id(old_hash, waste_type)
    calendar_stream_id = get_calendar_stream_id_for_schedule_group(conn, schedule_group_id)
    assert calendar_stream_id is not None
    conn.execute(
        """
        UPDATE calendar_streams
        SET calendar_id = 'plastikas_group@group.calendar.google.com',
            calendar_synced_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (calendar_stream_id,),
    )
    conn.commit()

    save_pdf_parsed_rows(
        [
            _pdf_item(
                waste_type=waste_type,
                seniunija=seniunija,
                village=village,
                street="Akmenų g.",
                dates=dates_q2,
                kaimai_str=new_raw,
            ),
            _pdf_item(
                waste_type=waste_type,
                seniunija=seniunija,
                village=village,
                street="Gėlyno g.",
                dates=dates_q2,
                kaimai_str=new_raw,
            ),
            _pdf_item(
                waste_type=waste_type,
                seniunija=seniunija,
                village=village,
                street="Kaštonų g.",
                dates=dates_q2,
                kaimai_str=new_raw,
            ),
        ],
        source_file=new_source,
        source_year=2026,
    )

    rows = conn.execute(
        """
        SELECT DISTINCT kaimai_hash
        FROM pdf_parsed_rows
        WHERE waste_type = 'plastikas'
        """
    ).fetchall()
    assert rows == [(old_hash,)]

    stream_row = conn.execute(
        """
        SELECT calendar_id, calendar_synced_at, dates
        FROM calendar_streams
        WHERE id = ?
        """,
        (calendar_stream_id,),
    ).fetchone()
    assert stream_row is not None
    assert stream_row[0] == "plastikas_group@group.calendar.google.com"
    assert stream_row[1] is None
    assert "2026-06-01" in stream_row[2]


def test_pdf_rollover_ambiguous_single_selection_falls_back_to_raw_hash(temp_db):
    conn, _ = temp_db

    waste_type = "plastikas"
    source_old = "plastic-q1.pdf"
    source_new = "plastic-q2.pdf"
    dates_q1 = [date(2026, 1, 2), date(2026, 2, 2), date(2026, 3, 2)]
    dates_q2 = [date(2026, 4, 1), date(2026, 5, 1), date(2026, 6, 1)]
    old_raw_a = "Avižienių sen. Avižienių mstl. (Gėlių g.)"
    old_raw_b = "Avižienių sen. Avižienių mstl. (Gėlių g., Kelpių g.)"
    new_raw = "Avižienių sen. Avižienių mstl. (Gėlių g. tik nuo 1 iki 10)"

    save_pdf_parsed_rows(
        [
            _pdf_item(
                waste_type=waste_type,
                seniunija="Avižienių",
                village="Avižienių mstl.",
                street="Gėlių g.",
                dates=dates_q1,
                kaimai_str=old_raw_a,
            ),
            _pdf_item(
                waste_type=waste_type,
                seniunija="Avižienių",
                village="Avižienių mstl.",
                street="Gėlių g.",
                dates=dates_q1,
                kaimai_str=old_raw_b,
            ),
            _pdf_item(
                waste_type=waste_type,
                seniunija="Avižienių",
                village="Avižienių mstl.",
                street="Kelpių g.",
                dates=dates_q1,
                kaimai_str=old_raw_b,
            ),
        ],
        source_file=source_old,
        source_year=2026,
    )

    save_pdf_parsed_rows(
        [
            _pdf_item(
                waste_type=waste_type,
                seniunija="Avižienių",
                village="Avižienių mstl.",
                street="Gėlių g.",
                dates=dates_q2,
                kaimai_str=new_raw,
            ),
        ],
        source_file=source_new,
        source_year=2026,
    )

    rows = conn.execute(
        """
        SELECT DISTINCT kaimai_hash
        FROM pdf_parsed_rows
        WHERE waste_type = 'plastikas'
        """
    ).fetchall()
    assert rows == [(generate_kaimai_hash(new_raw),)]


def test_pdf_rollover_prefers_group_winner_over_ambiguous_selection_overlap(temp_db):
    conn, _ = temp_db

    waste_type = "plastikas"
    source_old = "plastic-q1.pdf"
    source_new = "plastic-q2.pdf"
    dates_q1 = [date(2026, 1, 2), date(2026, 2, 2), date(2026, 3, 2)]
    dates_q2 = [date(2026, 4, 1), date(2026, 5, 1), date(2026, 6, 1)]
    old_primary = "Avižienių sen. Avižienių mstl. (Akmenų g., Gėlių g.)"
    old_secondary = "Avižienių sen. Avižienių mstl. (Gėlių g.)"
    new_raw = "Avižienių sen. Avižienių mstl. (Akmenų g., Gėlių g., Kaštonų g.)"

    save_pdf_parsed_rows(
        [
            _pdf_item(
                waste_type=waste_type,
                seniunija="Avižienių",
                village="Avižienių mstl.",
                street="Akmenų g.",
                dates=dates_q1,
                kaimai_str=old_primary,
            ),
            _pdf_item(
                waste_type=waste_type,
                seniunija="Avižienių",
                village="Avižienių mstl.",
                street="Gėlių g.",
                dates=dates_q1,
                kaimai_str=old_primary,
            ),
            _pdf_item(
                waste_type=waste_type,
                seniunija="Avižienių",
                village="Avižienių mstl.",
                street="Gėlių g.",
                dates=dates_q1,
                kaimai_str=old_secondary,
            ),
        ],
        source_file=source_old,
        source_year=2026,
    )

    primary_hash = generate_kaimai_hash(old_primary)
    schedule_group_id = generate_schedule_group_id(primary_hash, waste_type)
    calendar_stream_id = get_calendar_stream_id_for_schedule_group(conn, schedule_group_id)
    assert calendar_stream_id is not None
    conn.execute(
        """
        UPDATE calendar_streams
        SET calendar_id = 'plastikas_group_overlap@group.calendar.google.com',
            calendar_synced_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (calendar_stream_id,),
    )
    conn.commit()

    save_pdf_parsed_rows(
        [
            _pdf_item(
                waste_type=waste_type,
                seniunija="Avižienių",
                village="Avižienių mstl.",
                street="Akmenų g.",
                dates=dates_q2,
                kaimai_str=new_raw,
            ),
            _pdf_item(
                waste_type=waste_type,
                seniunija="Avižienių",
                village="Avižienių mstl.",
                street="Gėlių g.",
                dates=dates_q2,
                kaimai_str=new_raw,
            ),
            _pdf_item(
                waste_type=waste_type,
                seniunija="Avižienių",
                village="Avižienių mstl.",
                street="Kaštonų g.",
                dates=dates_q2,
                kaimai_str=new_raw,
            ),
        ],
        source_file=source_new,
        source_year=2026,
    )

    rows = conn.execute(
        """
        SELECT DISTINCT kaimai_hash
        FROM pdf_parsed_rows
        WHERE waste_type = 'plastikas'
        """
    ).fetchall()
    assert rows == [(primary_hash,)]

    relinked_stream_id = get_calendar_stream_id_for_schedule_group(conn, schedule_group_id)
    assert relinked_stream_id == calendar_stream_id


def test_pdf_rollover_recovers_missing_historical_seniunija_for_street_level_continuity(temp_db):
    conn, _ = temp_db

    waste_type = "stiklas"
    source_old = "glass-q1.pdf"
    source_new = "glass-q2.pdf"
    special_dates_q1 = [date(2026, 3, 28)]
    general_dates_q1 = [date(2026, 3, 23)]
    dates_q2 = [date(2026, 6, 26)]
    special_old_raw = "Kriaučiūnų k. Sėkmės g. Platiniškių k. tik Adomo Mickevičiaus g."
    general_old_raw = (
        "Zujūnų sen. kaimai Kriaučiūnų k. išskyrus Sėkmės g. "
        "Platiniškių k. išskyrus Adomo Mickevičiaus g."
    )
    new_raw = (
        "Sudervės sen. ... Zujūnų sen. kaimai: Kriaučiūnų k. Sėkmės g. "
        "Platiniškių k. tik Adomo Mickevičiaus g."
    )

    save_pdf_parsed_rows(
        [
            _pdf_item(
                waste_type=waste_type,
                seniunija="",
                village="Platiniškių k.",
                street="Adomo Mickevičiaus g.",
                dates=special_dates_q1,
                kaimai_str=special_old_raw,
            ),
            _pdf_item(
                waste_type=waste_type,
                seniunija="Zujūnų",
                village="Kriaučiūnų k.",
                street="",
                dates=general_dates_q1,
                kaimai_str=general_old_raw,
                house_numbers=None,
            ),
        ],
        source_file=source_old,
        source_year=2026,
    )

    special_hash = generate_kaimai_hash(special_old_raw)
    general_hash = generate_kaimai_hash(general_old_raw)
    special_group_id = generate_schedule_group_id(special_hash, waste_type)
    special_stream_id = get_calendar_stream_id_for_schedule_group(conn, special_group_id)
    assert special_stream_id is not None

    conn.execute(
        """
        UPDATE calendar_streams
        SET calendar_id = 'stiklas_special@group.calendar.google.com',
            calendar_synced_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (special_stream_id,),
    )
    conn.commit()

    save_pdf_parsed_rows(
        [
            _pdf_item(
                waste_type=waste_type,
                seniunija="Zujūnų",
                village="Kriaučiūnų k.",
                street="",
                dates=dates_q2,
                kaimai_str=new_raw,
                house_numbers=None,
            ),
            _pdf_item(
                waste_type=waste_type,
                seniunija="Zujūnų",
                village="Platiniškių k.",
                street="Adomo Mickevičiaus g.",
                dates=dates_q2,
                kaimai_str=new_raw,
            ),
        ],
        source_file=source_new,
        source_year=2026,
    )

    rows = {
        row[0]
        for row in conn.execute(
            """
            SELECT DISTINCT kaimai_hash
            FROM pdf_parsed_rows
            WHERE waste_type = 'stiklas'
            """
        ).fetchall()
    }
    assert rows == {special_hash, general_hash}

    assert get_calendar_stream_id_for_schedule_group(conn, special_group_id) == special_stream_id

    stream_row = conn.execute(
        """
        SELECT calendar_id, calendar_synced_at, dates
        FROM calendar_streams
        WHERE id = ?
        """,
        (special_stream_id,),
    ).fetchone()
    assert stream_row is not None
    assert stream_row[0] == "stiklas_special@group.calendar.google.com"
    assert stream_row[1] is None
    assert "2026-06-26" in stream_row[2]


def test_pdf_rollover_split_street_dates_fall_back_to_new_groups(temp_db):
    conn, _ = temp_db

    waste_type = "plastikas"
    source_old = "plastic-q1.pdf"
    source_new = "plastic-q2.pdf"
    old_raw = "Avižienių sen. Avižienių mstl. (Akmenų g., Gėlių g.)"
    new_raw_a = "Avižienių sen. Avižienių mstl. (Akmenų g.)"
    new_raw_b = "Avižienių sen. Avižienių mstl. (Gėlių g.)"
    dates_q1 = [date(2026, 1, 2), date(2026, 2, 2), date(2026, 3, 2)]
    dates_q2_a = [date(2026, 4, 1), date(2026, 5, 1), date(2026, 6, 1)]
    dates_q2_b = [date(2026, 4, 9), date(2026, 5, 9), date(2026, 6, 9)]

    save_pdf_parsed_rows(
        [
            _pdf_item(
                waste_type=waste_type,
                seniunija="Avižienių",
                village="Avižienių mstl.",
                street="Akmenų g.",
                dates=dates_q1,
                kaimai_str=old_raw,
            ),
            _pdf_item(
                waste_type=waste_type,
                seniunija="Avižienių",
                village="Avižienių mstl.",
                street="Gėlių g.",
                dates=dates_q1,
                kaimai_str=old_raw,
            ),
        ],
        source_file=source_old,
        source_year=2026,
    )

    save_pdf_parsed_rows(
        [
            _pdf_item(
                waste_type=waste_type,
                seniunija="Avižienių",
                village="Avižienių mstl.",
                street="Akmenų g.",
                dates=dates_q2_a,
                kaimai_str=new_raw_a,
            ),
            _pdf_item(
                waste_type=waste_type,
                seniunija="Avižienių",
                village="Avižienių mstl.",
                street="Gėlių g.",
                dates=dates_q2_b,
                kaimai_str=new_raw_b,
            ),
        ],
        source_file=source_new,
        source_year=2026,
    )

    rows = {
        row[0]
        for row in conn.execute(
            """
            SELECT DISTINCT kaimai_hash
            FROM pdf_parsed_rows
            WHERE waste_type = 'plastikas'
            """
        ).fetchall()
    }
    assert rows == {generate_kaimai_hash(new_raw_a), generate_kaimai_hash(new_raw_b)}


def test_pdf_rollover_split_keeps_old_hash_only_for_dominant_successor(temp_db):
    conn, _ = temp_db

    waste_type = "plastikas"
    source_old = "plastic-q1.pdf"
    source_new = "plastic-q2.pdf"
    old_raw = "Avižienių sen. Avižienių mstl. (Akmenų g., Gėlių g., Kaštonų g.)"
    new_raw_primary = "Avižienių sen. Avižienių mstl. (Akmenų g., Gėlių g.)"
    new_raw_secondary = "Avižienių sen. Avižienių mstl. (Kaštonų g.)"
    dates_q1 = [date(2026, 1, 2), date(2026, 2, 2), date(2026, 3, 2)]
    dates_q2_primary = [date(2026, 4, 1), date(2026, 5, 1), date(2026, 6, 1)]
    dates_q2_secondary = [date(2026, 4, 9), date(2026, 5, 9), date(2026, 6, 9)]

    save_pdf_parsed_rows(
        [
            _pdf_item(
                waste_type=waste_type,
                seniunija="Avižienių",
                village="Avižienių mstl.",
                street="Akmenų g.",
                dates=dates_q1,
                kaimai_str=old_raw,
            ),
            _pdf_item(
                waste_type=waste_type,
                seniunija="Avižienių",
                village="Avižienių mstl.",
                street="Gėlių g.",
                dates=dates_q1,
                kaimai_str=old_raw,
            ),
            _pdf_item(
                waste_type=waste_type,
                seniunija="Avižienių",
                village="Avižienių mstl.",
                street="Kaštonų g.",
                dates=dates_q1,
                kaimai_str=old_raw,
            ),
        ],
        source_file=source_old,
        source_year=2026,
    )

    old_hash = generate_kaimai_hash(old_raw)

    save_pdf_parsed_rows(
        [
            _pdf_item(
                waste_type=waste_type,
                seniunija="Avižienių",
                village="Avižienių mstl.",
                street="Akmenų g.",
                dates=dates_q2_primary,
                kaimai_str=new_raw_primary,
            ),
            _pdf_item(
                waste_type=waste_type,
                seniunija="Avižienių",
                village="Avižienių mstl.",
                street="Gėlių g.",
                dates=dates_q2_primary,
                kaimai_str=new_raw_primary,
            ),
            _pdf_item(
                waste_type=waste_type,
                seniunija="Avižienių",
                village="Avižienių mstl.",
                street="Kaštonų g.",
                dates=dates_q2_secondary,
                kaimai_str=new_raw_secondary,
            ),
        ],
        source_file=source_new,
        source_year=2026,
    )

    rows = {
        row[0]
        for row in conn.execute(
            """
            SELECT DISTINCT kaimai_hash
            FROM pdf_parsed_rows
            WHERE waste_type = 'plastikas'
            """
        ).fetchall()
    }
    assert rows == {old_hash, generate_kaimai_hash(new_raw_secondary)}


def test_pdf_rollover_unlinks_obsolete_groups_and_marks_old_stream_pending_clean(temp_db):
    conn, _ = temp_db

    waste_type = "plastikas"
    source_old = "plastic-q1.pdf"
    source_new = "plastic-q2.pdf"
    keep_dates_q1 = [date(2026, 1, 3), date(2026, 2, 3), date(2026, 3, 3)]
    drop_dates_q1 = [date(2026, 1, 7), date(2026, 2, 7), date(2026, 3, 7)]
    dates_q2 = [date(2026, 4, 3), date(2026, 5, 4), date(2026, 6, 3)]

    old_keep = "Nemenčinės sen. Aliniškių k."
    old_drop = "Nemenčinės sen. Bališkių k."
    keep_hash = generate_kaimai_hash(old_keep)
    drop_hash = generate_kaimai_hash(old_drop)
    keep_group_id = generate_schedule_group_id(keep_hash, waste_type)
    drop_group_id = generate_schedule_group_id(drop_hash, waste_type)

    save_pdf_parsed_rows(
        [
            _pdf_item(
                waste_type=waste_type,
                seniunija="Nemenčinės",
                village="Aliniškės",
                street="",
                dates=keep_dates_q1,
                kaimai_str=old_keep,
                house_numbers=None,
            ),
            _pdf_item(
                waste_type=waste_type,
                seniunija="Nemenčinės",
                village="Bališkės",
                street="",
                dates=drop_dates_q1,
                kaimai_str=old_drop,
                house_numbers=None,
            ),
        ],
        source_file=source_old,
        source_year=2026,
    )

    keep_stream_id = get_calendar_stream_id_for_schedule_group(conn, keep_group_id)
    drop_stream_id = get_calendar_stream_id_for_schedule_group(conn, drop_group_id)
    assert keep_stream_id is not None
    assert drop_stream_id is not None

    save_pdf_parsed_rows(
        [
            _pdf_item(
                waste_type=waste_type,
                seniunija="Nemenčinės",
                village="Aliniškės",
                street="",
                dates=dates_q2,
                kaimai_str="Nemenčinės sen. Aliniškių k. (Q2)",
                house_numbers=None,
            )
        ],
        source_file=source_new,
        source_year=2026,
    )

    assert get_calendar_stream_id_for_schedule_group(conn, keep_group_id) == keep_stream_id
    assert get_calendar_stream_id_for_schedule_group(conn, drop_group_id) is None

    drop_stream = conn.execute(
        """
        SELECT pending_clean_started_at
        FROM calendar_streams
        WHERE id = ?
        """,
        (drop_stream_id,),
    ).fetchone()
    assert drop_stream is not None
    assert drop_stream[0] is not None


def test_parse_pdf_uses_filename_months_when_headers_are_blank(monkeypatch):
    table = pd.DataFrame(
        [
            ["Seniūnijos pavadinimas (gyvenvietės pavadinimas)", "Atliekos", "", "", ""],
            ["Avižienių sen. Avižienių mstl. (Gėlių g.)", "Stiklas", "16 d.", "17 d.", "18 d."],
        ]
    )

    captured: dict[str, list[dict]] = {}
    monkeypatch.setattr(pdf_parser, "extract_marker_tables", lambda _file_path: [table])
    monkeypatch.setattr(
        pdf_parser,
        "parse_pdf_cell_with_ai",
        lambda *_args, **_kwargs: _fake_pdf_cell("Avižienių", "Avižienių mstl.", "Gėlių g."),
    )
    monkeypatch.setattr(pdf_parser, "apply_mappings", lambda rows: rows)
    monkeypatch.setattr(
        pdf_parser,
        "save_pdf_parsed_rows",
        lambda rows, source_file, source_year: captured.setdefault("rows", list(rows)),
    )

    results, _raw_rows, normalized_rows = pdf_parser.parse_pdf(
        Path("2026 m- balandis, gegužė, birželis mėn- Stiklo grafikas.pdf"),
        year=2026,
        skip_ai=False,
    )

    assert [d.isoformat() for d in results[0]["dates"]] == [
        "2026-04-16",
        "2026-05-17",
        "2026-06-18",
    ]
    assert normalized_rows[0]["month_Balandžio"] == "16 d."
    assert normalized_rows[0]["month_Gegužės"] == "17 d."
    assert normalized_rows[0]["month_Birželio"] == "18 d."
    assert [d.isoformat() for d in captured["rows"][0]["dates"]] == [
        "2026-04-16",
        "2026-05-17",
        "2026-06-18",
    ]


def test_split_fused_pdf_header_strips_q3_month_tokens():
    table = pd.DataFrame(
        [
            [
                "Seniūnijos pavadinimas (gyvenvietės pavadinimas) "
                "Atliekos Liepa Rugpjūtis Rugsėjis "
                "Nemenčinės sen. Gamernės k. Pakuotė 1 d."
            ],
        ]
    )

    split = pdf_parser.split_fused_header_rows(table)

    assert len(split) == 2
    data_cell = split.iloc[1, 0]
    assert data_cell == "Nemenčinės sen. Gamernės k. Pakuotė 1 d."
    assert "Liepa" not in data_cell
    assert "Rugpjūtis" not in data_cell
    assert "Rugsėjis" not in data_cell


def test_infer_pdf_waste_label_decodes_q3_encoded_filename():
    path = Path(
        "%E2%80%9E2026%20m-%20liepos%2C%20rugpj%C5%AB%C4%8Dio%2C%20"
        "rugs%C4%97jo%20m%C4%97n-%20Pakuo%C4%8Di%C5%B3%20atliek%C5%B3%20"
        "surinkimo%20grafikas.pdf"
    )

    assert pdf_parser.infer_pdf_waste_label(path) == "Pakuotė"


def test_infer_pdf_waste_label_prefers_glass_for_stiklo_pakuotes_filename():
    path = Path(
        "2026%20m-%20liepos%2C%20rugpj%C5%AB%C4%8Dio%2C%20"
        "rugs%C4%97jo%20m%C4%97n-%20Stiklo%20pakuo%C4%8Di%C5%B3%20"
        "atliek%C5%B3%20surinkimo%20grafikas.pdf"
    )

    assert pdf_parser.infer_pdf_waste_label(path) == "Stiklas"
    assert pdf_parser.normalize_waste_label("Stiklo pakuočių atliekos") == "Stiklas"
    assert pdf_parser.normalize_waste_type("Stiklo pakuočių atliekos") == "stiklas"


def test_parse_pdf_repeats_embedded_day_across_visible_q2_months(monkeypatch):
    table = pd.DataFrame(
        [
            ["Seniūnijos pavadinimas (gyvenvietės pavadinimas)", "Atliekos", "", "", ""],
            ["Avižienių sen. Avižienių mstl. 16 d. (Gėlių g.)", "Stiklas", "", "", ""],
        ]
    )

    monkeypatch.setattr(pdf_parser, "extract_marker_tables", lambda _file_path: [table])
    monkeypatch.setattr(
        pdf_parser,
        "parse_pdf_cell_with_ai",
        lambda *_args, **_kwargs: _fake_pdf_cell("Avižienių", "Avižienių mstl.", "Gėlių g."),
    )
    monkeypatch.setattr(pdf_parser, "apply_mappings", lambda rows: rows)
    monkeypatch.setattr(pdf_parser, "save_pdf_parsed_rows", lambda *args, **kwargs: None)

    results, _raw_rows, normalized_rows = pdf_parser.parse_pdf(
        Path("2026 m- balandis, gegužė, birželis mėn- Stiklo grafikas.pdf"),
        year=2026,
        skip_ai=False,
    )

    assert [d.isoformat() for d in results[0]["dates"]] == [
        "2026-04-16",
        "2026-05-16",
        "2026-06-16",
    ]
    assert normalized_rows[0]["month_Balandžio"] == "16 d."
    assert normalized_rows[0]["month_Gegužės"] == "16 d."
    assert normalized_rows[0]["month_Birželio"] == "16 d."


def test_parse_pdf_shifts_two_month_tables_by_visible_month_pair(monkeypatch):
    table = pd.DataFrame(
        [
            [
                "Seniūnijos pavadinimas (gyvenvietės pavadinimas)",
                "Atliekos",
                "Rugsėjo",
                "Spalio",
            ],
            ["Avižienių sen. Avižienių mstl. (Gėlių g.)", "Stiklas", "16 d.", ""],
        ]
    )

    monkeypatch.setattr(pdf_parser, "extract_marker_tables", lambda _file_path: [table])
    monkeypatch.setattr(
        pdf_parser,
        "parse_pdf_cell_with_ai",
        lambda *_args, **_kwargs: _fake_pdf_cell("Avižienių", "Avižienių mstl.", "Gėlių g."),
    )
    monkeypatch.setattr(pdf_parser, "apply_mappings", lambda rows: rows)
    monkeypatch.setattr(pdf_parser, "save_pdf_parsed_rows", lambda *args, **kwargs: None)

    results, _raw_rows, normalized_rows = pdf_parser.parse_pdf(
        Path("2026 m- rugsėjis, spalis mėn- Stiklo grafikas.pdf"),
        year=2026,
        skip_ai=False,
    )

    assert [d.isoformat() for d in results[0]["dates"]] == ["2026-10-16"]
    assert normalized_rows[0]["month_Rugsėjo"] == ""
    assert normalized_rows[0]["month_Spalio"] == "16 d."


def test_parse_pdf_uses_neighboring_month_hints_for_headerless_single_month_tables(monkeypatch):
    tables = [
        pd.DataFrame(
            [
                [
                    "Seniūnijos pavadinimas (gyvenvietės pavadinimas)",
                    "Atliekos",
                    "Gegužė",
                ],
                ["Avižienių sen. Avižienių mstl. (Gėlių g.)", "Stiklas", "15 d."],
            ]
        ),
        pd.DataFrame(
            [
                ["Avižienių sen. Avižienių mstl. (Gėlių g.)", "Stiklas", "16 d."],
            ]
        ),
        pd.DataFrame(
            [
                [
                    "Seniūnijos pavadinimas (gyvenvietės pavadinimas)",
                    "Atliekos",
                    "Balandis",
                    "Gegužė",
                    "Birželis",
                ],
                ["Avižienių sen. Avižienių mstl. (Gėlių g.)", "Stiklas", "", "", "22 d."],
            ]
        ),
        pd.DataFrame(
            [
                ["Avižienių sen. Avižienių mstl. (Gėlių g.)", "Stiklas", "29 d."],
            ]
        ),
    ]

    monkeypatch.setattr(pdf_parser, "extract_marker_tables", lambda _file_path: tables)
    monkeypatch.setattr(
        pdf_parser,
        "parse_pdf_cell_with_ai",
        lambda *_args, **_kwargs: _fake_pdf_cell("Avižienių", "Avižienių mstl.", "Gėlių g."),
    )
    monkeypatch.setattr(pdf_parser, "apply_mappings", lambda rows: rows)
    monkeypatch.setattr(pdf_parser, "save_pdf_parsed_rows", lambda *args, **kwargs: None)

    results, _raw_rows, normalized_rows = pdf_parser.parse_pdf(
        Path("2026 m- balandis, gegužė, birželis mėn- Stiklo grafikas.pdf"),
        year=2026,
        skip_ai=False,
    )

    assert [[d.isoformat() for d in row["dates"]] for row in results] == [
        ["2026-05-15"],
        ["2026-06-16"],
        ["2026-06-22"],
        ["2026-06-29"],
    ]
    assert normalized_rows[1]["month_Birželio"] == "16 d."
    assert normalized_rows[3]["month_Birželio"] == "29 d."
