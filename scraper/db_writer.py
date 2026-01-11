"""
Database writer module - Writes validated data to SQLite
"""
import sqlite3
from pathlib import Path
from typing import List, Dict, Optional
from datetime import datetime, date
import json
from database.init import get_db_connection

def find_or_create_schedule_group(conn: sqlite3.Connection, dates: List) -> int:
    """
    Find existing schedule group with same dates, or create new one
    
    Compares by checking if any existing group has the same date set
    
    Args:
        conn: Database connection
        dates: List of date objects
    
    Returns:
        schedule_group_id
    """
    cursor = conn.cursor()
    
    if not dates:
        first_date = None
        last_date = None
        date_count = 0
    else:
        first_date = min(dates).isoformat()
        last_date = max(dates).isoformat()
        date_count = len(dates)
    
    # Convert dates to sorted string for comparison
    date_strs = sorted([d.isoformat() if isinstance(d, date) else str(d) for d in dates])
    date_str = ','.join(date_strs)
    
    # Check existing schedule groups by comparing date sets
    # Get all schedule groups with matching metadata first (quick filter)
    cursor.execute("""
        SELECT sg.id, GROUP_CONCAT(pd.date ORDER BY pd.date)
        FROM schedule_groups sg
        JOIN locations l ON l.schedule_group_id = sg.id
        JOIN pickup_dates pd ON pd.location_id = l.id
        WHERE pd.waste_type = 'bendros'
          AND sg.date_count = ?
          AND sg.first_date = ?
          AND sg.last_date = ?
        GROUP BY sg.id
    """, (date_count, first_date, last_date))
    
    # Check if date strings match
    for row in cursor.fetchall():
        group_id, group_dates = row
        if group_dates == date_str:
            return group_id
    
    # Create new schedule group
    cursor.execute("""
        INSERT INTO schedule_groups (first_date, last_date, date_count)
        VALUES (?, ?, ?)
    """, (first_date, last_date, date_count))
    
    return cursor.lastrowid

def write_location_schedule(conn: sqlite3.Connection, seniūnija: str, village: str, street: str, dates: List, house_numbers: Optional[str] = None, schedule_group_id: Optional[int] = None) -> int:
    """
    Write or update location and its pickup dates
    
    Args:
        conn: Database connection
        seniūnija: County/municipality name
        village: Village name
        street: Street name (empty string if whole village)
        dates: List of date objects
        house_numbers: Optional house number restrictions
        schedule_group_id: Optional schedule group ID (will be found/created if None)
    
    Returns:
        location_id
    """
    cursor = conn.cursor()
    
    # Find or create schedule group
    if schedule_group_id is None:
        schedule_group_id = find_or_create_schedule_group(conn, dates)
    
    # Normalize house_numbers (None -> NULL in DB)
    house_nums_str = house_numbers if house_numbers else None
    
    # Insert or update location
    cursor.execute("""
        INSERT INTO locations (seniūnija, village, street, house_numbers, schedule_group_id, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(seniūnija, village, street, house_numbers) 
        DO UPDATE SET schedule_group_id = ?, updated_at = ?
    """, (seniūnija, village, street, house_nums_str, schedule_group_id, datetime.now(), schedule_group_id, datetime.now()))
    
    location_id = cursor.lastrowid
    if location_id == 0:
        # Location already exists, get its ID
        cursor.execute("SELECT id FROM locations WHERE seniūnija = ? AND village = ? AND street = ? AND (house_numbers = ? OR (house_numbers IS NULL AND ? IS NULL))", 
                      (seniūnija, village, street, house_nums_str, house_nums_str))
        location_id = cursor.fetchone()[0]
    
    # Delete existing pickup dates for this location
    cursor.execute("DELETE FROM pickup_dates WHERE location_id = ?", (location_id,))
    
    # Insert new pickup dates
    for date in dates:
        date_str = date.isoformat() if hasattr(date, 'isoformat') else str(date)
        cursor.execute("""
            INSERT INTO pickup_dates (location_id, date, waste_type)
            VALUES (?, ?, 'bendros')
        """, (location_id, date_str))
    
    return location_id

def log_fetch(conn: sqlite3.Connection, source_url: str, status: str, validation_errors: Optional[List[str]] = None) -> int:
    """
    Log a data fetch attempt
    
    Args:
        conn: Database connection
        source_url: URL that was fetched
        status: 'success', 'failed', or 'validation_error'
        validation_errors: Optional list of validation error messages
    
    Returns:
        fetch_id
    """
    cursor = conn.cursor()
    errors_json = json.dumps(validation_errors) if validation_errors else None
    
    cursor.execute("""
        INSERT INTO data_fetches (source_url, status, validation_errors)
        VALUES (?, ?, ?)
    """, (source_url, status, errors_json))
    
    return cursor.lastrowid

def write_parsed_data(parsed_data: List[Dict], source_url: str, validation_errors: Optional[List[str]] = None) -> bool:
    """
    Write all parsed data to database
    
    Args:
        parsed_data: List of location dictionaries from parser
        source_url: URL that was fetched
        validation_errors: Optional list of validation errors
    
    Returns:
        True if successful, False otherwise
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # Start transaction
        conn.execute("BEGIN TRANSACTION")
        
        # Log fetch
        status = 'success' if not validation_errors else 'validation_error'
        fetch_id = log_fetch(conn, source_url, status, validation_errors)
        
        if validation_errors:
            conn.commit()
            return False
        
        # Write each location
        for item in parsed_data:
            write_location_schedule(
                conn,
                item.get('seniūnija', ''),
                item.get('village', ''),
                item.get('street', ''),
                item.get('dates', []),
                item.get('house_numbers')
            )
        
        conn.commit()
        print(f"Successfully wrote {len(parsed_data)} locations to database")
        return True
        
    except Exception as e:
        conn.rollback()
        print(f"Error writing to database: {e}")
        # Log failed fetch
        try:
            log_fetch(conn, source_url, 'failed', [str(e)])
            conn.commit()
        except:
            pass
        return False
    finally:
        conn.close()

if __name__ == '__main__':
    # Test db writer
    from fetcher import fetch_xlsx
    from validator import validate_file_and_data
    
    file_path = fetch_xlsx()
    source_url = 'https://www.nemenkom.lt/uploads/failai/atliekos/Buitini%C5%B3%20atliek%C5%B3%20surinkimo%20grafikai/2026%20m-%20sausio-bir%C5%BEelio%20m%C4%97n%20%20Buitini%C5%B3%20atliek%C5%B3%20surinkimo%20grafikas.xlsx'
    is_valid, errors, data = validate_file_and_data(file_path)
    
    if is_valid:
        success = write_parsed_data(data, source_url)
        print(f"Write successful: {success}")
    else:
        print(f"Validation failed: {errors}")
