"""
Validator module - Validates xlsx structure and parsed data
"""
import pandas as pd
from pathlib import Path
from typing import List, Dict, Tuple
from scraper.parser import parse_xlsx, MONTH_MAPPING

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
    
    # Check for required column
    if 'Kaimai' not in df.columns:
        errors.append("Required column 'Kaimai' not found")
    
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
    
    Args:
        parsed_data: List of parsed location dictionaries
    
    Returns:
        Tuple of (is_valid, list_of_errors)
    """
    errors = []
    
    if not parsed_data:
        errors.append("No locations parsed from xlsx")
        return (False, errors)
    
    # Check structure
    required_keys = ['village', 'street', 'dates']
    for i, item in enumerate(parsed_data):
        for key in required_keys:
            if key not in item:
                errors.append(f"Item {i} missing required key: {key}")
        
        # Validate street is not empty
        if not item.get('street', '').strip():
            errors.append(f"Item {i} has empty street")
        
        # Validate dates
        dates = item.get('dates', [])
        if not isinstance(dates, list):
            errors.append(f"Item {i} dates is not a list")
        elif len(dates) == 0:
            # Warning but not error - some locations might have no dates
            pass
    
    # Check for reasonable number of locations
    if len(parsed_data) < 1:
        errors.append("Too few locations parsed (expected at least 1)")
    
    return (len(errors) == 0, errors)

def validate_file_and_data(file_path: Path, year: int = 2026) -> Tuple[bool, List[str], List[Dict]]:
    """
    Complete validation: structure + parsed data
    
    Args:
        file_path: Path to xlsx file
        year: Year for parsing
    
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
        parsed_data = parse_xlsx(file_path, year)
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
