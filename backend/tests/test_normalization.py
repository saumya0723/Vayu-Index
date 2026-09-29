"""
VAYU INDEX — Phase 8 Normalization Test Suite
===============================================

Covers the full approved Phase 8 test plan:
  primitives, categorical canonicalisation (whitespace/case/unknown), the
  empty alias map, airports and flight numbers, route-direction preservation,
  dates and times with no shifting and no timezone fabrication, round_sort_key
  including the lexical-ordering regression, price_state, fare decomposition
  with no reconstruction, fare_class_tier_rank as derived metadata only,
  declared currency, engine behaviour on the synthetic fixture, determinism,
  idempotence, shuffled-input invariance, real-corpus row-count invariants,
  upstream immutability by SHA-256, scope boundaries, and the mandated pandas
  column-indexing code-quality guard.

Run from the repository root.
"""

import hashlib
import os
import re
import sys
from decimal import Decimal

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.normalization import normalization_engine as E
from src.normalization import rules as R


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURE_CSV = os.path.join(REPO_ROOT, "tests", "fixtures", "phase8_synthetic.csv")

CONSOLIDATED_CSV = os.path.join(REPO_ROOT, "outputs", "consolidated_airfare_observations.csv")
FLIGHT_CELL_CSV = os.path.join(REPO_ROOT, "outputs", "phase7_flight_cell_report.csv")
OBSERVATION_MAP_CSV = os.path.join(REPO_ROOT, "outputs", "phase7_observation_map.csv")
CANONICAL_CSV = os.path.join(REPO_ROOT, "outputs", "canonical_airfare_observations.csv")

# Byte-level upstream baseline recorded BEFORE any Phase 8 work started.
# Phase 8 must never write to any of these files.
UPSTREAM_BASELINE_SHA256 = {
    CANONICAL_CSV: "1223c7b15e7a2eec4798565f9d5013085e8cb3c64b82c17dca9f5375178c488c",
    CONSOLIDATED_CSV: "792be83e1a36165388e397dcf8b1ee27f82a665276c7b2a1cf167b80cc108e80",
    FLIGHT_CELL_CSV: "fa7569ecd9463c15e41e4ba13db8e14e1198c34ccaf0b8366730115b7f67447f",
    OBSERVATION_MAP_CSV: "e4717e8f16d1b68ef8119e7708f1af7f6134ef2b3cf13c5185b74a04a93350c8",
}

EXPECTED_CONSOLIDATED_ROWS = 393
EXPECTED_FLIGHT_CELL_ROWS = 571
EXPECTED_OBSERVATION_ROWS = 778


# ---------------------------------------------------------------------------
# Helpers. Every builder assembles a dict FIRST and then applies overrides, so
# a caller can override any field without a duplicate-keyword TypeError.
# ---------------------------------------------------------------------------
def _sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _flight_cell_row(**overrides):
    record = {
        "flight_cell_id": "SYN-C01::FLT::6E|6E-2341|08:10",
        "consolidation_cell_id": "SYN-C01",
        "origin": "DEL",
        "destination": "BOM",
        "travel_date": "2026-09-20",
        "fare_class": "Economy Saver",
        "advance_purchase_window": "T15(12-18)",
        "collection_round_id": "ROUND::2026-09-05T09:00",
        "carrier": "6E",
        "flight_number": "6E-2341",
        "departure_time_normalized": "08:10",
        "flight_representative_fare": "7000.00",
        "flight_source_count": "2",
        "flight_sources": "Cleartrip|MMT",
        "flight_source_level_fares": "Cleartrip=7000.00|MMT=7000.00",
        "flight_min_fare": "7000.00",
        "flight_max_fare": "7000.00",
        "flight_source_spread": "0.00",
        "flight_source_relative_spread": "0.0",
        "flight_observation_count": "2",
        "flight_priced_observation_count": "2",
        "flight_sold_out_observation_count": "0",
        "flight_missing_price_observation_count": "0",
        "flight_observation_ids": "SYN0001|SYN0002",
    }
    record.update(overrides)
    return record


def _obs_map_row(**overrides):
    record = {
        "observation_id": "SYN0001",
        "source": "Cleartrip",
        "total_fare": "7000",
        "availability_status": "Available",
        "collection_timestamp": "2026-09-05 09:00",
        "collection_round_id": "ROUND::2026-09-05T09:00",
        "round_alignment": "ANCHORED",
        "round_anchor_timestamp": "2026-09-05 09:00",
        "origin": "DEL",
        "destination": "BOM",
        "travel_date": "2026-09-20",
        "fare_class": "Economy Saver",
        "advance_purchase_window": "T15(12-18)",
        "carrier": "6E",
        "flight_number": "6E-2341",
        "departure_time_normalized": "08:10",
        "flight_cell_id": "SYN-C01::FLT::6E|6E-2341|08:10",
        "flight_representative_fare": "7000.00",
        "consolidation_cell_id": "SYN-C01",
        "consolidated_fare": "7000.00",
        "participation_status": "PARTICIPATED",
    }
    record.update(overrides)
    return record


def _canonical_row(**overrides):
    record = {
        "observation_id": "SYN0001",
        "base_fare": "6300",
        "taxes": "500",
        "fees": "200",
        "departure_time": "08:10",
        "advance_purchase_days": "15",
    }
    record.update(overrides)
    return record


