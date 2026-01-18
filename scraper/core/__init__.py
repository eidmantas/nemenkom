"""
Core scraper modules - no AI dependencies
"""
from scraper.core.fetcher import fetch_xlsx, DEFAULT_URL
from scraper.core.parser import parse_xlsx, parse_village_and_streets, parse_street_with_house_numbers, extract_dates_from_cell
from scraper.core.validator import validate_file_and_data, validate_parsed_data
from scraper.core.db_writer import write_parsed_data, write_location_schedule

__all__ = [
    'fetch_xlsx', 'DEFAULT_URL',
    'parse_xlsx', 'parse_village_and_streets', 'parse_street_with_house_numbers', 'extract_dates_from_cell',
    'validate_file_and_data', 'validate_parsed_data',
    'write_parsed_data', 'write_location_schedule',
]
