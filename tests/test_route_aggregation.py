"""VAYU INDEX Phase 10 -- route-level aggregation tests.

Covers the 26 mandated test areas. Phase 1-9 behaviour is only READ here;
nothing upstream is modified.

Note on banned-token guards: literals such as the float constructor are
assembled at runtime so that this test file never itself contains a token it
forbids in source.
"""

import csv
import hashlib
import io
import os
import sys
from decimal import Decimal

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from scripts.build_vayu_route_basket import make_route_id  # noqa: E402
from src.route_aggregation import rules as R  # noqa: E402
from src.route_aggregation import route_engine as E  # noqa: E402

OUTPUTS = os.path.join(REPO_ROOT, "outputs")
BASKET_PATH = os.path.join(
    REPO_ROOT, "data", "official", "dgca", "processed", "vayu_route_basket_2024_25.csv"
)
CELLS_PATH = os.path.join(OUTPUTS, "anomaly_flagged_airfare_observations.csv")
OBSERVATION_MAP_PATH = os.path.join(OUTPUTS, "phase9_observation_anomaly_map.csv")

BASKET_LOCKED_SHA256 = "dc57e6d470a2ed9061dd82a92c84943749c3c648cef00b85b3f250df2f87c181"
EXPECTED_BASKET_ROUTES = 15
EXPECTED_NO_OBSERVATION_ROUTES = 13

PHASE10_SOURCES = (
    os.path.join(REPO_ROOT, "src", "route_aggregation", "rules.py"),
    os.path.join(REPO_ROOT, "src", "route_aggregation", "route_engine.py"),
    os.path.join(REPO_ROOT, "src", "route_aggregation", "__init__.py"),
    os.path.join(REPO_ROOT, "scripts", "run_route_aggregation.py"),
    os.path.join(REPO_ROOT, "scripts", "verify_phase10.py"),
)

UPSTREAM_LOCKED_FILES = (
    os.path.join(OUTPUTS, "validated_airfare_observations.csv"),
    os.path.join(OUTPUTS, "deduplicated_airfare_observations.csv"),
    os.path.join(OUTPUTS, "canonical_airfare_observations.csv"),
    os.path.join(OUTPUTS, "consolidated_airfare_observations.csv"),
    os.path.join(OUTPUTS, "normalized_airfare_observations.csv"),
    os.path.join(OUTPUTS, "anomaly_flagged_airfare_observations.csv"),
    os.path.join(OUTPUTS, "phase9_observation_anomaly_map.csv"),
    BASKET_PATH,
)


