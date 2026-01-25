from yoyo import step

steps = [
    step(
        """CREATE TABLE IF NOT EXISTS calendar_events (
    schedule_group_id TEXT NOT NULL,
    date DATE NOT NULL,
    event_id TEXT,
    status TEXT DEFAULT 'pending',
    error_message TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (schedule_group_id, date),
    FOREIGN KEY (schedule_group_id) REFERENCES schedule_groups(id) ON DELETE CASCADE
);""",
        "",
    ),
]
