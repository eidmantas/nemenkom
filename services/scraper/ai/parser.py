"""
AI Parser
"""

import asyncio
import logging
import sys
from pathlib import Path

from pydantic import BaseModel, Field
from pydantic_ai import Agent
from pydantic_ai.models.openrouter import OpenRouterModel
from pydantic_ai.providers.openrouter import OpenRouterProvider

from services.common.throttle import backoff, throttle
from services.scraper.ai.cache import get_cache

# Add parent directory to path for config import
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
import config
from services.common.logging_utils import setup_logging

setup_logging()
logger = logging.getLogger(__name__)


class ParsedStreet(BaseModel):
    street: str
    house_numbers: str | None = None


class ParsedLocation(BaseModel):
    village: str
    streets: list[ParsedStreet] = Field(default_factory=list)


_agent_by_model: dict[str, Agent] = {}


def get_ai_agent(model_id: str) -> Agent:
    agent = _agent_by_model.get(model_id)
    if agent is None:
        provider = OpenRouterProvider(api_key=config.OPENROUTER_API_KEY)
        model = OpenRouterModel(model_id, provider=provider)
        agent = Agent(
            model,
            system_prompt=(
                "You are a parser for Lithuanian location strings. "
                "Return ONLY valid JSON, no explanations."
            ),
            output_type=ParsedLocation,
        )
        _agent_by_model[model_id] = agent
    return agent


def run_agent_prompt(agent: Agent, prompt: str):
    if hasattr(agent, "run_sync"):
        return agent.run_sync(prompt)
    return asyncio.run(agent.run(prompt))


