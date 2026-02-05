"""
AI-assisted mapping between PDF values and XLSX canonical names.
"""

from __future__ import annotations

import json
import logging
import sqlite3

import requests

import config
from services.common.db import get_db_connection
from services.common.throttle import backoff, throttle
from services.scraper.ai.parser import get_model_rotation, is_rate_limit_error

PDF_AI_TIMEOUT_SECONDS = 300
MAPPING_BATCH_SIZE = 150

logger = logging.getLogger(__name__)


VILLAGE_SUFFIXES = ("k.", "vs.", "mstl.", "m.")
STREET_SUFFIXES = ("g.", "al.", "akl.", "pl.", "kel.", "tak.", "skg.", "aklg.")
ADMIN_SUFFIXES = ("sen.", "seniūnija", "seniunija")


def ensure_name_mappings_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS name_mappings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT NOT NULL,
            source_value TEXT NOT NULL,
            target_value TEXT,
            confidence REAL,
            mapping_method TEXT NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(category, source_value)
        )
        """
    )
    conn.commit()


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


def _get_provider_config(provider_name: str) -> dict:
    for provider in config.AI_PROVIDERS:
        if provider.get("name") == provider_name:
            return provider
    raise ValueError(f"Unknown AI provider: {provider_name}")


def _ai_map_batch(
    category: str,
    source_values: list[str],
    target_values: list[str],
    rotation: list[tuple[str, str]],
    disabled_providers: set[str],
) -> dict[str, dict]:
    prompt = f"""You map PDF values to canonical XLSX names.

Category: {category}
PDF values:
{json.dumps(source_values, ensure_ascii=False)}

Canonical XLSX values:
{json.dumps(target_values, ensure_ascii=False)}

Return JSON object where keys are the PDF values and values are:
{{
  "target_value": "one of the XLSX values or null",
  "confidence": 0.0-1.0
}}

Rules:
- Use only one of the provided XLSX values, or null if none are a good match.
- Do not invent new names.
- Do not drop any PDF values.
- Normalize Lithuanian grammar/case to match the canonical XLSX list (e.g., genitive -> nominative).
- Treat abbreviations/suffixes as equivalent (e.g., "g." == "gatvė", "k." == "kaimas",
  "sen." == "seniūnija") and match by meaning.
