"""
Main script to run the scraper - can be used for daily cron jobs
"""
import sys
import argparse
import json
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from scraper.core.fetcher import fetch_xlsx, DEFAULT_URL
from scraper.core.validator import validate_file_and_data
from scraper.core.db_writer import write_parsed_data
from database.init import init_database, get_db_connection
import tempfile

def run_scraper(simple_subset=False, file_path=None, url=None, year=2026, create_calendars=False):
    """Run the scraper with given parameters"""
    # Initialize database
    init_database()

    # Use default URL if not provided
    if url is None:
        url = DEFAULT_URL

    print("=" * 60)
    print("Waste Schedule Scraper")
    if simple_subset:
        print("🔍 MODE: Simple subset only (traditional parser)")
    if create_calendars:
        print("📅 MODE: Create Google Calendars after scraping")
    print("=" * 60)

    try:
        # Fetch or use local xlsx
        if file_path:
            print(f"\n1. Using local xlsx file: {file_path}")
            file_path = Path(file_path)
            if not file_path.exists():
                print(f"❌ File not found: {file_path}")
                return 1
        else:
            print(f"\n1. Fetching xlsx from: {url}")
            file_path = fetch_xlsx(url)

        # Validate and parse
        print("\n2. Validating and parsing xlsx...")
        is_valid, errors, parsed_data = validate_file_and_data(file_path, year, simple_subset=simple_subset)

        if errors:
            print(f"\n⚠️  Validation warnings/errors:")
            for error in errors:
                print(f"   - {error}")

        if not parsed_data:
            print("\n❌ No data parsed. Exiting.")
            write_parsed_data([], url, errors)
            return 1

        # Write to database
        print(f"\n3. Writing {len(parsed_data)} locations to database...")
        success = write_parsed_data(parsed_data, url, errors if not is_valid else None)

        # NEW: Create calendars after successful database write
        if success and create_calendars:
            print(f"\n4. Creating Google Calendars for schedule groups...")
            create_calendars_for_schedule_groups()

        # Cleanup
        if file_path.exists() and str(file_path).startswith(tempfile.gettempdir()):
            file_path.unlink()

        if success:
            print("\n✅ Successfully completed!")
            return 0
        else:
            print("\n❌ Failed to write to database")
            return 1

    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return 1

def main():
    """Main scraper function (CLI entry point)"""
    parser = argparse.ArgumentParser(description='Waste Schedule Scraper')
    parser.add_argument('--simple-subset', action='store_true',
                        help='Only process Kaimai entries that can be parsed by traditional parser (skip AI-needed entries)')
    parser.add_argument('--file', type=str, default=None,
                        help='Path to local xlsx file (if not provided, will fetch from URL)')
    parser.add_argument('--create-calendars', action='store_true',
                        help='Create Google Calendars for all schedule groups after scraping')
    args = parser.parse_args()

    return run_scraper(
        simple_subset=args.simple_subset,
        file_path=args.file,
        create_calendars=args.create_calendars
    )

def calendar_exists(schedule_group_id):
    """Check if calendar already exists for a schedule group"""
    try:
        from api.google_calendar import list_available_calendars

        calendars = list_available_calendars()
        # Calendar names follow pattern: "Nemenčinė Atliekos - Location - WasteType"
        expected_prefix = f"Nemenčinė Atliekos - {schedule_group_id}"

        return any(expected_prefix in cal['calendar_name'] for cal in calendars)
    except:
        return False  # If we can't check, assume it doesn't exist

def get_all_schedule_groups():
    """Get all schedule groups from database with their data"""
    conn = get_db_connection()
    cursor = conn.cursor()

    # Get all schedule groups with their metadata
    cursor.execute("""
        SELECT id, waste_type, dates, kaimai_hashes
        FROM schedule_groups
    """)

    schedule_groups = {}
    for row in cursor.fetchall():
        sg_id = row[0]
        waste_type = row[1]
        dates = json.loads(row[2] or '[]')
        kaimai_hashes = json.loads(row[3] or '[]')

        # Get location info from first kaimai_hash
        location_info = get_location_from_kaimai_hash(kaimai_hashes[0]) if kaimai_hashes else None
        location_name = location_info['village'] if location_info else sg_id

        schedule_groups[sg_id] = {
            'waste_type': waste_type,
            'dates': dates,
            'location': location_name,
            'kaimai_hashes': kaimai_hashes
        }

    conn.close()
    return schedule_groups

def get_location_from_kaimai_hash(kaimai_hash):
    """Get location info from kaimai_hash"""
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT seniūnija, village, street, house_numbers
        FROM locations
        WHERE kaimai_hash = ?
        LIMIT 1
    """, (kaimai_hash,))

    row = cursor.fetchone()
    conn.close()

    if row:
        return {
            'seniūnija': row[0],
            'village': row[1],
            'street': row[2],
            'house_numbers': row[3]
        }
    return None

def create_calendars_for_schedule_groups():
    """Create Google Calendars for all schedule groups after scraping"""
    try:
        from api.google_calendar import create_calendar_for_schedule_group

        print("📅 Starting calendar creation...")

        # Get all schedule groups from database
        schedule_groups = get_all_schedule_groups()

        created_count = 0
        skipped_count = 0

        for sg_id, sg_data in schedule_groups.items():
            # Check if calendar already exists for this group
            if calendar_exists(sg_id):
                print(f"✅ Calendar already exists for {sg_data['location']}")
                skipped_count += 1
                continue

            # Create calendar
            result = create_calendar_for_schedule_group(
                schedule_group_id=sg_id,
                location_name=sg_data['location'],
                dates=sg_data['dates'],
                waste_type=sg_data['waste_type']
            )

            if result and result['success']:
                print(f"📅 Created calendar: {result['calendar_name']} ({result['events_created']} events)")
                created_count += 1
            else:
                print(f"❌ Failed to create calendar for {sg_data['location']}")

        print(f"🎉 Calendar creation complete: {created_count} created, {skipped_count} skipped")

    except Exception as e:
        print(f"⚠️  Calendar creation failed: {e}")
        # Don't fail the whole scraper if calendar creation fails
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    sys.exit(main())