def create_parsing_prompt(kaimai_str: str, error_context: str | None = None) -> str:
    """
    Create prompt for AI to parse Kaimai string into structured format

    Args:
        kaimai_str: The location string to parse
        error_context: Optional context about previous parsing failures (for retries)
    """
    error_note = ""
    if error_context:
        error_note = f"\n\n RETRY ATTEMPT - Previous parsing failed:\n{error_context}\n\nPlease pay special attention to correctly separating the village name from street names. The village name should NOT contain parentheses, street names, or house numbers.\n"

    return f"""Parse this Lithuanian location string into structured JSON format.{error_note}

TASK: Extract the village/city name, street names, and house numbers from this Lithuanian location string. House numbers may appear in various formats: explicit lists ("26, 28"), ranges with "nuo...iki" ("nuo 18 iki 18U"), special cases ("nuo 107", "iki 5"), or directly after street names.

Location string: "{kaimai_str}"

Rules:
1. Extract the village/city name (first part, before any streets)
2. Extract all streets (they may be in parentheses or listed after village)
3. Extract house numbers if specified - MUST use normalized format (see below)
4. Street names ending with "g." (gatvė) are complete street names
5. Ordinal street names like "1-oji g., 2-oji g." are separate streets, not house numbers
6. If no streets, return just the village
7. Single letters or very short strings (like "m") are NOT house numbers - set to null
8. CRITICAL - House number patterns (check in this order):
   STEP 1: Find ALL occurrences of ",(" or ", (" in the string (comma immediately followed by opening parenthesis).
      - For EACH ",(" pattern found, scan BACKWARDS from the ",(" to find the LAST complete street name (ending with "g.") before it
      - The street name that comes IMMEDIATELY before the ",(" (the one right before the comma) gets ALL numbers inside those parentheses
      - CRITICAL: If you see "StreetA g., StreetB g.,(numbers)", the LAST street before the comma is StreetB - StreetB gets the numbers, StreetA gets null
      - IMPORTANT: If there are multiple ",(" patterns, process EACH one separately - each street gets its own numbers
      - Streets that come before a ",(" pattern but are not immediately before it get null for that pattern
      - Examples:
        * "StreetA g., StreetB g.,(numbers)" → StreetB gets ALL numbers, StreetA gets null
        * "Street1, Street2, Street3 g.,(numbers)" → ONLY Street3 gets numbers
        * "Žalioji g.,( Nr. 19, 23, 25)" → Žalioji g. gets "19,23,25"
        * "Molėtų g.,(40-48), StreetX, Vanaginės g., (1-31A)" → Molėtų g. gets "40-48", Vanaginės g. gets "1-31A" (TWO separate patterns)
        * "Akmenų g., Lauko g.,(numbers)" → ONLY Lauko g. gets numbers (it's the LAST street before ",("), Akmenų g. gets null
   STEP 2: If no ",(" pattern found, look for "Street g. (numbers)" (space before parenthesis, no comma) → Street gets the numbers
   STEP 3: If no parentheses, look for "Street g. 2, 4, 6" (numbers directly after street) → Street gets the numbers

HOUSE NUMBERS FORMAT (REQUIRED):
- Normalize to compact format: remove "nuo", "iki", "Nr." prefixes
- Ranges: "nuo 18 iki 18U" → "18-18U", "nuo Nr. 1 iki 9" → "1-9"
- Lists: "26, 28" → "26,28" (no spaces), "114, 114A,114B" → "114,114A,114B"
- Combined ranges: "nuo Nr.1 iki 31A, nuo 2 iki 14B" → "1-31A,2-14B"
- Complex ranges: "nuo Nr.103, 103A iki 119" → "103,103A-119" (start value + range, not "≥103")
- Special (only when no range follows): "nuo 107" (no "iki" after) → "≥107", "iki Nr.5" → "≤5"
- Single values: "26" → "26"
- If house numbers are unclear/invalid (single letter, typo), set to null

EXAMPLE - All house number patterns:
Input: "Didžioji Riešė (Kaštonų g. ( nuo Nr. 1 iki 9 ), Parko g. 2 ,4, 4A, 6, 8 ), Alyvų g., Riešės g., Rožių g., Rūtų g., Žalioji g.,( Nr. 19, 23, 25, 27, 29, 31), Svajonės g., Vanaginės g., (nuo Nr.1 iki 31A, nuo 2 iki 14B), Akmenų g., Lauko g.,(nuo Nr. 2 iki 20A, nuo 1 iki 19), Veneros g.(nuo Nr. 7))"
Output:
{{
  "village": "Didžioji Riešė",
  "streets": [
    {{"street": "Kaštonų g.", "house_numbers": "1-9"}},
    {{"street": "Parko g.", "house_numbers": "2,4,4A,6,8"}},
    {{"street": "Alyvų g.", "house_numbers": null}},
    {{"street": "Riešės g.", "house_numbers": null}},
    {{"street": "Rožių g.", "house_numbers": null}},
    {{"street": "Rūtų g.", "house_numbers": null}},
    {{"street": "Žalioji g.", "house_numbers": "19,23,25,27,29,31"}},
    {{"street": "Svajonės g.", "house_numbers": null}},
    {{"street": "Vanaginės g.", "house_numbers": "1-31A,2-14B"}},
    {{"street": "Akmenų g.", "house_numbers": null}},
    {{"street": "Lauko g.", "house_numbers": "2-20A,1-19"}},
    {{"street": "Veneros g.", "house_numbers": "≥7"}}
  ]
}}
Key patterns:
- "Kaštonų g. ( numbers)" → Direct parentheses, no comma
- "Parko g. 2 ,4, 4A" → Direct numbers, no parentheses
- "Alyvų g., Riešės g., Rožių g., Rūtų g., Žalioji g.,( numbers)" → Žalioji g. gets ALL numbers (even with many streets before it)
- "Svajonės g., Vanaginės g., (numbers)" → Vanaginės g. gets ALL numbers (trailing comma pattern, Svajonės gets null)
- "Akmenų g., Lauko g.,(nuo Nr. 2 iki 20A, nuo 1 iki 19)" → Lauko g. gets "2-20A,1-19" (combined range), Akmenų g. gets null
- "Molėtų g.,(40-48), ... Vanaginės g., (1-31A)" → TWO separate ",(" patterns: Molėtų g. gets "40-48", Vanaginės g. gets "1-31A"
- "Veneros g.(nuo Nr. 7)" → "≥7" (special case: "nuo X" with no end means "from X onwards")

Return JSON in this exact format:
{{
  "village": "VillageName",
  "streets": [
    {{"street": "Street Name g.", "house_numbers": null}},
    {{"street": "Another Street g.", "house_numbers": "26,28"}},
    {{"street": "Street with range g.", "house_numbers": "18-18U"}},
    {{"street": "Street with special g.", "house_numbers": "≥107"}}
  ]
}}

If there are no streets, return:
{{
  "village": "VillageName",
  "streets": []
}}

Return ONLY valid JSON, no explanations."""


