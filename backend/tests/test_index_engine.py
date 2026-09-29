"""Phase 11 index engine tests.

Covers the locked Phase 11 methodology (D1-D12):

* exact 4-tuple item identity        * REVIEW/HIGH primary inclusion
* matched price definition           * EXCL_REVIEW_HIGH sensitivity series
* price-relative direction           * anchored-only chaining
* weighted Jevons                    * base level 100.000000
* per-route elementary Jevons        * rebasing
* traffic-weight renormalization     * daily/weekly/monthly derivation
* partial coverage disclosure        * deterministic ordering
* entering/leaving products          * lineage reconciliation
* no imputation                      * basket immutability
* no zero substitution               * Phase 1-10 immutability
* no machine learning, no randomness, no binary floats
* no forbidden boolean eligibility field

The tests read the committed Phase 11 outputs and also recompute the tables
in memory from the locked Phase 10 inputs, so a drift between code and
published CSVs fails loudly.
"""

import csv
import hashlib
import os
import sys
from decimal import Decimal, localcontext

import pytest

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(TESTS_DIR)
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from src.index_engine import index_engine as engine  # noqa: E402
from src.index_engine import rules as R  # noqa: E402

OUTPUTS_DIR = os.path.join(REPO_ROOT, "outputs")
SRC_DIR = os.path.join(REPO_ROOT, "src", "index_engine")
SCRIPTS_DIR = os.path.join(REPO_ROOT, "scripts")
DOCS_DIR = os.path.join(REPO_ROOT, "docs")

GRAIN_A_PATH = os.path.join(OUTPUTS_DIR, "phase10_route_series.csv")
PHASE10_COVERAGE_PATH = os.path.join(OUTPUTS_DIR, "phase10_coverage_report.csv")
BASKET_PATH = os.path.join(
    REPO_ROOT,
    "data",
    "official",
    "dgca",
    "processed",
    "_".join(("vayu", "route", "basket", "2024", "25")) + ".csv",
)
METHODOLOGY_PATH = os.path.join(DOCS_DIR, "index_methodology.md")

ROUND_INDEX_PATH = os.path.join(OUTPUTS_DIR, "phase11_round_index.csv")
ROUTE_COMPONENTS_PATH = os.path.join(
    OUTPUTS_DIR, "phase11_route_index_components.csv"
)
ITEM_RELATIVES_PATH = os.path.join(
    OUTPUTS_DIR, "phase11_item_price_relatives.csv"
)
PERIOD_INDEX_PATH = os.path.join(OUTPUTS_DIR, "phase11_period_index.csv")
INDEX_COVERAGE_PATH = os.path.join(
    OUTPUTS_DIR, "phase11_index_coverage_report.csv"
)
INDEX_LINEAGE_PATH = os.path.join(OUTPUTS_DIR, "phase11_index_lineage_map.csv")
UNALIGNED_PATH = os.path.join(
    OUTPUTS_DIR, "phase11_unaligned_round_diagnostics.csv"
)

# Measured corpus facts. These are prototype-corpus values, not official
# statistics, and they exist so silent drift is caught.
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
EXPECTED_WEIGHT_REPRESENTED = Decimal("0.273706")
EXPECTED_COVERAGE_PCT = "27.3706"
EXPECTED_ROUND_INDEX_ROWS = 18
EXPECTED_ROUTE_COMPONENT_ROWS = 32
EXPECTED_ITEM_RELATIVE_ROWS = 440
EXPECTED_PERIOD_INDEX_ROWS = 12
EXPECTED_INDEX_COVERAGE_ROWS = 270
EXPECTED_INDEX_LINEAGE_ROWS = 318
EXPECTED_DAILY_PERIODS = 3
EXPECTED_WEEKLY_PERIODS = 2
EXPECTED_MONTHLY_PERIODS = 1
OFF_BASKET_ROUTES = ("BLR-HYD", "CCU-MAA")

# Banned literals are assembled at runtime so this test file never contains
# the tokens it forbids.
FORBIDDEN_FIELD_TOKEN = "index" + "_eligible"
FLOAT_CALL_TOKEN = "float" + "("
BANNED_SOURCE_TOKENS = (
    FLOAT_CALL_TOKEN,
    "import " + "random",
    "numpy" + ".random",
    "np" + ".random",
    "sk" + "learn",
    "Isolation" + "Forest",
    "xg" + "boost",
    "import " + "pandas",
    "itertuples",
)
# These weight-name tokens are legitimately declared inside
# rules.FORBIDDEN_OUTPUT_FIELDS, so they must appear in the source text. They
# are banned as *published columns*, and are therefore checked against every
# output header rather than against the source files.
BANNED_OUTPUT_WEIGHT_TOKENS = (
    "source" + "_weight",
    "expenditure" + "_weight",
    "quantity" + "_weight",
    "basket_weighted_fare",
)
PHASE11_SOURCE_FILES = (
    os.path.join(SRC_DIR, "__init__.py"),
    os.path.join(SRC_DIR, "rules.py"),
    os.path.join(SRC_DIR, "index_engine.py"),
    os.path.join(SCRIPTS_DIR, "run_index_engine.py"),
)
PHASE10_PROTECTED_FILES = (
    BASKET_PATH,
    GRAIN_A_PATH,
    PHASE10_COVERAGE_PATH,
    os.path.join(OUTPUTS_DIR, "phase10_route_class_round_series.csv"),
    os.path.join(OUTPUTS_DIR, "phase10_route_crosswalk.csv"),
    os.path.join(OUTPUTS_DIR, "phase10_route_lineage_map.csv"),
)


# ---------------------------------------------------------------------------
# Helpers and fixtures
# ---------------------------------------------------------------------------


