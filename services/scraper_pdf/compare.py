"""
Compare PDF-derived schedule groups against existing general waste schedule groups.
"""

import json
import re
import sqlite3
import unicodedata
from pathlib import Path


def _load_dates(dates_json: str | None) -> set[str]:
    if not dates_json:
        return set()
    try:
        data = json.loads(dates_json)
        return {str(item) for item in data}
    except json.JSONDecodeError:
        return set()


_VILLAGE_SUFFIXES = [
    "k.",
    "k",
    "vs.",
    "vs",
    "mstl.",
    "mstl",
    "m.",
    "m",
]

_ADMIN_SUFFIXES = [
    "sen.",
    "sen",
    "seniunija",
    "seniūnija",
]

_STREET_SUFFIXES = [
    "g.",
    "g",
    "al.",
    "al",
    "akl.",
    "akl",
    "pl.",
    "pl",
    "kel.",
    "kel",
    "tak.",
    "tak",
    "skg.",
    "skg",
    "aklg.",
    "aklg",
]


def _normalize_text(value: str, suffixes: list[str]) -> str:
    if not value:
        return ""
    text = value.strip().lower()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.replace("\u00a0", " ")
    for suffix in suffixes:
        text = re.sub(rf"\\b{re.escape(suffix)}\\b", "", text)
    text = re.sub(r"[.,;()\"]", " ", text)
    text = re.sub(r"\\s+", " ", text).strip()
    return text


def _normalize_admin(value: str) -> str:
    return _normalize_text(value, _ADMIN_SUFFIXES)


def _normalize_house_numbers(value: str | None) -> str:
    if not value:
        return ""
    text = str(value).strip().lower()
    if text in ("all", "all."):
        return ""
    text = text.replace(" ", "")
    return text


def _looks_like_village(value: str) -> bool:
    return bool(re.search(r"\\b(k\\.|vs\\.|mstl\\.|m\\.)\\b", value.lower()))


def _coerce_pdf_village_street(village: str, street: str) -> tuple[str, str]:
    """
    If the PDF row put a village into the street column (common when the AI keeps
    "sen. kaimai" in village), swap it back for comparison.
    """
    if (
        street
        and _looks_like_village(street)
        and ("sen." in village.lower() or "kaimai" in village.lower())
    ):
        return street, ""
    return village, street


def _stem_name(value: str) -> str:
    """Heuristic stem for genitive->nominative matching (best-effort)."""
    if not value:
        return ""
    text = value.strip().lower()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[.,;()\"]", " ", text)
    text = re.sub(r"\\s+", " ", text).strip()
    for suffix in (
        "iai",
        "ai",
        "iu",
        "ių",
        "iu",
        "iu",
        "u",
        "ų",
        "es",
        "os",
        "as",
        "is",
        "ys",
        "us",
        "e",
        "a",
        "i",
        "o",
    ):
        if text.endswith(suffix) and len(text) > len(suffix) + 1:
            return text[: -len(suffix)]
    return text


