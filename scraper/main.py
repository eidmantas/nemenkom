"""
Main script to run the scraper - can be used for daily cron jobs
"""
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from scraper.fetcher import fetch_xlsx, DEFAULT_URL
from scraper.validator import validate_file_and_data
from scraper.db_writer import write_parsed_data
from database.init import init_database
import tempfile

def main():
    """Main scraper function"""
    # Initialize database
    init_database()
    
    # Configuration
    url = DEFAULT_URL
    year = 2026  # Can be made configurable
    
    print("=" * 60)
    print("Waste Schedule Scraper")
    print("=" * 60)
    
    try:
        # Fetch xlsx
        print(f"\n1. Fetching xlsx from: {url}")
        file_path = fetch_xlsx(url)
        
        # Validate and parse
        print("\n2. Validating and parsing xlsx...")
        is_valid, errors, parsed_data = validate_file_and_data(file_path, year)
        
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

if __name__ == '__main__':
    sys.exit(main())
