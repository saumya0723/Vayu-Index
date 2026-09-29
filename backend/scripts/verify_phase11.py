"""VAYU INDEX Phase 11 -- independent verifier.

Recomputes the Phase 11 index from the Phase 10 outputs and the locked Phase 5
basket, then checks the on-disk Phase 11 tables against that recomputation and
against the locked methodology (decisions D1-D12).

The verifier is deliberately independent of the test suite: it re-derives the
chain, the weights, the relatives and the period series from the published
rows, rather than trusting the engine's own intermediate state.

Usage (from the repository root):
    python scripts/verify_phase11.py

Exit code 0 means every check passed.
"""

import csv
import hashlib
import os
import sys
from decimal import Decimal
from decimal import localcontext

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from src.index_engine import index_engine as engine  # noqa: E402
from src.index_engine import rules as R  # noqa: E402

OUTPUT_DIR = os.path.join(REPO_ROOT, "outputs")
SRC_DIR = os.path.join(REPO_ROOT, "src", "index_engine")
SCRIPTS_DIR = os.path.join(REPO_ROOT, "scripts")
DOCS_DIR = os.path.join(REPO_ROOT, "docs")
BASKET_PATH = os.path.join(
    REPO_ROOT,
    "data",
    "official",
    "dgca",
    "processed",
    "_".join(("vayu", "route", "basket", "2024", "25")) + ".csv",
)

GRAIN_A_PATH = os.path.join(OUTPUT_DIR, "phase10_route_series.csv")
PHASE10_COVERAGE_PATH = os.path.join(OUTPUT_DIR, "phase10_coverage_report.csv")

ROUND_INDEX_PATH = os.path.join(OUTPUT_DIR, "phase11_round_index.csv")
ROUTE_COMPONENTS_PATH = os.path.join(
    OUTPUT_DIR, "phase11_route_index_components.csv"
)
ITEM_RELATIVES_PATH = os.path.join(OUTPUT_DIR, "phase11_item_price_relatives.csv")
PERIOD_INDEX_PATH = os.path.join(OUTPUT_DIR, "phase11_period_index.csv")
INDEX_COVERAGE_PATH = os.path.join(
    OUTPUT_DIR, "phase11_index_coverage_report.csv"
)
INDEX_LINEAGE_PATH = os.path.join(OUTPUT_DIR, "phase11_index_lineage_map.csv")
UNALIGNED_PATH = os.path.join(
    OUTPUT_DIR, "phase11_unaligned_round_diagnostics.csv"
)
METHODOLOGY_PATH = os.path.join(DOCS_DIR, "index_methodology.md")

# Corpus anchors. These describe the CURRENT synthetic prototype corpus and
# are disclosure values, not official statistics.
EXPECTED_GRAIN_A_ROWS = 232
EXPECTED_GRAIN_A_OBSERVED = 219
EXPECTED_BASKET_ROUTES = 15
EXPECTED_ROUTES_REPRESENTED = 2
EXPECTED_NO_OBSERVATION_ROUTES = 13
EXPECTED_ANCHORED_ROUNDS = 9
EXPECTED_UNALIGNED_ROUNDS = 7
EXPECTED_CHAIN_LINKS = 8
EXPECTED_MATCHED_PER_LINK = (18, 19, 23, 25, 23, 18, 17, 16)
EXPECTED_MATCHED_TOTAL = 159
EXPECTED_BASE_ROUND_ID = "ROUND::2026-09-05T09:00"
EXPECTED_FINAL_ROUND_ID = "ROUND::2026-09-07T20:15"
EXPECTED_FINAL_LEVEL = "100.517647"
EXPECTED_COVERAGE_PCT = "27.3706"
EXPECTED_WEIGHT_REPRESENTED = "0.273706"
EXPECTED_ROUND_INDEX_ROWS = 18
EXPECTED_ROUTE_COMPONENT_ROWS = 32
EXPECTED_ITEM_RELATIVE_ROWS = 440
EXPECTED_PERIOD_INDEX_ROWS = 12
EXPECTED_INDEX_COVERAGE_ROWS = 270
EXPECTED_INDEX_LINEAGE_ROWS = 318
EXPECTED_UNALIGNED_ROWS = 7
EXPECTED_DAILY_PERIODS = 3
EXPECTED_WEEKLY_PERIODS = 2
EXPECTED_MONTHLY_PERIODS = 1

APPROVED_ELIGIBILITY_STATUSES = (
    R.ELIGIBILITY_ELIGIBLE,
    R.ELIGIBILITY_NO_OBSERVATIONS,
    R.ELIGIBILITY_NOT_PRICED,
    R.ELIGIBILITY_MISSING_FARE,
    R.ELIGIBILITY_UNPARSABLE_FARE,
    R.ELIGIBILITY_NON_POSITIVE_FARE,
    R.ELIGIBILITY_EXCLUDED_REVIEW_HIGH,
)

# Banned literals are assembled at runtime so that this verifier never itself
# contains the token it forbids.
FORBIDDEN_FIELD_TOKEN = "index" + "_eligible"
FLOAT_CALL_TOKEN = "float" + "("
RANDOM_IMPORT_TOKEN = "import " + "random"
NUMPY_RANDOM_TOKEN = "np" + ".random"
SKLEARN_TOKEN = "sk" + "learn"
ISOLATION_TOKEN = "Isolation" + "Forest"
XGBOOST_TOKEN = "xg" + "boost"
PANDAS_TOKEN = "import " + "pandas"
ITERTUPLES_TOKEN = "iter" + "tuples"
SOURCE_WEIGHT_TOKEN = "source" + "_weight"
EXPENDITURE_WEIGHT_TOKEN = "expenditure" + "_weight"
QUANTITY_WEIGHT_TOKEN = "quantity" + "_weight"

SOURCE_BANNED_TOKENS = (
    FLOAT_CALL_TOKEN,
    RANDOM_IMPORT_TOKEN,
    NUMPY_RANDOM_TOKEN,
    SKLEARN_TOKEN,
    ISOLATION_TOKEN,
    XGBOOST_TOKEN,
    PANDAS_TOKEN,
    ITERTUPLES_TOKEN,
)

PHASE11_SOURCE_FILES = (
    os.path.join(SRC_DIR, "__init__.py"),
    os.path.join(SRC_DIR, "rules.py"),
    os.path.join(SRC_DIR, "index_engine.py"),
    os.path.join(SCRIPTS_DIR, "run_index_engine.py"),
)

PHASE10_PROTECTED_FILES = (
    GRAIN_A_PATH,
    PHASE10_COVERAGE_PATH,
    os.path.join(OUTPUT_DIR, "phase10_route_class_round_series.csv"),
    os.path.join(OUTPUT_DIR, "phase10_route_crosswalk.csv"),
    os.path.join(OUTPUT_DIR, "phase10_route_lineage_map.csv"),
    os.path.join(OUTPUT_DIR, "phase10_off_basket_route_series.csv"),
    os.path.join(OUTPUT_DIR, "phase10_off_basket_route_class_round_series.csv"),
    BASKET_PATH,
)

PASSED = []
FAILED = []
CURRENT_SECTION = [""]


def section(title):
    CURRENT_SECTION[0] = title
    print("")
    print(title)
    print("-" * len(title))


def check(label, condition, detail=""):
    if condition:
        PASSED.append(label)
        print("  PASS  %s" % (label,))
    else:
        FAILED.append((CURRENT_SECTION[0], label, detail))
        print("  FAIL  %s%s" % (label, ("  [%s]" % (detail,)) if detail else ""))
    return condition


