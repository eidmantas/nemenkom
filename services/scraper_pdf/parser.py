"""
PDF Parser module - Extracts tables from PDF using marker-pdf (HTML output).
"""

# Flow overview:
# 1) marker-pdf HTML -> DataFrames
# 2) header/section normalization
# 3) row-level normalization (location + month values)
# 4) optional AI split to villages/streets
# 5) dedupe + persistence

import datetime
import hashlib
import json
import logging
import re
import sqlite3
import time
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import cast

import pandas as pd
import requests
from pydantic import BaseModel, Field

import config
from services.common.db import get_db_connection
from services.common.throttle import backoff, throttle
from services.scraper.ai.parser import get_model_rotation, is_rate_limit_error

#
# Previous retry/rotation loop (kept for reference):
# from services.common.throttle import backoff, throttle
# from services.scraper.ai.parser import _is_rate_limit_error, get_model_rotation
# attempt_index = 0
# while True:
#     try:
#         throttle("ai")
#         provider_name, model_id = model_rotation[attempt_index % len(model_rotation)]
#         logger.info(
#             "PDF AI parse attempt %s using %s:%s",
#             attempt_index + 1,
#             provider_name,
#             model_id,
#         )
#         provider_config = _get_provider_config(provider_name)
#         api_key = provider_config.get("api_key")
#         if not api_key:
#             raise ValueError(f"Missing API key for AI provider: {provider_name}")
from services.scraper.core.db_writer import (
    find_or_create_calendar_stream,
    find_or_create_schedule_group,
    generate_dates_hash,
    generate_kaimai_hash,
    get_calendar_stream_id_for_schedule_group,
    reconcile_calendar_streams,
    upsert_group_calendar_link,
)
from services.scraper_pdf.mapping import apply_mappings


class PdfParsedStreet(BaseModel):
    street: str
    house_numbers: str | None = None  # allow "all" or explicit ranges


class PdfParsedGroup(BaseModel):
    seniunija: str | None = None
    village: str
    include_streets: list[PdfParsedStreet] = Field(default_factory=list)
    exclude_streets: list[PdfParsedStreet] = Field(default_factory=list)


class PdfParsedCell(BaseModel):
    seniunija: str | None = None
    groups: list[PdfParsedGroup] = Field(default_factory=list)


# Lithuanian month names (genitive case as they appear in column headers)
MONTH_MAPPING = {
    "Sausio": 1,
    "Vasario": 2,
    "Kovo": 3,
    "Balandžio": 4,
    "Gegužės": 5,
    "Birželio": 6,
    "Liepos": 7,
    "Rugpjūčio": 8,
    "Rugsėjo": 9,
    "Spalio": 10,
    "Lapkričio": 11,
    "Gruodžio": 12,
}

MONTH_ALIASES = {
    "sausis": "Sausio",
    "sausio": "Sausio",
    "vasaris": "Vasario",
    "vasario": "Vasario",
    "kovas": "Kovo",
    "kovo": "Kovo",
    "balandis": "Balandžio",
    "balandžio": "Balandžio",
    "gegužė": "Gegužės",
    "gegužes": "Gegužės",
    "gegužės": "Gegužės",
    "birželis": "Birželio",
    "birzelis": "Birželio",
    "birželio": "Birželio",
    "liepa": "Liepos",
    "liepos": "Liepos",
    "rugpjūtis": "Rugpjūčio",
    "rugpjucio": "Rugpjūčio",
    "rugpjūčio": "Rugpjūčio",
    "rugsėjis": "Rugsėjo",
    "rugsejo": "Rugsėjo",
    "rugsėjo": "Rugsėjo",
    "spalis": "Spalio",
    "spalio": "Spalio",
    "lapkritis": "Lapkričio",
    "lapkričio": "Lapkričio",
    "gruodis": "Gruodžio",
    "gruodžio": "Gruodžio",
}

DEFAULT_HEADER = [
    "Seniūnijos pavadinimas (gyvenvietės pavadinimas)",
    "Atliekos",
    "Sausio",
    "Vasario",
    "Kovo",
    "Balandžio",
    "Gegužės",
    "Birželio",
    "Liepos",
    "Rugpjūčio",
    "Rugsėjo",
    "Spalio",
    "Lapkričio",
    "Gruodžio",
]


def parse_street_with_house_numbers(street_str: str) -> tuple[str, str | None]:
    """
    Parse street name and optional house number restrictions.
    Duplicated from XLSX scraper to keep PDF parsing isolated.
    """
    if not street_str or pd.isna(street_str):
        return ("", None)

    street_str = str(street_str).strip()

    match = re.match(r"^(.+?)\s*,\s*\((.+)\)\s*$", street_str)
    if match:
        street = match.group(1).strip()
        house_nums = match.group(2).strip()
        return (street, house_nums if house_nums else None)

    match = re.match(r"^(.+?)\s+\((.+)\)\s*$", street_str)
    if match:
        street = match.group(1).strip()
        house_nums = match.group(2).strip()
        return (street, house_nums if house_nums else None)

    match = re.match(r"^(.+?\s+g\.?)\s+(.+)$", street_str)
    if match:
        street = match.group(1).strip()
        potential_nums = match.group(2).strip()
        if re.search(r"\d|nuo|iki|Nr", potential_nums, re.IGNORECASE):
            return (street, potential_nums)

    match = re.match(r"^(.+?)\s*,\s*(nuo\s+.+)$", street_str, re.IGNORECASE)
    if match:
        street = match.group(1).strip()
        house_nums = match.group(2).strip()
        return (street, house_nums)

    return (street_str, None)


def parse_village_and_streets(kaimai_str: str) -> list[tuple[str, str | None]]:
    """
    Parse village name and list of streets (with optional house numbers).
    Duplicated from XLSX scraper to keep PDF parsing isolated.
    """
    if pd.isna(kaimai_str) or not kaimai_str:
        return []

    kaimai_str = str(kaimai_str).strip()

    match = re.match(r"^(.+?)\s*\((.+)\)\s*$", kaimai_str)
    if match:
        village = str(match.group(1)).strip()
        streets_str = match.group(2).strip()

        parts = []
        current_part = ""
        paren_depth = 0

        for char in streets_str:
            if char == "(":
                paren_depth += 1
                current_part += char
            elif char == ")":
                paren_depth -= 1
                current_part += char
            elif char == "," and paren_depth == 0:
                if current_part.strip():
                    parts.append(current_part.strip())
                current_part = ""
            else:
                current_part += char

        if current_part.strip():
            parts.append(current_part.strip())

        streets: list[tuple[str, str | None]] = []
        for part in parts:
            street, house_nums = parse_street_with_house_numbers(part)
            if street:
                streets.append((street, house_nums))

        return [(village, None)] + streets

    return [(kaimai_str.strip(), None)]


