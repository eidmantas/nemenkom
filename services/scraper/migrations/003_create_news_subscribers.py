from yoyo import step

steps = [
    step(
        """
        CREATE TABLE IF NOT EXISTS news_subscribers (
            email TEXT PRIMARY KEY,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """,
        "",
    ),
]
