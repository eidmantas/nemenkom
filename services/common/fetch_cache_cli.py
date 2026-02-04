"""
CLI helper to seed / inspect fetch cache.

Use-cases:
- Seed DB with current remote HEAD metadata so scrapers can skip immediately.
- Optionally download once and store the content hash (still no parsing).
"""

from __future__ import annotations

import argparse
from pathlib import Path
from urllib.parse import urlparse

from services.common.db import get_db_connection
from services.common.fetch_cache import (
    head_url,
    log_source_fetch,
    sha256_file,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch cache helper")
    parser.add_argument("--kind", choices=["xlsx", "pdf"], required=True)
    parser.add_argument("--url", required=True)
    parser.add_argument(
        "--download",
        action="store_true",
        help="Also download the file and store sha256 (still does NOT parse).",
    )
    parser.add_argument(
        "--file",
        type=str,
        default=None,
        help="If --download is set, optionally download to this path.",
    )
    args = parser.parse_args()

    url = args.url
    kind = args.kind
    head = head_url(url)
    source_file = Path(urlparse(url).path).name or None

    content_hash = None
    if args.download:
        import requests

        resp = requests.get(url, allow_redirects=True, timeout=60)
        resp.raise_for_status()
        target = Path(args.file) if args.file else None
        if target is None:
            target = Path("/tmp") / (source_file or f"download.{kind}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(resp.content)
        content_hash = sha256_file(target)

    conn = get_db_connection()
    try:
        log_source_fetch(
            conn,
            kind=kind,
            source_url=url,
            source_file=source_file,
            etag=head.etag if head else None,
            last_modified=head.last_modified if head else None,
            content_length=head.content_length if head else None,
            content_hash=content_hash,
            status="seeded",
        )
    finally:
        conn.close()

    print("Seeded fetch cache:")
    print(" kind:", kind)
    print(" url:", url)
    if head:
        print(" etag:", head.etag)
        print(" last_modified:", head.last_modified)
        print(" content_length:", head.content_length)
    if content_hash:
        print(" sha256:", content_hash)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
