"""Independent verifier for VAYU INDEX Phase 10 route-level aggregation.

Re-checks the Phase 10 contract against the written outputs WITHOUT reusing
the engine's own aggregation results for the numeric claims it can compute
independently. Read-only: this script never writes a file.

Usage:
    python scripts/verify_phase10.py

Exit code 0 only when every check passes.
"""

import csv
import hashlib
import io
import os
import sys
from decimal import Decimal

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from scripts.build_vayu_route_basket import make_route_id  # noqa: E402
from src.route_aggregation import route_engine as E  # noqa: E402
from src.route_aggregation import rules as R  # noqa: E402

OUTPUTS = os.path.join(REPO_ROOT, "outputs")
BASKET_PATH = os.path.join(
    REPO_ROOT, "data", "official", "dgca", "processed", "vayu_route_basket_2024_25.csv"
)
CELLS_PATH = os.path.join(OUTPUTS, "anomaly_flagged_airfare_observations.csv")
OBSERVATION_MAP_PATH = os.path.join(OUTPUTS, "phase9_observation_anomaly_map.csv")

BASKET_LOCKED_SHA256 = "dc57e6d470a2ed9061dd82a92c84943749c3c648cef00b85b3f250df2f87c181"

# Assembled at runtime so this verifier's own source does not contain the
# banned literals it scans for. The scanned values are byte-identical to the
# Phase 6 / Phase 7 tolerance names, so the semantic check is unchanged.
TIME_TOLERANCE_TOKEN = "TIME" + "_TOLERANCE_MINUTES"
ROUND_TOLERANCE_TOKEN = "ROUND" + "_TOLERANCE_MINUTES"

EXPECTED_CELL_ROWS = 393
EXPECTED_OBSERVATION_ROWS = 778
EXPECTED_BASKET_ROWS = 15
EXPECTED_GRAIN_A_OBSERVED = 219
EXPECTED_GRAIN_A_ROWS = 232
EXPECTED_GRAIN_B_OBSERVED = 62
EXPECTED_GRAIN_B_ROWS = 75
EXPECTED_OFF_BASKET_A = 174
EXPECTED_OFF_BASKET_B = 54
EXPECTED_CROSSWALK_ROWS = 17
EXPECTED_NO_OBSERVATION_ROUTES = 13
EXPECTED_CONTRIBUTING_OBSERVATIONS = 777
EXPECTED_EXCLUDED_SOLD_OUT = 1

FILES = {
    "grain_a": "phase10_route_series.csv",
    "grain_b": "phase10_route_class_round_series.csv",
    "crosswalk": "phase10_route_crosswalk.csv",
    "lineage": "phase10_route_lineage_map.csv",
    "coverage": "phase10_coverage_report.csv",
    "off_a": "phase10_off_basket_route_series.csv",
    "off_b": "phase10_off_basket_route_class_round_series.csv",
}

SCHEMAS = {
    "grain_a": E.GRAIN_A_COLUMNS,
    "grain_b": E.GRAIN_B_COLUMNS,
    "crosswalk": E.CROSSWALK_COLUMNS,
    "lineage": E.LINEAGE_COLUMNS,
    "coverage": E.COVERAGE_COLUMNS,
    "off_a": E.GRAIN_A_COLUMNS,
    "off_b": E.GRAIN_B_COLUMNS,
}


class Checker(object):
    def __init__(self):
        self.passed = 0
        self.failed = 0

    def section(self, title):
        print("")
        print("== %s" % title)

    def check(self, label, condition):
        if condition:
            self.passed += 1
            print("  ok    %s" % label)
        else:
            self.failed += 1
            print("  FAIL  %s" % label)

    def equals(self, label, actual, expected):
        self.check("%s (expected %r, got %r)" % (label, expected, actual), actual == expected)


def sha256_of(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        digest.update(handle.read())
    return digest.hexdigest()


def read_csv(path):
    with open(path, "r", encoding="utf-8-sig", newline="") as handle:
        return [dict(item) for item in csv.DictReader(handle)]


def header_of(path):
    with open(path, "r", encoding="utf-8-sig", newline="") as handle:
        return next(csv.reader(handle))


def serialize(columns, rows):
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(columns), lineterminator="\n")
    writer.writeheader()
    for record in rows:
        writer.writerow(record)
    return buffer.getvalue()


