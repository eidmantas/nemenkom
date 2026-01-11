"""
Parser module - Extracts street/village and date information from xlsx
"""
import pandas as pd
from pathlib import Path
from typing import List, Dict, Tuple
import re
import datetime

# Lithuanian month names
MONTH_MAPPING = {
    "Sausis": 1,
    "Vasaris": 2,
    "Kovas": 3,
    "Balandis": 4,
    "Gegužė": 5,
    "Birželis": 6,
    "Liepa": 7,
    "Rugpjūtis": 8,
    "Rugsėjis": 9,
    "Spalis": 10,
    "Lapkritis": 11,
    "Gruodis": 12,
}

def parse_street_village(location_str: str) -> Tuple[str, str]:
    """
    Parse street and village from location string
    Format appears to be like: "Vanaginės g., Kaimas" or similar
    
    Args:
        location_str: String containing street and village info
    
    Returns:
        Tuple of (village, street)
    """
    if pd.isna(location_str) or not location_str:
        return ("", "")
    
    # Try to split by comma
    parts = [p.strip() for p in str(location_str).split(',')]
    
    if len(parts) >= 2:
        street = parts[0].strip()
        village = parts[1].strip()
    elif len(parts) == 1:
        # Only street provided, no village
        street = parts[0].strip()
        village = ""
    else:
        street = str(location_str).strip()
        village = ""
    
    return (village, street)

def extract_dates_from_cell(cell_value, month_name: str, year: int = 2026) -> List[datetime.date]:
    """
    Extract dates from a single cell value
    
    Args:
        cell_value: Cell value (string or number)
        month_name: Lithuanian month name
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
    
    # Find all numbers in the string
    numbers = re.findall(r'(\d+)', str(cell_value))
    for num_str in numbers:
        try:
            day = int(num_str)
            # Validate day is in valid range for month
            if 1 <= day <= 31:
                try:
                    date_obj = datetime.date(year, month_num, day)
                    dates.append(date_obj)
                except ValueError:
                    # Invalid date (e.g., Feb 30)
                    continue
        except ValueError:
            continue
    
    return sorted(set(dates))  # Remove duplicates and sort

def parse_xlsx(file_path: Path, year: int = 2026) -> List[Dict]:
    """
    Parse xlsx file and extract all location schedules
    
    Args:
        file_path: Path to xlsx file
        year: Year for the schedule
    
    Returns:
        List of dictionaries with structure:
        {
            'village': str,
            'street': str,
            'dates': List[datetime.date]
        }
    """
    print(f"Parsing xlsx file: {file_path}")
    
    # Read excel file, skip first row (header)
    df = pd.read_excel(file_path, skiprows=1)
    
    # Check if required column exists
    if 'Kaimai' not in df.columns:
        raise ValueError("Required column 'Kaimai' not found in xlsx")
    
    results = []
    month_columns = [col for col in df.columns if col in MONTH_MAPPING]
    
    if not month_columns:
        raise ValueError("No valid month columns found in xlsx")
    
    print(f"Found {len(df)} rows and {len(month_columns)} month columns")
    
    # Process each row
    for idx, row in df.iterrows():
        location_str = row.get('Kaimai', '')
        village, street = parse_street_village(location_str)
        
        if not street:  # Skip rows without street info
            continue
        
        # Extract dates from all month columns
        all_dates = []
        for month_name in month_columns:
            month_cell_value = row[month_name]
            dates = extract_dates_from_cell(month_cell_value, month_name, year)
            all_dates.extend(dates)
        
        if all_dates:
            results.append({
                'village': village,
                'street': street,
                'dates': sorted(set(all_dates))  # Remove duplicates and sort
            })
    
    print(f"Parsed {len(results)} locations")
    return results

if __name__ == '__main__':
    # Test parser
    from fetcher import fetch_xlsx
    file_path = fetch_xlsx()
    results = parse_xlsx(file_path)
    print(f"\nSample results:")
    for result in results[:3]:
        print(f"  {result['village']} / {result['street']}: {len(result['dates'])} dates")
