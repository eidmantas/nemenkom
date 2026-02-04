import sqlite3
from datetime import date


def _seed_bendros_location(
    *,
    conn: sqlite3.Connection,
    seniunija: str,
    village: str,
    street: str,
    house_numbers: str | None,
    dates: list[date],
    kaimai_str: str,
):
    from services.scraper.core.db_writer import write_location_schedule

    write_location_schedule(
        conn,
        seniunija,
        village,
        street,
        dates,
        kaimai_str,
        house_numbers,
        waste_type="bendros",
    )
    conn.commit()


def _seed_pdf_row(
    *,
    source_file: str,
    waste_type: str,
    seniunija: str,
    village: str,
    street: str,
    dates: list[date],
    kaimai_str: str,
    house_numbers: str | None = "all",
):
    """
    Inserts a minimal pdf-parsed row via save_pdf_parsed_rows(), which also materializes schedule_groups.
    """
    from services.scraper_pdf.parser import save_pdf_parsed_rows

    save_pdf_parsed_rows(
        [
            {
                "source_file": source_file,
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
        ],
        source_file=source_file,
        source_year=2026,
    )


def test_streets_endpoint_returns_enriched_objects(temp_db):
    conn, _db_path = temp_db

    # Seed a village with streets so /streets returns non-empty list
    _seed_bendros_location(
        conn=conn,
        seniunija="TestSen",
        village="VillageWithStreets",
        street="Main Street",
        house_numbers=None,
        dates=[date(2026, 1, 1)],
        kaimai_str="VillageWithStreets (Main Street)",
    )

    from services.api.app import app

    with app.test_client() as client:
        resp = client.get("/api/v1/streets?seniunija=TestSen&village=VillageWithStreets")
        assert resp.status_code == 200
        payload = resp.get_json()
        assert isinstance(payload["streets"], list)
        assert payload["streets"]
        first = payload["streets"][0]
        assert isinstance(first, dict)
        assert set(first.keys()) >= {
            "street",
            "available_waste_types",
            "bendros_requires_house_numbers",
        }


def test_house_numbers_endpoint_returns_enriched_objects(temp_db):
    conn, _db_path = temp_db

    # Seed a street with an explicit bucket so /house-numbers returns at least one item.
    _seed_bendros_location(
        conn=conn,
        seniunija="TestSen",
        village="VillageWithBuckets",
        street="Bucket Street",
        house_numbers="1-10",
        dates=[date(2026, 1, 2)],
        kaimai_str="VillageWithBuckets (Bucket Street (1-10))",
    )

    from services.api.app import app

    with app.test_client() as client:
        resp = client.get(
            "/api/v1/house-numbers?seniunija=TestSen&village=VillageWithBuckets&street=Bucket%20Street"
        )
        assert resp.status_code == 200
        payload = resp.get_json()
        assert isinstance(payload["house_numbers"], list)
        assert payload["house_numbers"]
        # Because bendros is bucket-split and we did NOT seed any street-wide PDF waste types,
        # there should be no synthetic "Visiems" entry here.
        first = payload["house_numbers"][0]
        assert first["house_numbers"] == "1-10"
        assert isinstance(first, dict)
        assert set(first.keys()) >= {"house_numbers", "available_waste_types"}


def test_house_numbers_endpoint_includes_visiems_when_pdf_is_streetwide(temp_db):
    conn, _db_path = temp_db

    seniunija = "Riešės"
    village = "Didžioji Riešė"
    street = "Vanaginės g."

    # bendros bucket-split street
    _seed_bendros_location(
        conn=conn,
        seniunija=seniunija,
        village=village,
        street=street,
        house_numbers="1-10",
        dates=[date(2026, 1, 2)],
        kaimai_str=f"{village} ({street} (1-10))",
    )

    # PDF says plastikas is street-wide (all), so "Visiems" is valid for that waste type.
    _seed_pdf_row(
        source_file="plastic.pdf",
        waste_type="plastikas",
        seniunija=seniunija,
        village=village,
        street=street,
        dates=[date(2026, 1, 6)],
        kaimai_str=f"{village} {street} (all)",
        house_numbers="all",
    )

    from services.api.app import app

    with app.test_client() as client:
        resp = client.get(
            "/api/v1/house-numbers?seniunija=Rie%C5%A1%C4%97s&village=Did%C5%BEioji%20Rie%C5%A1%C4%97&street=Vanagin%C4%97s%20g."
        )
        assert resp.status_code == 200
        payload = resp.get_json()
        assert payload["house_numbers"][0]["house_numbers"] == ""
        assert "plastikas" in payload["house_numbers"][0]["available_waste_types"]


def test_schedule_multi_bucket_inherits_pdf_all_for_plastic_glass(temp_db):
    conn, _db_path = temp_db

    seniunija = "Riešės"
    village = "Didžioji Riešė"
    street = "Vanaginės g."
    bucket = "1-31A,2-14B"

    _seed_bendros_location(
        conn=conn,
        seniunija=seniunija,
        village=village,
        street=street,
        house_numbers=bucket,
        dates=[date(2026, 1, 9), date(2026, 1, 23)],
        kaimai_str=f"{village} ({street} ({bucket}))",
    )

    # Plastic/glass are street-wide in PDF ("all"), but should show up for any bendros bucket.
    _seed_pdf_row(
        source_file="plastic.pdf",
        waste_type="plastikas",
        seniunija=seniunija,
        village=village,
        street=street,
        dates=[date(2026, 1, 6), date(2026, 2, 4), date(2026, 3, 4)],
        kaimai_str=f"{village} {street} (all)",
        house_numbers="all",
    )
    _seed_pdf_row(
        source_file="glass.pdf",
        waste_type="stiklas",
        seniunija=seniunija,
        village=village,
        street=street,
        dates=[date(2026, 1, 29)],
        kaimai_str=f"{village} {street} (all)",
        house_numbers="all",
    )

    from services.api.app import app

    with app.test_client() as client:
        resp = client.get(
            "/api/v1/schedule-multi?seniunija=Rie%C5%A1%C4%97s&village=Did%C5%BEioji%20Rie%C5%A1%C4%97&street=Vanagin%C4%97s%20g.&house_numbers=1-31A,2-14B"
        )
        assert resp.status_code == 200
        payload = resp.get_json()
        assert payload["available_waste_types"] == ["bendros", "plastikas", "stiklas"]
        assert set(payload["schedules"].keys()) == {"bendros", "plastikas", "stiklas"}
        assert len(payload["schedules"]["bendros"]["dates"]) == 2
        assert len(payload["schedules"]["plastikas"]["dates"]) == 3
        assert len(payload["schedules"]["stiklas"]["dates"]) == 1

        # Combined date list should be tagged with waste_type.
        assert all("waste_type" in d and "date" in d for d in payload["dates"])


def test_schedule_multi_village_with_no_streets(temp_db):
    conn, _db_path = temp_db

    seniunija = "Maišiagalos"
    village = "Maišiagala"

    # Village-only (street="") selection
    _seed_bendros_location(
        conn=conn,
        seniunija=seniunija,
        village=village,
        street="",
        house_numbers=None,
        dates=[date(2026, 1, 15)],
        kaimai_str=village,
    )

    # Plastic exists at village-level in PDF (street="").
    _seed_pdf_row(
        source_file="plastic.pdf",
        waste_type="plastikas",
        seniunija=seniunija,
        village=village,
        street="",
        dates=[date(2026, 1, 2)],
        kaimai_str=f"{village} (all)",
        house_numbers=None,
    )

    from services.api.app import app

    with app.test_client() as client:
        resp = client.get(
            "/api/v1/schedule-multi?seniunija=Mai%C5%A1iagalos&village=Mai%C5%A1iagala"
        )
        assert resp.status_code == 200
        payload = resp.get_json()
        assert payload["selection"]["street"] == ""
        assert "bendros" in payload["available_waste_types"]
        assert "bendros" in payload["schedules"]
        assert "plastikas" in payload["available_waste_types"]
        assert "plastikas" in payload["schedules"]


def test_schedule_multi_street_inherits_villagewide_pdf_rows(temp_db):
    conn, _db_path = temp_db

    seniunija = "Zujūnų"
    village = "Buivydiškės"
    street = "Sodų Kalno g."

    # bendros exists at street-level (canonical XLSX)
    _seed_bendros_location(
        conn=conn,
        seniunija=seniunija,
        village=village,
        street=street,
        house_numbers=None,
        dates=[date(2026, 1, 10)],
        kaimai_str=f"{village} ({street})",
    )

    # plastikas is village-wide in PDF (street=""), should be inherited by any street selection in this village.
    _seed_pdf_row(
        source_file="plastic.pdf",
        waste_type="plastikas",
        seniunija=seniunija,
        village=village,
        street="",
        dates=[date(2026, 1, 6)],
        kaimai_str=f"{village} (all streets)",
        house_numbers=None,
    )

    from services.api.app import app

    with app.test_client() as client:
        resp = client.get(
            "/api/v1/schedule-multi?seniunija=Zuj%C5%ABn%C5%B3&village=Buivydi%C5%A1k%C4%97s&street=Sod%C5%B3%20Kalno%20g."
        )
        assert resp.status_code == 200
        payload = resp.get_json()
        assert "plastikas" in payload["available_waste_types"]
        assert "plastikas" in payload["schedules"]
        assert payload["schedules"]["plastikas"]["dates"][0]["date"] == "2026-01-06"
