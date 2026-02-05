# v1.0 Major Revision Notes

## Goal

Ship a v1.0 release that remains stable with imperfect provider data and avoids exploding the
number of Google calendars, while preparing for a future "single household calendar" model.

---

## Most Important (v1.0 Decision Gate)

Prove whether **plastic/glass schedules can be safely merged into the same calendar stream as
general waste**, based on schedule group timing overlap. If we cannot prove safe overlap, we keep
separate calendars by waste type for v1.0.

Evidence needed:

1. Extract PDF tables for plastic/glass, normalize to schedule groups.
2. Compare schedule groups against general waste for the same locations.
3. Quantify overlap/conflicts and define a safe merge rule.

---

## Current Reality (What We Have Today)

### Data Model

- `locations` stores address strings (seniunija, village, street, house_numbers) and a
  `kaimai_hash`.
- `schedule_groups` are keyed by the raw provider string (hash of `kaimai_str`) + waste type.
- Calendar streams are built by date pattern (not per household).

### Consequence

- If the waste provider changes formatting (ranges, suffixes, or text), the same real-world
  address becomes a new `kaimai_hash`, producing separate schedule groups.
- This leads to fragmentation, not mixing: the same household can appear in multiple groups if
  formatting changes.

---

## Why This Is Hard

- Different waste types (general/plastic/glass) are provided using different address standards.
- Even the same street can appear as:
  - Street-only (no house numbers)
  - Explicit ranges (`18-18U`)
  - Lists (`27,29,31,33,35,37,37A,B,C`)
- Some plastic/glass streets appear in the PDF but are missing in the general-waste `locations`
  dataset (even in prod), which blocks automated merging or matching.

If we merge these blindly, we can over-subscribe or mis-assign.

---

## Calendar Explosion Concern

Creating a calendar per household could mean 10k+ calendars, which is likely infeasible under
Google Calendar API rate limits.

We need a strategy that:

1. Keeps calendar count manageable.
2. Preserves consistency for users.
3. Can evolve later to household-level correctness.

---

## Decision Options

### Option A (Pragmatic, v1.0 Target)

- Keep date-pattern calendars (current model).
- Provide UI selection that makes waste-type availability obvious (v1.0 UX contract below).
- Improve parsing + AI cache + PDF coverage.
- Avoid household-level deduplication until we have authoritative address data.
- Current finding: PDF glass/plastic vs general waste shows no exact date overlaps after
  split/normalization; treat waste types as separate calendar streams for v1.0.

### Option B (Idealistic, Future v1.x / v2.0)

- Build a canonical household model.
- Normalize house numbers into atomic or range-safe entries.
- Use that as the single source of truth for all waste types.
- Allow a single household calendar with waste-type overlays.

Risk: Requires a major schema change and external address truth.

---

## House Number Normalization Reality

### Examples we already have

- `1-1,1-2,5,7,9-1,9-2,11-1,11-2,13-1,13-2`
- `27,29,31,33,35,37,37A,B,C`
- `18-18U`

### Key observation

- We cannot safely expand ranges without a canonical address database.
- Range strings are often ambiguous (e.g., `18-18U` might be letter suffixes or something else).

### Concrete mismatch we hit (why "explode everything" is risky)

Example: **Riešės seniūnija, Didžioji Riešė, Vanaginės g.**

- PDF plastic/glass rows often come through as **`house_numbers = all`** for the whole street.
- General waste `locations` (prod-synced) contains **multiple entries for the same street** split by house rules
  (e.g. `1-31A,2-14B`, `33A-101`, `103,103A-119,68,68A,68B-80`).

Consequence:

- A strict `(seniunija, village, street, house_numbers)` match will not match `all` to the split buckets.
- Naively exploding ranges into atomic houses would massively grow the dataset and still be incorrect without a
  canonical address truth source.

Recommended direction (v1.x/v2):

- Keep `house_numbers` as a **rule string**, but also persist a **parsed structure** (kind + segments) and implement
  a **containment predicate** (“does this user’s house number satisfy this rule?”) for selection/mapping.

### Recommended normalization (if we ever do canonical)

Store type + value, not just raw expansion:

- `kind = list | range | inequality | single`
- `value = "18-18U"` or `"27,29,31,33,35,37,37A,37B,37C"`
- Future: if we move to per-house calendars, we will need authoritative address data and a
  per-house-number normalization strategy (not just string ranges).

