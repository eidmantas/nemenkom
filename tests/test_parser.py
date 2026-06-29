"""
Unit tests for parser functions
"""

from datetime import date

from services.scraper.ai.router import should_use_ai_parser
from services.scraper.core.parser import (
    build_location_text,
    extract_dates_from_cell,
    parse_street_with_house_numbers,
    parse_village_and_streets,
    parse_xlsx,
)


class TestParseVillageAndStreets:
    """Test parse_village_and_streets function"""

    def test_simple_village(self):
        """Test simple village name"""
        result = parse_village_and_streets("Aleksandravas")
        assert result == [("Aleksandravas", None)]

    def test_village_with_streets(self):
        """Test village with streets in parentheses"""
        result = parse_village_and_streets("Avižieniai (Akacijų aklg., Avižų g.)")
        assert len(result) == 3  # Village + 2 streets
        assert result[0] == ("Avižieniai", None)
        assert ("Akacijų aklg.", None) in result
        assert ("Avižų g.", None) in result

    def test_empty_string(self):
        """Test empty string"""
        result = parse_village_and_streets("")
        assert result == []

    def test_none_value(self):
        """Test None value"""
        import pandas as pd

        result = parse_village_and_streets(pd.NA)
        assert result == []


class TestParseStreetWithHouseNumbers:
    """Test parse_street_with_house_numbers function"""

    def test_simple_street(self):
        """Test street without house numbers"""
        street, house_nums = parse_street_with_house_numbers("Akacijų aklg.")
        assert street == "Akacijų aklg."
        assert house_nums is None

    def test_street_with_explicit_numbers(self):
        """Test street with explicit house numbers (simple list, not ranges)"""
        street, house_nums = parse_street_with_house_numbers("Sudervės g. 26, 28")
        assert street == "Sudervės g."
        assert house_nums == "26, 28"

    def test_street_with_range_should_use_ai(self):
        """Test that streets with ranges (nuo...iki) are flagged for AI parser"""
        # This case contains a range that needs expansion: 40, 41, 42, ..., 48
        test_str = "Molėtų g.,(nuo Nr. 40 iki 48)"

        # Should be flagged for AI parser (not handled by traditional parser)
        assert should_use_ai_parser(test_str), (
            "Range 'nuo Nr. 40 iki 48' should be flagged for AI parser"
        )

        # Traditional parser just extracts the raw string, doesn't expand the range
        # This is why it needs AI - to expand "nuo Nr. 40 iki 48" to [40, 41, 42, ..., 48]
        street, house_nums = parse_street_with_house_numbers(test_str)
        assert street == "Molėtų g."
        assert house_nums == "nuo Nr. 40 iki 48"  # Raw string, NOT expanded


class TestExtractDatesFromCell:
    """Test extract_dates_from_cell function"""

    def test_single_date(self):
        """Test cell with single date"""
        dates = extract_dates_from_cell("8 d.", "Sausio", 2026)
        assert dates == [date(2026, 1, 8)]

    def test_multiple_dates(self):
        """Test cell with multiple dates"""
        dates = extract_dates_from_cell("8 d., 22 d.", "Sausio", 2026)
        assert set(dates) == {date(2026, 1, 8), date(2026, 1, 22)}

    def test_three_dates(self):
        """Test cell with three dates"""
        dates = extract_dates_from_cell("2 d., 16 d., 30 d.", "Balandžio", 2026)
        assert set(dates) == {date(2026, 4, 2), date(2026, 4, 16), date(2026, 4, 30)}

    def test_empty_cell(self):
        """Test empty cell"""
        dates = extract_dates_from_cell("", "Sausio", 2026)
        assert dates == []

    def test_none_value(self):
        """Test None value"""
        import pandas as pd

        dates = extract_dates_from_cell(pd.NA, "Sausio", 2026)
        assert dates == []

    def test_nominative_month_name_without_day_space(self):
        """Test newer XLSX month headers and compact day format."""
        dates = extract_dates_from_cell("9d., 23d.,", "Liepa", 2026)
        assert set(dates) == {date(2026, 7, 9), date(2026, 7, 23)}


