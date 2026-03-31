# v1.0 Major Revision Notes

This file is kept as the original v1.0 planning record.

If you need the current shipped continuity behavior, use
[v1-1-continuity.md](./v1-1-continuity.md).

## What v1.0 Solved

v1.0 established the project shape:

- stream-based calendars instead of per-household calendars
- XLSX + PDF ingestion paths
- UI support for separate waste-type availability
- the first safe version of shared date-pattern calendars

## Main v1.0 Constraint

We deliberately did **not** merge plastic/glass into the same stream as general waste.

Reason:

- provider datasets use different address shapes
- PDF rows often describe a whole street with `house_numbers = all`
- general waste often splits that same street into multiple house-number buckets

That means a naive merge would over-subscribe or mis-assign users.

## Main v1.0 Risk We Carried Forward

The original continuity key for PDF schedules was too dependent on raw provider wording:

```text
schedule_group_id = hash(waste_type + kaimai_hash)
kaimai_hash       = hash(raw PDF kaimai_str)
```

So harmless provider wording changes could create new groups and eventually new calendars.

That exact risk is what `1.1.0-rc1` fixes.

## Still Useful v1.0 Conclusions

- date-pattern calendars are a practical compromise for API limits
- household-level canonical modeling remains a future project
- house-number ranges cannot be safely exploded without an authoritative address source
- glass/plastic should stay as separate waste-type calendars for now

## House-Number Reality

Examples still seen in source data:

- `18-18U`
- `27,29,31,33,35,37,37A,B,C`
- `1-31A,2-14B`

This is why the system still treats `house_numbers` as a rule string rather than a canonical
expanded address list.

## Future Work

- authoritative address source exploration, likely outside OSM
- parsed `house_numbers` structure with containment logic
- better migration UX when the provider truly changes one street from one group to another

## Pointer Forward

For the actual Q2 / quarter-rollover behavior, read:

- [v1-1-continuity.md](./v1-1-continuity.md)
- [../services/ARCHITECTURE.md](../services/ARCHITECTURE.md)

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

5) **Enable AI parsing for PDF (optional)**
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
