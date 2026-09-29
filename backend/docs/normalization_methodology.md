# VAYU INDEX - Phase 8 Normalization Methodology

**Status:** implemented and verified
**Pipeline position:** Phase 7 (source consolidation) -> **Phase 8 (normalization)** -> Phase 9 (anomaly detection) -> Phase 10
**Schema version tag:** `phase8-v1`

---

## 1. Governing principle

> **Phase 8 canonicalizes REPRESENTATION. It never changes economic content.**

Every Phase 8 operation is one of:

1. a **representation** change (for example `7000` -> `7000.00`), or
2. a **derived metadata** addition (for example `round_sort_key`, `price_state`), or
3. a **flag** recording that something is unknown, missing or inconsistent.

Phase 8 never edits a fare's value, never imputes a missing value, never removes
a row, never merges rows and never reverses a route.

## 2. Honest characterisation of the current corpus

This must not be overstated. On the real 778-observation corpus, Phase 8 is
**almost a no-op in economic terms**:

| Measure | Result |
| --- | --- |
| Economic values changed | **0** |
| Rows added / merged / deleted | **0** |
| Whitespace or case corrections needed | **0** |
| Alias substitutions applied | **0** |
| Monetary representation changes (`MONEY_QUANTIZED`) | **777** |
| Unknown categorical values found | **0** |
| Rows flagged `FARE_DECOMPOSITION_INCOMPLETE` | **2** |
| Cells flagged `MISSING_PRICE` | **1** |

Phase 8 is therefore best understood as a **contract-enforcing and
lineage-adding stage** rather than a data-cleaning stage. Its value is that it
*proves* the corpus is already canonical, and that it supplies the derived
fields (`price_state`, `round_sort_key`, `currency`, `fare_class_tier_rank`)
that Phase 9 requires. The canonicalisation machinery exists so that a dirtier
future corpus is handled correctly, not because the current corpus is dirty.

## 3. Inputs and outputs

### Inputs (read-only)

| File | Rows | Role |
| --- | --- | --- |
| `outputs/consolidated_airfare_observations.csv` | 393 | primary analytical unit (consolidation cells) |
| `outputs/phase7_flight_cell_report.csv` | 571 | flight-level cells |
| `outputs/phase7_observation_map.csv` | 778 | observation-to-cell lineage |
| `outputs/canonical_airfare_observations.csv` | 778 | joined for fare components and departure time |

### Outputs

| File | Rows x Cols | Role |
| --- | --- | --- |
| `outputs/normalized_airfare_observations.csv` | 393 x 51 | **primary Phase 9 input** |
| `outputs/phase8_flight_cell_normalized.csv` | 571 x 42 | normalized flight cells |
| `outputs/normalized_observation_map.csv` | 778 x 49 | normalized observation lineage |
| `outputs/phase8_normalization_report.csv` | 777 x 7 | per-change audit trail |

Row counts are invariant: 393 -> 393, 571 -> 571, 778 -> 778.

---

## 4. The two-tier canonicalisation model

This is the single most important design decision in Phase 8, and it is a
deliberate deviation from naive "clean the column in place" normalization.

Phase 7 identity fields are **embedded inside** the identifiers
`consolidation_cell_id` and `flight_cell_id`, for example:

```
CELL::BLR|HYD|2026-09-06|Economy Flexi|T1(0-2)::ROUND::2026-09-05T09:00
```

If Phase 8 rewrote `origin` or `fare_class` in place, the row's own ID would no
longer describe the row, silently breaking every downstream join and every
Phase 6 / Phase 7 hash. Therefore:

> **Tier 1 - verify and flag.** The original Phase 7 columns are carried through
> **byte-identically**. They are never rewritten.
>
> **Tier 2 - derive alongside.** Canonical values are written to *new* columns:
> `origin_canonical`, `destination_canonical`, `travel_date_canonical`,
> `fare_class_canonical`, `carrier_canonical`, `flight_number_canonical`,
> `departure_time_canonical`.

A disagreement between tier 1 and tier 2 is recorded as a flag, never silently
resolved. On the current corpus there are zero disagreements: every
`*_canonical` value equals its source value.

Verification enforces this: all 36 consolidated columns, all 24 flight-cell
columns and all 21 observation-map columns are asserted identical to Phase 7.

## 5. Monetary handling

- All money flows through `Decimal`. **`float(` is banned from Phase 8 source**
  and this is enforced by both the test suite and `verify_phase8.py`.