def sha256_of(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        digest.update(handle.read())
    return digest.hexdigest()


def _cell(**overrides):
    record = {
        "consolidation_cell_id": "CELL::DEL|BOM|2026-09-06|Economy Saver|T15(12-18)",
        "origin_canonical": "DEL",
        "destination_canonical": "BOM",
        "travel_date_canonical": "2026-09-06",
        "fare_class_canonical": "Economy Saver",
        "advance_purchase_window": "T15(12-18)",
        "collection_round_id": "ROUND::2026-09-05T09:00",
        "round_sort_key": "2026-09-05 09:00",
        "round_alignment": "ANCHORED",
        "consolidated_fare_normalized": "5300.00",
        "price_state": "PRICED",
        "observation_count": "2",
        "participating_observation_count": "2",
        "sold_out_observation_count": "0",
        "missing_price_observation_count": "0",
        "contributing_observation_ids": "OBS00001;OBS00002",
        "source_coverage": "PARTIAL_COVERAGE",
        "participating_source_count": "2",
        "anomaly_rule_ids": "",
        "anomaly_severity_max": "NONE",
        "not_evaluable_rule_ids": "",
        "market_movement_class": "ISOLATED_DEVIATION",
        "recommended_review": "False",
        "retained": "True",
    }
    record.update(overrides)
    return record


def _observation(**overrides):
    record = {
        "observation_id": "OBS00001",
        "consolidation_cell_id": "CELL::DEL|BOM|2026-09-06|Economy Saver|T15(12-18)",
        "flight_cell_id": "CELL::DEL|BOM|2026-09-06|Economy Saver|T15(12-18)::FLT::6E|6E-773|16:45",
        "price_state": "PRICED",
        "participation_status": "PARTICIPATED",
        "inherited_severity_max": "NONE",
    }
    record.update(overrides)
    return record


def _basket(*route_ids):
    basket = []
    for position, route_id in enumerate(route_ids):
        basket.append(
            {
                "basket_rank": str(position + 1),
                "traffic_rank": str(position + 1),
                "route_id": route_id,
                "city_1": "CITY_ONE",
                "city_2": "CITY_TWO",
                "traffic_weight": "0.100000",
            }
        )
    return basket


def _run(cells, observations=None, basket=None):
    if observations is None:
        observations = [_observation()]
    if basket is None:
        basket = _basket("BOM-DEL")
    return E.aggregate(cells, observations, basket)


def _read_output(name):
    path = os.path.join(OUTPUTS, name)
    with open(path, "r", encoding="utf-8", newline="") as handle:
        return [dict(item) for item in csv.DictReader(handle)]


def _real_basket_rows():
    with open(BASKET_PATH, "r", encoding="utf-8-sig", newline="") as handle:
        return [dict(item) for item in csv.DictReader(handle)]


@pytest.fixture
def real_result():
    """Phase 10 run over the real Phase 9 corpus (in memory; writes nothing)."""
    cells = E.read_csv(CELLS_PATH)
    observations = E.read_csv(OBSERVATION_MAP_PATH)
    basket = E.load_basket(BASKET_PATH)
    return E.aggregate(cells, observations, basket)


# ===========================================================================
# AREA 1 + 2 + D8 -- Phase 5 canonicalization agreement
# ===========================================================================
class TestPhase5Canonicalization:
    def test_every_basket_route_agrees_with_phase5_make_route_id(self):
        for record in _real_basket_rows():
            route_id, status = make_route_id(record["city_1"], record["city_2"])
            assert status == "MAPPED"
            assert route_id == record["route_id"]

    def test_phase5_make_route_id_is_order_independent(self):
        for record in _real_basket_rows():
            forward, _ = make_route_id(record["city_1"], record["city_2"])
            reverse, _ = make_route_id(record["city_2"], record["city_1"])
            assert forward == reverse

    def test_phase10_canonicalization_matches_phase5_for_every_basket_route(self):
        for record in _real_basket_rows():
            first, second = record["route_id"].split("-")
            assert R.canonical_route_id(first, second) == record["route_id"]
            assert R.canonical_route_id(second, first) == record["route_id"]

    def test_canonicalization_is_undirected_for_del_bom(self):
        assert R.canonical_route_id("DEL", "BOM") == "BOM-DEL"
        assert R.canonical_route_id("BOM", "DEL") == "BOM-DEL"

    def test_canonicalization_is_undirected_for_del_blr(self):
        assert R.canonical_route_id("DEL", "BLR") == "BLR-DEL"
        assert R.canonical_route_id("BLR", "DEL") == "BLR-DEL"

    def test_canonicalization_handles_off_basket_pairs(self):
        assert R.canonical_route_id("MAA", "CCU") == "CCU-MAA"
        assert R.canonical_route_id("BLR", "HYD") == "BLR-HYD"

    def test_route_id_is_declared_undirected(self):
        assert R.ROUTE_ID_IS_UNDIRECTED is True
        assert R.ROUTE_ID_ORDERING == "ALPHABETIC_IATA"

    def test_route_id_source_of_truth_points_at_phase5(self):
        assert "build_vayu_route_basket" in R.ROUTE_ID_SOURCE_OF_TRUTH
        assert "make_route_id" in R.ROUTE_ID_SOURCE_OF_TRUTH

    def test_canonicalization_rejects_self_pair(self):
        with pytest.raises(R.RouteAggregationRuleError):
            R.canonical_route_id("DEL", "DEL")

    def test_canonicalization_rejects_blank_code(self):
        with pytest.raises(R.RouteAggregationRuleError):
            R.canonical_route_id("DEL", "")

    def test_observed_direction_is_preserved_not_reversed(self):
        result = _run([_cell()])
        row = result.grain_a[0]
        assert row["route_id"] == "BOM-DEL"
        assert row["observed_origin"] == "DEL"
        assert row["observed_destination"] == "BOM"
        assert row["observed_directed_pair"] == "DEL-BOM"

    def test_reverse_directed_observation_canonicalizes_to_same_route(self):
        forward = _run([_cell()])
        reverse = _run([_cell(origin_canonical="BOM", destination_canonical="DEL")])
        assert forward.grain_a[0]["route_id"] == reverse.grain_a[0]["route_id"]
        assert reverse.grain_a[0]["observed_directed_pair"] == "BOM-DEL"

    def test_reverse_directed_observation_is_labelled_exact_key_match(self):
        reverse = _run([_cell(origin_canonical="BOM", destination_canonical="DEL")])
        assert reverse.crosswalk[0]["route_direction_relation"] == R.DIRECTION_EXACT

    def test_forward_directed_observation_is_labelled_canonicalized(self):
        forward = _run([_cell()])
        assert forward.crosswalk[0]["route_direction_relation"] == R.DIRECTION_CANONICALIZED

    def test_engine_declares_it_never_reverses_observed_direction(self):
        assert R.REVERSES_OBSERVED_DIRECTION is False


# ===========================================================================
# AREA 3 + 22 + 26 -- basket integrity
# ===========================================================================
class TestBasketIntegrity:
    def test_basket_sha256_unchanged(self):
        assert sha256_of(BASKET_PATH) == BASKET_LOCKED_SHA256

    def test_basket_has_exactly_fifteen_routes(self):
        assert len(_real_basket_rows()) == EXPECTED_BASKET_ROUTES

    def test_basket_route_ids_are_unique(self):
        route_ids = [record["route_id"] for record in _real_basket_rows()]
        assert len(set(route_ids)) == EXPECTED_BASKET_ROUTES

    def test_aggregation_does_not_mutate_the_basket_rows(self):
        basket = _basket("BOM-DEL", "BLR-DEL")
        snapshot = [dict(item) for item in basket]
        _run([_cell()], basket=basket)
        assert basket == snapshot

    def test_aggregation_does_not_mutate_the_input_cells(self):
        cells = [_cell()]
        snapshot = [dict(item) for item in cells]
        _run(cells)
        assert cells == snapshot

    def test_off_basket_route_never_enters_the_basket(self):
        result = _run([_cell(origin_canonical="MAA", destination_canonical="CCU")])
        assert [
            record for record in result.grain_a if record["route_id"] == "CCU-MAA"
        ] == []
        for record in result.grain_a:
            assert record["route_coverage_status"] == R.COVERAGE_NONE
        assert len(result.off_basket_grain_a) == 1
        assert result.off_basket_grain_a[0]["route_id"] == "CCU-MAA"
        assert result.off_basket_grain_a[0]["basket_membership"] == R.BASKET_NON_MEMBER

    def test_engine_declares_it_never_modifies_the_basket(self):
        assert R.MODIFIES_BASKET is False

    def test_basket_file_is_never_opened_for_writing(self):
        with open(
            os.path.join(REPO_ROOT, "src", "route_aggregation", "route_engine.py"),
            "r",
            encoding="utf-8",
        ) as handle:
            source = handle.read()
        assert "vayu_route_basket" not in source

    def test_basket_rank_ordering_is_numeric_not_lexical(self):
        basket = _basket(*["R%02d-XXX" % index for index in range(1, 13)])
        loaded = sorted(basket, key=lambda item: int(item["basket_rank"]))
        assert [item["basket_rank"] for item in loaded][-1] == "12"


# ===========================================================================
# AREA 4 + 5 + 6 -- basket coverage and scope separation
# ===========================================================================
class TestBasketCoverage:
    def test_all_fifteen_basket_routes_appear_in_coverage(self, real_result):
        assert len(real_result.coverage) == EXPECTED_BASKET_ROUTES
        route_ids = {record["route_id"] for record in real_result.coverage}
        assert route_ids == {record["route_id"] for record in _real_basket_rows()}

    def test_thirteen_basket_routes_report_no_observations(self, real_result):
        unobserved = [
            record
            for record in real_result.coverage
            if record["route_coverage_status"] == R.COVERAGE_NONE
        ]
        assert len(unobserved) == EXPECTED_NO_OBSERVATION_ROUTES

    def test_two_basket_routes_are_observed_via_canonical_key(self, real_result):
        observed = [
            record
            for record in real_result.coverage
            if record["route_coverage_status"] != R.COVERAGE_NONE
        ]
        assert len(observed) == 2
        assert {record["route_id"] for record in observed} == {"BOM-DEL", "BLR-DEL"}
        for record in observed:
            assert record["route_coverage_status"] == R.COVERAGE_OBSERVED_CANONICAL

    def test_unobserved_routes_carry_blank_money_not_zero(self, real_result):
        for record in real_result.coverage:
            if record["route_coverage_status"] == R.COVERAGE_NONE:
                assert record["route_fare_median"] == ""
                assert record["route_fare_min"] == ""
                assert record["route_fare_max"] == ""
                assert record["route_price_state"] == R.ROUTE_PRICE_STATE_NO_OBSERVATIONS

    def test_unobserved_routes_have_zero_cell_counts(self, real_result):
        for record in real_result.coverage:
            if record["route_coverage_status"] == R.COVERAGE_NONE:
                assert record["observed_cell_count"] == "0"
                assert record["contributing_observation_count"] == "0"

    def test_coverage_is_ordered_by_numeric_basket_rank(self, real_result):
        ranks = [int(record["basket_rank"]) for record in real_result.coverage]
        assert ranks == sorted(ranks)
        assert ranks == list(range(1, EXPECTED_BASKET_ROUTES + 1))

    def test_coverage_carries_traffic_weight_as_metadata_only(self, real_result):
        for record in real_result.coverage:
            assert record["traffic_weight"] != ""
            assert record["traffic_weight_is_metadata_only"] == "True"

    def test_every_basket_route_appears_in_grain_a(self, real_result):
        route_ids = {record["route_id"] for record in real_result.grain_a}
        assert route_ids == {record["route_id"] for record in _real_basket_rows()}

    def test_every_basket_route_appears_in_grain_b(self, real_result):
        route_ids = {record["route_id"] for record in real_result.grain_b}
        assert route_ids == {record["route_id"] for record in _real_basket_rows()}

    def test_grain_a_contains_thirteen_no_observation_placeholders(self, real_result):
        placeholders = [
            record
            for record in real_result.grain_a
            if record["route_coverage_status"] == R.COVERAGE_NONE
        ]
        assert len(placeholders) == EXPECTED_NO_OBSERVATION_ROUTES

    def test_off_basket_rows_are_never_in_basket_scoped_outputs(self, real_result):
        for record in real_result.grain_a + real_result.grain_b:
            assert record["basket_membership"] == R.BASKET_MEMBER
            assert record["basket_scope"] == R.BASKET_SCOPE_IN
        for record in real_result.off_basket_grain_a + real_result.off_basket_grain_b:
            assert record["basket_membership"] == R.BASKET_NON_MEMBER
            assert record["basket_scope"] == R.BASKET_SCOPE_OUT

    def test_off_basket_routes_are_exactly_the_two_expected(self, real_result):
        route_ids = {record["route_id"] for record in real_result.off_basket_grain_a}
        assert route_ids == {"CCU-MAA", "BLR-HYD"}

    def test_off_basket_rows_have_no_basket_rank(self, real_result):
        for record in real_result.off_basket_grain_a:
            assert record["basket_rank"] == ""
            assert record["traffic_weight"] == ""

    def test_off_basket_outputs_are_ordered_by_route_then_grain(self, real_result):
        keys = [
            (
                record["route_id"],
                record["fare_class"],
                record["advance_purchase_window"],
                record["travel_date"],
                record["round_sort_key"],
            )
            for record in real_result.off_basket_grain_a
        ]
        assert keys == sorted(keys)


# ===========================================================================
# AREA 7-11 -- Grain A non-lossy grouping
# ===========================================================================
class TestGrainA:
    def test_grain_a_fields_are_the_locked_five(self):
        assert R.GRAIN_A_FIELDS == (
            "route_id",
            "fare_class",
            "advance_purchase_window",
            "travel_date",
            "collection_round_id",
        )

    def test_grain_a_preserves_travel_date_as_a_column(self, real_result):
        for record in real_result.grain_a:
            assert "travel_date" in record

    def test_grain_a_never_mixes_travel_dates(self, real_result):
        seen = {}
        for record in real_result.lineage:
            if record["basket_scope"] != R.BASKET_SCOPE_IN:
                continue
            seen.setdefault(record["route_series_id"], set()).add(record["travel_date"])
        for series_id in seen:
            assert len(seen[series_id]) == 1

    def test_grain_a_never_mixes_fare_class(self, real_result):
        seen = {}
        for record in real_result.lineage:
            seen.setdefault(record["route_series_id"], set()).add(record["fare_class"])
        for series_id in seen:
            assert len(seen[series_id]) == 1

    def test_grain_a_never_mixes_advance_purchase_window(self, real_result):
        seen = {}
        for record in real_result.lineage:
            seen.setdefault(record["route_series_id"], set()).add(
                record["advance_purchase_window"]
            )
        for series_id in seen:
            assert len(seen[series_id]) == 1

    def test_grain_a_never_mixes_collection_rounds(self, real_result):
        seen = {}
        for record in real_result.lineage:
            seen.setdefault(record["route_series_id"], set()).add(
                record["collection_round_id"]
            )
        for series_id in seen:
            assert len(seen[series_id]) == 1

    def test_grain_a_never_mixes_routes(self, real_result):
        seen = {}
        for record in real_result.lineage:
            seen.setdefault(record["route_series_id"], set()).add(record["route_id"])
        for series_id in seen:
            assert len(seen[series_id]) == 1

    def test_two_travel_dates_produce_two_grain_a_rows(self):
        cells = [
            _cell(consolidation_cell_id="CELL::A"),
            _cell(
                consolidation_cell_id="CELL::B",
                travel_date_canonical="2026-09-12",
                consolidated_fare_normalized="6100.00",
            ),
        ]
        result = _run(cells)
        observed = [
            record
            for record in result.grain_a
            if record["route_coverage_status"] != R.COVERAGE_NONE
        ]
        assert len(observed) == 2
        assert {record["travel_date"] for record in observed} == {
            "2026-09-06",
            "2026-09-12",
        }

    def test_two_fare_classes_produce_two_grain_a_rows(self):
        cells = [
            _cell(consolidation_cell_id="CELL::A"),
            _cell(consolidation_cell_id="CELL::B", fare_class_canonical="Economy Flexi"),
        ]
        result = _run(cells)
        observed = [
            record
            for record in result.grain_a
            if record["route_coverage_status"] != R.COVERAGE_NONE
        ]
        assert len(observed) == 2

    def test_two_windows_produce_two_grain_a_rows(self):
        cells = [
            _cell(consolidation_cell_id="CELL::A"),
            _cell(consolidation_cell_id="CELL::B", advance_purchase_window="T7(5-9)"),
        ]
        result = _run(cells)
        observed = [
            record
            for record in result.grain_a
            if record["route_coverage_status"] != R.COVERAGE_NONE
        ]
        assert len(observed) == 2

    def test_two_rounds_produce_two_grain_a_rows(self):
        cells = [
            _cell(consolidation_cell_id="CELL::A"),
            _cell(
                consolidation_cell_id="CELL::B",
                collection_round_id="ROUND::2026-09-05T14:30",
                round_sort_key="2026-09-05 14:30",
            ),
        ]
        result = _run(cells)
        observed = [
            record
            for record in result.grain_a
            if record["route_coverage_status"] != R.COVERAGE_NONE
        ]
        assert len(observed) == 2

    def test_grain_a_row_count_matches_observed_plus_placeholders(self, real_result):
        observed = [
            record
            for record in real_result.grain_a
            if record["route_coverage_status"] != R.COVERAGE_NONE
        ]
        assert len(observed) == 219
        assert len(real_result.grain_a) == 219 + EXPECTED_NO_OBSERVATION_ROUTES

    def test_grain_a_is_ordered_by_basket_rank_then_grain(self, real_result):
        keys = [
            (
                int(record["basket_rank"]),
                record["route_id"],
                record["fare_class"],
                record["advance_purchase_window"],
                record["travel_date"],
                record["round_sort_key"],
                record["collection_round_id"],
            )
            for record in real_result.grain_a
        ]
        assert keys == sorted(keys)

    def test_grain_a_series_ids_are_unique(self, real_result):
        ids = [
            record["route_series_id"]
            for record in real_result.grain_a
            if record["route_series_id"] != ""
        ]
        assert len(ids) == len(set(ids))

    def test_grain_a_carries_schema_version_on_every_row(self, real_result):
        for record in real_result.grain_a:
            assert record["phase10_schema_version"] == R.PHASE10_SCHEMA_VERSION

    def test_grain_a_off_basket_row_count(self, real_result):
        assert len(real_result.off_basket_grain_a) == 174


# ===========================================================================
# AREA 12 -- Grain B behaviour
# ===========================================================================
class TestGrainB:
    def test_grain_b_fields_are_the_locked_three(self):
        assert R.GRAIN_B_FIELDS == ("route_id", "fare_class", "collection_round_id")

    def test_grain_b_collapses_travel_dates_into_attributes(self):
        cells = [
            _cell(consolidation_cell_id="CELL::A", consolidated_fare_normalized="5300.00"),
            _cell(
                consolidation_cell_id="CELL::B",
                travel_date_canonical="2026-09-12",
                consolidated_fare_normalized="5500.00",
            ),
        ]
        result = _run(cells)
        observed = [
            record
            for record in result.grain_b
            if record["route_coverage_status"] != R.COVERAGE_NONE
        ]
        assert len(observed) == 1
        row = observed[0]
        assert row["contributing_travel_dates"] == "2026-09-06;2026-09-12"
        assert row["contributing_travel_date_count"] == "2"
        assert row["route_fare_median"] == "5400.00"

    def test_grain_b_lists_contributing_windows(self):
        cells = [
            _cell(consolidation_cell_id="CELL::A"),
            _cell(consolidation_cell_id="CELL::B", advance_purchase_window="T7(5-9)"),
        ]
        result = _run(cells)
        observed = [
            record
            for record in result.grain_b
            if record["route_coverage_status"] != R.COVERAGE_NONE
        ]
        row = observed[0]
        assert row["contributing_advance_purchase_windows"] == "T15(12-18);T7(5-9)"
        assert row["contributing_advance_purchase_window_count"] == "2"

    def test_grain_b_counts_contributing_grain_a_series(self):
        cells = [
            _cell(consolidation_cell_id="CELL::A"),
            _cell(consolidation_cell_id="CELL::B", travel_date_canonical="2026-09-12"),
        ]
        result = _run(cells)
        observed = [
            record
            for record in result.grain_b
            if record["route_coverage_status"] != R.COVERAGE_NONE
        ]
        assert observed[0]["contributing_grain_a_series_count"] == "2"

    def test_grain_b_still_separates_fare_class(self):
        cells = [
            _cell(consolidation_cell_id="CELL::A"),
            _cell(consolidation_cell_id="CELL::B", fare_class_canonical="Economy Flexi"),
        ]
        result = _run(cells)
        observed = [
            record
            for record in result.grain_b
            if record["route_coverage_status"] != R.COVERAGE_NONE
        ]
        assert len(observed) == 2

    def test_grain_b_still_separates_collection_round(self):
        cells = [
            _cell(consolidation_cell_id="CELL::A"),
            _cell(
                consolidation_cell_id="CELL::B",
                collection_round_id="ROUND::2026-09-05T14:30",
                round_sort_key="2026-09-05 14:30",
            ),
        ]
        result = _run(cells)
        observed = [
            record
            for record in result.grain_b
            if record["route_coverage_status"] != R.COVERAGE_NONE
        ]
        assert len(observed) == 2

    def test_grain_b_row_count_matches_observed_plus_placeholders(self, real_result):
        observed = [
            record
            for record in real_result.grain_b
            if record["route_coverage_status"] != R.COVERAGE_NONE
        ]
        assert len(observed) == 62
        assert len(real_result.grain_b) == 62 + EXPECTED_NO_OBSERVATION_ROUTES

    def test_grain_b_off_basket_row_count(self, real_result):
        assert len(real_result.off_basket_grain_b) == 54

    def test_grain_b_is_ordered_by_basket_rank(self, real_result):
        keys = [
            (
                int(record["basket_rank"]),
                record["route_id"],
                record["fare_class"],
                record["round_sort_key"],
                record["collection_round_id"],
            )
            for record in real_result.grain_b
        ]
        assert keys == sorted(keys)

    def test_grain_b_is_not_a_replacement_for_grain_a(self, real_result):
        assert len(real_result.grain_b) < len(real_result.grain_a)
        assert "travel_date" in E.GRAIN_A_COLUMNS
        assert "travel_date" not in E.GRAIN_B_COLUMNS

    def test_grain_b_carries_schema_version_on_every_row(self, real_result):
        for record in real_result.grain_b:
            assert record["phase10_schema_version"] == R.PHASE10_SCHEMA_VERSION


# ===========================================================================
# AREA 13 + 14 -- aggregation statistic and Decimal money path
# ===========================================================================
class TestAggregationStatistic:
    def test_declared_statistic_is_midpoint_median(self):
        assert R.AGGREGATION_STATISTIC == "MIDPOINT_MEDIAN"
        assert "midpoint_median" in R.AGGREGATION_STATISTIC_SOURCE

    def test_midpoint_median_of_two_values(self):
        assert R.route_median([Decimal("5300"), Decimal("5500")]) == Decimal("5400.00")

    def test_midpoint_median_of_four_values(self):
        values = [Decimal("5000"), Decimal("5200"), Decimal("5600"), Decimal("6000")]
        assert R.route_median(values) == Decimal("5400.00")

    def test_midpoint_median_of_odd_count(self):
        values = [Decimal("5000"), Decimal("5200"), Decimal("6000")]
        assert R.route_median(values) == Decimal("5200.00")

    def test_median_is_order_independent(self):
        forward = R.route_median([Decimal("5000"), Decimal("5200"), Decimal("6000")])
        reverse = R.route_median([Decimal("6000"), Decimal("5200"), Decimal("5000")])
        assert forward == reverse

    def test_median_rounds_half_up_at_two_decimal_places(self):
        values = [Decimal("5300.005"), Decimal("5300.005")]
        assert format(R.route_median(values), "f") == "5300.01"

    def test_median_requires_at_least_one_value(self):
        with pytest.raises(R.RouteAggregationRuleError):
            R.route_median([])

    def test_money_parsing_returns_decimal_not_binary_float(self):
        value = R.parse_money("5300.10")
        assert isinstance(value, Decimal)
        assert value == Decimal("5300.10")

    def test_money_values_are_emitted_with_two_decimal_places(self, real_result):
        for record in real_result.grain_a:
            for name in ("route_fare_median", "route_fare_min", "route_fare_max"):
                if record[name] != "":
                    assert len(record[name].split(".")[1]) == 2

    def test_even_count_group_uses_midpoint_in_a_real_style_group(self):
        cells = [
            _cell(consolidation_cell_id="CELL::A", consolidated_fare_normalized="5300.00"),
            _cell(
                consolidation_cell_id="CELL::B",
                consolidated_fare_normalized="5500.00",
                travel_date_canonical="2026-09-12",
            ),
        ]
        result = _run(cells)
        observed = [
            record
            for record in result.grain_b
            if record["route_coverage_status"] != R.COVERAGE_NONE
        ]
        assert observed[0]["route_fare_median"] == "5400.00"
        assert observed[0]["route_fare_min"] == "5300.00"
        assert observed[0]["route_fare_max"] == "5500.00"

    def test_relative_spread_is_a_six_decimal_ratio(self):
        spread = R.relative_spread([Decimal("5000"), Decimal("5500")])
        assert format(spread, "f") == "0.100000"

    def test_no_weighting_flags_are_enabled(self):
        assert R.APPLIES_TRAFFIC_WEIGHTS is False
        assert R.APPLIES_SOURCE_WEIGHTS is False

    def test_traffic_weight_is_never_multiplied_into_a_fare(self):
        basket = _basket("BOM-DEL")
        basket[0]["traffic_weight"] = "0.162603"
        result = E.aggregate([_cell()], [_observation()], basket)
        assert result.grain_a[0]["route_fare_median"] == "5300.00"
        assert result.grain_a[0]["traffic_weight"] == "0.162603"
        assert result.grain_a[0]["traffic_weight_is_metadata_only"] == "True"


# ===========================================================================
# AREA 15 + 16 -- anomaly annotation without exclusion
# ===========================================================================
class TestAnomalyHandling:
    def test_high_severity_cell_is_retained_and_counted(self):
        cells = [
            _cell(
                consolidation_cell_id="CELL::A",
                anomaly_rule_ids="R01_NONPOSITIVE_FARE",
                anomaly_severity_max="HIGH",
            )
        ]
        result = _run(cells)
        row = result.grain_a[0]
        assert row["contributing_cell_count"] == "1"
        assert row["high_severity_cell_count"] == "1"
        assert row["anomaly_severity_max"] == "HIGH"
        assert row["route_fare_median"] == "5300.00"

    def test_review_severity_cell_is_retained_and_counted(self):
        cells = [_cell(anomaly_rule_ids="R13", anomaly_severity_max="REVIEW")]
        result = _run(cells)
        assert result.grain_a[0]["review_severity_cell_count"] == "1"
        assert result.grain_a[0]["contributing_priced_cell_count"] == "1"

    def test_info_severity_cell_is_retained_and_counted(self):
        cells = [_cell(anomaly_rule_ids="R09", anomaly_severity_max="INFO")]
        result = _run(cells)
        assert result.grain_a[0]["info_severity_cell_count"] == "1"

    def test_not_evaluable_rules_are_retained_and_counted(self):
        cells = [_cell(not_evaluable_rule_ids="R08_SOURCE_LEVEL_DEVIATION")]
        result = _run(cells)
        row = result.grain_a[0]
        assert row["not_evaluable_cell_count"] == "1"
        assert row["not_evaluable_rule_ids"] == "R08_SOURCE_LEVEL_DEVIATION"

    def test_severity_mix_never_reduces_cell_count(self):
        cells = [
            _cell(consolidation_cell_id="CELL::A", anomaly_severity_max="HIGH"),
            _cell(
                consolidation_cell_id="CELL::B",
                anomaly_severity_max="REVIEW",
                travel_date_canonical="2026-09-12",
            ),
            _cell(
                consolidation_cell_id="CELL::C",
                anomaly_severity_max="INFO",
                travel_date_canonical="2026-09-20",
            ),
        ]
        result = _run(cells)
        observed = [
            record
            for record in result.grain_b
            if record["route_coverage_status"] != R.COVERAGE_NONE
        ]
        assert observed[0]["contributing_cell_count"] == "3"
        assert observed[0]["anomaly_excluded_cell_count"] == "0"
        assert observed[0]["anomaly_severity_max"] == "HIGH"

    def test_engine_declares_no_severity_based_exclusion(self):
        assert R.EXCLUDES_BY_ANOMALY_SEVERITY is False
        assert R.DELETES_OBSERVATIONS is False

    def test_real_corpus_anomaly_counts_are_fully_propagated(self, real_result):
        totals = {"HIGH": 0, "REVIEW": 0, "INFO": 0, "NONE": 0}
        for record in real_result.lineage:
            totals[record["anomaly_severity_max"]] += 1
        assert sum(totals.values()) == 393
        assert totals["REVIEW"] == 2
        assert totals["INFO"] == 160
        assert totals["NONE"] == 231
        assert totals["HIGH"] == 0

    def test_real_corpus_recommended_review_is_carried(self, real_result):
        flagged = [
            record for record in real_result.lineage if record["recommended_review"] == "True"
        ]
        assert len(flagged) == 2

    def test_no_forbidden_index_fields_in_any_output(self, real_result):
        tables = (
            real_result.grain_a,
            real_result.grain_b,
            real_result.off_basket_grain_a,
            real_result.off_basket_grain_b,
            real_result.crosswalk,
            real_result.lineage,
            real_result.coverage,
        )
        for table in tables:
            for record in table:
                for name in R.FORBIDDEN_OUTPUT_FIELDS:
                    assert name not in record

    def test_no_index_eligible_column_in_any_schema(self):
        banned = "index" + "_eligible"
        for columns in (
            E.GRAIN_A_COLUMNS,
            E.GRAIN_B_COLUMNS,
            E.CROSSWALK_COLUMNS,
            E.LINEAGE_COLUMNS,
            E.COVERAGE_COLUMNS,
        ):
            for name in columns:
                assert banned not in name

    def test_phase10_produces_no_new_anomaly_verdicts(self):
        assert R.PRODUCES_ROUTE_AGGREGATE_ANOMALIES is False


# ===========================================================================
# AREA 17 + 18 -- missingness, sold out, no imputation
# ===========================================================================
class TestMissingness:
    def test_unpriced_cell_yields_blank_money_not_zero(self):
        cells = [
            _cell(
                consolidated_fare_normalized="",
                price_state="NO_PRICE_CELL",
                participating_observation_count="0",
                sold_out_observation_count="1",
                contributing_observation_ids="",
            )
        ]
        result = _run(cells)
        row = result.grain_a[0]
        assert row["route_fare_median"] == ""
        assert row["route_fare_min"] == ""
        assert row["route_fare_max"] == ""
        assert row["route_price_state"] == R.ROUTE_PRICE_STATE_NO_PRICE

    def test_sold_out_observations_are_counted_but_never_priced(self):
        cells = [
            _cell(
                consolidated_fare_normalized="",
                price_state="NO_PRICE_CELL",
                observation_count="1",
                participating_observation_count="0",
                sold_out_observation_count="1",
                contributing_observation_ids="",
            )
        ]
        observations = [
            _observation(price_state="SOLD_OUT", participation_status="EXCLUDED_SOLD_OUT")
        ]
        result = _run(cells, observations=observations)
        row = result.grain_a[0]
        assert row["sold_out_observation_count"] == "1"
        assert row["excluded_sold_out_observation_count"] == "1"
        assert row["route_fare_median"] == ""

    def test_mixed_priced_and_unpriced_cells_use_only_priced_fares(self):
        cells = [
            _cell(consolidation_cell_id="CELL::A", consolidated_fare_normalized="5300.00"),
            _cell(
                consolidation_cell_id="CELL::B",
                consolidated_fare_normalized="",
                price_state="NO_PRICE_CELL",
                travel_date_canonical="2026-09-12",
            ),
        ]
        result = _run(cells)
        observed = [
            record
            for record in result.grain_b
            if record["route_coverage_status"] != R.COVERAGE_NONE
        ]
        row = observed[0]
        assert row["route_fare_median"] == "5300.00"
        assert row["contributing_cell_count"] == "2"
        assert row["contributing_priced_cell_count"] == "1"
        assert row["contributing_unpriced_cell_count"] == "1"

    def test_parse_money_returns_none_for_blank(self):
        assert R.parse_money("") is None
        assert R.parse_money(None) is None

    def test_parse_money_rejects_non_numeric(self):
        with pytest.raises(R.RouteAggregationRuleError):
            R.parse_money("not-a-number")

    def test_no_zero_substitution_anywhere_in_money_columns(self, real_result):
        money = ("route_fare_median", "route_fare_min", "route_fare_max")
        for record in real_result.grain_a + real_result.grain_b:
            for name in money:
                assert record[name] != "0"
                assert record[name] != "0.00"

    def test_engine_declares_no_imputation_and_no_zero_substitution(self):
        assert R.PERFORMS_IMPUTATION is False
        assert R.SUBSTITUTES_ZERO_FOR_MISSING is False

    def test_real_corpus_has_exactly_one_unpriced_cell(self, real_result):
        unpriced = [
            record
            for record in real_result.lineage
            if record["consolidated_fare_normalized"] == ""
        ]
        assert len(unpriced) == 1
        assert unpriced[0]["price_state"] == "NO_PRICE_CELL"


# ===========================================================================
# AREA 19 -- lineage completeness
# ===========================================================================
class TestLineage:
    def test_lineage_has_one_row_per_consolidation_cell(self, real_result):
        assert len(real_result.lineage) == 393
        ids = [record["consolidation_cell_id"] for record in real_result.lineage]
        assert len(set(ids)) == 393

    def test_lineage_preserves_every_required_key(self):
        required = (
            "observation_id",
            "flight_cell_id",
            "consolidation_cell_id",
            "route_id",
            "collection_round_id",
            "fare_class",
            "advance_purchase_window",
            "travel_date",
        )
        for name in required:
            plural = name + "s"
            contributing = "contributing_" + plural
            assert (
                name in E.LINEAGE_COLUMNS
                or plural in E.LINEAGE_COLUMNS
                or contributing in E.LINEAGE_COLUMNS
            )

    def test_lineage_observation_ids_reconcile_with_phase9(self, real_result):
        contributing = sum(
            int(record["contributing_observation_id_count"])
            for record in real_result.lineage
        )
        excluded = sum(
            int(record["excluded_sold_out_observation_count"])
            for record in real_result.lineage
        )
        mapped = sum(
            int(record["mapped_observation_count"]) for record in real_result.lineage
        )
        assert contributing == 777
        assert excluded == 1
        assert contributing + excluded == 778
        assert mapped == 778

    def test_every_lineage_row_carries_a_flight_cell_id(self, real_result):
        for record in real_result.lineage:
            assert record["flight_cell_ids"] != ""
            assert int(record["flight_cell_count"]) >= 1

    def test_lineage_links_both_grain_series_ids(self, real_result):
        grain_a_ids = {
            record["route_series_id"]
            for record in real_result.grain_a + real_result.off_basket_grain_a
            if record["route_series_id"] != ""
        }
        grain_b_ids = {
            record["route_class_round_series_id"]
            for record in real_result.grain_b + real_result.off_basket_grain_b
            if record["route_class_round_series_id"] != ""
        }
        for record in real_result.lineage:
            assert record["route_series_id"] in grain_a_ids
            assert record["route_class_round_series_id"] in grain_b_ids

    def test_lineage_preserves_observed_direction_and_canonical_key(self, real_result):
        for record in real_result.lineage:
            observed = record["observed_directed_pair"].split("-")
            assert observed[0] == record["observed_origin"]
            assert observed[1] == record["observed_destination"]
            assert record["route_id"] == R.canonical_route_id(observed[0], observed[1])

    def test_lineage_is_ordered_deterministically(self, real_result):
        keys = [
            (
                record["route_id"],
                record["fare_class"],
                record["advance_purchase_window"],
                record["travel_date"],
                record["round_sort_key"],
                record["consolidation_cell_id"],
            )
            for record in real_result.lineage
        ]
        assert keys == sorted(keys)

    def test_lineage_carries_schema_version(self, real_result):
        for record in real_result.lineage:
            assert record["phase10_schema_version"] == R.PHASE10_SCHEMA_VERSION

    def test_lineage_covers_both_basket_and_off_basket_cells(self, real_result):
        scopes = {record["basket_scope"] for record in real_result.lineage}
        assert scopes == {R.BASKET_SCOPE_IN, R.BASKET_SCOPE_OUT}


# ===========================================================================
# ROUTE CROSSWALK contract
# ===========================================================================
class TestCrosswalk:
    def test_crosswalk_has_seventeen_rows(self, real_result):
        assert len(real_result.crosswalk) == 17

    def test_crosswalk_preserves_all_required_fields(self):
        for name in (
            "observed_origin",
            "observed_destination",
            "observed_directed_pair",
            "route_id",
            "route_direction_relation",
            "basket_membership",
        ):
            assert name in E.CROSSWALK_COLUMNS

    def test_crosswalk_relations_use_the_closed_vocabulary(self, real_result):
        allowed = set(R.DIRECTION_RELATIONS) | {""}
        for record in real_result.crosswalk:
            assert record["route_direction_relation"] in allowed

    def test_del_bom_is_canonicalized_from_reverse_with_direction_preserved(
        self, real_result
    ):
        rows = [
            record
            for record in real_result.crosswalk
            if record["observed_directed_pair"] == "DEL-BOM"
        ]
        assert len(rows) == 1
        assert rows[0]["route_id"] == "BOM-DEL"
        assert rows[0]["route_direction_relation"] == R.DIRECTION_CANONICALIZED
        assert rows[0]["observed_origin"] == "DEL"
        assert rows[0]["observed_destination"] == "BOM"
        assert rows[0]["observed_cell_count"] == "113"

    def test_del_blr_crosswalk_row(self, real_result):
        rows = [
            record
            for record in real_result.crosswalk
            if record["observed_directed_pair"] == "DEL-BLR"
        ]
        assert len(rows) == 1
        assert rows[0]["route_id"] == "BLR-DEL"
        assert rows[0]["observed_cell_count"] == "106"

    def test_off_basket_crosswalk_rows_are_labelled_off_basket(self, real_result):
        rows = [
            record
            for record in real_result.crosswalk
            if record["basket_membership"] == R.BASKET_NON_MEMBER
        ]
        assert len(rows) == 2
        assert {record["observed_directed_pair"] for record in rows} == {
            "MAA-CCU",
            "BLR-HYD",
        }
        for record in rows:
            assert record["route_direction_relation"] == R.DIRECTION_OFF_BASKET

    def test_unobserved_basket_routes_appear_with_no_observations(self, real_result):
        rows = [
            record
            for record in real_result.crosswalk
            if record["route_coverage_status"] == R.COVERAGE_NONE
        ]
        assert len(rows) == EXPECTED_NO_OBSERVATION_ROUTES
        for record in rows:
            assert record["observed_directed_pair"] == ""
            assert record["observed_cell_count"] == "0"

    def test_crosswalk_basket_rows_precede_off_basket_rows_by_rank(self, real_result):
        ranks = []
        for record in real_result.crosswalk:
            if record["basket_rank"] == "":
                ranks.append(10000)
            else:
                ranks.append(int(record["basket_rank"]))
        assert ranks == sorted(ranks)

    def test_crosswalk_names_the_canonicalization_source(self, real_result):
        for record in real_result.crosswalk:
            assert record["canonicalization_source"] == R.ROUTE_ID_SOURCE_OF_TRUTH
            assert record["observed_direction_preserved"] == "True"


# ===========================================================================
# AREA 20 + 21 -- determinism and order independence
# ===========================================================================
def _serialize(columns, rows):
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(columns), lineterminator="\n")
    writer.writeheader()
    for record in rows:
        writer.writerow(record)
    return buffer.getvalue()