def _build_location_index(
    conn: sqlite3.Connection,
) -> tuple[
    dict[tuple[str, str, str, str], str],
    dict[tuple[str, str], str],
    dict[tuple[str, str, str, str], str],
    dict[tuple[str, str], str],
    dict[tuple[str, str, str], str],
    dict[tuple[str, str], str],
]:
    rows = conn.execute(
        """
        SELECT seniunija, village, street, house_numbers, kaimai_hash
        FROM locations
        """
    ).fetchall()
    index: dict[tuple[str, str, str, str], str] = {}
    street_index: dict[tuple[str, str], str] = {}
    street_counts: dict[tuple[str, str], int] = {}
    stem_index: dict[tuple[str, str, str, str], str] = {}
    village_index: dict[tuple[str, str], str] = {}
    village_counts: dict[tuple[str, str], int] = {}
    global_index: dict[tuple[str, str, str], str] = {}
    global_counts: dict[tuple[str, str, str], int] = {}
    global_stem_index: dict[tuple[str, str], str] = {}
    global_stem_counts: dict[tuple[str, str], int] = {}
    for row in rows:
        seniunija = _normalize_admin(row["seniunija"] or "")
        village = _normalize_text(row["village"] or "", _VILLAGE_SUFFIXES)
        street = _normalize_text(row["street"] or "", _STREET_SUFFIXES)
        house_numbers = _normalize_house_numbers(row["house_numbers"])
        village_stem = _stem_name(village)
        key = (seniunija, village, street, house_numbers)
        if key not in index and row["kaimai_hash"]:
            index[key] = row["kaimai_hash"]
        global_key = (village, street, house_numbers)
        global_counts[global_key] = global_counts.get(global_key, 0) + 1
        if global_key not in global_index and row["kaimai_hash"]:
            global_index[global_key] = row["kaimai_hash"]
        global_stem_key = (village_stem, street)
        global_stem_counts[global_stem_key] = global_stem_counts.get(global_stem_key, 0) + 1
        if global_stem_key not in global_stem_index and row["kaimai_hash"]:
            global_stem_index[global_stem_key] = row["kaimai_hash"]
        if street:
            street_key = (street, house_numbers)
            street_counts[street_key] = street_counts.get(street_key, 0) + 1
            if street_key not in street_index and row["kaimai_hash"]:
                street_index[street_key] = row["kaimai_hash"]
        if village_stem:
            stem_key = (seniunija, village_stem, street, house_numbers)
            if stem_key not in stem_index and row["kaimai_hash"]:
                stem_index[stem_key] = row["kaimai_hash"]
        if village:
            village_key = (seniunija, village)
            village_counts[village_key] = village_counts.get(village_key, 0) + 1
            if village_key not in village_index and row["kaimai_hash"]:
                village_index[village_key] = row["kaimai_hash"]
    # Remove non-unique street/village keys to avoid unsafe matches.
    for key, count in list(street_counts.items()):
        if count > 1:
            street_index.pop(key, None)
    for key, count in list(village_counts.items()):
        if count > 1:
            village_index.pop(key, None)
    for key, count in list(global_counts.items()):
        if count > 1:
            global_index.pop(key, None)
    for key, count in list(global_stem_counts.items()):
        if count > 1:
            global_stem_index.pop(key, None)
    return index, street_index, stem_index, village_index, global_index, global_stem_index