logger = logging.getLogger(__name__)


def _dump_pdf_ai_failure(
    *,
    provider_name: str,
    model_id: str,
    waste_type: str,
    prompt: str,
    response_text: str,
    error: str,
) -> None:
    try:
        path = Path("tmp/pdf_ai_failures.jsonl")
        payload = {
            "ts": datetime.datetime.utcnow().isoformat() + "Z",
            "provider": provider_name,
            "model": model_id,
            "waste_type": waste_type,
            "error": error,
            "prompt": prompt,
            "response": response_text,
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except Exception as dump_exc:
        logger.warning("Failed to dump PDF AI failure payload: %s", dump_exc)


def _extract_retry_delay_seconds(response_text: str) -> float | None:
    try:
        payload = json.loads(response_text)
    except json.JSONDecodeError:
        return None
    error_obj = None
    if isinstance(payload, dict):
        error_obj = payload.get("error")
    elif isinstance(payload, list) and payload and isinstance(payload[0], dict):
        error_obj = payload[0].get("error")
    if not isinstance(error_obj, dict):
        return None
    details = error_obj.get("details") or []
    if not isinstance(details, list):
        return None
    for item in details:
        if not isinstance(item, dict):
            continue
        retry_delay = item.get("retryDelay")
        if isinstance(retry_delay, str) and retry_delay.endswith("s"):
            try:
                return float(retry_delay[:-1])
            except ValueError:
                return None
    return None


_DISABLED_AI_PROVIDERS: set[str] = set()
PDF_AI_TIMEOUT_SECONDS = 300


class HTMLTableParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tables: list[list[list[str]]] = []
        self._in_table = False
        self._in_row = False
        self._in_cell = False
        self._current_table: list[list[str]] = []
        self._current_row: list[str] = []
        self._current_cell: list[str] = []
        self._current_cell_colspan = 1
        self._current_cell_rowspan = 1
        self._col_idx = 0
        # Track rowspans/colspans so header rows stay aligned across pages.
        self._rowspans: list[dict[str, object]] = []

    def _ensure_rowspans_len(self, length: int) -> None:
        while len(self._rowspans) < length:
            self._rowspans.append({"remaining": 0, "value": ""})

    def _fill_active_spans(self) -> None:
        while self._col_idx < len(self._rowspans):
            span = self._rowspans[self._col_idx]
            remaining = int(span.get("remaining", 0) or 0)
            if remaining <= 0:
                break
            self._current_row.append(str(span.get("value", "")).strip())
            span["remaining"] = remaining - 1
            self._col_idx += 1

    def _append_cell(self, cell_text: str, colspan: int, rowspan: int) -> None:
        self._fill_active_spans()
        colspan = max(1, int(colspan))
        rowspan = max(1, int(rowspan))
        self._ensure_rowspans_len(self._col_idx + colspan)
        for offset in range(colspan):
            self._current_row.append(cell_text)
            if rowspan > 1:
                self._rowspans[self._col_idx + offset] = {
                    "remaining": rowspan - 1,
                    "value": cell_text,
                }
            self._col_idx += 1

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self._in_table = True
            self._current_table = []
            self._rowspans = []
        elif tag == "tr" and self._in_table:
            self._in_row = True
            self._current_row = []
            self._col_idx = 0
        elif tag in ("td", "th") and self._in_row:
            self._in_cell = True
            self._current_cell = []
            attrs_dict = dict(attrs or [])
            self._current_cell_colspan = int(attrs_dict.get("colspan", 1) or 1)
            self._current_cell_rowspan = int(attrs_dict.get("rowspan", 1) or 1)
        elif tag == "br" and self._in_cell:
            self._current_cell.append("\n")

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._in_cell:
            cell_text = "".join(self._current_cell).strip()
            self._append_cell(cell_text, self._current_cell_colspan, self._current_cell_rowspan)
            self._in_cell = False
            self._current_cell = []
        elif tag == "tr" and self._in_row:
            self._fill_active_spans()
            if any(cell.strip() for cell in self._current_row):
                self._current_table.append(self._current_row)
            self._in_row = False
            self._current_row = []
        elif tag == "table" and self._in_table:
            if self._current_table:
                self.tables.append(self._current_table)
            self._in_table = False
            self._current_table = []

    def handle_data(self, data):
        if self._in_cell:
            self._current_cell.append(data)


def ensure_pdf_ai_cache_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS pdf_ai_parser_cache (
            kaimai_hash TEXT NOT NULL,
            kaimai_str TEXT NOT NULL,
            waste_type TEXT NOT NULL,
            parsed_result TEXT NOT NULL,
            tokens_used INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_used_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (kaimai_hash, waste_type)
        )
        """
    )
    conn.commit()


def get_pdf_ai_cache(kaimai_str: str, waste_type: str) -> PdfParsedCell | None:
    conn = get_db_connection()
    ensure_pdf_ai_cache_table(conn)
    kaimai_hash = generate_kaimai_hash(kaimai_str)
    row = conn.execute(
        """
        SELECT parsed_result
        FROM pdf_ai_parser_cache
        WHERE kaimai_hash = ? AND waste_type = ?
        """,
        (kaimai_hash, waste_type),
    ).fetchone()
    if row:
        conn.execute(
            """
            UPDATE pdf_ai_parser_cache
            SET last_used_at = CURRENT_TIMESTAMP
            WHERE kaimai_hash = ? AND waste_type = ?
            """,
            (kaimai_hash, waste_type),
        )
        conn.commit()
        conn.close()
        try:
            return PdfParsedCell.model_validate_json(row[0])
        except Exception:
            return None
    conn.close()
    return None


def set_pdf_ai_cache(kaimai_str: str, waste_type: str, parsed: PdfParsedCell) -> None:
    conn = get_db_connection()
    ensure_pdf_ai_cache_table(conn)
    kaimai_hash = generate_kaimai_hash(kaimai_str)
    payload = parsed.model_dump_json()
    conn.execute(
        """
        INSERT INTO pdf_ai_parser_cache (
            kaimai_hash, kaimai_str, waste_type, parsed_result, tokens_used
        )
        VALUES (?, ?, ?, ?, 0)
        ON CONFLICT(kaimai_hash, waste_type) DO UPDATE SET
            parsed_result = excluded.parsed_result,
            last_used_at = CURRENT_TIMESTAMP
        """,
        (kaimai_hash, kaimai_str, waste_type, payload),
    )
    conn.commit()
    conn.close()


def ensure_pdf_parsed_rows_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS pdf_parsed_rows (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_file TEXT NOT NULL,
            source_year INTEGER,
            waste_type TEXT NOT NULL,
            kaimai_hash TEXT NOT NULL,
            kaimai_str TEXT NOT NULL,
            seniunija TEXT,
            mapped_seniunija TEXT,
            village TEXT,
            mapped_village TEXT,
            street TEXT,
            mapped_street TEXT,
            house_numbers TEXT,
            exclude_streets_json TEXT,
            dates_json TEXT,
            dates_hash TEXT,
            mapping_method TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    try:
        conn.execute("ALTER TABLE pdf_parsed_rows ADD COLUMN exclude_streets_json TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE pdf_parsed_rows ADD COLUMN source_year INTEGER")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE pdf_parsed_rows ADD COLUMN seniunija TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE pdf_parsed_rows ADD COLUMN mapped_seniunija TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE pdf_parsed_rows ADD COLUMN mapped_village TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE pdf_parsed_rows ADD COLUMN mapped_street TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE pdf_parsed_rows ADD COLUMN mapping_method TEXT")
    except sqlite3.OperationalError:
        pass
    conn.commit()


def save_pdf_parsed_rows(results: list[dict], source_file: str, source_year: int | None) -> None:
    if not results:
        return
    conn = get_db_connection()
    ensure_pdf_parsed_rows_table(conn)
    conn.execute("DELETE FROM pdf_parsed_rows WHERE source_file = ?", (source_file,))
    touched_schedule_groups: set[tuple[str, str]] = set()  # (waste_type, kaimai_hash)
    for item in results:
        kaimai_str = clean_cell(item.get("kaimai_str", ""))
        kaimai_hash = generate_kaimai_hash(kaimai_str) if kaimai_str else ""
        dates = item.get("dates") or []
        dates_hash = generate_dates_hash(dates) if dates else ""
        dates_json = json.dumps([d.isoformat() for d in dates], ensure_ascii=False)
        # Normalize optional dimensions. We consistently store "no street" as empty string rather
        # than NULL to match the existing `locations.street == ''` convention and avoid NULL-vs-empty
        # mismatches in API queries.
        street = (item.get("street") or "").strip()
        mapped_street = (item.get("mapped_street") or "").strip()
        conn.execute(
            """
            INSERT INTO pdf_parsed_rows (
                source_file, source_year, waste_type, kaimai_hash, kaimai_str, seniunija,
                mapped_seniunija, village, mapped_village, street, mapped_street, house_numbers,
                exclude_streets_json, dates_json, dates_hash, mapping_method
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                source_file,
                source_year,
                item.get("waste_type") or "",
                kaimai_hash,
                kaimai_str,
                item.get("seniunija"),
                item.get("mapped_seniunija"),
                item.get("village"),
                item.get("mapped_village"),
                street,
                mapped_street,
                item.get("house_numbers"),
                json.dumps(item.get("exclude_streets") or [], ensure_ascii=False),
                dates_json,
                dates_hash,
                item.get("mapping_method") or "none",
            ),
        )

        # Materialize into schedule_groups/calendar_streams so the web/API can serve plastikas/stiklas schedules.
        waste_type = (item.get("waste_type") or "").strip()
        if waste_type and kaimai_hash and dates:
            touched_schedule_groups.add((waste_type, kaimai_hash))
            schedule_group_id = find_or_create_schedule_group(conn, dates, waste_type, kaimai_hash)
            existing_stream_id = get_calendar_stream_id_for_schedule_group(conn, schedule_group_id)
            if not existing_stream_id:
                calendar_stream_id = find_or_create_calendar_stream(conn, dates, waste_type)
                upsert_group_calendar_link(conn, schedule_group_id, calendar_stream_id)

    # Keep streams consistent if any groups changed/added (split/merge behavior, pending cleanup, etc.)
    if touched_schedule_groups:
        reconcile_calendar_streams(conn)
    conn.commit()
    conn.close()