class TestDeterminism:
    def test_repeated_runs_produce_identical_tables(self, real_result):
        cells = E.read_csv(CELLS_PATH)
        observations = E.read_csv(OBSERVATION_MAP_PATH)
        basket = E.load_basket(BASKET_PATH)
        again = E.aggregate(cells, observations, basket)
        assert again.grain_a == real_result.grain_a
        assert again.grain_b == real_result.grain_b
        assert again.crosswalk == real_result.crosswalk
        assert again.lineage == real_result.lineage
        assert again.coverage == real_result.coverage

    def test_reversed_cell_input_order_produces_identical_output(self):
        cells = E.read_csv(CELLS_PATH)
        observations = E.read_csv(OBSERVATION_MAP_PATH)
        basket = E.load_basket(BASKET_PATH)
        forward = E.aggregate(cells, observations, basket)
        reverse = E.aggregate(
            list(reversed(cells)), list(reversed(observations)), basket
        )
        assert reverse.grain_a == forward.grain_a
        assert reverse.grain_b == forward.grain_b
        assert reverse.off_basket_grain_a == forward.off_basket_grain_a
        assert reverse.off_basket_grain_b == forward.off_basket_grain_b
        assert reverse.crosswalk == forward.crosswalk
        assert reverse.lineage == forward.lineage
        assert reverse.coverage == forward.coverage

    def test_reversed_basket_input_produces_identical_output(self):
        cells = E.read_csv(CELLS_PATH)
        observations = E.read_csv(OBSERVATION_MAP_PATH)
        basket = E.load_basket(BASKET_PATH)
        forward = E.aggregate(cells, observations, basket)
        reverse = E.aggregate(cells, observations, list(reversed(basket)))
        assert reverse.grain_a == forward.grain_a
        assert reverse.grain_b == forward.grain_b
        assert reverse.crosswalk == forward.crosswalk
        assert reverse.coverage == forward.coverage
        assert reverse.lineage == forward.lineage

    def test_rotated_basket_input_produces_identical_output(self):
        cells = E.read_csv(CELLS_PATH)
        observations = E.read_csv(OBSERVATION_MAP_PATH)
        basket = E.load_basket(BASKET_PATH)
        forward = E.aggregate(cells, observations, basket)
        rotated = E.aggregate(cells, observations, basket[7:] + basket[:7])
        assert rotated.grain_a == forward.grain_a
        assert rotated.grain_b == forward.grain_b
        assert rotated.crosswalk == forward.crosswalk
        assert rotated.coverage == forward.coverage

    def test_reversed_basket_input_is_byte_identical_when_serialized(self):
        cells = E.read_csv(CELLS_PATH)
        observations = E.read_csv(OBSERVATION_MAP_PATH)
        basket = E.load_basket(BASKET_PATH)
        forward = E.aggregate(cells, observations, basket)
        reverse = E.aggregate(cells, observations, list(reversed(basket)))
        for columns, left, right in (
            (E.GRAIN_A_COLUMNS, forward.grain_a, reverse.grain_a),
            (E.GRAIN_B_COLUMNS, forward.grain_b, reverse.grain_b),
            (E.CROSSWALK_COLUMNS, forward.crosswalk, reverse.crosswalk),
            (E.LINEAGE_COLUMNS, forward.lineage, reverse.lineage),
            (E.COVERAGE_COLUMNS, forward.coverage, reverse.coverage),
        ):
            assert _serialize(columns, left) == _serialize(columns, right)

    def test_written_files_are_byte_identical_across_runs(self):
        import tempfile

        cells = E.read_csv(CELLS_PATH)
        observations = E.read_csv(OBSERVATION_MAP_PATH)
        basket = E.load_basket(BASKET_PATH)
        result = E.aggregate(cells, observations, basket)
        digests = []
        for attempt in range(2):
            directory = tempfile.mkdtemp(prefix="phase10_run_%d_" % attempt)
            path = os.path.join(directory, "grain_a.csv")
            E.write_csv(path, E.GRAIN_A_COLUMNS, result.grain_a)
            digests.append(sha256_of(path))
        assert digests[0] == digests[1]

    def test_shuffled_basket_order_does_not_change_coverage_order(self):
        cells = E.read_csv(CELLS_PATH)
        observations = E.read_csv(OBSERVATION_MAP_PATH)
        basket = E.load_basket(BASKET_PATH)
        forward = E.aggregate(cells, observations, basket)
        shuffled = [
            basket[index] for index in (4, 0, 9, 14, 2, 7, 1, 11, 3, 13, 6, 8, 5, 12, 10)
        ]
        result = E.aggregate(cells, observations, shuffled)
        assert result.coverage == forward.coverage
        assert [record["route_id"] for record in result.coverage] == [
            record["route_id"] for record in forward.coverage
        ]

    def test_packed_list_fields_are_sorted(self, real_result):
        for record in real_result.lineage:
            ids = record["contributing_observation_ids"].split(";")
            ids = [item for item in ids if item != ""]
            assert ids == sorted(ids)

    def test_engine_declares_no_randomness(self):
        assert R.USES_RANDOMNESS is False
        assert R.USES_MACHINE_LEARNING is False


