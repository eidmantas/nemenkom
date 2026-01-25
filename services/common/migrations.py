"""
Shared migration runner for service-owned migrations.
"""
from pathlib import Path

from yoyo import get_backend, read_migrations

from services.common.db import DB_PATH


def run_migrations(db_path: Path, migrations_dir: Path) -> None:
    """Apply migrations from a directory to a SQLite database."""
    backend = get_backend(f"sqlite:///{db_path}")
    migrations = read_migrations(str(migrations_dir))
    backend.apply_migrations(backend.to_apply(migrations))


def init_database(migrations_dir: Path) -> Path:
    """Initialize the SQLite database and apply migrations for a service."""
    run_migrations(DB_PATH, migrations_dir)
    return DB_PATH


if __name__ == "__main__":
    raise SystemExit("Use init_database(migrations_dir=...) from a service.")
