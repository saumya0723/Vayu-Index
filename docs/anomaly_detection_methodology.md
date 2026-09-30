# VAYU INDEX - Phase 9 Anomaly Detection Methodology

Project: SIH26056 - Development of a Real-time Airfare Price Index for India
Stage: Phase 9 (Anomaly Detection)
Schema version: `phase9-v1`
Status: implemented, tested and verified against the Phase 8 outputs

---

## 1. Purpose and boundaries

Phase 9 **detects observations and aggregates that deserve human review**. It is
an annotation layer, not a cleaning layer.

Phase 9 explicitly does **not**:

- delete or silently drop any observation;
- impute, substitute or zero any price;
- correct, cap or replace a fare merely because the fare is high;
- decide index eligibility (`index_eligible` is **owned by Phase 10** and is
  deliberately absent from every Phase 9 output);
- aggregate to route level (route-aggregate anomalies are out of scope);
- change anything produced by Phases 1-8.

All four Phase 8 outputs are opened **read-only**. The verifier hashes them
before and after execution and fails if a single byte changes.

## 2. Inputs

| Input | Rows x cols | Role |
| --- | --- | --- |
| `outputs/normalized_airfare_observations.csv` | 393 x 51 | consolidation cells (primary price carrier) |
| `outputs/phase8_flight_cell_normalized.csv` | 571 x 42 | flight cells (source-level dispersion) |
| `outputs/normalized_observation_map.csv` | 778 x 49 | observations (structural checks, lineage) |
| `outputs/phase8_normalization_report.csv` | 777 x 7 | Phase 8 audit trail (context only) |

Phase 9 reuses Phase 8's canonical fields (`*_canonical`, `price_state`,
`round_sort_key`, `round_alignment`) instead of re-deriving them. No
normalization logic is duplicated.

## 3. Anomaly levels

1. `OBSERVATION` - a single source-level price record (R01, R02, R03, R04)
2. `FLIGHT_CELL` - one flight instance within a cell (R07, R08)
3. `CONSOLIDATION_CELL` - one economic product in one round (R09, R11, R12, R13)
4. `PRODUCT_SERIES` - one economic product across rounds (R05, R06, R10)

## 4. Outputs

| Output | Shape | Contents |
| --- | --- | --- |
| `outputs/anomaly_flagged_airfare_observations.csv` | 393 x 63 | every Phase 8 cell column plus 12 additive annotation columns |
| `outputs/phase9_anomaly_report.csv` | 1535 x 26 | one row per rule evaluation that is FLAGGED or NOT_EVALUABLE |
| `outputs/phase9_observation_anomaly_map.csv` | 778 x 20 | per-observation lineage and inherited severity |
| `outputs/phase9_series_diagnostics.csv` | 61 x 25 | per-product-series temporal diagnostics |
| `outputs/phase9_source_reliability_report.csv` | 4 x 13 | per-source diagnostic summary (no weights) |

### 4.1 Report grain ruling

The rule-level report is **normalized rather than wide**. It records only
`FLAGGED` and `NOT_EVALUABLE` evaluations; silent passes are omitted. A cell
that satisfies every rule generates no report rows at all, which keeps the
report an exception log rather than a 5,000-row cross-product.

`R04` is the one deliberate exception to per-entity grain: because it is
inactive for *every* observation for the *same* reason, it emits **one
framework row** with `entity_id = RULE_FRAMEWORK` instead of 777 identical
rows. The affected population is recorded in `comparison_basis`.

### 4.2 Annotation columns added to the primary output

`series_id`, `anomaly_rule_ids`, `anomaly_flag_count`, `anomaly_severity_max`,
`not_evaluable_rule_ids`, `market_movement_class`, `r13_peer_basis`,
`r13_modified_zscore`, `r13_scale_basis`, `recommended_review`, `retained`,
`phase9_schema_version`.

Every original Phase 8 column is carried through byte-identically. Phase 9
adds columns; it never rewrites one.

## 5. Rule contract (R01-R13, locked, never renumbered)

| Rule | Name | Level | Max severity | Behaviour on this corpus |
| --- | --- | --- | --- | --- |
| R01 | Nonpositive fare | observation | HIGH | 0 flags, 1 NOT_EVALUABLE |
| R02 | Nonnumeric fare | observation | HIGH | 0 flags, 1 NOT_EVALUABLE |
| R03 | Component mismatch (> INR 1) | observation | HIGH | 0 flags, 2 NOT_EVALUABLE |
| R04 | Plausible range | observation | HIGH | inactive by design, 1 framework row |
| R05 | Round-over-round movement | product series | HIGH | 1 flag (REVIEW), 180 NOT_EVALUABLE |
| R06 | Sustained drift | product series | HIGH | 0 flags, 237 NOT_EVALUABLE |
| R07 | Abnormal source dispersion | flight cell | REVIEW | 0 flags, 364 NOT_EVALUABLE |
| R08 | Source-level deviation | flight cell | REVIEW | 0 flags, 571 NOT_EVALUABLE |
| R09 | Thin source coverage | consolidation cell | INFO | 161 flags |
| R10 | Insufficient history | product series | INFO | 4 flags |
| R11 | No-price cell | consolidation cell | INFO | 1 flag |
| R12 | Unaligned round context | consolidation cell | INFO | 8 flags |
| R13 | Robust peer outlier | consolidation cell | HIGH | 2 flags, 1 NOT_EVALUABLE |

