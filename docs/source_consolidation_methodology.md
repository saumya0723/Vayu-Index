# VAYU INDEX — Phase 7: Source Consolidation Methodology

**Status:** Approved and implemented (2026-09-10)
**Scope:** Consolidate multiple observation sources into one representative quote per economic product per collection round.
**Input:** `outputs/canonical_airfare_observations.csv` (778 canonical Phase 6 observations, 29 columns)
**Outputs:** `outputs/consolidated_airfare_observations.csv`, `outputs/phase7_flight_cell_report.csv`, `outputs/phase7_observation_map.csv`

---

## 1. Purpose

Airline sites and OTAs are **multiple observation sources for the same economic product**, not different products. Phase 6 removed technical duplicates *within* a source. Phase 7 resolves the remaining multiplicity *across* sources, producing exactly one representative fare per economic product per collection round.

Phase 7 does **not** perform normalization, anomaly detection, route aggregation, index calculation, scraping, Amadeus integration, API or dashboard work. It does not resolve route directionality and does not touch the locked Phase 5 basket.

Invented market-share weighting was explicitly rejected: no defensible public source assigns booking share to AirlineSite / Cleartrip / Goibibo / MMT, and an invented weight would be indefensible in an official statistical product.

---

## 2. Primary estimator (locked)

> **Phase 7 primary estimator = flight-first, two-stage median: cross-source median within each flight cell, followed by median across flight-level representative fares within each economic product and collection round.**

This is a **median-based source-consolidation method with a flight-first aggregation hierarchy**. It must **not** be described as equal-weighting of sources.

### Why flight-first

- Sources frequently expose **different flight sets**. Measured on the real canonical data: of 232 multi-source cells, **151 (65.1%)** have sources covering different flight sets.
- Source-first aggregation converts those **flight-coverage differences into artificial source-price differences**: a source that happens to list only the cheap early-morning departure looks "cheaper" when it is merely differently stocked.
- Flight-first confines source comparison to **like-for-like observations of the same flight**, and guarantees each flight contributes **exactly one value** at Stage 2, which structurally prevents flight double-counting.
- No market-share weights are invented anywhere in the method.

### Honest limitation — residual coverage asymmetry

Flight-first does **not** completely remove source-coverage bias. A source that **uniquely exposes a flight still fully determines that flight's representative value** and therefore still influences the Stage 2 result. On the real data, 363 of 571 flight cells (63.6%) are single-source.

This residual is **accepted deliberately and disclosed**, not weighted away. The alternatives were rejected:
- discarding unmatched flights would throw away ~64% of flight cells and bias toward flights that happen to be widely listed;
- imputing prices for absent sources would fabricate data.

Coverage is therefore reported on every row (`participating_source_count`, `participating_sources`, `missing_sources`, `source_coverage`, `source_coverage_ratio`) so downstream phases can filter or stratify on it.

---

## 3. Consolidation cell

One output row per:

```
origin + destination + travel_date + fare_class + advance_purchase_window + collection_round_id
```

- **Route direction is preserved exactly as stored.** `DEL-BOM` is never folded into `BOM-DEL`. No route IDs are created or altered. The Phase 5 basket is untouched.
- **Fare classes are never combined.** Saver + Standard, Saver + Flexi and Economy + Premium Economy are distinct products.
- **Advance-purchase windows are separate strata.** `advance_purchase_days` is metadata only and is never a key.
- **Travel dates are separate.**
- **`source` is deliberately not part of the key** — it is the dimension being consolidated, and is preserved as diagnostics.

### Flight cell

```
consolidation cell + carrier + flight_number + normalized departure_time
```

This is Phase 6's product-instance identity, reused unchanged. Departure time is normalized **for comparison only** using the Phase 6 normalizer (`8:10` and `08:10` are the same flight); the stored raw value is never rewritten.

---

## 4. Collection rounds

### Prototype anchors

```
09:00   14:30   20:15      tolerance ±30 minutes
```

> These clock anchors are **prototype configuration derived from the current synthetic collection schedule, not a finalized production sampling schedule.** The production scraping cadence may later replace these configuration values without changing the Phase 7 methodology.

Evidence: 768 of the 778 canonical observations land exactly on these three clock times across 2026-09-05/06/07, producing nine scheduled rounds in which all four sources are present at the identical minute.

### Assignment rule

