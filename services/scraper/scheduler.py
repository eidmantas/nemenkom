"""
Python-based scheduler for the scraper
Runs immediately on startup, then schedules runs at 11:00 and 18:00 daily
"""

import sys
import time
from datetime import datetime
from datetime import time as dt_time
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from services.common.migrations import init_database
from services.scraper.main import run_scraper


def run_scraper_job():
    """Run the scraper job"""
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Running scraper...")
    try:
        exit_code = run_scraper(skip_ai=False)  # Full parsing with AI (default)

        if exit_code == 0:
            print(
                f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Scraper completed successfully"
            )
        else:
            print(
                f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Scraper exited with code {exit_code}"
            )
        return exit_code == 0
    except Exception as e:
        print(
            f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Error running scraper: {e}"
        )
        import traceback

        traceback.print_exc()
        return False


def should_run_now():
    """Check if we should run the scraper now (11:00 or 18:00)"""
    now = datetime.now()
    current_time = now.time()

    # Check if current time is 11:00 or 18:00 (within 1 minute tolerance)
    target_times = [dt_time(11, 0), dt_time(18, 0)]

    for target_time in target_times:
        time_diff = abs(
            (
                datetime.combine(now.date(), current_time)
                - datetime.combine(now.date(), target_time)
            ).total_seconds()
        )
        if time_diff < 60:  # Within 1 minute
            return True
    return False


def main():
    """Main scheduler loop"""
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Scheduler started")

    # Ensure scraper-owned migrations are applied on container start.
    migrations_dir = Path(__file__).parent / "migrations"
    init_database(migrations_dir=migrations_dir)

    # Run immediately on startup
    print(
        f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Running initial scraper on startup..."
    )
    run_scraper_job()

    # Track last run time to avoid duplicate runs
    last_run_date = datetime.now().date()
    last_run_hour = None

    # Main loop - check every minute
    print(
        f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Scheduler waiting for scheduled times (11:00 and 18:00)..."
    )

    while True:
        now = datetime.now()
        current_time = now.time()
        current_date = now.date()

        # Check if it's 11:00 or 18:00 and we haven't run yet today at this hour
        if should_run_now():
            target_hour = current_time.hour
            # Only run if we haven't run at this hour today
            if last_run_date != current_date or last_run_hour != target_hour:
                run_scraper_job()
                last_run_date = current_date
                last_run_hour = target_hour

        # Sleep for 60 seconds before checking again
        time.sleep(60)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Scheduler stopped")
        sys.exit(0)
