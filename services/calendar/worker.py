"""
Calendar sync worker service.
Creates calendars and keeps events in sync in the background.
"""

import datetime
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from services.calendar import (
    create_calendar_for_calendar_stream,
    delete_calendar_for_stream,
    post_cleanup_notice_for_stream,
    sync_calendar_for_calendar_stream,
)
from services.common.db_helpers import (
    get_calendar_streams_needing_sync,
    get_calendar_streams_pending_cleanup,
)
from services.common.logging_utils import setup_logging
from services.common.migrations import init_database


def calendar_sync_worker():
    """
    Background worker for calendar creation and sync.
    Continuously checks for schedule groups needing sync and processes them.
    Retries every 5 minutes on failures (simple approach - no complex rate limiting).
    """
    setup_logging()
    logger = logging.getLogger(__name__)
    logger.info("Calendar sync worker started")

    RETRY_INTERVAL_SECONDS = 1800  # 30 minutes

    while True:
        try:
            streams = get_calendar_streams_needing_sync()

            if streams:
                logger.info("Found %s calendar streams needing sync", len(streams))

            for stream in streams:
                calendar_stream_id = stream["id"]
                calendar_id = stream.get("calendar_id")
                dates_hash = stream.get("dates_hash", "unknown")

                try:
                    if calendar_id is None:
                        logger.info(
                            "Creating calendar for calendar_stream_id=%s (dates_hash=%s)",
                            calendar_stream_id,
                            dates_hash,
                        )
                        result = create_calendar_for_calendar_stream(calendar_stream_id)
                        if result and result.get("success"):
                            calendar_id = result["calendar_id"]
                            logger.info(
                                "Calendar created for calendar_stream_id=%s: %s",
                                calendar_stream_id,
                                calendar_id,
                            )

                        else:
                            logger.warning(
                                "Failed to create calendar for calendar_stream_id=%s (dates_hash=%s) - will retry in 30 minutes",
                                calendar_stream_id,
                                dates_hash,
                            )
                            continue

                    logger.info("Syncing events for calendar_stream_id=%s", calendar_stream_id)
                    sync_result = sync_calendar_for_calendar_stream(calendar_stream_id)
                    if sync_result.get("success"):
                        logger.info(
                            "Events synced for calendar_stream_id=%s: added=%s, deleted=%s, retried=%s",
                            calendar_stream_id,
                            sync_result.get("events_added", 0),
                            sync_result.get("events_deleted", 0),
                            sync_result.get("events_retried", 0),
                        )
                    else:
                        logger.warning(
                            "Failed to sync events for calendar_stream_id=%s: %s - will retry in 30 minutes",
                            calendar_stream_id,
                            sync_result.get("error"),
                        )

                except Exception as e:
                    logger.exception(
                        "Error processing calendar_stream_id=%s (dates_hash=%s): %s",
                        calendar_stream_id,
                        dates_hash,
                        e,
                    )
                    continue

            cleanup_result = process_pending_cleanup_streams()
            if cleanup_result["noticed"] or cleanup_result["deleted"]:
                logger.info(
                    "Pending cleanup processed: noticed=%s, deleted=%s",
                    cleanup_result["noticed"],
                    cleanup_result["deleted"],
                )

            logger.info(
                "Calendar sync worker sleeping for %ss...",
                RETRY_INTERVAL_SECONDS,
            )
            time.sleep(RETRY_INTERVAL_SECONDS)

        except Exception as e:
            logger.exception("Error in calendar sync worker: %s", e)
            logger.info("Retrying in %ss...", RETRY_INTERVAL_SECONDS)
            time.sleep(RETRY_INTERVAL_SECONDS)


def _parse_db_timestamp(value: str | None) -> datetime.datetime | None:
    if not value:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def process_pending_cleanup_streams(now: datetime.datetime | None = None) -> dict[str, int]:
    """
    Post update notices for deprecated calendars and delete them after the grace period.
    """
    logger = logging.getLogger(__name__)
    current_time = now or datetime.datetime.now()
    noticed = 0
    deleted = 0

    for stream in get_calendar_streams_pending_cleanup():
        calendar_stream_id = stream["id"]
        try:
            pending_clean_until = _parse_db_timestamp(stream.get("pending_clean_until"))
            notice_sent_at = _parse_db_timestamp(stream.get("pending_clean_notice_sent_at"))

            if pending_clean_until and current_time >= pending_clean_until:
                logger.info("Deleting deprecated calendar stream %s", calendar_stream_id)
                delete_calendar_for_stream(calendar_stream_id)
                deleted += 1
                continue

            if not notice_sent_at and stream.get("calendar_id"):
                logger.info("Posting cleanup notice for calendar stream %s", calendar_stream_id)
                post_cleanup_notice_for_stream(calendar_stream_id)
                noticed += 1
        except Exception:
            logger.exception(
                "Failed to process pending cleanup for calendar stream %s",
                calendar_stream_id,
            )

    return {"noticed": noticed, "deleted": deleted}


def main():
    calendar_migrations = Path(__file__).parent / "migrations"
    scraper_migrations = Path(__file__).parent.parent / "scraper" / "migrations"
    init_database(migrations_dir=scraper_migrations)
    init_database(migrations_dir=calendar_migrations)
    calendar_sync_worker()


if __name__ == "__main__":
    main()
