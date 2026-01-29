from yoyo import step

steps = [
    step(
        """CREATE TABLE IF NOT EXISTS calendar_stream_events (
    calendar_stream_id TEXT NOT NULL,
    date DATE NOT NULL,
    event_id TEXT,
    status TEXT DEFAULT 'pending',
    error_message TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (calendar_stream_id, date),
    FOREIGN KEY (calendar_stream_id) REFERENCES calendar_streams(id) ON DELETE CASCADE
);""",
        "",
    ),
]
