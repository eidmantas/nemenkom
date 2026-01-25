"""
Calendar sync worker service.
Creates calendars and keeps events in sync in the background.
"""

import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from services.common.db_helpers import get_schedule_groups_needing_sync
from services.calendar import create_calendar_for_schedule_group, sync_calendar_for_schedule_group
from services.common.migrations import init_database


def calendar_sync_worker():
    """
    Background worker for calendar creation and sync.
    Continuously checks for schedule groups needing sync and processes them.
    Retries every 5 minutes on failures (simple approach - no complex rate limiting).
    """
    print(
        f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Calendar sync worker started"
    )

    RETRY_INTERVAL_SECONDS = 300  # 5 minutes

    while True:
        try:
            groups = get_schedule_groups_needing_sync()

            if groups:
                print(
                    f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Found {len(groups)} schedule groups needing sync"
                )

            for group in groups:
                schedule_group_id = group["id"]
                calendar_id = group.get("calendar_id")
                kaimai_hash = group.get("kaimai_hash", "unknown")

                try:
                    if calendar_id is None:
                        print(
                            f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Creating calendar for schedule_group_id={schedule_group_id} (kaimai_hash={kaimai_hash})..."
                        )
                        result = create_calendar_for_schedule_group(schedule_group_id)
                        if result and result.get("success"):
                            calendar_id = result["calendar_id"]
                            print(
                                f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] ✅ Calendar created for schedule_group_id={schedule_group_id}: {calendar_id}"
                            )

                        else:
                            print(
                                f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] ❌ Failed to create calendar for schedule_group_id={schedule_group_id} (kaimai_hash={kaimai_hash}) - will retry in 5 minutes"
                            )
                            continue

                    print(
                        f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Syncing events for schedule_group_id={schedule_group_id}..."
                    )
                    sync_result = sync_calendar_for_schedule_group(schedule_group_id)
                    if sync_result.get("success"):
                        print(
                            f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] ✅ Events synced for schedule_group_id={schedule_group_id}: "
                            f"added={sync_result.get('events_added', 0)}, "
                            f"deleted={sync_result.get('events_deleted', 0)}, "
                            f"retried={sync_result.get('events_retried', 0)}"
                        )
                    else:
                        print(
                            f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] ❌ Failed to sync events for schedule_group_id={schedule_group_id}: {sync_result.get('error')} - will retry in 5 minutes"
                        )

                except Exception as e:
                    print(
                        f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Error processing schedule_group_id={schedule_group_id} (kaimai_hash={kaimai_hash}): {e}"
                    )
                    import traceback

                    traceback.print_exc()
                    continue

            print(
                f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Calendar sync worker sleeping for {RETRY_INTERVAL_SECONDS}s..."
            )
            time.sleep(RETRY_INTERVAL_SECONDS)

        except Exception as e:
            print(
                f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Error in calendar sync worker: {e}"
            )
            import traceback

            traceback.print_exc()
            print(
                f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Retrying in {RETRY_INTERVAL_SECONDS}s..."
            )
            time.sleep(RETRY_INTERVAL_SECONDS)


def main():
    migrations_dir = Path(__file__).parent / "migrations"
    init_database(migrations_dir=migrations_dir)
    calendar_sync_worker()


if __name__ == "__main__":
    main()
