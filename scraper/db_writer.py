"""
Database writer module - Writes validated data to SQLite
"""
import sqlite3
from pathlib import Path
from typing import List, Dict, Optional
from datetime import datetime
import json
from database.init import get_db_connection

def find_or_create_schedule_group(conn: sqlite3.Connection, dates: List) -> int:
    """
    Find existing schedule group with same dates, or create new one
    
    Args:
        conn: Database connection
        dates: List of date objects
    
    Returns:
        schedule_group_id
    """
    cursor = conn.cursor()
    
    # Convert dates to sorted list of date strings for comparison
    date_strs = sorted([d.isoformat() if hasattr(d, 'isoformat') else str(d) for d in dates])
    date_str = ','.join(date_strs)
    
    # Check existing schedule groups by comparing date sets
    # Get all schedule groups with their dates
    cursor.execute("""
        SELECT sg.id, GROUP_CONCAT(pd.date ORDER BY pd.date)
        FROM schedule_groups sg
        JOIN locations l ON l.schedule_group_id = sg.id
        JOIN pickup_dates pd ON pd.location_id = l.id
        WHERE pd.waste_type = 'bendros'
        GROUP BY sg.id
    """)
    
    for row in cursor.fetchall():
        group_id, group_dates = row
        if group_dates == date_str:
            return group_id
    
    # Create new schedule group
    cursor.execute("INSERT INTO schedule_groups DEFAULT VALUES")
    return cursor.lastrowid

def write_location_schedule(conn: sqlite3.Connection, village: str, street: str, dates: List, schedule_group_id: Optional[int] = None) -> int:
    """
    Write or update location and its pickup dates
    
    Args:
        conn: Database connection
        village: Village name
        street: Street name
        dates: List of date objects
        schedule_group_id: Optional schedule group ID (will be found/created if None)
    
    Returns:
        location_id
    """
    cursor = conn.cursor()
    
    # Find or create schedule group
    if schedule_group_id is None:
        schedule_group_id = find_or_create_schedule_group(conn, dates)
    
    # Insert or update location
    cursor.execute("""
        INSERT INTO locations (village, street, schedule_group_id, updated_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(village, street) 
        DO UPDATE SET schedule_group_id = ?, updated_at = ?
    """, (village, street, schedule_group_id, datetime.now(), schedule_group_id, datetime.now()))
    
    location_id = cursor.lastrowid
    if location_id == 0:
        # Location already exists, get its ID
        cursor.execute("SELECT id FROM locations WHERE village = ? AND street = ?", (village, street))
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
                item['village'],
                item['street'],
                item['dates']
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
