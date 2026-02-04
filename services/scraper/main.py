"""
Main script to run the scraper - can be used for daily cron jobs
"""

import argparse
import logging
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlparse

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from services.common.db import get_db_connection
from services.common.fetch_cache import (
    get_latest_cached_fetch,
    head_url,
    is_unchanged_by_head,
    log_source_fetch,
    sha256_file,
)
from services.common.logging_utils import setup_logging
from services.common.migrations import init_database
from services.scraper.core.db_writer import write_parsed_data
from services.scraper.core.fetcher import DEFAULT_URL, fetch_xlsx
from services.scraper.core.validator import validate_file_and_data


def run_scraper(
    skip_ai: bool = False,
    file_path: Path | None = None,
    url: str | None = None,
    year: int = 2026,
):
    """Run the scraper with given parameters

    Args:
        skip_ai: If True, skip AI parsing (use traditional parser only)
        file_path: Path to local xlsx file (if not provided, will fetch from URL)
        url: URL to fetch xlsx from (uses default if not provided)
        year: Year for date validation
    """
    setup_logging()
    logger = logging.getLogger(__name__)

    # Initialize database (scraper-owned migrations)
    migrations_dir = Path(__file__).parent / "migrations"
    init_database(migrations_dir=migrations_dir)

    # Use default URL if not provided
    if url is None:
        url = DEFAULT_URL

    print("=" * 60)
    print("Waste Schedule Scraper")
    if skip_ai:
        print(" MODE: Skip AI parsing (traditional parser only)")
    print(" MODE: Auto-create Google Calendars after scraping")
    print("=" * 60)
    logger.info("Scraper started (skip_ai=%s, year=%s)", skip_ai, year)

    try:
        headers: dict[str, str] | None = None
        byte_len: int | None = None

        # Fetch or use local xlsx
        if file_path:
            print(f"\n1. Using local xlsx file: {file_path}")
            if not file_path.exists():
                print(f" File not found: {file_path}")
                return 1
        else:
            print(f"\n1. Fetching xlsx from: {url}")
            # HEAD-based skip to avoid BOTH download and parsing when unchanged.
            conn = get_db_connection()
            try:
                cached = get_latest_cached_fetch(conn, kind="xlsx", source_url=url)
            finally:
                conn.close()
            head = head_url(url)
            if is_unchanged_by_head(cached=cached, head=head):
                assert head is not None
                hint = head.etag or head.last_modified or "unchanged"
                print(f" Skip: XLSX unchanged (HEAD match: {hint})")
                return 0

            file_path, headers, byte_len = fetch_xlsx(url)

        # Validate and parse
        print("\n2. Validating and parsing xlsx...")
        is_valid, errors, parsed_data = validate_file_and_data(file_path, year, skip_ai=skip_ai)

        if errors:
            print("\n  Validation warnings/errors:")
            for error in errors:
                print(f"   - {error}")

        if not parsed_data:
            print("\n No data parsed. Exiting.")
            write_parsed_data([], url, errors)
            return 1

        # Write to database
        print(f"\n3. Writing {len(parsed_data)} locations to database...")
        success = write_parsed_data(parsed_data, url, errors if not is_valid else None)

        # Log successful source fetch metadata for future HEAD-based skips.
        try:
            downloaded_from_url = headers is not None and str(file_path).startswith(tempfile.gettempdir())
            if downloaded_from_url:
                assert headers is not None
                content_hash = sha256_file(Path(file_path))
                etag = headers.get("ETag")
                last_modified = headers.get("Last-Modified")
                try:
                    content_length = (
                        int(headers.get("Content-Length"))
                        if headers.get("Content-Length") is not None
                        else byte_len
                    )
                except Exception:
                    content_length = byte_len
                source_file = Path(urlparse(url).path).name if url else None
                conn = get_db_connection()
                try:
                    log_source_fetch(
                        conn,
                        kind="xlsx",
                        source_url=url,
                        source_file=source_file,
                        etag=etag,
                        last_modified=last_modified,
                        content_length=content_length,
                        content_hash=content_hash,
                        status="success" if success else "failed",
                    )
                finally:
                    conn.close()
        except Exception:
            # Never fail the run because of fetch-cache logging.
            pass

        # Cleanup
        if file_path.exists() and str(file_path).startswith(tempfile.gettempdir()):
            file_path.unlink()

        if success:
            print("\n Successfully completed!")
            return 0
        else:
            print("\n Failed to write to database")
            return 1

    except Exception as e:
        print(f"\n Error: {e}")
        import traceback

        traceback.print_exc()
        return 1


def main():
    """Main scraper function (CLI entry point)"""
    parser = argparse.ArgumentParser(description="Waste Schedule Scraper")
    parser.add_argument(
        "--skip-ai",
        action="store_true",
        help="Skip AI parsing (use traditional parser only). Default: AI parsing enabled",
    )
    parser.add_argument(
        "--file",
        type=str,
        default=None,
        help="Path to local xlsx file (if not provided, will fetch from URL)",
    )
    args = parser.parse_args()

    file_path = Path(args.file) if args.file else None
    return run_scraper(skip_ai=args.skip_ai, file_path=file_path)


if __name__ == "__main__":
    sys.exit(main())