def read_rows(path):
    with open(path, "r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return (list(reader.fieldnames or []), [dict(item) for item in reader])


def sha256_of(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        digest.update(handle.read())
    return digest.hexdigest()


def read_text(path):
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


def decimal_of(text):
    return Decimal(str(text).strip())


def close_enough(left, right, tolerance):
    return abs(Decimal(left) - Decimal(right)) <= Decimal(tolerance)


def rows_for(rows, variant):
    return [record for record in rows if record["series_variant"] == variant]


def main():
    print("VAYU INDEX -- Phase 11 verifier")
    print("repository: %s" % (REPO_ROOT,))

    # -----------------------------------------------------------------
    section("1. Inputs, outputs and headers")
    # -----------------------------------------------------------------
    for path in (GRAIN_A_PATH, PHASE10_COVERAGE_PATH, BASKET_PATH):
        check("input present: %s" % (os.path.basename(path),), os.path.isfile(path))
    output_paths = (
        (ROUND_INDEX_PATH, engine.ROUND_INDEX_COLUMNS),
        (ROUTE_COMPONENTS_PATH, engine.ROUTE_COMPONENT_COLUMNS),
        (ITEM_RELATIVES_PATH, engine.ITEM_RELATIVE_COLUMNS),
        (PERIOD_INDEX_PATH, engine.PERIOD_INDEX_COLUMNS),
        (INDEX_COVERAGE_PATH, engine.INDEX_COVERAGE_COLUMNS),
        (INDEX_LINEAGE_PATH, engine.INDEX_LINEAGE_COLUMNS),
        (UNALIGNED_PATH, engine.UNALIGNED_DIAGNOSTIC_COLUMNS),
    )
    for path, columns in output_paths:
        name = os.path.basename(path)
        if not check("output present: %s" % (name,), os.path.isfile(path)):
            continue
        header, _rows = read_rows(path)
        check("header matches contract: %s" % (name,), header == list(columns))
        check(
            "no forbidden field in header: %s" % (name,),
            FORBIDDEN_FIELD_TOKEN not in header,
        )
        check(
            "schema version column present: %s" % (name,),
            "phase11_schema_version" in header,
        )
    check("methodology doc present", os.path.isfile(METHODOLOGY_PATH))

    # -----------------------------------------------------------------
    section("2. Locked inputs and Phase 10 contract")
    # -----------------------------------------------------------------
    basket = engine.load_basket(BASKET_PATH)
    check("basket carries 15 routes", len(basket) == EXPECTED_BASKET_ROUTES)
    weight_total = Decimal(0)
    for entry in basket:
        weight_total = weight_total + entry["traffic_weight"]
    check("basket weights sum to 1.000000", weight_total == Decimal("1.000000"))
    check(
        "basket file digest matches the locked Phase 5 value",
        sha256_of(BASKET_PATH) == R.BASKET_LOCKED_SHA256,
        sha256_of(BASKET_PATH),
    )
    check(
        "basket ranks are 1..15 exactly once",
        sorted(entry["basket_rank"] for entry in basket)
        == list(range(1, EXPECTED_BASKET_ROUTES + 1)),
    )

    phase10_coverage = engine.load_phase10_coverage(PHASE10_COVERAGE_PATH, basket)
    check(
        "phase10 coverage covers every basket route",
        len(phase10_coverage) == EXPECTED_BASKET_ROUTES,
    )
    no_observation_routes = [
        route_id
        for route_id in phase10_coverage
        if phase10_coverage[route_id] == R.COVERAGE_STATUS_NO_OBSERVATIONS
    ]
    check(
        "13 basket routes carry NO_OBSERVATIONS",
        len(no_observation_routes) == EXPECTED_NO_OBSERVATION_ROUTES,
        str(len(no_observation_routes)),
    )

    grain_a_records = engine.load_grain_a(GRAIN_A_PATH, basket)
    check("phase10 route series row count", len(grain_a_records) == EXPECTED_GRAIN_A_ROWS)
    observed = engine.observed_records(grain_a_records)
    check(
        "phase10 observed row count",
        len(observed) == EXPECTED_GRAIN_A_OBSERVED,
        str(len(observed)),
    )
    check(
        "every phase10 row carries the expected schema version",
        all(
            engine.text_of(entry, "phase10_schema_version")
            == R.PHASE10_SCHEMA_VERSION_EXPECTED
            for entry in grain_a_records
        ),
    )
    check(
        "no PRICED phase10 fare is zero, negative or unparsable",
        all(
            R.parse_decimal(engine.text_of(entry, "route_fare_median")) > 0
            for entry in observed
            if engine.text_of(entry, "route_price_state") == R.PRICE_STATE_PRICED
        ),
    )

    rounds = engine.collect_rounds(grain_a_records)
    anchored = engine.anchored_rounds(rounds)
    unaligned = engine.unaligned_rounds(rounds)
    check(
        "anchored round count",
        len(anchored) == EXPECTED_ANCHORED_ROUNDS,
        str(len(anchored)),
    )
    check(
        "unaligned round count",
        len(unaligned) == EXPECTED_UNALIGNED_ROUNDS,
        str(len(unaligned)),
    )
    check(
        "rounds are ordered by round_sort_key then round id",
        rounds
        == sorted(
            rounds,
            key=lambda entry: (
                entry["round_sort_key"],
                entry["collection_round_id"],
            ),
        ),
    )

    # -----------------------------------------------------------------
    section("3. Recomputation of every published table")
    # -----------------------------------------------------------------
    recomputed = engine.aggregate(grain_a_records, basket, phase10_coverage)
    tables = (
        ("phase11_round_index.csv", ROUND_INDEX_PATH, "round_index"),
        (
            "phase11_route_index_components.csv",
            ROUTE_COMPONENTS_PATH,
            "route_components",
        ),
        (
            "phase11_item_price_relatives.csv",
            ITEM_RELATIVES_PATH,
            "item_relatives",
        ),
        ("phase11_period_index.csv", PERIOD_INDEX_PATH, "period_index"),
        (
            "phase11_index_coverage_report.csv",
            INDEX_COVERAGE_PATH,
            "index_coverage",
        ),
        ("phase11_index_lineage_map.csv", INDEX_LINEAGE_PATH, "index_lineage"),
        (
            "phase11_unaligned_round_diagnostics.csv",
            UNALIGNED_PATH,
            "unaligned_diagnostics",
        ),
    )
    on_disk = {}
    for name, path, key in tables:
        _header, disk_rows = read_rows(path)
        on_disk[key] = disk_rows
        expected_rows = [
            {column: str(record[column]) for column in record}
            for record in recomputed[key]
        ]
        check(
            "row count matches recomputation: %s" % (name,),
            len(disk_rows) == len(expected_rows),
            "%d on disk vs %d recomputed" % (len(disk_rows), len(expected_rows)),
        )
        mismatches = 0
        for position in range(min(len(disk_rows), len(expected_rows))):
            if disk_rows[position] != expected_rows[position]:
                mismatches = mismatches + 1
        check(
            "every row matches recomputation: %s" % (name,),
            mismatches == 0,
            "%d mismatching row(s)" % (mismatches,),
        )

    check(
        "round index row count",
        len(on_disk["round_index"]) == EXPECTED_ROUND_INDEX_ROWS,
    )
    check(
        "route component row count",
        len(on_disk["route_components"]) == EXPECTED_ROUTE_COMPONENT_ROWS,
    )
    check(
        "item relative row count",
        len(on_disk["item_relatives"]) == EXPECTED_ITEM_RELATIVE_ROWS,
    )
    check(
        "period index row count",
        len(on_disk["period_index"]) == EXPECTED_PERIOD_INDEX_ROWS,
    )
    check(
        "index coverage row count",
        len(on_disk["index_coverage"]) == EXPECTED_INDEX_COVERAGE_ROWS,
    )
    check(
        "index lineage row count",
        len(on_disk["index_lineage"]) == EXPECTED_INDEX_LINEAGE_ROWS,
    )
    check(
        "unaligned diagnostics row count",
        len(on_disk["unaligned_diagnostics"]) == EXPECTED_UNALIGNED_ROWS,
    )

    # -----------------------------------------------------------------
    section("4. Determinism and input-order independence")
    # -----------------------------------------------------------------
    # A fixed, reproducible permutation: reverse, then rotate by a third.
    shuffled = list(reversed(grain_a_records))
    offset = len(shuffled) // 3
    shuffled = shuffled[offset:] + shuffled[:offset]
    check(
        "the permutation actually reorders the input",
        shuffled != grain_a_records,
    )
    reordered = engine.aggregate(shuffled, basket, phase10_coverage)
    for _name, _path, key in tables:
        check(
            "output is input-order independent: %s" % (key,),
            reordered[key] == recomputed[key],
        )
    reversed_basket = list(reversed(basket))
    basket_reordered = engine.aggregate(
        grain_a_records, reversed_basket, phase10_coverage
    )
    check(
        "output is independent of basket row order",
        basket_reordered["round_index"] == recomputed["round_index"],
    )


    # -----------------------------------------------------------------
    section("5. D3 chaining: relatives, factors and levels")
    # -----------------------------------------------------------------
    round_rows = on_disk["round_index"]
    component_rows = on_disk["route_components"]
    relative_rows = on_disk["item_relatives"]
    coverage_rows = on_disk["index_coverage"]
    for variant in R.SERIES_VARIANTS:
        variant_rows = rows_for(round_rows, variant)
        label = variant.lower()
        check(
            "%s: one published row per anchored round" % (label,),
            len(variant_rows) == EXPECTED_ANCHORED_ROUNDS,
            str(len(variant_rows)),
        )
        check(
            "%s: link sequence is 0..8 in order" % (label,),
            [int(record["link_sequence"]) for record in variant_rows]
            == list(range(EXPECTED_CHAIN_LINKS + 1)),
        )
        check(
            "%s: every published round is anchored" % (label,),
            all(
                record["round_alignment"] == R.ROUND_ALIGNMENT_ANCHORED
                for record in variant_rows
            ),
        )
        base = variant_rows[0]
        check(
            "%s: base level is 100.000000" % (label,),
            base["index_level"] == "100.000000",
            base["index_level"],
        )
        check(
            "%s: base round is the first anchored round" % (label,),
            base["collection_round_id"] == EXPECTED_BASE_ROUND_ID,
        )
        check(
            "%s: base round carries no chain factor and no link id" % (label,),
            base["chain_factor"] == "" and base["link_id"] == "",
        )
        check(
            "%s: base round carries no change percentage" % (label,),
            base["index_change_pct_vs_prev_round"] == "",
        )
        check(
            "%s: base round is flagged as the base period" % (label,),
            base["is_base_period"] == "True",
        )
        check(
            "%s: only the base round is flagged as base" % (label,),
            [record["is_base_period"] for record in variant_rows[1:]]
            == ["False"] * EXPECTED_CHAIN_LINKS,
        )
        check(
            "%s: every round declares the published base level" % (label,),
            all(
                record["index_base_level"] == "100.000000"
                for record in variant_rows
            ),
        )
        check(
            "%s: every link carries an 8dp chain factor" % (label,),
            all(
                len(record["chain_factor"].split(".")[1])
                == R.CHAIN_FACTOR_DECIMAL_PLACES
                for record in variant_rows[1:]
            ),
        )
        check(
            "%s: every level carries 6 decimal places" % (label,),
            all(
                len(record["index_level"].split(".")[1])
                == R.INDEX_LEVEL_DECIMAL_PLACES
                for record in variant_rows
            ),
        )
        check(
            "%s: every link names its previous round" % (label,),
            all(
                record["prev_round_id"]
                == variant_rows[position - 1]["collection_round_id"]
                for position, record in enumerate(variant_rows)
                if position >= 1
            ),
        )
        levels_ok = True
        change_ok = True
        for position in range(1, len(variant_rows)):
            previous = decimal_of(variant_rows[position - 1]["index_level"])
            factor = decimal_of(variant_rows[position]["chain_factor"])
            published = decimal_of(variant_rows[position]["index_level"])
            with localcontext() as context:
                context.prec = R.INTERNAL_PRECISION
                product = +(previous * factor)
            if not close_enough(published, product, "0.000001"):
                levels_ok = False
            expected_change = R.percent_change(published, previous)
            if not close_enough(
                decimal_of(
                    variant_rows[position]["index_change_pct_vs_prev_round"]
                ),
                expected_change,
                "0.0001",
            ):
                change_ok = False
        check(
            "%s: I_t equals I_(t-1) times J_t at published precision" % (label,),
            levels_ok,
        )
        check("%s: round-on-round change reconciles" % (label,), change_ok)
        check(
            "%s: every round names the chained weighted Jevons statistic"
            % (label,),
            all(
                record["aggregation_statistic"] == R.AGGREGATION_STATISTIC
                for record in variant_rows
            ),
        )
        check(
            "%s: every round names the elementary Jevons statistic" % (label,),
            all(
                record["elementary_aggregation_statistic"]
                == R.ELEMENTARY_AGGREGATION_STATISTIC
                for record in variant_rows
            ),
        )
        check(
            "%s: every round names its inclusion rule id" % (label,),
            all(
                record[R.INCLUSION_RULE_FIELD_NAME]
                == R.INDEX_INCLUSION_RULE_ID[variant]
                for record in variant_rows
            ),
        )

    primary_rounds = rows_for(round_rows, R.SERIES_VARIANT_PRIMARY)
    check(
        "primary matched products per link",
        tuple(
            int(record["matched_product_count"]) for record in primary_rounds[1:]
        )
        == EXPECTED_MATCHED_PER_LINK,
        str([record["matched_product_count"] for record in primary_rounds[1:]]),
    )
    check(
        "primary final round id",
        primary_rounds[-1]["collection_round_id"] == EXPECTED_FINAL_ROUND_ID,
    )
    check(
        "primary final index level",
        primary_rounds[-1]["index_level"] == EXPECTED_FINAL_LEVEL,
        primary_rounds[-1]["index_level"],
    )

    # -----------------------------------------------------------------
    section("6. D4 weights: route level, renormalized per link")
    # -----------------------------------------------------------------
    basket_weights = {
        entry["route_id"]: entry["traffic_weight"] for entry in basket
    }
    weight_sums = {}
    for record in component_rows:
        key = (record["series_variant"], int(record["link_sequence"]))
        weight_sums.setdefault(key, Decimal(0))
        weight_sums[key] = weight_sums[key] + decimal_of(
            record["renormalized_weight"]
        )
    check(
        "renormalized weights sum to 1 on every link",
        all(
            close_enough(total, Decimal(1), "0.000000001")
            for total in weight_sums.values()
        ),
    )
    check(
        "every component carries the unnormalized Phase 5 traffic weight",
        all(
            decimal_of(record["traffic_weight"])
            == basket_weights[record["route_id"]]
            for record in component_rows
        ),
    )
    renormalization_ok = True
    for record in component_rows:
        key = (record["series_variant"], int(record["link_sequence"]))
        contributing = [
            other
            for other in component_rows
            if (other["series_variant"], int(other["link_sequence"])) == key
        ]
        denominator = Decimal(0)
        for other in contributing:
            denominator = denominator + basket_weights[other["route_id"]]
        with localcontext() as context:
            context.prec = R.INTERNAL_PRECISION
            expected = +(basket_weights[record["route_id"]] / denominator)
        if not close_enough(
            decimal_of(record["renormalized_weight"]),
            expected,
            "0.000000000001",
        ):
            renormalization_ok = False
    check(
        "w_tilde equals w_r divided by the contributing weight sum",
        renormalization_ok,
    )
    check(
        "components never publish a source, expenditure or quantity weight",
        all(
            token not in engine.ROUTE_COMPONENT_COLUMNS
            for token in (
                SOURCE_WEIGHT_TOKEN,
                EXPENDITURE_WEIGHT_TOKEN,
                QUANTITY_WEIGHT_TOKEN,
            )
        ),
    )
    check(
        "weights are applied to log relatives, never to price levels",
        R.WEIGHT_APPLICATION
        == "APPLIED_TO_LOG_PRICE_RELATIVES_NEVER_TO_PRICE_LEVELS"
        and all(
            record["weight_application"] == R.WEIGHT_APPLICATION
            for record in round_rows
        ),
    )
    check(
        "within-route weighting is equal per matched item",
        R.WITHIN_ROUTE_WEIGHTING == "EQUAL_WEIGHT_PER_MATCHED_ITEM"
        and all(
            record["within_route_weighting"] == R.WITHIN_ROUTE_WEIGHTING
            for record in component_rows
        ),
    )
    check(
        "the weight basis names conservative bidirectional DGCA traffic",
        all(record["weight_basis"] == R.WEIGHT_BASIS for record in round_rows),
    )
    check(
        "the fare value is never used as a weight",
        R.USES_FARE_VALUE_AS_WEIGHT is False,
    )

    elementary_ok = True
    counts_reconcile = True
    for record in component_rows:
        matched = [
            other
            for other in relative_rows
            if other["series_variant"] == record["series_variant"]
            and other["link_sequence"] == record["link_sequence"]
            and other["route_id"] == record["route_id"]
            and other["item_status"] == R.ITEM_STATUS_MATCHED
        ]
        if len(matched) != int(record["matched_product_count"]):
            counts_reconcile = False
            continue
        expected = R.elementary_jevons(
            [decimal_of(other["price_relative"]) for other in matched]
        )
        if not close_enough(
            decimal_of(record["route_elementary_jevons"]),
            expected,
            "0.00000001",
        ):
            elementary_ok = False
    check(
        "per-route elementary Jevons equals the geometric mean of its relatives",
        elementary_ok,
    )
    check(
        "component matched counts reconcile with the relative table",
        counts_reconcile,
    )
    aggregate_ok = True
    contribution_ok = True
    for variant in R.SERIES_VARIANTS:
        for position in range(1, EXPECTED_CHAIN_LINKS + 1):
            components = [
                record
                for record in component_rows
                if record["series_variant"] == variant
                and int(record["link_sequence"]) == position
            ]
            published = decimal_of(
                [
                    record["chain_factor"]
                    for record in rows_for(round_rows, variant)
                    if int(record["link_sequence"]) == position
                ][0]
            )
            triples = [
                (
                    record["route_id"],
                    decimal_of(record["renormalized_weight"]),
                    decimal_of(record["route_elementary_jevons"]),
                )
                for record in components
            ]
            if not close_enough(
                published, R.weighted_jevons(triples), "0.00000001"
            ):
                aggregate_ok = False
            total = Decimal(0)
            for record in components:
                total = total + decimal_of(record["weighted_log_contribution"])
            if not close_enough(
                total, R.natural_log(published), "0.00000001"
            ):
                contribution_ok = False
    check(
        "chain factor equals the weighted Jevons of the route elementaries",
        aggregate_ok,
    )
    check(
        "weighted log contributions sum to the log of the chain factor",
        contribution_ok,
    )
    check(
        "every component route log relative matches its elementary Jevons",
        all(
            close_enough(
                decimal_of(record["route_log_relative"]),
                R.natural_log(decimal_of(record["route_elementary_jevons"])),
                "0.00000001",
            )
            for record in component_rows
        ),
    )

    # -----------------------------------------------------------------
    section("7. D5 coverage disclosure (no threshold, no suppression)")
    # -----------------------------------------------------------------
    check(
        "engine applies no coverage threshold",
        R.APPLIES_COVERAGE_THRESHOLD is False
        and R.MINIMUM_COVERAGE_THRESHOLD is None,
    )
    check(
        "engine never suppresses a round automatically",
        R.SUPPRESSES_INDEX_AUTOMATICALLY is False,
    )
    disclosure_columns = (
        "basket_routes_represented",
        "basket_routes_total",
        "basket_weight_represented",
        "basket_coverage_pct",
        "effective_weight_sum",
        "renormalization_applied",
        "coverage_status",
    )
    for column in disclosure_columns:
        check(
            "every round discloses %s" % (column,),
            all(record[column] != "" for record in round_rows),
        )
    check(
        "routes represented is 2 on every round",
        all(
            int(record["basket_routes_represented"])
            == EXPECTED_ROUTES_REPRESENTED
            for record in round_rows
        ),
    )
    check(
        "routes total is 15 on every round",
        all(
            int(record["basket_routes_total"]) == EXPECTED_BASKET_ROUTES
            for record in round_rows
        ),
    )
    check(
        "basket weight represented is the unnormalized 0.273706",
        all(
            decimal_of(record["basket_weight_represented"])
            == decimal_of(EXPECTED_WEIGHT_REPRESENTED)
            for record in round_rows
        ),
        round_rows[0]["basket_weight_represented"],
    )
    check(
        "basket coverage percentage is 27.3706",
        all(
            record["basket_coverage_pct"] == EXPECTED_COVERAGE_PCT
            for record in round_rows
        ),
    )
    check(
        "effective weight sum is exactly 1.000000",
        all(
            record["effective_weight_sum"] == "1.000000"
            for record in round_rows
        ),
    )
    check(
        "renormalization is disclosed as applied",
        all(
            record["renormalization_applied"] == "True"
            for record in round_rows
        ),
    )
    check(
        "coverage status is PARTIAL_COVERAGE_PROTOTYPE on every round",
        all(
            record["coverage_status"] == R.COVERAGE_STATUS_PARTIAL
            for record in round_rows
        ),
    )
    check(
        "missing basket weight is disclosed, never redistributed",
        R.REDISTRIBUTES_MISSING_ROUTE_WEIGHT is False
        and all(
            close_enough(
                decimal_of(record["basket_weight_represented"])
                + decimal_of(record["basket_weight_missing"]),
                Decimal("1.000000"),
                "0.000000000001",
            )
            for record in round_rows
        ),
    )
    for variant in R.SERIES_VARIANTS:
        variant_coverage = rows_for(coverage_rows, variant)
        check(
            "%s: coverage report covers 15 routes on every round"
            % (variant.lower(),),
            len(variant_coverage)
            == EXPECTED_ANCHORED_ROUNDS * EXPECTED_BASKET_ROUTES,
            str(len(variant_coverage)),
        )
    grouped_coverage = {}
    for record in coverage_rows:
        key = (record["series_variant"], record["collection_round_id"])
        grouped_coverage.setdefault(key, []).append(record)
    coverage_ok = True
    excluded_ok = True
    for key in grouped_coverage:
        entries = grouped_coverage[key]
        if sorted(record["route_id"] for record in entries) != sorted(
            basket_weights
        ):
            coverage_ok = False
        contributed = [
            record
            for record in entries
            if record["contributed_to_index"] == "True"
        ]
        if len(contributed) != EXPECTED_ROUTES_REPRESENTED:
            coverage_ok = False
        total_represented = Decimal(0)
        for record in contributed:
            total_represented = total_represented + decimal_of(
                record["weight_represented"]
            )
        if not close_enough(
            total_represented,
            decimal_of(EXPECTED_WEIGHT_REPRESENTED),
            "0.000000000001",
        ):
            coverage_ok = False
        for record in entries:
            if record["contributed_to_index"] == "True":
                if record["weight_excluded"] != "":
                    excluded_ok = False
            else:
                if (
                    record["weight_excluded"] == ""
                    or record["renormalized_weight"] != ""
                ):
                    excluded_ok = False
    check("every round lists all 15 basket routes exactly once", coverage_ok)
    check(
        "non-contributing routes disclose excluded weight and no renormalized weight",
        excluded_ok,
    )
    check(
        "the 13 unobserved routes are disclosed as NO_OBSERVATIONS, never dropped",
        all(
            record["coverage_contribution_status"] == R.COVERAGE_NOT_OBSERVED
            for record in coverage_rows
            if record["route_id"] in no_observation_routes
        )
        and len(
            [
                record
                for record in rows_for(coverage_rows, R.SERIES_VARIANT_PRIMARY)
                if record["coverage_contribution_status"]
                == R.COVERAGE_NOT_OBSERVED
            ]
        )
        == EXPECTED_ANCHORED_ROUNDS * EXPECTED_NO_OBSERVATION_ROUTES,
    )

    # -----------------------------------------------------------------
    section("8. D1/D6 item identity, matching and eligibility")
    # -----------------------------------------------------------------
    check(
        "elementary item key is the locked 4-tuple",
        R.ITEM_KEY_FIELDS
        == ("route_id", "fare_class", "advance_purchase_window", "travel_date"),
    )
    identity_ok = True
    for record in relative_rows:
        expected_id = R.item_id(
            (
                record["route_id"],
                record["fare_class"],
                record["advance_purchase_window"],
                record["travel_date"],
            )
        )
        if record["item_id"] != expected_id:
            identity_ok = False
    check("every item id is built from the 4-tuple only", identity_ok)
    check(
        "travel_date is part of item identity and never collapsed",
        all(record["travel_date"] != "" for record in relative_rows),
    )
    check(
        "fare classes are never substituted for one another",
        R.SUBSTITUTES_FARE_CLASSES is False,
    )
    check(
        "advance purchase windows are never substituted",
        R.SUBSTITUTES_ADVANCE_PURCHASE_WINDOWS is False,
    )

    matched_rows = [
        record
        for record in relative_rows
        if record["item_status"] == R.ITEM_STATUS_MATCHED
    ]
    entering_rows = [
        record
        for record in relative_rows
        if record["item_status"] == R.ITEM_STATUS_ENTERING
    ]
    leaving_rows = [
        record
        for record in relative_rows
        if record["item_status"] == R.ITEM_STATUS_LEAVING
    ]
    check(
        "primary matched relative count",
        len(
            [
                record
                for record in matched_rows
                if record["series_variant"] == R.SERIES_VARIANT_PRIMARY
            ]
        )
        == EXPECTED_MATCHED_TOTAL,
    )
    relative_ok = True
    for record in matched_rows:
        expected = R.price_relative(
            decimal_of(record["curr_fare"]), decimal_of(record["prev_fare"])
        )
        if not close_enough(
            decimal_of(record["price_relative"]), expected, "0.00000001"
        ):
            relative_ok = False
    check(
        "price relative is current divided by previous, never inverted",
        relative_ok,
    )
    check(
        "a rising fare produces a relative above one",
        all(
            decimal_of(record["price_relative"]) > 1
            for record in matched_rows
            if decimal_of(record["curr_fare"]) > decimal_of(record["prev_fare"])
        ),
    )
    check(
        "a falling fare produces a relative below one",
        all(
            decimal_of(record["price_relative"]) < 1
            for record in matched_rows
            if decimal_of(record["curr_fare"]) < decimal_of(record["prev_fare"])
        ),
    )
    check(
        "only matched items carry both fares",
        all(
            record["prev_fare"] != "" and record["curr_fare"] != ""
            for record in matched_rows
        ),
    )
    check(
        "entering items carry no previous fare and no relative",
        all(
            record["prev_fare"] == "" and record["price_relative"] == ""
            for record in entering_rows
        ),
    )
    check(
        "leaving items carry no current fare and no relative",
        all(
            record["curr_fare"] == "" and record["price_relative"] == ""
            for record in leaving_rows
        ),
    )
    check(
        "entering and leaving items state why they carry no relative",
        all(
            record["exclusion_reason"] != ""
            for record in entering_rows + leaving_rows
        ),
    )
    check(
        "entering and leaving items never contribute to a chain factor",
        not (
            {
                (
                    record["series_variant"],
                    record["link_sequence"],
                    record["item_id"],
                )
                for record in entering_rows + leaving_rows
            }
            & {
                (
                    record["series_variant"],
                    record["link_sequence"],
                    record["item_id"],
                )
                for record in on_disk["index_lineage"]
            }
        ),
    )
    counts_ok = True
    for variant in R.SERIES_VARIANTS:
        for record in rows_for(round_rows, variant)[1:]:
            sequence = record["link_sequence"]
            matched = len(
                [
                    other
                    for other in matched_rows
                    if other["series_variant"] == variant
                    and other["link_sequence"] == sequence
                ]
            )
            entering = len(
                [
                    other
                    for other in entering_rows
                    if other["series_variant"] == variant
                    and other["link_sequence"] == sequence
                ]
            )
            leaving = len(
                [
                    other
                    for other in leaving_rows
                    if other["series_variant"] == variant
                    and other["link_sequence"] == sequence
                ]
            )
            if matched != int(record["matched_product_count"]):
                counts_ok = False
            if entering != int(record["entering_product_count"]):
                counts_ok = False
            if leaving != int(record["leaving_product_count"]):
                counts_ok = False
            if int(record["missing_product_count"]) != entering + leaving:
                counts_ok = False
    check(
        "matched, entering and leaving counts reconcile with the round table",
        counts_ok,
    )
    check(
        "no imputation, carry-forward, interpolation or zero substitution",
        R.USES_IMPUTATION is False
        and R.USES_CARRY_FORWARD is False
        and R.USES_PRICE_INTERPOLATION is False
        and R.USES_ZERO_SUBSTITUTION is False,
    )
    check(
        "no published fare or relative is zero",
        all(
            decimal_of(record["price_relative"]) != 0
            and decimal_of(record["prev_fare"]) != 0
            and decimal_of(record["curr_fare"]) != 0
            for record in matched_rows
        ),
    )

    # D6: severity never drives the headline series.
    check(
        "severity does not determine the primary series",
        R.SEVERITY_DETERMINES_PRIMARY_SERIES is False,
    )
    check(
        "primary inclusion rule text names severity-independent inclusion",
        "regardless"
        in R.INDEX_INCLUSION_RULE_TEXT[
            R.INDEX_INCLUSION_RULE_ID[R.SERIES_VARIANT_PRIMARY]
        ].lower(),
    )
    primary_severity_total = 0
    for record in rows_for(round_rows, R.SERIES_VARIANT_PRIMARY):
        primary_severity_total = primary_severity_total + int(
            record["anomaly_excluded_product_count"]
        )
    check(
        "primary series excludes nothing for anomaly severity",
        primary_severity_total == 0,
        str(primary_severity_total),
    )
    check(
        "every eligibility status uses the approved vocabulary",
        all(
            record[R.ELIGIBILITY_FIELD_NAME] in APPROVED_ELIGIBILITY_STATUSES
            for record in relative_rows
        ),
    )
    check(
        "structural ineligibility reasons are the only exclusion reasons",
        all(
            record[R.ELIGIBILITY_FIELD_NAME]
            in (R.ELIGIBILITY_ELIGIBLE, R.ELIGIBILITY_EXCLUDED_REVIEW_HIGH)
            for record in relative_rows
        ),
    )
    check(
        "the sensitivity variant is named EXCL_REVIEW_HIGH",
        R.SERIES_VARIANTS == ("PRIMARY", "EXCL_REVIEW_HIGH"),
    )
    check(
        "the sensitivity variant excludes REVIEW and HIGH severities",
        R.SENSITIVITY_EXCLUDED_SEVERITIES == ("REVIEW", "HIGH"),
    )
    check(
        "both variants are published as separate series ids",
        len({R.INDEX_SERIES_ID[variant] for variant in R.SERIES_VARIANTS}) == 2,
    )

    # -----------------------------------------------------------------
    section("9. D2 anchored-only chaining and unaligned diagnostics")
    # -----------------------------------------------------------------
    check(
        "only anchored rounds are chain eligible",
        R.CHAIN_ELIGIBLE_ALIGNMENTS == (R.ROUND_ALIGNMENT_ANCHORED,),
    )
    anchored_ids = {entry["collection_round_id"] for entry in anchored}
    unaligned_ids = {entry["collection_round_id"] for entry in unaligned}
    check(
        "no unaligned round appears in the round index",
        not any(
            record["collection_round_id"] in unaligned_ids for record in round_rows
        ),
    )
    check(
        "no unaligned round appears in the lineage map",
        not any(
            record["prev_round_id"] in unaligned_ids
            or record["curr_round_id"] in unaligned_ids
            for record in on_disk["index_lineage"]
        ),
    )
    unaligned_diagnostics = on_disk["unaligned_diagnostics"]
    check(
        "all 7 unaligned rounds are published as diagnostics",
        len(unaligned_diagnostics) == EXPECTED_UNALIGNED_ROWS
        and {record["collection_round_id"] for record in unaligned_diagnostics}
        == unaligned_ids,
    )
    check(
        "every diagnostic round is marked not chain eligible",
        all(
            record["chain_eligible"] == "False"
            and record["excluded_from_chain_reason"] == R.UNALIGNED_EXCLUSION_REASON
            for record in unaligned_diagnostics
        ),
    )
    check(
        "every diagnostic round names its nearest anchored round",
        all(
            record["nearest_anchored_round_id"] in anchored_ids
            and record["minutes_to_nearest_anchored_round"] != ""
            for record in unaligned_diagnostics
        ),
    )
    check(
        "anchor configuration is labelled prototype calibration",
        R.ANCHOR_CONFIGURATION_STATUS == "PROTOTYPE_CALIBRATION",
    )

    # -----------------------------------------------------------------
    section("10. D7 period derivation")
    # -----------------------------------------------------------------
    period_rows = on_disk["period_index"]
    for variant in R.SERIES_VARIANTS:
        variant_periods = rows_for(period_rows, variant)
        grain_counts = {}
        for record in variant_periods:
            grain_counts[record["period_grain"]] = (
                grain_counts.get(record["period_grain"], 0) + 1
            )
        check(
            "%s: daily periods" % (variant.lower(),),
            grain_counts.get("DAILY") == EXPECTED_DAILY_PERIODS,
        )
        check(
            "%s: weekly periods" % (variant.lower(),),
            grain_counts.get("WEEKLY") == EXPECTED_WEEKLY_PERIODS,
        )
        check(
            "%s: monthly periods" % (variant.lower(),),
            grain_counts.get("MONTHLY") == EXPECTED_MONTHLY_PERIODS,
        )
    check(
        "every period row is derived from the round-level chain",
        all(
            record["derivation_rule"] == "DERIVED_FROM_ROUND_LEVEL_CHAIN"
            for record in period_rows
        ),
    )
    check(
        "period primary measure is the period-end chain level",
        all(
            record["period_primary_measure"] == R.PERIOD_PRIMARY_MEASURE
            for record in period_rows
        ),
    )
    check(
        "period average is explicitly labelled non chain consistent",
        all(
            record["period_average_is_chain_consistent"] == "False"
            for record in period_rows
        ),
    )
    level_by_round = {}
    for record in round_rows:
        level_by_round[
            (record["series_variant"], record["collection_round_id"])
        ] = record["index_level"]
    check(
        "every period-end level is an actual round level on the chain",
        all(
            level_by_round[
                (record["series_variant"], record["period_end_round_id"])
            ]
            == record["period_end_index_level"]
            for record in period_rows
        ),
    )
    monthly = [
        record
        for record in rows_for(period_rows, R.SERIES_VARIANT_PRIMARY)
        if record["period_grain"] == "MONTHLY"
    ]
    check(
        "the monthly period-end level equals the final round level",
        monthly[-1]["period_end_index_level"] == EXPECTED_FINAL_LEVEL,
    )
    check(
        "partial periods are flagged rather than silently completed",
        all(
            record["period_is_partial"]
            == (
                "True"
                if int(record["round_count"]) < int(record["expected_round_count"])
                else "False"
            )
            for record in period_rows
        ),
    )
    check(
        "weekly and monthly prototype periods are flagged partial",
        all(
            record["period_is_partial"] == "True"
            for record in period_rows
            if record["period_grain"] in ("WEEKLY", "MONTHLY")
        ),
    )

    # -----------------------------------------------------------------
    section("11. D8 precision and rebasing")
    # -----------------------------------------------------------------
    check("internal precision is 28", R.INTERNAL_PRECISION == 28)
    check("rounding mode is ROUND_HALF_UP", R.ROUNDING_MODE_NAME == "ROUND_HALF_UP")
    check(
        "index levels are published at 6 decimal places",
        R.INDEX_LEVEL_DECIMAL_PLACES == 6,
    )
    check(
        "chain factors are published at 8 decimal places",
        R.CHAIN_FACTOR_DECIMAL_PLACES == 8,
    )
    rebased = engine.rebase_round_index(
        recomputed, R.SERIES_VARIANT_PRIMARY, EXPECTED_FINAL_ROUND_ID
    )
    rebased_levels = dict(rebased)
    check(
        "rebasing sets the new base round to exactly 100.000000",
        rebased_levels[EXPECTED_FINAL_ROUND_ID] == Decimal("100.000000"),
        str(rebased_levels[EXPECTED_FINAL_ROUND_ID]),
    )
    original = recomputed["chains"][R.SERIES_VARIANT_PRIMARY]["levels"]
    original_levels = dict(original)
    # Relative preservation is an exact property of the UNROUNDED rebased
    # series. Publishing quantizes to 6 dp, so the exactness check runs on
    # the unrounded levels and the published series is checked separately at
    # publication tolerance.
    unrounded_rebased = dict(
        R.rebase_levels(original, EXPECTED_FINAL_ROUND_ID)
    )
    ratios_ok = True
    published_ratios_ok = True
    ordered_ids = [round_id for round_id, _level in original]
    for position in range(1, len(ordered_ids)):
        previous_id = ordered_ids[position - 1]
        current_id = ordered_ids[position]
        with localcontext() as context:
            context.prec = R.INTERNAL_PRECISION
            before = +(
                original_levels[current_id] / original_levels[previous_id]
            )
            after = +(
                unrounded_rebased[current_id]
                / unrounded_rebased[previous_id]
            )
            published_after = +(
                rebased_levels[current_id] / rebased_levels[previous_id]
            )
        if not close_enough(before, after, "0.000000000000000001"):
            ratios_ok = False
        if not close_enough(before, published_after, "0.0000001"):
            published_ratios_ok = False
    check(
        "rebasing preserves every adjacent price relative exactly",
        ratios_ok,
    )
    check(
        "the published rebased series preserves relatives at 6dp precision",
        published_ratios_ok,
    )
    check(
        "rebasing does not change the published original chain",
        dict(
            engine.rebase_round_index(
                recomputed, R.SERIES_VARIANT_PRIMARY, EXPECTED_BASE_ROUND_ID
            )
        )[EXPECTED_FINAL_ROUND_ID]
        == Decimal(EXPECTED_FINAL_LEVEL),
    )

    # -----------------------------------------------------------------
    section("12. D9/D10 basket scope and grain discipline")
    # -----------------------------------------------------------------
    check(
        "only basket routes appear in the index tables",
        all(record["route_id"] in basket_weights for record in component_rows)
        and all(record["route_id"] in basket_weights for record in relative_rows)
        and all(
            record["route_id"] in basket_weights
            for record in on_disk["index_lineage"]
        ),
    )
    check(
        "off-basket routes never reach the headline index",
        R.USES_OFF_BASKET_ROUTES_IN_HEADLINE is False
        and not any(
            record["route_id"] in ("BLR-HYD", "CCU-MAA")
            for record in component_rows + relative_rows
        ),
    )
    check(
        "grain B is never used as an index input",
        R.USES_GRAIN_B_AS_INDEX_INPUT is False,
    )
    engine_source = read_text(os.path.join(SRC_DIR, "index_engine.py"))
    runner_source = read_text(os.path.join(SCRIPTS_DIR, "run_index_engine.py"))
    check(
        "the engine never reads the grain B or off-basket tables",
        "phase10_route_class_round_series" not in engine_source
        and "phase10_off_basket" not in engine_source
        and "phase10_route_class_round_series" not in runner_source
        and "phase10_off_basket" not in runner_source,
    )
    check(
        "route aggregation is not reimplemented in Phase 11",
        "route_fare_median" in engine_source
        and "median(" not in engine_source,
    )
    check(
        "the engine reuses the Phase 10 route_id source of truth",
        R.ROUTE_ID_SOURCE_OF_TRUTH.endswith("make_route_id"),
    )

    # -----------------------------------------------------------------
    section("13. D11 field vocabulary and forbidden fields")
    # -----------------------------------------------------------------
    check(
        "eligibility field is index_eligibility_status",
        R.ELIGIBILITY_FIELD_NAME == "index_eligibility_status",
    )
    check(
        "inclusion rule field is index_inclusion_rule_id",
        R.INCLUSION_RULE_FIELD_NAME == "index_inclusion_rule_id",
    )
    check(
        "the forbidden field name is declared forbidden",
        FORBIDDEN_FIELD_TOKEN in R.FORBIDDEN_OUTPUT_FIELDS,
    )
    forbidden_in_output = []
    for _name, path, _key in tables:
        header, _rows = read_rows(path)
        for column in header:
            if column in R.FORBIDDEN_OUTPUT_FIELDS:
                forbidden_in_output.append((os.path.basename(path), column))
    check(
        "no output table publishes a forbidden field",
        not forbidden_in_output,
        str(forbidden_in_output),
    )
    text_hits = []
    for _name, path, _key in tables:
        if FORBIDDEN_FIELD_TOKEN in read_text(path):
            text_hits.append(os.path.basename(path))
    check(
        "the forbidden field name appears nowhere in the output text",
        not text_hits,
        str(text_hits),
    )
    check(
        "both inclusion rule ids are published",
        {record[R.INCLUSION_RULE_FIELD_NAME] for record in round_rows}
        == {R.INDEX_INCLUSION_RULE_ID[variant] for variant in R.SERIES_VARIANTS},
    )

    # -----------------------------------------------------------------
    section("14. Lineage reconciliation")
    # -----------------------------------------------------------------
    lineage_rows = on_disk["index_lineage"]
    check(
        "primary lineage row count equals the matched relative count",
        len(rows_for(lineage_rows, R.SERIES_VARIANT_PRIMARY))
        == EXPECTED_MATCHED_TOTAL,
    )
    lineage_keys = {
        (
            record["series_variant"],
            record["link_sequence"],
            record["route_id"],
            record["fare_class"],
            record["advance_purchase_window"],
            record["travel_date"],
        )
        for record in lineage_rows
    }
    matched_keys = {
        (
            record["series_variant"],
            record["link_sequence"],
            record["route_id"],
            record["fare_class"],
            record["advance_purchase_window"],
            record["travel_date"],
        )
        for record in matched_rows
    }
    check(
        "every matched relative has exactly one lineage row",
        lineage_keys == matched_keys
        and len(lineage_keys) == len(lineage_rows) // len(R.SERIES_VARIANTS) * len(
            R.SERIES_VARIANTS
        ),
    )
    phase10_fares = {}
    phase10_observations = {}
    for entry in observed:
        key = (
            engine.text_of(entry, "collection_round_id"),
            engine.text_of(entry, "route_id"),
            engine.text_of(entry, "fare_class"),
            engine.text_of(entry, "advance_purchase_window"),
            engine.text_of(entry, "travel_date"),
        )
        phase10_fares[key] = engine.text_of(entry, "route_fare_median")
        phase10_observations[key] = engine.text_of(
            entry, "contributing_observation_ids"
        )
    fares_ok = True
    observations_ok = True
    for record in lineage_rows:
        previous_key = (
            record["prev_round_id"],
            record["route_id"],
            record["fare_class"],
            record["advance_purchase_window"],
            record["travel_date"],
        )
        current_key = (
            record["curr_round_id"],
            record["route_id"],
            record["fare_class"],
            record["advance_purchase_window"],
            record["travel_date"],
        )
        if decimal_of(record["prev_fare"]) != decimal_of(
            phase10_fares[previous_key]
        ):
            fares_ok = False
        if decimal_of(record["curr_fare"]) != decimal_of(
            phase10_fares[current_key]
        ):
            fares_ok = False
        if record["prev_contributing_observation_ids"] == "":
            observations_ok = False
        if record["curr_contributing_observation_ids"] == "":
            observations_ok = False
    check("every lineage fare traces back to a Phase 10 row", fares_ok)
    check(
        "every lineage row carries Phase 10 contributing observation ids",
        observations_ok,
    )
    check(
        "published fares keep 2 decimal places",
        all(
            len(record["curr_fare"].split(".")[1]) == R.MONEY_DECIMAL_PLACES
            for record in lineage_rows
        ),
    )
    contribution_totals = {}
    for record in lineage_rows:
        key = (record["series_variant"], record["link_sequence"])
        contribution_totals.setdefault(key, Decimal(0))
        contribution_totals[key] = contribution_totals[key] + decimal_of(
            record["contribution_weight"]
        )
    check(
        "lineage contribution weights sum to 1 on every link",
        all(
            close_enough(total, Decimal(1), "0.000000001")
            for total in contribution_totals.values()
        ),
    )
    check(
        "every lineage row names its link id",
        all(
            record["link_id"].startswith(R.LINK_ID_PREFIX)
            for record in lineage_rows
        ),
    )

    # -----------------------------------------------------------------
    section("15. Deterministic ordering of every table")
    # -----------------------------------------------------------------
    # The engine's declared variant order is SERIES_VARIANTS (PRIMARY first),
    # which is deliberately NOT lexical order.
    def variant_rank(record):
        return R.SERIES_VARIANTS.index(record["series_variant"])

    check(
        "round index is ordered by variant then link sequence",
        [
            (variant_rank(record), int(record["link_sequence"]))
            for record in round_rows
        ]
        == sorted(
            (variant_rank(record), int(record["link_sequence"]))
            for record in round_rows
        ),
    )
    check(
        "the primary series is emitted before the sensitivity series",
        [
            record["series_variant"]
            for record in round_rows
            if int(record["link_sequence"]) == 0
        ]
        == list(R.SERIES_VARIANTS),
    )
    check(
        "components are ordered by variant, link, then numeric basket rank",
        [
            (
                variant_rank(record),
                int(record["link_sequence"]),
                int(record["basket_rank"]),
            )
            for record in component_rows
        ]
        == sorted(
            (
                variant_rank(record),
                int(record["link_sequence"]),
                int(record["basket_rank"]),
            )
            for record in component_rows
        ),
    )
    check(
        "coverage is ordered by variant, link, then numeric basket rank",
        [
            (
                variant_rank(record),
                int(record["link_sequence"]),
                int(record["basket_rank"]),
            )
            for record in coverage_rows
        ]
        == sorted(
            (
                variant_rank(record),
                int(record["link_sequence"]),
                int(record["basket_rank"]),
            )
            for record in coverage_rows
        ),
    )
    check(
        "basket rank ordering is numeric, not lexical",
        [
            int(record["basket_rank"])
            for record in coverage_rows[:EXPECTED_BASKET_ROUTES]
        ]
        == list(range(1, EXPECTED_BASKET_ROUTES + 1)),
    )
    check(
        "unaligned diagnostics are ordered by round sort key",
        [record["round_sort_key"] for record in unaligned_diagnostics]
        == sorted(record["round_sort_key"] for record in unaligned_diagnostics),
    )
    # Item rows are ordered by identity, NOT by status, so that a product
    # keeps its position when it changes between MATCHED, ENTERING and
    # LEAVING from one link to the next.
    check(
        "item relatives are ordered deterministically within each link",
        [
            (
                variant_rank(record),
                int(record["link_sequence"]),
                int(record["basket_rank"]),
                record["fare_class"],
                record["advance_purchase_window"],
                record["travel_date"],
            )
            for record in relative_rows
        ]
        == sorted(
            (
                variant_rank(record),
                int(record["link_sequence"]),
                int(record["basket_rank"]),
                record["fare_class"],
                record["advance_purchase_window"],
                record["travel_date"],
            )
            for record in relative_rows
        ),
    )
    check(
        "item ordering is independent of item status",
        len(
            {
                (
                    record["series_variant"],
                    record["link_sequence"],
                    record["item_id"],
                )
                for record in relative_rows
            }
        )
        == len(relative_rows),
    )

    # -----------------------------------------------------------------
    section("16. Guard flags, banned constructs and immutability")
    # -----------------------------------------------------------------
    guard_flags = (
        "USES_MACHINE_LEARNING",
        "USES_RANDOMNESS",
        "USES_IMPUTATION",
        "USES_ZERO_SUBSTITUTION",
        "USES_CARRY_FORWARD",
        "USES_PRICE_INTERPOLATION",
        "USES_SOURCE_WEIGHTS",
        "USES_EXPENDITURE_WEIGHTS",
        "USES_QUANTITY_WEIGHTS",
        "USES_FARE_VALUE_AS_WEIGHT",
        "USES_GRAIN_B_AS_INDEX_INPUT",
        "USES_OFF_BASKET_ROUTES_IN_HEADLINE",
        "SEVERITY_DETERMINES_PRIMARY_SERIES",
        "SUBSTITUTES_FARE_CLASSES",
        "SUBSTITUTES_ADVANCE_PURCHASE_WINDOWS",
        "MODIFIES_PHASE_1_TO_10",
        "REDISTRIBUTES_MISSING_ROUTE_WEIGHT",
    )
    for flag in guard_flags:
        check("guard flag is False: %s" % (flag,), getattr(R, flag) is False)
    for path in PHASE11_SOURCE_FILES:
        source = read_text(path)
        name = os.path.basename(path)
        hits = [token for token in SOURCE_BANNED_TOKENS if token in source]
        check(
            "no banned construct in %s" % (name,),
            not hits,
            str(hits),
        )
        check(
            "the forbidden field name is never emitted literally in %s" % (name,),
            source.count(FORBIDDEN_FIELD_TOKEN) == 0,
        )
        check(
            "no attribute-style row access in %s" % (name,),
            "row." not in source,
        )
    digests_before = {path: sha256_of(path) for path in PHASE10_PROTECTED_FILES}
    engine.run_index_engine(
        grain_a_path=GRAIN_A_PATH,
        basket_path=BASKET_PATH,
        phase10_coverage_path=PHASE10_COVERAGE_PATH,
        round_index_path=ROUND_INDEX_PATH,
        route_components_path=ROUTE_COMPONENTS_PATH,
        item_relatives_path=ITEM_RELATIVES_PATH,
        period_index_path=PERIOD_INDEX_PATH,
        index_coverage_path=INDEX_COVERAGE_PATH,
        index_lineage_path=INDEX_LINEAGE_PATH,
        unaligned_diagnostics_path=UNALIGNED_PATH,
    )
    unchanged = [
        os.path.basename(path)
        for path in PHASE10_PROTECTED_FILES
        if sha256_of(path) != digests_before[path]
    ]
    check(
        "a Phase 11 run leaves every Phase 10 output and the basket byte-identical",
        not unchanged,
        str(unchanged),
    )
    rerun_stable = True
    for _name, path, key in tables:
        _header, rerun_rows = read_rows(path)
        if rerun_rows != on_disk[key]:
            rerun_stable = False
    check("re-running the engine reproduces byte-stable outputs", rerun_stable)

    # -----------------------------------------------------------------
    section("17. D12 methodology disclosure")
    # -----------------------------------------------------------------
    if os.path.isfile(METHODOLOGY_PATH):
        doc = read_text(METHODOLOGY_PATH)
        disclosures = (
            ("basket-weight representation", "27.3706"),
            ("routes represented", "2 of 15"),
            ("synthetic data status", "synthetic"),
            ("maturity ramp limitation", "maturity"),
            ("unaligned diagnostic rounds", "7 unaligned"),
            ("no official MoSPI endorsement", "not endorsed by MoSPI"),
            ("prototype nature", "prototype"),
            ("weighted Jevons naming", "weighted Jevons"),
            ("base level", "100.000000"),
            ("forbidden field prohibition", R.ELIGIBILITY_FIELD_NAME),
        )
        for label, token in disclosures:
            check(
                "methodology discloses %s" % (label,),
                token.lower() in doc.lower(),
                token,
            )
        check(
            "methodology never claims official endorsement",
            "officially endorsed" not in doc.lower(),
        )
        check(
            "methodology does not name the forbidden field as an output",
            ("`" + FORBIDDEN_FIELD_TOKEN + "`") not in doc,
        )

    # -----------------------------------------------------------------
    print("")
    print("=" * 64)
    print("Phase 11 verifier: %d passed, %d failed" % (len(PASSED), len(FAILED)))
    if FAILED:
        print("")
        for section_name, label, detail in FAILED:
            print(
                "  FAILED [%s] %s%s"
                % (section_name, label, ("  -> %s" % (detail,)) if detail else "")
            )
    print("=" * 64)
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