### R01 / R02 / R03 - structural rules

Structural violations are HIGH and are **immune to contextual downgrade**. A
nonpositive fare stays HIGH even when four sources agree. R03 reuses Phase 2's
established **INR 1.00** tolerance and compares `total_fare` against
`base_fare + taxes + fees`. When any component is missing the rule returns
`NOT_EVALUABLE / NO_DECOMPOSITION`; **no component is ever reconstructed** to
force the arithmetic to balance.

On the real corpus R01-R03 never fire, because the only negative-fare record
(`OBS00775`) was already rejected upstream with `is_valid=False` and therefore
never reaches Phase 9. These rules are proven by engineered unit-test fixtures
instead, and remain as defensive guards for richer future data.

### R04 - plausible range (inactive by design)

R04 exists in the framework but is permanently `NOT_EVALUABLE` with reason
`NO_FROZEN_CALIBRATION_SNAPSHOT`. Deriving plausible-range bounds from the same
observations being screened would be circular, so **no calibration distribution
is inferred from the live target data**. R04 activates only when an
independently designated, separately frozen calibration snapshot exists.

### R05 / R06 - temporal rules

Both are strictly **backward-looking**: an evaluation at round *n* uses only
rounds *1..n-1*. No future information leaks in, and appending a later round
never changes an earlier verdict (test-enforced).

- R05 requires at least **3 prior priced rounds**; `> 15%` is REVIEW and
  `> 30%` is HIGH.
- R06 requires at least **4 prior points**, **3 consecutive same-sign deltas**
  and cumulative absolute change `> 15%`.

History contains **anchored, priced rounds only**. Unaligned singleton rounds
are excluded from temporal calculation so a stray off-schedule capture cannot
manufacture a fictitious price movement, but they are never discarded: R12
records their context and R13 still evaluates them cross-sectionally.

Ordering uses `round_sort_key`, never the raw round id. This matters: `-` is
`0x2D` and `:` is `0x3A`, so every `ROUND-UNALIGNED::` id sorts lexically
*before* every `ROUND::` id regardless of the actual instant.

### R07 / R08 - source rules

R07 uses **relative** spread `(max - min) / min`, not absolute rupee spread, so
an INR 1,500 gap on an expensive flight and an INR 200 gap on a cheap one are
judged on the same scale. Threshold `> 15%`.

R08 requires **at least 3 priced sources**; with fewer it returns
`NOT_EVALUABLE / INSUFFICIENT_SOURCE_COUNT_FOR_ATTRIBUTION`. A two-source
disagreement is symmetric and cannot identify which source is deviant, so it is
never presented as attribution. On the current corpus `flight_source_count` is
`{0: 1, 1: 363, 2: 207}` - **no flight cell has 3 sources**, so R08 is
structurally unevaluable everywhere. It is retained, not removed or renumbered,
as a defensive rule for richer future data.

### R09 / R10 / R11 / R12 - informational rules

Capped at INFO and never sufficient on their own to set
`recommended_review`. Thin coverage is a **coverage** fact, not an economic
anomaly. R11 retains no-price cells with no imputation and no zero price. R10
reports short history without manufacturing any.

### R13 - robust peer outlier

Peer group is `(origin, destination, fare_class)` **within the same collection
round**. If fewer than 5 priced peers are available the comparison widens to the
same `(origin, destination, fare_class)` across all rounds, and the basis is
recorded explicitly as `WITHIN_ROUND` or `WIDENED_ALL_ROUNDS`.

Modified z-score: `z = 0.6745 * (x - median) / MAD`, threshold `|z| > 3.5`
(REVIEW) and `|z| > 7.0` (HIGH). The peer population **includes the point being
tested**, which is the standard construction and keeps the median stable in
small groups.

When `MAD == 0` the scale collapses and the **IQR fallback** engages
(`scale = IQR / 1.349`), recorded as `r13_scale_basis = IQR_FALLBACK`. When both
MAD and IQR are zero the result is `NOT_EVALUABLE / ZERO_DISPERSION` rather than
a division by zero or a fabricated score.

