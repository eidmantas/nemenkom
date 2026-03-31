"""
Continuity helpers for PDF-derived waste schedules.

The PDF provider changes raw grouping text between quarters fairly often. To keep
calendar subscriptions stable, we prefer to reuse an existing `kaimai_hash` when a
newly parsed PDF row resolves to the same canonical mapped selection.
"""

from __future__ import annotations

import re
import sqlite3
import unicodedata
from collections import defaultdict
from dataclasses import dataclass

from services.scraper.core.db_writer import generate_kaimai_hash

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

SelectionKey = tuple[str, str, str, str]
AdminlessSelectionKey = tuple[str, str, str]
DatesKey = tuple[str, ...]


@dataclass(frozen=True)
class HistoricalCandidate:
    kaimai_hash: str
    has_calendar_id: bool
    has_stream: bool
    from_other_source: bool
    row_id: int


@dataclass
class PendingAssignment:
    item: dict
    waste_type: str
    raw_hash: str
    selection_key: SelectionKey
    dates_key: DatesKey
    candidates: list[HistoricalCandidate]
    assigned_hash: str = ""
    continuity_method: str = "raw"


def _normalize_text(value: str, suffixes: list[str]) -> str:
    if not value:
        return ""
    text = value.strip().lower()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.replace("\u00a0", " ")
    for suffix in suffixes:
        text = re.sub(rf"\b{re.escape(suffix)}\b", "", text)
    text = re.sub(r'[.,;()"]', " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _normalize_admin(value: str) -> str:
    return _normalize_text(value, _ADMIN_SUFFIXES)


def _normalize_house_numbers(value: str | None) -> str:
    if not value:
        return ""
    text = str(value).strip().lower()
    if text in ("all", "all."):
        return ""
    return text.replace(" ", "")


def _looks_like_village(value: str) -> bool:
    return bool(re.search(r"\b(k\.|vs\.|mstl\.|m\.)\b", value.lower()))


def _coerce_pdf_village_street(village: str, street: str) -> tuple[str, str]:
    if (
        street
        and _looks_like_village(street)
        and ("sen." in village.lower() or "kaimai" in village.lower())
    ):
        return street, ""
    return village, street


def build_selection_key(
    *,
    seniunija: str,
    village: str,
    street: str,
    house_numbers: str | None,
) -> SelectionKey:
    village, street = _coerce_pdf_village_street(village, street)
    return (
        _normalize_admin(seniunija),
        _normalize_text(village, _VILLAGE_SUFFIXES),
        _normalize_text(street, _STREET_SUFFIXES),
        _normalize_house_numbers(house_numbers),
    )


def selection_key_from_item(item: dict) -> SelectionKey:
    return build_selection_key(
        seniunija=(item.get("mapped_seniunija") or item.get("seniunija") or "").strip(),
        village=(item.get("mapped_village") or item.get("village") or "").strip(),
        street=(item.get("mapped_street") or item.get("street") or "").strip(),
        house_numbers=item.get("house_numbers"),
    )


def _adminless_selection_key(selection_key: SelectionKey) -> AdminlessSelectionKey:
    return selection_key[1:]


def _candidate_rank(candidate: HistoricalCandidate) -> tuple[int, int, int, int, int]:
    return (
        0 if candidate.has_calendar_id else 1,
        0 if candidate.has_stream else 1,
        0 if candidate.from_other_source else 1,
        candidate.row_id,
        len(candidate.kaimai_hash),
    )


def _build_existing_selection_candidates(
    conn: sqlite3.Connection,
    *,
    waste_types: set[str],
    source_file: str,
) -> tuple[
    dict[tuple[str, SelectionKey], list[HistoricalCandidate]],
    dict[tuple[str, AdminlessSelectionKey], list[HistoricalCandidate]],
    dict[tuple[str, str], set[SelectionKey]],
]:
    if not waste_types:
        return {}, {}, {}

    placeholders = ", ".join("?" for _ in waste_types)
    rows = conn.execute(
        f"""
        SELECT
            pdf.id,
            pdf.source_file,
            pdf.waste_type,
            pdf.kaimai_hash,
            COALESCE(pdf.mapped_seniunija, pdf.seniunija, '') AS seniunija,
            COALESCE(pdf.mapped_village, pdf.village, '') AS village,
            COALESCE(pdf.mapped_street, pdf.street, '') AS street,
            pdf.house_numbers,
            CASE WHEN cs.calendar_id IS NOT NULL THEN 1 ELSE 0 END AS has_calendar_id,
            CASE WHEN gcl.calendar_stream_id IS NOT NULL THEN 1 ELSE 0 END AS has_stream
        FROM pdf_parsed_rows pdf
        LEFT JOIN schedule_groups sg
          ON sg.kaimai_hash = pdf.kaimai_hash
         AND sg.waste_type = pdf.waste_type
        LEFT JOIN group_calendar_links gcl
          ON gcl.schedule_group_id = sg.id
        LEFT JOIN calendar_streams cs
          ON cs.id = gcl.calendar_stream_id
        WHERE pdf.waste_type IN ({placeholders})
        """,
        tuple(sorted(waste_types)),
    ).fetchall()

    candidate_map: dict[tuple[str, SelectionKey, str], HistoricalCandidate] = {}
    historical_group_keys: dict[tuple[str, str], set[SelectionKey]] = defaultdict(set)
    for row in rows:
        selection_key = build_selection_key(
            seniunija=row[4] or "",
            village=row[5] or "",
            street=row[6] or "",
            house_numbers=row[7],
        )
        if not any(selection_key[:3]):
            continue
        waste_type = row[2]
        kaimai_hash = row[3]
        historical_group_keys[(waste_type, kaimai_hash)].add(selection_key)
        candidate = HistoricalCandidate(
            kaimai_hash=kaimai_hash,
            has_calendar_id=bool(row[8]),
            has_stream=bool(row[9]),
            from_other_source=(row[1] or "") != source_file,
            row_id=int(row[0]),
        )
        key = (waste_type, selection_key, kaimai_hash)
        current = candidate_map.get(key)
        if current is None or _candidate_rank(candidate) < _candidate_rank(current):
            candidate_map[key] = candidate

    selection_candidates: dict[tuple[str, SelectionKey], list[HistoricalCandidate]] = defaultdict(list)
    missing_admin_candidates: dict[tuple[str, AdminlessSelectionKey], list[HistoricalCandidate]] = (
        defaultdict(list)
    )
    for waste_type, selection_key, _kaimai_hash in candidate_map:
        candidate = candidate_map[(waste_type, selection_key, _kaimai_hash)]
        selection_candidates[(waste_type, selection_key)].append(candidate)
        if not selection_key[0]:
            missing_admin_candidates[(waste_type, _adminless_selection_key(selection_key))].append(
                candidate
            )
    for candidates in selection_candidates.values():
        candidates.sort(key=_candidate_rank)
    for candidates in missing_admin_candidates.values():
        candidates.sort(key=_candidate_rank)

    return dict(selection_candidates), dict(missing_admin_candidates), historical_group_keys


def _get_selection_candidates(
    *,
    waste_type: str,
    selection_key: SelectionKey,
    selection_candidates: dict[tuple[str, SelectionKey], list[HistoricalCandidate]],
    missing_admin_candidates: dict[tuple[str, AdminlessSelectionKey], list[HistoricalCandidate]],
) -> list[HistoricalCandidate]:
    exact_candidates = selection_candidates.get((waste_type, selection_key), [])
    if exact_candidates:
        return exact_candidates
    return missing_admin_candidates.get((waste_type, _adminless_selection_key(selection_key)), [])


def _dates_key_from_item(item: dict) -> DatesKey:
    return tuple(sorted(str(date_value.isoformat()) for date_value in item.get("dates") or []))


def _unique_candidate_hash(
    candidates: list[HistoricalCandidate],
    *,
    blocked_hashes: set[str] | None = None,
) -> str | None:
    blocked_hashes = blocked_hashes or set()
    distinct_hashes: list[str] = []
    seen_hashes: set[str] = set()
    for candidate in candidates:
        if candidate.kaimai_hash in blocked_hashes or candidate.kaimai_hash in seen_hashes:
            continue
        seen_hashes.add(candidate.kaimai_hash)
        distinct_hashes.append(candidate.kaimai_hash)
    return distinct_hashes[0] if len(distinct_hashes) == 1 else None


def _choose_group_reuse_hash(
    *,
    waste_type: str,
    selection_keys: set[SelectionKey],
    selection_candidates: dict[tuple[str, SelectionKey], list[HistoricalCandidate]],
    missing_admin_candidates: dict[tuple[str, AdminlessSelectionKey], list[HistoricalCandidate]],
    historical_group_keys: dict[tuple[str, str], set[SelectionKey]],
) -> str | None:
    if not selection_keys:
        return None

    matches_by_hash: dict[str, dict[str, object]] = {}
    for selection_key in selection_keys:
        for candidate in _get_selection_candidates(
            waste_type=waste_type,
            selection_key=selection_key,
            selection_candidates=selection_candidates,
            missing_admin_candidates=missing_admin_candidates,
        ):
            bucket = matches_by_hash.setdefault(
                candidate.kaimai_hash,
                {
                    "matched_count": 0,
                    "best_candidate": candidate,
                },
            )
            bucket["matched_count"] = int(bucket["matched_count"]) + 1
            best_candidate = bucket["best_candidate"]
            if (
                isinstance(best_candidate, HistoricalCandidate)
                and _candidate_rank(candidate) < _candidate_rank(best_candidate)
            ):
                bucket["best_candidate"] = candidate

    if not matches_by_hash:
        return None

    if len(matches_by_hash) == 1:
        return next(iter(matches_by_hash))

    ranked = sorted(
        matches_by_hash.items(),
        key=lambda item: (
            -int(item[1]["matched_count"]),
            0 if item[1]["best_candidate"].has_calendar_id else 1,
            0 if item[1]["best_candidate"].has_stream else 1,
            abs(
                len(historical_group_keys.get((waste_type, item[0]), set())) - len(selection_keys)
            ),
            _candidate_rank(item[1]["best_candidate"]),
        ),
    )

    top_hash, top_meta = ranked[0]
    second_matched = int(ranked[1][1]["matched_count"]) if len(ranked) > 1 else -1
    top_matched = int(top_meta["matched_count"])
    top_candidate = top_meta["best_candidate"]
    top_group_size = len(historical_group_keys.get((waste_type, top_hash), set()))
    selection_count = len(selection_keys)
    matched_ratio = top_matched / max(selection_count, 1)
    historical_coverage = top_matched / max(top_group_size, 1)

    if top_matched == selection_count and top_matched > second_matched:
        return top_hash
    if top_matched > second_matched and matched_ratio >= 0.5 and historical_coverage >= 0.75:
        return top_hash
    if (
        top_candidate.has_calendar_id
        and top_matched > second_matched
        and matched_ratio >= 0.5
    ):
        return top_hash
    return None


def _assign_group(
    group_assignments: list[PendingAssignment],
    *,
    selection_candidates: dict[tuple[str, SelectionKey], list[HistoricalCandidate]],
    missing_admin_candidates: dict[tuple[str, AdminlessSelectionKey], list[HistoricalCandidate]],
    historical_group_keys: dict[tuple[str, str], set[SelectionKey]],
) -> None:
    waste_type = group_assignments[0].waste_type if group_assignments else ""
    selection_keys = {
        assignment.selection_key for assignment in group_assignments if any(assignment.selection_key[:3])
    }
    group_reuse_hash = _choose_group_reuse_hash(
        waste_type=waste_type,
        selection_keys=selection_keys,
        selection_candidates=selection_candidates,
        missing_admin_candidates=missing_admin_candidates,
        historical_group_keys=historical_group_keys,
    )

    for assignment in group_assignments:
        if group_reuse_hash:
            assignment.assigned_hash = group_reuse_hash
            assignment.continuity_method = "group_reuse"
            continue

        unique_hash = _unique_candidate_hash(assignment.candidates)
        if unique_hash:
            assignment.assigned_hash = unique_hash
            assignment.continuity_method = "selection_reuse"
        else:
            assignment.assigned_hash = assignment.raw_hash
            assignment.continuity_method = "raw"


def _choose_conflict_winner(assignments: list[PendingAssignment]) -> DatesKey | None:
    by_dates: dict[DatesKey, list[PendingAssignment]] = defaultdict(list)
    for assignment in assignments:
        by_dates[assignment.dates_key].append(assignment)

    if len(by_dates) <= 1:
        return next(iter(by_dates)) if by_dates else None

    ranked = sorted(
        by_dates.items(),
        key=lambda item: (
            -len(item[1]),
            0 if any(row.continuity_method == "group_reuse" for row in item[1]) else 1,
            item[0],
        ),
    )
    top_dates_key, top_assignments = ranked[0]
    second_count = len(ranked[1][1]) if len(ranked) > 1 else -1

    if len(top_assignments) > second_count:
        return top_dates_key
    return None


def _resolve_hash_conflicts(assignments: list[PendingAssignment]) -> None:
    while True:
        by_hash: dict[tuple[str, str], list[PendingAssignment]] = defaultdict(list)
        for assignment in assignments:
            if not assignment.assigned_hash or assignment.assigned_hash == assignment.raw_hash:
                continue
            by_hash[(assignment.waste_type, assignment.assigned_hash)].append(assignment)

        changed = False
        for (_waste_type, assigned_hash), bucket in by_hash.items():
            distinct_dates = {assignment.dates_key for assignment in bucket}
            if len(distinct_dates) <= 1:
                continue

            winner_dates_key = _choose_conflict_winner(bucket)
            for assignment in bucket:
                if winner_dates_key is not None and assignment.dates_key == winner_dates_key:
                    continue

                alternative_hash = _unique_candidate_hash(
                    assignment.candidates,
                    blocked_hashes={assigned_hash},
                )
                new_hash = alternative_hash or assignment.raw_hash
                new_method = "selection_reuse" if alternative_hash else "raw"
                if (
                    assignment.assigned_hash != new_hash
                    or assignment.continuity_method != new_method
                ):
                    assignment.assigned_hash = new_hash
                    assignment.continuity_method = new_method
                    changed = True

        if not changed:
            return


def assign_continuity_kaimai_hashes(
    conn: sqlite3.Connection,
    results: list[dict],
    *,
    source_file: str,
) -> dict[str, int]:
    """
    Assign stable `kaimai_hash` values to parsed PDF rows.

    Strategy:
    - Match each canonical mapped selection against existing rows of the same waste type.
    - If a newly parsed raw group only points at one historical hash, reuse that hash for the
      whole group (this preserves continuity across regrouped provider cells).
    - Otherwise, reuse the matched historical hash per selection when available and fall back to
      the raw-text hash for unmatched rows.
    """
    waste_types = {
        (item.get("waste_type") or "").strip()
        for item in results
        if (item.get("waste_type") or "").strip()
    }
    selection_candidates, missing_admin_candidates, historical_group_keys = (
        _build_existing_selection_candidates(
        conn,
        waste_types=waste_types,
        source_file=source_file,
        )
    )

    grouped: dict[tuple[str, str, DatesKey], list[PendingAssignment]] = defaultdict(list)
    assignments: list[PendingAssignment] = []
    for item in results:
        raw_kaimai_str = str(item.get("kaimai_str") or "").strip()
        raw_hash = generate_kaimai_hash(raw_kaimai_str) if raw_kaimai_str else ""
        selection_key = selection_key_from_item(item)
        waste_type = (item.get("waste_type") or "").strip()
        candidates = _get_selection_candidates(
            waste_type=waste_type,
            selection_key=selection_key,
            selection_candidates=selection_candidates,
            missing_admin_candidates=missing_admin_candidates,
        )
        assignment = PendingAssignment(
            item=item,
            waste_type=waste_type,
            raw_hash=raw_hash,
            selection_key=selection_key,
            dates_key=_dates_key_from_item(item),
            candidates=candidates,
        )
        assignments.append(assignment)
        grouped[(waste_type, raw_hash, assignment.dates_key)].append(assignment)

    stats = {
        "group_reuse_rows": 0,
        "selection_reuse_rows": 0,
        "raw_rows": 0,
    }

    for group_assignments in grouped.values():
        _assign_group(
            group_assignments,
            selection_candidates=selection_candidates,
            missing_admin_candidates=missing_admin_candidates,
            historical_group_keys=historical_group_keys,
        )

    _resolve_hash_conflicts(assignments)

    for assignment in assignments:
        assignment.item["kaimai_hash"] = assignment.assigned_hash
        assignment.item["continuity_method"] = assignment.continuity_method
        if assignment.continuity_method == "group_reuse":
            stats["group_reuse_rows"] += 1
        elif assignment.continuity_method == "selection_reuse":
            stats["selection_reuse_rows"] += 1
        else:
            stats["raw_rows"] += 1

    return stats