def normalize_house_numbers(house_numbers: str | None) -> str | None:
    """
    Normalize house numbers to compact format

    Rules:
    - Remove "nuo", "iki", "Nr." prefixes
    - Remove spaces around commas
    - Convert ranges: "nuo X iki Y" → "X-Y"
    - Special cases: "nuo X" (no end) → "≥X", "iki X" → "≤X"
    - Reject invalid formats (single letters, very short strings)
    """
    if not house_numbers:
        return None

    def finalize(value: str) -> str:
        if "≥" in value and "-" in value:
            return value.replace("≥", "")
        return value

    house_numbers = house_numbers.strip()

    # Reject obviously invalid formats (single letter, very short)
    if len(house_numbers) <= 1 and not house_numbers.isdigit():
        return None

    # Handle special cases first
    if house_numbers.startswith("iki "):
        # "iki X" → "≤X"
        rest = house_numbers.replace("iki ", "").replace("Nr.", "").replace("Nr", "").strip()
        return finalize(f"≤{rest}") if rest else None

    if house_numbers.startswith("nuo ") and " iki " not in house_numbers:
        # "nuo X" (no end) → "≥X"
        rest = house_numbers.replace("nuo ", "").replace("Nr.", "").replace("Nr", "").strip()
        return finalize(f"≥{rest}") if rest else None

    # Handle special cases first
    if house_numbers.startswith("iki ") and " iki " not in house_numbers[4:]:
        return finalize(f"≤{house_numbers[4:].replace('Nr.', '').replace('Nr', '').strip()}")

    if house_numbers.startswith("nuo ") and " iki " not in house_numbers:
        return finalize(f"≥{house_numbers[4:].replace('Nr.', '').replace('Nr', '').strip()}")

    # Handle ranges: "nuo X iki Y" → "X-Y"
    if " iki " in house_numbers:
        # Split by ", nuo " to handle multiple ranges
        if ", nuo " in house_numbers:
            parts = house_numbers.split(", nuo ")
            normalized_parts = []
            for i, part in enumerate(parts):
                if i > 0:
                    part = "nuo " + part
                if " iki " in part:
                    start, end = part.split(" iki ", 1)
                    start = start.replace("nuo ", "").replace("Nr.", "").replace("Nr", "").strip()
                    end = end.split(",")[0].strip()
                    start = start.replace(", ", ",")
                    normalized_parts.append(f"{start}-{end}")
            return finalize(",".join(normalized_parts)) if normalized_parts else None
        else:
            # Single range
            start, end = house_numbers.split(" iki ", 1)
            start = start.replace("nuo ", "").replace("Nr.", "").replace("Nr", "").strip()
            end = end.split(",")[0].strip()
            start = start.replace(", ", ",")
            return finalize(f"{start}-{end}")

    # Basic cleanup: remove prefixes, clean spacing
    normalized = (
        house_numbers.replace("nuo ", "")
        .replace("iki ", "")
        .replace("Nr.", "")
        .replace("Nr", "")
        .strip()
    )
    normalized = normalized.replace(", ", ",").replace(" ,", ",")

    return finalize(normalized) if normalized else None


def validate_ai_output(parsed_json: object) -> tuple[bool, str | None]:
    """
    Validate AI parser output structure

    Returns:
        (is_valid, error_message)
    """
    # Check required keys
    if not isinstance(parsed_json, dict):
        return (False, "Output is not a dictionary")

    if "village" not in parsed_json:
        return (False, "Missing 'village' key")

    if "streets" not in parsed_json:
        return (False, "Missing 'streets' key")

    # Validate village
    village = parsed_json.get("village", "")
    if not isinstance(village, str) or not village.strip():
        return (False, "Village must be a non-empty string")

    # Validate streets
    streets = parsed_json.get("streets", [])
    if not isinstance(streets, list):
        return (False, "'streets' must be a list")

    # Validate each street entry
    for i, street_entry in enumerate(streets):
        if not isinstance(street_entry, dict):
            return (False, f"Street entry {i} is not a dictionary")

        if "street" not in street_entry:
            return (False, f"Street entry {i} missing 'street' key")

        street_name = street_entry.get("street", "")
        if not isinstance(street_name, str) or not street_name.strip():
            return (False, f"Street entry {i} has invalid street name")

        house_numbers = street_entry.get("house_numbers")
        if house_numbers is not None:
            if not isinstance(house_numbers, str):
                return (
                    False,
                    f"Street entry {i} has invalid house_numbers (must be string or null)",
                )

            # Reject obviously invalid house numbers (single letter, very short)
            house_numbers_stripped = house_numbers.strip()
            if len(house_numbers_stripped) <= 1 and not house_numbers_stripped.isdigit():
                return (
                    False,
                    f"Street entry {i} has invalid house_numbers format: '{house_numbers}' (too short/invalid)",
                )

    return (True, None)


