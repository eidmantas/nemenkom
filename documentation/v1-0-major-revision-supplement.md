# v1.0 Major Revision - Supplemental Notes

This file captures ad-hoc AI parsing tests and outputs so we can resume later without rerunning
costly calls.

---

## PDF AI Parsing Tests (Single-Provider, Raw HTTP)

Provider used (from `AI_MODEL_ROTATION[0]`):

- `gemini:gemini-3-flash-preview`

### Test 1 (Simple multi-village cell)

Input:

```
Avižienių sen. Mažosios Riešės k. Kalno g. (išskyrus Kalno g.)
Lindiniškių k. (išskyrus Astrų g., Mėtų g., Tvenkinio g.)
Bajorų k. Draustinio g.
```

Output:

```
{
  "seniunija": "Avižienių sen.",
  "groups": [
    {
      "village": "Mažosios Riešės k.",
      "include_streets": [
        {"street": "Kalno g.", "house_numbers": "all"}
      ],
      "exclude_streets": [
        {"street": "Kalno g.", "house_numbers": "all"}
      ]
    },
    {
      "village": "Lindiniškių k.",
      "include_streets": [],
      "exclude_streets": [
        {"street": "Astrų g.", "house_numbers": "all"},
        {"street": "Mėtų g.", "house_numbers": "all"},
        {"street": "Tvenkinio g.", "house_numbers": "all"}
      ]
    },
    {
      "village": "Bajorų k.",
      "include_streets": [
        {"street": "Draustinio g.", "house_numbers": "all"}
      ],
      "exclude_streets": []
    }
  ]
}
```

### Test 2 (Complex cell with ranges, lists, exclusions)

Input:

```
Avižienių sen. Didžioji Riešė k. Vanaginės g. 18-18U, 27, 29, 31, 33, 35, 37, 37A,B,C;
Mažosios Riešės k. (išskyrus Kalno g. 1-15, 21A, 22, 24-30)
Riešės k. Parko g., Žalioji g. nuo 5 iki 19, nuo 24 iki 30;
Lindiniškių k. (išskyrus Astrų g., Mėtų g., Tvenkinio g.)
Bajorų k. Draustinio g., Pievų g. (išskyrus Pievų g. 2-10)
```

Output:

```
{
  "seniunija": "Avižienių sen.",
  "groups": [
    {
      "village": "Didžioji Riešė k.",
      "include_streets": [
        {
          "street": "Vanaginės g.",
          "house_numbers": "18-18U, 27, 29, 31, 33, 35, 37, 37A,B,C"
        }
      ],
      "exclude_streets": []
    },
    {
      "village": "Mažosios Riešės k.",
      "include_streets": [],
      "exclude_streets": [
        {"street": "Kalno g.", "house_numbers": "1-15, 21A, 22, 24-30"}
      ]
    },
    {
      "village": "Riešės k.",
      "include_streets": [
        {"street": "Parko g.", "house_numbers": "all"},
        {"street": "Žalioji g.", "house_numbers": "5-19, 24-30"}
      ],
      "exclude_streets": []
    },
    {
      "village": "Lindiniškių k.",
      "include_streets": [],
      "exclude_streets": [
        {"street": "Astrų g.", "house_numbers": "all"},
        {"street": "Mėtų g.", "house_numbers": "all"},
        {"street": "Tvenkinio g.", "house_numbers": "all"}
      ]
    },
    {
      "village": "Bajorų k.",
      "include_streets": [
        {"street": "Draustinio g.", "house_numbers": "all"},
        {"street": "Pievų g.", "house_numbers": "all"}
      ],
      "exclude_streets": [
        {"street": "Pievų g.", "house_numbers": "2-10"}
      ]
    }
  ]
}
```

### Observations

- Output matches the intended schema (seniunija + groups, include/exclude).
- When no explicit house numbers exist, the model returns `"all"`.
- For complex ranges and lists, the model keeps them compact (no expansion).
- The complex test required a higher timeout (120s) to return a response.
- Timeout handling updated in code (`PDF_AI_TIMEOUT_SECONDS = 300`).

---

## PDF Row-Level Validation (Phase 1, No AI)

- Added `*.rows.csv` output for phase-1 row normalization (location + month columns).
- Plastic pages 1–4 match screenshot dates/locations at row level.
- Glass pages mostly match; remaining issues tracked during comparison runs (noted in dev log).

---

## Full PDF Runs (AI Enabled)

### 2026-02-03 - Glass re-run (AI enabled, failover active)

- `glass_ai_run.log` completed without errors/timeouts/429s.
- Page-by-page screenshot comparison matches all rows **except** the known missing Kovo 30 row.
- Kovo 30 row (Avižienių/Aleksandravo + Paberžės + Nemenčinės + Maišiagalos) is still missing
  in marker output; tracked in `CHANGELOG.md` TODO.
- One row had empty `waste_type_cell` in `glass.rows.csv` (Bajorų/Lindiniškių, 23 d.);
  fixed by backfilling `waste_type_cell` from PDF filename (glass/plastic).

### 2026-02-04 - PDF/General waste mapping sanity check

- Synced `services/database/waste_schedule.db` locations from `tmp/prod-db.db`.
- Re-ran plastic PDF with AI mapping (list-based per category, no chunking).
- Coverage after sync: seniunija/village fully mapped; ~65 streets remain unmapped.
- Example unmapped streets: `Minties g.`, `Raisto g.`, `Riešės 1-oji g.`; many are likely
  genitive/nominative variants or missing in general waste data.
- Unmapped list saved to `tmp/unmapped_streets.txt` for review.

### 2026-02-04 - PDF vs general waste compare (AI-only mapping)

- Re-ran plastic + glass PDFs with AI-only mapping (no heuristic pre-match).
- Report:
  - total_pdf_rows: 1104
  - matched_to_general: 489
  - exact_date_overlap: 0
  - conflicts: 489
  - no_general_match: 615
- By waste type:
  - plastikas: matched 253, conflicts 253, no_general_match 410
  - stiklas: matched 236, conflicts 236, no_general_match 205

### Prompt/Parsing Updates

- Prompt now explicitly treats `d.` tokens as dates (not house numbers).
- AI output normalization accepts list responses by coercing into the expected object shape.

---

## 2026-02-04 - v1.0 UX Notes (Waste-Type Availability Chips)

Goal: make it obvious in the web dropdowns what can be subscribed to for a given selection.

Implemented (Option 1):

- Street dropdown items can display chips like `bendros`, `plastikas`, `stiklas` when that waste type is available.
- If `bendros` requires house-number buckets for a street, we hide `bendros` at street-level and only show it on the
  house-number bucket dropdown (because selection must pick the exact bucket string).

Concrete example (Didžioji Riešė / Vanaginės g.):

- Street-level: shows `plastikas` + `stiklas` chips.
- House-number buckets: show `bendros` on specific buckets like `1-31A,2-14B`.

Deferred (Option 2):

- Add conservative house-number containment, so users can type `25`/`2C`/`37A` and auto-select the right bucket.
