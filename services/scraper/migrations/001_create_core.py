from yoyo import step

steps = [
    step(
        """
        CREATE TABLE IF NOT EXISTS data_fetches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fetch_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            source_url TEXT NOT NULL,
            status TEXT NOT NULL,
            validation_errors TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """,
        "",
    ),
    step(
        """
        CREATE TABLE IF NOT EXISTS schedule_groups (
            id TEXT PRIMARY KEY,
            waste_type TEXT NOT NULL DEFAULT 'bendros',
            kaimai_hash TEXT NOT NULL,
            dates TEXT,
            dates_hash TEXT,
            first_date DATE,
            last_date DATE,
            date_count INTEGER,
            calendar_id TEXT,
            calendar_synced_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(kaimai_hash, waste_type)
        );
        """,
        "",
    ),
    step(
        """
        CREATE TABLE IF NOT EXISTS locations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            seniunija TEXT NOT NULL,
            village TEXT NOT NULL,
            street TEXT NOT NULL,
            house_numbers TEXT,
            kaimai_hash TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(seniunija, village, street, house_numbers)
        );
        """,
        "",
    ),
]
