"""
Fetcher module - Downloads xlsx file from nemenkom.lt
"""

from pathlib import Path

from services.common.fetch_cache import download_url_to_file


def fetch_xlsx(url: str, save_path: Path | None = None) -> tuple[Path, dict[str, str], int]:
    """
    Download xlsx file from URL

    Args:
        url: URL to download from
        save_path: Optional path to save file. If None, uses temp file.

    Returns:
        (Path to downloaded file, response headers, byte length)

    Raises:
        requests.RequestException: If download fails
    """
    if not url or not str(url).strip():
        raise ValueError("XLSX source URL is required")

    print(f"Fetching xlsx from {url}")

    downloaded = download_url_to_file(
        url,
        save_path=save_path,
        suffix=".xlsx",
        default_source_file="waste_schedule.xlsx",
        timeout_seconds=30,
    )
    print(f"Downloaded {downloaded.byte_len} bytes to {downloaded.path}")
    return downloaded.path, downloaded.headers, downloaded.byte_len


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Fetch an XLSX waste schedule source")
    parser.add_argument("url", help="XLSX source URL")
    args = parser.parse_args()

    file_path, _headers, _byte_len = fetch_xlsx(args.url)
    print(f"File saved to: {file_path}")