**A widened result is weaker evidence than a within-round result and is capped
at REVIEW**, however extreme the z-score. On this corpus that cap is load
bearing: the largest outlier scores `z = +7.29` (fare INR 14,050 against a peer
median of INR 5,755, n = 40) and is deliberately held at REVIEW rather than HIGH
because its basis is `WIDENED_ALL_ROUNDS`.

Peer basis distribution: 105 `WITHIN_ROUND`, 287 `WIDENED_ALL_ROUNDS`, 1 not
applicable (the no-price cell).

## 6. Unaligned round handling

Unaligned rounds are excluded from **temporal** rules (R05, R06) only. They are
fully evaluated by **cross-sectional** R13, which is what keeps engineered edge
cases detectable. `OBS00776` is the worked example: it sits in an unaligned
round, is flagged `R09;R12;R13` at REVIEW severity with `recommended_review =
True` and `retained = True`, and is never dropped.

## 7. Dynamic pricing protection

A sharp price move is not by itself suspicious. Each cell is classified as:

- `COHERENT_MARKET_MOVEMENT` - corroborated by at least 2 sources or at least 2
  flight instances;
- `ISOLATED_DEVIATION` - single source and single flight;
- `INDETERMINATE` - insufficient context.

Coherent movements are **downgraded one severity step**. The adjustment can
only ever lower severity - it can never escalate (test-enforced and
verifier-enforced) - and it never removes the flag, which stays in the report
with both `severity_before_context` and the final `severity` recorded. Isolated
deviations retain full severity. Structural rules R01-R03 are exempt entirely.

Both directions are observable in the real run: one R13 result moved
REVIEW -> INFO on coherence, and one moved HIGH -> REVIEW on the widened-basis
cap.

## 8. Threshold calibration honesty

**The 15% / 30% family (R05, R06, R07) are PROTOTYPE_CALIBRATION values. They
are not official MoSPI thresholds and must not be presented as universal
statistical truths.**

- Calibration source: VAYU synthetic screening corpus (783 raw / 778 canonical)
- Calibration date: 2026-09-10
- **In-sample caveat: these thresholds were informed by the same synthetic
  corpus they are used to screen.** Observed maxima are 19.01% round-over-round,
  10.99% cumulative drift and 12.26% source dispersion, so the 15% line sits
  just above the observed distribution by construction.

R06 and R07 producing zero flags is an **expected and acceptable** result on a
corpus this small, not a defect.

R13's `3.5` / `7.0` modified-z thresholds are standard robust-statistics
conventions (`ROBUST_STATISTIC`), not corpus-fitted. R03's INR 1 tolerance is
inherited from Phase 2 (`INHERITED_PHASE2`). R04 has no calibration at all
(`ABSENT`).

## 9. Determinism

- No randomness, no RNG seeding, no machine learning. Isolation Forest is
  deferred completely from the MVP.
- All monetary arithmetic uses `Decimal`; the binary `float` constructor is
  banned from the Phase 9 source and the ban is test-enforced.
- Output ordering is explicit: the report sorts by
  `(rule_id, anomaly_level, entity_id, evaluation_status)`.
- Results are **input-order independent**: reversing the input row order
  reproduces a byte-identical report.
- Re-running the engine on unchanged inputs reproduces identical outputs.
- Pandas rows are always accessed as `row["column"]`, never `row.column`, which
  is enforced by a regex guard in the test suite. Attribute access silently
  resolves names such as `prod`, `min`, `max`, `count` and `size` to DataFrame
  methods; that exact bug produced 384 phantom single-point series during
  methodology projection and is now permanently guarded against.

## 10. Option B

`alt_source_first_fare` is **diagnostic only**. The anomaly engine never reads
it; every price decision uses `consolidated_fare_normalized`. This is enforced
by a test asserting the column is never dereferenced in the engine source.

## 11. Verification

- `tests/test_anomaly_detection.py` - 116 tests, all R01-R13 plus all 17
  required engineered edge cases.
- `scripts/verify_phase9.py` - 123 independent checks across 15 sections,
  including upstream SHA-256 integrity, retention, scope boundaries, the rule
  contract, lineage resolution, and determinism.
- Upstream regression: Phase 6 verifier 27/0, Phase 7 verifier 57/0, Phase 8
  verifier 127/0, and 22 locked upstream SHA-256 hashes all `OK`.

## 12. Out of scope for Phase 9

Index eligibility, index calculation, source weighting, route aggregation,
route-direction resolution, basket changes, live scraping / Amadeus / API
integration, and dashboards. The route-direction mismatch between the observed
records and the locked Phase 5 basket is **knowingly left unresolved** here; it
becomes blocking at Phase 10.