class TestParseXlsx:
    """Test full XLSX layout handling."""

    def test_build_location_text_uses_gatve_when_kaimai_empty(self):
        """If Kaimai is empty, Gatvė is the source for village + streets."""
        import pandas as pd

        row = pd.Series({"Kaimai": None, "Gatvė": "Didžioji Riešė (Alyvų g., Parko g.)"})

        assert build_location_text(row) == "Didžioji Riešė (Alyvų g., Parko g.)"

    def test_build_location_text_merges_kaimai_and_gatve(self):
        """If Kaimai has village and Gatvė has street payload, compose one parser input."""
        import pandas as pd

        row = pd.Series({"Kaimai": "Didžioji Riešė", "Gatvė": "Alyvų g., Ateities g."})

        assert build_location_text(row) == "Didžioji Riešė (Alyvų g., Ateities g.)"

    def test_build_location_text_keeps_kaimai_when_gatve_empty(self):
        """If they restore the old layout, Kaimai remains the source."""
        import pandas as pd

        row = pd.Series({"Kaimai": "Aleksandravas", "Gatvė": None})

        assert build_location_text(row) == "Aleksandravas"

    def test_build_location_text_does_not_duplicate_prefixed_gatve(self):
        """If Gatvė already includes the village, use it as-is."""
        import pandas as pd

        row = pd.Series(
            {
                "Kaimai": "Didžioji Riešė",
                "Gatvė": "Didžioji Riešė (Alyvų g., Ateities g.)",
            }
        )

        assert build_location_text(row) == "Didžioji Riešė (Alyvų g., Ateities g.)"

    def test_uses_gatve_when_kaimai_column_is_empty(self, tmp_path):
        """Newer XLSX files put location text in Gatvė while Kaimai is blank."""
        import pandas as pd

        file_path = tmp_path / "schedule.xlsx"
        df = pd.DataFrame(
            [
                {
                    "Seniūnija": "Avižienių",
                    "Kaimai": None,
                    "Gatvė": "Aleksandravas",
                    "Savaitės diena": "Ketvirtadienis",
                    "Birželis": "11 d., 25 d.",
                    "Liepa": "9d., 23d.,",
                    "Rugpjūtis": "",
                    "Rugsėjis": "",
                    "Spalis": "",
                    "Lapkritis": "",
                    "Gruodis": "",
                }
            ]
        )
        with pd.ExcelWriter(file_path) as writer:
            df.to_excel(writer, index=False, startrow=1)

        results = parse_xlsx(file_path, year=2026, skip_ai=True)

        assert len(results) == 1
        assert results[0]["seniunija"] == "Avižienių"
        assert results[0]["village"] == "Aleksandravas"
        assert results[0]["street"] == ""
        assert set(results[0]["dates"]) == {
            date(2026, 6, 11),
            date(2026, 6, 25),
            date(2026, 7, 9),
            date(2026, 7, 23),
        }

    def test_merges_kaimai_and_gatve_street_payload(self, tmp_path):
        """New XLSX variants may split village into Kaimai and streets into Gatvė."""
        import pandas as pd

        file_path = tmp_path / "schedule.xlsx"
        df = pd.DataFrame(
            [
                {
                    "Seniūnija": "Riešės",
                    "Kaimai": "Didžioji Riešė",
                    "Gatvė": "Alyvų g., Ateities g.",
                    "Savaitės diena": "Ketvirtadienis",
                    "Birželis": "",
                    "Liepa": "9d., 23d.,",
                    "Rugpjūtis": "",
                    "Rugsėjis": "",
                    "Spalis": "",
                    "Lapkritis": "",
                    "Gruodis": "",
                }
            ]
        )
        with pd.ExcelWriter(file_path) as writer:
            df.to_excel(writer, index=False, startrow=1)

        results = parse_xlsx(file_path, year=2026, skip_ai=True)

        assert len(results) == 2
        assert {result["village"] for result in results} == {"Didžioji Riešė"}
        assert {result["street"] for result in results} == {"Alyvų g.", "Ateities g."}
        assert {result["kaimai_str"] for result in results} == {
            "Didžioji Riešė (Alyvų g., Ateities g.)"
        }
