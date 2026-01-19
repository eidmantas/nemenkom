"""
Unit tests for parser functions
"""
from datetime import date
from scraper.core.parser import (
    parse_village_and_streets,
    parse_street_with_house_numbers,
    extract_dates_from_cell
)
from scraper.ai.router import should_use_ai_parser


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
        assert should_use_ai_parser(test_str) == True, \
            "Range 'nuo Nr. 40 iki 48' should be flagged for AI parser"
        
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
