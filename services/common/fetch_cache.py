"""
Shared "source fetch cache" for XLSX/PDF downloads.

Goal:
- Allow scrapers to avoid re-downloading AND re-parsing when the remote source hasn't changed.
- Use HTTP HEAD metadata when available (ETag / Last-Modified / Content-Length).
- Fall back to content-hash based logging when we do download.
"""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import requests

FetchKind = Literal["xlsx", "pdf"]


@dataclass(frozen=True)
class HeadMeta:
    url: str
    etag: str | None
    last_modified: str | None
    content_length: int | None


@dataclass(frozen=True)
class CachedFetch:
    kind: str
    source_url: str
    etag: str | None
    last_modified: str | None
    content_length: int | None
    content_hash: str | None
    status: str


def ensure_source_fetches_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS source_fetches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kind TEXT NOT NULL,
            source_url TEXT NOT NULL,
            source_file TEXT,
            etag TEXT,
            last_modified TEXT,
            content_length INTEGER,
            content_hash TEXT,
            status TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_source_fetches_kind_url_created
        ON source_fetches(kind, source_url, created_at)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_source_fetches_kind_url_etag
        ON source_fetches(kind, source_url, etag)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_source_fetches_kind_url_lm_len
        ON source_fetches(kind, source_url, last_modified, content_length)
        """
    )
    conn.commit()


def _parse_int(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except Exception:
        return None


def head_url(url: str, *, timeout_seconds: int = 20) -> HeadMeta | None:
    """
    Best-effort HTTP HEAD request.

    Returns None if HEAD is blocked/failed.
    """
    try:
        resp = requests.head(url, allow_redirects=True, timeout=timeout_seconds)
        # Some servers return 405 for HEAD.
        if resp.status_code >= 400:
            return None
        headers = resp.headers or {}
        etag = headers.get("ETag")
        last_modified = headers.get("Last-Modified")
        content_length = _parse_int(headers.get("Content-Length"))
        return HeadMeta(
            url=str(resp.url or url),
            etag=etag,
            last_modified=last_modified,
            content_length=content_length,
        )
    except Exception:
        return None


def get_latest_cached_fetch(
    conn: sqlite3.Connection, *, kind: FetchKind, source_url: str
) -> CachedFetch | None:
    ensure_source_fetches_table(conn)
    row = conn.execute(
        """
        SELECT kind, source_url, etag, last_modified, content_length, content_hash, status
        FROM source_fetches
        WHERE kind = ? AND source_url = ? AND status IN ('success', 'seeded')
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (kind, source_url),
    ).fetchone()
    if not row:
        return None
    return CachedFetch(
        kind=row[0],
        source_url=row[1],
        etag=row[2],
        last_modified=row[3],
        content_length=row[4],
        content_hash=row[5],
        status=row[6],
    )


def is_unchanged_by_head(*, cached: CachedFetch | None, head: HeadMeta | None) -> bool:
    """
    Decide if a remote resource is unchanged, based only on HEAD metadata.

    Rules (conservative):
    - If ETag is present and matches -> unchanged
    - Else if both Last-Modified and Content-Length are present and match -> unchanged
    - Else -> unknown/changed (do download)
    """
    if not cached or not head:
        return False

    if head.etag and cached.etag and head.etag == cached.etag:
        return True

    if (
        head.last_modified
        and cached.last_modified
        and head.content_length is not None
        and cached.content_length is not None
        and head.last_modified == cached.last_modified
        and head.content_length == cached.content_length
    ):
        return True

    return False


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def log_source_fetch(
    conn: sqlite3.Connection,
    *,
    kind: FetchKind,
    source_url: str,
    source_file: str | None,
    etag: str | None,
    last_modified: str | None,
    content_length: int | None,
    content_hash: str | None,
    status: str,
) -> None:
    ensure_source_fetches_table(conn)
    conn.execute(
        """
        INSERT INTO source_fetches (
            kind, source_url, source_file, etag, last_modified, content_length, content_hash, status
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            kind,
            source_url,
            source_file,
            etag,
            last_modified,
            content_length,
            content_hash,
            status,
        ),
    )
    conn.commit()
