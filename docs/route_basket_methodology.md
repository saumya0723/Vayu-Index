# VAYU Route Basket Methodology

**Financial year:** 2024-25  
**Selection method:** VAYU-Basket-Rule-v1  
**Generated:** 2026-09-29T18:03:54.561302+00:00

## Provenance

| Layer | Status |
|---|---|
| DGCA passenger counts, route ranks | Official DGCA 2024-25 data |
| VAYU-Basket-Rule-v1 (the selection rule) | VAYU design choice, not an official MoSPI/DGCA rule |
| The specific 15 routes selected | VAYU basket selection, deterministically derived from the rule above |
| traffic_weight values | Derived VAYU weights — traffic-proportional by construction, not officially endorsed |

## VAYU-Basket-Rule-v1

1. Include the top 10 routes by **conservative** bidirectional passenger traffic unconditionally.
2. **Stage 1 (region gap-filling):** scan remaining routes in descending traffic-rank order. Add a route if and only if it introduces a region (of North/South/East/West/Central/Northeast) not yet in the basket. Continue until all 6 regions are represented.
3. **Stage 2 (city gap-filling):** continue scanning in descending rank order. Add a route if and only if it introduces a city not yet in the basket. Stop at 15 routes.

This rule is deterministic and reproducible: given the same ranked DGCA table, any analyst re-running it gets the same 15 routes. No route was chosen by name.

## DASH treatment

Conservative bidirectional traffic (both directions present, no DGCA_DASH) is used for ranking, eligibility, and `traffic_weight`. The zero-treated alternative (DGCA_DASH treated as 0) is preserved in outputs purely as a documented analytical alternative and was not used for selection or weighting.

## GOA / DABOLIM

The DGCA-standardized name `GOA` remains deliberately unmapped (`FLAG_FOR_REVIEW`) — Goa has had two separate operating airports since Jan 2023 (Dabolim/GOI, Manohar Intl-Mopa/GOX) and DGCA's `GOA` vs `DABOLIM` rows carry materially different passenger counts. This basket uses only the unambiguous `DABOLIM` (GOI) entries.

## Publication weight precision and rounding rule

Published `traffic_weight` values are rounded to 6 decimal places. Because independently rounding 15 weights does not generally sum to exactly 1.0, any rounding residual is added to the single route with the largest full-precision weight (ties broken by lowest basket_rank) — for this basket, that route is **BOM-DEL**. The unadjusted, full-precision weight for every route is preserved in `traffic_weight_full_precision` in the exported CSV and metadata, so the adjustment is fully auditable rather than hidden.

## Approved basket

| Basket Rank | Traffic Rank | Route | route_id | Bidirectional Pax | Weight | Stage |
|---|---|---|---|---|---|---|
| 1 | 1 | DELHI–MUMBAI | BOM-DEL | 6,850,869 | 16.26% | TOP_K |
| 2 | 2 | BENGALURU–DELHI | BLR-DEL | 4,681,042 | 11.11% | TOP_K |
| 3 | 3 | BENGALURU–MUMBAI | BLR-BOM | 4,114,574 | 9.77% | TOP_K |
| 4 | 4 | DELHI–HYDERABAD | DEL-HYD | 3,295,918 | 7.82% | TOP_K |
| 5 | 5 | DELHI–PUNE | DEL-PNQ | 2,924,045 | 6.94% | TOP_K |
| 6 | 6 | DELHI–KOLKATA | CCU-DEL | 2,770,386 | 6.58% | TOP_K |
| 7 | 7 | AHMEDABAD–DELHI | AMD-DEL | 2,537,042 | 6.02% | TOP_K |
| 8 | 8 | CHENNAI–DELHI | DEL-MAA | 2,452,761 | 5.82% | TOP_K |
| 9 | 9 | HYDERABAD–MUMBAI | BOM-HYD | 2,353,279 | 5.59% | TOP_K |
| 10 | 10 | BENGALURU–KOLKATA | BLR-CCU | 2,326,980 | 5.52% | TOP_K |
| 11 | 11 | DELHI–SRINAGAR | DEL-SXR | 2,315,422 | 5.50% | STAGE2_CITY |
| 12 | 18 | DABOLIM–DELHI | DEL-GOI | 1,561,827 | 3.71% | STAGE2_CITY |
| 13 | 19 | DELHI–GUWAHATI | DEL-GAU | 1,538,643 | 3.65% | STAGE1_REGION |
| 14 | 21 | BENGALURU–KOCHI | BLR-COK | 1,485,148 | 3.52% | STAGE2_CITY |
| 15 | 39 | DELHI–INDORE | DEL-IDR | 924,366 | 2.19% | STAGE1_REGION |

## Coverage and concentration statistics

- Total basket traffic: 42,132,302 pax
- Coverage of all eligible DGCA traffic: 26.13%
- Distinct cities: 13 — AHMEDABAD, BENGALURU, CHENNAI, DABOLIM, DELHI, GUWAHATI, HYDERABAD, INDORE, KOCHI, KOLKATA, MUMBAI, PUNE, SRINAGAR
- Distinct regions: 6 — Central, East, North, Northeast, South, West
- Delhi appears in 11/15 routes (73.3%)
- Mumbai appears in 3/15 routes (20.0%)
- Weight sum (verification): 1.000000

## What this basket is NOT

- NOT an official MoSPI basket
- NOT official CPI route weights
- NOT endorsed by DGCA or any government body
- NOT final — weights will update when newer DGCA traffic data is published