def _frame(rows, columns):
    return pd.DataFrame(rows, columns=list(columns))


def _fixture_consolidated():
    return E.read_phase7_csv(FIXTURE_CSV)


def _run_fixture(flight_rows=None, obs_rows=None, canonical_rows=None):
    consolidated = _fixture_consolidated()
    flights = _frame(
        flight_rows if flight_rows is not None else [_flight_cell_row()],
        E.PHASE7_FLIGHT_CELL_COLUMNS,
    )
    observations = _frame(
        obs_rows if obs_rows is not None else [_obs_map_row()],
        E.PHASE7_OBSERVATION_MAP_COLUMNS,
    )
    canonical = _frame(
        canonical_rows if canonical_rows is not None else [_canonical_row()],
        E.CANONICAL_JOIN_COLUMNS,
    )
    return E.run_normalization(consolidated, flights, observations, canonical)


def _cell(result, cell_id):
    frame = result.normalized
    matches = frame[frame["consolidation_cell_id"] == cell_id]
    assert len(matches) == 1, "expected exactly one row for %s" % cell_id
    return matches.iloc[0]


def _flags_of(row):
    text = str(row["normalization_flags"]).strip()
    return set(text.split("|")) if text else set()


# ===========================================================================
class TestPhase8Primitives:
    def test_is_missing_blank_and_none(self):
        assert R.is_missing(None) is True
        assert R.is_missing("") is True
        assert R.is_missing("   ") is True

    def test_is_missing_zero_is_not_missing(self):
        assert R.is_missing("0") is False
        assert R.is_missing(0) is False

    def test_clean_str_trims_and_collapses(self):
        assert R.clean_str("  Economy   Saver  ") == "Economy Saver"
        assert R.clean_str(None) == ""

    def test_parse_money_valid(self):
        assert R.parse_money("5400") == Decimal("5400")
        assert R.parse_money(" 5400.25 ") == Decimal("5400.25")

    def test_parse_money_invalid_returns_none(self):
        assert R.parse_money("abc") is None
        assert R.parse_money("1,234") is None

    def test_parse_money_missing_returns_none(self):
        assert R.parse_money("") is None
        assert R.parse_money(None) is None

    def test_quantize_money_half_up(self):
        assert R.quantize_money(Decimal("5400.005")) == Decimal("5400.01")
        assert R.quantize_money(Decimal("5400.004")) == Decimal("5400.00")

    def test_format_money_two_decimals(self):
        assert R.format_money(Decimal("5400")) == "5400.00"
        assert R.format_money(None) == ""

    def test_normalize_money_reports_quantization(self):
        value, text, actions = R.normalize_money("7000")
        assert text == "7000.00"
        assert R.ACTION_MONEY_QUANTIZED in actions
        assert value == Decimal("7000.00")

    def test_normalize_money_preserves_economic_value(self):
        for raw in ("7000", "7000.0", "7000.00", " 7000.000 "):
            value, text, _ = R.normalize_money(raw)
            assert Decimal(text) == Decimal(raw.strip())
            assert value == Decimal("7000.00")

    def test_normalize_money_blank_is_not_zero(self):
        value, text, actions = R.normalize_money("")
        assert value is None
        assert text == ""
        assert actions == []

    def test_join_flags_sorted_and_deduped(self):
        assert R.join_flags(["B", "A", "B", ""]) == "A|B"
        assert R.join_flags([]) == ""


