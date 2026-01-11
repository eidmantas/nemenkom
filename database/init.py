"""
Database initialization script
"""
import sqlite3
import os
from pathlib import Path

DB_PATH = Path(__file__).parent / 'waste_schedule.db'
SCHEMA_PATH = Path(__file__).parent / 'schema.sql'

def init_database():
    """Initialize the SQLite database with schema"""
    # Remove existing database if it exists (for development)
    if DB_PATH.exists():
        print(f"Database already exists at {DB_PATH}")
        return DB_PATH
    
    # Create database connection
    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()
    
    # Read and execute schema
    with open(SCHEMA_PATH, 'r', encoding='utf-8') as f:
        schema_sql = f.read()
    
    cursor.executescript(schema_sql)
    conn.commit()
    conn.close()
    
    print(f"Database initialized at {DB_PATH}")
    return DB_PATH

def get_db_connection():
    """Get a database connection"""
    if not DB_PATH.exists():
        init_database()
    return sqlite3.connect(str(DB_PATH), check_same_thread=False)

if __name__ == '__main__':
    init_database()
