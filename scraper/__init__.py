"""
Scraper module for fetching and processing waste schedule data

Structure:
- core/     - Core scraping logic (no AI dependencies)
- ai/       - AI parser and Groq integration
"""
# Re-export core modules for backward compatibility
from scraper.core import (
    fetch_xlsx, DEFAULT_URL,
    parse_xlsx, parse_village_and_streets, parse_street_with_house_numbers, extract_dates_from_cell,
    validate_file_and_data, validate_parsed_data,
    write_parsed_data, write_location_schedule,
)

# Re-export AI modules
from scraper.ai import (
    should_use_ai_parser,
    get_rate_limiter, GroqRateLimiter,
    get_cache, AIParserCache,
    parse_with_ai,
)