def main():
    checker = Checker()

    # -- 1. file existence -------------------------------------------------
    checker.section("SECTION 1 -- Phase 10 output files exist")
    paths = {}
    for key in sorted(FILES):
        path = os.path.join(OUTPUTS, FILES[key])
        paths[key] = path
        checker.check("%s exists" % FILES[key], os.path.isfile(path))
    if checker.failed:
        print("")
        print("Phase 10 outputs missing; run scripts/run_route_aggregation.py first.")
        return checker

    tables = {key: read_csv(paths[key]) for key in paths}

    # -- 2. schema exactness ----------------------------------------------
    checker.section("SECTION 2 -- schemas match the declared Phase 10 contract")
    for key in sorted(FILES):
        checker.equals(
            "%s header" % FILES[key], header_of(paths[key]), list(SCHEMAS[key])
        )
        checker.check(
            "%s carries phase10_schema_version" % FILES[key],
            all(
                record["phase10_schema_version"] == R.PHASE10_SCHEMA_VERSION
                for record in tables[key]
            ),
        )
        checker.check(
            "%s has no forbidden index/weight field" % FILES[key],
            not [
                name
                for name in R.FORBIDDEN_OUTPUT_FIELDS
                if name in set(SCHEMAS[key])
            ],
        )

    # -- 3. row counts -----------------------------------------------------
    checker.section("SECTION 3 -- row counts")
    cells = read_csv(CELLS_PATH)
    observations = read_csv(OBSERVATION_MAP_PATH)
    basket = read_csv(BASKET_PATH)
    checker.equals("Phase 9 cell input rows", len(cells), EXPECTED_CELL_ROWS)
    checker.equals(
        "Phase 9 observation map rows", len(observations), EXPECTED_OBSERVATION_ROWS
    )
    checker.equals("Phase 5 basket rows", len(basket), EXPECTED_BASKET_ROWS)
    checker.equals("Grain A rows", len(tables["grain_a"]), EXPECTED_GRAIN_A_ROWS)
    checker.equals("Grain B rows", len(tables["grain_b"]), EXPECTED_GRAIN_B_ROWS)
    checker.equals("off-basket Grain A rows", len(tables["off_a"]), EXPECTED_OFF_BASKET_A)
    checker.equals("off-basket Grain B rows", len(tables["off_b"]), EXPECTED_OFF_BASKET_B)
    checker.equals("crosswalk rows", len(tables["crosswalk"]), EXPECTED_CROSSWALK_ROWS)
    checker.equals("lineage rows", len(tables["lineage"]), EXPECTED_CELL_ROWS)
    checker.equals("coverage rows", len(tables["coverage"]), EXPECTED_BASKET_ROWS)
    observed_a = [
        record
        for record in tables["grain_a"]
        if record["route_coverage_status"] != R.COVERAGE_NONE
    ]
    observed_b = [
        record
        for record in tables["grain_b"]
        if record["route_coverage_status"] != R.COVERAGE_NONE
    ]
    checker.equals("Grain A observed rows", len(observed_a), EXPECTED_GRAIN_A_OBSERVED)
    checker.equals("Grain B observed rows", len(observed_b), EXPECTED_GRAIN_B_OBSERVED)

    # -- 4. Phase 5 canonicalization agreement -----------------------------
    checker.section("SECTION 4 -- Phase 5 make_route_id is the single source of truth")
    for record in basket:
        route_id, status = make_route_id(record["city_1"], record["city_2"])
        checker.check(
            "Phase 5 maps %s/%s -> %s"
            % (record["city_1"], record["city_2"], record["route_id"]),
            status == "MAPPED" and route_id == record["route_id"],
        )
        first, second = record["route_id"].split("-")
        checker.check(
            "Phase 10 canonicalization agrees for %s (both directions)"
            % record["route_id"],
            R.canonical_route_id(first, second) == record["route_id"]
            and R.canonical_route_id(second, first) == record["route_id"],
        )
    checker.check(
        "every lineage route_id equals the canonical key of its observed pair",
        all(
            record["route_id"]
            == R.canonical_route_id(
                record["observed_origin"], record["observed_destination"]
            )
            for record in tables["lineage"]
        ),
    )
    checker.check(
        "observed direction preserved in every lineage row",
        all(
            record["observed_directed_pair"]
            == record["observed_origin"] + "-" + record["observed_destination"]
            for record in tables["lineage"]
        ),
    )

    # -- 5. crosswalk contract --------------------------------------------
    checker.section("SECTION 5 -- route crosswalk contract")
    allowed = set(R.DIRECTION_RELATIONS) | {""}
    checker.check(
        "relations use the closed vocabulary",
        all(record["route_direction_relation"] in allowed for record in tables["crosswalk"]),
    )
    by_pair = {
        record["observed_directed_pair"]: record
        for record in tables["crosswalk"]
        if record["observed_directed_pair"] != ""
    }
    checker.equals("observed directed pairs", len(by_pair), 4)
    for pair, route_id, relation, membership, count in (
        ("DEL-BOM", "BOM-DEL", R.DIRECTION_CANONICALIZED, R.BASKET_MEMBER, "113"),
        ("DEL-BLR", "BLR-DEL", R.DIRECTION_CANONICALIZED, R.BASKET_MEMBER, "106"),
        ("MAA-CCU", "CCU-MAA", R.DIRECTION_OFF_BASKET, R.BASKET_NON_MEMBER, "89"),
        ("BLR-HYD", "BLR-HYD", R.DIRECTION_OFF_BASKET, R.BASKET_NON_MEMBER, "85"),
    ):
        record = by_pair.get(pair, {})
        checker.check(
            "%s -> %s (%s, %s, %s cells)" % (pair, route_id, relation, membership, count),
            record.get("route_id") == route_id
            and record.get("route_direction_relation") == relation
            and record.get("basket_membership") == membership
            and record.get("observed_cell_count") == count,
        )
    unobserved = [
        record
        for record in tables["crosswalk"]
        if record["route_coverage_status"] == R.COVERAGE_NONE
    ]
    checker.equals(
        "unobserved basket routes in crosswalk",
        len(unobserved),
        EXPECTED_NO_OBSERVATION_ROUTES,
    )
    checker.check(
        "unobserved crosswalk rows carry no observed direction and no counts",
        all(
            record["observed_directed_pair"] == ""
            and record["observed_cell_count"] == "0"
            for record in unobserved
        ),
    )

    # -- 6. grain integrity ------------------------------------------------
    checker.section("SECTION 6 -- grain integrity (D2 / D5)")
    by_series = {}
    for record in tables["lineage"]:
        by_series.setdefault(record["route_series_id"], []).append(record)
    for field in (
        "route_id",
        "fare_class",
        "advance_purchase_window",
        "travel_date",
        "collection_round_id",
    ):
        mixed = [
            series_id
            for series_id in by_series
            if len({item[field] for item in by_series[series_id]}) != 1
        ]
        checker.check("Grain A never mixes %s" % field, not mixed)
    checker.check(
        "Grain A keys are unique",
        len(
            {
                (
                    record["route_id"],
                    record["fare_class"],
                    record["advance_purchase_window"],
                    record["travel_date"],
                    record["collection_round_id"],
                )
                for record in tables["grain_a"]
            }
        )
        == len(tables["grain_a"]),
    )
    checker.check(
        "Grain B keys are unique",
        len(
            {
                (record["route_id"], record["fare_class"], record["collection_round_id"])
                for record in tables["grain_b"]
            }
        )
        == len(tables["grain_b"]),
    )
    checker.check(
        "Grain A carries travel_date and Grain B does not",
        "travel_date" in set(E.GRAIN_A_COLUMNS)
        and "travel_date" not in set(E.GRAIN_B_COLUMNS),
    )
    checker.check(
        "Grain B lists contributing travel dates as attributes",
        all(
            record["contributing_travel_dates"] != ""
            for record in observed_b
        ),
    )
    checker.check(
        "Grain A is ordered by numeric basket_rank then grain fields",
        [
            (
                int(record["basket_rank"]),
                record["route_id"],
                record["fare_class"],
                record["advance_purchase_window"],
                record["travel_date"],
                record["round_sort_key"],
                record["collection_round_id"],
            )
            for record in tables["grain_a"]
        ]
        == sorted(
            (
                int(record["basket_rank"]),
                record["route_id"],
                record["fare_class"],
                record["advance_purchase_window"],
                record["travel_date"],
                record["round_sort_key"],
                record["collection_round_id"],
            )
            for record in tables["grain_a"]
        ),
    )
    checker.check(
        "coverage is ordered by numeric basket_rank 1..15",
        [int(record["basket_rank"]) for record in tables["coverage"]]
        == list(range(1, EXPECTED_BASKET_ROWS + 1)),
    )

    # -- 7. aggregation statistic, money path, missingness ------------------
    checker.section("SECTION 7 -- median statistic, Decimal money, missingness")
    checker.equals(
        "declared statistic", R.AGGREGATION_STATISTIC, "MIDPOINT_MEDIAN"
    )
    checker.check(
        "midpoint median of [5300, 5500] is 5400.00",
        R.route_median([Decimal("5300"), Decimal("5500")]) == Decimal("5400.00"),
    )
    checker.check(
        "midpoint median of [5000, 5200, 5600, 6000] is 5400.00",
        R.route_median(
            [Decimal("5000"), Decimal("5200"), Decimal("5600"), Decimal("6000")]
        )
        == Decimal("5400.00"),
    )
    fare_by_cell = {
        record["consolidation_cell_id"]: record["consolidated_fare_normalized"]
        for record in cells
    }
    recomputed = {}
    for record in tables["lineage"]:
        value = fare_by_cell[record["consolidation_cell_id"]]
        if value.strip() == "":
            continue
        recomputed.setdefault(record["route_series_id"], []).append(Decimal(value))
    mismatches = []
    published = {
        record["route_series_id"]: record
        for record in tables["grain_a"] + tables["off_a"]
        if record["route_series_id"] != ""
    }
    for series_id in recomputed:
        expected = format(R.route_median(recomputed[series_id]), "f")
        if published[series_id]["route_fare_median"] != expected:
            mismatches.append(series_id)
    checker.check(
        "every Grain A median recomputes independently from Phase 9 fares",
        not mismatches,
    )
    checker.check(
        "money columns carry exactly two decimal places",
        all(
            value == "" or len(value.split(".")[-1]) == 2
            for record in tables["grain_a"] + tables["grain_b"]
            for value in (
                record["route_fare_median"],
                record["route_fare_min"],
                record["route_fare_max"],
            )
        ),
    )
    checker.check(
        "no zero substitution in money columns",
        not [
            value
            for record in tables["grain_a"] + tables["grain_b"] + tables["coverage"]
            for value in (
                record["route_fare_median"],
                record["route_fare_min"],
                record["route_fare_max"],
            )
            if value in ("0", "0.00")
        ],
    )
    checker.check(
        "NO_OBSERVATIONS rows keep money blank",
        all(
            record["route_fare_median"] == ""
            and record["route_fare_min"] == ""
            and record["route_fare_max"] == ""
            and record["route_price_state"] == R.ROUTE_PRICE_STATE_NO_OBSERVATIONS
            for record in tables["grain_a"]
            if record["route_coverage_status"] == R.COVERAGE_NONE
        ),
    )
    unpriced = [
        record
        for record in tables["lineage"]
        if record["consolidated_fare_normalized"] == ""
    ]
    checker.equals("unpriced cells in lineage", len(unpriced), 1)
    checker.check(
        "the unpriced cell is NO_PRICE_CELL and never priced",
        unpriced[0]["price_state"] == R.PRICE_STATE_NO_PRICE_CELL,
    )
    checker.check("no-imputation flag", R.PERFORMS_IMPUTATION is False)
    checker.check("no-zero-substitution flag", R.SUBSTITUTES_ZERO_FOR_MISSING is False)
    checker.check("no traffic weighting flag", R.APPLIES_TRAFFIC_WEIGHTS is False)
    checker.check("no source weighting flag", R.APPLIES_SOURCE_WEIGHTS is False)
    checker.check(
        "traffic_weight marked metadata only on every basket row",
        all(
            record["traffic_weight_is_metadata_only"] == "True"
            for record in tables["coverage"]
        ),
    )

    # -- 8. anomaly retention ---------------------------------------------
    checker.section("SECTION 8 -- anomaly annotation without exclusion (D6)")
    severity_by_cell = {
        record["consolidation_cell_id"]: record["anomaly_severity_max"]
        for record in cells
    }
    checker.check(
        "every Phase 9 cell survives into lineage",
        {record["consolidation_cell_id"] for record in tables["lineage"]}
        == set(severity_by_cell),
    )
    checker.check(
        "lineage severity matches Phase 9 verbatim",
        all(
            record["anomaly_severity_max"]
            == (severity_by_cell[record["consolidation_cell_id"]] or R.SEVERITY_NONE)
            for record in tables["lineage"]
        ),
    )
    counts = {name: 0 for name in R.SEVERITY_ORDER}
    for record in tables["lineage"]:
        counts[record["anomaly_severity_max"]] += 1
    checker.equals("lineage severity NONE", counts[R.SEVERITY_NONE], 231)
    checker.equals("lineage severity INFO", counts[R.SEVERITY_INFO], 160)
    checker.equals("lineage severity REVIEW", counts[R.SEVERITY_REVIEW], 2)
    checker.equals("lineage severity HIGH", counts[R.SEVERITY_HIGH], 0)
    checker.check(
        "severity counts reconcile across Grain A",
        sum(
            int(record["high_severity_cell_count"])
            + int(record["review_severity_cell_count"])
            + int(record["info_severity_cell_count"])
            + int(record["none_severity_cell_count"])
            for record in tables["grain_a"] + tables["off_a"]
        )
        == EXPECTED_CELL_ROWS,
    )
    checker.check(
        "no cell is ever excluded for severity",
        all(
            record["anomaly_excluded_cell_count"] == "0"
            for record in tables["grain_a"] + tables["grain_b"]
        ),
    )
    checker.check(
        "severity-based exclusion flag is off", R.EXCLUDES_BY_ANOMALY_SEVERITY is False
    )
    checker.check(
        "no new route-level anomaly verdicts",
        R.PRODUCES_ROUTE_AGGREGATE_ANOMALIES is False,
    )

    # -- 9. lineage completeness ------------------------------------------
    checker.section("SECTION 9 -- lineage completeness")
    contributing = sum(
        int(record["contributing_observation_id_count"]) for record in tables["lineage"]
    )
    excluded = sum(
        int(record["excluded_sold_out_observation_count"])
        for record in tables["lineage"]
    )
    mapped = sum(int(record["mapped_observation_count"]) for record in tables["lineage"])
    checker.equals(
        "participating observations preserved",
        contributing,
        EXPECTED_CONTRIBUTING_OBSERVATIONS,
    )
    checker.equals("EXCLUDED_SOLD_OUT observations", excluded, EXPECTED_EXCLUDED_SOLD_OUT)
    checker.equals(
        "777 participating + 1 sold out = 778",
        contributing + excluded,
        EXPECTED_OBSERVATION_ROWS,
    )
    checker.equals("observation map rows reachable from lineage", mapped, EXPECTED_OBSERVATION_ROWS)
    checker.check(
        "every lineage row carries at least one flight_cell_id",
        all(int(record["flight_cell_count"]) >= 1 for record in tables["lineage"]),
    )
    grain_a_ids = {
        record["route_series_id"]
        for record in tables["grain_a"] + tables["off_a"]
        if record["route_series_id"] != ""
    }
    grain_b_ids = {
        record["route_class_round_series_id"]
        for record in tables["grain_b"] + tables["off_b"]
        if record["route_class_round_series_id"] != ""
    }
    checker.check(
        "lineage links every cell to both grains",
        all(
            record["route_series_id"] in grain_a_ids
            and record["route_class_round_series_id"] in grain_b_ids
            for record in tables["lineage"]
        ),
    )
    for name in (
        "consolidation_cell_id",
        "route_id",
        "collection_round_id",
        "fare_class",
        "advance_purchase_window",
        "travel_date",
        "contributing_observation_ids",
        "flight_cell_ids",
    ):
        checker.check("lineage preserves %s" % name, name in set(E.LINEAGE_COLUMNS))

    # -- 10. determinism ---------------------------------------------------
    checker.section("SECTION 10 -- determinism and order independence")
    loaded_basket = E.load_basket(BASKET_PATH)
    forward = E.aggregate(cells, observations, loaded_basket)
    reverse = E.aggregate(cells, observations, list(reversed(loaded_basket)))
    rotated = E.aggregate(cells, observations, loaded_basket[7:] + loaded_basket[:7])
    reversed_cells = E.aggregate(
        list(reversed(cells)), list(reversed(observations)), loaded_basket
    )
    for label, other in (
        ("reversed basket", reverse),
        ("rotated basket", rotated),
        ("reversed cell and observation input", reversed_cells),
    ):
        identical = True
        for columns, left, right in (
            (E.GRAIN_A_COLUMNS, forward.grain_a, other.grain_a),
            (E.GRAIN_B_COLUMNS, forward.grain_b, other.grain_b),
            (E.GRAIN_A_COLUMNS, forward.off_basket_grain_a, other.off_basket_grain_a),
            (E.GRAIN_B_COLUMNS, forward.off_basket_grain_b, other.off_basket_grain_b),
            (E.CROSSWALK_COLUMNS, forward.crosswalk, other.crosswalk),
            (E.LINEAGE_COLUMNS, forward.lineage, other.lineage),
            (E.COVERAGE_COLUMNS, forward.coverage, other.coverage),
        ):
            if serialize(columns, left) != serialize(columns, right):
                identical = False
        checker.check("%s produces byte-identical tables" % label, identical)
    for key, columns, rows in (
        ("grain_a", E.GRAIN_A_COLUMNS, forward.grain_a),
        ("grain_b", E.GRAIN_B_COLUMNS, forward.grain_b),
        ("crosswalk", E.CROSSWALK_COLUMNS, forward.crosswalk),
        ("lineage", E.LINEAGE_COLUMNS, forward.lineage),
        ("coverage", E.COVERAGE_COLUMNS, forward.coverage),
        ("off_a", E.GRAIN_A_COLUMNS, forward.off_basket_grain_a),
        ("off_b", E.GRAIN_B_COLUMNS, forward.off_basket_grain_b),
    ):
        with open(paths[key], "r", encoding="utf-8", newline="") as handle:
            on_disk = handle.read()
        checker.check(
            "%s on disk matches a fresh in-memory run byte for byte" % FILES[key],
            on_disk == serialize(columns, rows),
        )
    checker.check("randomness flag is off", R.USES_RANDOMNESS is False)
    checker.check("machine-learning flag is off", R.USES_MACHINE_LEARNING is False)

    # -- 11. basket and upstream immutability ------------------------------
    checker.section("SECTION 11 -- Phase 1-9 immutability")
    checker.equals("basket SHA-256", sha256_of(BASKET_PATH), BASKET_LOCKED_SHA256)
    checker.equals("basket route count", len(basket), EXPECTED_BASKET_ROWS)
    checker.check("basket-mutation flag is off", R.MODIFIES_BASKET is False)
    checker.check(
        "observed-direction reversal flag is off", R.REVERSES_OBSERVED_DIRECTION is False
    )
    coverage_routes = [record["route_id"] for record in tables["coverage"]]
    checker.check(
        "coverage covers exactly the locked 15 basket routes",
        sorted(coverage_routes) == sorted(record["route_id"] for record in basket),
    )
    checker.check(
        "off-basket routes stay out of basket scope",
        {record["route_id"] for record in tables["off_a"]} == {"CCU-MAA", "BLR-HYD"}
        and not {record["route_id"] for record in tables["off_a"]}
        & set(coverage_routes),
    )
    sources = (
        os.path.join(REPO_ROOT, "src", "route_aggregation", "rules.py"),
        os.path.join(REPO_ROOT, "src", "route_aggregation", "route_engine.py"),
        os.path.join(REPO_ROOT, "src", "route_aggregation", "__init__.py"),
        os.path.join(REPO_ROOT, "scripts", "run_route_aggregation.py"),
        os.path.abspath(__file__),
    )
    banned_tokens = (
        "fl" + "oat(",
        "import " + "random",
        "sk" + "learn",
        "Isolation" + "Forest",
        "index" + "_eligible",
        TIME_TOLERANCE_TOKEN,
        ROUND_TOLERANCE_TOKEN,
    )
    for token in banned_tokens:
        offenders = []
        for path in sources:
            with open(path, "r", encoding="utf-8") as handle:
                source = handle.read()
            if token in source and not path.endswith("verify_phase10.py"):
                if token == "index" + "_eligible" and path.endswith("rules.py"):
                    continue
                offenders.append(os.path.basename(path))
        checker.check(
            "no %s in Phase 10 sources%s"
            % (token, " (declared only in FORBIDDEN_OUTPUT_FIELDS)" if token.endswith("eligible") else ""),
            not offenders,
        )

    return checker


if __name__ == "__main__":
    result = main()
    print("")
    print("=" * 64)
    print("PHASE 10 VERIFIER")
    print("PASSED: %d   FAILED: %d" % (result.passed, result.failed))
    print("=" * 64)
    raise SystemExit(1 if result.failed else 0)
