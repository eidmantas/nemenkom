"""
PDF fetcher - downloads PDF files (plastic/glass) from nemenkom.lt or any URL.
"""

from pathlib import Path

from services.common.fetch_cache import download_url_to_file


def fetch_pdf(
    url: str, save_path: Path | None = None, timeout_seconds: int = 60
) -> tuple[Path, str, dict, int]:
    """
    Download a PDF file and return (path, sha256 hex digest, response headers, byte length).
    """
    downloaded = download_url_to_file(
        url,
        save_path=save_path,
        suffix=".pdf",
        default_source_file="waste_schedule.pdf",
        timeout_seconds=timeout_seconds,
    )
    return downloaded.path, downloaded.content_hash, downloaded.headers, downloaded.byte_len
