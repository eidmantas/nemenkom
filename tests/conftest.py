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
    """Create a temporary database for testing and patch get_db_connection to use it"""
    from unittest.mock import patch
    import services.api.db as api_db_module
    import services.common.db as db_module
    import services.calendar as calendar_module
    import services.common.db_helpers as db_helpers_module
    
    db_fd, db_path = tempfile.mkstemp(suffix='.db')
    conn = sqlite3.connect(db_path)
    
    from services.common.migrations import apply_migrations
    apply_migrations(conn, Path(__file__).parent.parent / "services" / "scraper" / "migrations")
    apply_migrations(conn, Path(__file__).parent.parent / "services" / "calendar" / "migrations")
    conn.commit()
    
    def mock_get_conn():
        return sqlite3.connect(db_path, check_same_thread=False)
    
    # Patch get_db_connection in all modules that use it
    with patch.object(api_db_module, 'get_db_connection', mock_get_conn), \
         patch.object(db_module, 'get_db_connection', mock_get_conn), \
         patch.object(calendar_module, 'get_db_connection', mock_get_conn), \
         patch.object(db_helpers_module, 'get_db_connection', mock_get_conn):
        yield conn, db_path
    
    conn.close()
    os.unlink(db_path)


@pytest.fixture(autouse=True)
def disable_throttle_env():
    os.environ.setdefault("THROTTLE_DISABLED", "1")
    yield


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
    config.addinivalue_line("markers", "real_api: marks tests that make real API calls (Google Calendar, etc.)")


def pytest_addoption(parser):
    """Add custom pytest options"""
    parser.addoption(
        "--use-ai-tokens",
        action="store_true",
        default=False,
        help="Run AI integration tests that use actual tokens (expensive)"
    )
