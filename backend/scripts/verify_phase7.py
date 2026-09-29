#!/usr/bin/env python3
"""
VAYU INDEX — Phase 7 Verification
===================================

Independent acceptance checks run against the Phase 7 outputs ON DISK.
This script is read-only: it never rewrites an output.

It verifies the locked methodology end to end — median definition, round
assignment, the flight-first hierarchy, diagnostic non-influence, coverage
labelling, audit completeness, determinism, and that Phase 2 / Phase 5 /
Phase 6 artefacts are byte-identical to the pre-Phase-7 baseline.

Usage:
    python scripts/verify_phase7.py
"""

from __future__ import annotations

import collections
import hashlib
import os
import sys
from decimal import Decimal

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.consolidation import consolidation_engine as E  # noqa: E402
from src.consolidation import rules as R  # noqa: E402
from src.deduplication import rules as dedup_rules  # noqa: E402


CANONICAL_CSV = os.path.join("outputs", "canonical_airfare_observations.csv")
DEDUPLICATED_CSV = os.path.join("outputs", "deduplicated_airfare_observations.csv")
PHASE6_AUDIT_CSV = os.path.join("outputs", "phase6_duplicate_audit_report.csv")
VALIDATED_CSV = os.path.join("outputs", "validated_airfare_observations.csv")
BASKET_CSV = os.path.join(
    "data", "official", "dgca", "processed", "vayu_route_basket_2024_25.csv"
)

CONSOLIDATED_CSV = os.path.join("outputs", "consolidated_airfare_observations.csv")
FLIGHT_REPORT_CSV = os.path.join("outputs", "phase7_flight_cell_report.csv")
OBSERVATION_MAP_CSV = os.path.join("outputs", "phase7_observation_map.csv")

EXPECTED_CANONICAL_ROWS = 778

# Byte-level baseline captured BEFORE any Phase 7 work began.
LOCKED_SHA256 = {
    VALIDATED_CSV: "f1220617f380f645b8cb21dc4e8e93a069d17a5b8333835558df33e0b43cf45b",
    DEDUPLICATED_CSV: "6c51ea30d1728d959afdd91c1fea3fc6f2524c8b49875ecfea7791cf79a0a7d9",
    CANONICAL_CSV: "1223c7b15e7a2eec4798565f9d5013085e8cb3c64b82c17dca9f5375178c488c",
    PHASE6_AUDIT_CSV: "86afc9b8378ddd127d10002537669ae263da5f7dca86548aaca84a32f8d14030",
    BASKET_CSV: "dc57e6d470a2ed9061dd82a92c84943749c3c648cef00b85b3f250df2f87c181",
}

PASSED = []
FAILED = []


def check(label, condition, detail=""):
    if condition:
        PASSED.append(label)
        print("  PASS  %s%s" % (label, ("  — " + detail) if detail else ""))
    else:
        FAILED.append(label)
        print("  FAIL  %s%s" % (label, ("  — " + detail) if detail else ""))


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read(path):
    import pandas as pd

    return pd.read_csv(path, dtype=str, keep_default_na=False)