- If a normalized/trimmed form is not present in the XLSX list, return null (do not invent it).
"""

    last_error: Exception | None = None
    for provider_name, model_id in rotation:
        if provider_name in disabled_providers:
            continue
        provider_config = _get_provider_config(provider_name)
        api_key = provider_config.get("api_key")
        if not api_key:
            continue
        base_url = provider_config.get("base_url", "").rstrip("/")
        payload = {
            "model": model_id,
            "messages": [
                {"role": "system", "content": "Return valid JSON only."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0,
        }
        try:
            if provider_name == "gemini":
                throttle("pdf-name-mapping", min_seconds=3.0, max_seconds=3.5)
            else:
                throttle("pdf-name-mapping", min_seconds=0.5, max_seconds=1.2)
            resp = requests.post(
                f"{base_url}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json=payload,
                timeout=PDF_AI_TIMEOUT_SECONDS,
            )
            if resp.status_code == 429:
                disabled_providers.add(provider_name)
                backoff("pdf-name-mapping-rate-limit", min_seconds=15.0, max_seconds=30.0)
                raise ValueError(f"AI request failed (429): {resp.text}")
            if resp.status_code >= 400:
                raise ValueError(f"AI request failed ({resp.status_code}): {resp.text}")
            response_json = resp.json()
            content = response_json["choices"][0]["message"]["content"]
            content = _strip_json_code_fence(content)
            output = json.loads(content)
            if not isinstance(output, dict):
                raise ValueError("AI output must be a JSON object")
            return output
        except Exception as exc:
            if is_rate_limit_error(exc):
                disabled_providers.add(provider_name)
            last_error = exc
            continue
    raise RuntimeError("All AI providers failed") from last_error


def _load_existing_mappings(
    conn: sqlite3.Connection, category: str
) -> dict[str, tuple[str | None, str]]:
    cur = conn.cursor()
    cur.execute(
        """
        SELECT source_value, target_value, mapping_method
        FROM name_mappings
        WHERE category = ?
        """,
        (category,),
    )
    return {row[0]: (row[1], row[2]) for row in cur.fetchall()}


def _load_distinct_locations(conn: sqlite3.Connection, category: str) -> set[str]:
    column = {"seniunija": "seniunija", "village": "village", "street": "street"}[category]
    cur = conn.cursor()
    cur.execute(f"SELECT DISTINCT COALESCE({column}, '') FROM locations")
    return {row[0] for row in cur.fetchall() if row[0]}


def _store_mapping(
    conn: sqlite3.Connection,
    category: str,
    source_value: str,
    target_value: str | None,
    confidence: float | None,
    mapping_method: str,
) -> None:
    conn.execute(
        """
        INSERT INTO name_mappings (category, source_value, target_value, confidence, mapping_method)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(category, source_value) DO UPDATE SET
            target_value = excluded.target_value,
            confidence = excluded.confidence,
            mapping_method = excluded.mapping_method,
            updated_at = CURRENT_TIMESTAMP
        """,
        (category, source_value, target_value, confidence, mapping_method),
    )


def apply_mappings(results: list[dict]) -> list[dict]:
    if not results:
        return results
    conn = get_db_connection()
    ensure_name_mappings_table(conn)

    categories = {
        "seniunija": ADMIN_SUFFIXES,
        "village": VILLAGE_SUFFIXES,
        "street": STREET_SUFFIXES,
    }
    distinct = {cat: set() for cat in categories}
    for item in results:
        for cat in categories:
            value = (item.get(cat) or "").strip()
            if value:
                distinct[cat].add(value)

    existing = {cat: _load_existing_mappings(conn, cat) for cat in categories}
    targets = {cat: _load_distinct_locations(conn, cat) for cat in categories}
    rotation = get_model_rotation()
    disabled_providers: set[str] = set()

    for cat, values in distinct.items():
        pending: list[str] = []
        for value in sorted(values):
            if value in existing[cat]:
                continue
            # Optional heuristic matching (disabled):
            # exact = normalized_targets[cat].get(_normalize(value, categories[cat]))
            # if exact:
            #     _store_mapping(conn, cat, value, exact, 1.0, "exact")
            #     continue
            # stem_match = stem_targets[cat].get(_stem_name(value))
            # if stem_match:
            #     _store_mapping(conn, cat, value, stem_match, 0.75, "stem")
            #     continue
            pending.append(value)
        conn.commit()

        if not pending:
            continue

        target_list = sorted(targets[cat])
        # For now, send all pending values in a single batch.
        # If prompt size becomes an issue, re-enable chunking with MAPPING_BATCH_SIZE.
        batch = pending
        if not target_list:
            for value in batch:
                _store_mapping(conn, cat, value, None, 0.0, "none")
            conn.commit()
            continue
        output = _ai_map_batch(cat, batch, target_list, rotation, disabled_providers)
        for value in batch:
            item = output.get(value, {})
            target_value = item.get("target_value")
            confidence = item.get("confidence")
            if isinstance(confidence, (int, float)):
                confidence = float(confidence)
            else:
                confidence = None
            if target_value is not None and target_value not in targets[cat]:
                target_value = None
            _store_mapping(conn, cat, value, target_value, confidence, "ai")
        conn.commit()

    refreshed = {cat: _load_existing_mappings(conn, cat) for cat in categories}
    conn.close()

    for item in results:
        row_method = "none"
        for cat in categories:
            raw = (item.get(cat) or "").strip()
            mapped, method = refreshed[cat].get(raw, (None, "none"))
            item[f"mapped_{cat}"] = mapped or raw
            if method == "ai":
                row_method = "ai"
            elif method == "exact" and row_method == "none":
                row_method = "exact"
        item["mapping_method"] = row_method

    # DB-backed fixups (no AI): ensure mapped (seniunija, village, street) exists in canonical `locations`.
    # If a street exists uniquely in another village within the same seniūnija, correct mapped_village.
    #
    # This helps when PDF text associates a street with the wrong village, but XLSX canonical data
    # has a single unambiguous village for that street (e.g., "Sodų Kalno g.").
    try:
        fix_conn = get_db_connection()
        cur = fix_conn.cursor()

        street_village_cache: dict[tuple[str, str], list[str]] = {}

        def _street_villages(s: str, st: str) -> list[str]:
            key = (s, st)
            if key in street_village_cache:
                return street_village_cache[key]
            rows = cur.execute(
                """
                SELECT DISTINCT village
                FROM locations
                WHERE seniunija = ? AND street = ?
                ORDER BY village
                """,
                (s, st),
            ).fetchall()
            vals = [r[0] for r in rows if r and r[0]]
            street_village_cache[key] = vals
            return vals

        def _selection_exists(s: str, v: str, st: str) -> bool:
            row = cur.execute(
                """
                SELECT 1
                FROM locations
                WHERE seniunija = ? AND village = ? AND street = ?
                LIMIT 1
                """,
                (s, v, st),
            ).fetchone()
            return bool(row)

        for item in results:
            s = (item.get("mapped_seniunija") or "").strip()
            v = (item.get("mapped_village") or "").strip()
            st = (item.get("mapped_street") or "").strip()
            if not s or not v or not st:
                continue
            if _selection_exists(s, v, st):
                continue
            candidates = _street_villages(s, st)
            if len(candidates) == 1:
                item["mapped_village"] = candidates[0]
                item["mapping_method"] = (item.get("mapping_method") or "none") + "+db_fixup"
    except Exception:
        # Never fail mapping due to fixups; worst-case we keep the original mapping.
        pass
    finally:
        try:
            fix_conn.close()  # type: ignore[name-defined]
        except Exception:
            pass

    return results
