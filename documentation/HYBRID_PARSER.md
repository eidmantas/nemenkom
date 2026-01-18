# Hybrid Parser Implementation (Option 2)

## Overview

Hybrid approach using traditional regex parser for simple cases and Groq LLM API for complex cases.

## Architecture

```
xlsx → Parser Router → [Traditional Parser | AI Parser (Groq)] → Structured Data → Database
```

## Parsing Strategy

### Traditional Parser Can Handle (No AI Needed)

These patterns can be matched directly with regex/traditional parsing:

1. **Simple village names**:
   - `Aleksandravas`
   - `Aukštadvaris`
   - `Aukštieji Rusokai`

2. **Village with streets in parentheses (standard format)**:
   - `Avižieniai (Akacijų aklg., Avižų g., Ąžuolų g., Baseino g., Braškyno g., Darželio g., Gabijos g., Gailašių g., Gajos g., Gegliškių g., Gerovės g., Gėlių g., Gilužio g., Kalno g., Kardelių g., Kaštonų g.,Kelpių g., Klevų g., Laurų g., Liepų g., Lubinų g., Mechanizatorių g., Miško g., Naujoji g., Parko g., Pavasario g., Perkūno g., Plukių g., Rožių g., Rytmečio g., Ryto g., Senoji g., Skandinavijos al., Slyvų g., Smilgų g., Sodų g., Stebuklų g., Šaltinio g., Tylioji g., Tujų g., Tulpių g., Upelio g., Vaikystės g., Žiburių g., Žirgupės g.)`
   - `Avižieniai (Durpių g., Ožiaraičių g., Saulės g., Svajonių g., Riešutų g.)`
   - `Bendoriai (Ateities g., Bendorėlių arka, Debesų g., Draugų g., Gausos g., Ilgoji g., Kėkštų g., Melisų g., Meškėnų g., Pavakario g., Samanynės g., Senasis Ukmergės kel.,  Trumpoji g., Žalčių g.,  Žemaitukų 1-oji g., Žirgyno g., Žvaigdžių g., Vyturių g., Vilnios g.)`

   **Important distinction - Ordinal street names vs House numbers**:
   - ✅ `Žemaitukų 1-oji g.` - This is a **street name** (ordinal suffix "1-oji" = "first", part of street name). Traditional parser can handle this.
   - ❌ `Sudervės g. 26, 28` - These are **house numbers** (numbers after street name). Needs AI parser.
   - ❌ `Kalvių 1-oji, 2-oji, 3-oji, 4-oji, 5-oji g.` - When combined with house numbers like `26, 28`, this becomes ambiguous and needs AI parser.

**Criteria for traditional parser**:
- Village name followed by parentheses
- Streets separated by commas
- **Street names with ordinal suffixes (X-oji g.) are OK** - these are part of the street name
- **No house numbers mixed in** (numbers after street names like "g. 26, 28")
- No complex nested structures

### AI Parser Needed (Send to Groq LLM)

These patterns require AI parsing due to complexity:

1. **House numbers mixed with streets**:
   - `Pikutiškės (Braškių g., Kalvių 1-oji, 2-oji, 3-oji, 4-oji, 5-oji g., Sudervės g. 26, 28, Žolynų g.)`
   - Contains: `Kalvių 1-oji, 2-oji, 3-oji, 4-oji, 5-oji g.` - **These are 5 separate streets** (Kalvių 1-oji g., Kalvių 2-oji g., etc.), schedule applies to **all house numbers** on all 5 streets
   - Contains: `Sudervės g. 26, 28` - **House number restrictions** (only houses 26 and 28 on Sudervės g.)
   - **Why AI parser needed**: Mixed format - some streets have no restrictions (all houses), others have specific house numbers. AI needs to:
     - Parse 5 separate ordinal street names (all houses)
     - Parse street with house number restrictions (only specific houses)
     - Distinguish between "all houses" vs "specific houses" correctly
   - Mixed format makes it complex - needs AI parser

2. **Complex house number patterns**:
   - `nuo X iki Y` (from X to Y - inclusive range)
   - `X-Y` (hyphenated range, e.g., `1-1`, `18-18U`)
     - `18-18U` means house numbers from 18 to 18U inclusive: **18, 18A, 18B, 18C, ..., 18U** (all letters from A to U)
   - `X, Y, Z` (list of specific house numbers)
   - `Nr. X` (house number X)

3. **Nested structures with house numbers**:
   - `Kaštonų g. ( nuo Nr. 1 iki 9 )` inside a larger list
   - Multiple levels of parentheses with house numbers

4. **Streets outside parentheses**:
   - `Bezdonys Pakalnės g., Draugystės g.` (no parentheses)
   - `Bendoriai (...)   Žalumos g.` (street after closing paren)

5. **Missing commas between items**:
   - `Melisų g. Pipirmėčių g. Ramunėlių g.` (no commas)

**Criteria for AI parser**:
- Contains house numbers (any format)
- Contains `nuo...iki` patterns
- Contains hyphenated numbers (`1-1`, `18-18U` - where `18-18U` means 18, 18A, 18B, ..., 18U)
- Missing commas between streets
- Streets outside parentheses
- Complex nested structures

## Implementation Logic

The routing logic is implemented in `scraper/parser_router.py` - see `should_use_ai_parser()` function.

The function checks for:
- House number indicators (nuo/iki, Nr., hyphenated numbers, numbers after street names)
- Missing commas between street names
- Streets outside parentheses
- Complex nested structures

## Examples Reference

