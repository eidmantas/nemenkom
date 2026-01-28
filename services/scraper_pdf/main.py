"""
Main script to run the PDF scraper - MVP for testing camelot extraction
"""

import argparse
import logging
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import config
from services.common.logging_utils import setup_logging
from services.scraper_pdf.parser import MONTH_MAPPING, parse_pdf


def run_pdf_scraper(file_path: str, year: int = 2026, skip_ai: bool = False):
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
        stderr_handler.setFormatter(
            logging.Formatter("[%(asctime)s] %(levelname)s: %(message)s")
        )
        pdf_logger.addHandler(stderr_handler)
        pdf_logger.propagate = False
        logging.getLogger("pdfminer").setLevel(logging.WARNING)
        logging.getLogger("camelot").setLevel(logging.WARNING)

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
        file_path = Path(file_path)
        if not file_path.exists():
            print(f"❌ File not found: {file_path}")
            return 1

        print(f"\n1. Parsing PDF: {file_path}")

        # Parse PDF
        parsed_data, raw_rows = parse_pdf(file_path, year, skip_ai=skip_ai)

        if not parsed_data:
            print("\n❌ No data parsed. Exiting.")
            return 1

        print(f"\n2. Parsed {len(parsed_data)} rows")
        print("\n3. Sample output (first 5 rows):")
        print("-" * 60)
        
        for i, item in enumerate(parsed_data[:5]):
            print(f"\nRow {i + 1}:")
            print(f"  Location: {item['kaimai_str'][:80]}...")
            print(f"  Waste Type: {item['waste_type']}")
            print(f"  Dates: {len(item['dates'])} dates")
            if item['dates']:
                print(f"    First: {item['dates'][0]}, Last: {item['dates'][-1]}")

        print("\n" + "=" * 60)
        print(f"✅ Successfully parsed {len(parsed_data)} rows")
        print("=" * 60)
        
        # Write to CSV for manual inspection
        import csv
        output_csv = file_path.with_suffix('.parsed.csv')
        # Always include all months (plastic should cover all; glass may be empty)
        months_present = list(MONTH_MAPPING.keys())
        with open(output_csv, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            # Write header
            writer.writerow([
                'Seniūnija',
                'Kaimas',
                'Gatvė',
                'Namų numeriai',
                'Atliekos',
                *months_present
            ])
            
            # Write data rows
            for item in parsed_data:
                # Group dates by month
                dates_by_month = {}
                for date in item['dates']:
                    month_name = list(MONTH_MAPPING.keys())[date.month - 1]
                    if month_name not in dates_by_month:
                        dates_by_month[month_name] = []
                    dates_by_month[month_name].append(date.day)
                
                # Format dates as "2 d., 16 d." etc.
                parsed_items = item.get("parsed_items") or [(item.get("village", ""), None)]
                for idx, (name, house_numbers) in enumerate(parsed_items):
                    if idx == 0:
                        village = name
                        street = ""
                        house_nums = None
                    else:
                        village = item.get("village", "")
                        street = name
                        house_nums = house_numbers

                    row = [
                        item.get("seniunija", ""),
                        village,
                        street,
                        house_nums or "",
                        item.get('waste_type_label') or item['waste_type'],
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

        # Write raw CSV for debugging
        raw_csv = file_path.with_suffix('.raw.csv')
        if raw_rows:
            month_headers = [f"month_{m}" for m in MONTH_MAPPING.keys()]
            raw_headers = (
                ["location", "waste_type_cell"]
                + month_headers
                + ["table_index", "section_index", "row_index"]
            )
            with open(raw_csv, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(
                    f, fieldnames=raw_headers, extrasaction="ignore"
                )
                writer.writeheader()
                for row in raw_rows:
                    writer.writerow(row)
            print(f"🧪 Raw output written to: {raw_csv}")
        
        return 0

    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return 1


def main():
    """Main PDF scraper function (CLI entry point)"""
    parser = argparse.ArgumentParser(description="PDF Waste Schedule Scraper (MVP)")
    parser.add_argument(
        "file",
        type=str,
        help="Path to PDF file to parse",
    )
    parser.add_argument(
        "--skip-ai",
        action="store_true",
        help="Skip AI parsing (use regex-only parsing). Default: AI enabled",
    )
    parser.add_argument(
        "--year",
        type=int,
        default=2026,
        help="Year for date validation (default: 2026)",
    )
    args = parser.parse_args()

    return run_pdf_scraper(args.file, args.year, skip_ai=args.skip_ai)


if __name__ == "__main__":
    sys.exit(main())