def compare_pdf_to_general(db_path: Path) -> dict:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    (
        location_index,
        street_index,
        stem_index,
        village_index,
        global_index,
        global_stem_index,
    ) = _build_location_index(conn)

    rows = conn.execute(
        """
        SELECT
            pdf.id as pdf_id,
            pdf.waste_type as pdf_waste_type,
            COALESCE(pdf.mapped_seniunija, pdf.seniunija) as pdf_seniunija,
            COALESCE(pdf.mapped_village, pdf.village) as pdf_village,
            COALESCE(pdf.mapped_street, pdf.street) as pdf_street,
            COALESCE(pdf.house_numbers, '') as pdf_house_numbers,
            pdf.dates_json as pdf_dates_json
        FROM pdf_parsed_rows pdf
        """
    ).fetchall()

    stats_by_type: dict[str, dict[str, int]] = {}
    total = matched = overlaps = conflicts = no_general = 0
    match_methods: dict[str, int] = {
        "exact": 0,
        "street_only": 0,
        "village_stem": 0,
        "village_only": 0,
        "global_exact": 0,
        "global_stem": 0,
    }
    seen_rows: set[tuple[str, str, str, str, str, str]] = set()

    for row in rows:
        row_key = (
            row["pdf_waste_type"] or "unknown",
            row["pdf_seniunija"] or "",
            row["pdf_village"] or "",
            row["pdf_street"] or "",
            row["pdf_house_numbers"] or "",
            row["pdf_dates_json"] or "",
        )
        if row_key in seen_rows:
            continue
        seen_rows.add(row_key)
        total += 1
        waste_type = row["pdf_waste_type"] or "unknown"
        stats = stats_by_type.setdefault(
            waste_type,
            {
                "total_pdf_rows": 0,
                "matched_to_general": 0,
                "exact_date_overlap": 0,
                "conflicts": 0,
                "no_general_match": 0,
            },
        )
        stats["total_pdf_rows"] += 1

        pdf_village = row["pdf_village"] or ""
        pdf_street = row["pdf_street"] or ""
        pdf_village, pdf_street = _coerce_pdf_village_street(pdf_village, pdf_street)
        seniunija = _normalize_admin(row["pdf_seniunija"] or "")
        village = _normalize_text(pdf_village, _VILLAGE_SUFFIXES)
        street = _normalize_text(pdf_street, _STREET_SUFFIXES)
        house_numbers = _normalize_house_numbers(row["pdf_house_numbers"])
        kaimai_hash = location_index.get((seniunija, village, street, house_numbers))
        if kaimai_hash:
            match_methods["exact"] += 1
        if not kaimai_hash and street:
            kaimai_hash = street_index.get((street, house_numbers))
            if kaimai_hash:
                match_methods["street_only"] += 1
        if not kaimai_hash and village:
            stem_key = (seniunija, _stem_name(village), street, house_numbers)
            kaimai_hash = stem_index.get(stem_key)
            if kaimai_hash:
                match_methods["village_stem"] += 1
        if not kaimai_hash and village and not street:
            kaimai_hash = village_index.get((seniunija, village))
            if kaimai_hash:
                match_methods["village_only"] += 1
        if not kaimai_hash and village:
            kaimai_hash = global_index.get((village, street, house_numbers))
            if kaimai_hash:
                match_methods["global_exact"] += 1
        if not kaimai_hash and village:
            kaimai_hash = global_stem_index.get((_stem_name(village), street))
            if kaimai_hash:
                match_methods["global_stem"] += 1
        if not kaimai_hash:
            no_general += 1
            stats["no_general_match"] += 1
            continue

        sg = conn.execute(
            """
            SELECT dates
            FROM schedule_groups
            WHERE kaimai_hash = ? AND waste_type = 'bendros'
            LIMIT 1
            """,
            (kaimai_hash,),
        ).fetchone()
        if not sg:
            no_general += 1
            stats["no_general_match"] += 1
            continue

        pdf_dates = _load_dates(row["pdf_dates_json"])
        gen_dates = _load_dates(sg["dates"])
        if not pdf_dates or not gen_dates:
            conflicts += 1
            stats["conflicts"] += 1
            continue

        matched += 1
        stats["matched_to_general"] += 1
        if pdf_dates == gen_dates:
            overlaps += 1
            stats["exact_date_overlap"] += 1
        else:
            conflicts += 1
            stats["conflicts"] += 1

    conn.close()
    return {
        "total_pdf_rows": total,
        "matched_to_general": matched,
        "exact_date_overlap": overlaps,
        "conflicts": conflicts,
        "no_general_match": no_general,
        "by_waste_type": stats_by_type,
        "match_methods": match_methods,
    }


def print_report(db_path: Path) -> None:
    stats = compare_pdf_to_general(db_path)
    print("PDF vs general waste overlap report")
    for key, value in stats.items():
        if key != "by_waste_type":
            print(f"- {key}: {value}")
    by_type = stats.get("by_waste_type") or {}
    if by_type:
        print("\nBreakdown by waste type:")
        for waste_type, payload in sorted(by_type.items()):
            print(f"  - {waste_type}:")
            for key, value in payload.items():
                print(f"      - {key}: {value}")
    match_methods = stats.get("match_methods") or {}
    if match_methods:
        print("\nMatch method usage:")
        for key, value in match_methods.items():
            print(f"- {key}: {value}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="services/database/waste_schedule.db")
    args = parser.parse_args()
    print_report(Path(args.db))
