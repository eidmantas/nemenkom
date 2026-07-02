"""
Main script to run the scraper - can be used for daily cron jobs
"""

import argparse
import logging
import re
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from services.common.db import get_db_connection
from services.common.fetch_cache import (
    PreparedRemoteSource,
    log_prepared_source_fetch,
    prepare_remote_source,
)
from services.common.logging_utils import setup_logging
from services.common.migrations import init_database
from services.scraper.core.db_writer import write_parsed_data
from services.scraper.core.validator import validate_file_and_data


def get_configured_xlsx_url() -> str:
    try:
        import config
    except ImportError as exc:
        raise RuntimeError("Missing config.py with XLSX_BENDROS_URL") from exc

    url = str(getattr(config, "XLSX_BENDROS_URL", "") or "").strip()
    if not url:
        raise RuntimeError("Missing required config.XLSX_BENDROS_URL")
    return url


def _normalize_lookup_key(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().casefold()


def get_existing_villages_by_seniunija() -> dict[str, list[str]]:
    """
    Load current DB village names so AI parsing can pick an existing village
    when the new XLSX row has merged village/street text.
    """
    conn = get_db_connection()
    try:
        rows = conn.execute(
            """
            SELECT seniunija, village
            FROM locations
            WHERE village IS NOT NULL AND TRIM(village) != ''
            GROUP BY seniunija, village
            ORDER BY seniunija, village
            """
        ).fetchall()
    finally:
        conn.close()

    villages_by_key: dict[str, set[str]] = {}
    for seniunija, village in rows:
        seniunija_text = str(seniunija or "").strip()
        village_text = str(village or "").strip()
        if not seniunija_text or not village_text:
            continue
        for key in {seniunija_text, _normalize_lookup_key(seniunija_text)}:
            villages_by_key.setdefault(key, set()).add(village_text)

    return {key: sorted(villages) for key, villages in villages_by_key.items()}


def run_scraper(
    skip_ai: bool = False,
    file_path: Path | None = None,
    url: str | None = None,
    year: int = 2026,
    force: bool = False,
):
    """Run the scraper with given parameters

    Args:
        skip_ai: If True, skip AI parsing (use traditional parser only)
        file_path: Path to local xlsx file (if not provided, will fetch from URL)
        url: URL to fetch xlsx from (uses default if not provided)
        year: Year for date validation
        force: If True, bypass HEAD-based "unchanged" skip and re-parse anyway.
    """
    setup_logging()
    logger = logging.getLogger(__name__)

    # Initialize database (scraper-owned migrations)
    migrations_dir = Path(__file__).parent / "migrations"
    init_database(migrations_dir=migrations_dir)

    # Use default URL if not provided
    if url is None:
        url = get_configured_xlsx_url()

    print("=" * 60)
    print("Waste Schedule Scraper")
    if skip_ai:
        print(" MODE: Skip AI parsing (traditional parser only)")
    print(" MODE: Auto-create Google Calendars after scraping")
    print("=" * 60)
    logger.info("Scraper started (skip_ai=%s, year=%s)", skip_ai, year)
    known_villages_by_seniunija = get_existing_villages_by_seniunija()
    if known_villages_by_seniunija:
        distinct_villages = {
            village for villages in known_villages_by_seniunija.values() for village in villages
        }
        print(f" Loaded {len(distinct_villages)} existing villages for AI matching")

    try:
        remote_source: PreparedRemoteSource | None = None

        # Fetch or use local xlsx
        if file_path:
            print(f"\n1. Using local xlsx file: {file_path}")
            if not file_path.exists():
                print(f" File not found: {file_path}")
                return 1
        else:
            print(f"\n1. Fetching xlsx from: {url}")
            conn = get_db_connection()
            try:
                remote_source = prepare_remote_source(
                    conn,
                    kind="xlsx",
                    source_url=url,
                    suffix=".xlsx",
                    default_source_file="waste_schedule.xlsx",
                    force=force,
                    timeout_seconds=30,
                )
            finally:
                conn.close()

            if not remote_source.should_parse:
                print(f" Skip: XLSX {remote_source.skip_reason}")
                if (
                    remote_source.cleanup_path
                    and remote_source.path
                    and remote_source.path.exists()
                ):
                    remote_source.path.unlink()
                return 0

            assert remote_source.path is not None
            file_path = remote_source.path

        # Validate and parse
        print("\n2. Validating and parsing xlsx...")
        is_valid, errors, parsed_data = validate_file_and_data(
            file_path,
            year,
            skip_ai=skip_ai,
            known_villages_by_seniunija=known_villages_by_seniunija,
        )

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

        if remote_source:
            try:
                conn = get_db_connection()
                try:
                    log_prepared_source_fetch(
                        conn,
                        source=remote_source,
                        status="success" if success else "failed",
                    )
                finally:
                    conn.close()
            except Exception:
                # Never fail the run because of fetch-cache logging.
                pass

        # Cleanup
        if remote_source and remote_source.cleanup_path and remote_source.path:
            if remote_source.path.exists():
                remote_source.path.unlink()

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
        help="Path to local xlsx file (if not provided, will fetch from configured URL)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force parsing even if the remote XLSX is unchanged (bypass HEAD skip).",
    )
    args = parser.parse_args()

    file_path = Path(args.file) if args.file else None
    return run_scraper(skip_ai=args.skip_ai, file_path=file_path, force=args.force)


if __name__ == "__main__":
    sys.exit(main())