class TestCategoricalCanonicalization:
    def test_exact_known_fare_class(self):
        value, known, actions = R.canonicalize_categorical(
            "Economy Saver", R.KNOWN_FARE_CLASSES
        )
        assert value == "Economy Saver"
        assert known is True
        assert actions == []

    def test_whitespace_is_trimmed(self):
        value, known, actions = R.canonicalize_categorical(
            "  Economy Saver  ", R.KNOWN_FARE_CLASSES
        )
        assert value == "Economy Saver"
        assert known is True
        assert R.ACTION_TRIM_WHITESPACE in actions

    def test_internal_whitespace_is_collapsed(self):
        value, known, actions = R.canonicalize_categorical(
            "Economy   Saver", R.KNOWN_FARE_CLASSES
        )
        assert value == "Economy Saver"
        assert known is True
        assert R.ACTION_COLLAPSE_WHITESPACE in actions

    def test_case_normalized_to_known_casing(self):
        value, known, actions = R.canonicalize_categorical(
            "economy saver", R.KNOWN_FARE_CLASSES
        )
        assert value == "Economy Saver"
        assert known is True
        assert R.ACTION_CASE_NORMALIZED in actions

    def test_unknown_value_flags_and_continues(self):
        value, known, actions = R.canonicalize_categorical(
            "Premium Economy", R.KNOWN_FARE_CLASSES
        )
        assert value == "Premium Economy"
        assert known is False
        assert R.ACTION_UNKNOWN_VALUE_FLAGGED in actions

    def test_unknown_value_preserves_original_text(self):
        value, _, _ = R.canonicalize_categorical("Business Flex", R.KNOWN_FARE_CLASSES)
        assert value == "Business Flex"

    def test_distinct_fare_products_never_merged(self):
        saver, _, _ = R.canonicalize_categorical("Economy Saver", R.KNOWN_FARE_CLASSES)
        flexi, _, _ = R.canonicalize_categorical("Economy Flexi", R.KNOWN_FARE_CLASSES)
        assert saver != flexi

    def test_empty_value_is_not_known(self):
        value, known, _ = R.canonicalize_categorical("", R.KNOWN_FARE_CLASSES)
        assert value == ""
        assert known is False

    def test_alias_maps_are_empty_by_approval(self):
        assert R.FARE_CLASS_ALIASES == {}
        assert R.SOURCE_ALIASES == {}
        assert R.CARRIER_ALIASES == {}
        assert R.ALIAS_MAPS_EMPTY_BY_APPROVAL is True

    def test_canonicalization_is_idempotent(self):
        for raw in ("  Economy   Saver ", "economy flexi", "Premium Economy"):
            once, _, _ = R.canonicalize_categorical(raw, R.KNOWN_FARE_CLASSES)
            twice, _, _ = R.canonicalize_categorical(once, R.KNOWN_FARE_CLASSES)
            assert once == twice

    def test_known_sets_have_no_case_collisions(self):
        for known in (
            R.KNOWN_FARE_CLASSES,
            R.KNOWN_SOURCES,
            R.KNOWN_CARRIERS,
            R.KNOWN_ADVANCE_PURCHASE_WINDOWS,
        ):
            folded = [value.casefold() for value in known]
            assert len(folded) == len(set(folded))

    def test_known_sources_match_phase7_expectation(self):
        assert set(R.KNOWN_SOURCES) == {"AirlineSite", "Cleartrip", "Goibibo", "MMT"}

    def test_known_carriers(self):
        value, known, _ = R.canonicalize_categorical("6e", R.KNOWN_CARRIERS)
        assert value == "6E"
        assert known is True

    def test_unknown_source_is_not_merged_into_known_source(self):
        value, known, _ = R.canonicalize_categorical("MakeMyTrip", R.KNOWN_SOURCES)
        assert value == "MakeMyTrip"
        assert known is False


class TestAirportsAndFlightNumbers:
    def test_airport_uppercased(self):
        value, actions = R.canonicalize_airport("del")
        assert value == "DEL"
        assert R.ACTION_UPPERCASE in actions

    def test_airport_whitespace_trimmed(self):
        value, actions = R.canonicalize_airport("  BOM ")
        assert value == "BOM"
        assert R.ACTION_TRIM_WHITESPACE in actions

    def test_route_direction_never_reversed(self):
        origin, _ = R.canonicalize_airport("DEL")
        destination, _ = R.canonicalize_airport("BOM")
        assert (origin, destination) == ("DEL", "BOM")
        assert (origin, destination) != ("BOM", "DEL")

    def test_flight_number_uppercased(self):
        value, actions = R.canonicalize_flight_number("6e-2341")
        assert value == "6E-2341"
        assert R.ACTION_UPPERCASE in actions

    def test_flight_number_whitespace(self):
        value, _ = R.canonicalize_flight_number("  SG-451  ")
        assert value == "SG-451"

    def test_airport_idempotent(self):
        once, _ = R.canonicalize_airport(" del ")
        twice, _ = R.canonicalize_airport(once)
        assert once == twice == "DEL"


class TestDatesAndTimes:
    def test_travel_date_valid_unchanged(self):
        value, ok, actions = R.normalize_travel_date("2026-09-20")
        assert value == "2026-09-20"
        assert ok is True
        assert actions == []

    def test_travel_date_never_shifted(self):
        for raw in ("2026-09-20", "2026-01-01", "2026-12-31"):
            value, ok, _ = R.normalize_travel_date(raw)
            assert value == raw
            assert ok is True

    def test_travel_date_invalid_flagged_not_repaired(self):
        value, ok, actions = R.normalize_travel_date("20-09-2026")
        assert ok is False
        assert value == "20-09-2026"
        assert R.ACTION_INVALID_FORMAT_FLAGGED in actions

    def test_travel_date_blank(self):
        value, ok, _ = R.normalize_travel_date("")
        assert value == ""
        assert ok is False

    def test_collection_timestamp_iso(self):
        value, ok, _ = R.collection_timestamp_iso("2026-09-05 09:00")
        assert value == "2026-09-05T09:00:00"
        assert ok is True

    def test_collection_timestamp_carries_no_timezone(self):
        value, _, _ = R.collection_timestamp_iso("2026-09-05 09:00")
        assert "Z" not in value
        assert "+" not in value
        assert R.TIMEZONE_INFERENCE_PERFORMED is False
        assert R.COLLECTION_TIMESTAMP_IS_NAIVE_LOCAL is True

    def test_collection_timestamp_unparseable(self):
        value, ok, actions = R.collection_timestamp_iso("not-a-timestamp")
        assert value == ""
        assert ok is False
        assert R.ACTION_INVALID_FORMAT_FLAGGED in actions

    def test_collection_timestamp_missing(self):
        value, ok, actions = R.collection_timestamp_iso("")
        assert value == ""
        assert ok is False
        assert actions == []

    def test_departure_time_reused_from_phase6(self):
        from src.deduplication.rules import normalize_departure_time as phase6

        assert R.normalize_departure_time is phase6

    def test_departure_time_equivalent_forms(self):
        assert R.normalize_departure_time("8:10") == "08:10"
        assert R.normalize_departure_time("08:10") == "08:10"
        assert R.normalize_departure_time("08:10:00") == "08:10"

    def test_departure_time_invalid_returns_none(self):
        assert R.normalize_departure_time("25:99") is None
        assert R.normalize_departure_time("") is None