@dataclass
class MarkerCacheEntry:
    html: str
    cache_path: Path


def _hash_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _load_marker_cache(file_path: Path, output_format: str) -> MarkerCacheEntry | None:
    if not config.MARKER_CACHE_ENABLED:
        return None
    cache_dir = Path(config.MARKER_CACHE_DIR)
    cache_dir.mkdir(parents=True, exist_ok=True)
    file_hash = _hash_file(file_path)
    cache_path = cache_dir / f"{file_path.stem}-{file_hash}-{output_format}.json"
    if not cache_path.exists():
        return None
    try:
        with open(cache_path, "r", encoding="utf-8") as f:
            payload = json.load(f)
        html = payload.get("html") if isinstance(payload, dict) else None
        if not html:
            return None
        return MarkerCacheEntry(html=html, cache_path=cache_path)
    except Exception:
        return None


def _write_marker_cache(cache_path: Path, html: str, output_format: str) -> None:
    payload = {"html": html, "output_format": output_format}
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)


def extract_marker_tables(file_path: Path) -> list[pd.DataFrame]:
    try:
        from marker.config.parser import ConfigParser
        from marker.converters.table import TableConverter
        from marker.models import create_model_dict
    except Exception as exc:  # marker-pdf not installed
        logger.warning("marker-pdf not available: %s", exc)
        return []

    # marker-pdf output is expensive; cache the HTML by file hash.
    output_format = "html"
    cache_entry = _load_marker_cache(file_path, output_format)
    if cache_entry:
        html = cache_entry.html
    else:
        config_parser = ConfigParser({"output_format": output_format})
        converter = TableConverter(
            config=config_parser.generate_config_dict(),
            artifact_dict=create_model_dict(),
            processor_list=config_parser.get_processors(),
            renderer=config_parser.get_renderer(),
        )
        rendered = converter(str(file_path))
        rendered_dict = (
            rendered.model_dump() if hasattr(rendered, "model_dump") else rendered.dict()
        )
        html = rendered_dict.get("html", "")
        if not html:
            return []
        if config.MARKER_CACHE_ENABLED:
            file_hash = _hash_file(file_path)
            cache_path = (
                Path(config.MARKER_CACHE_DIR) / f"{file_path.stem}-{file_hash}-{output_format}.json"
            )
            _write_marker_cache(cache_path, html, output_format)

    parser = HTMLTableParser()
    parser.feed(html)

    tables: list[pd.DataFrame] = []
    for rows in parser.tables:
        max_len = max((len(row) for row in rows), default=0)
        if max_len == 0:
            continue
        normalized = [row + [""] * (max_len - len(row)) for row in rows]
        tables.append(pd.DataFrame(normalized))
    return tables


def _get_provider_config(provider_name: str) -> dict:
    for provider in config.AI_PROVIDERS:
        if provider.get("name") == provider_name:
            return provider
    raise ValueError(f"Unknown AI provider: {provider_name}")


def _strip_json_code_fence(content: str) -> str:
    text = content.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if len(lines) >= 2 and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text


