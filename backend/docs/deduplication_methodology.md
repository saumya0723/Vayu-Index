# VAYU Phase 6 — Deduplication Methodology

**Status:** Implemented and verified.
**Input:** `outputs/validated_airfare_observations.csv` (Phase 2 output, 783 rows)
**Outputs:**
1. `outputs/deduplicated_airfare_observations.csv` — full audited dataset (783 rows, original 23 columns + 6 audit columns)
2. `outputs/canonical_airfare_observations.csv` — derived canonical analytical view (778 rows)
3. `outputs/phase6_duplicate_audit_report.csv` — one row per confirmed duplicate group

**Verification:** `python scripts/verify_phase6.py` (27 acceptance checks, read-only)

## Pipeline position

```
RAW (783) → VALIDATION (783, +4 verdict columns) → DEDUPLICATION (783, +6 audit columns)
    → SOURCE CONSOLIDATION (not implemented) → NORMALIZATION (not implemented)
    → ANOMALY DETECTION (not implemented) → ROUTE AGGREGATION (not implemented) → INDEX (not implemented)
```

Deduplication grouping runs **only** on the 779 rows where Phase 2's `is_valid == True`. The 4 `is_valid == False` rows pass through completely unevaluated, retaining every Phase 2 verdict column, tagged `duplicate_reason = SKIPPED_INVALID_BY_PHASE2`, `retained = True`.

## Identity keys

