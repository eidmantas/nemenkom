"""
Database query functions for API
Updated for new schema: hash-based schedule_groups, dates in JSON, no pickup_dates table
"""
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
        SELECT id, seniunija, village, street, house_numbers, kaimai_hash
        FROM locations
        ORDER BY seniunija, village, street
    """)
    
    results = []
    for row in cursor.fetchall():
        results.append({
            'id': row[0],
            'seniunija': row[1],
            'village': row[2],
            'street': row[3],
            'house_numbers': row[4],
            'kaimai_hash': row[5]
        })
    
    conn.close()
    return results

def get_location_schedule(location_id: Optional[int] = None, seniunija: Optional[str] = None, village: Optional[str] = None, street: Optional[str] = None, waste_type: str = 'bendros') -> Optional[Dict]:
    """
    Get schedule for a specific location
    
    Args:
        location_id: Location ID (preferred)
        seniunija: Seniūnija name (required if using village/street)
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
            SELECT id, seniunija, village, street, house_numbers, kaimai_hash
            FROM locations
            WHERE id = ?
        """, (location_id,))
    elif seniunija and village and street is not None:
        cursor.execute("""
            SELECT id, seniunija, village, street, house_numbers, kaimai_hash
            FROM locations
            WHERE seniunija = ? AND village = ? AND street = ?
        """, (seniunija, village, street))
    else:
        conn.close()
        return None
    
    location_row = cursor.fetchone()
    if not location_row:
        conn.close()
        return None
    
    location_id = location_row[0]
    kaimai_hash = location_row[5]
    
    # Get dates and calendar_id from schedule_groups by kaimai_hash + waste_type (direct lookup, no JSON)
    cursor.execute("""
        SELECT sg.id, sg.dates, sg.calendar_id, sg.calendar_synced_at
        FROM schedule_groups sg
        WHERE sg.kaimai_hash = ?
          AND sg.waste_type = ?
        LIMIT 1
    """, (kaimai_hash, waste_type))
    
    schedule_row = cursor.fetchone()
    dates = []
    schedule_group_id = None
    calendar_id = None
    calendar_synced_at = None
    
    if schedule_row:
        schedule_group_id = schedule_row[0]
        dates_json = schedule_row[1]
        calendar_id = schedule_row[2]
        calendar_synced_at = schedule_row[3]
        if dates_json:
            date_list = json.loads(dates_json)
            dates = [{'date': d, 'waste_type': waste_type} for d in date_list]
    
    conn.close()
    
    result = {
        'id': location_row[0],
        'seniunija': location_row[1],
        'village': location_row[2],
        'street': location_row[3],
        'house_numbers': location_row[4],
        'kaimai_hash': location_row[5],
        'schedule_group_id': schedule_group_id,
        'waste_type': waste_type,
        'dates': dates
    }
    
    # Add calendar_id and subscription_link if calendar exists
    if calendar_id:
        result['calendar_id'] = calendar_id
        result['subscription_link'] = f"https://calendar.google.com/calendar/render?cid={calendar_id}"
    
    # Add calendar_status
    result['calendar_status'] = get_calendar_status(calendar_id, calendar_synced_at)
    
    return result

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
        SELECT id, waste_type, kaimai_hash, first_date, last_date, date_count, dates, dates_hash, 
               calendar_id, calendar_synced_at, created_at, updated_at
        FROM schedule_groups
        WHERE id = ?
    """, (schedule_group_id,))
    
    row = cursor.fetchone()
    conn.close()
    
    if not row:
        return None
    
    dates = json.loads(row[6] or '[]')
    
    return {
        'id': row[0],
        'waste_type': row[1],
        'kaimai_hash': row[2],  # Single value, not JSON array
        'first_date': row[3],
        'last_date': row[4],
        'date_count': row[5],
        'dates': dates,
        'dates_hash': row[7],
        'calendar_id': row[8],
        'calendar_synced_at': row[9],
        'created_at': row[10],
        'updated_at': row[11]
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
    
    # Get all locations in this group (by matching kaimai_hash directly)
    kaimai_hash = group_info['kaimai_hash']
    if not kaimai_hash:
        conn.close()
        return {
            'schedule_group_id': schedule_group_id,
            'metadata': group_info,
            'location_count': 0,
            'locations': [],
            'dates': group_info['dates']
        }
    
    # Direct lookup by kaimai_hash (single value, not JSON array)
    cursor.execute("""
        SELECT id, seniunija, village, street, house_numbers
        FROM locations
        WHERE kaimai_hash = ?
        ORDER BY seniunija, village, street
    """, (kaimai_hash,))
    
    locations = []
    for row in cursor.fetchall():
        locations.append({
            'id': row[0],
            'seniunija': row[1],
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
            'date_count': group_info['date_count'],
            'calendar_id': group_info.get('calendar_id')
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
        SELECT id, seniunija, village, street, house_numbers, kaimai_hash
        FROM locations
        WHERE seniunija LIKE ? OR village LIKE ? OR street LIKE ?
        ORDER BY seniunija, village, street
        LIMIT 50
    """, (search_term, search_term, search_term))
    
    results = []
    for row in cursor.fetchall():
        results.append({
            'id': row[0],
            'seniunija': row[1],
            'village': row[2],
            'street': row[3],
            'house_numbers': row[4],
            'kaimai_hash': row[5]
        })
    
    conn.close()
    return results

def get_unique_villages() -> List[Dict]:
    """Get list of unique villages with seniunija and village as separate keys"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT DISTINCT seniunija, village
        FROM locations
        WHERE village != ''
        ORDER BY seniunija, village
    """)
    
    results = [{"seniunija": row[0], "village": row[1]} for row in cursor.fetchall()]
    conn.close()
    return results

def get_streets_for_village(seniunija: str, village: str) -> List[str]:
    """Get list of unique streets for a village in a specific seniunija (includes empty string for whole village)"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT DISTINCT street
        FROM locations
        WHERE seniunija = ? AND village = ?
        ORDER BY CASE WHEN street = '' THEN 0 ELSE 1 END, street
    """, (seniunija, village))
    
    results = [row[0] for row in cursor.fetchall()]
    conn.close()
    return results

def get_house_numbers_for_street(seniunija: str, village: str, street: str) -> List[str]:
    """Get list of unique house numbers for a street in a specific seniunija/village (street can be empty string for whole village)"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT DISTINCT house_numbers
        FROM locations
        WHERE seniunija = ? AND village = ? AND street = ?
        ORDER BY house_numbers
    """, (seniunija, village, street))
    
    # Filter out None values, but keep empty strings if they exist
    results = [row[0] for row in cursor.fetchall() if row[0] is not None]
    conn.close()
    return results

def village_has_streets(seniunija: str, village: str) -> bool:
    """Check if a village in a specific seniunija has any non-empty streets"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT COUNT(*) 
        FROM locations
        WHERE seniunija = ? AND village = ? AND street != '' AND street IS NOT NULL
        LIMIT 1
    """, (seniunija, village))
    
    count = cursor.fetchone()[0]
    conn.close()
    return count > 0

def street_has_house_numbers(seniunija: str, village: str, street: str) -> bool:
    """Check if a street in a specific seniunija/village has any house numbers"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT COUNT(*) 
        FROM locations
        WHERE seniunija = ? AND village = ? AND street = ? AND house_numbers IS NOT NULL AND house_numbers != ''
        LIMIT 1
    """, (seniunija, village, street))
    
    count = cursor.fetchone()[0]
    conn.close()
    return count > 0

def get_location_by_selection(seniunija: str, village: str, street: str, house_numbers: Optional[str] = None) -> Optional[Dict]:
    """Get location by seniunija, village, street, and optionally house_numbers"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    if house_numbers:
        cursor.execute("""
            SELECT id, seniunija, village, street, house_numbers, kaimai_hash
            FROM locations
            WHERE seniunija = ? AND village = ? AND street = ? AND house_numbers = ?
            LIMIT 1
        """, (seniunija, village, street, house_numbers))
    else:
        # If no house_numbers specified, get first match (or one with NULL house_numbers)
        cursor.execute("""
            SELECT id, seniunija, village, street, house_numbers, kaimai_hash
            FROM locations
            WHERE seniunija = ? AND village = ? AND street = ?
            ORDER BY CASE WHEN house_numbers IS NULL THEN 0 ELSE 1 END
            LIMIT 1
        """, (seniunija, village, street))
    
    row = cursor.fetchone()
    conn.close()
    
    if not row:
        return None
    
    return {
        'id': row[0],
        'seniunija': row[1],
        'village': row[2],
        'street': row[3],
        'house_numbers': row[4],
        'kaimai_hash': row[5]
    }

def update_schedule_group_calendar_id(schedule_group_id: str, calendar_id: str) -> bool:
    """
    Update the calendar_id for a schedule group
    
    Args:
        schedule_group_id: Schedule group ID
        calendar_id: Google Calendar ID to store
    
    Returns:
        True if updated successfully, False otherwise
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            UPDATE schedule_groups
            SET calendar_id = ?
            WHERE id = ?
        """, (calendar_id, schedule_group_id))
        
        conn.commit()
        success = cursor.rowcount > 0
        conn.close()
        return success
    except Exception as e:
        conn.close()
        print(f"Error updating calendar_id: {e}")
        return False

def get_schedule_group_by_calendar_id(calendar_id: str) -> Optional[Dict]:
    """
    Get schedule group by calendar_id (reverse lookup)
    
    Args:
        calendar_id: Google Calendar ID
    
    Returns:
        Schedule group info, or None if not found
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT id
        FROM schedule_groups
        WHERE calendar_id = ?
        LIMIT 1
    """, (calendar_id,))
    
    row = cursor.fetchone()
    conn.close()
    
    if not row:
        return None
    
    # Use existing function to get full info
    return get_schedule_group_info(row[0])

def get_calendar_status(calendar_id: Optional[str], calendar_synced_at: Optional[str]) -> Dict:
    """
    Get calendar status based on calendar_id and calendar_synced_at
    
    Returns:
        Dictionary with status and calendar_id
        Status values: 'synced', 'pending', 'needs_update', 'not_available'
    """
    if not calendar_id:
        return {
            'status': 'pending',
            'calendar_id': None
        }
    
    if calendar_synced_at is None:
        return {
            'status': 'needs_update',
            'calendar_id': calendar_id
        }
    
    return {
        'status': 'synced',
        'calendar_id': calendar_id
    }

def get_schedule_groups_needing_sync() -> List[Dict]:
    """
    Get schedule groups that need calendar creation or sync
    
    Conditions:
    - calendar_id IS NULL (needs calendar creation)
    - OR calendar_synced_at IS NULL (needs event sync)
    
    Returns:
        List of schedule group dictionaries
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT id, waste_type, kaimai_hash, dates, calendar_id, calendar_synced_at
        FROM schedule_groups
        WHERE calendar_id IS NULL OR calendar_synced_at IS NULL
        ORDER BY created_at ASC
    """)
    
    results = []
    for row in cursor.fetchall():
        dates = json.loads(row[3] or '[]')
        results.append({
            'id': row[0],
            'waste_type': row[1],
            'kaimai_hash': row[2],
            'dates': dates,
            'calendar_id': row[4],
            'calendar_synced_at': row[5]
        })
    
    conn.close()
    return results

def update_schedule_group_calendar_synced(schedule_group_id: str) -> bool:
    """
    Mark a schedule group as synced (set calendar_synced_at to current timestamp)
    
    Args:
        schedule_group_id: Schedule group ID
    
    Returns:
        True if updated successfully, False otherwise
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            UPDATE schedule_groups
            SET calendar_synced_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (schedule_group_id,))
        
        conn.commit()
        success = cursor.rowcount > 0
        conn.close()
        return success
    except Exception as e:
        conn.close()
        print(f"Error updating calendar_synced_at: {e}")
        return False