class TestRoundSortKey:
    def test_sort_key_from_anchor(self):
        key, provenance = R.derive_round_sort_key(
            "2026-09-05 09:00", "ROUND::2026-09-05T09:00"
        )
        assert key == "2026-09-05 09:00"
        assert provenance == R.ROUND_SORT_KEY_SOURCE_ANCHOR

    def test_sort_key_from_unaligned_round_id(self):
        key, provenance = R.derive_round_sort_key("", "ROUND-UNALIGNED::2026-09-05 10:32")
        assert key == "2026-09-05 10:32"
        assert provenance == R.ROUND_SORT_KEY_SOURCE_ROUND_ID

    def test_sort_key_from_anchored_round_id_when_anchor_missing(self):
        key, provenance = R.derive_round_sort_key("", "ROUND::2026-09-07T20:15")
        assert key == "2026-09-07 20:15"
        assert provenance == R.ROUND_SORT_KEY_SOURCE_ROUND_ID

    def test_sort_key_unresolvable_is_blank(self):
        key, provenance = R.derive_round_sort_key("", "ROUND-UNRESOLVED::OBS00781")
        assert key == ""
        assert provenance == R.ROUND_SORT_KEY_SOURCE_UNRESOLVED

    def test_lexical_round_id_ordering_is_wrong(self):
        """Regression guard: documents WHY round_sort_key exists.

        '-' is 0x2D and ':' is 0x3A, so '-' sorts before ':'. Every
        'ROUND-UNALIGNED::' id therefore sorts BEFORE every 'ROUND::' id no
        matter which instant it represents. Ordering on the raw round id
        manufactures fictitious price movement.
        """
        chronologically_early = "ROUND::2026-09-05T09:00"
        chronologically_late = "ROUND-UNALIGNED::2026-09-07 23:59"
        # The chronologically LATER round sorts first. That is the trap.
        assert sorted([chronologically_early, chronologically_late]) == [
            chronologically_late,
            chronologically_early,
        ]

    def test_round_sort_key_fixes_lexical_trap(self):
        early, _ = R.derive_round_sort_key("", "ROUND::2026-09-05T09:00")
        late, _ = R.derive_round_sort_key("", "ROUND-UNALIGNED::2026-09-07 23:59")
        assert early == "2026-09-05 09:00"
        assert late == "2026-09-07 23:59"
        assert sorted([early, late]) == [early, late]

    def test_round_sort_tuple_puts_blank_last(self):
        ordered = sorted(
            [
                R.round_sort_tuple("", "z"),
                R.round_sort_tuple("2026-09-05 09:00", "a"),
            ]
        )
        assert ordered[0][1] == "2026-09-05 09:00"
        assert ordered[-1][1] == ""

    def test_round_sort_key_is_deterministic(self):
        first = R.derive_round_sort_key("2026-09-05 14:30", "ROUND::2026-09-05T14:30")
        second = R.derive_round_sort_key("2026-09-05 14:30", "ROUND::2026-09-05T14:30")
        assert first == second

    def test_is_anchored(self):
        assert R.is_anchored("ANCHORED") is True
        assert R.is_anchored("UNALIGNED") is False


class TestPriceState:
    def test_cell_priced(self):
        assert R.derive_cell_price_state("CONSOLIDATED", "7000.00") == R.PRICE_STATE_PRICED

    def test_cell_no_price_when_status_not_consolidated(self):
        assert (
            R.derive_cell_price_state("NO_PRICE_ALL_SOLD_OUT", "")
            == R.PRICE_STATE_NO_PRICE_CELL
        )

    def test_cell_no_price_when_fare_blank(self):
        assert R.derive_cell_price_state("CONSOLIDATED", "") == R.PRICE_STATE_NO_PRICE_CELL

    def test_observation_sold_out(self):
        assert (
            R.derive_observation_price_state("Sold Out", "") == R.PRICE_STATE_SOLD_OUT
        )

    def test_observation_sold_out_is_never_zero_priced(self):
        state = R.derive_observation_price_state("Sold Out", "")
        assert state != R.PRICE_STATE_PRICED

    def test_observation_priced(self):
        assert (
            R.derive_observation_price_state("Available", "7000")
            == R.PRICE_STATE_PRICED
        )

    def test_observation_missing_price(self):
        assert (
            R.derive_observation_price_state("Available", "")
            == R.PRICE_STATE_MISSING_PRICE
        )

    def test_flight_cell_states(self):
        assert (
            R.derive_flight_cell_price_state("7000.00", "0", "2")
            == R.PRICE_STATE_PRICED
        )
        assert R.derive_flight_cell_price_state("", "1", "0") == R.PRICE_STATE_SOLD_OUT
        assert (
            R.derive_flight_cell_price_state("", "0", "0")
            == R.PRICE_STATE_MISSING_PRICE
        )

    def test_price_states_are_mutually_exclusive_labels(self):
        assert len(set(R.PRICE_STATES)) == 4


