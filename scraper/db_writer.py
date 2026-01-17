"""
Database writer module - Writes validated data to SQLite
"""
import sqlite3
from pathlib import Path
from typing import List, Dict, Optional
from datetime import datetime, date
import json
import hashlib
from database.init import get_db_connection

def generate_kaimai_hash(kaimai_str: str) -> str:
    """Generate hash for Kaimai column"""
    hash_obj = hashlib.sha256(kaimai_str.encode())
    return f"k1_{hash_obj.hexdigest()[:12]}"

def generate_schedule_group_id(dates: List[date], waste_type: str = 'bendros') -> str:
    """Generate hash-based schedule group ID"""
    if not dates:
        date_str = ''
    else:
        date_str = ','.join(sorted([d.isoformat() if isinstance(d, date) else str(d) for d in dates]))
    combined = f"{waste_type}:{date_str}"
    hash_obj = hashlib.sha256(combined.encode())
    hash_hex = hash_obj.hexdigest()[:12]
    return f"sg_{hash_hex}"

def find_or_create_schedule_group(conn: sqlite3.Connection, dates: List, waste_type: str, kaimai_hash: str) -> str:
    """
    Find existing schedule group with same dates, or create new one
    Uses hash-based ID for deterministic grouping
    
    Args:
        conn: Database connection
        dates: List of date objects
        waste_type: Waste type ('bendros', 'plastikas', etc.)
        kaimai_hash: Hash of original Kaimai string
    
    Returns:
        schedule_group_id (hash-based string like "sg_a3f8b2c1d4e5")
    """
    schedule_group_id = generate_schedule_group_id(dates, waste_type)
    cursor = conn.cursor()
    
    # Check if schedule group exists
    cursor.execute("SELECT kaimai_hashes FROM schedule_groups WHERE id = ?", (schedule_group_id,))
    row = cursor.fetchone()
    
    if row:
        # Update kaimai_hashes (add this hash if not present)
        existing_hashes = json.loads(row[0] or '[]')
        if kaimai_hash not in existing_hashes:
            existing_hashes.append(kaimai_hash)
            cursor.execute("""
                UPDATE schedule_groups 
                SET kaimai_hashes = json(?)
                WHERE id = ?
            """, (json.dumps(existing_hashes), schedule_group_id))
    else:
        # Create new schedule group
        if not dates:
            first_date = None
            last_date = None
            date_count = 0
        else:
            first_date = min(dates).isoformat()
            last_date = max(dates).isoformat()
            date_count = len(dates)
        
        # Convert dates to JSON array
        dates_json = json.dumps([d.isoformat() if isinstance(d, date) else str(d) for d in sorted(dates)])
        
        cursor.execute("""
            INSERT INTO schedule_groups (id, waste_type, first_date, last_date, date_count, dates, kaimai_hashes)
            VALUES (?, ?, ?, ?, ?, json(?), json(?))
        """, (schedule_group_id, waste_type, first_date, last_date, date_count, dates_json, json.dumps([kaimai_hash])))
    
    return schedule_group_id

def write_location_schedule(conn: sqlite3.Connection, seniūnija: str, village: str, street: str, dates: List, kaimai_str: str, house_numbers: Optional[str] = None, waste_type: str = 'bendros') -> int:
    """
    Write or update location and its pickup dates
    
    Args:
        conn: Database connection
        seniūnija: County/municipality name
        village: Village name
        street: Street name (empty string if whole village)
        dates: List of date objects
        kaimai_str: Original Kaimai string (for hash generation)
        house_numbers: Optional house number restrictions
        waste_type: Waste type ('bendros', 'plastikas', etc.)
    
    Returns:
        location_id
    """
    cursor = conn.cursor()
    
    # Generate kaimai_hash
    kaimai_hash = generate_kaimai_hash(kaimai_str)
    
    # Find or create schedule group (updates kaimai_hashes)
    schedule_group_id = find_or_create_schedule_group(conn, dates, waste_type, kaimai_hash)
    
    # Normalize house_numbers (None -> NULL in DB)
    house_nums_str = house_numbers if house_numbers else None
    
    # Insert or update location (no FK to schedule_group, just store kaimai_hash)
    cursor.execute("""
        INSERT INTO locations (seniūnija, village, street, house_numbers, kaimai_hash, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(seniūnija, village, street, house_numbers) 
        DO UPDATE SET kaimai_hash = ?, updated_at = ?
    """, (seniūnija, village, street, house_nums_str, kaimai_hash, datetime.now(), kaimai_hash, datetime.now()))
    
    # Dates are now stored in schedule_groups, not in pickup_dates table
    # No need to insert pickup_dates - just return location_id
    location_id = cursor.lastrowid
    if location_id == 0:
        # Location already exists, get its ID
        cursor.execute("SELECT id FROM locations WHERE seniūnija = ? AND village = ? AND street = ? AND (house_numbers = ? OR (house_numbers IS NULL AND ? IS NULL))", 
                      (seniūnija, village, street, house_nums_str, house_nums_str))
        location_id = cursor.fetchone()[0]
    
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
                item.get('kaimai_str', ''),  # Original Kaimai string for hash
                item.get('house_numbers'),
                waste_type='bendros'  # Default for now
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