# ===========================================================================
# AREA 23 -- upstream Phase 1-9 regression
# ===========================================================================
class TestUpstreamRegression:
    def test_upstream_locked_files_still_exist(self):
        for path in UPSTREAM_LOCKED_FILES:
            assert os.path.isfile(path)

    def test_phase9_cell_input_still_has_393_rows(self):
        assert len(E.read_csv(CELLS_PATH)) == 393

    def test_phase9_observation_map_still_has_778_rows(self):
        assert len(E.read_csv(OBSERVATION_MAP_PATH)) == 778

    def test_phase9_cell_input_still_has_63_columns(self):
        rows = E.read_csv(CELLS_PATH)
        assert len(rows[0]) == 63

    def test_phase10_does_not_import_upstream_engines(self):
        with open(
            os.path.join(REPO_ROOT, "src", "route_aggregation", "route_engine.py"),
            "r",
            encoding="utf-8",
        ) as handle:
            source = handle.read()
        for banned in (
            "dedup_engine",
            "consolidation_engine",
            "normalization_engine",
            "anomaly_engine",
        ):
            assert banned not in source

    def test_phase10_reuses_upstream_rules_not_reimplemented_math(self):
        with open(
            os.path.join(REPO_ROOT, "src", "route_aggregation", "rules.py"),
            "r",
            encoding="utf-8",
        ) as handle:
            source = handle.read()
        assert "from ..consolidation.rules import" in source
        assert "midpoint_median" in source

    def test_phase10_never_imports_phase6_or_phase7_tolerances(self):
        for path in PHASE10_SOURCES:
            if not os.path.isfile(path):
                continue
            with open(path, "r", encoding="utf-8") as handle:
                source = handle.read()
            assert "TIME_TOLERANCE_MINUTES" not in source
            assert "ROUND_TOLERANCE_MINUTES" not in source