---

## OSM (Nominatim) Experiment

We tested Vanaginės g., Didžioji Riešė:

- `18 Vanaginės g.` exists in OSM.
- `37A` and `37B` exist.
- `18A..18U` returned only road results, no house numbers.

Conclusion: OSM is insufficient to validate suffix ranges.
We need to explore an authoritative dataset (e.g., data.gov.lt).

---

## PDF Scraper Status (Scraper PDF Service)

### Current state

- `services/scraper_pdf` exists (prototype).
- Parsing is still incomplete for normalization into `schedule_groups`.

### Plan

1. Finish PDF normalization and output format compatibility.
2. Compare general vs plastic/glass schedule groups.
3. Analyze how many overlaps are safe to merge.

---

## Calendar Consistency Risk (New XLSX Windows)

- Provider sometimes ships new XLSX files containing only future months, not old months.
- Need to re-verify in-place update logic:
  - Calendar streams must extend, not reset.
  - Tests exist but are not fully trusted.

---

## v1.0 Proposed Scope

### Must-have

- Stable calendar streams by date pattern.
- PDF scraper normalization completed (marker-pdf HTML path).
- AI parsing robust (cache, retries, rotation).

### Should-have

- Strong logging for AI rotation + retries.
- Explicit docs for all data inconsistencies.
- Safe rules for matching waste types without merging household calendars.

---

## TODOs

- Explore data.gov.lt for authoritative address/house-number datasets.
- Validate XLSX "new window" behavior with new test cases.
- Decide if/when to introduce canonical household schema.

---

## Open Questions

- Can we safely merge glass/plastic into general without over-subscribing?
- Which waste types are guaranteed to match by street/house?
- What is the maximum acceptable number of Google calendars in prod?

---

## Next Step (Immediate)

Finish `services/scraper_pdf` normalization and compare parsed outputs for:

- general vs plastic vs glass
- whether address patterns overlap cleanly or diverge

---

## Follow-up Dev Log

### 2026-01-31

- Decision: treat marker-pdf output as multiple tables per page, then merge into one logical table
  by normalizing headers and concatenating rows.
- PDF rows often contain multiple villages in a single cell; switch to whole-cell AI parsing with
  explicit include/exclude streets schema to handle "išskyrus".
- Keep a strict rule: if a page has no header, carry forward the last known header schema.
- Keep repeated headers as no-ops (dedupe during row parsing).
- Implemented marker-pdf HTML parsing path (no camelot fallback).
- Added PDF-specific AI cache table keyed by `kaimai_hash` + `waste_type`.
- Ran single-provider raw AI parsing tests for PDF cells (simple + complex); outputs stored in
  `documentation/v1-0-major-revision-supplement.md`.
- Increased PDF AI timeout handling (see `PDF_AI_TIMEOUT_SECONDS`, now 300s).

### 2026-02-03

- Added row-level PDF normalization output (`*.rows.csv`) as phase-1 truth before AI/splitting.
- Removed custom marker-pdf HTML caching; we rely on marker-pdf behavior and the source fetch cache (HEAD/hash) for idempotency.
- Fixed header pre-rows, month-column mapping, and waste-type fallback (carry last label).
- Added row-merge heuristic for split location lines and fail-fast validation for empty-month rows.
- Plastic rows match screenshots across all pages; glass mostly matches with remaining gaps noted.
- Added AI prompt rule: `d.` tokens are dates, not house numbers.
- Added AI output normalization for list vs object responses.
- Added AI provider failover on timeouts/429s to continue rotation.
- Backfilled missing `waste_type_cell` from PDF filename for glass/plastic runs.

### 2026-02-04

- Synced `locations` from prod DB for mapping; confirmed PDF has streets not present in general waste.
- AI name-mapping now runs list-based per category and stores mapped fields in `pdf_parsed_rows`.
- Decision: keep plastic/glass rows as-is when no canonical match exists.
- Observed many unmapped streets likely due to genitive/nominative or missing general-waste data.
- PDF AI parser prompt rewritten as a single coherent schema-first spec; added per-group `seniunija` support so
  multi-seniūnija cells can be represented without data loss.
- Verified `Didžioji Riešė / Vanaginės g.` exists in both PDF rows and general waste, but does not match cleanly
  due to `all` vs split house-number rules (see mismatch section above).