### Simple (Traditional Parser)
- `Aleksandravas`
- `Aukštadvaris`
- `Avižieniai (Durpių g., Ožiaraičių g., Saulės g., Svajonių g., Riešutų g.)`
- `Bendoriai (Ateities g., Bendorėlių arka, Debesų g., Draugų g., Gausos g., Ilgoji g., Kėkštų g., Melisų g., Meškėnų g., Pavakario g., Samanynės g., Senasis Ukmergės kel.,  Trumpoji g., Žalčių g.,  Žemaitukų 1-oji g., Žirgyno g., Žvaigdžių g., Vyturių g., Vilnios g.)`

### Complex (AI Parser)
- `Pikutiškės (Braškių g., Kalvių 1-oji, 2-oji, 3-oji, 4-oji, 5-oji g., Sudervės g. 26, 28, Žolynų g.)`
- `Bendoriai ( Ilgoji g.,nuo 18 iki 18U,Ilgoji g., 27, 29, 31, 33, 35, 37, 37 A,B,C)   Žalumos g.`
- `Bezdonys Pakalnės g., Draugystės g.`
- `Gilužiai Trumpoji g.  (Nr. 1-1, 1-2, 5, 7, 9-1, 9-2, 11-1, 11-2, 13-1, 13-2)`

## Implementation Steps

### 1. Enhance Traditional Parser (`scraper/parser.py`)

**Goal**: Handle simple cases reliably (80%+ of data)

**Patterns to handle**:
- Simple village names: `Aleksandravas`
- Village with standard street list: `Avižieniai (Durpių g., Ožiaraičių g., ...)`
- Village with roads: `Bendoriai (..., Senasis Ukmergės kel., ...)`

**Improvements needed**:
- Better handling of inconsistent spacing
- Support for roads (kelias, kel.)
- Support for alleys (al.), squares (pl.), etc.

### 2. Create AI Parser Module ✅ **COMPLETE**

**File**: `scraper/ai/parser.py`

**Status**: ✅ Implemented and tested

**Functionality**:
- ✅ Connect to Groq API (using `groq` library)
- ✅ Send location string with structured prompt
- ✅ Parse JSON response into location structure
- ✅ Handle rate limiting (30 RPM, 14.4k RPD via `scraper/ai/rate_limiter.py`)
- ✅ Caching (SQLite-based via `scraper/ai/cache.py`)
- ✅ Error handling with fallback to traditional parser
- ✅ Full validation of AI output before caching
- ✅ Returns same format as traditional parser: `List[Tuple[str, Optional[str]]]`

**Prompt structure**:
```python
prompt = f"""
Parse this Lithuanian waste pickup location string into structured JSON:

Location: "{kaimai_str}"

Extract:
- village: Village/city name
- streets: List of street objects with:
  - name: Street name
  - house_numbers: Optional house number restrictions (nuo X iki Y, or list, or range)
  
Return JSON:
{{
  "village": "...",
  "streets": [
    {{"name": "...", "house_numbers": null}},
    {{"name": "...", "house_numbers": "nuo 18 iki 18U"}}
  ]
}}
"""
```

### 3. Create Parser Router (`scraper/parser_router.py`)

**Status**: ✅ Already created

**Function**: `should_use_ai_parser(kaimai_str: str) -> bool`

**Logic**:
- Check for house numbers (nuo, iki, Nr., numbers after street names)
- Check for hyphenated numbers (X-Y pattern)
- Check for missing commas
- Check for streets outside parentheses
- Return True if any complex pattern detected

**Function**: `parse_location(kaimai_str: str, seniūnija: str) -> List[Dict]`

**Flow**:
1. Call `should_use_ai_parser()`
2. If False → use traditional parser
3. If True → use AI parser
4. Return standardized structure

### 4. Update Main Parser (`scraper/parser.py`)

**Modify**: `parse_xlsx()` function

**Changes**:
- Import `parser_router`
- Replace `parse_village_and_streets()` calls with `parser_router.parse_location()`
- Keep date extraction logic unchanged

### 5. Add Groq Dependency

**Update**: `requirements.txt`
```
groq>=0.4.0
```

**Environment variable**: `GROQ_API_KEY`

### 6. Rate Limiting & Batching

**Challenge**: Groq free tier = 30 requests/minute

**Solution**: Batch processing with delays
- Process 30 locations → wait 60 seconds → continue
- For 700 rows: ~24 minutes total (acceptable for daily batch)

### 7. Error Handling

**Scenarios**:
- Groq API down → fallback to traditional parser (with warning)
- Rate limit exceeded → wait and retry
- Invalid response → log error, use traditional parser as fallback
- Network error → retry with exponential backoff

### 8. Testing Strategy

**Test cases**:
1. Simple village names (traditional parser)
2. Standard street lists (traditional parser)
3. House numbers (AI parser)
4. Missing commas (AI parser)
5. Streets outside parentheses (AI parser)
6. Mixed formats (AI parser)

**Validation**:
- Compare AI parser results with manual parsing
- Log confidence scores (if available)
- Flag suspicious results for review

## File Structure Changes

```
scraper/
├── __init__.py
├── fetcher.py
├── parser.py (modified - uses router)
├── parser_router.py (✅ created - routing logic)
├── ai_parser.py (new - Groq integration)
├── validator.py
└── db_writer.py
```

## Cost Analysis

- **Free tier**: 14,400 requests/day
- **Daily usage**: ~700 rows
- **With 80% traditional parser**: ~140 AI calls/day
- **Monthly**: ~4,200 AI calls
- **Cost**: $0 (within free tier limits)

## Success Metrics

- **Parsing accuracy**: >95% of locations correctly parsed
- **AI usage**: <30% of locations need AI (cost optimization)
- **Performance**: Daily batch completes in <30 minutes
- **Reliability**: <1% error rate