def convert_to_parser_format(parsed_json: dict) -> list[tuple[str, str | None]]:
    """
    Convert AI output to same format as parse_village_and_streets()

    Returns:
        List of tuples: [(village_name, None), (street1, house_nums1), ...]
    """
    result = []

    village = parsed_json.get("village", "").strip()
    if not village:
        return []

    # First tuple is always (village, None)
    result.append((village, None))

    # Add streets
    streets = parsed_json.get("streets", [])
    for street_entry in streets:
        street_name = street_entry.get("street", "").strip()
        if not street_name:
            continue

        house_numbers = street_entry.get("house_numbers")
        # Normalize house numbers format (safety net - AI should return normalized values per prompt,
        # but we normalize here to handle cases where AI returns raw values like "nuo Nr. 2 iki 20A, nuo 1 iki 19")
        house_numbers_str = normalize_house_numbers(house_numbers) if house_numbers else None

        result.append((street_name, house_numbers_str))

    return result


def parse_with_ai(
    kaimai_str: str, error_context: str | None = None, max_retries: int = 2
) -> list[tuple[str, str | None]]:
    """
    Parse complex Kaimai string using PydanticAI + OpenRouter with retry logic

    Uses cache and rate limiter for efficiency.
    Returns same format as parse_village_and_streets() for seamless integration.

    Args:
        kaimai_str: Location string from Kaimai column
        error_context: Optional context about previous parsing failures (for retries)
        max_retries: Maximum number of retry attempts (default: 2)

    Returns:
        List of tuples: [(village_name, None), (street1, house_nums1), ...]
        Same format as traditional parser

    Raises:
        ValueError: If parsing fails or output is invalid after all retries
    """
    if not kaimai_str or not kaimai_str.strip():
        return []

    kaimai_str = kaimai_str.strip()

    # Check cache first - ALWAYS use cache if available (for idempotency)
    # Even for retries, if we have a cached result, use it to ensure consistency
    cache = get_cache()
    cached_result = cache.get(kaimai_str)
    if cached_result is not None:
        # If we have error_context but also have a cached result, log a warning
        # but still use the cache for idempotency
        if error_context:
            logger.warning(
                f"Using cached result for '{kaimai_str[:50]}...' despite error_context (ensuring idempotency)"
            )
        return cached_result

    last_error = None
    last_error_context = error_context

    model_ids = [config.OPENROUTER_MODEL] + list(config.OPENROUTER_FALLBACK_MODELS)
    for attempt in range(max_retries + 1):  # +1 for initial attempt
        try:
            throttle("ai")

            # Build error context for retry
            retry_context = last_error_context
            if attempt > 0 and last_error:
                retry_context = f"Attempt {attempt} failed: {last_error}\n" + (
                    last_error_context or ""
                )

            model_id = model_ids[attempt % len(model_ids)]
            agent = get_ai_agent(model_id)
            response = run_agent_prompt(agent, create_parsing_prompt(kaimai_str, retry_context))

            output = (
                getattr(response, "output", None)
                or getattr(response, "data", None)
                or getattr(response, "result", None)
            )
            if output is None:
                raise ValueError("AI response missing output payload")

            if hasattr(output, "model_dump"):
                parsed_json = output.model_dump()
            elif isinstance(output, dict):
                parsed_json = output
            else:
                raise ValueError("AI response output has unexpected type")

            # Validate output
            is_valid, error_msg = validate_ai_output(parsed_json)
            if not is_valid:
                raise ValueError(f"AI output validation failed: {error_msg}")

            # Convert to parser format
            result = convert_to_parser_format(parsed_json)

            # Get token usage before caching
            usage = getattr(response, "usage", None)
            tokens_used = usage.total_tokens if usage and hasattr(usage, "total_tokens") else 0

            # Cache the result with token usage (only for successful non-retry attempts)
            if not error_context:
                cache = get_cache()
                cache.set(kaimai_str, result, tokens_used=tokens_used)

            return result

        except Exception as e:
            msg = str(e).lower()
            if "rate limit" in msg or "429" in msg:
                backoff("ai_rate_limit")
            last_error = str(e)
            if attempt < max_retries:
                # Build context for next retry
                if not last_error_context:
                    last_error_context = f"Previous attempt failed: {last_error}"
                else:
                    last_error_context = (
                        f"{last_error_context}\nAttempt {attempt + 1} failed: {last_error}"
                    )
                continue  # Retry
            else:
                # All retries exhausted
                raise ValueError(
                    f"AI parsing failed after {max_retries + 1} attempts. Last error: {last_error}"
                ) from e

    raise ValueError("AI parsing failed without a result")
