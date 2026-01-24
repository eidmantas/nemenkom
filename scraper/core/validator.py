"""
Validator module - Validates xlsx structure and parsed data
"""
import pandas as pd
from pathlib import Path
from typing import List, Dict, Tuple
from scraper.core.parser import parse_xlsx, MONTH_MAPPING

def validate_xlsx_structure(file_path: Path) -> Tuple[bool, List[str]]:
    """
    Validate that xlsx has expected structure
    
    Args:
        file_path: Path to xlsx file
    
    Returns:
        Tuple of (is_valid, list_of_errors)
    """
    errors = []
    
    try:
        df = pd.read_excel(file_path, skiprows=1)
    except Exception as e:
        return (False, [f"Failed to read xlsx: {str(e)}"])
    
    # Check for required columns
    required_columns = ['Seniūnija', 'Kaimai']
    missing_columns = [col for col in required_columns if col not in df.columns]
    if missing_columns:
        errors.append(f"Required columns not found: {missing_columns}")
    
    # Check for month columns
    month_columns = [col for col in df.columns if col in MONTH_MAPPING]
    if not month_columns:
        errors.append("No valid month columns found (expected Lithuanian month names)")
    else:
        # Check that we have reasonable number of month columns
        if len(month_columns) < 6:
            errors.append(f"Only {len(month_columns)} month columns found, expected at least 6")
    
    # Check that dataframe is not empty
    if len(df) == 0:
        errors.append("Dataframe is empty")
    
    # Check that 'Kaimai' column has some non-null values
    if 'Kaimai' in df.columns:
        non_null_count = df['Kaimai'].notna().sum()
        if non_null_count == 0:
            errors.append("'Kaimai' column has no non-null values")
    
    return (len(errors) == 0, errors)

def validate_parsed_data(parsed_data: List[Dict]) -> Tuple[bool, List[str]]:
    """
    Validate parsed data structure and content
    
    More lenient validation - warns about issues but doesn't fail on minor problems
    
    Args:
        parsed_data: List of parsed location dictionaries
    
    Returns:
        Tuple of (is_valid, list_of_warnings_or_errors)
    """
    warnings = []
    critical_errors = []
    
    if not parsed_data:
        critical_errors.append("No locations parsed from xlsx")
        return (False, critical_errors)
    
    # Check structure
    required_keys = ['seniunija', 'village', 'street', 'dates']
    locations_with_dates = 0
    locations_without_dates = 0
    
    for i, item in enumerate(parsed_data):
        # Check required keys
        for key in required_keys:
            if key not in item:
                critical_errors.append(f"Item {i} missing required key: {key}")
        
        # Validate seniunija is not empty
        if not item.get('seniunija', '').strip():
            critical_errors.append(f"Item {i} has empty seniunija")
        
        # Validate village is not empty
        if not item.get('village', '').strip():
            critical_errors.append(f"Item {i} has empty village")
        
        # Street can be empty (means whole village), but must be present
        if 'street' not in item:
            critical_errors.append(f"Item {i} missing 'street' key (can be empty string)")
        
        # Validate dates
        dates = item.get('dates', [])
        if not isinstance(dates, list):
            critical_errors.append(f"Item {i} dates is not a list")
        elif len(dates) == 0:
            locations_without_dates += 1
            # Warning - location has no pickup dates
            street_display = item.get('street', '') or '(visas kaimas)'
            warnings.append(f"Item {i} ({item.get('village', '?')} / {street_display}) has no pickup dates")
        else:
            locations_with_dates += 1
    
    # Check for reasonable number of locations
    if len(parsed_data) < 1:
        critical_errors.append("Too few locations parsed (expected at least 1)")
    
    # Warn if many locations have no dates
    if locations_without_dates > 0:
        warnings.append(f"{locations_without_dates} locations have no pickup dates (out of {len(parsed_data)} total)")
    
    # Return warnings and errors together
    all_issues = critical_errors + warnings
    is_valid = len(critical_errors) == 0
    
    return (is_valid, all_issues)

def validate_file_and_data(file_path: Path, year: int = 2026, skip_ai: bool = False) -> Tuple[bool, List[str], List[Dict]]:
    """
    Complete validation: structure + parsed data
    
    Args:
        file_path: Path to xlsx file
        year: Year for parsing
        skip_ai: If True, skip AI parsing (use traditional parser only). Default: False (AI enabled)
    
    Returns:
        Tuple of (is_valid, list_of_errors, parsed_data)
    """
    all_errors = []
    
    # Validate structure
    struct_valid, struct_errors = validate_xlsx_structure(file_path)
    all_errors.extend(struct_errors)
    
    if not struct_valid:
        return (False, all_errors, [])
    
    # Parse and validate data
    try:
        parsed_data = parse_xlsx(file_path, year, skip_ai=skip_ai)
        data_valid, data_errors = validate_parsed_data(parsed_data)
        all_errors.extend(data_errors)
        
        return (data_valid, all_errors, parsed_data)
    except Exception as e:
        all_errors.append(f"Parsing failed: {str(e)}")
        return (False, all_errors, [])

if __name__ == '__main__':
    # Test validator
    from fetcher import fetch_xlsx
    file_path = fetch_xlsx()
    is_valid, errors, data = validate_file_and_data(file_path)
    print(f"Valid: {is_valid}")
    if errors:
        print(f"Errors: {errors}")
    else:
        print(f"Successfully validated {len(data)} locations")