def _normalize_ai_output(output: object) -> dict:
    """
    Normalize model output to a single PdfParsedCell-shaped dict.
    Some providers return a single-item list or multiple objects.
    """
    if isinstance(output, dict):
        return {
            "seniunija": output.get("seniunija"),
            "groups": output.get("groups") or [],
        }
    if isinstance(output, list):
        if len(output) == 1 and isinstance(output[0], dict):
            item = output[0]
            return {
                "seniunija": item.get("seniunija"),
                "groups": item.get("groups") or [],
            }
        merged_groups: list[object] = []
        seniunija = None
        for item in output:
            if not isinstance(item, dict):
                continue
            if seniunija is None and item.get("seniunija"):
                seniunija = item.get("seniunija")
            groups = item.get("groups") or []
            if isinstance(groups, list):
                merged_groups.extend(groups)
        return {"seniunija": seniunija, "groups": merged_groups}
    return {"seniunija": None, "groups": []}


def _validate_pdf_ai_output(kaimai_str: str, parsed: PdfParsedCell) -> None:
    if not parsed.groups:
        return
    lowered = kaimai_str.lower()
    if (
        parsed.seniunija is None
        and "sen." in lowered
        and not any((g.seniunija for g in parsed.groups))
    ):
        raise ValueError("AI output missing seniunija despite input containing 'sen.'")
    for group in parsed.groups:
        village = (group.village or "").lower()
        if any(token in village for token in ["kaimai", "sen.", "seniūnija"]):
            raise ValueError(f"AI output contains header-like village: {group.village}")


def create_pdf_parsing_prompt(kaimai_str: str) -> str:
    return f"""You are extracting structured locations from a Lithuanian waste-schedule PDF cell.
Return ONLY valid JSON (no markdown, no code fences, no explanations).

### Output schema (single JSON object)
{{
  "groups": [
    {{
      "seniunija": "string | null",
      "village": "string",
      "include_streets": [{{"street": "string", "house_numbers": "all|<range>|<list>|null"}}],
      "exclude_streets": [{{"street": "string", "house_numbers": "all|<range>|<list>|null"}}]
    }}
  ]
}}

### Core meaning
- Each group describes ONE village/settlement within ONE seniūnija.
- If a village has NO streets listed, set include_streets=[] (this means: whole village / all streets).
- If the text says "išskyrus ...", put those streets in exclude_streets (with house_numbers when present).
- "tik ..." means ONLY those streets; put them in include_streets.

### Seniūnija handling (important)
- Always set group.seniunija to the nearest preceding "<X> sen." label in the cell.
- If the cell contains multiple seniūnija sections, output groups for EACH village under EACH seniūnija section.
- If you truly cannot infer a seniūnija for a group, set group.seniunija=null.
- Never put "sen." / "seniūnija" / "kaimai" into the village field.

### Street vs village
- "village" is a settlement name (usually ends with "k." or "vs."), not a street.
- "street" must be an actual street name (often ends with "g.", "al.", "pl.", "kel.", "akl.", "tak.").
- Never place villages inside include_streets/exclude_streets.
- Never invent placeholder villages like "Visi kaimai", "Kaimai", "Visos gatvės".

### House numbers
- Use house_numbers="all" when all houses on that street are included.
- Keep compact strings as written (ranges/lists). Do NOT expand.
- Tokens like "2 d." / "16 d." are dates, not house numbers.

### Lithuanian
- Keep Lithuanian letters and suffixes as written (k., vs., g., ...). Do not anglicize.

### Example
Input:
"Dūkštų sen. kaimai išskyrus Verkšionys k., Neries Kilpų g. Sudervės sen. kaimai: Grikienių k."
Output:
{{
  "groups": [
    {{
      "seniunija": "Dūkštų sen.",
      "village": "Verkšionys k.",
      "include_streets": [],
      "exclude_streets": [{{"street": "Neries Kilpų g.", "house_numbers": "all"}}]
    }},
    {{
      "seniunija": "Sudervės sen.",
      "village": "Grikienių k.",
      "include_streets": [],
      "exclude_streets": []
    }}
  ]
}}

### Cell string
"{kaimai_str}"
"""


