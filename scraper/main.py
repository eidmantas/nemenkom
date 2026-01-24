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

def run_scraper(skip_ai=False, file_path=None, url=None, year=2026):
    """Run the scraper with given parameters
    
    Args:
        skip_ai: If True, skip AI parsing (use traditional parser only)
        file_path: Path to local xlsx file (if not provided, will fetch from URL)
        url: URL to fetch xlsx from (uses default if not provided)
        year: Year for date validation
    """
    # Initialize database
    init_database()

    # Use default URL if not provided
    if url is None:
        url = DEFAULT_URL

    print("=" * 60)
    print("Waste Schedule Scraper")
    if skip_ai:
        print("🔍 MODE: Skip AI parsing (traditional parser only)")
    print("📅 MODE: Auto-create Google Calendars after scraping")
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
        is_valid, errors, parsed_data = validate_file_and_data(file_path, year, skip_ai=skip_ai)

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

        # Create calendars after successful database write (always)
        if success:
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
    parser.add_argument('--skip-ai', action='store_true',
                        help='Skip AI parsing (use traditional parser only). Default: AI parsing enabled')
    parser.add_argument('--file', type=str, default=None,
                        help='Path to local xlsx file (if not provided, will fetch from URL)')
    args = parser.parse_args()

    return run_scraper(
        skip_ai=args.skip_ai,
        file_path=args.file
    )


def get_all_schedule_groups():
    """Get all schedule groups from database with their data"""
    conn = get_db_connection()
    cursor = conn.cursor()

    # Get all schedule groups with their metadata
    cursor.execute("""
        SELECT id, waste_type, dates, kaimai_hash
        FROM schedule_groups
    """)

    schedule_groups = {}
    for row in cursor.fetchall():
        sg_id = row[0]
        waste_type = row[1]
        dates = json.loads(row[2] or '[]')
        kaimai_hash = row[3]  # Single TEXT value, not JSON array

        # Get location info from kaimai_hash
        location_info = get_location_from_kaimai_hash(kaimai_hash) if kaimai_hash else None
        location_name = location_info['village'] if location_info else sg_id

        schedule_groups[sg_id] = {
            'waste_type': waste_type,
            'dates': dates,
            'location': location_name,
            'kaimai_hash': kaimai_hash
        }

    conn.close()
    return schedule_groups

def get_location_from_kaimai_hash(kaimai_hash):
    """Get location info from kaimai_hash"""
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT seniunija, village, street, house_numbers
        FROM locations
        WHERE kaimai_hash = ?
        LIMIT 1
    """, (kaimai_hash,))

    row = cursor.fetchone()
    conn.close()

    if row:
        return {
            'seniunija': row[0],
            'village': row[1],
            'street': row[2],
            'house_numbers': row[3]
        }
    return None

def create_calendars_for_schedule_groups():
    """Create Google Calendars for all schedule groups after scraping"""
    import time
    import logging
    logging.basicConfig(level=logging.DEBUG, format='[%(asctime)s] %(levelname)s: %(message)s')
    logger = logging.getLogger(__name__)
    
    try:
        from services.calendar import create_calendar_for_schedule_group

        print("📅 Starting calendar creation...")
        logger.info("Starting calendar creation for all schedule groups")
        start_time = time.time()

        # Get all schedule groups from database
        logger.debug("Fetching schedule groups from database...")
        db_fetch_start = time.time()
        schedule_groups = get_all_schedule_groups()
        logger.info(f"Found {len(schedule_groups)} schedule groups (took {time.time() - db_fetch_start:.2f}s)")

        created_count = 0
        skipped_count = 0
        error_count = 0

        for idx, (sg_id, sg_data) in enumerate(schedule_groups.items(), 1):
            logger.info(f"Processing calendar {idx}/{len(schedule_groups)}: {sg_data['location']} (schedule_group: {sg_id})")
            calendar_start = time.time()
            
            # Create calendar (function checks database for existing calendar_id automatically)
            result = create_calendar_for_schedule_group(
                schedule_group_id=sg_id,
                location_name=sg_data['location'],
                dates=sg_data['dates'],
                waste_type=sg_data['waste_type']
            )

            calendar_time = time.time() - calendar_start
            if result and result['success']:
                if result.get('existing'):
                    logger.info(f"Using existing calendar for {sg_data['location']} (took {calendar_time:.2f}s)")
                    print(f"✅ Using existing calendar for {sg_data['location']}: {result['calendar_name']}")
                    skipped_count += 1
                else:
                    logger.info(f"Created calendar for {sg_data['location']} with {result['events_created']} events (took {calendar_time:.2f}s)")
                    print(f"📅 Created calendar: {result['calendar_name']} ({result['events_created']} events)")
                    created_count += 1
            else:
                logger.error(f"Failed to create calendar for {sg_data['location']} (schedule_group: {sg_id}) (took {calendar_time:.2f}s)")
                print(f"❌ Failed to create calendar for {sg_data['location']} (schedule_group: {sg_id})")
                error_count += 1

        total_time = time.time() - start_time
        logger.info(f"Calendar creation complete: {created_count} created, {skipped_count} skipped, {error_count} errors (total time: {total_time:.2f}s)")
        print(f"🎉 Calendar creation complete: {created_count} created, {skipped_count} skipped, {error_count} errors")

    except Exception as e:
        logger.error(f"Calendar creation failed: {e}", exc_info=True)
        print(f"⚠️  Calendar creation failed: {e}")
        # Don't fail the whole scraper if calendar creation fails
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    sys.exit(main())