class TestFareDecomposition:
    def test_complete_and_reconciles(self):
        complete, reconciles, flags = R.fare_decomposition_state("6300", "500", "200", "7000")
        assert complete == "True"
        assert reconciles == "True"
        assert flags == []

    def test_incomplete_is_not_evaluable(self):
        complete, reconciles, flags = R.fare_decomposition_state("", "500", "200", "7000")
        assert complete == "False"
        assert reconciles == ""
        assert R.FLAG_FARE_DECOMPOSITION_INCOMPLETE in flags

    def test_not_evaluable_is_not_reported_as_failure(self):
        _, reconciles, _ = R.fare_decomposition_state("", "", "", "7000")
        assert reconciles != "False"

    def test_mismatch_flagged(self):
        complete, reconciles, flags = R.fare_decomposition_state("6300", "500", "200", "9000")
        assert complete == "True"
        assert reconciles == "False"
        assert R.FLAG_FARE_COMPONENTS_MISMATCH in flags

    def test_within_tolerance_passes(self):
        _, reconciles, _ = R.fare_decomposition_state("6300", "500", "200", "7000.50")
        assert reconciles == "True"

    def test_tolerance_reused_from_phase2(self):
        from src.validation.rules import FARE_COMPONENT_TOLERANCE

        assert R.FARE_COMPONENT_TOLERANCE_DECIMAL == Decimal(str(FARE_COMPONENT_TOLERANCE))

    def test_no_reconstruction_of_missing_components(self):
        """A missing component is never back-filled from the total."""
        complete, reconciles, _ = R.fare_decomposition_state("", "500", "200", "7000")
        assert complete == "False"
        assert reconciles == ""


class TestTierRankAndCurrency:
    def test_tier_rank_mapping(self):
        assert R.fare_class_tier_rank("Economy Saver") == "1"
        assert R.fare_class_tier_rank("Economy Standard") == "2"
        assert R.fare_class_tier_rank("Economy Flexi") == "3"

    def test_tier_rank_unknown_is_blank(self):
        assert R.fare_class_tier_rank("Premium Economy") == ""

    def test_tier_rank_is_not_an_identity_field(self):
        assert R.FARE_CLASS_TIER_RANK_IS_IDENTITY_FIELD is False

    def test_tier_rank_absent_from_every_upstream_key(self):
        from src.consolidation import rules as C
        from src.deduplication import rules as D

        for key_set in (
            C.ECONOMIC_IDENTITY_FIELDS,
            C.CONSOLIDATION_CELL_FIELDS,
            C.FLIGHT_INSTANCE_EXTRA_FIELDS,
            D.ECONOMIC_IDENTITY_FIELDS,
            D.PRODUCT_INSTANCE_IDENTITY_FIELDS,
        ):
            assert "fare_class_tier_rank" not in tuple(key_set)

    def test_currency_is_declared_constant(self):
        assert R.CURRENCY_CODE == "INR"
        assert R.CURRENCY_SOURCE == "DECLARED_PROTOTYPE_CONSTANT"

    def test_no_fx_conversion_supported(self):
        assert R.FX_CONVERSION_SUPPORTED is False


