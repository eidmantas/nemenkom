"""
PDF fetcher - downloads PDF files (plastic/glass) from nemenkom.lt or any URL.
"""

import hashlib
import tempfile
from pathlib import Path
from urllib.parse import urlparse

import requests


def fetch_pdf(
    url: str, save_path: Path | None = None, timeout_seconds: int = 60
) -> tuple[Path, str, dict, int]:
    """
    Download a PDF file and return (path, sha256 hex digest, response headers, byte length).
    """
    resp = requests.get(url, allow_redirects=True, timeout=timeout_seconds)
    resp.raise_for_status()

    content = resp.content
    sha = hashlib.sha256(content).hexdigest()

    if save_path is None:
        name = Path(urlparse(url).path).name or "waste_schedule.pdf"
        tmp = Path(tempfile.gettempdir()) / name
        save_path = tmp

    save_path.parent.mkdir(parents=True, exist_ok=True)
    save_path.write_bytes(content)
    return save_path, sha, dict(resp.headers or {}), len(content)