def parse_pdf_cell_with_ai(
    kaimai_str: str, waste_type: str, skip_ai: bool = False
) -> PdfParsedCell:
    if not kaimai_str:
        return PdfParsedCell()

    kaimai_str = str(kaimai_str).strip()
    if not kaimai_str:
        return PdfParsedCell()

    if skip_ai:
        parsed_items = parse_village_and_streets(kaimai_str)
        if not parsed_items:
            return PdfParsedCell()
        village = parsed_items[0][0]
        include = [
            PdfParsedStreet(street=name, house_numbers=house_nums)
            for name, house_nums in parsed_items[1:]
        ]
        return PdfParsedCell(groups=[PdfParsedGroup(village=village, include_streets=include)])

    cached = get_pdf_ai_cache(kaimai_str, waste_type)
    if cached is not None:
        return cached

    model_rotation = [
        (provider_name, model_id)
        for provider_name, model_id in get_model_rotation()
        if provider_name not in _DISABLED_AI_PROVIDERS
    ]
    if not model_rotation and _DISABLED_AI_PROVIDERS:
        logger.warning(
            "PDF AI providers temporarily disabled (%s); retrying full rotation.",
            ", ".join(sorted(_DISABLED_AI_PROVIDERS)),
        )
        _DISABLED_AI_PROVIDERS.clear()
        model_rotation = get_model_rotation()
    prompt = create_pdf_parsing_prompt(kaimai_str)
    logger.info(
        "PDF AI input (waste_type=%s): %s",
        waste_type or "unknown",
        kaimai_str,
    )
    last_error = None
    for provider_name, model_id in model_rotation:
        response_text = None
        current_prompt = prompt
        for attempt in range(2):
            try:
                if provider_name == "gemini":
                    throttle("ai", min_seconds=3.0, max_seconds=3.5)
                else:
                    throttle("ai")
                logger.info("PDF AI parse using %s:%s", provider_name, model_id)
                provider_config = _get_provider_config(provider_name)
                api_key = provider_config.get("api_key")
                if not api_key:
                    raise ValueError(f"Missing API key for AI provider: {provider_name}")

                base_url = provider_config.get("base_url", "").rstrip("/")
                payload = {
                    "model": model_id,
                    "messages": [
                        {"role": "system", "content": "Return valid JSON only."},
                        {"role": "user", "content": current_prompt},
                    ],
                    "temperature": 0,
                }
                logger.info(
                    "PDF AI request (%s:%s) payload: %s",
                    provider_name,
                    model_id,
                    json.dumps(payload, ensure_ascii=False),
                )
                logger.info(
                    "PDF AI request (%s:%s) url=%s headers=%s",
                    provider_name,
                    model_id,
                    f"{base_url}/chat/completions",
                    json.dumps(
                        {"Authorization": f"Bearer {api_key}"},
                        ensure_ascii=False,
                    ),
                )
                resp = requests.post(
                    f"{base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}"},
                    json=payload,
                    timeout=PDF_AI_TIMEOUT_SECONDS,
                )
                response_text = resp.text
                logger.info(
                    "PDF AI raw response (%s:%s): %s",
                    provider_name,
                    model_id,
                    response_text,
                )
                if resp.status_code >= 400:
                    retry_delay = _extract_retry_delay_seconds(response_text)
                    if resp.status_code in (429, 503) and attempt == 0:
                        delay = retry_delay or (3.5 if resp.status_code == 429 else 2.0)
                        logger.warning(
                            "PDF AI request failed (%s:%s, status=%s). Retrying in %.2fs.",
                            provider_name,
                            model_id,
                            resp.status_code,
                            delay,
                        )
                        time.sleep(delay)
                        continue
                    raise ValueError(f"AI request failed ({resp.status_code}): {response_text}")
                response_json = resp.json()
                content = response_json["choices"][0]["message"]["content"]
                content = _strip_json_code_fence(content)
                output = json.loads(content)
                normalized = _normalize_ai_output(output)
                parsed = PdfParsedCell.model_validate(normalized)
                _validate_pdf_ai_output(kaimai_str, parsed)
                set_pdf_ai_cache(kaimai_str, waste_type, parsed)
                return parsed
            except Exception as exc:
                last_error = exc
                logger.exception(
                    "PDF AI parse failed (provider=%s model=%s waste_type=%s). Prompt=%s",
                    provider_name,
                    model_id,
                    waste_type or "unknown",
                    prompt,
                )
                if response_text is not None:
                    logger.error(
                        "PDF AI raw response (%s:%s): %s",
                        provider_name,
                        model_id,
                        response_text,
                    )
                    _dump_pdf_ai_failure(
                        provider_name=provider_name,
                        model_id=model_id,
                        waste_type=waste_type or "unknown",
                        prompt=prompt,
                        response_text=response_text,
                        error=str(exc),
                    )
                if attempt == 0 and isinstance(exc, requests.exceptions.ReadTimeout):
                    backoff("ai", min_seconds=5.0, max_seconds=10.0)
                    continue
                if (
                    attempt == 0
                    and isinstance(exc, ValueError)
                    and ("header-like village" in str(exc) or "missing seniunija" in str(exc))
                ):
                    current_prompt = (
                        f"{prompt}\n\nValidation error: {exc}. "
                        "Fix the JSON output accordingly and return corrected JSON only."
                    )
                    continue
                if is_rate_limit_error(exc) or isinstance(exc, requests.exceptions.ReadTimeout):
                    _DISABLED_AI_PROVIDERS.add(provider_name)
                    logger.warning(
                        "Temporarily disabling AI provider due to errors: %s",
                        provider_name,
                    )
                break
        continue
    raise RuntimeError("All PDF AI providers failed") from last_error


def extract_dates_from_cell(
    cell_value: object,
    month_name: str,
    year: int = 2026,
    require_day_suffix: bool = False,
) -> list[datetime.date]:
    """
    Extract dates from a cell value
    Format: "2 d." or "19 d." or "2 d., 16 d., 30 d."

    Args:
        cell_value: Cell value (string like "2 d." or "19 d.")
        month_name: Lithuanian month name (genitive)
        year: Year for the dates

    Returns:
        List of date objects
    """
    dates = []
    month_num = MONTH_MAPPING.get(month_name)

    if month_num is None:
        return dates

    if cast(bool, pd.isna(cell_value)):
        return dates

    cell_str = str(cell_value).strip()
    if not cell_str:
        return dates

    # Pattern to match "8 d." or just "8" or "8," etc.
    pattern = r"\b(\d{1,2})\s*d\." if require_day_suffix else r"(\d+)\s*(?:d\.|d|,)?\s*"
    matches = re.findall(pattern, cell_str)

    for match in matches:
        try:
            day = int(match[0] if isinstance(match, tuple) else match)
            if 1 <= day <= 31:
                try:
                    date_obj = datetime.date(year, month_num, day)
                    dates.append(date_obj)
                except ValueError:
                    # Invalid date (e.g., Feb 30, Apr 31)
                    continue
        except (ValueError, IndexError):
            continue

    return sorted(set(dates))  # Remove duplicates and sort


def normalize_month_name(value: str) -> str | None:
    if not value:
        return None
    key = re.sub(r"[^\wąčęėįšųūžĄČĘĖĮŠŲŪŽ]+", "", str(value).strip().lower())
    return MONTH_ALIASES.get(key)


def clean_cell(value: object) -> str:
    if value is None or cast(bool, pd.isna(value)):
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def row_has_months(row: pd.Series) -> bool:
    row_str = " ".join([str(cell) for cell in row.values if pd.notna(cell)]).lower()
    for month in MONTH_ALIASES:
        if month in row_str:
            return True
    return False


def row_has_labels(row: pd.Series) -> bool:
    row_str = " ".join([str(cell) for cell in row.values if pd.notna(cell)]).lower()
    return "seniūn" in row_str or "gyvenviet" in row_str or "pavadinimas" in row_str


def row_contains_header(row: pd.Series) -> bool:
    row_str = " ".join([str(cell) for cell in row.values if pd.notna(cell)]).lower()
    has_labels = row_has_labels(row)
    has_waste = "atliek" in row_str
    has_months = row_has_months(row)
    return (has_labels and has_waste) or (has_labels and has_months)


def _has_day_token(text: str) -> bool:
    return bool(re.search(r"\b\d{1,2}\s*d\.", text))


def _has_waste_label(text: str) -> bool:
    return bool(re.search(r"\b(Pakuotė|Stiklas)\b", text))


def _has_location_marker(text: str) -> bool:
    return any(token in text for token in (" sen.", " m.", " k.", " vs."))


def split_fused_header_rows(df: pd.DataFrame) -> pd.DataFrame:
    """
    marker-pdf can fuse the header row with the first data row (notably on plastic page 1).
    Detect that pattern and split into a clean header row + data row.
    """
    rows: list[list[str]] = []
    for _, row in df.iterrows():
        cells = [clean_cell(cell) for cell in row.tolist()]
        row_text = " ".join([c for c in cells if c]).strip()
        if (
            row_contains_header(row)
            and _has_waste_label(row_text)
            and _has_day_token(row_text)
            and _has_location_marker(row_text)
        ):
            header_cells = cells[:]
            header_cells[0] = "Seniūnijos pavadinimas (gyvenvietės pavadinimas)"

            data_cells = [""] * len(cells)
            cleaned = row_text
            cleaned = re.sub(r"\b\d{4}\s*m\.\b", "", cleaned)
            cleaned = re.sub(r"Seniūnijos pavadinimas\s*\(gyvenvietės pavadinimas\)", "", cleaned)
            cleaned = re.sub(r"\b(Atliekos|Sausio|Vasario|Kovo)\b", "", cleaned)
            cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()
            data_cells[0] = cleaned

            rows.append(header_cells)
            rows.append(data_cells)
        else:
            rows.append(cells)
    return pd.DataFrame(rows)