**Economic identity** (route + product-class level, matches the pre-existing `economic_signature` field's own construction):
`(origin, destination, travel_date, fare_class, advance_purchase_window)`

**Product-instance identity** (economic identity + the fields it deliberately excludes):
`economic identity + (carrier, flight_number, normalized departure_time)`

## Technical duplicate rule

All five conditions required:
1. Same economic identity
2. Same product-instance identity
3. Same source
4. Same total_fare (exact)
5. `collection_timestamp` difference ≤ 15 minutes

These five conditions are the complete rule. No sixth condition exists. `availability_status` appears in the grouping bucket key purely as an implementation guard for the sold-out rule below; `capture_signature_agreement` is audit output, never an input to the decision.

### Grouping strategy — anchored sweep, not transitive chaining

Within each bucket, candidate records are sorted deterministically by parsed `collection_timestamp`, then `observation_id`. The earliest record becomes the **anchor**. A following record joins that group only if its timestamp is within 15 minutes **of the anchor**. Once a record exceeds that window it starts a new group and becomes the new anchor.

Transitive chaining is explicitly rejected: under chaining, observations drifting 14 minutes apart would collapse into one unbounded group spanning hours, silently destroying genuine repeated captures. The boundary is inclusive at exactly 15 minutes and exclusive at 16.

### `collection_timestamp` interpretation

Timestamps are parsed as **naive local datetimes exactly as represented in the input** (`%Y-%m-%d %H:%M`). No timezone is inferred, assigned, converted, or fabricated — the Phase 2 file carries no timezone markers, and inventing one would be an unfounded assumption. A value that is empty or does not match the declared format is treated as unparseable and is **never** considered "within tolerance". Should the collection layer later emit timezone-aware timestamps, this assumption must be revisited before comparison.

### `is_valid` parsing

Phase 2's verdict is read strictly: only the literal booleans `True`/`False` and the exact strings `"True"`/`"False"` are accepted. Anything else raises `IsValidParseError` rather than defaulting. This exists because raw-string truthiness would evaluate `bool("False")` as `True` and silently admit invalid rows into grouping.

### `total_fare` comparison

Fares are compared through a canonical normalized form that treats `5400`, `5400.00` and `5400.0` as equal while preserving integer formatting in every emitted field (`"5400"`, never `"5400.0"`). The raw `total_fare` column itself is never rewritten.

**Time tolerance justification:** the dataset's observed collection cadence is a fixed daily schedule (~09:00 / 14:30 / 20:15, ~345 minutes apart). 15 minutes gives a >20x safety margin below that gap while comfortably covering realistic single-pass retry/pagination latency (the one genuine planted duplicate, OBS00770, is 1 minute after OBS00769). Must be recalibrated once real scraper cadence is known.

## `capture_signature` — not used as the hard key

Direct inspection proved `capture_signature` normally changes with `collection_timestamp` (OBS00769 ≠ OBS00770's hash) but was found identical between OBS00769 and a since-invalidated missing-timestamp row (OBS00781) — behavior that couldn't be explained without the generator source, which was unavailable. It is retained only as `capture_signature_agreement` (True/False/None), an informational **audit-only** field. It is a **group-level** property — whether records within a confirmed duplicate group share the same `capture_signature` — and is therefore recorded identically on every member of that group, the canonical record included. It is empty for singletons, ungrouped rows and invalid rows, and is never used to decide duplicate status. On the one real duplicate pair (OBS00769/770), `capture_signature_agreement = False` — concrete evidence for why this field cannot be trusted as authoritative.

## Sold-out handling
Sold-out rows deduplicate only against other sold-out rows sharing economic + product-instance identity + source + time tolerance. Never compared to a priced row by fare.

## Missing identity / missing timestamp
Rows with a missing core identity field are excluded from grouping, retained, tagged `EXCLUDED_MISSING_IDENTITY`. A missing `collection_timestamp` is never assumed "within tolerance" — under current Phase 2 rules this can't reach deduplication at all (`MISSING_COLLECTION_TIMESTAMP` → `INVALID`, confirmed by OBS00781), but the `AMBIGUOUS_MISSING_TIMESTAMP_POSSIBLE_DUPLICATE` path is kept as defensive future-proofing and directly unit-tested by bypassing the Phase 2 gate.

## Determinism and order-independence
Pure function of field values. Canonical record within a duplicate group: earliest valid `collection_timestamp`, tie-broken by lowest `observation_id` lexicographically. Verified by `test_deterministic_rerun` and `test_shuffled_input_produces_identical_grouping`.

## Audit fields
`duplicate_group_id`, `is_duplicate`, `duplicate_of`, `duplicate_reason`, `retained`, `capture_signature_agreement` — appended to every row; no raw column ever dropped or modified; no raw row ever deleted.

`duplicate_group_id` uses explicit namespaces so a group identifier can never be mistaken for another category:

| Prefix | Meaning |
| --- | --- |
| `DUPGRP-` | confirmed duplicate group (≥2 members) |
| `SINGLETON::` | evaluated, no duplicate found |
| `UNGROUPED::` | excluded from grouping (missing identity, unusable price, ambiguous timestamp) |
| `SKIPPED::` | `is_valid = False`, never evaluated |

No fare value is embedded in the identifier.

## Duplicate audit report

`outputs/phase6_duplicate_audit_report.csv` carries one row per confirmed group: group id, group size, canonical observation, canonical timestamp, the duplicate observation ids, the maximum timestamp delta in minutes, `capture_signature_agreement`, the shared identity fields, and the duplicate reason. On the current dataset it contains exactly one row: `DUPGRP-OBS00769`, size 2, duplicate `OBS00770`, delta 1 minute, agreement `False`.

## Route directionality

Out of Phase 6 scope. `DEL-BOM` and `BOM-DEL` are treated as distinct and are never folded together. Noted for a later phase.

## Ground-truth reconciliation

Every category in `data/synthetic/edge_case_log.csv` (OBS00769–OBS00783) was individually verified against the actual engine output — see `tests/test_deduplication.py`, which uses these real rows as fixtures directly rather than only synthetic ones.

## Explicitly out of scope for Phase 6
Source consolidation, normalization, anomaly detection, index calculation, live scraping, Amadeus integration, API, dashboard. Phase 1, Phase 2 validation methodology, MoSPI reference data, DGCA raw source and processing, and Phase 5 / VAYU-Basket-Rule-v1 were not touched.
