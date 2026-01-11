"""
Database query functions for API
"""
import sqlite3
from typing import List, Dict, Optional
from datetime import date, datetime
from database.init import get_db_connection

def get_all_locations() -> List[Dict]:
    """
    Get all locations (street/village combos)
    
    Returns:
        List of dictionaries with id, village, street, schedule_group_id
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT id, seniūnija, village, street, house_numbers, schedule_group_id
        FROM locations
        ORDER BY seniūnija, village, street
    """)
    
    results = []
    for row in cursor.fetchall():
        results.append({
            'id': row[0],
            'seniūnija': row[1],
            'village': row[2],
            'street': row[3],
            'house_numbers': row[4],
            'schedule_group_id': row[5]
        })
    
    conn.close()
    return results

def get_location_schedule(location_id: Optional[int] = None, village: Optional[str] = None, street: Optional[str] = None) -> Optional[Dict]:
    """
    Get schedule for a specific location
    
    Args:
        location_id: Location ID (preferred)
        village: Village name
        street: Street name
    
    Returns:
        Dictionary with location info and dates, or None if not found
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Build query based on provided parameters
    if location_id:
        cursor.execute("""
            SELECT id, seniūnija, village, street, house_numbers, schedule_group_id
            FROM locations
            WHERE id = ?
        """, (location_id,))
    elif village and street:
        cursor.execute("""
            SELECT id, seniūnija, village, street, house_numbers, schedule_group_id
            FROM locations
            WHERE village = ? AND street = ?
        """, (village, street))
    else:
        conn.close()
        return None
    
    location_row = cursor.fetchone()
    if not location_row:
        conn.close()
        return None
    
    location_id = location_row[0]
    
    # Get pickup dates
    cursor.execute("""
        SELECT date, waste_type
        FROM pickup_dates
        WHERE location_id = ?
        ORDER BY date
    """, (location_id,))
    
    dates = []
    for row in cursor.fetchall():
        dates.append({
            'date': row[0],
            'waste_type': row[1]
        })
    
    conn.close()
    
    return {
        'id': location_row[0],
        'seniūnija': location_row[1],
        'village': location_row[2],
        'street': location_row[3],
        'house_numbers': location_row[4],
        'schedule_group_id': location_row[5],
        'dates': dates
    }

def get_schedule_group_info(schedule_group_id: int) -> Optional[Dict]:
    """
    Get metadata about a schedule group
    
    Args:
        schedule_group_id: Schedule group ID
    
    Returns:
        Dictionary with schedule group metadata, or None if not found
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT id, first_date, last_date, date_count, created_at
        FROM schedule_groups
        WHERE id = ?
    """, (schedule_group_id,))
    
    row = cursor.fetchone()
    conn.close()
    
    if not row:
        return None
    
    return {
        'id': row[0],
        'first_date': row[1],
        'last_date': row[2],
        'date_count': row[3],
        'created_at': row[4]
    }

def get_schedule_group_schedule(schedule_group_id: int) -> Dict:
    """
    Get schedule for a schedule group (all locations with same schedule)
    
    Args:
        schedule_group_id: Schedule group ID
    
    Returns:
        Dictionary with schedule group info, locations, and dates
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Get schedule group metadata
    group_info = get_schedule_group_info(schedule_group_id)
    if not group_info:
        conn.close()
        return {
            'schedule_group_id': schedule_group_id,
            'error': 'Schedule group not found',
            'locations': [],
            'dates': []
        }
    
    # Get all locations in this group
    cursor.execute("""
        SELECT id, seniūnija, village, street, house_numbers
        FROM locations
        WHERE schedule_group_id = ?
        ORDER BY seniūnija, village, street
    """, (schedule_group_id,))
    
    locations = []
    location_ids = []
    for row in cursor.fetchall():
        locations.append({
            'id': row[0],
            'seniūnija': row[1],
            'village': row[2],
            'street': row[3],
            'house_numbers': row[4]
        })
        location_ids.append(row[0])
    
    # Get dates (all locations in group have same dates, so get from first)
    dates = []
    if location_ids:
        cursor.execute("""
            SELECT date, waste_type
            FROM pickup_dates
            WHERE location_id = ?
            ORDER BY date
        """, (location_ids[0],))
        
        for row in cursor.fetchall():
            dates.append({
                'date': row[0],
                'waste_type': row[1]
            })
    
    conn.close()
    
    return {
        'schedule_group_id': schedule_group_id,
        'metadata': {
            'first_date': group_info['first_date'],
            'last_date': group_info['last_date'],
            'date_count': group_info['date_count']
        },
        'location_count': len(locations),
        'locations': locations,
        'dates': dates
    }

def search_locations(query: str) -> List[Dict]:
    """
    Search locations by village or street name
    
    Args:
        query: Search query
    
    Returns:
        List of matching locations
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    search_term = f"%{query}%"
    cursor.execute("""
        SELECT id, seniūnija, village, street, house_numbers, schedule_group_id
        FROM locations
        WHERE seniūnija LIKE ? OR village LIKE ? OR street LIKE ?
        ORDER BY seniūnija, village, street
        LIMIT 50
    """, (search_term, search_term, search_term))
    
    results = []
    for row in cursor.fetchall():
        results.append({
            'id': row[0],
            'seniūnija': row[1],
            'village': row[2],
            'street': row[3],
            'house_numbers': row[4],
            'schedule_group_id': row[5]
        })
    
    conn.close()
    return results