1. Parse `collection_timestamp` as a **naive local datetime**, exactly as represented in the input. No timezone is inferred, assigned, converted or fabricated (inherited Phase 6 rule).
2. Compare against each anchor **on the observation's own calendar date**; pick the nearest. Exact ties (impossible at this tolerance) resolve to the earlier anchor.
3. Distance **≤ 30 minutes inclusive** → `ROUND::<date>T<anchor>`, alignment `ANCHORED`. 31 minutes is outside.
4. Distance **> 30 minutes** → `ROUND-UNALIGNED::<timestamp>`, alignment `UNALIGNED`: its own singleton round. Never merged, never dropped.
5. **Missing or unparseable timestamp** → `ROUND-UNRESOLVED::<observation_id>`, alignment `UNRESOLVED`: excluded from cross-source consolidation, but **retained in the observation map** with participation status `EXCLUDED_NO_ROUND`.

### Why 30 minutes, and why it is not 15

| | Phase 6 | Phase 7 |
|---|---|---|
| Constant | `TIME_TOLERANCE_MINUTES = 15` | `ROUND_TOLERANCE_MINUTES = 30` |
| Question | Are these the *same capture* of the same flight by the same source at the same fare? | Were captures by *different sources* close enough to reflect the same market state? |
| Concept | Record identity | Economic comparability |

These are different questions and deliberately carry **different numbers in separate constants**. Phase 7 never imports Phase 6's tolerance; a test asserts the two remain independent.

30 minutes is defensible because:
1. It cannot merge two rounds — the minimum anchor gap is 330 minutes, so the collision threshold is 165 minutes; 30 is 5.5× below it, making nearest-anchor assignment provably unique.
2. It covers a realistic multi-source crawl sweep.
3. It is empirically calibrated: it absorbs the two near-anchor stragglers (09:20 = +20 min, 20:00 = −15 min) while correctly leaving the genuinely distant captures (10:32–10:44, 18:47, 23:59) unaligned.

---

## 5. The three stages

### Stage 0 — within-source, within-flight representative value

If multiple surviving observations from the **same source** and **same flight** fall in the **same round**, collapse them to one value using the midpoint median. This is **defensive** (Phase 6 leaves no such rows in the current data) and exists to prevent a source from receiving multiple votes for one flight.

### Stage 1 — cross-source median within a flight cell

```
flight_representative_fare = midpoint_median(stage-0 value per participating source)
```

This is the **only** place sources are compared, and the comparison is strictly like-for-like.

### Stage 2 — median across flight-level representative fares

```
consolidated_fare = midpoint_median(flight_representative_fare across flights in the cell)
```

Each flight contributes exactly one value regardless of how many sources listed it.

### Worked example

| Source | Flight A | Flight B | Flight C | Flight D |
|---|---|---|---|---|
| AirlineSite | 5000 | 5100 | 5200 | 5300 |
| MMT | 6000 | — | — | — |

- Stage 1: A → midpoint(5000, 6000) = **5500**; B → 5100; C → 5200; D → 5300
- Stage 2: midpoint median of [5100, 5200, 5300, 5500] = (5200+5300)/2 = **5250.00**
- Pooled single median would have given 5200; source-first (Option B) would have given 5575.

The 4-flight source does **not** outvote the 1-flight source, and the 1-flight source does **not** get half the weight of a 4-flight source. Each *flight* counts once.

---

## 6. Median definition (locked)

**Standard midpoint median.** For an even number of values:

```
median = (lower_middle + upper_middle) / 2
```

- `[5300, 5500] → 5400`
- `[5000, 5200, 5600, 6000] → 5400`

A lower-median rule was rejected: it would systematically select the lower middle value and introduce a downward tendency. `consolidated_fare` is a **derived statistic**, not a claim that a source actually quoted that amount, so a midpoint such as ₹5,425 or ₹11,041.75 is acceptable.

- **`Decimal` is used throughout the monetary calculation path.** No float ever touches a fare.
- Derived results are retained to **2 decimal places** (`ROUND_HALF_UP`).
- **`consolidated_fare_is_observed_value`** is emitted on every priced row so it is transparent whether the final fare was actually observed (`True`) or is a derived midpoint (`False`).

---

## 7. Missing sources, sold-out and missing prices

