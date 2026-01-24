"""
Database initialization script
"""
import sqlite3
import os
from pathlib import Path

DB_PATH = Path(__file__).parent / 'waste_schedule.db'
SCHEMA_PATH = Path(__file__).parent / 'schema.sql'

def init_database():
    """Initialize the SQLite database with schema and run migrations"""
    # Create database connection
    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()
    
    # Check if database already exists
    db_exists = DB_PATH.exists() and DB_PATH.stat().st_size > 0
    
    if not db_exists:
        # Read and execute schema for new database
        with open(SCHEMA_PATH, 'r', encoding='utf-8') as f:
            schema_sql = f.read()
        
        cursor.executescript(schema_sql)
        conn.commit()
        print(f"Database initialized at {DB_PATH}")
    else:
        print(f"Database already exists at {DB_PATH}, running migrations...")
    
    # Always run migrations (they check if columns exist)
    run_migrations(cursor)
    conn.commit()
    conn.close()
    
    return DB_PATH

def run_migrations(cursor):
    """Run database migrations for existing databases"""
    # Migration: Add calendar_id column to schedule_groups if it doesn't exist
    try:
        cursor.execute("SELECT calendar_id FROM schedule_groups LIMIT 1")
    except sqlite3.OperationalError:
        # Column doesn't exist, add it
        print("Running migration: Adding calendar_id column to schedule_groups...")
        cursor.execute("ALTER TABLE schedule_groups ADD COLUMN calendar_id TEXT")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_schedule_groups_calendar_id ON schedule_groups(calendar_id)")
        print("✅ Migration completed: calendar_id column added")

def get_db_connection():
    """Get a database connection"""
    if not DB_PATH.exists():
        init_database()
    return sqlite3.connect(str(DB_PATH), check_same_thread=False)

if __name__ == '__main__':
    init_database()
