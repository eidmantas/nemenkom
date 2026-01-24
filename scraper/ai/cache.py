"""
Cache for AI parser results to avoid re-parsing the same kaimai strings
Stores results in SQLite database for persistence across runs
"""

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional


class AIParserCache:
    """
    Cache for AI parser results

    Stores parsed results in database so we don't re-parse the same kaimai strings.
    This is critical for efficiency - many kaimai strings are duplicates.
    """

    def __init__(self, db_path: Optional[Path] = None):
        if db_path is None:
            db_path = (
                Path(__file__).parent.parent.parent / "database" / "waste_schedule.db"
            )

        self.db_path = db_path
        self._ensure_cache_table()

    def _ensure_cache_table(self):
        """Create cache table if it doesn't exist"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS ai_parser_cache (
                kaimai_hash TEXT PRIMARY KEY,
                kaimai_str TEXT NOT NULL,
                parsed_result TEXT NOT NULL,  -- JSON string
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

    def get(self, kaimai_str: str) -> Optional[List]:
        """
        Get cached parsed result for a kaimai string

        Args:
            kaimai_str: Original kaimai string

        Returns:
            Parsed result (list of tuples: [(village, None), (street1, house_nums1), ...]) or None if not cached
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Use hash for lookup (faster)
        import hashlib

        kaimai_hash = hashlib.sha256(kaimai_str.encode()).hexdigest()[:16]

        cursor.execute(
            """
            SELECT parsed_result, tokens_used
            FROM ai_parser_cache
            WHERE kaimai_hash = ?
        """,
            (kaimai_hash,),
        )

        row = cursor.fetchone()
        conn.close()

        if row:
            # Update last_used_at
            self._update_last_used(kaimai_hash)

            # Return parsed result (convert lists back to tuples)
            parsed_result = json.loads(row[0])
            # Convert list of lists back to list of tuples
            return [
                tuple(item) if isinstance(item, list) else item
                for item in parsed_result
            ]

        return None

    def _update_last_used(self, kaimai_hash: str):
        """Update last_used_at timestamp"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute(
            """
            UPDATE ai_parser_cache
            SET last_used_at = ?
            WHERE kaimai_hash = ?
        """,
            (datetime.now().isoformat(), kaimai_hash),
        )

        conn.commit()
        conn.close()

    def set(self, kaimai_str: str, parsed_result: List, tokens_used: int = 0):
        """
        Cache a parsed result

        Args:
            kaimai_str: Original kaimai string
            parsed_result: Parsed result (list of tuples: [(village, None), (street1, house_nums1), ...])
            tokens_used: Tokens used for this parse
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        import hashlib

        kaimai_hash = hashlib.sha256(kaimai_str.encode()).hexdigest()[:16]

        # Convert tuples to lists for JSON serialization
        serializable_result = [
            list(item) if isinstance(item, tuple) else item for item in parsed_result
        ]

        cursor.execute(
            """
            INSERT OR REPLACE INTO ai_parser_cache 
            (kaimai_hash, kaimai_str, parsed_result, tokens_used, created_at, last_used_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """,
            (
                kaimai_hash,
                kaimai_str,
                json.dumps(serializable_result),
                tokens_used,
                datetime.now().isoformat(),
                datetime.now().isoformat(),
            ),
        )

        conn.commit()
        conn.close()

    def get_cache_stats(self) -> Dict:
        """Get cache statistics"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("SELECT COUNT(*) FROM ai_parser_cache")
        total_entries = cursor.fetchone()[0]

        cursor.execute("SELECT SUM(tokens_used) FROM ai_parser_cache")
        total_tokens = cursor.fetchone()[0] or 0

        conn.close()

        return {
            "total_entries": total_entries,
            "total_tokens_saved": total_tokens,
        }


# Global cache instance
_cache = None


def get_cache(db_path: Optional[Path] = None) -> AIParserCache:
    """Get or create global cache instance"""
    global _cache
    if _cache is None:
        _cache = AIParserCache(db_path)
    return _cache