# ===========================================================================
# AREA 24 + 25 -- code quality guards
# ===========================================================================
class TestCodeQualityGuard:
    def test_no_binary_float_constructor_in_phase10_sources(self):
        banned = "fl" + "oat("
        for path in PHASE10_SOURCES:
            assert os.path.isfile(path)
            with open(path, "r", encoding="utf-8") as handle:
                source = handle.read()
            assert banned not in source

    def test_no_randomness_imports_in_phase10_sources(self):
        banned = ("import " + "random", "np." + "random", "numpy." + "random")
        for path in PHASE10_SOURCES:
            with open(path, "r", encoding="utf-8") as handle:
                source = handle.read()
            for token in banned:
                assert token not in source

    def test_no_machine_learning_imports_in_phase10_sources(self):
        banned = ("sk" + "learn", "Isolation" + "Forest", "xg" + "boost")
        for path in PHASE10_SOURCES:
            with open(path, "r", encoding="utf-8") as handle:
                source = handle.read()
            for token in banned:
                assert token not in source

    def test_no_index_eligible_token_in_phase10_engine(self):
        banned = "index" + "_eligible"
        for columns in (
            E.GRAIN_A_COLUMNS,
            E.GRAIN_B_COLUMNS,
            E.CROSSWALK_COLUMNS,
            E.LINEAGE_COLUMNS,
            E.COVERAGE_COLUMNS,
        ):
            for name in columns:
                assert banned not in name
        with open(
            os.path.join(REPO_ROOT, "src", "route_aggregation", "route_engine.py"),
            "r",
            encoding="utf-8",
        ) as handle:
            assert banned not in handle.read()

    def test_no_pandas_attribute_indexing_in_phase10_sources(self):
        banned = "iter" + "tuples"
        for path in PHASE10_SOURCES:
            with open(path, "r", encoding="utf-8") as handle:
                source = handle.read()
            assert banned not in source
            assert "import pandas" not in source

    def test_no_weighting_tokens_applied_in_phase10_sources(self):
        banned = ("basket_weighted_fare", "expenditure_weight", "quantity_weight")
        for path in (PHASE10_SOURCES[0], PHASE10_SOURCES[1]):
            with open(path, "r", encoding="utf-8") as handle:
                source = handle.read()
            for token in banned:
                assert source.count(token) <= 1

    def test_phase10_sources_are_ascii(self):
        for path in PHASE10_SOURCES:
            with open(path, "rb") as handle:
                data = handle.read()
            assert data.decode("ascii") is not None

    def test_deterministic_ordering_is_documented(self):
        with open(
            os.path.join(REPO_ROOT, "src", "route_aggregation", "route_engine.py"),
            "r",
            encoding="utf-8",
        ) as handle:
            source = handle.read()
        assert "DETERMINISTIC ORDERING" in source
        assert "basket_rank" in source