class TestEngineOnFixture:
    def test_fixture_loads_with_phase7_schema(self):
        frame = _fixture_consolidated()
        assert len(frame) == 12
        assert list(frame.columns) == list(E.PHASE7_CONSOLIDATED_COLUMNS)

    def test_row_count_preserved(self):
        result = _run_fixture()
        assert len(result.normalized) == 12
        assert len(result.flight_cells) == 1
        assert len(result.observation_map) == 1

    def test_output_schema_is_exact(self):
        result = _run_fixture()
        assert list(result.normalized.columns) == list(E.NORMALIZED_CELL_COLUMNS)
        assert list(result.flight_cells.columns) == list(E.NORMALIZED_FLIGHT_CELL_COLUMNS)
        assert list(result.observation_map.columns) == list(E.NORMALIZED_OBSERVATION_COLUMNS)
        assert list(result.report.columns) == list(E.NORMALIZATION_REPORT_COLUMNS)

    def test_phase7_columns_are_preserved_verbatim(self):
        source = _fixture_consolidated()
        result = _run_fixture()
        merged = result.normalized.set_index("consolidation_cell_id")
        original = source.set_index("consolidation_cell_id")
        for cell_id in original.index:
            for column in E.PHASE7_CONSOLIDATED_COLUMNS:
                if column == "consolidation_cell_id":
                    continue
                assert merged.loc[cell_id, column] == original.loc[cell_id, column]

    def test_unknown_fare_class_is_flagged_not_fatal(self):
        result = _run_fixture()
        row = _cell(result, "SYN-C04")
        assert bool(row["fare_class_is_known"]) is False
        assert row["fare_class_canonical"] == "Premium Economy"
        assert R.FLAG_UNKNOWN_FARE_CLASS in _flags_of(row)

    def test_unknown_fare_class_has_no_tier_rank(self):
        result = _run_fixture()
        assert _cell(result, "SYN-C04")["fare_class_tier_rank"] == ""

    def test_whitespace_fare_class_canonicalized(self):
        result = _run_fixture()
        row = _cell(result, "SYN-C03")
        assert row["fare_class_canonical"] == "Economy Saver"
        assert bool(row["fare_class_is_known"]) is True
        assert row["fare_class"] == "  Economy   Saver  "

    def test_lowercase_airports_canonicalized(self):
        result = _run_fixture()
        row = _cell(result, "SYN-C07")
        assert row["origin_canonical"] == "DEL"
        assert row["destination_canonical"] == "BOM"

    def test_reverse_direction_is_preserved(self):
        result = _run_fixture()
        forward = _cell(result, "SYN-C01")
        reverse = _cell(result, "SYN-C08")
        assert (forward["origin_canonical"], forward["destination_canonical"]) == ("DEL", "BOM")
        assert (reverse["origin_canonical"], reverse["destination_canonical"]) == ("BOM", "DEL")

    def test_unknown_window_flagged_but_not_rebinned(self):
        result = _run_fixture()
        row = _cell(result, "SYN-C09")
        assert bool(row["advance_purchase_window_is_known"]) is False
        assert row["advance_purchase_window"] == "T60(55-65)"
        assert R.FLAG_UNKNOWN_ADVANCE_PURCHASE_WINDOW in _flags_of(row)

    def test_no_price_cell_state(self):
        result = _run_fixture()
        row = _cell(result, "SYN-C05")
        assert row["price_state"] == R.PRICE_STATE_NO_PRICE_CELL
        assert row["consolidated_fare_normalized"] == ""

    def test_unaligned_round_still_gets_sort_key(self):
        result = _run_fixture()
        row = _cell(result, "SYN-C02")
        assert row["round_sort_key"] == "2026-09-05 10:32"
        assert row["round_sort_key_source"] == R.ROUND_SORT_KEY_SOURCE_ROUND_ID

    def test_unresolved_round_sort_key_blank_and_flagged(self):
        result = _run_fixture()
        row = _cell(result, "SYN-C10")
        assert row["round_sort_key"] == ""
        assert R.FLAG_MISSING_ROUND_SORT_KEY in _flags_of(row)

    def test_money_quantization_is_representation_only(self):
        result = _run_fixture()
        row = _cell(result, "SYN-C11")
        assert row["consolidated_fare"] == "7000"
        assert row["consolidated_fare_normalized"] == "7000.00"
        assert Decimal(row["consolidated_fare"]) == Decimal(row["consolidated_fare_normalized"])

    def test_fractional_fare_preserved(self):
        result = _run_fixture()
        row = _cell(result, "SYN-C06")
        assert row["consolidated_fare_normalized"] == "5612.25"

    def test_high_fare_is_never_altered_or_removed(self):
        result = _run_fixture()
        row = _cell(result, "SYN-C12")
        assert row["consolidated_fare_normalized"] == "52000.00"
        assert row["price_state"] == R.PRICE_STATE_PRICED

    def test_currency_columns_present_on_every_row(self):
        result = _run_fixture()
        assert set(result.normalized["currency"]) == {"INR"}
        assert set(result.normalized["currency_source"]) == {"DECLARED_PROTOTYPE_CONSTANT"}

    def test_schema_version_stamped(self):
        result = _run_fixture()
        assert set(result.normalized["phase8_schema_version"]) == {R.PHASE8_SCHEMA_VERSION}

    def test_report_grain_is_entity_field_action(self):
        result = _run_fixture()
        report = result.report
        assert len(report) > 0
        grain = list(zip(report["entity_id"], report["field"], report["action"]))
        assert len(grain) == len(set(grain))

    def test_report_records_the_unknown_fare_class(self):
        result = _run_fixture()
        report = result.report
        subset = report[
            (report["entity_id"] == "SYN-C04")
            & (report["action"] == R.ACTION_UNKNOWN_VALUE_FLAGGED)
        ]
        assert len(subset) == 1

    def test_observation_join_recovers_fare_components(self):
        result = _run_fixture()
        row = result.observation_map.iloc[0]
        assert row["base_fare"] == "6300"
        assert row["taxes"] == "500"
        assert row["fees"] == "200"
        assert row["fare_components_reconcile"] == "True"

    def test_observation_iso_timestamp(self):
        result = _run_fixture()
        assert result.observation_map.iloc[0]["collection_timestamp_iso"] == "2026-09-05T09:00:00"

    def test_missing_canonical_join_does_not_crash(self):
        result = _run_fixture(canonical_rows=[_canonical_row(observation_id="OTHER")])
        row = result.observation_map.iloc[0]
        assert row["base_fare"] == ""
        assert row["fare_decomposition_complete"] == "False"
        assert row["fare_components_reconcile"] == ""

    def test_unknown_carrier_flagged_on_flight_cell(self):
        result = _run_fixture(flight_rows=[_flight_cell_row(carrier="ZZ")])
        row = result.flight_cells.iloc[0]
        assert bool(row["carrier_is_known"]) is False
        assert R.FLAG_UNKNOWN_CARRIER in _flags_of(row)

    def test_unknown_source_flagged_on_observation(self):
        result = _run_fixture(obs_rows=[_obs_map_row(source="Yatra")])
        row = result.observation_map.iloc[0]
        assert bool(row["source_is_known"]) is False
        assert R.FLAG_UNKNOWN_SOURCE in _flags_of(row)

    def test_sold_out_observation_price_state(self):
        result = _run_fixture(
            obs_rows=[_obs_map_row(availability_status="Sold Out", total_fare="")]
        )
        assert result.observation_map.iloc[0]["price_state"] == R.PRICE_STATE_SOLD_OUT

    def test_missing_schema_column_raises(self):
        broken = _fixture_consolidated().drop(columns=["fare_class"])
        try:
            E.normalize_consolidated(broken)
        except R.NormalizationRuleError:
            return
        raise AssertionError("expected NormalizationRuleError")


