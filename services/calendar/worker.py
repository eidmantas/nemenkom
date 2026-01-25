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

from services.common.db_helpers import get_schedule_groups_needing_sync
from services.calendar import create_calendar_for_schedule_group, sync_calendar_for_schedule_group
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

    RETRY_INTERVAL_SECONDS = 300  # 5 minutes

    while True:
        try:
            groups = get_schedule_groups_needing_sync()

            if groups:
                logger.info("Found %s schedule groups needing sync", len(groups))

            for group in groups:
                schedule_group_id = group["id"]
                calendar_id = group.get("calendar_id")
                kaimai_hash = group.get("kaimai_hash", "unknown")

                try:
                    if calendar_id is None:
                        logger.info(
                            "Creating calendar for schedule_group_id=%s (kaimai_hash=%s)",
                            schedule_group_id,
                            kaimai_hash,
                        )
                        result = create_calendar_for_schedule_group(schedule_group_id)
                        if result and result.get("success"):
                            calendar_id = result["calendar_id"]
                            logger.info(
                                "Calendar created for schedule_group_id=%s: %s",
                                schedule_group_id,
                                calendar_id,
                            )

                        else:
                            logger.warning(
                                "Failed to create calendar for schedule_group_id=%s (kaimai_hash=%s) - will retry in 5 minutes",
                                schedule_group_id,
                                kaimai_hash,
                            )
                            continue

                    logger.info("Syncing events for schedule_group_id=%s", schedule_group_id)
                    sync_result = sync_calendar_for_schedule_group(schedule_group_id)
                    if sync_result.get("success"):
                        logger.info(
                            "Events synced for schedule_group_id=%s: added=%s, deleted=%s, retried=%s",
                            schedule_group_id,
                            sync_result.get("events_added", 0),
                            sync_result.get("events_deleted", 0),
                            sync_result.get("events_retried", 0),
                        )
                    else:
                        logger.warning(
                            "Failed to sync events for schedule_group_id=%s: %s - will retry in 5 minutes",
                            schedule_group_id,
                            sync_result.get("error"),
                        )

                except Exception as e:
                    logger.exception(
                        "Error processing schedule_group_id=%s (kaimai_hash=%s): %s",
                        schedule_group_id,
                        kaimai_hash,
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
    migrations_dir = Path(__file__).parent / "migrations"
    init_database(migrations_dir=migrations_dir)
    calendar_sync_worker()


if __name__ == "__main__":
    main()