- Quantization is `Decimal("0.01")` with `ROUND_HALF_UP`, to exactly 2 decimal
  places.
- Quantization is a **representation** change only. The verifier asserts
  `Decimal(original) == Decimal(normalized)` for all 777 report rows, so the
  economic value is provably unchanged.
- The original `total_fare` / `consolidated_fare` columns are preserved as-is;
  the 2 dp form lands in `total_fare_normalized` /
  `consolidated_fare_normalized`.
- Fractional fares are preserved exactly (for example `5612.25`).

## 6. Currency

- `currency = INR` on every row.
- `currency_source = DECLARED_PROTOTYPE_CONSTANT`.
- `FX_CONVERSION_SUPPORTED = False`.

No currency column existed anywhere upstream. INR is a **declared prototype
constant**, not an observed or inferred field. No exchange-rate logic exists
anywhere in Phase 8.

## 7. Fare class tier rank (derived metadata only)

`fare_class_tier_rank` maps `Economy Saver` -> `1`, `Economy Standard` -> `2`,
`Economy Flexi` -> `3`; unknown classes yield an empty string.

> **It is derived metadata ONLY.** It must never enter economic identity,
> consolidation keys or product keys.

Verification asserts that `fare_class_tier_rank` is absent from
`ECONOMIC_IDENTITY_FIELDS`, absent from `CONSOLIDATION_CELL_FIELDS`, never
appears inside any `consolidation_cell_id`, and that
`FARE_CLASS_TIER_RANK_IS_IDENTITY_FIELD is False`.

## 8. Alias policy

The fare-class, source and carrier alias maps are **empty by explicit
approval** (`ALIAS_MAPS_EMPTY_BY_APPROVAL = True`). No aliases were invented.
The machinery is present and tested, but it applies zero substitutions, and the
verifier asserts that no `ALIAS_APPLIED` action was ever emitted.

Canonicalisation is limited to genuinely safe operations: whitespace trimming,
internal whitespace collapsing, and case normalization for airport codes and
carrier codes. **Genuinely different fare products are never collapsed.**
`Economy Saver`, `Economy Standard` and `Economy Flexi` remain three distinct
products.

## 9. Unknown values: FLAG AND CONTINUE

An unrecognised fare class, source, carrier, advance-purchase window or
availability state is **flagged and carried**, never dropped and never
rewritten. Phase 8 does not hard-fail the run on an unknown value. Flags used:
`UNKNOWN_FARE_CLASS`, `UNKNOWN_SOURCE`, `UNKNOWN_CARRIER`,
`UNKNOWN_ADVANCE_PURCHASE_WINDOW`.

On the current corpus, zero unknown values occur; the behaviour is proven by
the synthetic fixture instead (see section 13).

## 10. Timestamps, round ordering, and the lexical trap

`collection_timestamp` is treated as a **naive local datetime**
(`COLLECTION_TIMESTAMP_IS_NAIVE_LOCAL = True`,
`TIMEZONE_INFERENCE_PERFORMED = False`). **No timezone is fabricated.** An ISO
rendering is added as `collection_timestamp_iso`; no offset is invented.

### The lexical ordering trap

`collection_round_id` values cannot be sorted as text. Because `-` is ASCII
`0x2D` and `:` is ASCII `0x3A`, we have `'-' < ':'`, so **every**
`ROUND-UNALIGNED::...` identifier sorts *before* **every** `ROUND::...`
identifier, regardless of the instant it represents:

```
ROUND-UNALIGNED::2026-09-07 23:59   <- sorts FIRST lexically
ROUND::2026-09-05T09:00             <- sorts SECOND lexically
```

Ordering rounds lexically would therefore **manufacture fictitious price
movements** in Phase 9's temporal rules. Phase 8 solves this with
`round_sort_key`, a real `YYYY-MM-DD HH:MM` timestamp, plus
`round_sort_key_source` recording provenance:

| provenance | meaning | count |
| --- | --- | --- |
| `ANCHOR_TIMESTAMP` | taken from `round_anchor_timestamp` | 385 |
| `ROUND_ID` | parsed from an unaligned round identifier | 8 |
| `UNRESOLVED` | no key derivable; sorts LAST, never silently first | 0 |

Rows with no resolvable key sort **last**, never first, so a missing key can
never masquerade as the earliest observation.

## 11. Explicit price state

