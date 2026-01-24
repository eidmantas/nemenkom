"""
Parser module - Extracts street/village and date information from xlsx
Handles hierarchical structure: Seniūnija -> Kaimai (with optional streets and house numbers)
"""
import pandas as pd
from pathlib import Path
from typing import List, Dict, Tuple, Optional
import re
import datetime

# Lithuanian month names (genitive case as they appear in column headers)
MONTH_MAPPING = {
    "Sausio": 1,
    "Vasario": 2,
    "Kovo": 3,
    "Balandžio": 4,
    "Gegužės": 5,
    "Birželio": 6,
    "Liepos": 7,
    "Rugpjūčio": 8,
    "Rugsėjo": 9,
    "Spalio": 10,
    "Lapkričio": 11,
    "Gruodžio": 12,
}

def parse_street_with_house_numbers(street_str: str) -> Tuple[str, Optional[str]]:
    """
    Parse street name and optional house number restrictions
    
    Handles various formats:
    - "Vanaginės g." -> ("Vanaginės g.", None)
    - "Molėtų g.,(nuo Nr. 40 iki 48)" -> ("Molėtų g.", "nuo Nr. 40 iki 48")
    - "Vanaginės g., (nuo Nr.1 iki 31A, nuo 2 iki 14B)" -> ("Vanaginės g.", "nuo Nr.1 iki 31A, nuo 2 iki 14B")
    - "Kaštonų g., (nuo Nr. 10)" -> ("Kaštonų g.", "nuo Nr. 10")
    - "Sudervės g. 26, 28" -> ("Sudervės g.", "26, 28")
    - "Parko g. 2 ,4, 4A, 6, 8" -> ("Parko g.", "2, 4, 4A, 6, 8")
    - "Ilgoji g.,nuo 18 iki 18U" -> ("Ilgoji g.", "nuo 18 iki 18U")
    
    Args:
        street_str: Street string that may contain house numbers
    
    Returns:
        Tuple of (street_name, house_numbers_string or None)
    """
    if not street_str or pd.isna(street_str):
        return ("", None)
    
    street_str = str(street_str).strip()
    
    # Pattern 1: Street with house numbers in parentheses at the end
    # e.g., "Molėtų g.,(nuo Nr. 40 iki 48)" or "Vanaginės g., (nuo Nr.1 iki 31A)"
    match = re.match(r'^(.+?)\s*,\s*\((.+)\)\s*$', street_str)
    if match:
        street = match.group(1).strip()
        house_nums = match.group(2).strip()
        return (street, house_nums if house_nums else None)
    
    # Pattern 2: Street with house numbers in parentheses (no comma before paren)
    # e.g., "Molėtų g. (nuo Nr. 32A iki 20, 20A, 22 )"
    match = re.match(r'^(.+?)\s+\((.+)\)\s*$', street_str)
    if match:
        street = match.group(1).strip()
        house_nums = match.group(2).strip()
        return (street, house_nums if house_nums else None)
    
    # Pattern 3: Street followed by numbers (no parentheses)
    # e.g., "Sudervės g. 26, 28" or "Parko g. 2 ,4, 4A, 6, 8"
    # Look for pattern: street name ending with "g." or similar, then numbers
    match = re.match(r'^(.+?\s+g\.?)\s+(.+)$', street_str)
    if match:
        street = match.group(1).strip()
        potential_nums = match.group(2).strip()
        # Check if it looks like house numbers (contains numbers, "nuo", "iki", "Nr", etc.)
        if re.search(r'\d|nuo|iki|Nr', potential_nums, re.IGNORECASE):
            return (street, potential_nums)
    
    # Pattern 4: Street with "nuo X iki Y" pattern (no parentheses)
    # e.g., "Ilgoji g.,nuo 18 iki 18U"
    match = re.match(r'^(.+?)\s*,\s*(nuo\s+.+)$', street_str, re.IGNORECASE)
    if match:
        street = match.group(1).strip()
        house_nums = match.group(2).strip()
        return (street, house_nums)
    
    # Pattern 5: Just street name, no house numbers
    return (street_str, None)

