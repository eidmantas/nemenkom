import pytest

from services.scraper.core.fetcher import fetch_xlsx


def test_fetch_xlsx_requires_source_url():
    with pytest.raises(ValueError, match="XLSX source URL is required"):
        fetch_xlsx("")
