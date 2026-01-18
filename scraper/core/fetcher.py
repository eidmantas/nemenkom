"""
Fetcher module - Downloads xlsx file from nemenkom.lt
"""
import requests
from pathlib import Path
from typing import Optional
import tempfile

# Default URL (will be made dynamic in V1.1)
DEFAULT_URL = "https://www.nemenkom.lt/uploads/failai/atliekos/Buitini%C5%B3%20atliek%C5%B3%20surinkimo%20grafikai/2026%20m-%20sausio-bir%C5%BEelio%20m%C4%97n%20%20Buitini%C5%B3%20atliek%C5%B3%20surinkimo%20grafikas.xlsx"

def fetch_xlsx(url: str = DEFAULT_URL, save_path: Optional[Path] = None) -> Path:
    """
    Download xlsx file from URL
    
    Args:
        url: URL to download from
        save_path: Optional path to save file. If None, uses temp file.
    
    Returns:
        Path to downloaded file
    
    Raises:
        requests.RequestException: If download fails
    """
    print(f"Fetching xlsx from {url}")
    
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    
    if save_path is None:
        # Use temporary file
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.xlsx')
        save_path = Path(temp_file.name)
        temp_file.close()
    
    save_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(save_path, 'wb') as f:
        f.write(response.content)
    
    print(f"Downloaded {len(response.content)} bytes to {save_path}")
    return save_path

if __name__ == '__main__':
    # Test fetch
    file_path = fetch_xlsx()
    print(f"File saved to: {file_path}")
