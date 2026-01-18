"""
Main script to run the scraper - can be used for daily cron jobs
"""
import sys
import argparse
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from scraper.core.fetcher import fetch_xlsx, DEFAULT_URL
from scraper.core.validator import validate_file_and_data
from scraper.core.db_writer import write_parsed_data
from database.init import init_database
import tempfile

def run_scraper(simple_subset=False, file_path=None, url=None, year=2026):
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
    args = parser.parse_args()
    
    return run_scraper(simple_subset=args.simple_subset, file_path=args.file)

if __name__ == '__main__':
    sys.exit(main())
