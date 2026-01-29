"""
PDF Parser module - Extracts tables from PDF using camelot
"""

import datetime
import logging
import re
from pathlib import Path
from typing import cast

import camelot
import pandas as pd

from services.scraper.ai.parser import parse_with_ai
from services.scraper.ai.router import should_use_ai_parser

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

TABLE_AREAS = {
    "plastic": "150,750,610,50",
}

TABLE_COLUMNS = {
    "plastic": [415, 465, 515, 565],
}


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


def extract_dates_from_cell(
    cell_value: object, month_name: str, year: int = 2026
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
    pattern = r"(\d+)\s*(?:d\.|d|,)?\s*"
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
        return [clean_cell(cell) for cell in header_row]

    combined = []
    for first, second in zip(header_row, next_row, strict=False):
        first_clean = clean_cell(first)
        second_clean = clean_cell(second)
        if first_clean:
            combined.append(first_clean)
        elif second_clean:
            combined.append(second_clean)
        else:
            combined.append("")
    return combined


def split_table_by_headers(df: pd.DataFrame) -> list[pd.DataFrame]:
    header_rows = find_header_rows(df)
    if not header_rows:
        return []
    header_rows.append(len(df))
    sections = []
    for start_idx, end_idx in zip(header_rows, header_rows[1:], strict=False):
        header = build_header(df, start_idx)
        section = df.iloc[start_idx + 1 : end_idx].copy()
        if section.empty:
            continue
        section.columns = header[: len(section.columns)]
        sections.append(section.reset_index(drop=True))
    return sections


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


def parse_location_items(kaimai_str: str, skip_ai: bool = False) -> list[tuple[str, str | None]]:
    if not kaimai_str:
        return []

    kaimai_str = str(kaimai_str).strip()
    if not kaimai_str:
        return []

    if not skip_ai and should_use_ai_parser(kaimai_str):
        try:
            return parse_with_ai(kaimai_str)
        except Exception as exc:
            logger.warning(
                "AI parser failed for '%s...': %s, falling back to regex",
                kaimai_str[:50],
                exc,
            )
            return parse_village_and_streets(kaimai_str)

    parsed_items = parse_village_and_streets(kaimai_str)
    if not parsed_items:
        return parsed_items

    village = parsed_items[0][0] if parsed_items else ""
    if (
        not skip_ai
        and village
        and (
            ("(" in village and "g." in village)
            or village.count("g.") > 1
            or ("," in village and "g." in village and not village.strip().startswith("("))
        )
    ):
        try:
            error_context = (
                f"Traditional parser incorrectly included streets in village name: "
                f"'{village[:100]}'"
            )
            return parse_with_ai(kaimai_str, error_context=error_context, max_retries=2)
        except Exception as exc:
            logger.warning(
                "AI retry failed for '%s...': %s, keeping regex output",
                kaimai_str[:50],
                exc,
            )
    return parsed_items


def parse_pdf(
    file_path: Path, year: int = 2026, skip_ai: bool = False
) -> tuple[list[dict], list[dict]]:
    """
    Parse PDF file and extract all location schedules using camelot.

    Args:
        file_path: Path to PDF file
        year: Year for the schedule

    Returns:
        List of dictionaries with structure:
        {
            'seniunija': str,
            'village': str,
            'street': str,
            'house_numbers': str,
            'dates': List[datetime.date],
            'waste_type': str,
            'kaimai_str': str
        }
    """
    logger.info(f"Parsing PDF file: {file_path}")

    # Extract tables from PDF using camelot
    tables = []
    lattice_tables = []
    file_key = "plastic" if "plastic" in file_path.name.lower() else None
    table_area = TABLE_AREAS.get(file_key) if file_key else None
    table_columns = TABLE_COLUMNS.get(file_key) if file_key else None
    lattice_params = {
        "table_areas": [table_area] if table_area else None,
        "strip_text": "\n",
        "line_scale": 60,
        "line_tol": 3,
        "joint_tol": 3,
        "process_background": True,
    }
    logger.info("Camelot table area: %s", table_area)
    logger.info("Camelot columns: %s", table_columns)

    try:
        lattice_tables = camelot.read_pdf(  # type: ignore[reportPrivateImportUsage]
            str(file_path),
            pages="all",
            flavor="lattice",
            table_areas=lattice_params.get("table_areas"),
            strip_text=lattice_params.get("strip_text"),
            line_scale=lattice_params.get("line_scale"),
            line_tol=lattice_params.get("line_tol"),
            joint_tol=lattice_params.get("joint_tol"),
            process_background=lattice_params.get("process_background"),
        )
        logger.info(f"Extracted {len(lattice_tables)} tables using lattice method")
    except Exception as e:
        logger.warning(f"Lattice method failed: {e}")

    def group_by_page(table_list: list) -> dict[int | None, list]:
        grouped = {}
        for table in table_list:
            page = getattr(table, "page", None)
            try:
                if page is None:
                    raise TypeError("Missing page number")
                page = int(page)
            except (TypeError, ValueError):
                page = None
            grouped.setdefault(page, []).append(table)
        return grouped

    lattice_by_page = group_by_page(list(lattice_tables))
    pages = sorted(page for page in lattice_by_page.keys() if page is not None)
    for page in pages:
        tables.extend(lattice_by_page.get(page, []))
    if None in lattice_by_page:
        tables.extend(lattice_by_page.get(None, []))

    raw_rows = []
    if not tables:
        logger.error("No tables extracted from PDF using lattice or stream")
        return ([], raw_rows)
    logger.info("Using %s tables after page selection", len(tables))

    results = []

    last_header = None
    # Process each table
    for table_idx, table in enumerate(tables):
        logger.debug(f"Processing table {table_idx + 1}/{len(tables)}")

        df = table.df
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

            # Find month columns (using aliases)
            month_columns = {}
            for col in section.columns:
                normalized = normalize_month_name(col)
                if normalized:
                    month_columns[normalized] = col

            if not month_columns:
                logger.debug(f"No month columns in table {table_idx + 1} section {section_idx + 1}")
                continue
            last_header = list(section.columns)

            logger.debug(
                "Found %s month columns: %s",
                len(month_columns),
                list(month_columns.keys()),
            )

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

                # Get waste type
                waste_type_cell = ""
                waste_type_raw = ""
                waste_type = "bendros"
                if waste_type_col:
                    waste_type_cell = clean_cell(row.get(waste_type_col, ""))

                normalized_label = normalize_waste_label(waste_type_cell) if waste_type_cell else ""
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

                # Extract dates from month columns
                all_dates = []
                for month_name, col_name in month_columns.items():
                    cell_value = row.get(col_name, "")
                    dates = extract_dates_from_cell(cell_value, month_name, year)
                    all_dates.extend(dates)

                if not all_dates:
                    logger.debug(
                        "Row %s has no dates (table %s section %s): %s",
                        idx,
                        table_idx + 1,
                        section_idx + 1,
                        location_str[:80],
                    )

                parsed_items = parse_location_items(location_str, skip_ai=skip_ai)
                results.append(
                    {
                        "seniunija": "",
                        "village": parsed_items[0][0] if parsed_items else location_str,
                        "street": "",
                        "house_numbers": None,
                        "dates": sorted(set(all_dates)),
                        "waste_type": waste_type,
                        "waste_type_label": normalize_waste_label(waste_type_raw)
                        or normalize_waste_label(waste_type),
                        "kaimai_str": location_str,
                        "parsed_items": parsed_items,
                    }
                )

    if not results:
        logger.info("Parsed 0 rows from PDF")
        return (results, raw_rows)

    deduped = []
    seen = set()
    for item in results:
        dates_key = tuple(d.isoformat() for d in item.get("dates", []))
        key = (
            clean_cell(item.get("kaimai_str", "")),
            item.get("waste_type_label") or item.get("waste_type"),
            dates_key,
        )
        if key in seen:
            logger.debug("Dropping duplicate row: %s", key[0][:80])
            continue
        seen.add(key)
        deduped.append(item)

    logger.info(f"Parsed {len(deduped)} rows from PDF")
    return (deduped, raw_rows)
