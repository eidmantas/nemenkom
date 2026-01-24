"""
Python-based scheduler for the scraper
Runs immediately on startup, then schedules runs at 11:00 and 18:00 daily
Also runs background worker for calendar sync
"""
import sys
import time
import threading
from datetime import datetime, time as dt_time
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from scraper.main import run_scraper
from api.db import get_schedule_groups_needing_sync
from services.calendar import create_calendar_for_schedule_group, sync_calendar_for_schedule_group

def run_scraper_job():
    """Run the scraper job"""
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Running scraper...")
    try:
        exit_code = run_scraper(skip_ai=False)  # Full parsing with AI (default)
        
        if exit_code == 0:
            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Scraper completed successfully")
        else:
            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Scraper exited with code {exit_code}")
        return exit_code == 0
    except Exception as e:
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Error running scraper: {e}")
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
        time_diff = abs((datetime.combine(now.date(), current_time) - 
                        datetime.combine(now.date(), target_time)).total_seconds())
        if time_diff < 60:  # Within 1 minute
            return True
    return False

def calendar_sync_worker():
    """
    Background worker for calendar creation and sync
    Continuously checks for schedule groups needing sync and processes them
    Retries every 5 minutes on failures (simple approach - no complex rate limiting)
    """
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Calendar sync worker started")
    
    RETRY_INTERVAL_SECONDS = 300  # 5 minutes
    
    while True:
        try:
            # Get groups needing sync
            groups = get_schedule_groups_needing_sync()
            
            if groups:
                print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Found {len(groups)} schedule groups needing sync")
            
            for group in groups:
                schedule_group_id = group['id']
                calendar_id = group.get('calendar_id')
                
                try:
                    # Phase 1: Create calendar if needed
                    if calendar_id is None:
                        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Creating calendar for {schedule_group_id}...")
                        result = create_calendar_for_schedule_group(schedule_group_id)
                        if result and result.get('success'):
                            calendar_id = result['calendar_id']
                            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] ✅ Calendar created: {calendar_id}")
                        else:
                            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] ❌ Failed to create calendar for {schedule_group_id} - will retry in 5 minutes")
                            # Will retry on next cycle (every 5 minutes)
                            continue
                    
                    # Phase 2: Sync events
                    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Syncing events for {schedule_group_id}...")
                    sync_result = sync_calendar_for_schedule_group(schedule_group_id)
                    if sync_result.get('success'):
                        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] ✅ Events synced: "
                              f"added={sync_result.get('events_added', 0)}, "
                              f"deleted={sync_result.get('events_deleted', 0)}, "
                              f"retried={sync_result.get('events_retried', 0)}")
                    else:
                        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] ❌ Failed to sync events: {sync_result.get('error')} - will retry in 5 minutes")
                        # Will retry on next cycle (every 5 minutes)
                
                except Exception as e:
                    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Error processing {schedule_group_id}: {e}")
                    import traceback
                    traceback.print_exc()
                    # Will retry on next cycle (every 5 minutes)
                    continue
            
            # Sleep for 5 minutes before checking again (simple retry approach)
            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Calendar sync worker sleeping for {RETRY_INTERVAL_SECONDS}s...")
            time.sleep(RETRY_INTERVAL_SECONDS)
            
        except Exception as e:
            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Error in calendar sync worker: {e}")
            import traceback
            traceback.print_exc()
            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Retrying in {RETRY_INTERVAL_SECONDS}s...")
            time.sleep(RETRY_INTERVAL_SECONDS)  # Wait 5 minutes before retrying


def main():
    """Main scheduler loop"""
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Scheduler started")
    
    # Start calendar sync worker in background thread
    calendar_thread = threading.Thread(target=calendar_sync_worker, daemon=True)
    calendar_thread.start()
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Calendar sync worker started in background")
    
    # Run immediately on startup
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Running initial scraper on startup...")
    run_scraper_job()
    
    # Track last run time to avoid duplicate runs
    last_run_date = datetime.now().date()
    last_run_hour = None
    
    # Main loop - check every minute
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Scheduler waiting for scheduled times (11:00 and 18:00)...")
    
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

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Scheduler stopped")
        sys.exit(0)