def parse_village_and_streets(kaimai_str: str) -> List[Tuple[str, Optional[str]]]:
    """
    Parse village name and list of streets (with optional house numbers) from Kaimai column
    
    Returns list of (street_name, house_numbers) tuples
    
    Args:
        kaimai_str: String from Kaimai column
    
    Returns:
        List of tuples: [(village_name, None), (street1, house_nums1), (street2, house_nums2), ...]
        First tuple is always (village_name, None)
    """
    if pd.isna(kaimai_str) or not kaimai_str:
        return []
    
    kaimai_str = str(kaimai_str).strip()
    
    # Check if there are streets in parentheses
    match = re.match(r'^(.+?)\s*\((.+)\)\s*$', kaimai_str)
    if match:
        village = match.group(1).strip()
        streets_str = match.group(2).strip()
        
        # Split by comma, but be careful with nested parentheses
        # Simple approach: split by comma, then parse each part
        parts = []
        current_part = ""
        paren_depth = 0
        
        for char in streets_str:
            if char == '(':
                paren_depth += 1
                current_part += char
            elif char == ')':
                paren_depth -= 1
                current_part += char
            elif char == ',' and paren_depth == 0:
                if current_part.strip():
                    parts.append(current_part.strip())
                current_part = ""
            else:
                current_part += char
        
        if current_part.strip():
            parts.append(current_part.strip())
        
        # Parse each street part
        streets = []
        for part in parts:
            street, house_nums = parse_street_with_house_numbers(part)
            if street:
                streets.append((street, house_nums))
        
        return [(village, None)] + streets
    else:
        # No parentheses - just village name, no individual streets
        return [(kaimai_str.strip(), None)]

def extract_dates_from_cell(cell_value, month_name: str, year: int = 2026) -> List[datetime.date]:
    """
    Extract dates from a single cell value
    Format: "8 d., 22 d." or "2 d., 16 d., 30 d." or just numbers
    
    Args:
        cell_value: Cell value (string like "8 d., 22 d.")
        month_name: Lithuanian month name (genitive)
        year: Year for the dates
    
    Returns:
        List of date objects
    """
    dates = []
    month_num = MONTH_MAPPING.get(month_name)
    
    if month_num is None:
        return dates
    
    if pd.isna(cell_value):
        return dates
    
    cell_str = str(cell_value).strip()
    if not cell_str:
        return dates
    
    # Pattern to match "8 d." or just "8" or "8," etc.
    # Match numbers followed by optional " d." or "d." or comma/space
    pattern = r'(\d+)\s*(?:d\.|d|,)?\s*'
    matches = re.findall(pattern, cell_str)
    
    for match in matches:
        try:
            day = int(match[0] if isinstance(match, tuple) else match)
            # Validate day is in valid range
            if 1 <= day <= 31:
                try:
                    date_obj = datetime.date(year, month_num, day)
                    dates.append(date_obj)
                except ValueError:
                    # Invalid date (e.g., Feb 30, Apr 31)
                    continue
        except (ValueError, IndexError):
            continue
    
    return sorted(set(dates))  # Remove duplicates and sort

