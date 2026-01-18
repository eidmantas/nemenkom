"""
Pytest fixtures for testing
"""
import pytest
import sqlite3
import tempfile
from pathlib import Path
import sys
import os

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.fixture
def temp_db():
    """Create a temporary database for testing"""
    db_fd, db_path = tempfile.mkstemp(suffix='.db')
    conn = sqlite3.connect(db_path)
    
    # Read and execute schema
    schema_path = Path(__file__).parent.parent / 'database' / 'schema.sql'
    with open(schema_path, 'r', encoding='utf-8') as f:
        schema_sql = f.read()
    conn.executescript(schema_sql)
    conn.commit()
    
    yield conn, db_path
    
    conn.close()
    os.unlink(db_path)


@pytest.fixture
def sample_xlsx_path():
    """Path to sample XLSX file"""
    return Path(__file__).parent / 'fixtures' / 'sample_schedule.xlsx'
