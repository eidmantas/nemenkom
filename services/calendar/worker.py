"""
Calendar sync worker service.
Creates calendars and keeps events in sync in the background.
"""

import logging
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from services.common.db_helpers import (
    get_calendar_streams_needing_sync,
    get_calendar_streams_pending_cleanup,
)
from services.calendar import (
    create_calendar_for_calendar_stream,
    sync_calendar_for_calendar_stream,
)
from services.common.migrations import init_database
from services.common.logging_utils import setup_logging


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
            pending_streams = get_calendar_streams_pending_cleanup()
            if pending_streams:
                logger.info("Found %s calendar streams pending cleanup", len(pending_streams))

            for stream in pending_streams:
                calendar_stream_id = stream["id"]
                calendar_id = stream.get("calendar_id")
                pending_until = stream.get("pending_clean_until")
                notice_sent_at = stream.get("pending_clean_notice_sent_at")

                try:
                    if calendar_id and not notice_sent_at:
                        logger.info(
                            "Posting cleanup notice for calendar_stream_id=%s",
                            calendar_stream_id,
                        )
                        from services.calendar import post_cleanup_notice_for_stream

                        post_cleanup_notice_for_stream(calendar_stream_id)

                    if pending_until:
                        from datetime import datetime as dt

                        pending_until_dt = dt.fromisoformat(pending_until)
                        if dt.now() >= pending_until_dt:
                            logger.info(
                                "Deleting deprecated calendar for calendar_stream_id=%s",
                                calendar_stream_id,
                            )
                            from services.calendar import delete_calendar_for_stream

                            delete_calendar_for_stream(calendar_stream_id)
                except Exception as e:
                    logger.exception(
                        "Error processing pending cleanup for %s: %s",
                        calendar_stream_id,
                        e,
                    )

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

            logger.info(
                "Calendar sync worker sleeping for %ss...",
                RETRY_INTERVAL_SECONDS,
            )
            time.sleep(RETRY_INTERVAL_SECONDS)

        except Exception as e:
            logger.exception("Error in calendar sync worker: %s", e)
            logger.info("Retrying in %ss...", RETRY_INTERVAL_SECONDS)
            time.sleep(RETRY_INTERVAL_SECONDS)


def main():
    calendar_migrations = Path(__file__).parent / "migrations"
    scraper_migrations = Path(__file__).parent.parent / "scraper" / "migrations"
    init_database(migrations_dir=scraper_migrations)
    init_database(migrations_dir=calendar_migrations)
    calendar_sync_worker()


if __name__ == "__main__":
    main()