class TestDeterminism:
    def test_rerun_is_identical(self):
        first = _run_fixture()
        second = _run_fixture()
        assert first.normalized.to_csv(index=False) == second.normalized.to_csv(index=False)
        assert first.report.to_csv(index=False) == second.report.to_csv(index=False)

    def test_shuffled_input_is_identical(self):
        consolidated = _fixture_consolidated()
        shuffled = consolidated.sample(frac=1.0, random_state=20260910).reset_index(drop=True)
        flights = _frame([_flight_cell_row()], E.PHASE7_FLIGHT_CELL_COLUMNS)
        observations = _frame([_obs_map_row()], E.PHASE7_OBSERVATION_MAP_COLUMNS)
        canonical = _frame([_canonical_row()], E.CANONICAL_JOIN_COLUMNS)

        ordered = E.run_normalization(consolidated, flights, observations, canonical)
        scrambled = E.run_normalization(shuffled, flights, observations, canonical)
        assert ordered.normalized.to_csv(index=False) == scrambled.normalized.to_csv(index=False)

    def test_engine_does_not_mutate_its_input(self):
        consolidated = _fixture_consolidated()
        before = consolidated.to_csv(index=False)
        _run_fixture()
        E.run_normalization(
            consolidated,
            _frame([_flight_cell_row()], E.PHASE7_FLIGHT_CELL_COLUMNS),
            _frame([_obs_map_row()], E.PHASE7_OBSERVATION_MAP_COLUMNS),
            _frame([_canonical_row()], E.CANONICAL_JOIN_COLUMNS),
        )
        assert consolidated.to_csv(index=False) == before

    def test_report_is_sorted_deterministically(self):
        report = _run_fixture().report
        keys = list(
            zip(report["entity_type"], report["entity_id"], report["field"], report["action"])
        )
        assert keys == sorted(keys)

    def test_flags_are_sorted_within_a_row(self):
        result = _run_fixture()
        for value in result.normalized["normalization_flags"]:
            text = str(value).strip()
            if text:
                parts = text.split("|")
                assert parts == sorted(parts)


class TestRealCorpusInvariants:
    def test_consolidated_input_row_count(self):
        assert len(E.read_phase7_csv(CONSOLIDATED_CSV)) == EXPECTED_CONSOLIDATED_ROWS

    def test_flight_cell_input_row_count(self):
        assert len(E.read_phase7_csv(FLIGHT_CELL_CSV)) == EXPECTED_FLIGHT_CELL_ROWS

    def test_observation_input_row_count(self):
        assert len(E.read_phase7_csv(OBSERVATION_MAP_CSV)) == EXPECTED_OBSERVATION_ROWS

    def test_engine_preserves_all_three_row_counts(self):
        result = E.run_normalization(
            E.read_phase7_csv(CONSOLIDATED_CSV),
            E.read_phase7_csv(FLIGHT_CELL_CSV),
            E.read_phase7_csv(OBSERVATION_MAP_CSV),
            E.read_phase7_csv(CANONICAL_CSV),
        )
        assert len(result.normalized) == EXPECTED_CONSOLIDATED_ROWS
        assert len(result.flight_cells) == EXPECTED_FLIGHT_CELL_ROWS
        assert len(result.observation_map) == EXPECTED_OBSERVATION_ROWS

    def test_no_observation_is_lost(self):
        source = E.read_phase7_csv(OBSERVATION_MAP_CSV)
        result = E.run_normalization(
            E.read_phase7_csv(CONSOLIDATED_CSV),
            E.read_phase7_csv(FLIGHT_CELL_CSV),
            source,
            E.read_phase7_csv(CANONICAL_CSV),
        )
        assert set(source["observation_id"]) == set(result.observation_map["observation_id"])

    def test_no_cell_id_is_lost_or_invented(self):
        source = E.read_phase7_csv(CONSOLIDATED_CSV)
        result = E.run_normalization(
            source,
            E.read_phase7_csv(FLIGHT_CELL_CSV),
            E.read_phase7_csv(OBSERVATION_MAP_CSV),
            E.read_phase7_csv(CANONICAL_CSV),
        )
        assert set(source["consolidation_cell_id"]) == set(
            result.normalized["consolidation_cell_id"]
        )

    def test_upstream_files_are_byte_identical(self):
        for path, expected in UPSTREAM_BASELINE_SHA256.items():
            assert os.path.exists(path), path
            assert _sha256(path) == expected, "Phase 8 modified an upstream file: %s" % path

    def test_running_the_engine_does_not_touch_upstream(self):
        before = {path: _sha256(path) for path in UPSTREAM_BASELINE_SHA256}
        E.run_normalization(
            E.read_phase7_csv(CONSOLIDATED_CSV),
            E.read_phase7_csv(FLIGHT_CELL_CSV),
            E.read_phase7_csv(OBSERVATION_MAP_CSV),
            E.read_phase7_csv(CANONICAL_CSV),
        )
        after = {path: _sha256(path) for path in UPSTREAM_BASELINE_SHA256}
        assert before == after