def read_rows(path):
    with open(path, "r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def read_text(path):
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


def sha256_of(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        digest.update(handle.read())
    return digest.hexdigest()


def dec(text):
    return Decimal(str(text))


def close_enough(left, right, tolerance):
    return abs(dec(left) - dec(right)) <= Decimal(tolerance)


def rows_for(rows, variant):
    return [row for row in rows if row["series_variant"] == variant]


@pytest.fixture(scope="module")
def basket():
    return engine.load_basket(BASKET_PATH)


@pytest.fixture(scope="module")
def grain_a(basket):
    return engine.load_grain_a(GRAIN_A_PATH, basket)


@pytest.fixture(scope="module")
def phase10_coverage(basket):
    return engine.load_phase10_coverage(PHASE10_COVERAGE_PATH, basket)


@pytest.fixture(scope="module")
def result(grain_a, basket, phase10_coverage):
    return engine.aggregate(grain_a, basket, phase10_coverage)


@pytest.fixture(scope="module")
def basket_weights(basket):
    return {entry["route_id"]: entry["traffic_weight"] for entry in basket}


@pytest.fixture(scope="module")
def round_rows():
    return read_rows(ROUND_INDEX_PATH)


@pytest.fixture(scope="module")
def component_rows():
    return read_rows(ROUTE_COMPONENTS_PATH)


@pytest.fixture(scope="module")
def relative_rows():
    return read_rows(ITEM_RELATIVES_PATH)


@pytest.fixture(scope="module")
def period_rows():
    return read_rows(PERIOD_INDEX_PATH)


@pytest.fixture(scope="module")
def coverage_rows():
    return read_rows(INDEX_COVERAGE_PATH)


@pytest.fixture(scope="module")
def lineage_rows():
    return read_rows(INDEX_LINEAGE_PATH)


@pytest.fixture(scope="module")
def unaligned_rows():
    return read_rows(UNALIGNED_PATH)


@pytest.fixture(scope="module")
def primary_rounds(round_rows):
    return rows_for(round_rows, R.SERIES_VARIANT_PRIMARY)


# ---------------------------------------------------------------------------
# D1: elementary item identity (exact 4-tuple)
# ---------------------------------------------------------------------------


class TestItemIdentity:
    def test_item_key_is_the_locked_four_tuple(self):
        assert R.ITEM_KEY_FIELDS == (
            "route_id",
            "fare_class",
            "advance_purchase_window",
            "travel_date",
        )

    def test_item_key_reads_exactly_those_four_fields(self):
        mapping = {
            "route_id": "BOM-DEL",
            "fare_class": "Economy Saver",
            "advance_purchase_window": "T15(12-18)",
            "travel_date": "2026-09-20",
            "collection_round_id": "ROUND::2026-09-05T09:00",
            "route_fare_median": "5300.00",
        }
        assert R.item_key(mapping) == (
            "BOM-DEL",
            "Economy Saver",
            "T15(12-18)",
            "2026-09-20",
        )

    def test_item_id_is_built_from_the_four_tuple_only(self):
        key = ("BOM-DEL", "Economy Saver", "T15(12-18)", "2026-09-20")
        built = R.item_id(key)
        assert built.startswith(R.ITEM_ID_PREFIX)
        assert built == R.ITEM_ID_PREFIX + R.ITEM_ID_SEPARATOR.join(key)

    def test_travel_date_is_never_collapsed_out_of_identity(self):
        first = R.item_id(
            ("BOM-DEL", "Economy Saver", "T15(12-18)", "2026-09-20")
        )
        second = R.item_id(
            ("BOM-DEL", "Economy Saver", "T15(12-18)", "2026-10-05")
        )
        assert first != second

    def test_fare_classes_are_never_substituted(self):
        assert R.SUBSTITUTES_FARE_CLASSES is False

    def test_advance_purchase_windows_are_never_substituted(self):
        assert R.SUBSTITUTES_ADVANCE_PURCHASE_WINDOWS is False

    def test_published_item_ids_match_their_identity_columns(
        self, relative_rows
    ):
        for row in relative_rows:
            expected = R.item_id(
                (
                    row["route_id"],
                    row["fare_class"],
                    row["advance_purchase_window"],
                    row["travel_date"],
                )
            )
            assert row["item_id"] == expected

    def test_maturity_ramp_limitation_is_documented_in_code(self):
        assert "maturity" in R.MATURITY_RAMP_DISCLOSURE.lower()


# ---------------------------------------------------------------------------
# D3: matched price definition and price-relative direction
# ---------------------------------------------------------------------------


class TestPriceRelatives:
    def test_relative_is_current_over_previous(self):
        assert R.price_relative(Decimal("5500"), Decimal("5000")) == Decimal(
            "1.10000000"
        )

    def test_a_rising_fare_gives_a_relative_above_one(self):
        assert R.price_relative(Decimal("6000"), Decimal("5000")) > Decimal(1)

    def test_a_falling_fare_gives_a_relative_below_one(self):
        assert R.price_relative(Decimal("4000"), Decimal("5000")) < Decimal(1)

    def test_an_unchanged_fare_gives_exactly_one(self):
        assert R.price_relative(Decimal("5000"), Decimal("5000")) == Decimal(
            "1.00000000"
        )

    def test_relative_is_not_inverted(self):
        rising = R.price_relative(Decimal("5500"), Decimal("5000"))
        falling = R.price_relative(Decimal("5000"), Decimal("5500"))
        assert rising > Decimal(1) > falling

    def test_a_non_positive_previous_price_is_refused(self):
        with pytest.raises(R.IndexRuleError):
            R.price_relative(Decimal("5000"), Decimal("0"))

    def test_a_non_positive_current_price_is_refused(self):
        with pytest.raises(R.IndexRuleError):
            R.price_relative(Decimal("0"), Decimal("5000"))

    def test_matched_rows_carry_both_fares_and_a_relative(self, relative_rows):
        matched = [
            row
            for row in relative_rows
            if row["item_status"] == R.ITEM_STATUS_MATCHED
        ]
        assert matched
        for row in matched:
            assert row["prev_fare"] != ""
            assert row["curr_fare"] != ""
            assert row["price_relative"] != ""

    def test_published_relatives_equal_current_over_previous(
        self, relative_rows
    ):
        matched = [
            row
            for row in relative_rows
            if row["item_status"] == R.ITEM_STATUS_MATCHED
        ]
        for row in matched:
            expected = R.quantize_relative(
                R.price_relative(dec(row["curr_fare"]), dec(row["prev_fare"]))
            )
            assert dec(row["price_relative"]) == expected

    def test_fares_keep_two_decimal_places(self, relative_rows):
        matched = [
            row
            for row in relative_rows
            if row["item_status"] == R.ITEM_STATUS_MATCHED
        ]
        for row in matched:
            assert (
                len(row["curr_fare"].split(".")[1]) == R.MONEY_DECIMAL_PLACES
            )

    def test_primary_matched_count_is_the_measured_total(self, relative_rows):
        matched = [
            row
            for row in rows_for(relative_rows, R.SERIES_VARIANT_PRIMARY)
            if row["item_status"] == R.ITEM_STATUS_MATCHED
        ]
        assert len(matched) == EXPECTED_MATCHED_TOTAL


# ---------------------------------------------------------------------------
# Entering and leaving products
# ---------------------------------------------------------------------------


class TestEnteringAndLeaving:
    def test_entering_items_have_no_previous_fare_and_no_relative(
        self, relative_rows
    ):
        entering = [
            row
            for row in relative_rows
            if row["item_status"] == R.ITEM_STATUS_ENTERING
        ]
        assert entering
        for row in entering:
            assert row["prev_fare"] == ""
            assert row["price_relative"] == ""
            assert row["curr_fare"] != ""

    def test_leaving_items_have_no_current_fare_and_no_relative(
        self, relative_rows
    ):
        leaving = [
            row
            for row in relative_rows
            if row["item_status"] == R.ITEM_STATUS_LEAVING
        ]
        assert leaving
        for row in leaving:
            assert row["curr_fare"] == ""
            assert row["price_relative"] == ""
            assert row["prev_fare"] != ""

    def test_entering_and_leaving_state_a_reason(self, relative_rows):
        for row in relative_rows:
            if row["item_status"] in (
                R.ITEM_STATUS_ENTERING,
                R.ITEM_STATUS_LEAVING,
            ):
                assert row["exclusion_reason"] != ""

    def test_entering_and_leaving_never_reach_the_lineage(
        self, relative_rows, lineage_rows
    ):
        unmatched = {
            (row["series_variant"], row["link_sequence"], row["item_id"])
            for row in relative_rows
            if row["item_status"] != R.ITEM_STATUS_MATCHED
        }
        contributing = {
            (row["series_variant"], row["link_sequence"], row["item_id"])
            for row in lineage_rows
        }
        assert not (unmatched & contributing)

    def test_round_counts_reconcile_with_the_item_table(
        self, primary_rounds, relative_rows
    ):
        primary_items = rows_for(relative_rows, R.SERIES_VARIANT_PRIMARY)
        for row in primary_rounds[1:]:
            sequence = row["link_sequence"]
            for status, column in (
                (R.ITEM_STATUS_MATCHED, "matched_product_count"),
                (R.ITEM_STATUS_ENTERING, "entering_product_count"),
                (R.ITEM_STATUS_LEAVING, "leaving_product_count"),
            ):
                counted = len(
                    [
                        item
                        for item in primary_items
                        if item["link_sequence"] == sequence
                        and item["item_status"] == status
                    ]
                )
                assert int(row[column]) == counted

    def test_missing_products_equal_entering_plus_leaving(self, round_rows):
        for row in round_rows:
            if int(row["link_sequence"]) == 0:
                continue
            assert int(row["missing_product_count"]) == int(
                row["entering_product_count"]
            ) + int(row["leaving_product_count"])


# ---------------------------------------------------------------------------
# Per-route elementary Jevons (unweighted within a route)
# ---------------------------------------------------------------------------


class TestElementaryJevons:
    def test_elementary_jevons_is_the_geometric_mean(self):
        result = R.elementary_jevons([Decimal("1.21"), Decimal("1.00")])
        assert close_enough(result, Decimal("1.1"), "0.00000001")

    def test_a_single_relative_returns_itself(self):
        result = R.elementary_jevons([Decimal("1.05")])
        assert close_enough(result, Decimal("1.05"), "0.00000001")

    def test_an_empty_matched_set_returns_none(self):
        assert R.elementary_jevons([]) is None

    def test_offsetting_relatives_return_one(self):
        result = R.elementary_jevons([Decimal("1.25"), Decimal("0.8")])
        assert close_enough(result, Decimal(1), "0.00000001")

    def test_geometric_mean_is_below_the_arithmetic_mean(self):
        relatives = [Decimal("0.5"), Decimal("2.0")]
        geometric = R.elementary_jevons(relatives)
        assert geometric < Decimal("1.25")

    def test_elementary_jevons_is_input_order_independent(self):
        relatives = [Decimal("1.3"), Decimal("0.7"), Decimal("1.05")]
        forward = R.elementary_jevons(relatives)
        backward = R.elementary_jevons(list(reversed(relatives)))
        assert forward == backward

    def test_within_route_items_are_equally_weighted(self):
        assert R.WITHIN_ROUTE_WEIGHTING == "EQUAL_WEIGHT_PER_MATCHED_ITEM"

    def test_elementary_statistic_is_declared_unweighted(self):
        assert R.ELEMENTARY_AGGREGATION_STATISTIC == "UNWEIGHTED_JEVONS"

    def test_published_route_elementary_matches_its_matched_items(
        self, component_rows, relative_rows
    ):
        for component in component_rows:
            matched = [
                dec(row["price_relative"])
                for row in relative_rows
                if row["series_variant"] == component["series_variant"]
                and row["link_sequence"] == component["link_sequence"]
                and row["route_id"] == component["route_id"]
                and row["item_status"] == R.ITEM_STATUS_MATCHED
            ]
            assert len(matched) == int(component["matched_product_count"])
            expected = R.elementary_jevons(matched)
            assert close_enough(
                component["route_elementary_jevons"], expected, "0.00000001"
            )


# ---------------------------------------------------------------------------
# D4: weighted Jevons and traffic-weight renormalization
# ---------------------------------------------------------------------------


class TestWeightedJevonsAndRenormalization:
    def test_renormalized_weights_sum_to_one(self):
        weights = {"BOM-DEL": Decimal("0.162603"), "BLR-DEL": Decimal("0.111103")}
        renormalized = R.renormalize_weights(weights)
        total = sum(renormalized.values(), Decimal(0))
        assert close_enough(total, Decimal(1), "0.000000000001")

    def test_renormalization_uses_the_contributing_weight_sum(self):
        weights = {"BOM-DEL": Decimal("0.162603"), "BLR-DEL": Decimal("0.111103")}
        renormalized = R.renormalize_weights(weights)
        with localcontext() as context:
            context.prec = R.INTERNAL_PRECISION
            expected = +(
                Decimal("0.162603")
                / (Decimal("0.162603") + Decimal("0.111103"))
            )
        assert close_enough(
            renormalized["BOM-DEL"], expected, "0.000000000001"
        )

    def test_renormalization_preserves_relative_weight_ratios(self):
        weights = {"A": Decimal("0.2"), "B": Decimal("0.1")}
        renormalized = R.renormalize_weights(weights)
        assert close_enough(
            renormalized["A"] / renormalized["B"], Decimal(2), "0.000000000001"
        )

    def test_missing_routes_are_absent_rather_than_redistributed(self):
        weights = {"A": Decimal("0.2")}
        renormalized = R.renormalize_weights(weights)
        assert list(renormalized) == ["A"]
        assert R.REDISTRIBUTES_MISSING_ROUTE_WEIGHT is False

    def test_an_empty_weight_map_renormalizes_to_nothing(self):
        assert R.renormalize_weights({}) == {}

    def test_represented_weight_is_unnormalized(self):
        weights = {"BOM-DEL": Decimal("0.162603"), "BLR-DEL": Decimal("0.111103")}
        assert R.represented_weight(weights) == EXPECTED_WEIGHT_REPRESENTED

    def test_weighted_jevons_of_equal_route_indices_is_that_index(self):
        contributions = [
            ("A", Decimal("0.6"), Decimal("1.10")),
            ("B", Decimal("0.4"), Decimal("1.10")),
        ]
        assert close_enough(
            R.weighted_jevons(contributions), Decimal("1.10"), "0.00000001"
        )

    def test_weighted_jevons_leans_toward_the_heavier_route(self):
        contributions = [
            ("A", Decimal("0.9"), Decimal("1.20")),
            ("B", Decimal("0.1"), Decimal("1.00")),
        ]
        result = R.weighted_jevons(contributions)
        assert result > Decimal("1.15")

    def test_weighted_jevons_is_input_order_independent(self):
        contributions = [
            ("A", Decimal("0.6"), Decimal("1.10")),
            ("B", Decimal("0.4"), Decimal("0.95")),
        ]
        forward = R.weighted_jevons(contributions)
        backward = R.weighted_jevons(list(reversed(contributions)))
        assert forward == backward

    def test_weighted_jevons_of_nothing_is_none(self):
        assert R.weighted_jevons([]) is None

    def test_weights_are_applied_to_logs_never_to_price_levels(self):
        assert R.WEIGHT_APPLICATION == (
            "APPLIED_TO_LOG_PRICE_RELATIVES_NEVER_TO_PRICE_LEVELS"
        )

    def test_weight_basis_is_the_phase5_traffic_basket(self):
        assert R.WEIGHT_BASIS == "DGCA_CONSERVATIVE_BIDIRECTIONAL_TRAFFIC"

    def test_no_source_expenditure_quantity_or_fare_value_weights_exist(self):
        assert R.USES_SOURCE_WEIGHTS is False
        assert R.USES_EXPENDITURE_WEIGHTS is False
        assert R.USES_QUANTITY_WEIGHTS is False
        assert R.USES_FARE_VALUE_AS_WEIGHT is False

    def test_published_renormalized_weights_sum_to_one_per_link(
        self, component_rows
    ):
        links = {}
        for row in component_rows:
            key = (row["series_variant"], row["link_sequence"])
            links.setdefault(key, Decimal(0))
            links[key] = links[key] + dec(row["renormalized_weight"])
        assert links
        for total in links.values():
            assert close_enough(total, Decimal(1), "0.000001")

    def test_published_renormalized_weights_match_the_locked_weights(
        self, component_rows, basket_weights
    ):
        for row in component_rows:
            assert close_enough(
                row["traffic_weight"],
                basket_weights[row["route_id"]],
                "0.000000000001",
            )

    def test_published_chain_factor_is_the_weighted_jevons(
        self, primary_rounds, component_rows
    ):
        for row in primary_rounds[1:]:
            contributions = [
                (
                    component["route_id"],
                    dec(component["renormalized_weight"]),
                    dec(component["route_elementary_jevons"]),
                )
                for component in component_rows
                if component["series_variant"] == row["series_variant"]
                and component["link_sequence"] == row["link_sequence"]
            ]
            expected = R.weighted_jevons(contributions)
            assert close_enough(row["chain_factor"], expected, "0.00000001")

    def test_aggregation_statistic_is_named_weighted_jevons_chained(self):
        assert R.AGGREGATION_STATISTIC == "WEIGHTED_JEVONS_CHAINED"


# ---------------------------------------------------------------------------
# D5: partial coverage disclosure
# ---------------------------------------------------------------------------


class TestCoverageDisclosure:
    DISCLOSURE_FIELDS = (
        "basket_routes_represented",
        "basket_routes_total",
        "basket_weight_represented",
        "basket_coverage_pct",
        "effective_weight_sum",
        "renormalization_applied",
        "coverage_status",
    )

    def test_every_round_discloses_all_seven_fields(self, round_rows):
        for row in round_rows:
            for field in self.DISCLOSURE_FIELDS:
                assert field in row
                assert row[field] != ""

    def test_coverage_reports_two_of_fifteen_routes(self, round_rows):
        for row in round_rows:
            assert int(row["basket_routes_represented"]) == (
                EXPECTED_ROUTES_REPRESENTED
            )
            assert int(row["basket_routes_total"]) == EXPECTED_BASKET_ROUTES

    def test_represented_weight_is_published_unnormalized(self, round_rows):
        for row in round_rows:
            assert dec(row["basket_weight_represented"]) == (
                EXPECTED_WEIGHT_REPRESENTED
            )

    def test_effective_weight_sum_is_exactly_one(self, round_rows):
        for row in round_rows:
            assert row["effective_weight_sum"] == "1.000000"

    def test_represented_weight_and_effective_sum_are_both_published(
        self, round_rows
    ):
        for row in round_rows:
            assert dec(row["basket_weight_represented"]) < dec(
                row["effective_weight_sum"]
            )

    def test_coverage_percentage_is_the_measured_value(self, round_rows):
        for row in round_rows:
            assert row["basket_coverage_pct"] == EXPECTED_COVERAGE_PCT

    def test_coverage_percentage_formula(self):
        assert R.coverage_percentage(
            EXPECTED_WEIGHT_REPRESENTED, Decimal("1.000000")
        ) == Decimal(EXPECTED_COVERAGE_PCT)

    def test_missing_weight_is_disclosed_not_hidden(self, round_rows):
        for row in round_rows:
            total = dec(row["basket_weight_represented"]) + dec(
                row["basket_weight_missing"]
            )
            assert close_enough(total, Decimal(1), "0.000001")

    def test_renormalization_is_flagged(self, round_rows):
        for row in round_rows:
            assert row["renormalization_applied"] == "True"

    def test_corpus_is_labelled_partial_coverage_prototype(self, round_rows):
        assert R.COVERAGE_STATUS_PARTIAL == "PARTIAL_COVERAGE_PROTOTYPE"
        for row in round_rows:
            assert row["coverage_status"] == R.COVERAGE_STATUS_PARTIAL

    def test_coverage_status_helper_labels_without_thresholds(self):
        assert R.coverage_status(2, 15) == R.COVERAGE_STATUS_PARTIAL
        assert R.coverage_status(15, 15) == R.COVERAGE_STATUS_FULL
        assert R.coverage_status(0, 15) == R.COVERAGE_STATUS_NONE

    def test_no_coverage_threshold_and_no_suppression(self):
        assert R.APPLIES_COVERAGE_THRESHOLD is False
        assert R.SUPPRESSES_INDEX_AUTOMATICALLY is False
        assert R.MINIMUM_COVERAGE_THRESHOLD is None

    def test_all_fifteen_basket_routes_appear_in_every_coverage_round(
        self, coverage_rows
    ):
        grouped = {}
        for row in coverage_rows:
            key = (row["series_variant"], row["collection_round_id"])
            grouped.setdefault(key, set())
            grouped[key].add(row["route_id"])
        assert grouped
        for routes in grouped.values():
            assert len(routes) == EXPECTED_BASKET_ROUTES

    def test_unobserved_basket_routes_are_listed_not_dropped(
        self, coverage_rows
    ):
        grouped = {}
        for row in coverage_rows:
            key = (row["series_variant"], row["collection_round_id"])
            grouped.setdefault(key, [])
            grouped[key].append(row)
        for rows in grouped.values():
            absent = [
                row
                for row in rows
                if row["route_coverage_status"]
                == R.COVERAGE_STATUS_NO_OBSERVATIONS
            ]
            assert len(absent) == EXPECTED_NO_OBSERVATION_ROUTES


# ---------------------------------------------------------------------------
# No imputation, no zero substitution
# ---------------------------------------------------------------------------


class TestNoImputationOrZeroSubstitution:
    def test_imputation_guards_are_all_false(self):
        assert R.USES_IMPUTATION is False
        assert R.USES_ZERO_SUBSTITUTION is False
        assert R.USES_CARRY_FORWARD is False
        assert R.USES_PRICE_INTERPOLATION is False

    def test_unobserved_routes_never_receive_a_fare(self, coverage_rows):
        for row in coverage_rows:
            if (
                row["route_coverage_status"]
                == R.COVERAGE_STATUS_NO_OBSERVATIONS
            ):
                assert row["matched_product_count"] == "0"
                assert row["contributed_to_index"] == "False"

    def test_unobserved_routes_never_receive_a_renormalized_weight(
        self, coverage_rows
    ):
        for row in coverage_rows:
            if (
                row["route_coverage_status"]
                == R.COVERAGE_STATUS_NO_OBSERVATIONS
            ):
                assert row["renormalized_weight"] == ""

    def test_no_published_fare_is_zero_or_negative(self, relative_rows):
        for row in relative_rows:
            for column in ("prev_fare", "curr_fare"):
                if row[column] != "":
                    assert dec(row[column]) > 0

    def test_no_published_price_relative_is_zero(self, relative_rows):
        for row in relative_rows:
            if row["price_relative"] != "":
                assert dec(row["price_relative"]) > 0

    def test_unmatched_items_are_blank_never_zero(self, relative_rows):
        for row in relative_rows:
            if row["item_status"] == R.ITEM_STATUS_ENTERING:
                assert row["prev_fare"] == ""
            if row["item_status"] == R.ITEM_STATUS_LEAVING:
                assert row["curr_fare"] == ""

    def test_a_non_positive_fare_is_ineligible_rather_than_replaced(self):
        mapping = {
            "route_coverage_status": "OBSERVED",
            "route_price_state": R.PRICE_STATE_PRICED,
            "route_fare_median": "0.00",
            "anomaly_severity_max": R.SEVERITY_NONE,
        }
        status, price = R.evaluate_index_eligibility(
            mapping, R.SERIES_VARIANT_PRIMARY
        )
        assert status == R.ELIGIBILITY_NON_POSITIVE_FARE
        assert R.is_structurally_ineligible(status) is True
        # The offending value is returned for diagnostics only; the status,
        # not the value, keeps the item out of the index.
        assert price == Decimal("0.00")

    def test_an_unparsable_fare_is_ineligible_rather_than_replaced(self):
        mapping = {
            "route_coverage_status": "OBSERVED",
            "route_price_state": R.PRICE_STATE_PRICED,
            "route_fare_median": "not-a-number",
            "anomaly_severity_max": R.SEVERITY_NONE,
        }
        status, price = R.evaluate_index_eligibility(
            mapping, R.SERIES_VARIANT_PRIMARY
        )
        assert status == R.ELIGIBILITY_UNPARSABLE_FARE
        assert price is None

    def test_a_missing_fare_is_ineligible_rather_than_replaced(self):
        mapping = {
            "route_coverage_status": "OBSERVED",
            "route_price_state": R.PRICE_STATE_PRICED,
            "route_fare_median": "",
            "anomaly_severity_max": R.SEVERITY_NONE,
        }
        status, price = R.evaluate_index_eligibility(
            mapping, R.SERIES_VARIANT_PRIMARY
        )
        assert status == R.ELIGIBILITY_MISSING_FARE
        assert price is None

    def test_a_route_with_no_observations_is_ineligible(self):
        mapping = {
            "route_coverage_status": R.COVERAGE_STATUS_NO_OBSERVATIONS,
            "route_price_state": "",
            "route_fare_median": "",
            "anomaly_severity_max": "",
        }
        status, price = R.evaluate_index_eligibility(
            mapping, R.SERIES_VARIANT_PRIMARY
        )
        assert status == R.ELIGIBILITY_NO_OBSERVATIONS
        assert price is None

    def test_structural_ineligibility_statuses_are_declared(self):
        assert R.ELIGIBILITY_NOT_PRICED in R.STRUCTURAL_INELIGIBILITY_STATUSES
        assert R.ELIGIBILITY_MISSING_FARE in R.STRUCTURAL_INELIGIBILITY_STATUSES
        assert (
            R.ELIGIBILITY_NON_POSITIVE_FARE
            in R.STRUCTURAL_INELIGIBILITY_STATUSES
        )
        assert (
            R.ELIGIBILITY_UNPARSABLE_FARE
            in R.STRUCTURAL_INELIGIBILITY_STATUSES
        )


# ---------------------------------------------------------------------------
# D6: REVIEW/HIGH primary inclusion and the EXCL_REVIEW_HIGH sensitivity series
# ---------------------------------------------------------------------------


class TestSeverityInclusion:
    def test_primary_keeps_a_review_severity_item(self):
        mapping = {
            "route_coverage_status": "OBSERVED",
            "route_price_state": R.PRICE_STATE_PRICED,
            "route_fare_median": "14050.00",
            "anomaly_severity_max": R.SEVERITY_REVIEW,
        }
        status, price = R.evaluate_index_eligibility(
            mapping, R.SERIES_VARIANT_PRIMARY
        )
        assert status == R.ELIGIBILITY_ELIGIBLE
        assert price == Decimal("14050.00")

    def test_primary_keeps_a_high_severity_item(self):
        mapping = {
            "route_coverage_status": "OBSERVED",
            "route_price_state": R.PRICE_STATE_PRICED,
            "route_fare_median": "20000.00",
            "anomaly_severity_max": R.SEVERITY_HIGH,
        }
        status, price = R.evaluate_index_eligibility(
            mapping, R.SERIES_VARIANT_PRIMARY
        )
        assert status == R.ELIGIBILITY_ELIGIBLE
        assert price == Decimal("20000.00")

    def test_severity_never_determines_the_primary_series(self):
        assert R.SEVERITY_DETERMINES_PRIMARY_SERIES is False

    def test_sensitivity_drops_review_items_with_its_own_status(self):
        mapping = {
            "route_coverage_status": "OBSERVED",
            "route_price_state": R.PRICE_STATE_PRICED,
            "route_fare_median": "14050.00",
            "anomaly_severity_max": R.SEVERITY_REVIEW,
        }
        status, price = R.evaluate_index_eligibility(
            mapping, R.SERIES_VARIANT_SENSITIVITY
        )
        assert status == R.ELIGIBILITY_EXCLUDED_REVIEW_HIGH
        # Severity exclusion is not a structural exclusion.
        assert R.is_structurally_ineligible(status) is False

    def test_sensitivity_drops_high_items(self):
        mapping = {
            "route_coverage_status": "OBSERVED",
            "route_price_state": R.PRICE_STATE_PRICED,
            "route_fare_median": "20000.00",
            "anomaly_severity_max": R.SEVERITY_HIGH,
        }
        status, price = R.evaluate_index_eligibility(
            mapping, R.SERIES_VARIANT_SENSITIVITY
        )
        assert status == R.ELIGIBILITY_EXCLUDED_REVIEW_HIGH

    def test_sensitivity_keeps_info_and_none_items(self):
        for severity in (R.SEVERITY_NONE, R.SEVERITY_INFO):
            mapping = {
                "route_coverage_status": "OBSERVED",
                "route_price_state": R.PRICE_STATE_PRICED,
                "route_fare_median": "5300.00",
                "anomaly_severity_max": severity,
            }
            status, _price = R.evaluate_index_eligibility(
                mapping, R.SERIES_VARIANT_SENSITIVITY
            )
            assert status == R.ELIGIBILITY_ELIGIBLE

    def test_a_non_priced_item_is_excluded_from_both_variants(self):
        mapping = {
            "route_coverage_status": "OBSERVED",
            "route_price_state": "SOLD_OUT",
            "route_fare_median": "",
            "anomaly_severity_max": R.SEVERITY_NONE,
        }
        for variant in R.SERIES_VARIANTS:
            status, price = R.evaluate_index_eligibility(mapping, variant)
            assert status == R.ELIGIBILITY_NOT_PRICED
            assert price is None

    def test_the_primary_variant_is_the_headline_series(self):
        assert R.PRIMARY_SERIES_VARIANT == R.SERIES_VARIANT_PRIMARY
        assert R.SERIES_VARIANTS[0] == R.SERIES_VARIANT_PRIMARY

    def test_both_variants_are_published_with_distinct_rule_ids(
        self, round_rows
    ):
        variants = {row["series_variant"] for row in round_rows}
        assert variants == set(R.SERIES_VARIANTS)
        assert (
            R.INDEX_INCLUSION_RULE_ID[R.SERIES_VARIANT_PRIMARY]
            != R.INDEX_INCLUSION_RULE_ID[R.SERIES_VARIANT_SENSITIVITY]
        )

    def test_published_rows_carry_the_matching_inclusion_rule_id(
        self, round_rows
    ):
        for row in round_rows:
            assert row["index_inclusion_rule_id"] == R.INDEX_INCLUSION_RULE_ID[
                row["series_variant"]
            ]

    def test_unknown_variants_are_refused(self):
        with pytest.raises(R.IndexRuleError):
            R.evaluate_index_eligibility({}, "NOT_A_VARIANT")

    def test_sensitivity_excludes_exactly_review_and_high(self):
        assert set(R.SENSITIVITY_EXCLUDED_SEVERITIES) == {
            R.SEVERITY_REVIEW,
            R.SEVERITY_HIGH,
        }


# ---------------------------------------------------------------------------
# D2: anchored-only chaining
# ---------------------------------------------------------------------------


class TestAnchoredOnlyChaining:
    def test_only_anchored_rounds_are_chain_eligible(self):
        assert R.is_chain_eligible_round(R.ROUND_ALIGNMENT_ANCHORED) is True
        assert R.is_chain_eligible_round(R.ROUND_ALIGNMENT_UNALIGNED) is False

    def test_chain_eligible_alignments_contain_only_anchored(self):
        assert R.CHAIN_ELIGIBLE_ALIGNMENTS == (R.ROUND_ALIGNMENT_ANCHORED,)

    def test_the_published_chain_holds_only_anchored_rounds(self, round_rows):
        for row in round_rows:
            assert row["round_alignment"] == R.ROUND_ALIGNMENT_ANCHORED

    def test_the_chain_has_the_measured_anchored_round_count(
        self, primary_rounds
    ):
        assert len(primary_rounds) == EXPECTED_ANCHORED_ROUNDS

    def test_the_chain_has_one_fewer_link_than_rounds(self, primary_rounds):
        links = [row for row in primary_rounds if int(row["link_sequence"]) > 0]
        assert len(links) == EXPECTED_CHAIN_LINKS
        assert len(links) == len(primary_rounds) - 1

    def test_unaligned_rounds_are_published_as_diagnostics(
        self, unaligned_rows
    ):
        assert len(unaligned_rows) == EXPECTED_UNALIGNED_ROUNDS

    def test_every_unaligned_round_is_marked_chain_ineligible(
        self, unaligned_rows
    ):
        for row in unaligned_rows:
            assert row["chain_eligible"] == "False"
            assert row["excluded_from_chain_reason"] != ""

    def test_unaligned_diagnostics_state_their_nearest_anchored_round(
        self, unaligned_rows
    ):
        for row in unaligned_rows:
            assert row["nearest_anchored_round_id"] != ""
            assert int(row["minutes_to_nearest_anchored_round"]) > 0

    def test_no_unaligned_round_appears_in_the_chain(
        self, round_rows, unaligned_rows
    ):
        chained = {row["collection_round_id"] for row in round_rows}
        diagnostics = {row["collection_round_id"] for row in unaligned_rows}
        assert not (chained & diagnostics)

    def test_diagnostics_are_labelled_as_diagnostics(self, unaligned_rows):
        for row in unaligned_rows:
            assert row["diagnostic_basis"] == R.UNALIGNED_DIAGNOSTIC_BASIS

    def test_anchor_configuration_is_declared_a_prototype_calibration(self):
        assert R.EXPECTED_ANCHOR_TIMES == ("09:00", "14:30", "20:15")
        assert R.ANCHOR_CONFIGURATION_STATUS == "PROTOTYPE_CALIBRATION"


# ---------------------------------------------------------------------------
# D3/D8: base level, chaining arithmetic, precision and rebasing
# ---------------------------------------------------------------------------


class TestChainingPrecisionAndRebasing:
    def test_base_level_is_one_hundred(self):
        assert R.INDEX_BASE_LEVEL == Decimal(100)
        assert R.INDEX_BASE_LEVEL_PUBLISHED == Decimal("100.000000")
        assert str(R.INDEX_BASE_LEVEL_PUBLISHED) == "100.000000"

    def test_the_first_round_publishes_exactly_one_hundred(
        self, round_rows
    ):
        bases = [row for row in round_rows if int(row["link_sequence"]) == 0]
        assert bases
        for row in bases:
            assert row["index_level"] == "100.000000"
            assert row["is_base_period"] == "True"
            assert row["chain_factor"] == ""

    def test_the_base_round_is_the_first_anchored_round(self, primary_rounds):
        assert primary_rounds[0]["collection_round_id"] == (
            EXPECTED_BASE_ROUND_ID
        )

    def test_chain_level_multiplies_the_previous_level(self):
        assert R.chain_level(Decimal(100), Decimal("1.05")) == Decimal("105.00")

    def test_published_levels_follow_the_chain_recursion(self, primary_rounds):
        previous = None
        for row in primary_rounds:
            if previous is None:
                previous = dec(row["index_level"])
                continue
            expected = R.quantize_level(
                R.chain_level(previous, dec(row["chain_factor"]))
            )
            assert close_enough(row["index_level"], expected, "0.000001")
            previous = dec(row["index_level"])

    def test_the_final_level_is_the_measured_value(self, primary_rounds):
        final = primary_rounds[-1]
        assert final["collection_round_id"] == EXPECTED_FINAL_ROUND_ID
        assert final["index_level"] == EXPECTED_FINAL_LEVEL

    def test_matched_counts_per_link_are_the_measured_values(
        self, primary_rounds
    ):
        counts = tuple(
            int(row["matched_product_count"]) for row in primary_rounds[1:]
        )
        assert counts == EXPECTED_MATCHED_PER_LINK

    def test_internal_precision_is_twenty_eight(self):
        assert R.INTERNAL_PRECISION == 28

    def test_rounding_mode_is_round_half_up(self):
        assert R.ROUNDING_MODE_NAME == "ROUND_HALF_UP"

    def test_index_levels_are_published_at_six_decimal_places(
        self, round_rows
    ):
        assert R.INDEX_LEVEL_DECIMAL_PLACES == 6
        for row in round_rows:
            assert len(row["index_level"].split(".")[1]) == 6

    def test_chain_factors_are_published_at_eight_decimal_places(
        self, round_rows
    ):
        assert R.CHAIN_FACTOR_DECIMAL_PLACES == 8
        for row in round_rows:
            if row["chain_factor"] != "":
                assert len(row["chain_factor"].split(".")[1]) == 8

    def test_round_half_up_is_applied_at_the_midpoint(self):
        assert R.quantize_level(Decimal("100.0000005")) == Decimal(
            "100.000001"
        )

    def test_rebasing_sets_the_new_base_to_one_hundred(self, result):
        rebased = dict(
            engine.rebase_round_index(
                result, R.SERIES_VARIANT_PRIMARY, EXPECTED_FINAL_ROUND_ID
            )
        )
        assert rebased[EXPECTED_FINAL_ROUND_ID] == Decimal("100.000000")

    def test_rebasing_preserves_every_adjacent_relative(self, result):
        levels = result["chains"][R.SERIES_VARIANT_PRIMARY]["levels"]
        original = dict(levels)
        rebased = dict(R.rebase_levels(levels, EXPECTED_FINAL_ROUND_ID))
        keys = [key for key, _level in levels]
        for position in range(1, len(keys)):
            previous_key = keys[position - 1]
            current_key = keys[position]
            with localcontext() as context:
                context.prec = R.INTERNAL_PRECISION
                before = +(original[current_key] / original[previous_key])
                after = +(rebased[current_key] / rebased[previous_key])
            assert close_enough(before, after, "0.000000000000000001")

    def test_rebasing_to_the_original_base_is_a_no_op(self, result):
        rebased = dict(
            engine.rebase_round_index(
                result, R.SERIES_VARIANT_PRIMARY, EXPECTED_BASE_ROUND_ID
            )
        )
        assert rebased[EXPECTED_FINAL_ROUND_ID] == Decimal(
            EXPECTED_FINAL_LEVEL
        )

    def test_rebasing_operates_on_unrounded_levels(self, result):
        levels = result["chains"][R.SERIES_VARIANT_PRIMARY]["levels"]
        unrounded = [level for _key, level in levels]
        assert any(
            level != R.quantize_level(level) for level in unrounded
        )

    def test_rebasing_to_an_unknown_round_is_refused(self, result):
        with pytest.raises(R.IndexRuleError):
            engine.rebase_round_index(
                result, R.SERIES_VARIANT_PRIMARY, "ROUND::not-a-round"
            )

    def test_percent_change_reconciles_with_published_levels(
        self, primary_rounds
    ):
        previous = None
        for row in primary_rounds:
            if previous is None:
                previous = dec(row["index_level"])
                continue
            expected = R.percent_change(dec(row["index_level"]), previous)
            assert dec(row["index_change_pct_vs_prev_round"]) == expected
            previous = dec(row["index_level"])


# ---------------------------------------------------------------------------
# D7: daily / weekly / monthly derivation
# ---------------------------------------------------------------------------


class TestPeriodDerivation:
    def test_period_grains_are_daily_weekly_monthly(self):
        assert R.PERIOD_GRAINS == (
            R.PERIOD_GRAIN_DAILY,
            R.PERIOD_GRAIN_WEEKLY,
            R.PERIOD_GRAIN_MONTHLY,
        )

    def test_period_ids_are_derived_from_the_round_sort_key(self):
        assert R.period_id("2026-09-07 20:15", R.PERIOD_GRAIN_DAILY) == (
            "2026-09-07"
        )
        assert R.period_id("2026-09-07 20:15", R.PERIOD_GRAIN_MONTHLY) == (
            "2026-09"
        )
        assert R.period_id("2026-09-07 20:15", R.PERIOD_GRAIN_WEEKLY) == (
            "2026-W37"
        )

    def test_a_short_round_sort_key_is_refused(self):
        with pytest.raises(R.IndexRuleError):
            R.period_id("2026-09", R.PERIOD_GRAIN_DAILY)

    def test_every_period_row_declares_it_is_derived(self, period_rows):
        assert period_rows
        for row in period_rows:
            assert row["derivation_rule"] == "DERIVED_FROM_ROUND_LEVEL_CHAIN"

    def test_the_measured_period_counts_are_published(self, period_rows):
        primary = rows_for(period_rows, R.SERIES_VARIANT_PRIMARY)
        counts = {}
        for row in primary:
            counts.setdefault(row["period_grain"], 0)
            counts[row["period_grain"]] = counts[row["period_grain"]] + 1
        assert counts[R.PERIOD_GRAIN_DAILY] == EXPECTED_DAILY_PERIODS
        assert counts[R.PERIOD_GRAIN_WEEKLY] == EXPECTED_WEEKLY_PERIODS
        assert counts[R.PERIOD_GRAIN_MONTHLY] == EXPECTED_MONTHLY_PERIODS

    def test_period_index_row_count_is_stable(self, period_rows):
        assert len(period_rows) == EXPECTED_PERIOD_INDEX_ROWS

    def test_the_primary_measure_is_the_period_end_chain_level(
        self, period_rows
    ):
        for row in period_rows:
            assert row["period_primary_measure"] == "PERIOD_END_CHAIN_LEVEL"

    def test_period_end_levels_come_from_the_round_chain(
        self, period_rows, round_rows
    ):
        published = {
            (row["series_variant"], row["index_level"])
            for row in round_rows
        }
        for row in period_rows:
            assert (
                row["series_variant"],
                row["period_end_index_level"],
            ) in published

    def test_the_monthly_period_ends_at_the_final_chain_level(
        self, period_rows
    ):
        monthly = [
            row
            for row in rows_for(period_rows, R.SERIES_VARIANT_PRIMARY)
            if row["period_grain"] == R.PERIOD_GRAIN_MONTHLY
        ]
        assert len(monthly) == 1
        assert monthly[0]["period_end_index_level"] == EXPECTED_FINAL_LEVEL

    def test_the_secondary_measure_is_the_period_average(self, period_rows):
        for row in period_rows:
            assert row["period_secondary_measure"] == (
                "PERIOD_AVERAGE_INDEX_LEVEL"
            )

    def test_the_period_average_is_labelled_non_chain_consistent(
        self, period_rows
    ):
        assert R.PERIOD_AVERAGE_IS_CHAIN_CONSISTENT is False
        for row in period_rows:
            assert row["period_average_is_chain_consistent"] == "False"

    def test_the_period_average_disclosure_text_exists(self):
        assert "chain" in R.PERIOD_AVERAGE_DISCLOSURE.lower()

    def test_period_averages_are_the_mean_of_member_round_levels(
        self, period_rows, round_rows
    ):
        for row in period_rows:
            members = [
                dec(candidate["index_level"])
                for candidate in round_rows
                if candidate["series_variant"] == row["series_variant"]
                and R.period_id(
                    candidate["round_sort_key"], row["period_grain"]
                )
                == row["period_id"]
            ]
            assert len(members) == int(row["round_count"])
            expected = R.quantize_level(R.mean_level(members))
            assert close_enough(
                row["period_average_level"], expected, "0.000001"
            )

    def test_incomplete_periods_are_flagged_partial(self, period_rows):
        for row in period_rows:
            expected = R.expected_round_count(
                row["period_grain"], row["period_id"]
            )
            assert int(row["expected_round_count"]) == expected
            is_partial = int(row["round_count"]) < expected
            assert row["period_is_partial"] == str(is_partial)

    def test_expected_round_counts_use_three_rounds_per_day(self):
        assert R.EXPECTED_ROUNDS_PER_DAY == 3
        assert R.expected_round_count(R.PERIOD_GRAIN_DAILY, "2026-09-07") == 3
        assert R.expected_round_count(R.PERIOD_GRAIN_WEEKLY, "2026-W37") == 21
        assert R.expected_round_count(R.PERIOD_GRAIN_MONTHLY, "2026-09") == 90

    def test_an_unknown_grain_is_refused(self):
        with pytest.raises(R.IndexRuleError):
            R.expected_round_count("QUARTERLY", "2026-Q3")

    def test_period_rows_are_never_chained_onward(self, period_rows):
        for row in period_rows:
            assert "chain_factor" not in row


# ---------------------------------------------------------------------------
# D9 / D10: basket scope and grain discipline
# ---------------------------------------------------------------------------


class TestScopeBoundaries:
    def test_only_basket_routes_appear_in_the_index(
        self, component_rows, basket_weights
    ):
        for row in component_rows:
            assert row["route_id"] in basket_weights

    def test_off_basket_routes_never_enter_the_headline_index(
        self, component_rows, relative_rows, coverage_rows
    ):
        for rows in (component_rows, relative_rows, coverage_rows):
            observed = {row["route_id"] for row in rows}
            for route_id in OFF_BASKET_ROUTES:
                assert route_id not in observed

    def test_off_basket_routes_are_excluded_by_guard_flag(self):
        assert R.USES_OFF_BASKET_ROUTES_IN_HEADLINE is False

    def test_grain_b_is_never_an_index_input(self):
        assert R.USES_GRAIN_B_AS_INDEX_INPUT is False

    def test_the_engine_reads_only_grain_a_the_basket_and_coverage(self):
        source = read_text(os.path.join(SRC_DIR, "index_engine.py"))
        assert "phase10_route_class_round_series" not in source
        assert "off_basket" not in source

    def test_route_aggregation_is_not_repeated_in_phase_11(self):
        source = read_text(os.path.join(SRC_DIR, "index_engine.py"))
        assert "route_fare_min" not in source
        assert "route_fare_max" not in source

    def test_only_the_two_observed_routes_contribute(self, component_rows):
        assert {row["route_id"] for row in component_rows} == {
            "BOM-DEL",
            "BLR-DEL",
        }


# ---------------------------------------------------------------------------
# D11: field vocabulary and the forbidden field
# ---------------------------------------------------------------------------


class TestFieldVocabulary:
    ALL_PATHS = (
        ROUND_INDEX_PATH,
        ROUTE_COMPONENTS_PATH,
        ITEM_RELATIVES_PATH,
        PERIOD_INDEX_PATH,
        INDEX_COVERAGE_PATH,
        INDEX_LINEAGE_PATH,
        UNALIGNED_PATH,
    )

    def test_the_approved_field_names_are_declared(self):
        assert R.ELIGIBILITY_FIELD_NAME == "index_eligibility_status"
        assert R.INCLUSION_RULE_FIELD_NAME == "index_inclusion_rule_id"

    def test_the_forbidden_field_is_declared_forbidden(self):
        assert FORBIDDEN_FIELD_TOKEN in R.FORBIDDEN_OUTPUT_FIELDS

    def test_no_output_publishes_the_forbidden_field(self):
        for path in self.ALL_PATHS:
            with open(path, "r", encoding="utf-8-sig", newline="") as handle:
                header = next(csv.reader(handle))
            assert FORBIDDEN_FIELD_TOKEN not in header

    def test_no_declared_column_tuple_contains_the_forbidden_field(self):
        for columns in engine.ALL_OUTPUT_COLUMN_SETS:
            assert FORBIDDEN_FIELD_TOKEN not in columns
            assert R.assert_no_forbidden_fields(columns) is True

    def test_the_forbidden_field_guard_raises_when_violated(self):
        with pytest.raises(R.IndexRuleError):
            R.assert_no_forbidden_fields(["route_id", FORBIDDEN_FIELD_TOKEN])

    def test_the_eligibility_field_is_published_on_item_rows(
        self, relative_rows
    ):
        for row in relative_rows:
            assert row["index_eligibility_status"] != ""

    def test_published_eligibility_statuses_are_approved_values(
        self, relative_rows
    ):
        approved = {
            R.ELIGIBILITY_ELIGIBLE,
            R.ELIGIBILITY_NO_OBSERVATIONS,
            R.ELIGIBILITY_NOT_PRICED,
            R.ELIGIBILITY_MISSING_FARE,
            R.ELIGIBILITY_UNPARSABLE_FARE,
            R.ELIGIBILITY_NON_POSITIVE_FARE,
            R.ELIGIBILITY_EXCLUDED_REVIEW_HIGH,
        }
        for row in relative_rows:
            assert row["index_eligibility_status"] in approved

    def test_every_output_carries_the_phase11_schema_version(self):
        for path in self.ALL_PATHS:
            with open(path, "r", encoding="utf-8-sig", newline="") as handle:
                header = next(csv.reader(handle))
            assert "phase11_schema_version" in header

    def test_the_schema_version_value_is_stamped_on_every_row(
        self, round_rows, period_rows, lineage_rows
    ):
        for rows in (round_rows, period_rows, lineage_rows):
            for row in rows:
                assert row["phase11_schema_version"] == (
                    R.PHASE11_SCHEMA_VERSION
                )

    def test_the_expected_phase10_schema_version_is_asserted(self):
        assert R.PHASE10_SCHEMA_VERSION_EXPECTED


# ---------------------------------------------------------------------------
# Deterministic ordering and input-order independence
# ---------------------------------------------------------------------------


class TestDeterminism:
    def test_round_index_is_ordered_by_variant_then_link(self, round_rows):
        keys = [
            (
                R.SERIES_VARIANTS.index(row["series_variant"]),
                int(row["link_sequence"]),
            )
            for row in round_rows
        ]
        assert keys == sorted(keys)

    def test_the_primary_series_is_emitted_first(self, round_rows):
        emitted = []
        for row in round_rows:
            if row["series_variant"] not in emitted:
                emitted.append(row["series_variant"])
        assert emitted == list(R.SERIES_VARIANTS)

    def test_components_are_ordered_by_numeric_basket_rank(
        self, component_rows
    ):
        keys = [
            (
                R.SERIES_VARIANTS.index(row["series_variant"]),
                int(row["link_sequence"]),
                int(row["basket_rank"]),
            )
            for row in component_rows
        ]
        assert keys == sorted(keys)

    def test_basket_rank_ordering_is_numeric_not_lexical(self, coverage_rows):
        ranks = [
            int(row["basket_rank"])
            for row in coverage_rows
            if row["series_variant"] == R.SERIES_VARIANT_PRIMARY
            and row["collection_round_id"] == EXPECTED_BASE_ROUND_ID
        ]
        assert ranks == sorted(ranks)
        assert ranks == list(range(1, EXPECTED_BASKET_ROUTES + 1))

    def test_item_rows_are_ordered_by_identity_not_status(
        self, relative_rows
    ):
        keys = [
            (
                R.SERIES_VARIANTS.index(row["series_variant"]),
                int(row["link_sequence"]),
                int(row["basket_rank"]),
                row["fare_class"],
                row["advance_purchase_window"],
                row["travel_date"],
            )
            for row in relative_rows
        ]
        assert keys == sorted(keys)

    def test_item_rows_are_unique_per_link(self, relative_rows):
        keys = [
            (row["series_variant"], row["link_sequence"], row["item_id"])
            for row in relative_rows
        ]
        assert len(set(keys)) == len(keys)

    def test_unaligned_diagnostics_are_ordered_by_round(self, unaligned_rows):
        keys = [row["round_sort_key"] for row in unaligned_rows]
        assert keys == sorted(keys)

    def test_reversing_the_input_changes_nothing(
        self, grain_a, basket, phase10_coverage, result
    ):
        reversed_result = engine.aggregate(
            list(reversed(grain_a)), basket, phase10_coverage
        )
        assert reversed_result["round_index"] == result["round_index"]
        assert reversed_result["route_components"] == (
            result["route_components"]
        )
        assert reversed_result["item_relatives"] == result["item_relatives"]

    def test_rotating_the_input_changes_nothing(
        self, grain_a, basket, phase10_coverage, result
    ):
        midpoint = len(grain_a) // 2
        rotated = list(grain_a[midpoint:]) + list(grain_a[:midpoint])
        rotated_result = engine.aggregate(rotated, basket, phase10_coverage)
        assert rotated_result["period_index"] == result["period_index"]
        assert rotated_result["index_coverage"] == result["index_coverage"]
        assert rotated_result["index_lineage"] == result["index_lineage"]

    def test_reversing_the_basket_changes_nothing(
        self, grain_a, basket, phase10_coverage, result
    ):
        reversed_basket_result = engine.aggregate(
            grain_a, list(reversed(basket)), phase10_coverage
        )
        assert reversed_basket_result["round_index"] == result["round_index"]

    def test_recomputation_matches_the_published_round_index(
        self, result, round_rows
    ):
        assert len(result["round_index"]) == len(round_rows)
        for computed, published in zip(result["round_index"], round_rows):
            assert computed["collection_round_id"] == (
                published["collection_round_id"]
            )
            assert computed["index_level"] == published["index_level"]

    def test_published_row_counts_are_stable(
        self,
        round_rows,
        component_rows,
        relative_rows,
        coverage_rows,
        lineage_rows,
    ):
        assert len(round_rows) == EXPECTED_ROUND_INDEX_ROWS
        assert len(component_rows) == EXPECTED_ROUTE_COMPONENT_ROWS
        assert len(relative_rows) == EXPECTED_ITEM_RELATIVE_ROWS
        assert len(coverage_rows) == EXPECTED_INDEX_COVERAGE_ROWS
        assert len(lineage_rows) == EXPECTED_INDEX_LINEAGE_ROWS


# ---------------------------------------------------------------------------
# Lineage reconciliation
# ---------------------------------------------------------------------------


class TestLineageReconciliation:
    def test_lineage_holds_exactly_the_matched_items(
        self, lineage_rows, relative_rows
    ):
        matched = {
            (row["series_variant"], row["link_sequence"], row["item_id"])
            for row in relative_rows
            if row["item_status"] == R.ITEM_STATUS_MATCHED
        }
        lineage = {
            (row["series_variant"], row["link_sequence"], row["item_id"])
            for row in lineage_rows
        }
        assert lineage == matched

    def test_lineage_fares_match_the_item_table(
        self, lineage_rows, relative_rows
    ):
        indexed = {
            (row["series_variant"], row["link_sequence"], row["item_id"]): row
            for row in relative_rows
        }
        for row in lineage_rows:
            item = indexed[
                (row["series_variant"], row["link_sequence"], row["item_id"])
            ]
            assert row["prev_fare"] == item["prev_fare"]
            assert row["curr_fare"] == item["curr_fare"]

    def test_lineage_names_both_rounds_of_each_link(self, lineage_rows):
        for row in lineage_rows:
            assert row["prev_round_id"] != ""
            assert row["curr_round_id"] != ""
            assert row["prev_round_id"] != row["curr_round_id"]

    def test_lineage_carries_phase10_observation_ids(self, lineage_rows):
        for row in lineage_rows:
            assert row["prev_contributing_observation_ids"] != ""
            assert row["curr_contributing_observation_ids"] != ""

    def test_lineage_carries_the_contribution_weight(self, lineage_rows):
        for row in lineage_rows:
            assert dec(row["contribution_weight"]) > 0

    def test_lineage_reconciles_with_published_matched_counts(
        self, lineage_rows, primary_rounds
    ):
        for row in primary_rounds[1:]:
            counted = len(
                [
                    entry
                    for entry in lineage_rows
                    if entry["series_variant"] == row["series_variant"]
                    and entry["link_sequence"] == row["link_sequence"]
                ]
            )
            assert counted == int(row["matched_product_count"])

    def test_lineage_identity_columns_agree_with_the_item_id(
        self, lineage_rows
    ):
        for row in lineage_rows:
            assert row["item_id"] == R.item_id(
                (
                    row["route_id"],
                    row["fare_class"],
                    row["advance_purchase_window"],
                    row["travel_date"],
                )
            )

    def test_lineage_is_ordered_deterministically(self, lineage_rows):
        keys = [
            (
                R.SERIES_VARIANTS.index(row["series_variant"]),
                int(row["link_sequence"]),
                int(row["basket_rank"]),
                row["route_id"],
                row["fare_class"],
                row["advance_purchase_window"],
                row["travel_date"],
            )
            for row in lineage_rows
        ]
        assert keys == sorted(keys)


# ---------------------------------------------------------------------------
# Basket immutability and Phase 1-10 immutability
# ---------------------------------------------------------------------------


class TestImmutability:
    def test_the_locked_basket_digest_is_unchanged(self):
        assert sha256_of(BASKET_PATH) == R.BASKET_LOCKED_SHA256

    def test_the_basket_still_holds_fifteen_routes(self, basket):
        assert len(basket) == EXPECTED_BASKET_ROUTES
        assert R.BASKET_ROUTE_COUNT_EXPECTED == EXPECTED_BASKET_ROUTES

    def test_the_basket_weights_still_sum_to_one(self, basket_weights):
        total = Decimal(0)
        for route_id in sorted(basket_weights):
            total = total + basket_weights[route_id]
        assert close_enough(total, Decimal(1), "0.0000001")

    def test_basket_ranks_are_one_through_fifteen(self, basket):
        ranks = sorted(int(entry["basket_rank"]) for entry in basket)
        assert ranks == list(range(1, EXPECTED_BASKET_ROUTES + 1))

    def test_route_ids_come_from_the_phase_5_source_of_truth(self):
        assert "make_route_id" in R.ROUTE_ID_SOURCE_OF_TRUTH

    def test_phase_11_never_modifies_phases_1_to_10(self):
        assert R.MODIFIES_PHASE_1_TO_10 is False

    def test_running_the_engine_leaves_phase_10_files_byte_identical(
        self, grain_a, basket, phase10_coverage
    ):
        before = {
            path: sha256_of(path) for path in PHASE10_PROTECTED_FILES
        }
        engine.aggregate(grain_a, basket, phase10_coverage)
        after = {path: sha256_of(path) for path in PHASE10_PROTECTED_FILES}
        assert after == before

    def test_the_engine_never_opens_a_phase_10_file_for_writing(self):
        source = read_text(os.path.join(SRC_DIR, "index_engine.py"))
        for marker in ("phase10_route_series", "phase10_coverage_report"):
            for line in source.splitlines():
                if marker in line:
                    assert '"w"' not in line

    def test_the_engine_writes_only_phase11_outputs(self):
        source = read_text(os.path.join(SRC_DIR, "index_engine.py"))
        for line in source.splitlines():
            if ".csv" in line and "phase11" not in line:
                assert "phase10" in line or "basket" in line or "#" in line


# ---------------------------------------------------------------------------
# No machine learning, no randomness, no binary floats
# ---------------------------------------------------------------------------


class TestSourceGuards:
    def test_no_banned_construct_appears_in_any_phase11_source_file(self):
        for path in PHASE11_SOURCE_FILES:
            source = read_text(path)
            for token in BANNED_SOURCE_TOKENS:
                assert token not in source, (path, token)

    def test_no_phase11_source_file_names_the_forbidden_field_as_a_column(
        self,
    ):
        for path in PHASE11_SOURCE_FILES:
            source = read_text(path)
            assert '"' + FORBIDDEN_FIELD_TOKEN + '"' not in source

    def test_no_machine_learning_or_randomness_flags_are_set(self):
        assert R.USES_MACHINE_LEARNING is False
        assert R.USES_RANDOMNESS is False

    def test_all_declared_guard_flags_are_false(self):
        flags = [
            name
            for name in dir(R)
            if name.startswith("USES_")
            or name.startswith("SUBSTITUTES_")
            or name.startswith("MODIFIES_")
            or name.startswith("REDISTRIBUTES_")
            or name.startswith("SUPPRESSES_")
            or name.startswith("APPLIES_")
            or name.startswith("SEVERITY_DETERMINES_")
        ]
        assert flags
        for name in flags:
            assert getattr(R, name) is False, name

    def test_arithmetic_is_decimal_end_to_end(self, result):
        for row in result["round_index"]:
            assert isinstance(row["index_level"], str)
        levels = result["chains"][R.SERIES_VARIANT_PRIMARY]["levels"]
        for _key, level in levels:
            assert isinstance(level, Decimal)

    def test_no_attribute_style_row_access_is_used(self):
        for path in PHASE11_SOURCE_FILES:
            for line in read_text(path).splitlines():
                assert "row." + "get(" not in line
                assert "record." + "get(" not in line

    def test_the_engine_is_importable_without_side_effects(self):
        assert engine.ROUND_INDEX_COLUMNS
        assert engine.ALL_OUTPUT_COLUMN_SETS


# ---------------------------------------------------------------------------
# D12: methodology documentation disclosures
# ---------------------------------------------------------------------------


class TestMethodologyDisclosure:
    @pytest.fixture(scope="class")
    def methodology(self):
        return read_text(METHODOLOGY_PATH)

    def test_the_methodology_document_exists(self):
        assert os.path.isfile(METHODOLOGY_PATH)

    def test_it_discloses_the_basket_weight_representation(self, methodology):
        assert "27.3706" in methodology

    def test_it_discloses_two_of_fifteen_routes(self, methodology):
        assert "2 of 15" in methodology

    def test_it_discloses_the_synthetic_data_status(self, methodology):
        assert "synthetic" in methodology.lower()

    def test_it_discloses_the_maturity_ramp_limitation(self, methodology):
        assert "maturity" in methodology.lower()

    def test_it_discloses_the_seven_unaligned_rounds(self, methodology):
        assert "7 unaligned" in methodology

    def test_it_discloses_the_absence_of_mospi_endorsement(self, methodology):
        assert "not endorsed by MoSPI" in methodology

    def test_it_discloses_the_prototype_nature(self, methodology):
        assert "prototype" in methodology.lower()

    def test_it_names_the_method_weighted_jevons(self, methodology):
        assert "weighted Jevons" in methodology

    def test_it_states_the_base_level(self, methodology):
        assert "100.000000" in methodology

    def test_it_never_claims_official_endorsement(self, methodology):
        lowered = methodology.lower()
        assert "officially endorsed" not in lowered
        assert "official statistic." not in lowered

    def test_it_does_not_name_the_forbidden_field_as_an_output(
        self, methodology
    ):
        assert "`" + FORBIDDEN_FIELD_TOKEN + "`" not in methodology

    def test_it_documents_the_approved_status_field(self, methodology):
        assert "index_eligibility_status" in methodology


# ---------------------------------------------------------------------------
# Banned weight vocabulary in published columns
# ---------------------------------------------------------------------------


class TestNoBannedWeightColumns:
    def test_no_output_header_publishes_a_banned_weight_column(self):
        paths = (
            ROUND_INDEX_PATH,
            ROUTE_COMPONENTS_PATH,
            ITEM_RELATIVES_PATH,
            PERIOD_INDEX_PATH,
            INDEX_COVERAGE_PATH,
            INDEX_LINEAGE_PATH,
            UNALIGNED_PATH,
        )
        for path in paths:
            with open(path, "r", encoding="utf-8-sig", newline="") as handle:
                header = next(csv.reader(handle))
            for token in BANNED_OUTPUT_WEIGHT_TOKENS:
                assert token not in header, (path, token)

    def test_no_declared_column_tuple_holds_a_banned_weight_column(self):
        for columns in engine.ALL_OUTPUT_COLUMN_SETS:
            for token in BANNED_OUTPUT_WEIGHT_TOKENS:
                assert token not in columns, token

    def test_every_banned_weight_token_is_declared_forbidden_in_rules(self):
        for token in BANNED_OUTPUT_WEIGHT_TOKENS:
            assert token in R.FORBIDDEN_OUTPUT_FIELDS

    def test_the_only_published_weight_columns_are_the_approved_ones(self):
        approved = {
            "traffic_weight",
            "traffic_weight_is_metadata_only",
            "renormalized_weight",
            "contribution_weight",
            "basket_weight_represented",
            "basket_weight_missing",
            "effective_weight_sum",
            "weight_represented",
            "weight_excluded",
            "weight_basis",
            "weight_application",
            "within_route_weighting",
            "weighted_log_contribution",
        }
        for columns in engine.ALL_OUTPUT_COLUMN_SETS:
            for column in columns:
                if "weight" in column:
                    assert column in approved, column