def main():
    print("VAYU INDEX — Phase 7 Verification")
    print("=" * 70)

    # -- Section 1: upstream artefacts are untouched -----------------------
    print("\n[1] Upstream artefacts byte-identical (Phase 2 / Phase 5 / Phase 6)")
    for path, expected in sorted(LOCKED_SHA256.items()):
        if not os.path.exists(path):
            check("baseline present: %s" % path, False, "file missing")
            continue
        actual = sha256(path)
        check("unchanged: %s" % path, actual == expected, actual[:16])

    # -- Section 2: outputs exist and have the locked schema ---------------
    print("\n[2] Phase 7 outputs and schemas")
    for path in (CONSOLIDATED_CSV, FLIGHT_REPORT_CSV, OBSERVATION_MAP_CSV):
        check("output exists: %s" % path, os.path.exists(path))
    if FAILED:
        _summary()
        return

    canonical = read(CANONICAL_CSV)
    consolidated = read(CONSOLIDATED_CSV)
    flights = read(FLIGHT_REPORT_CSV)
    observations = read(OBSERVATION_MAP_CSV)

    check(
        "consolidated schema matches locked column order",
        tuple(consolidated.columns) == E.CONSOLIDATED_COLUMNS,
    )
    check(
        "flight-cell schema matches locked column order",
        tuple(flights.columns) == E.FLIGHT_CELL_COLUMNS,
    )
    check(
        "observation-map schema matches locked column order",
        tuple(observations.columns) == E.OBSERVATION_MAP_COLUMNS,
    )

    # -- Section 3: auditability ------------------------------------------
    print("\n[3] Auditability — nothing deleted, everything explained")
    check(
        "canonical input row count",
        len(canonical) == EXPECTED_CANONICAL_ROWS,
        "%d rows" % len(canonical),
    )
    check(
        "observation map preserves every canonical observation",
        len(observations) == len(canonical),
        "%d rows" % len(observations),
    )
    check(
        "observation ids match the canonical input exactly",
        set(observations["observation_id"]) == set(canonical["observation_id"]),
    )
    check(
        "observation ids are unique",
        observations["observation_id"].nunique() == len(observations),
    )
    known_statuses = {
        R.PARTICIPATION_PARTICIPATED,
        R.PARTICIPATION_EXCLUDED_SOLD_OUT,
        R.PARTICIPATION_EXCLUDED_MISSING_PRICE,
        R.PARTICIPATION_EXCLUDED_NO_ROUND,
        R.PARTICIPATION_EXCLUDED_MISSING_SOURCE,
        R.PARTICIPATION_EXCLUDED_MISSING_IDENTITY,
    }
    check(
        "every observation has an explicit participation status",
        set(observations["participation_status"]).issubset(known_statuses)
        and "" not in set(observations["participation_status"]),
    )
    check(
        "consolidation cell ids are unique",
        consolidated["consolidation_cell_id"].nunique() == len(consolidated),
    )
    check("flight cell ids are unique", flights["flight_cell_id"].nunique() == len(flights))
    cell_ids = set(consolidated["consolidation_cell_id"])
    check(
        "every flight cell belongs to a consolidation cell",
        set(flights["consolidation_cell_id"]).issubset(cell_ids),
    )
    mapped_cells = set(observations["consolidation_cell_id"]) - {""}
    check("every mapped cell id exists in the output", mapped_cells.issubset(cell_ids))
    member_rows = observations[observations["consolidation_cell_id"] != ""]
    declared = sum(int(value) for value in consolidated["observation_count"])
    check(
        "cell observation counts reconcile with the map",
        declared == len(member_rows),
        "%d == %d" % (declared, len(member_rows)),
    )

    # -- Section 4: price rules -------------------------------------------
    print("\n[4] Price rules — no imputation, no zeros, no anomaly detection")
    fares = [value for value in consolidated["consolidated_fare"] if value != ""]
    check("no consolidated fare is zero", all(Decimal(v) != 0 for v in fares))
    check("no consolidated fare is negative", all(Decimal(v) > 0 for v in fares))
    check(
        "every consolidated fare carries 2 decimal places",
        all(v.split(".")[-1].__len__() == 2 for v in fares),
    )
    statuses = set(consolidated["consolidation_status"])
    check(
        "consolidation status vocabulary is closed",
        statuses.issubset(
            {
                R.STATUS_CONSOLIDATED,
                R.STATUS_NO_PRICE_ALL_SOLD_OUT,
                R.STATUS_NO_PRICE_ALL_MISSING,
                R.STATUS_NO_PRICE_NO_USABLE_FARE,
            }
        ),
    )
    priced = consolidated[consolidated["consolidation_status"] == R.STATUS_CONSOLIDATED]
    unpriced = consolidated[consolidated["consolidation_status"] != R.STATUS_CONSOLIDATED]
    check("every CONSOLIDATED cell has a fare", all(v != "" for v in priced["consolidated_fare"]))
    check(
        "every non-consolidated cell has no fabricated fare",
        all(v == "" for v in unpriced["consolidated_fare"]),
    )
    check(
        "sold-out observations are excluded from pricing but retained",
        sum(int(v) for v in consolidated["sold_out_observation_count"])
        == int((observations["participation_status"] == R.PARTICIPATION_EXCLUDED_SOLD_OUT).sum()),
    )
    check(
        "missing-price observations are excluded from pricing but retained",
        sum(int(v) for v in consolidated["missing_price_observation_count"])
        == int(
            (observations["participation_status"] == R.PARTICIPATION_EXCLUDED_MISSING_PRICE).sum()
        ),
    )
    check(
        "no anomaly / normalization / index columns leaked into Phase 7",
        not any(
            token in column.lower()
            for column in consolidated.columns
            for token in ("anomaly", "outlier", "normalized_index", "index_value", "weight")
        ),
    )

    # -- Section 5: median and hierarchy ----------------------------------
    print("\n[5] Median definition and the flight-first hierarchy")
    check(
        "midpoint median: [5300, 5500] -> 5400",
        R.midpoint_median([Decimal("5300"), Decimal("5500")]) == Decimal("5400.00"),
    )
    check(
        "midpoint median: [5000, 5200, 5600, 6000] -> 5400",
        R.midpoint_median(
            [Decimal("5000"), Decimal("5200"), Decimal("5600"), Decimal("6000")]
        )
        == Decimal("5400.00"),
    )
    check(
        "odd-count median: [5000, 5200, 6000] -> 5200",
        R.midpoint_median([Decimal("5000"), Decimal("5200"), Decimal("6000")])
        == Decimal("5200.00"),
    )

    rep_by_cell = collections.defaultdict(list)
    for _, row in flights.iterrows():
        if row["flight_representative_fare"] != "":
            rep_by_cell[row["consolidation_cell_id"]].append(
                Decimal(row["flight_representative_fare"])
            )
    stage2_ok = True
    stage2_bad = ""
    for _, row in priced.iterrows():
        values = rep_by_cell.get(row["consolidation_cell_id"], [])
        if not values or R.midpoint_median(values) != Decimal(row["consolidated_fare"]):
            stage2_ok = False
            stage2_bad = row["consolidation_cell_id"]
            break
    check(
        "Stage 2 reproduces every consolidated fare from flight representatives",
        stage2_ok,
        stage2_bad,
    )
    check(
        "each flight contributes exactly one Stage 2 value (no double counting)",
        all(
            len(rep_by_cell.get(row["consolidation_cell_id"], []))
            == int(row["priced_flight_instance_count"])
            for _, row in consolidated.iterrows()
        ),
    )
    check(
        "observed-value flag is populated for every priced cell",
        all(v in ("True", "False") for v in priced["consolidated_fare_is_observed_value"]),
    )
    check(
        "observed-value flag is blank when there is no fare",
        all(v == "" for v in unpriced["consolidated_fare_is_observed_value"]),
    )

    # -- Section 6: Option B diagnostic non-influence ----------------------
    print("\n[6] Option B (source-first) is diagnostic only")
    baseline_bytes = open(CONSOLIDATED_CSV, "rb").read()
    original = E.alt_source_first_fare
    try:
        E.alt_source_first_fare = lambda observations: (
            Decimal("999999"),
            {"TAMPERED": Decimal("999999")},
        )
        tampered = E.run_consolidation(E.read_canonical_csv(CANONICAL_CSV))
    finally:
        E.alt_source_first_fare = original
    check(
        "tampering with the diagnostic never changes consolidated_fare",
        list(tampered.consolidated["consolidated_fare"]) == list(consolidated["consolidated_fare"]),
    )
    check(
        "tampering does change the diagnostic column (the probe really fired)",
        set(tampered.consolidated["alt_source_first_fare"]) == {"999999.00"},
    )
    differing = sum(
        1
        for _, row in priced.iterrows()
        if row["alt_source_first_fare"] not in ("", row["consolidated_fare"])
    )
    check(
        "diagnostic is genuinely informative (differs somewhere)",
        differing > 0,
        "%d cells differ from the source-first alternative" % differing,
    )

    # -- Section 7: collection rounds --------------------------------------
    print("\n[7] Collection rounds")
    check(
        "Phase 7 tolerance is 30 minutes and independent of Phase 6's 15",
        R.ROUND_TOLERANCE_MINUTES == 30 and dedup_rules.TIME_TOLERANCE_MINUTES == 15,
    )
    check(
        "anchors documented as prototype configuration",
        R.ROUND_ANCHORS_ARE_PROTOTYPE_CONFIG
        and "not a finalized production sampling schedule" in R.ROUND_ANCHORS_PROVENANCE,
    )
    check(
        "+/-30 inclusive, 31 exclusive",
        R.assign_collection_round("2026-09-05 09:30", "A")[1] == R.ROUND_ALIGNMENT_ANCHORED
        and R.assign_collection_round("2026-09-05 08:30", "A")[1] == R.ROUND_ALIGNMENT_ANCHORED
        and R.assign_collection_round("2026-09-05 09:31", "A")[1] == R.ROUND_ALIGNMENT_UNALIGNED,
    )
    alignments = set(observations["round_alignment"])
    check(
        "round alignment vocabulary is closed",
        alignments.issubset(
            {
                R.ROUND_ALIGNMENT_ANCHORED,
                R.ROUND_ALIGNMENT_UNALIGNED,
                R.ROUND_ALIGNMENT_UNRESOLVED,
            }
        ),
    )
    anchored = observations[observations["round_alignment"] == R.ROUND_ALIGNMENT_ANCHORED]
    within = True
    for _, row in anchored.iterrows():
        stamp = R.parse_collection_timestamp(row["collection_timestamp"])
        anchor = R.parse_collection_timestamp(row["round_anchor_timestamp"])
        if stamp is None or anchor is None:
            within = False
            break
        if abs((stamp - anchor).total_seconds()) / 60 > R.ROUND_TOLERANCE_MINUTES:
            within = False
            break
    check("every anchored observation is within +/-30 minutes of its anchor", within)
    unaligned_rounds = sorted(
        {
            value
            for value in observations["collection_round_id"]
            if value.startswith(R.UNALIGNED_ROUND_ID_PREFIX)
        }
    )
    unaligned_singleton = all(
        observations[observations["collection_round_id"] == round_id][
            "collection_timestamp"
        ].nunique()
        == 1
        for round_id in unaligned_rounds
    )
    check(
        "unaligned rounds are singleton capture times",
        unaligned_singleton,
        "%d unaligned rounds" % len(unaligned_rounds),
    )
    unresolved = observations[observations["round_alignment"] == R.ROUND_ALIGNMENT_UNRESOLVED]
    check(
        "unresolved-timestamp observations form no consolidation cell",
        all(value == "" for value in unresolved["consolidation_cell_id"]),
        "%d unresolved" % len(unresolved),
    )

    # -- Section 8: coverage labelling ------------------------------------
    print("\n[8] Source coverage labelling")
    coverage_ok = all(
        row["source_coverage"] == R.source_coverage_label(int(row["participating_source_count"]))
        for _, row in consolidated.iterrows()
    )
    check("coverage label always matches the participating source count", coverage_ok)
    single = consolidated[consolidated["source_coverage"] == R.SOURCE_COVERAGE_SINGLE]
    check(
        "single-source cells are labelled SINGLE_SOURCE and still consolidated",
        all(int(row["participating_source_count"]) == 1 for _, row in single.iterrows()),
        "%d single-source cells" % len(single),
    )
    check(
        "missing sources are listed, never imputed",
        all(
            set(filter(None, row["missing_sources"].split(";")))
            == set(R.EXPECTED_SOURCES) - set(filter(None, row["participating_sources"].split(";")))
            for _, row in consolidated.iterrows()
        ),
    )

    # -- Section 9: route direction and strata -----------------------------
    print("\n[9] Route direction and strata separation")
    input_pairs = {(row["origin"], row["destination"]) for _, row in canonical.iterrows()}
    output_pairs = {(row["origin"], row["destination"]) for _, row in consolidated.iterrows()}
    check("no route direction was reversed or invented", output_pairs.issubset(input_pairs))
    grouped = observations[observations["consolidation_cell_id"] != ""].groupby(
        "consolidation_cell_id"
    )
    strata_ok = all(
        frame["fare_class"].nunique() == 1
        and frame["travel_date"].nunique() == 1
        and frame["advance_purchase_window"].nunique() == 1
        and frame["origin"].nunique() == 1
        and frame["destination"].nunique() == 1
        for _, frame in grouped
    )
    check(
        "no cell mixes routes, travel dates, fare classes or AP windows", strata_ok
    )

    # -- Section 10: determinism -------------------------------------------
    print("\n[10] Determinism")
    df = E.read_canonical_csv(CANONICAL_CSV)
    rerun = E.run_consolidation(df)
    check(
        "rerun reproduces the consolidated file byte-for-byte",
        rerun.consolidated.to_csv(index=False).replace("\r\n", "\n")
        == baseline_bytes.decode("utf-8").replace("\r\n", "\n"),
    )
    shuffled = E.run_consolidation(df.sample(frac=1, random_state=20260910).reset_index(drop=True))
    check(
        "shuffled input produces identical consolidated output",
        shuffled.consolidated.to_csv(index=False) == rerun.consolidated.to_csv(index=False),
    )
    check(
        "shuffled input produces identical flight-cell output",
        shuffled.flight_cells.to_csv(index=False) == rerun.flight_cells.to_csv(index=False),
    )
    check(
        "shuffled input produces identical observation map",
        shuffled.observation_map.to_csv(index=False) == rerun.observation_map.to_csv(index=False),
    )
    check(
        "outputs are deterministically sorted",
        list(consolidated["consolidation_cell_id"]) == sorted(consolidated["consolidation_cell_id"])
        and list(flights["flight_cell_id"]) == sorted(flights["flight_cell_id"])
        and list(observations["observation_id"]) == sorted(observations["observation_id"]),
    )

    _summary(consolidated, flights, observations)


def _summary(consolidated=None, flights=None, observations=None):
    print("\n" + "=" * 70)
    if consolidated is not None:
        coverage = collections.Counter(consolidated["source_coverage"])
        status = collections.Counter(consolidated["consolidation_status"])
        participation = collections.Counter(observations["participation_status"])
        print("Consolidation cells : %d" % len(consolidated))
        print("Flight cells        : %d" % len(flights))
        print("Observations mapped : %d" % len(observations))
        print("Status              : %s" % dict(sorted(status.items())))
        print("Coverage            : %s" % dict(sorted(coverage.items())))
        print("Participation       : %s" % dict(sorted(participation.items())))
        print("-" * 70)
    print("PASSED: %d   FAILED: %d" % (len(PASSED), len(FAILED)))
    if FAILED:
        print("\nFailed checks:")
        for label in FAILED:
            print("  - %s" % label)
    print("=" * 70)
    sys.exit(1 if FAILED else 0)


if __name__ == "__main__":
    main()