def _format_day_list(dates: list[datetime.date]) -> str:
    if not dates:
        return ""
    days = sorted({d.day for d in dates})
    return ", ".join([f"{day} d." for day in days])


def find_header_rows(df: pd.DataFrame) -> list[int]:
    header_rows = []
    for idx, row in df.iterrows():
        if row_contains_header(row):
            header_rows.append(idx)
    return header_rows


def build_header(df: pd.DataFrame, header_idx: int) -> list[str]:
    header_row = df.iloc[header_idx].tolist()
    next_row = None
    if header_idx + 1 < len(df):
        candidate = df.iloc[header_idx + 1]
        if row_has_months(candidate) and not row_has_months(df.iloc[header_idx]):
            next_row = candidate.tolist()

    if not next_row:
        cleaned = [clean_cell(cell) for cell in header_row]
        return [re.sub(r"\b\d{4}\s*m\.\b", "", cell).strip() for cell in cleaned]

    combined = []
    for first, second in zip(header_row, next_row, strict=False):
        first_clean = re.sub(r"\b\d{4}\s*m\.\b", "", clean_cell(first)).strip()
        second_clean = re.sub(r"\b\d{4}\s*m\.\b", "", clean_cell(second)).strip()
        if first_clean:
            combined.append(first_clean)
        elif second_clean:
            combined.append(second_clean)
        else:
            combined.append("")
    return combined


def split_table_by_headers(df: pd.DataFrame) -> list[pd.DataFrame]:
    df = split_fused_header_rows(df)
    header_rows = find_header_rows(df)
    if not header_rows:
        return []
    sections = []
    if header_rows[0] > 0:
        header = build_header(df, header_rows[0])
        pre_section = df.iloc[: header_rows[0]].copy()
        if not pre_section.empty:
            pre_section.columns = header[: len(pre_section.columns)]
            sections.append(pre_section.reset_index(drop=True))
    if header_rows[0] > 0:
        df = df.iloc[header_rows[0] :].reset_index(drop=True)
        header_rows = find_header_rows(df)
        if not header_rows:
            return []
    header_rows.append(len(df))
    for start_idx, end_idx in zip(header_rows, header_rows[1:], strict=False):
        header = build_header(df, start_idx)
        section = df.iloc[start_idx + 1 : end_idx].copy()
        if section.empty:
            continue
        section.columns = header[: len(section.columns)]
        sections.append(section.reset_index(drop=True))
    return sections


def infer_month_columns(section: pd.DataFrame) -> dict[str, str]:
    """Map month columns deterministically based on column count."""
    column_count = len(section.columns)
    if column_count < 3:
        return {}
    expected = column_count - 2
    ordered = list(MONTH_MAPPING.keys())[:expected]
    found = set()
    for _, row in section.iterrows():
        for cell in row.tolist():
            normalized = normalize_month_name(cell)
            if normalized:
                found.add(normalized)
    if found and not set(found).issubset(set(ordered)):
        raise ValueError(f"Unexpected month headers {sorted(found)} for {expected} month columns.")
    return {name: section.columns[2 + idx] for idx, name in enumerate(ordered)}


def normalize_waste_type(waste_type: str) -> str:
    """
    Normalize waste type to standard format.
    'Pakuotė' -> 'plastikas', 'Stiklas' -> 'stiklas'
    """
    waste_type = str(waste_type).strip().lower()
    if "pakuotė" in waste_type or "pak" in waste_type:
        return "plastikas"
    elif "stiklas" in waste_type or "stikl" in waste_type:
        return "stiklas"
    return "bendros"  # default


def normalize_waste_label(waste_type: str) -> str:
    if not waste_type:
        return ""
    lower = str(waste_type).strip().lower()
    if "pakuotė" in lower or "pak" in lower:
        return "Pakuotė"
    if "stiklas" in lower or "stikl" in lower:
        return "Stiklas"
    return str(waste_type).strip()


def infer_pdf_waste_label(file_path: Path) -> str:
    """Infer waste label from file name (used as a backfill for missing cells)."""
    name = file_path.name.lower()
    if "glass" in name or "stiklas" in name:
        return "Stiklas"
    if "plastic" in name or "plast" in name or "pakuot" in name:
        return "Pakuotė"
    return ""


def normalize_village_name(value: str) -> str:
    """Normalize village names for consistent output."""
    text = str(value or "").strip()
    if not text:
        return ""
    text = re.sub(r"^D\.\s*Riešės\b", "Didžiosios Riešės", text)
    text = re.sub(r"^M\.\s*Riešės\b", "Mažosios Riešės", text)
    text = re.sub(r"\bRiešės\s+k\.\b", "Riešės", text)
    text = re.sub(r"\b(Didžiosios|Mažosios)\s+Riešės\s+k\.\b", r"\\1 Riešės", text)
    text = re.sub(r"\b(k\.|vs\.|mstl\.|m\.)\b$", "", text).strip()
    text = re.sub(r"\s{2,}", " ", text).strip()
    return text