| Situation | Rule |
|---|---|
| One source present | Consolidation proceeds; labelled `SINGLE_SOURCE`. Never imputed, never zero. |
| Two or three sources | `PARTIAL_COVERAGE`; absent sources listed in `missing_sources`. |
| All four sources | `FULL_COVERAGE`. |
| No priced source | `NO_PRICED_SOURCE`, no fare emitted. |
| Sold out | Excluded from the price median, **retained** in the cell and map, counted in `sold_out_observation_count`, status `EXCLUDED_SOLD_OUT`. |
| Every observation sold out | No consolidated fare; status **`NO_PRICE_ALL_SOLD_OUT`**. |
| Missing `total_fare` | Excluded from price aggregation, retained and counted; status `EXCLUDED_MISSING_PRICE`. |
| Missing source label | No cell membership; status `EXCLUDED_MISSING_SOURCE`; retained in the map. |
| Missing core identity | No cell membership; status `EXCLUDED_MISSING_IDENTITY`; retained in the map. |

A missing price is **never** treated as zero, and an absent source is **never** imputed. Partial fare decomposition (missing `base_fare`/`taxes`/`fees` while `total_fare` is present) is irrelevant here — Phase 7 only consumes `total_fare`.

---

## 8. High prices and dispersion

- **High prices are retained and participate.** A high airfare can be legitimate. **Phase 7 performs no anomaly detection**; that is a separate later stage with its own approval.
- **No observation is ever dropped or altered because of dispersion.** Dispersion is *measured and reported* only, with **no thresholds and no flags**.
- Dispersion is measured at **flight level** (`flight_source_spread`, `flight_source_relative_spread`) because that is the only place the compared values describe the same flight.
- Cell rollups: `max_flight_source_spread`, `median_flight_source_spread`, and — deliberately named separately — `cross_flight_spread`, which measures variation *across flights* (time-of-day and carrier mix), a genuinely different quantity that must not be mistaken for source disagreement.

---

## 9. Auditability

`outputs/phase7_observation_map.csv` retains **all 778 canonical observations**, each with an explicit `participation_status`. Nothing is physically deleted.

Full lineage chain:

```
raw observation (Phase 1/2)
  → canonical observation (Phase 6)
    → source + product identity + collection round
      → flight_cell_id → flight_representative_fare
        → consolidation_cell_id → consolidated_fare
```

The consolidated dataset is fully reproducible from the canonical Phase 6 dataset by running `scripts/run_consolidation.py`.

---

## 10. Determinism

- Input rows are sorted by `observation_id` before processing; every group is materialised through an explicit sort.
- Output ordering: consolidated by `consolidation_cell_id`, flight report by `flight_cell_id`, observation map by `observation_id`.
- List-valued fields are sorted and `;`-joined; source-level fares render as `AirlineSite=5400.00;Cleartrip=5500.00`.
- All monetary arithmetic runs in `Decimal`.
- Result: byte-stable outputs, identical across reruns and across shuffled or reversed input order.

---

## 11. Downstream compatibility (Phase 8 and later)

Phase 8 (Normalization) consumes `outputs/consolidated_airfare_observations.csv` and needs at minimum:
`origin`, `destination`, `travel_date`, `fare_class`, `advance_purchase_window`, `collection_round_id`, `round_anchor_timestamp`, `consolidated_fare`, `consolidation_status`, `source_coverage`.

Deliberately left for later phases: normalization, anomaly detection (which will want `min/max_participating_fare` and the dispersion columns), route aggregation and weighting (which will want route direction resolved first), and index calculation.

Open item carried forward, **not** resolved here: the canonical routes (`DEL-BOM`, `DEL-BLR`, `MAA-CCU`, `BLR-HYD`) do not match the locked Phase 5 basket as stored — `BOM-DEL` and `BLR-DEL` are in the basket in the reverse direction, and `MAA-CCU`/`BLR-HYD` are absent in either direction. This is **reported only**; route directionality requires its own explicit decision.

---

## 12. Files

| File | Role |
|---|---|
| `src/consolidation/rules.py` | Identity keys, round assignment, midpoint median, vocabularies, prototype config |
| `src/consolidation/consolidation_engine.py` | Stage 0/1/2 pipeline, dispersion, output rendering |
| `src/consolidation/__init__.py` | Public surface |
| `scripts/run_consolidation.py` | CLI |
| `scripts/verify_phase7.py` | Independent acceptance checks against the outputs on disk |
| `tests/test_consolidation.py` | Full approved test plan |
| `tests/fixtures/phase7_synthetic.csv` | Synthetic edge-case fixture |
| `docs/source_consolidation_methodology.md` | This document |
