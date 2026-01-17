"""
Database query functions for API
Updated for new schema: hash-based schedule_groups, dates in JSON, no pickup_dates table
"""
import sqlite3
import json
from typing import List, Dict, Optional
from database.init import get_db_connection

def get_all_locations() -> List[Dict]:
    """
    Get all locations (street/village combos)
    
    Returns:
        List of dictionaries with id, village, street, kaimai_hash
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT id, seniūnija, village, street, house_numbers, kaimai_hash
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
            'kaimai_hash': row[5]
        })
    
    conn.close()
    return results

def get_location_schedule(location_id: Optional[int] = None, village: Optional[str] = None, street: Optional[str] = None, waste_type: str = 'bendros') -> Optional[Dict]:
    """
    Get schedule for a specific location
    
    Args:
        location_id: Location ID (preferred)
        village: Village name
        street: Street name
        waste_type: Waste type ('bendros', 'plastikas', etc.)
    
    Returns:
        Dictionary with location info and dates, or None if not found
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Build query based on provided parameters
    if location_id:
        cursor.execute("""
            SELECT id, seniūnija, village, street, house_numbers, kaimai_hash
            FROM locations
            WHERE id = ?
        """, (location_id,))
    elif village and street:
        cursor.execute("""
            SELECT id, seniūnija, village, street, house_numbers, kaimai_hash
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
    kaimai_hash = location_row[5]
    
    # Get dates from schedule_groups by kaimai_hash + waste_type
    cursor.execute("""
        SELECT sg.id, sg.dates
        FROM schedule_groups sg, json_each(sg.kaimai_hashes)
        WHERE json_each.value = ?
          AND sg.waste_type = ?
        LIMIT 1
    """, (kaimai_hash, waste_type))
    
    schedule_row = cursor.fetchone()
    dates = []
    schedule_group_id = None
    
    if schedule_row:
        schedule_group_id = schedule_row[0]
        dates_json = schedule_row[1]
        if dates_json:
            date_list = json.loads(dates_json)
            dates = [{'date': d, 'waste_type': waste_type} for d in date_list]
    
    conn.close()
    
    return {
        'id': location_row[0],
        'seniūnija': location_row[1],
        'village': location_row[2],
        'street': location_row[3],
        'house_numbers': location_row[4],
        'kaimai_hash': location_row[5],
        'schedule_group_id': schedule_group_id,
        'waste_type': waste_type,
        'dates': dates
    }

def get_schedule_group_info(schedule_group_id: str) -> Optional[Dict]:
    """
    Get metadata about a schedule group
    
    Args:
        schedule_group_id: Schedule group ID (hash-based string)
    
    Returns:
        Dictionary with schedule group metadata, or None if not found
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT id, waste_type, first_date, last_date, date_count, dates, kaimai_hashes, created_at
        FROM schedule_groups
        WHERE id = ?
    """, (schedule_group_id,))
    
    row = cursor.fetchone()
    conn.close()
    
    if not row:
        return None
    
    dates = json.loads(row[5] or '[]')
    kaimai_hashes = json.loads(row[6] or '[]')
    
    return {
        'id': row[0],
        'waste_type': row[1],
        'first_date': row[2],
        'last_date': row[3],
        'date_count': row[4],
        'dates': dates,
        'kaimai_hashes': kaimai_hashes,
        'created_at': row[7]
    }

def get_schedule_group_schedule(schedule_group_id: str, waste_type: str = 'bendros') -> Dict:
    """
    Get schedule for a schedule group (all locations with same schedule)
    
    Args:
        schedule_group_id: Schedule group ID (hash-based string)
        waste_type: Waste type to filter by
    
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
    
    # Filter by waste_type if provided
    if group_info['waste_type'] != waste_type:
        conn.close()
        return {
            'schedule_group_id': schedule_group_id,
            'error': f'Schedule group is for waste_type "{group_info["waste_type"]}", not "{waste_type}"',
            'locations': [],
            'dates': []
        }
    
    # Get all locations in this group (by matching kaimai_hash in kaimai_hashes)
    kaimai_hashes = group_info['kaimai_hashes']
    if not kaimai_hashes:
        conn.close()
        return {
            'schedule_group_id': schedule_group_id,
            'metadata': group_info,
            'location_count': 0,
            'locations': [],
            'dates': group_info['dates']
        }
    
    # Build query with placeholders for kaimai_hashes
    placeholders = ','.join(['?'] * len(kaimai_hashes))
    cursor.execute(f"""
        SELECT id, seniūnija, village, street, house_numbers
        FROM locations
        WHERE kaimai_hash IN ({placeholders})
        ORDER BY seniūnija, village, street
    """, kaimai_hashes)
    
    locations = []
    for row in cursor.fetchall():
        locations.append({
            'id': row[0],
            'seniūnija': row[1],
            'village': row[2],
            'street': row[3],
            'house_numbers': row[4]
        })
    
    # Dates are already in group_info
    dates = [{'date': d, 'waste_type': waste_type} for d in group_info['dates']]
    
    conn.close()
    
    return {
        'schedule_group_id': schedule_group_id,
        'metadata': {
            'waste_type': group_info['waste_type'],
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
        SELECT id, seniūnija, village, street, house_numbers, kaimai_hash
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
            'kaimai_hash': row[5]
        })
    
    conn.close()
    return results