def parse_xlsx(file_path: Path, year: int = 2026, skip_ai: bool = False) -> List[Dict]:
    """
    Parse xlsx file and extract all location schedules
    
    Handles:
    - Seniūnija (county) - merged cells, tracked per row
    - Kaimai (village) - can have streets in parentheses with house numbers
    - Month columns with dates in format "8 d., 22 d."
    
    Args:
        file_path: Path to xlsx file
        year: Year for the schedule
        skip_ai: If True, skip AI parsing (use traditional parser only). Default: False (AI enabled)
    
    Returns:
        List of dictionaries with structure:
        {
            'seniunija': str,      # County name
            'village': str,        # Village name
            'street': str,          # Street name (empty if village has no street list)
            'house_numbers': str,   # House number restrictions (None if not specified)
            'dates': List[datetime.date]
        }
    """
    print(f"Parsing xlsx file: {file_path}")
    if skip_ai:
        print("🔍 Filtering: Skipping AI parsing (traditional parser only)")
    
    # Read excel file, skip first row (header)
    df = pd.read_excel(file_path, skiprows=1)
    
    # Check required columns
    required_columns = ['Seniūnija', 'Kaimai']
    missing_columns = [col for col in required_columns if col not in df.columns]
    if missing_columns:
        raise ValueError(f"Required columns not found: {missing_columns}")
    
    # Find month columns
    month_columns = [col for col in df.columns if col in MONTH_MAPPING]
    if not month_columns:
        raise ValueError("No valid month columns found in xlsx")
    
    print(f"Found {len(df)} rows, {len(month_columns)} month columns")
    
    # Import parser_router for skip_ai filtering and AI parsing
    from scraper.ai.router import should_use_ai_parser
    import logging
    import time
    logging.basicConfig(level=logging.DEBUG, format='[%(asctime)s] %(levelname)s: %(message)s')
    logger = logging.getLogger(__name__)
    
    results = []
    current_seniunija = None  # Track current county (handles merged cells)
    skipped_count = 0
    ai_parse_count = 0
    traditional_parse_count = 0
    parse_start_time = time.time()
    
    logger.info(f"Starting to parse {len(df)} rows...")
    
    # Process each row
    for idx, row in df.iterrows():
        if (idx + 1) % 50 == 0:
            elapsed = time.time() - parse_start_time
            logger.debug(f"Processing row {idx + 1}/{len(df)} (elapsed: {elapsed:.1f}s, AI: {ai_parse_count}, Traditional: {traditional_parse_count})")
        # Handle Seniūnija (county) - can be merged, so track current value
        seniunija_value = row.get('Seniūnija', '')
        if pd.notna(seniunija_value) and str(seniunija_value).strip():
            current_seniunija = str(seniunija_value).strip()
        
        # Skip if no county (shouldn't happen, but be safe)
        if not current_seniunija:
            continue
        
        # Parse Kaimai (village and streets)
        kaimai_value = row.get('Kaimai', '')
        if pd.isna(kaimai_value):
            continue
        
        # Convert to string once and check if empty
        kaimai_str = str(kaimai_value).strip()
        if not kaimai_str:
            continue
        
        # Filter by skip_ai flag (inverted logic)
        if skip_ai:
            if should_use_ai_parser(kaimai_str):
                skipped_count += 1
                continue
        
        # Route to appropriate parser
        if should_use_ai_parser(kaimai_str):
            # Use AI parser for complex cases
            ai_start = time.time()
            logger.debug(f"Row {idx + 1}: Using AI parser for: {kaimai_str[:80]}")
            try:
                from scraper.ai.parser import parse_with_ai
                parsed_items = parse_with_ai(kaimai_str)
                ai_parse_count += 1
                ai_time = time.time() - ai_start
                if ai_time > 1.0:
                    logger.warning(f"AI parse took {ai_time:.2f}s for: {kaimai_str[:50]}")
                else:
                    logger.debug(f"AI parse completed in {ai_time:.2f}s")
            except Exception as e:
                # Fallback to traditional parser if AI fails
                logger.warning(f"AI parser failed for '{kaimai_str[:50]}...': {e}, falling back")
                print(f"⚠️  AI parser failed for '{kaimai_str[:50]}...': {e}")
                print(f"   Falling back to traditional parser")
                parsed_items = parse_village_and_streets(kaimai_str)
                traditional_parse_count += 1
        else:
            # Use traditional parser for simple cases
            logger.debug(f"Row {idx + 1}: Using traditional parser for: {kaimai_str[:80]}")
            parsed_items = parse_village_and_streets(kaimai_str)
            traditional_parse_count += 1
            
            # Validate traditional parser output - if village contains complex patterns, retry with AI
            if parsed_items:
                village = parsed_items[0][0] if parsed_items else ""
                # Check if village field contains street-like patterns (indicates parsing failure)
                # Patterns like: parentheses with streets, multiple "g." endings, complex structures
                if village and (
                    '(' in village and 'g.' in village or  # Village contains parentheses with streets
                    village.count('g.') > 1 or  # Multiple street endings in village
                    (',' in village and 'g.' in village and not village.strip().startswith('('))  # Streets mixed in village
                ):
                    logger.warning(f"Traditional parser produced suspicious village '{village[:50]}...' - retrying with AI")
                    print(f"⚠️  Traditional parser produced invalid output for '{kaimai_str[:50]}...' - retrying with AI")
                    try:
                        from scraper.ai.parser import parse_with_ai
                        parsed_items = parse_with_ai(kaimai_str)
                        ai_parse_count += 1
                        traditional_parse_count -= 1  # Adjust counts
                        logger.debug(f"AI retry successful for: {kaimai_str[:80]}")
                    except Exception as e:
                        logger.warning(f"AI retry also failed for '{kaimai_str[:50]}...': {e}, skipping this entry")
                        print(f"⚠️  AI retry also failed for '{kaimai_str[:50]}...', skipping this malformed entry")
                        parsed_items = []  # Skip this entry - don't write bad data
        
        if not parsed_items:
            continue
        
        village = parsed_items[0][0]  # First item is always village
        if not village:
            continue
        
        # Extract dates from all month columns
        all_dates = []
        for month_name in month_columns:
            month_cell_value = row[month_name]
            dates = extract_dates_from_cell(month_cell_value, month_name, year)
            all_dates.extend(dates)
        
        # If no dates found, skip this location
        if not all_dates:
            continue
        
        all_dates = sorted(set(all_dates))  # Remove duplicates and sort
        
        # Create entries based on parsed items
        # First item is village, rest are streets
        # Store original kaimai_str for hash generation
        if len(parsed_items) == 1:
            # No street list - just village entry
            results.append({
                'seniunija': current_seniunija,
                'village': village,
                'street': '',  # Empty street means whole village
                'house_numbers': None,
                'dates': all_dates,
                'kaimai_str': kaimai_str  # Original Kaimai string for hash
            })
        else:
            # Multiple streets - create entry for each street
            # All streets share the same kaimai_str (from the parent row)
            for street, house_nums in parsed_items[1:]:  # Skip first (village)
                if street:  # Only add if street name is not empty
                    results.append({
                        'seniunija': current_seniunija,
                        'village': village,
                        'street': street,
                        'house_numbers': house_nums,
                        'dates': all_dates,
                        'kaimai_str': kaimai_str  # Original Kaimai string for hash
                    })
    
    total_time = time.time() - parse_start_time
    logger.info(f"Parsing complete: {len(results)} entries in {total_time:.1f}s (AI: {ai_parse_count}, Traditional: {traditional_parse_count}, Skipped: {skipped_count})")
    if skip_ai and skipped_count > 0:
        print(f"Parsed {len(results)} location entries (skipped {skipped_count} AI-needed entries) in {total_time:.1f}s")
    else:
        print(f"Parsed {len(results)} location entries in {total_time:.1f}s")
    return results

if __name__ == '__main__':
    # Test parser
    from scraper.core.fetcher import fetch_xlsx
    file_path = fetch_xlsx()
    results = parse_xlsx(file_path)
    print(f"\nSample results (first 5):")
    for result in results[:5]:
        street_display = result['street'] if result['street'] else "(visas kaimas)"
        house_display = f" [{result['house_numbers']}]" if result['house_numbers'] else ""
        print(f"  {result['seniunija']} / {result['village']} / {street_display}{house_display}: {len(result['dates'])} dates")
