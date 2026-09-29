# VAYU INDEX - Phase 11 Index Methodology

This document describes the Phase 11 index construction method exactly as it
is implemented in `src/index_engine/`. It is a prototype methodology built on
a synthetic corpus. Nothing in this document should be read as an official
statistical release.

---

## 1. Method name

The Phase 11 headline series is a **chained, traffic-weighted Jevons index**
with a two-stage aggregation hierarchy:

1. **Elementary stage (per route, unweighted):** the geometric mean (Jevons)
   of matched adjacent price relatives for all elementary items on that route.
2. **Upper stage (across routes, weighted):** the weighted Jevons of the route
   elementary indices, where the weights are the locked Phase 5 route traffic
   weights, renormalized over contributing routes for that link only.

Weights are applied to the **logarithms of price relatives**, never to raw
price levels. The fare value itself is never used as a weight.

---

## 2. Elementary item definition (D1)

An elementary item is the 4-tuple:

```
(route_id, fare_class, advance_purchase_window, travel_date)
```

`route_id` is the undirected canonical Phase 10 route identifier. Fare classes
are never substituted for one another, advance purchase windows are never
substituted for one another, and `travel_date` is never collapsed.

### Maturity-ramp limitation (explicit, not resolved)

Because `travel_date` is fixed inside item identity while collection rounds
move forward in time, the days-to-departure of a given item **shrinks** as the
chain advances. A price relative for a fixed `travel_date` therefore mixes two
effects:

- genuine airfare movement, and
- movement along the airline's advance-purchase pricing ramp (maturity ramp).

This index does **not** correct for that. It has **not** been switched to a
constant-maturity design. The `advance_purchase_window` bucket limits but does
not eliminate the effect, because a window such as `T15(12-18)` still spans
several days of ramp. Any interpretation of short-run movements in this index
must account for this maturity-ramp limitation. Resolving it is deliberately
out of Phase 11 scope.

---

## 3. Matched price relatives and chaining (D2, D3)

For each adjacent pair of anchored collection rounds `t-1` and `t`, an item is
**MATCHED** only when it has an eligible priced observation in *both* rounds.
Matched items produce a price relative:

```
r_i,t = p_i,t / p_i,t-1
```

Items priced only in the current round are **ENTERING**; items priced only in
the previous round are **LEAVING**. Entering and leaving items are published
with their reason, carry no price relative, and never enter a chain factor.

Chained levels use:

```
I_t = I_(t-1) x J_t
```

The base level is exactly `100.000000` at the first anchored round.

### Anchored-only chaining

Only rounds whose alignment is `ANCHORED` are chain links. The prototype
anchor configuration is `09:00`, `14:30`, `20:15` (+/- 30 minutes), status
`PROTOTYPE_CALIBRATION`, not an official collection schedule.

The current corpus contains **16 collection rounds: 9 anchored and
7 unaligned**. The **7 unaligned** rounds are published in
`outputs/phase11_unaligned_round_diagnostics.csv` with their nearest anchored
round and minute distance, and every one of them carries
`chain_eligible = False`. They are diagnostics only and are never chain links.

The published primary chain therefore has 9 rounds and 8 links.

---

## 4. Weights and renormalization (D4)

Weights are the locked Phase 5 route traffic weights
(`data/official/dgca/processed/vayu_route_basket_2024_25.csv`), which sum to
`1.000000` across the 15 basket routes. For each link:

```
w_tilde_r,t = w_r / sum(w over routes contributing to that link)
```

Renormalization is **per link**. Missing route weight is never silently
redistributed as a bonus to observed routes: it is disclosed. Both of the
following are published on every round:

- `basket_weight_represented` - the **unnormalized** represented weight
- `effective_weight_sum` - `1.000000` after per-link renormalization

No source weights, expenditure weights, or quantity weights exist anywhere in
Phase 11. Within a route, matched items are equally weighted.

---

## 5. Coverage disclosure (D5)

There is **no automatic coverage threshold** and **no automatic suppression**.
A round with thin coverage is published with its coverage stated, never
hidden. Every round discloses seven fields:

| Field | Current value |
| --- | --- |
| `basket_routes_represented` | 2 |
| `basket_routes_total` | 15 |
| `basket_weight_represented` | 0.273706 |
| `basket_coverage_pct` | 27.3706 |
| `effective_weight_sum` | 1.000000 |
| `renormalization_applied` | True |
| `coverage_status` | PARTIAL_COVERAGE_PROTOTYPE |

### Current coverage, stated plainly

- Only **2 of 15** basket routes are observed: `BOM-DEL` and `BLR-DEL`.
- Those two routes carry **27.3706%** of the locked basket weight.
- The remaining 13 basket routes have **zero** observations. They are listed
  in every round of `phase11_index_coverage_report.csv` with
  `NO_OBSERVATIONS`. They are never dropped, never imputed, and never
  assigned a zero fare.
- The headline index movement is therefore driven by 27.3706% of the intended
  basket weight, renormalized to 1. **This is not a national airfare index.**
  It is labelled `PARTIAL_COVERAGE_PROTOTYPE` for exactly this reason.

---

## 6. Inclusion rules and series variants (D6, D11)

**PRIMARY (`VAYU-RI-PRIMARY`, rule `P11-INCL-01`)** includes every retained
Phase 10 item whose `route_price_state` is `PRICED` and whose median fare is
parsable and strictly positive, **regardless of Phase 9 anomaly severity**.
A genuine airfare surge is a price signal, not an error, so `REVIEW` and
`HIGH` severity items remain in the headline series.

