from yoyo import step

steps = [
    step(
        """
        CREATE TABLE IF NOT EXISTS calendar_streams (
            id TEXT PRIMARY KEY,
            waste_type TEXT NOT NULL,
            dates_hash TEXT NOT NULL,
            dates TEXT NOT NULL,
            first_date DATE,
            last_date DATE,
            date_count INTEGER,
            calendar_id TEXT,
            calendar_synced_at TIMESTAMP,
            pending_clean_started_at TIMESTAMP,
            pending_clean_until TIMESTAMP,
            pending_clean_notice_sent_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """,
        "",
    ),
    step(
        """
        CREATE TABLE IF NOT EXISTS group_calendar_links (
            schedule_group_id TEXT PRIMARY KEY,
            calendar_stream_id TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (schedule_group_id) REFERENCES schedule_groups(id) ON DELETE CASCADE,
            FOREIGN KEY (calendar_stream_id) REFERENCES calendar_streams(id) ON DELETE CASCADE
        );
        """,
        "",
    ),
    step(
        """
        CREATE INDEX IF NOT EXISTS idx_group_calendar_links_stream
        ON group_calendar_links(calendar_stream_id);
        """,
        "",
    ),
    step(
        """
        CREATE INDEX IF NOT EXISTS idx_calendar_streams_dates_hash
        ON calendar_streams(waste_type, dates_hash);
        """,
        "",
    ),
    # NOTE: Backfill steps removed because we are recreating the database.
]
