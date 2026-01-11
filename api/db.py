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
        SELECT id, village, street, schedule_group_id
        FROM locations
        ORDER BY village, street
    """)
    
    results = []
    for row in cursor.fetchall():
        results.append({
            'id': row[0],
            'village': row[1],
            'street': row[2],
            'schedule_group_id': row[3]
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
            SELECT id, village, street, schedule_group_id
            FROM locations
            WHERE id = ?
        """, (location_id,))
    elif village and street:
        cursor.execute("""
            SELECT id, village, street, schedule_group_id
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
        'village': location_row[1],
        'street': location_row[2],
        'schedule_group_id': location_row[3],
        'dates': dates
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
    
    # Get all locations in this group
    cursor.execute("""
        SELECT id, village, street
        FROM locations
        WHERE schedule_group_id = ?
        ORDER BY village, street
    """, (schedule_group_id,))
    
    locations = []
    location_ids = []
    for row in cursor.fetchall():
        locations.append({
            'id': row[0],
            'village': row[1],
            'street': row[2]
        })
        location_ids.append(row[0])
    
    if not location_ids:
        conn.close()
        return {
            'schedule_group_id': schedule_group_id,
            'locations': [],
            'dates': []
        }
    
    # Get dates (all locations in group have same dates, so get from first)
    cursor.execute("""
        SELECT date, waste_type
        FROM pickup_dates
        WHERE location_id = ?
        ORDER BY date
    """, (location_ids[0],))
    
    dates = []
    for row in cursor.fetchall():
        dates.append({
            'date': row[0],
            'waste_type': row[1]
        })
    
    conn.close()
    
    return {
        'schedule_group_id': schedule_group_id,
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
        SELECT id, village, street, schedule_group_id
        FROM locations
        WHERE village LIKE ? OR street LIKE ?
        ORDER BY village, street
        LIMIT 50
    """, (search_term, search_term))
    
    results = []
    for row in cursor.fetchall():
        results.append({
            'id': row[0],
            'village': row[1],
            'street': row[2],
            'schedule_group_id': row[3]
        })
    
    conn.close()
    return results