---

## Next Steps (E2E Checklist)

Use this list verbatim to resume work without extra context.

1. **Install deps + verify versions**
   - `make venv-install` (or `venv/bin/pip install -r requirements.txt`)
   - Confirm `marker-pdf==1.10.1` and `openai>=2.16.0` are installed.
   - Expect pip to warn about marker-pdf `<2.0.0` constraint; note it but continue.

2. **Verify PDF table extraction (no AI)**
   - Run: `venv/bin/python services/scraper_pdf/main.py /path/to/glass.pdf`
   - Ensure `.rows.csv`, `.parsed.csv`, and `.raw.csv` are generated for inspection.
   - Confirm multiple page headers are handled and rows are populated.
   - No marker output cache to clear; re-run with `--force` when you want to rebuild parsed output.

3. **Inspect raw tables**
   - Open `.rows.csv` to verify row-level locations + month values before splitting.
   - Open `.raw.csv` to debug extraction glitches.
   - Check that header dedupe and carry-forward rules behave correctly.

4. **Run single-provider AI tests (raw HTTP, no retries)**
   - Use the raw requests snippet from `documentation/v1-0-major-revision-supplement.md`.
   - Tests already executed (simple + complex), outputs captured in the supplement.
   - Results: schema matched (seniunija + groups, include/exclude); house numbers stayed compact
     (e.g., `18-18U, 27, 29, ...`) and were not expanded into numerical lists.
   - Note: complex test required a higher timeout (120s+) to return.
   - If rerunning, paste new outputs into the supplement and compare against prior results.

5. **Enable AI parsing for PDF (optional)**
   - Default is AI enabled; run: `venv/bin/python services/scraper_pdf/main.py /path/to/glass.pdf`
   - Confirm `pdf_ai_parser_cache` is populated.
   - Verify `pdf_parsed_rows.exclude_streets_json` is filled.
   - If AI providers time out or 429, rotation should failover automatically; check logs.

6. **Check SQLite outputs**
   - Inspect `pdf_ai_parser_cache` and `pdf_parsed_rows` tables.
   - Validate that include/exclude streets look sane for tricky villages.

7. **Compare PDF vs general waste**
   - Run comparison script: `venv/bin/python services/scraper_pdf/compare.py`
   - Capture counts of overlaps/mismatches to evaluate merge feasibility.

8. **Decide on merge safety**
   - Summarize overlap stats: safe vs conflicting cases.
   - Decide if glass/plastic can merge into general waste streams.

8a) **Decide the v1.0 address-selection contract**

- Keep separate waste-type calendars (no merge).
- Address lookup for subscription must still pick the correct schedule group for each waste type.
- Define matching precedence: exact street+house rule > street-only > village-only.
- Document that PDF may use `house_numbers=all` where general waste is split; v1.0 may still provide correct
  subscriptions via separate waste-type streams.

8a.1) **v1.0 Web UX contract (Option 1: bucket-based, no containment)**

- Street dropdown shows **waste-type chips** when a waste type is available for that street:
  - If general waste ("bendros") is split by house-number buckets, do NOT show `bendros` chip at street-level.
  - If plastic/glass is available at street-level (often PDF `all`), show `plastikas`/`stiklas` chips.
- House-number dropdown shows chips per bucket when `bendros` requires buckets.
- Users may need to subscribe to multiple waste-type calendars separately (expected in v1.0).

8a.2) **Option 2 (later): containment matcher**

- Allow users to enter `25`, `2C`, `37A` and match against bucket rules (range/list/inequality).
- Only implement conservatively and fall back to manual bucket selection when ambiguous.

8b) **Design v1.x/v2 house-number containment**

- Add a parsed house-number representation (do NOT explode ranges).
- Implement membership checks for user input (e.g. `2C`, `37A`) against list/range/inequality rules.
- Consider a derived table (e.g. `house_number_rules`) rather than bloating `locations`.

9. **Document decisions**
   - Append findings to this file and to `CHANGELOG.md`.
   - Keep supplemental doc updated with any new AI test outputs.
   - Keep Kovo 30 glass row gap tracked in TODO (marker extraction issue).

10. **Review unmapped PDF streets**

- Inspect `tmp/unmapped_streets.txt` and confirm if missing from general waste data.
- If missing, keep PDF streets as-is (no forced mapping) and treat as separate calendars.
