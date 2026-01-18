"""
AI Parser - Uses Groq LLM to parse complex Kaimai strings
Returns same format as traditional parser for seamless integration
"""
import json
from typing import List, Tuple, Optional
from groq import Groq

from scraper.ai.cache import get_cache
from scraper.ai.rate_limiter import get_rate_limiter
import sys
from pathlib import Path

# Add parent directory to path for config import
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
import config


def create_parsing_prompt(kaimai_str: str) -> str:
    """
    Create prompt for Groq to parse Kaimai string into structured format
    """
    return f"""Parse this Lithuanian location string into structured JSON format.

Location string: "{kaimai_str}"

Rules:
1. Extract the village/city name (first part, before any streets)
2. Extract all streets (they may be in parentheses or listed after village)
3. Extract house numbers if specified - MUST use normalized format (see below)
4. Street names ending with "g." (gatvė) are complete names, but house numbers often follow immediately.
5. Ordinal street names like "1-oji g., 2-oji g." are separate streets, not house numbers.
6. If no streets, return just the village.
7. Single letters or very short strings (like "m") are NOT house numbers - set to null.
8. IMPORTANT: House numbers often appear in parentheses immediately after the street name, sometimes separated by a comma (e.g., "Street g.,(nuo...)" or "Street g. (nuo...)"). These numbers BELONG to the preceding street.

HOUSE NUMBERS FORMAT (REQUIRED):
- Normalize to compact format: remove "nuo", "iki", "Nr." prefixes.
- Ranges: "nuo 18 iki 18U" → "18-18U", "nuo Nr. 1 iki 9" → "1-9"
- Lists: "26, 28" → "26,28" (no spaces)
- Combined: "nuo Nr.1 iki 31A, nuo 2 iki 14B" → "1-31A,2-14B"
- Parenthesis Handling: If a street is "Molėtų g.,(nuo Nr. 40 iki 48)", the street is "Molėtų g." and house_numbers is "40-48".
- Special: "nuo 107" → "≥107", "iki Nr.5" → "≤5"
- If house numbers are unclear/invalid, set to null.

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


def normalize_house_numbers(house_numbers: Optional[str]) -> Optional[str]:
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
    
    house_numbers = house_numbers.strip()
    
    # Reject obviously invalid formats (single letter, very short)
    if len(house_numbers) <= 1 and not house_numbers.isdigit():
        return None
    
    # Handle special cases first
    if house_numbers.startswith("iki "):
        # "iki X" → "≤X"
        rest = house_numbers.replace("iki ", "").replace("Nr.", "").replace("Nr", "").strip()
        return f"≤{rest}" if rest else None
    
    if house_numbers.startswith("nuo ") and " iki " not in house_numbers:
        # "nuo X" (no end) → "≥X"
        rest = house_numbers.replace("nuo ", "").replace("Nr.", "").replace("Nr", "").strip()
        return f"≥{rest}" if rest else None
    
    # Handle ranges: "nuo X iki Y" → "X-Y"
    if " iki " in house_numbers:
        # Extract range parts
        parts = house_numbers.split(" iki ", 1)
        if len(parts) == 2:
            start = parts[0].replace("nuo ", "").replace("Nr.", "").replace("Nr", "").strip()
            end = parts[1].strip()
            # Remove any trailing commas or other parts
            end = end.split(",")[0].strip()
            return f"{start}-{end}"
    
    # Remove common prefixes
    normalized = house_numbers.replace("nuo ", "").replace("iki ", "").replace("Nr.", "").replace("Nr", "").strip()
    
    # Remove spaces around commas
    normalized = normalized.replace(", ", ",").replace(" ,", ",")
    
    # If already has special prefix, return as-is
    if normalized.startswith("≥") or normalized.startswith("≤"):
        return normalized
    
    return normalized if normalized else None


def validate_ai_output(parsed_json: dict, original_kaimai: str) -> Tuple[bool, Optional[str]]:
    """
    Validate AI parser output structure
    
    Returns:
        (is_valid, error_message)
    """
    # Check required keys
    if not isinstance(parsed_json, dict):
        return (False, "Output is not a dictionary")
    
    if 'village' not in parsed_json:
        return (False, "Missing 'village' key")
    
    if 'streets' not in parsed_json:
        return (False, "Missing 'streets' key")
    
    # Validate village
    village = parsed_json.get('village', '')
    if not isinstance(village, str) or not village.strip():
        return (False, "Village must be a non-empty string")
    
    # Validate streets
    streets = parsed_json.get('streets', [])
    if not isinstance(streets, list):
        return (False, "'streets' must be a list")
    
    # Validate each street entry
    for i, street_entry in enumerate(streets):
        if not isinstance(street_entry, dict):
            return (False, f"Street entry {i} is not a dictionary")
        
        if 'street' not in street_entry:
            return (False, f"Street entry {i} missing 'street' key")
        
        street_name = street_entry.get('street', '')
        if not isinstance(street_name, str) or not street_name.strip():
            return (False, f"Street entry {i} has invalid street name")
        
        house_numbers = street_entry.get('house_numbers')
        if house_numbers is not None:
            if not isinstance(house_numbers, str):
                return (False, f"Street entry {i} has invalid house_numbers (must be string or null)")
            
            # Reject obviously invalid house numbers (single letter, very short)
            house_numbers_stripped = house_numbers.strip()
            if len(house_numbers_stripped) <= 1 and not house_numbers_stripped.isdigit():
                return (False, f"Street entry {i} has invalid house_numbers format: '{house_numbers}' (too short/invalid)")
    
    return (True, None)


def convert_to_parser_format(parsed_json: dict) -> List[Tuple[str, Optional[str]]]:
    """
    Convert AI output to same format as parse_village_and_streets()
    
    Returns:
        List of tuples: [(village_name, None), (street1, house_nums1), ...]
    """
    result = []
    
    village = parsed_json.get('village', '').strip()
    if not village:
        return []
    
    # First tuple is always (village, None)
    result.append((village, None))
    
    # Add streets
    streets = parsed_json.get('streets', [])
    for street_entry in streets:
        street_name = street_entry.get('street', '').strip()
        if not street_name:
            continue
        
        house_numbers = street_entry.get('house_numbers')
        # Normalize house numbers format
        house_numbers_str = normalize_house_numbers(house_numbers) if house_numbers else None
        
        result.append((street_name, house_numbers_str))
    
    return result


def parse_with_ai(kaimai_str: str) -> List[Tuple[str, Optional[str]]]:
    """
    Parse complex Kaimai string using Groq AI
    
    Uses cache and rate limiter for efficiency.
    Returns same format as parse_village_and_streets() for seamless integration.
    
    Args:
        kaimai_str: Location string from Kaimai column
    
    Returns:
        List of tuples: [(village_name, None), (street1, house_nums1), ...]
        Same format as traditional parser
    
    Raises:
        ValueError: If parsing fails or output is invalid
    """
    if not kaimai_str or not kaimai_str.strip():
        return []
    
    kaimai_str = kaimai_str.strip()
    
    # Check cache first
    cache = get_cache()
    cached_result = cache.get(kaimai_str)
    if cached_result is not None:
        return cached_result
    
    # Rate limit check
    rate_limiter = get_rate_limiter()
    rate_limiter.wait_if_needed()
    
    # Call Groq API
    try:
        client = Groq(api_key=config.GROQ_API_KEY)
        
        response = client.chat.completions.create(
            model=config.GROQ_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": "You are a parser for Lithuanian location strings. Return ONLY valid JSON, no explanations."
                },
                {
                    "role": "user",
                    "content": create_parsing_prompt(kaimai_str)
                }
            ],
            temperature=0.1,  # Low temperature for consistent parsing
            response_format={"type": "json_object"}  # Force JSON output
        )
        
        # Extract JSON from response
        content = response.choices[0].message.content.strip()
        
        # Parse JSON
        try:
            parsed_json = json.loads(content)
        except json.JSONDecodeError as e:
            # Try to extract JSON from markdown code blocks if present
            if '```' in content:
                json_start = content.find('{')
                json_end = content.rfind('}') + 1
                if json_start >= 0 and json_end > json_start:
                    content = content[json_start:json_end]
                    parsed_json = json.loads(content)
                else:
                    raise ValueError(f"Failed to parse JSON from AI response: {e}")
            else:
                raise ValueError(f"Failed to parse JSON from AI response: {e}")
        
        # Validate output
        is_valid, error_msg = validate_ai_output(parsed_json, kaimai_str)
        if not is_valid:
            raise ValueError(f"AI output validation failed: {error_msg}")
        
        # Convert to parser format
        result = convert_to_parser_format(parsed_json)
        
        # Get token usage before caching
        tokens_used = response.usage.total_tokens if hasattr(response, 'usage') and hasattr(response.usage, 'total_tokens') else 0
        
        # Cache the result with token usage
        cache.set(kaimai_str, result, tokens_used=tokens_used)
        
        # Update rate limiter with token usage
        rate_limiter.record_request(tokens_used)
        
        return result
        
    except Exception as e:
        # Don't cache failures
        raise ValueError(f"AI parsing failed for '{kaimai_str}': {str(e)}")
