"""
Fetcher module - Downloads xlsx file from nemenkom.lt
"""

import tempfile
from pathlib import Path

import requests


def fetch_xlsx(
    url: str, save_path: Path | None = None
) -> tuple[Path, dict[str, str], int]:
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

    response = requests.get(url, allow_redirects=True, timeout=30)
    response.raise_for_status()

    if save_path is None:
        # Use temporary file
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx")
        save_path = Path(temp_file.name)
        temp_file.close()

    save_path.parent.mkdir(parents=True, exist_ok=True)

    with open(save_path, "wb") as f:
        f.write(response.content)

    print(f"Downloaded {len(response.content)} bytes to {save_path}")
    return save_path, dict(response.headers or {}), len(response.content)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Fetch an XLSX waste schedule source")
    parser.add_argument("url", help="XLSX source URL")
    args = parser.parse_args()

    file_path, _headers, _byte_len = fetch_xlsx(args.url)
    print(f"File saved to: {file_path}")