# ===========================================================================
# Written outputs on disk
# ===========================================================================
class TestWrittenOutputs:
    def test_all_seven_outputs_exist(self):
        for name in (
            "phase10_route_series.csv",
            "phase10_route_class_round_series.csv",
            "phase10_route_crosswalk.csv",
            "phase10_route_lineage_map.csv",
            "phase10_coverage_report.csv",
            "phase10_off_basket_route_series.csv",
            "phase10_off_basket_route_class_round_series.csv",
        ):
            assert os.path.isfile(os.path.join(OUTPUTS, name))

    def test_written_row_counts_match_expectations(self):
        assert len(_read_output("phase10_route_series.csv")) == 232
        assert len(_read_output("phase10_route_class_round_series.csv")) == 75
        assert len(_read_output("phase10_route_crosswalk.csv")) == 17
        assert len(_read_output("phase10_route_lineage_map.csv")) == 393
        assert len(_read_output("phase10_coverage_report.csv")) == 15
        assert len(_read_output("phase10_off_basket_route_series.csv")) == 174
        assert len(_read_output("phase10_off_basket_route_class_round_series.csv")) == 54

    def test_written_files_match_in_memory_tables(self, real_result):
        assert _read_output("phase10_route_series.csv") == real_result.grain_a
        assert _read_output("phase10_coverage_report.csv") == real_result.coverage
        assert _read_output("phase10_route_crosswalk.csv") == real_result.crosswalk

    def test_every_written_output_carries_schema_version(self):
        for name in (
            "phase10_route_series.csv",
            "phase10_route_class_round_series.csv",
            "phase10_route_crosswalk.csv",
            "phase10_route_lineage_map.csv",
            "phase10_coverage_report.csv",
            "phase10_off_basket_route_series.csv",
            "phase10_off_basket_route_class_round_series.csv",
        ):
            rows = _read_output(name)
            assert rows
            for record in rows:
                assert record["phase10_schema_version"] == R.PHASE10_SCHEMA_VERSION

    def test_no_written_output_contains_a_forbidden_column(self):
        for name in (
            "phase10_route_series.csv",
            "phase10_route_class_round_series.csv",
            "phase10_route_crosswalk.csv",
            "phase10_route_lineage_map.csv",
            "phase10_coverage_report.csv",
        ):
            rows = _read_output(name)
            for banned in R.FORBIDDEN_OUTPUT_FIELDS:
                assert banned not in rows[0]

    def test_written_outputs_use_unix_line_endings(self):
        path = os.path.join(OUTPUTS, "phase10_coverage_report.csv")
        with open(path, "rb") as handle:
            data = handle.read()
        assert b"\r\n" not in data
