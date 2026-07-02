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
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

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


@dataclass(frozen=True)
class DownloadedSource:
    path: Path
    source_file: str
    headers: dict[str, str]
    byte_len: int
    content_hash: str


@dataclass(frozen=True)
class PreparedRemoteSource:
    kind: FetchKind
    source_url: str
    path: Path | None
    source_file: str | None
    headers: dict[str, str]
    byte_len: int | None
    content_hash: str | None
    skip_reason: str | None
    cleanup_path: bool

    @property
    def should_parse(self) -> bool:
        return self.skip_reason is None


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


def source_file_name(url: str, *, default_name: str) -> str:
    return Path(urlparse(url).path).name or default_name


def download_url_to_file(
    url: str,
    *,
    save_path: Path | None = None,
    suffix: str = "",
    default_source_file: str = "download",
    timeout_seconds: int = 60,
) -> DownloadedSource:
    if not url or not str(url).strip():
        raise ValueError("Source URL is required")

    resp = requests.get(url, allow_redirects=True, timeout=timeout_seconds)
    resp.raise_for_status()

    content = resp.content
    content_hash = hashlib.sha256(content).hexdigest()
    source_file = source_file_name(str(resp.url or url), default_name=default_source_file)

    if save_path is None:
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
        save_path = Path(tmp.name)
        tmp.close()

    save_path.parent.mkdir(parents=True, exist_ok=True)
    save_path.write_bytes(content)

    return DownloadedSource(
        path=save_path,
        source_file=source_file,
        headers=dict(resp.headers or {}),
        byte_len=len(content),
        content_hash=content_hash,
    )


def has_successful_source_fetch(
    conn: sqlite3.Connection, *, kind: FetchKind, source_url: str, content_hash: str
) -> bool:
    ensure_source_fetches_table(conn)
    row = conn.execute(
        """
        SELECT 1
        FROM source_fetches
        WHERE kind = ? AND source_url = ? AND content_hash = ? AND status = 'success'
        LIMIT 1
        """,
        (kind, source_url, content_hash),
    ).fetchone()
    return bool(row)


def prepare_remote_source(
    conn: sqlite3.Connection,
    *,
    kind: FetchKind,
    source_url: str,
    suffix: str,
    default_source_file: str,
    force: bool = False,
    timeout_seconds: int = 60,
    save_path: Path | None = None,
) -> PreparedRemoteSource:
    """
    Shared remote-source gate for XLSX and PDF scrapers.

    It avoids parse work in two cases:
    - HEAD metadata matches the latest successful/seeded fetch.
    - HEAD was inconclusive, but the downloaded content hash was already parsed successfully.
    """
    cached = get_latest_cached_fetch(conn, kind=kind, source_url=source_url)
    head = head_url(source_url)
    if not force and is_unchanged_by_head(cached=cached, head=head):
        assert head is not None
        hint = head.etag or head.last_modified or "unchanged"
        return PreparedRemoteSource(
            kind=kind,
            source_url=source_url,
            path=None,
            source_file=source_file_name(source_url, default_name=default_source_file),
            headers={},
            byte_len=None,
            content_hash=None,
            skip_reason=f"unchanged (HEAD match: {hint})",
            cleanup_path=False,
        )

    downloaded = download_url_to_file(
        source_url,
        save_path=save_path,
        suffix=suffix,
        default_source_file=default_source_file,
        timeout_seconds=timeout_seconds,
    )
    cleanup_path = save_path is None

    if not force and has_successful_source_fetch(
        conn, kind=kind, source_url=source_url, content_hash=downloaded.content_hash
    ):
        return PreparedRemoteSource(
            kind=kind,
            source_url=source_url,
            path=downloaded.path,
            source_file=downloaded.source_file,
            headers=downloaded.headers,
            byte_len=downloaded.byte_len,
            content_hash=downloaded.content_hash,
            skip_reason=f"already parsed (content hash match: {downloaded.content_hash[:12]})",
            cleanup_path=cleanup_path,
        )

    return PreparedRemoteSource(
        kind=kind,
        source_url=source_url,
        path=downloaded.path,
        source_file=downloaded.source_file,
        headers=downloaded.headers,
        byte_len=downloaded.byte_len,
        content_hash=downloaded.content_hash,
        skip_reason=None,
        cleanup_path=cleanup_path,
    )


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


def log_prepared_source_fetch(
    conn: sqlite3.Connection, *, source: PreparedRemoteSource, status: str
) -> None:
    if source.content_hash is None:
        return

    try:
        content_length_header = source.headers.get("Content-Length")
        content_length = (
            int(content_length_header) if content_length_header is not None else source.byte_len
        )
    except Exception:
        content_length = source.byte_len

    log_source_fetch(
        conn,
        kind=source.kind,
        source_url=source.source_url,
        source_file=source.source_file,
        etag=source.headers.get("ETag"),
        last_modified=source.headers.get("Last-Modified"),
        content_length=content_length,
        content_hash=source.content_hash,
        status=status,
    )