def parse_pdf(
    file_path: Path, year: int = 2026, skip_ai: bool = True
) -> tuple[list[dict], list[dict], list[dict]]:
    """
    Parse PDF file and extract all location schedules using marker-pdf (HTML output).

    Args:
        file_path: Path to PDF file
        year: Year for the schedule

    Returns:
        Tuple of:
          - parsed_rows: split rows (village/street) ready for persistence
          - raw_rows: raw marker-pdf output (debug)
          - normalized_rows: row-level output before splitting/AI (phase 1)
    """
    logger.info(f"Parsing PDF file: {file_path}")

    # Extract tables from PDF using marker-pdf HTML output
    tables = []
    marker_tables = extract_marker_tables(file_path)
    if marker_tables:
        tables.extend(marker_tables)
        logger.info("Extracted %s tables using marker-pdf", len(marker_tables))

    # raw_rows: marker-pdf raw rows
    # normalized_rows: row-level truth before any splitting/AI
    raw_rows = []
    normalized_rows = []
    if not tables:
        logger.error("No tables extracted from PDF using marker-pdf")
        return ([], raw_rows, normalized_rows)
    logger.info("Using %s tables after page selection", len(tables))

    results = []
    pdf_waste_label = infer_pdf_waste_label(file_path)

    last_header = None
    # Process each table
    for table_idx, table in enumerate(tables):
        logger.debug(f"Processing table {table_idx + 1}/{len(tables)}")

        df = table if isinstance(table, pd.DataFrame) else table.df
        sections = split_table_by_headers(df)
        if not sections:
            if last_header and len(last_header) == df.shape[1]:
                fallback = df.copy()
                fallback.columns = last_header[: len(fallback.columns)]
                sections = [fallback.reset_index(drop=True)]
                logger.warning(
                    "No header row in table %s; reusing previous header",
                    table_idx + 1,
                )
            else:
                if df.shape[1] <= len(DEFAULT_HEADER):
                    fallback = df.copy()
                    fallback.columns = DEFAULT_HEADER[: df.shape[1]]
                    sections = [fallback.reset_index(drop=True)]
                    logger.warning(
                        "No header row in table %s; using default header",
                        table_idx + 1,
                    )
                else:
                    logger.warning(f"Could not find header row in table {table_idx + 1}, skipping")
                    continue

        for section_idx, section in enumerate(sections):
            last_waste_label = None
            # Find location column (may have different names)
            location_col = None
            for col in section.columns:
                col_lower = str(col).lower()
                if (
                    "seniūnijos" in col_lower
                    or "gyvenvietės" in col_lower
                    or "pavadinimas" in col_lower
                ):
                    location_col = col
                    break

            if location_col is None:
                logger.debug(
                    f"No location column in table {table_idx + 1} section {section_idx + 1}"
                )
                continue

            # Find waste type column
            waste_type_col = None
            for col in section.columns:
                col_lower = str(col).lower()
                if "atliekos" in col_lower or "atliek" in col_lower:
                    waste_type_col = col
                    break
            if waste_type_col == location_col:
                waste_type_col = None

            # Find month columns (using aliases)
            month_columns = {}
            for col in section.columns:
                normalized = normalize_month_name(col)
                if normalized:
                    month_columns[normalized] = col

            if not month_columns:
                try:
                    month_columns = infer_month_columns(section)
                except ValueError as exc:
                    raise ValueError(
                        f"Month inference failed for table {table_idx + 1} "
                        f"section {section_idx + 1}: {exc}"
                    ) from exc
            last_header = list(section.columns)

            logger.debug(
                "Found %s month columns: %s",
                len(month_columns),
                list(month_columns.keys()),
            )

            # Handle misaligned month headers on some glass pages (Sausio column holds Vasario).
            shift_sausio_to_vasario = False
            if "Sausio" in month_columns and "Vasario" in month_columns:
                sa_col = month_columns["Sausio"]
                va_col = month_columns["Vasario"]
                has_sausio = False
                has_vasario = False
                for _, scan_row in section.iterrows():
                    if clean_cell(scan_row.get(sa_col, "")):
                        has_sausio = True
                    if clean_cell(scan_row.get(va_col, "")):
                        has_vasario = True
                if has_sausio and not has_vasario and len(section.columns) == 4:
                    shift_sausio_to_vasario = True

            # Process each row
            for idx, row in section.iterrows():
                row_raw = {
                    "table_index": table_idx + 1,
                    "section_index": section_idx + 1,
                    "row_index": idx,
                    "location": clean_cell(row.get(location_col, "")),
                    "waste_type_cell": clean_cell(row.get(waste_type_col, "")),
                }
                for month_name, col_name in month_columns.items():
                    row_raw[f"month_{month_name}"] = clean_cell(row.get(col_name, ""))
                raw_rows.append(row_raw)

                location_str = clean_cell(row.get(location_col, ""))
                if not location_str:
                    logger.debug(
                        "Skipping empty location row %s in table %s section %s",
                        idx,
                        table_idx + 1,
                        section_idx + 1,
                    )
                    continue

                # Skip if this looks like a header row
                if any(col in location_str for col in ["Seniūnijos", "pavadinimas", "Atliekos"]):
                    logger.debug(
                        "Skipping header-like row %s in table %s section %s: %s",
                        idx,
                        table_idx + 1,
                        section_idx + 1,
                        location_str[:80],
                    )
                    continue
                if location_str in ["Pakuotė", "Stiklas"]:
                    logger.debug(
                        "Skipping waste-only row %s in table %s section %s",
                        idx,
                        table_idx + 1,
                        section_idx + 1,
                    )
                    continue
                if normalize_month_name(location_str):
                    logger.debug(
                        "Skipping month-only row %s in table %s section %s",
                        idx,
                        table_idx + 1,
                        section_idx + 1,
                    )
                    continue
                if any(
                    phrase in location_str
                    for phrase in [
                        "Konteineriai tuštinimo dieną",
                        "organizuojamas atliekų surinkimo maršrutas",
                        "neaptarnautą konteinerį",
                        "Parengė :",
                    ]
                ):
                    logger.debug(
                        "Skipping footer/info row %s in table %s section %s",
                        idx,
                        table_idx + 1,
                        section_idx + 1,
                    )
                    continue

                # Get waste type; if missing, inherit last seen label in section.
                waste_type_cell = ""
                waste_type_raw = ""
                waste_type = "bendros"
                if waste_type_col:
                    waste_type_cell = clean_cell(row.get(waste_type_col, ""))
                else:
                    match = re.search(r"\b(Pakuotė|Stiklas)\b", location_str)
                    if match:
                        waste_type_cell = match.group(1)
                        location_str = re.sub(r"\b(Pakuotė|Stiklas)\b", "", location_str)
                        location_str = re.sub(r"\s{2,}", " ", location_str).strip()
                    elif last_waste_label:
                        waste_type_cell = last_waste_label

                normalized_label = normalize_waste_label(waste_type_cell) if waste_type_cell else ""
                if not normalized_label and pdf_waste_label:
                    waste_type_cell = pdf_waste_label
                    normalized_label = pdf_waste_label
                if (
                    waste_type_cell
                    and any(label in waste_type_cell for label in ["Pakuotė", "Stiklas"])
                    and waste_type_cell not in ["Pakuotė", "Stiklas"]
                ):
                    match = re.split(r"(Pakuotė|Stiklas)", waste_type_cell, maxsplit=1)
                    if len(match) >= 3:
                        prefix, label, suffix = match[0].strip(), match[1], match[2].strip()
                        if prefix:
                            location_str = f"{location_str} {prefix}".strip()
                        if suffix:
                            location_str = f"{location_str} {suffix}".strip()
                        waste_type_cell = label
                        normalized_label = label
                if normalized_label in ["Pakuotė", "Stiklas"]:
                    last_waste_label = normalized_label
                    waste_type_raw = normalized_label
                    waste_type = normalize_waste_type(normalized_label)
                elif last_waste_label:
                    waste_type_raw = last_waste_label
                    waste_type = normalize_waste_type(last_waste_label)

                if location_str.startswith("Pakuotė "):
                    location_str = location_str[len("Pakuotė ") :]
                if location_str.startswith("Stiklas "):
                    location_str = location_str[len("Stiklas ") :]

                if waste_type_cell and normalize_waste_label(waste_type_cell) not in [
                    "Pakuotė",
                    "Stiklas",
                ]:
                    if any(token in waste_type_cell for token in ["k.", "g.", ","]):
                        location_str = f"{location_str} {waste_type_cell}".strip()

                # Extract dates from month columns into ISO dates and keep display values.
                all_dates = []
                month_values: dict[str, str] = {}
                for month_name, col_name in month_columns.items():
                    cell_value = row.get(col_name, "")
                    month_values[month_name] = clean_cell(cell_value)
                    dates = extract_dates_from_cell(cell_value, month_name, year)
                    all_dates.extend(dates)
                if shift_sausio_to_vasario:
                    month_values["Vasario"] = month_values.get("Sausio", "")
                    month_values["Sausio"] = ""

                # If "Sausio" column is missing or empty, look for embedded day tokens in the location cell.
                if not month_values.get("Sausio"):
                    embedded_dates = extract_dates_from_cell(
                        location_str, "Sausio", year, require_day_suffix=True
                    )
                    if embedded_dates:
                        all_dates.extend(embedded_dates)
                        month_values["Sausio"] = _format_day_list(embedded_dates)
                        location_str = re.sub(r"\b\d{1,2}\s*d\.\b", "", location_str)
                        location_str = re.sub(r"\s{2,}", " ", location_str).strip()
                        # If only one day is present and all other month cells are empty,
                        # repeat it across visible months (common in glass tables).
                        if len(embedded_dates) == 1 and all(
                            not month_values.get(name) for name in month_columns
                        ):
                            fallback_value = month_values["Sausio"]
                            for name in month_columns:
                                month_values[name] = fallback_value

                normalized_rows.append(
                    {
                        "table_index": table_idx + 1,
                        "section_index": section_idx + 1,
                        "row_index": idx,
                        "location": location_str,
                        "waste_type_cell": waste_type_cell,
                        **{f"month_{name}": value for name, value in month_values.items()},
                    }
                )

                if not all_dates:
                    logger.debug(
                        "Row %s has no dates (table %s section %s): %s",
                        idx,
                        table_idx + 1,
                        section_idx + 1,
                        location_str[:80],
                    )

                # Phase 2: split/AI parsing (optional)
                parsed_cell = parse_pdf_cell_with_ai(
                    location_str, waste_type=waste_type, skip_ai=skip_ai
                )
                if not parsed_cell.groups:
                    continue

                for group in parsed_cell.groups:
                    include = group.include_streets or []
                    exclude_payload = [
                        {"street": s.street, "house_numbers": s.house_numbers}
                        for s in group.exclude_streets
                    ]
                    effective_seniunija = group.seniunija or parsed_cell.seniunija or ""
                    if include:
                        for street in include:
                            normalized_village = normalize_village_name(group.village)
                            results.append(
                                {
                                    "seniunija": effective_seniunija,
                                    "village": normalized_village,
                                    "street": street.street,
                                    "house_numbers": street.house_numbers,
                                    "exclude_streets": exclude_payload,
                                    "dates": sorted(set(all_dates)),
                                    "waste_type": waste_type,
                                    "waste_type_label": normalize_waste_label(waste_type_raw)
                                    or normalize_waste_label(waste_type),
                                    "kaimai_str": location_str,
                                    "parsed_items": parsed_cell.model_dump(),
                                }
                            )
                    else:
                        normalized_village = normalize_village_name(group.village)
                        results.append(
                            {
                                "seniunija": effective_seniunija,
                                "village": normalized_village,
                                "street": "",
                                "house_numbers": None,
                                "exclude_streets": exclude_payload,
                                "dates": sorted(set(all_dates)),
                                "waste_type": waste_type,
                                "waste_type_label": normalize_waste_label(waste_type_raw)
                                or normalize_waste_label(waste_type),
                                "kaimai_str": location_str,
                                "parsed_items": parsed_cell.model_dump(),
                            }
                        )

    if not results:
        logger.info("Parsed 0 rows from PDF")
        return (results, raw_rows, normalized_rows)

    def row_has_months(row: dict) -> bool:
        return any(row.get(f"month_{name}") for name in MONTH_MAPPING.keys())

    # Merge split rows where the location overflows into the next line with month values.
    merged_rows = []
    i = 0
    while i < len(normalized_rows):
        current = normalized_rows[i]
        next_row = normalized_rows[i + 1] if i + 1 < len(normalized_rows) else None
        if (
            next_row
            and current.get("table_index") == next_row.get("table_index")
            and current.get("section_index") == next_row.get("section_index")
            and not row_has_months(current)
            and row_has_months(next_row)
            and current.get("location")
            and next_row.get("location")
        ):
            merged = dict(current)
            merged["location"] = (
                f"{current.get('location', '').strip()} {next_row.get('location', '').strip()}".strip()
            )
            merged["waste_type_cell"] = current.get("waste_type_cell") or next_row.get(
                "waste_type_cell"
            )
            for name in MONTH_MAPPING.keys():
                key = f"month_{name}"
                if next_row.get(key):
                    merged[key] = next_row.get(key)
            merged_rows.append(merged)
            i += 2
            continue
        merged_rows.append(current)
        i += 1

    # Fail fast if a normalized row has location + waste type but no month values.
    for row in merged_rows:
        if row.get("location") and row.get("waste_type_cell") and not row_has_months(row):
            raise ValueError(
                "Parsed row has no month values after normalization; "
                f"table={row.get('table_index')} section={row.get('section_index')} "
                f"row={row.get('row_index')} location={row.get('location')[:120]}"
            )

    deduped = []
    seen = set()
    for item in results:
        dates_key = tuple(d.isoformat() for d in item.get("dates", []))
        key = (
            clean_cell(item.get("seniunija", "")),
            clean_cell(item.get("village", "")),
            clean_cell(item.get("street", "")),
            clean_cell(item.get("house_numbers", "") or ""),
            item.get("waste_type_label") or item.get("waste_type"),
            dates_key,
        )
        if key in seen:
            logger.debug("Dropping duplicate row: %s", key[:4])
            continue
        seen.add(key)
        deduped.append(item)

    logger.info("Parsed %s rows from PDF", len(deduped))
    mapped = apply_mappings(deduped)
    save_pdf_parsed_rows(mapped, source_file=file_path.name, source_year=year)
    return (mapped, raw_rows, merged_rows)
