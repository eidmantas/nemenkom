"""
Core scraper modules - no AI dependencies
"""

from services.scraper.core.db_writer import write_location_schedule, write_parsed_data
from services.scraper.core.fetcher import DEFAULT_URL, fetch_xlsx
from services.scraper.core.parser import (
    extract_dates_from_cell,
    parse_street_with_house_numbers,
    parse_village_and_streets,
    parse_xlsx,
)
from services.scraper.core.validator import validate_file_and_data, validate_parsed_data

__all__ = [
    "DEFAULT_URL",
    "extract_dates_from_cell",
    "fetch_xlsx",
    "parse_street_with_house_numbers",
    "parse_village_and_streets",
    "parse_xlsx",
    "validate_file_and_data",
    "validate_parsed_data",
    "write_location_schedule",
    "write_parsed_data",
]