class TestScopeBoundaries:
    def test_phase6_and_phase7_tolerances_are_not_imported(self):
        assert not hasattr(R, "TIME_TOLERANCE_MINUTES")
        assert not hasattr(R, "ROUND_TOLERANCE_MINUTES")
        assert not hasattr(E, "TIME_TOLERANCE_MINUTES")
        assert not hasattr(E, "ROUND_TOLERANCE_MINUTES")

    def test_tolerance_names_absent_from_phase8_source(self):
        for name in ("rules.py", "normalization_engine.py"):
            path = os.path.join(REPO_ROOT, "src", "normalization", name)
            with open(path, "r", encoding="utf-8") as handle:
                text = handle.read()
            assert "TIME_TOLERANCE_MINUTES" not in text
            assert "ROUND_TOLERANCE_MINUTES" not in text

    def test_no_index_or_aggregation_symbols(self):
        banned = ("index_value", "route_aggregate", "basket_weight", "source_weight")
        for name in ("rules.py", "normalization_engine.py"):
            path = os.path.join(REPO_ROOT, "src", "normalization", name)
            with open(path, "r", encoding="utf-8") as handle:
                text = handle.read()
            for token in banned:
                assert token not in text

    def test_no_basket_membership_column(self):
        result = _run_fixture()
        for frame in (result.normalized, result.flight_cells, result.observation_map):
            for column in frame.columns:
                assert "basket" not in column.lower()

    def test_no_anomaly_or_severity_columns(self):
        result = _run_fixture()
        for frame in (result.normalized, result.flight_cells, result.observation_map):
            for column in frame.columns:
                lowered = column.lower()
                assert "anomaly" not in lowered
                assert "severity" not in lowered
                assert "outlier" not in lowered

    def test_no_ml_or_rng_dependencies(self):
        for name in ("rules.py", "normalization_engine.py"):
            path = os.path.join(REPO_ROOT, "src", "normalization", name)
            with open(path, "r", encoding="utf-8") as handle:
                text = handle.read()
            assert "sklearn" not in text
            assert "import random" not in text
            assert "numpy.random" not in text

    def test_no_float_in_the_monetary_path(self):
        for name in ("rules.py",):
            path = os.path.join(REPO_ROOT, "src", "normalization", name)
            with open(path, "r", encoding="utf-8") as handle:
                text = handle.read()
            assert "float(" not in text

    def test_engine_never_deletes_a_row(self):
        consolidated = _fixture_consolidated()
        result = _run_fixture()
        assert len(result.normalized) == len(consolidated)

    def test_no_imputation_of_a_missing_fare(self):
        result = _run_fixture()
        row = _cell(result, "SYN-C05")
        assert row["consolidated_fare"] == ""
        assert row["consolidated_fare_normalized"] == ""


class TestCodeQualityGuard:
    """Mandated guard: pandas rows must use explicit column indexing.

    Attribute-style access such as .prod, .min, .max, .count or .size on a
    pandas row silently resolves to a Series METHOD instead of the column of
    that name. That exact defect produced 384 phantom single-point series
    during Phase 9 calibration and was caught only by cross-checking. This
    guard exists so it can never recur silently.
    """

    def _sources(self):
        paths = [
            os.path.join(REPO_ROOT, "src", "normalization", "rules.py"),
            os.path.join(REPO_ROOT, "src", "normalization", "normalization_engine.py"),
            os.path.join(REPO_ROOT, "scripts", "run_normalization.py"),
            os.path.abspath(__file__),
        ]
        return [path for path in paths if os.path.exists(path)]

    def test_no_row_attribute_access(self):
        pattern = re.compile(r"\b" + "row" + r"\.[A-Za-z_]")
        for path in self._sources():
            with open(path, "r", encoding="utf-8") as handle:
                text = handle.read()
            assert not pattern.search(text), "attribute-style row access in %s" % path

    def test_no_source_row_attribute_access(self):
        pattern = re.compile(r"\b" + "source_row" + r"\.[A-Za-z_]")
        for path in self._sources():
            with open(path, "r", encoding="utf-8") as handle:
                text = handle.read()
            assert not pattern.search(text), "attribute-style row access in %s" % path

    def test_no_tuple_row_iteration(self):
        # The banned literal is assembled at runtime so that this guard does
        # not fail against its own source file.
        token = "iter" + "tuples"
        for path in self._sources():
            with open(path, "r", encoding="utf-8") as handle:
                text = handle.read()
            assert token not in text, "tuple-style row iteration in %s" % path

    def test_guard_detects_a_violation(self):
        """The guard must actually be capable of failing."""
        pattern = re.compile(r"\b" + "row" + r"\.[A-Za-z_]")
        sample = "value = " + "row" + "." + "prod"
        assert pattern.search(sample) is not None