Only structurally invalid inputs are excluded: non-PRICED, missing,
unparsable, non-positive, or contract-violating values. Each exclusion is
published with an `index_eligibility_status` value such as
`INELIGIBLE_NOT_PRICED` or `INELIGIBLE_NON_POSITIVE_FARE`.

**EXCL_REVIEW_HIGH (`VAYU-RI-EXCL-REVIEW-HIGH`, rule `P11-INCL-02`)** is a
**diagnostic sensitivity series only**, which additionally drops `REVIEW` and
`HIGH` severity items. It is never the headline series.

### Honest disclosure about the sensitivity series

In the current corpus the sensitivity series is **numerically identical** to
PRIMARY. The corpus contains exactly one `REVIEW` severity row, and it belongs
to an unaligned round (`2026-09-05 23:59`) that is not a chain link. Across
the 9 anchored rounds the severity distribution is `NONE: 142, INFO: 69`, with
zero `REVIEW` and zero `HIGH`. The sensitivity series is fully wired and will
diverge when anchored REVIEW/HIGH items appear, but **it currently excludes
nothing**. It should not be presented as evidence that the headline series is
robust to anomaly exclusion.

### Field vocabulary

Only `index_eligibility_status` and `index_inclusion_rule_id` are published.
No boolean eligibility flag is produced in any Phase 11 output; eligibility is
always a named status plus a named rule id, so the reason is auditable.

---

## 7. Period derivation (D7)

The **round-level chained index is authoritative**. Daily, weekly and monthly
figures are **derived** from it (`derivation_rule =
DERIVED_FROM_ROUND_LEVEL_CHAIN`); they are never recomputed from raw fares.

- Primary period value: **period-end chain level**
  (`PERIOD_END_CHAIN_LEVEL`).
- Secondary diagnostic: **period-average index level**
  (`PERIOD_AVERAGE_INDEX_LEVEL`), published with
  `period_average_is_chain_consistent = False`. An arithmetic mean of chained
  levels is not itself a chain-consistent index value and must not be chained
  onward.

Periods that do not contain the full expected number of anchored rounds are
flagged `period_is_partial = True`. In the current corpus the weekly and
monthly periods are partial (6 of 21 and 9 of 90 expected rounds).

---

## 8. Precision and rebasing (D8)

- Internal arithmetic: `Decimal`, precision 28, `ROUND_HALF_UP`.
- `index_level`: 6 decimal places. Base level `100.000000`.
- `chain_factor`: 8 decimal places.
- Fares are preserved at 2 decimal places.
- No binary floating point is used anywhere in the engine.

Rebasing divides **unrounded internal levels** by the unrounded level of the
new base round, so adjacent price relatives are preserved exactly. Rebasing
never re-reads Phase 10 and never operates on published rounded values.

---

## 9. Scope boundaries (D9, D10)

- Only the locked 15-route Phase 5 basket contributes to the headline index.
- Off-basket routes `BLR-HYD` and `CCU-MAA` are observed in Phase 10 but stay
  **outside** the headline index entirely.
- Grain B (route x fare class x round) is diagnostics and reconciliation only
  and is never an index input. Phase 11 reads only the Grain A route series,
  the Phase 10 coverage report, and the locked basket.
- Phase 11 reads Phase 10 outputs **read-only** and does not re-aggregate
  routes. Route aggregation stays in Phase 10.

---

## 10. Determinism

- No machine learning, no randomness, no seeds.
- No imputation, no carry-forward, no interpolation, no zero substitution.
- Output row order is fully determined by identity keys (series variant, link
  sequence, numeric basket rank, then item identity), so the engine is
  independent of input row order.
- Re-running the engine reproduces byte-identical outputs.

---

## 11. Data status and limitations (summary)

These limitations are material and are stated without hedging:

1. **Synthetic data.** The underlying airfare corpus is synthetic prototype
   data, not a live or official airfare feed.
2. **Partial coverage.** 2 of 15 basket routes observed; 27.3706% of basket
   weight represented; status `PARTIAL_COVERAGE_PROTOTYPE`.
3. **Maturity ramp.** Price relatives are not maturity-controlled; movements
   mix genuine price change with advance-purchase ramp effects.
4. **Short series.** 9 anchored rounds over 3 calendar days produce 8 links.
5. **Unaligned rounds.** 7 unaligned rounds are diagnostics only.
6. **Sensitivity series is currently non-binding.** `EXCL_REVIEW_HIGH`
   excludes nothing in this corpus.
7. **Weight provenance.** The Phase 5 traffic basket is derived from
   conservative bidirectional DGCA traffic figures. It is
   **not endorsed by MoSPI**, it is not an official MoSPI or CPI route
   weighting, and it is not endorsed by DGCA. No official endorsement of this
   basket exists.
8. **Prototype status.** This is a prototype index for SIH26056 development
   work. It is not an official statistic and must not be published as one.

---

## 12. Outputs

| File | Contents |
| --- | --- |
| `phase11_round_index.csv` | Authoritative round-level chained index per variant |
| `phase11_route_index_components.csv` | Per-route elementary Jevons, weights, log contributions |
| `phase11_item_price_relatives.csv` | Item-level matched/entering/leaving relatives |
| `phase11_period_index.csv` | Derived daily/weekly/monthly values |
| `phase11_index_coverage_report.csv` | Per-round, per-basket-route coverage disclosure |
| `phase11_index_lineage_map.csv` | Item-level lineage back to Phase 10 fares and observation ids |
| `phase11_unaligned_round_diagnostics.csv` | The 7 unaligned rounds, never chained |

Every output carries `phase11_schema_version`.