`price_state` removes the ambiguity of a blank fare. It is one of `PRICED`,
`SOLD_OUT`, `MISSING_PRICE`, `NO_PRICE_CELL`. On the current corpus:
392 `PRICED` cells and 1 `NO_PRICE_CELL`. A `NO_PRICE_CELL` row never carries a
normalized fare, so Phase 9 can never mistake "no price" for "price of zero".

## 12. No imputation, no reconstruction

- Missing fare components are **never** reconstructed. `OBS00777` and
  `OBS00778` have blank components and are flagged
  `FARE_DECOMPOSITION_INCOMPLETE`; the blank count is 2 before and 2 after.
- The one no-price cell is never assigned an invented fare.
- `fare_components_reconcile` records whether `base_fare + taxes + fees` equals
  `total_fare` within the inherited Phase 2 tolerance of INR 1.00. It reports;
  it does not repair.

---

## 13. The normalization report and its grain

`outputs/phase8_normalization_report.csv` has 7 columns:

```
entity_type, entity_id, field, action, original_value, normalized_value, detail
```

**Approved audit granularity: `(entity_id, field, action)`.** This triple is
asserted UNIQUE across the report, and the report is sorted deterministically
by `(entity_type, entity_id, field, action)`.

### Report-grain ruling (documented deviation)

The report records **only real representation changes and flags**. It does NOT
emit one row per derived column. Emitting a row for every derived field would
produce roughly 393 x 13 rows of pure noise and would bury the handful of rows
that actually matter. Derived-column *values* are visible in the output files
themselves; the report is reserved for changes and exceptions.

On the current corpus all 777 report rows are
`OBSERVATION / total_fare / MONEY_QUANTIZED` - for example `10259` ->
`10259.00`. There are **zero** economic-value changes.

## 14. Determinism and idempotence

- `run_normalization` is a pure function of its inputs; inputs are never
  mutated.
- Re-running the engine reproduces all four outputs **byte-identically**.
- Shuffling every input frame (`random_state=20260910`) produces identical
  output, so the result is order-independent.
- Output ordering follows a declared **chronological** contract:
  canonical route identity, then `round_sort_tuple(round_sort_key, id)`.
  Observations are ordered by `observation_id`. Output order is deliberately
  **not** lexicographic on the cell identifier, for the reason given in
  section 10.
- No randomness, no RNG, no ML. `sklearn`, `import random` and `numpy.random`
  are banned tokens enforced by tests and by the verifier.

## 15. Verification summary

| Gate | Result |
| --- | --- |
| `tests/test_normalization.py` | **127 passed / 0 failed** |
| `scripts/verify_phase8.py` | **127 checks passed / 0 failed** |
| Locked Phase 1-7 artefacts | all byte-identical |
| Idempotence re-run | all four outputs byte-identical |

The test suite includes a `TestCodeQualityGuard` class that scans Phase 8
source for banned constructs, including attribute-style pandas row access.

### Why attribute-style row access is banned

Attribute access such as `.prod`, `.min`, `.max`, `.count` or `.size` on a
pandas row silently resolves to a **Series method** instead of the column of
that name. During Phase 9 calibration this exact defect produced 384 phantom
single-point series and invalidated a first projection; it was caught only by
cross-checking. Column access must always be explicit:
`row["column_name"]`. The guard exists so this can never recur silently, and
it includes a self-test proving the guard itself can fail.

## 16. Calibration labelling convention

Phase 8 introduces no thresholds of its own. Where a downstream constant is
calibrated against the current synthetic corpus, it is labelled
`PROTOTYPE_CALIBRATION` and must never be presented as an official MoSPI
threshold or a universal statistical truth. The anchor schedule inherited from
Phase 7 (`09:00`, `14:30`, `20:15`) remains a **prototype configuration derived
from the current synthetic collection schedule, not a finalized production
sampling schedule**.

## 17. Explicitly out of scope for Phase 8

Phase 8 does **not**:

- detect, score, remove or annotate anomalies (Phase 9)
- compute any index value, route aggregate or source weight (Phase 10)
- add Phase 5 basket membership
- re-bin advance-purchase windows
- reverse or repair route direction (the known DEL-BOM / DEL-BLR / MAA-CCU /
  BLR-HYD basket mismatch is **intentionally left unresolved**)
- merge economically distinct sources
- shift travel dates or collection dates
- fabricate timezones or exchange rates
- impute, interpolate or reconstruct any missing value
- modify any Phase 1, Phase 2, MoSPI, DGCA, Phase 5, Phase 6 or Phase 7 file
