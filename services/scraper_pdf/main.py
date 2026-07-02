"""
Main script to run the PDF scraper - MVP for testing marker-pdf extraction
"""

import argparse
import logging
import sqlite3
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import config
from services.common.db import get_db_connection
from services.common.fetch_cache import (
    log_prepared_source_fetch,
    prepare_remote_source,
)
from services.common.logging_utils import setup_logging
from services.scraper_pdf.parser import MONTH_MAPPING, PdfParsedCell, parse_pdf


def _ensure_pdf_fetches_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS pdf_fetches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_url TEXT NOT NULL,
            source_file TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_pdf_fetches_url_hash
        ON pdf_fetches(source_url, content_hash)
        """
    )
    conn.commit()


def _log_fetch(
    conn: sqlite3.Connection, *, source_url: str, source_file: str, content_hash: str, status: str
) -> None:
    _ensure_pdf_fetches_table(conn)
    conn.execute(
        """
        INSERT INTO pdf_fetches (source_url, source_file, content_hash, status)
        VALUES (?, ?, ?, ?)
        """,
        (source_url, source_file, content_hash, status),
    )
    conn.commit()


def run_pdf_scraper(file_path: str | Path, year: int = 2026, skip_ai: bool = True):
    """Run the PDF scraper with given parameters

    Args:
        file_path: Path to local PDF file
        year: Year for date validation
    """
    setup_logging()
    logger = logging.getLogger(__name__)
    if (config.LOG_LEVEL or "").upper() == "DEBUG" or config.DEBUG:
        pdf_logger = logging.getLogger("services.scraper_pdf")
        stderr_handler = logging.StreamHandler(sys.stderr)
        stderr_handler.setLevel(logging.DEBUG)
        stderr_handler.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)s: %(message)s"))
        pdf_logger.addHandler(stderr_handler)
        pdf_logger.propagate = False
        logging.getLogger("pdfminer").setLevel(logging.WARNING)

    print("=" * 60)
    print("PDF Waste Schedule Scraper (MVP)")
    print("=" * 60)
    logger.info(
        "PDF Scraper started (file=%s, year=%s, skip_ai=%s)",
        file_path,
        year,
        skip_ai,
    )

    try:
        file_path_obj = Path(file_path)
        if not file_path_obj.exists():
            print(f" File not found: {file_path_obj}")
            return 1

        print(f"\n1. Parsing PDF: {file_path_obj}")

        # Parse PDF
        parsed_data, raw_rows, normalized_rows = parse_pdf(file_path_obj, year, skip_ai=skip_ai)

        if not parsed_data:
            print("\n No data parsed. Exiting.")
            return 1

        print(f"\n2. Parsed {len(parsed_data)} rows")
        print("\n3. Sample output (first 5 rows):")
        print("-" * 60)

        for i, item in enumerate(parsed_data[:5]):
            print(f"\nRow {i + 1}:")
            print(f"  Location: {item['kaimai_str'][:80]}...")
            print(f"  Waste Type: {item['waste_type']}")
            print(f"  Dates: {len(item['dates'])} dates")
            if item["dates"]:
                print(f"    First: {item['dates'][0]}, Last: {item['dates'][-1]}")

        print("\n" + "=" * 60)
        print(f" Successfully parsed {len(parsed_data)} rows")
        print("=" * 60)

        # Write to CSV for manual inspection
        import csv

        output_csv = file_path_obj.with_suffix(".parsed.csv")
        # Always include all months (plastic should cover all; glass may be empty)
        months_present = list(MONTH_MAPPING.keys())
        with open(output_csv, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            # Write header
            writer.writerow(
                [
                    "Seniūnija",
                    "Kaimas",
                    "Gatvė",
                    "Namų numeriai",
                    "Išskyrus",
                    "Atliekos",
                    *months_present,
                ]
            )

            # Write data rows
            for item in parsed_data:
                # Group dates by month
                dates_by_month = {}
                for date in item["dates"]:
                    month_name = list(MONTH_MAPPING.keys())[date.month - 1]
                    if month_name not in dates_by_month:
                        dates_by_month[month_name] = []
                    dates_by_month[month_name].append(date.day)

                # Format dates as "2 d., 16 d." etc.
                parsed_items = item.get("parsed_items") or {}
                parsed_cell = (
                    PdfParsedCell.model_validate(parsed_items)
                    if isinstance(parsed_items, dict)
                    else PdfParsedCell()
                )
                groups = parsed_cell.groups or []
                for group in groups:
                    exclude_str = ", ".join(
                        f"{s.street} {s.house_numbers or ''}".strip() for s in group.exclude_streets
                    )
                    include = group.include_streets
                    if include:
                        for street in include:
                            row = [
                                parsed_cell.seniunija or item.get("seniunija", ""),
                                group.village,
                                street.street,
                                street.house_numbers or "",
                                exclude_str,
                                item.get("waste_type_label") or item["waste_type"],
                            ]
                            for month_name in months_present:
                                if month_name in dates_by_month:
                                    dates_str = ", ".join(
                                        [f"{d} d." for d in sorted(dates_by_month[month_name])]
                                    )
                                    row.append(dates_str)
                                else:
                                    row.append("")
                            writer.writerow(row)
                    else:
                        row = [
                            parsed_cell.seniunija or item.get("seniunija", ""),
                            group.village,
                            "",
                            "",
                            exclude_str,
                            item.get("waste_type_label") or item["waste_type"],
                        ]
                        for month_name in months_present:
                            if month_name in dates_by_month:
                                dates_str = ", ".join(
                                    [f"{d} d." for d in sorted(dates_by_month[month_name])]
                                )
                                row.append(dates_str)
                            else:
                                row.append("")
                        writer.writerow(row)

        print(f"\n📄 Output written to: {output_csv}")
        print("   Compare this with the expected CSV files in samples/")

        # Write normalized row CSV (no street/village split)
        rows_csv = file_path_obj.with_suffix(".rows.csv")
        if normalized_rows:
            row_headers = (
                ["location", "waste_type_cell"]
                + [f"month_{m}" for m in MONTH_MAPPING.keys()]
                + ["table_index", "section_index", "row_index"]
            )
            with open(rows_csv, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=row_headers, extrasaction="ignore")
                writer.writeheader()
                for row in normalized_rows:
                    writer.writerow(row)
            print(f" Row-level output written to: {rows_csv}")

        # Write raw CSV for debugging
        raw_csv = file_path_obj.with_suffix(".raw.csv")
        if raw_rows:
            month_headers = [f"month_{m}" for m in MONTH_MAPPING.keys()]
            raw_headers = (
                ["location", "waste_type_cell"]
                + month_headers
                + ["table_index", "section_index", "row_index"]
            )
            with open(raw_csv, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=raw_headers, extrasaction="ignore")
                writer.writeheader()
                for row in raw_rows:
                    writer.writerow(row)
            print(f" Raw output written to: {raw_csv}")

        return 0

    except Exception as e:
        print(f"\n Error: {e}")
        import traceback

        traceback.print_exc()
        return 1


def main():
    """Main PDF scraper function (CLI entry point)"""
    parser = argparse.ArgumentParser(description="PDF Waste Schedule Scraper (MVP)")
    parser.add_argument("file", type=str, nargs="?", help="Path to PDF file to parse")
    parser.add_argument("--url", type=str, default=None, help="URL to PDF to download and parse")
    parser.add_argument(
        "--source",
        type=str,
        choices=["plastikas", "stiklas"],
        default=None,
        help="Shortcut for configured PDF URL (config.PDF_PLASTIKAS_URL / config.PDF_STIKLAS_URL).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force parsing even if the same URL+content hash was already parsed successfully.",
    )
    parser.add_argument(
        "--skip-ai",
        action="store_true",
        help="Skip AI parsing (default: enabled).",
    )
    parser.add_argument(
        "--year",
        type=int,
        default=2026,
        help="Year for date validation (default: 2026)",
    )
    args = parser.parse_args()

    if args.source and not args.url and not args.file:
        if args.source == "plastikas":
            args.url = getattr(config, "PDF_PLASTIKAS_URL", None)
        elif args.source == "stiklas":
            args.url = getattr(config, "PDF_STIKLAS_URL", None)
        if not args.url:
            parser.error(f"Missing configured PDF URL for source: {args.source}")

    if not args.file and not args.url:
        parser.error("Must provide either a local PDF file path or --url")

    if args.url:
        url = args.url
        print(f"\n1. Fetching PDF from: {url}")

        conn = get_db_connection()
        try:
            remote_source = prepare_remote_source(
                conn,
                kind="pdf",
                source_url=url,
                suffix=".pdf",
                default_source_file="waste_schedule.pdf",
                force=args.force,
                timeout_seconds=60,
            )
        finally:
            conn.close()

        if not remote_source.should_parse:
            print(f" Skip: PDF {remote_source.skip_reason}")
            if remote_source.cleanup_path and remote_source.path and remote_source.path.exists():
                remote_source.path.unlink()
            return 0

        assert remote_source.path is not None
        assert remote_source.content_hash is not None
        local_path = remote_source.path
        source_file = remote_source.source_file or Path(local_path).name
        content_hash = remote_source.content_hash

        try:
            rc = run_pdf_scraper(local_path, args.year, skip_ai=args.skip_ai)
            conn = get_db_connection()
            try:
                _log_fetch(
                    conn,
                    source_url=url,
                    source_file=source_file,
                    content_hash=content_hash,
                    status="success" if rc == 0 else "failed",
                )
                log_prepared_source_fetch(
                    conn,
                    source=remote_source,
                    status="success" if rc == 0 else "failed",
                )
            finally:
                conn.close()
            if remote_source.cleanup_path and local_path.exists():
                local_path.unlink()
            return rc
        except Exception:
            conn = get_db_connection()
            try:
                _log_fetch(
                    conn,
                    source_url=url,
                    source_file=source_file,
                    content_hash=content_hash,
                    status="failed",
                )
                log_prepared_source_fetch(conn, source=remote_source, status="failed")
            finally:
                conn.close()
            if remote_source.cleanup_path and local_path.exists():
                local_path.unlink()
            raise

    return run_pdf_scraper(args.file, args.year, skip_ai=args.skip_ai)


if __name__ == "__main__":
    sys.exit(main())
