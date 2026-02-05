"""
PDF scraper scheduler.

Runs immediately on startup, then schedules runs at 11:00 and 18:00 daily.
Intended for docker-compose service `scraper_pdf`.

Important: With HEAD/hash skipping, "no changes" should result in very little work.
"""

import logging
import os
import sys
import time
from datetime import datetime
from datetime import time as dt_time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import config
from services.common.logging_utils import setup_logging
from services.common.migrations import init_database


def _env_true(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "y", "on"}


def _one_time_flag_path(flag_name: str) -> Path:
    db_dir = Path(__file__).parent.parent / "database"
    return db_dir / f".{flag_name}"


def _run_one(source: str, *, force: bool = False, use_ai: bool = False) -> bool:
    """
    Run scraper_pdf for one configured source.
    Returns True if command completed successfully.
    """
    logger = logging.getLogger(__name__)

    url_attr = "PDF_PLASTIKAS_URL" if source == "plastikas" else "PDF_STIKLAS_URL"
    url = getattr(config, url_attr, None) or os.getenv(url_attr)
    if not url:
        logger.info("Skipping %s: %s not configured", source, url_attr)
        return True

    try:
        # Run via module main to preserve skip logic.
        from services.scraper_pdf.main import main as pdf_main

        argv_prev = sys.argv[:]
        try:
            sys.argv = [
                "services.scraper_pdf.main",
                "--url",
                url,
                "--source",
                source,
                "--year",
                "2026",
            ]
            if use_ai:
                sys.argv.append("--use-ai")
            if force:
                sys.argv.append("--force")
            rc = pdf_main()
        finally:
            sys.argv = argv_prev

        if rc == 0:
            logger.info("scraper_pdf completed successfully for %s", source)
            return True
        logger.warning("scraper_pdf exited with code %s for %s", rc, source)
        return False
    except Exception as e:
        logger.exception("Error running scraper_pdf for %s: %s", source, e)
        return False


def run_pdf_job(*, force: bool = False, use_ai: bool = False) -> bool:
    logger = logging.getLogger(__name__)
    logger.info("Running PDF scraper job")
    ok1 = _run_one("plastikas", force=force, use_ai=use_ai)
    ok2 = _run_one("stiklas", force=force, use_ai=use_ai)
    return ok1 and ok2


def should_run_now() -> bool:
    now = datetime.now()
    current_time = now.time()
    target_times = [dt_time(11, 0), dt_time(18, 0)]
    for target_time in target_times:
        time_diff = abs(
            (
                datetime.combine(now.date(), current_time)
                - datetime.combine(now.date(), target_time)
            ).total_seconds()
        )
        if time_diff < 60:
            return True
    return False


def main() -> None:
    setup_logging()
    logger = logging.getLogger(__name__)
    logger.info("PDF scheduler started")

    # Ensure core tables exist (schedule_groups + calendar_streams + calendar tables).
    scraper_migrations = Path(__file__).parent.parent / "scraper" / "migrations"
    calendar_migrations = Path(__file__).parent.parent / "calendar" / "migrations"
    init_database(migrations_dir=scraper_migrations)
    init_database(migrations_dir=calendar_migrations)

    # Run immediately on startup
    print(
        f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Running initial PDF scrape on startup..."
    )
    use_ai = _env_true("SCRAPER_PDF_USE_AI")
    force_on_start = _env_true("FORCE_PARSE_ON_START") or _env_true("SCRAPER_PDF_FORCE_ON_START")
    flag_path = _one_time_flag_path("force_pdf_on_start_done")
    if force_on_start and not flag_path.exists():
        ok = run_pdf_job(force=True, use_ai=use_ai)
        if ok:
            try:
                flag_path.touch()
            except Exception:
                pass
    else:
        run_pdf_job(use_ai=use_ai)

    last_run_date = datetime.now().date()
    last_run_hour = None
    logger.info("PDF scheduler waiting for scheduled times (11:00 and 18:00)...")
    while True:
        now = datetime.now()
        current_date = now.date()
        if should_run_now():
            target_hour = now.time().hour
            if last_run_date != current_date or last_run_hour != target_hour:
                run_pdf_job(use_ai=use_ai)
                last_run_date = current_date
                last_run_hour = target_hour
        time.sleep(60)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logging.getLogger(__name__).info("PDF scheduler stopped")
        raise SystemExit(0) from None
