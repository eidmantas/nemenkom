# v1.0 Supplemental Notes

This file keeps the original exploratory notes that were useful while the PDF parser was still
being stabilized. It is intentionally historical.

Current shipped behavior for Q2 / `1.1.0-rc1` lives in
[v1-1-continuity.md](./v1-1-continuity.md).

## What These Notes Still Tell Us

### AI parsing shape

The project expectation for complex PDF cells remains:

- one `seniunija`
- one or more village groups
- each group may include streets
- each group may exclude streets
- house numbers are preserved as compact strings, not expanded atomically

That output contract is still the basis for the downstream continuity code.

### Why AI is still needed

The provider regularly publishes mixed cells that include:

- several villages in one block
- explicit exclusions
- compact range syntax
- date tokens that can be mistaken for house numbers

The parser can normalize and repair a lot, but complex cells still need AI JSON splitting.

### Important v1.0 UX conclusion

The UI should expose waste-type availability conservatively:

- street-level plastic/glass may exist even when general waste requires a house-number bucket
- a street-level PDF schedule with `house_numbers = all` does not mean bendros can be inferred for the same whole street

The `Vanaginės g.` shape remains the canonical example of why this matters.

## Historical Lessons Carried Into 1.1 RC

- keep `house_numbers` compact and rule-based
- do not trust raw PDF wording as the continuity key
- do not merge waste types into one household model without better address truth
- let AI parsing stay structured and auditable instead of free-form text

## Where to Look Now

- implementation: `services/scraper_pdf/continuity.py`
- architecture: [../services/ARCHITECTURE.md](../services/ARCHITECTURE.md)
- testing: [./TESTING.md](./TESTING.md)
