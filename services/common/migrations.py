"""
Shared migration runner for service-owned migrations.
"""

import sqlite3
from pathlib import Path

from services.common.db import DB_PATH

MIGRATIONS_TABLE = "schema_migrations"


def init_database(migrations_dir: Path) -> Path:
    """Initialize the SQLite database and apply migrations for a service."""
    conn = sqlite3.connect(str(DB_PATH))
    apply_migrations(conn, migrations_dir=migrations_dir)
    conn.close()
    return DB_PATH


def apply_migrations(conn: sqlite3.Connection, migrations_dir: Path) -> None:
    """Apply SQL migrations in order and record them in schema_migrations."""
    cursor = conn.cursor()
    cursor.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {MIGRATIONS_TABLE} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT NOT NULL UNIQUE,
            applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """
    )

    applied = {
        row[0]
        for row in cursor.execute(
            f"SELECT filename FROM {MIGRATIONS_TABLE}"
        ).fetchall()
    }

    migration_files = sorted(migrations_dir.rglob("*.sql"))
    for migration_file in migration_files:
        name = migration_file.relative_to(migrations_dir).as_posix()
        if name in applied:
            continue

        sql = migration_file.read_text(encoding="utf-8")
        cursor.executescript(sql)
        cursor.execute(
            f"INSERT INTO {MIGRATIONS_TABLE} (filename) VALUES (?)", (name,)
        )
        conn.commit()
