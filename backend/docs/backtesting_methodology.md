# VAYU INDEX — Phase 12 Backtesting Methodology

**Project:** SIH26056 — Development of a Real-time Airfare Price Index for India  
**Schema:** `phase12-v1`  
**Status:** locked implementation methodology

## 1. Boundary and current result

Phase 12 reads Phase 11 and official-reference artefacts read-only. It never rewrites Phases 1–11, the locked Phase 5 basket, MoSPI processed data, or DGCA processed data. The current airfare corpus is synthetic and covers only three collection days (5–7 September 2026), nine anchored rounds, and two of the fifteen locked routes. It cannot satisfy a real 30-day empirical backtest.

The authoritative empirical result is:

- VAYU complete monthly periods: **0**
- MoSPI monthly periods: **19** (January 2025–July 2026)
- exact complete-month overlap: **0**
- backtest status: `PROTOTYPE_BACKTEST`
- comparison status: `NO_OVERLAPPING_COMPLETE_PERIODS`
- all external metrics: `INSUFFICIENT_SAMPLE`
- production status: `PRODUCTION_BACKTEST_REQUIRED`

The September 2026 VAYU month has 9 of 90 expected anchored rounds and is `PARTIAL_MONTH_EXCLUDED_FROM_REFERENCE_COMPARISON`. It remains in coverage and lineage outputs.

## 2. References

MoSPI domestic airfare CPI (`07.3.3.1.2.01`) is the only external price reference. It is monthly, All India, Combined, base year 2024. DGCA city-pair passenger traffic is not a fare or price index; it is used only for the locked basket, traffic weights, and coverage context. Phase 12 emits `INVALID_REFERENCE_TYPE_TRAFFIC_NOT_PRICE` for any attempt to use DGCA traffic as an external price target.

## 3. Population separation

1. `ENGINE_PIPELINE_BACKTEST`: deterministic fixtures with known answers validate formulas and controls.
2. `PROTOTYPE_BACKTEST`: genuine current overlap only. There is no complete-month overlap now.
3. `PRODUCTION_BACKTEST_REQUIRED`: future assessment using sufficiently long real collected airfare data.

Fixture success is not real-world validation.

## 4. Frequency and alignment

VAYU may only be aggregated upward: round → day → week → month. MoSPI is never disaggregated. Matching is exact `YYYY-MM` only and requires a complete VAYU month. There is no interpolation, forward fill, backward fill, carry-forward, nearest-neighbour matching, or date tolerance. A partial month never becomes a comparison observation.

The Phase 11 period-end chained level is the primary monthly VAYU measure. The period-average level is diagnostic only and retains `period_average_is_chain_consistent = False`.

## 5. Rebasing and comparison measures

For an eligible overlap, both original series are preserved and comparison-only levels are rebased to 100 at the first complete overlapping month using unrounded values. Rebasing never alters adjacent growth rates.

Primary comparison: paired month-over-month percentage changes. Secondary diagnostics: positive rebased levels, directional agreement, YoY changes when sufficient history exists, turning points, peak/trough timing, and volatility. MAPE is allowed only on positive rebased levels and never on changes.

Zero-direction rule: zero agrees only with zero. Missing values remain missing.

## 6. Minimum samples

| Measure | Minimum |
|---|---:|
| Descriptive level difference | 1 paired level |
| MAE / RMSE / mean bias | 6 paired changes |
| MAPE | 6 positive paired levels |
| Directional agreement | 6 paired changes |
| Pearson correlation | 12 paired changes plus nonzero variance and at least 3 distinct values per series |
| Spearman correlation | 12 paired changes plus at least 3 distinct ranks per series |
| Change standard deviation | 12 paired changes |
| Volatility ratio | 12 paired changes and nonzero reference SD |
| Turning points | 12 paired changes |
| Peak/trough timing | 12 paired levels |
| Lead/lag | 18 pairs after lagging |

Insufficient metrics have blank values, explicit available and required counts, and `INSUFFICIENT_SAMPLE`. There are no p-values, confidence intervals, or statistical significance tests in the prototype.

## 7. Coverage sensitivities

All coverage sensitivities are `DIAGNOSTIC_NOT_HEADLINE` and never replace Phase 11.

- `SENS-COV-01`: locked PRIMARY chain.
- `SENS-COV-02`: equal-route diagnostic using contributing Phase 11 route elementary Jevons factors.
- `SENS-COV-03`: observed-coverage log contribution, $\sum w_r\log(J_r)$, using original locked basket-weight mass. It is not a full-basket index.
- `SENS-COV-04`: exclusion below 80% represented basket weight.

Current basket coverage is two observed routes, thirteen unobserved routes, 27.3706% represented weight, and 72.6294% missing weight. Missing routes are never imputed and no counterfactual full-basket index is created.

## 8. Anomaly sensitivity

`PRIMARY` is compared with `EXCL_REVIEW_HIGH`. The two current anchored chains are identical. This is a corpus artefact: the only REVIEW record belongs to an unaligned round that never enters the chain. Equality is not evidence of general anomaly robustness.

## 9. Lead/lag

Current status is `NOT_APPLICABLE_NO_OVERLAP`. Future diagnostics are limited a priori to lags `{-1, 0, +1}` month and require 18 paired observations after lagging. Phase 12 never searches arbitrary lags or chooses a best lag after seeing results.

## 10. Production gate

A production backtest requires all of:

- at least 30 consecutive collection days;
- at least 72 of 90 valid anchored rounds;
- at least 24 of 30 valid daily period-end observations;
- at least 12 of 15 locked routes;
- at least 80% locked basket weight;
- at least 30 matched elementary items per chain link;
- at least one matched item per contributing route;
- at least 10,000 valid observations;
- no more than two consecutive missing days;
- real collected airfare data.

Missing days and rounds are disclosed, not filled. A 30-day window alone does not create enough monthly MoSPI observations for meaningful monthly correlation.

## 11. Reference limitations

MoSPI CPI and VAYU scraped-fare indices can differ because of product definitions, samples, collection timing, basket composition, source coverage, fare-class composition, advance-purchase structure, missingness, index formulas, maturity-ramp effects, and real-versus-synthetic data. Disagreement is not automatically a model failure. DGCA traffic is never treated as airfare.

## 12. Determinism and lineage

The engine uses deterministic sorting, Decimal arithmetic for index and metric calculations, no machine learning, no RNG, no hidden filtering, and no upstream imports. Every metric—including blocked metrics—resolves to exact VAYU candidate rows, all unpaired MoSPI rows, source hashes, series and period keys, alignment, rebasing, metric, coverage, and inclusion/exclusion rules. Sensitivity rows resolve to Phase 11 route-component or round-index inputs.

Every output carries `phase12_schema_version`. Before and after execution, SHA-256 digests of protected Phase 1–11 outputs, the Phase 5 basket, and processed MoSPI and DGCA references are compared. Any change aborts the run.

## 13. Outputs

- `phase12_backtest_summary.csv`: overall prototype and production statuses.
- `phase12_period_comparison.csv`: union of candidate VAYU and MoSPI months, including exclusions.
- `phase12_metric_report.csv`: metric definitions, thresholds, blocked values, and statuses.
- `phase12_sensitivity_report.csv`: coverage and anomaly diagnostics.
- `phase12_coverage_report.csv`: all fifteen routes under every coverage policy and round.
- `phase12_reference_metadata.csv`: valid MoSPI price reference and rejected DGCA traffic target.
- `phase12_backtest_lineage.csv`: source-row and rule lineage, including blocked metrics.
- `phase12_thirty_day_gate.csv`: every locked production gate.
