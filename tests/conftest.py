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


@pytest.fixture
def temp_cache_db():
    """Create a temporary cache database for AI integration tests
    
    This ensures tests use fresh API calls and don't rely on existing cache.
    """
    db_fd, db_path = tempfile.mkstemp(suffix='.db')
    os.close(db_fd)  # Close file descriptor, we'll use the path
    
    # Create cache table in temp DB
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS ai_parser_cache (
            kaimai_hash TEXT PRIMARY KEY,
            kaimai_str TEXT NOT NULL,
            parsed_result TEXT NOT NULL,
            tokens_used INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_used_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_ai_cache_kaimai_str 
        ON ai_parser_cache(kaimai_str)
    """)
    conn.commit()
    conn.close()
    
    yield Path(db_path)
    
    # Cleanup
    if os.path.exists(db_path):
        os.unlink(db_path)


def pytest_configure(config):
    """Register custom markers"""
    config.addinivalue_line("markers", "ai_integration: marks tests that use real AI tokens")


def pytest_addoption(parser):
    """Add custom pytest options"""
    parser.addoption(
        "--use-ai-tokens",
        action="store_true",
        default=False,
        help="Run AI integration tests that use actual tokens (expensive)"
    )
