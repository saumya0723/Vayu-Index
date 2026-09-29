"""Phase 9 anomaly-detection tests.

Every rule R01-R13 has focused unit tests driven by engineered synthetic
frames, so cases that do not occur in the real corpus (nonpositive fare,
nonnumeric fare, component mismatch, MAD=0 fallback, 3-source attribution)
are still proven to work.

Naming note: local row dictionaries are called `record`, never `row`, so the
banned-attribute-access guard cannot trip over `record.update(...)`.
"""

import os
import re
import sys
from decimal import Decimal

import pandas as pd
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.anomaly_detection import anomaly_engine as E
from src.anomaly_detection import rules as R

REPO_ROOT = os.path.join(os.path.dirname(__file__), "..")


# ---------------------------------------------------------------------------
# Synthetic frame builders
# ---------------------------------------------------------------------------
def _cell(**overrides):
    """One consolidation-cell record with sane defaults."""
    record = {
        "consolidation_cell_id": "CELL::DEL|BOM|2026-09-20|Economy Saver|T15(12-18)"
        "::ROUND::2026-09-05T09:00",
        "origin_canonical": "DEL",
        "destination_canonical": "BOM",
        "travel_date_canonical": "2026-09-20",
        "fare_class_canonical": "Economy Saver",
        "advance_purchase_window": "T15(12-18)",
        "collection_round_id": "ROUND::2026-09-05T09:00",
        "round_alignment": "ANCHORED",
        "round_sort_key": "2026-09-05 09:00",
        "consolidated_fare_normalized": "5000.00",
        "price_state": "PRICED",
        "participating_source_count": "2",
        "participating_sources": "Goibibo;MMT",
        "flight_instance_count": "2",
        "source_coverage": "PARTIAL_COVERAGE",
        "currency": "INR",
        "consolidation_status": "CONSOLIDATED",
        "alt_source_first_fare": "9999.00",
    }
    record.update(overrides)
    return record


def _flight(**overrides):
    """One flight-cell record with sane defaults."""
    record = {
        "flight_cell_id": "CELL::DEL|BOM|2026-09-20|Economy Saver|T15(12-18)"
        "::ROUND::2026-09-05T09:00::FLT::6E|6E-101|08:00",
        "consolidation_cell_id": "CELL::DEL|BOM|2026-09-20|Economy Saver|T15(12-18)"
        "::ROUND::2026-09-05T09:00",
        "collection_round_id": "ROUND::2026-09-05T09:00",
        "round_sort_key": "2026-09-05 09:00",
        "carrier_canonical": "6E",
        "flight_number_canonical": "6E-101",
        "flight_representative_fare_normalized": "5000.00",
        "flight_source_count": "2",
        "flight_sources": "Goibibo;MMT",
        "flight_source_level_fares": "Goibibo=5000.00;MMT=5000.00",
        "flight_min_fare": "5000.00",
        "flight_max_fare": "5000.00",
        "price_state": "PRICED",
    }
    record.update(overrides)
    return record


def _observation(**overrides):
    """One observation record with sane defaults (decomposition reconciles)."""
    record = {
        "observation_id": "OBS00001",
        "source_canonical": "MMT",
        "total_fare_normalized": "5000.00",
        "availability_status": "Available",
        "participation_status": "PARTICIPATED",
        "price_state": "PRICED",
        "flight_cell_id": "CELL::DEL|BOM|2026-09-20|Economy Saver|T15(12-18)"
        "::ROUND::2026-09-05T09:00::FLT::6E|6E-101|08:00",
        "consolidation_cell_id": "CELL::DEL|BOM|2026-09-20|Economy Saver|T15(12-18)"
        "::ROUND::2026-09-05T09:00",
        "collection_round_id": "ROUND::2026-09-05T09:00",
        "round_alignment": "ANCHORED",
        "round_sort_key": "2026-09-05 09:00",
        "base_fare": "4000.00",
        "taxes": "800.00",
        "fees": "200.00",
        "fare_decomposition_complete": "True",
        "origin_canonical": "DEL",
        "destination_canonical": "BOM",
        "travel_date_canonical": "2026-09-20",
        "fare_class_canonical": "Economy Saver",
        "advance_purchase_window": "T15(12-18)",
    }
    record.update(overrides)
    return record


def _frame(records):
    """Build a string-typed frame from a list of dictionaries."""
    return pd.DataFrame(records, dtype=str).fillna("")


def _run(cells=None, flights=None, observations=None):
    """Run the engine over synthetic frames."""
    cell_records = cells if cells is not None else [_cell()]
    flight_records = flights if flights is not None else [_flight()]
    observation_records = (
        observations if observations is not None else [_observation()]
    )
    return E.run_anomaly_detection(
        _frame(cell_records), _frame(flight_records), _frame(observation_records)
    )


def _rule_rows(result, rule_id, status=None):
    """All emitted evaluations for a rule, optionally filtered by status."""
    report = result.report
    subset = report[report["rule_id"] == rule_id]
    if status is not None:
        subset = subset[subset["evaluation_status"] == status]
    return subset.to_dict("records")


# ---------------------------------------------------------------------------
# Deterministic primitives
# ---------------------------------------------------------------------------
class TestPrimitives(object):
    def test_median_odd(self):
        assert R.median([Decimal("1"), Decimal("5"), Decimal("3")]) == Decimal("3")

    def test_median_even_is_midpoint(self):
        values = [Decimal("5300"), Decimal("5500")]
        assert R.median(values) == Decimal("5400")

    def test_median_empty_is_none(self):
        assert R.median([]) is None

    def test_median_absolute_deviation(self):
        values = [Decimal("1"), Decimal("2"), Decimal("3"), Decimal("4")]
        assert R.median_absolute_deviation(values) == Decimal("1.0")

    def test_robust_zscore_uses_mad(self):
        # Spread-out peers give a nonzero MAD, so the primary scale is used.
        population = [
            Decimal("100"),
            Decimal("101"),
            Decimal("102"),
            Decimal("103"),
            Decimal("104"),
            Decimal("500"),
        ]
        assert R.median_absolute_deviation(population) > Decimal("0")
        zscore, basis, centre, scale = R.robust_zscore(Decimal("500"), population)
        assert basis == R.SCALE_BASIS_MAD
        assert zscore is not None and zscore > R.R13_Z_REVIEW
        assert centre is not None and scale is not None

    def test_identical_peers_collapse_mad_to_zero(self):
        # Documents why the IQR fallback is needed: a tight cluster plus one
        # extreme value still has a zero MAD.
        population = [Decimal("100")] * 4 + [Decimal("105"), Decimal("500")]
        assert R.median_absolute_deviation(population) == Decimal("0")
        zscore, basis, centre, scale = R.robust_zscore(Decimal("500"), population)
        assert basis == R.SCALE_BASIS_IQR

    def test_robust_zscore_iqr_fallback_when_mad_zero(self):
        # MAD is exactly zero here, but the IQR is not: the fallback must engage.
        population = [Decimal("100")] * 5 + [Decimal("120"), Decimal("130")]
        assert R.median_absolute_deviation(population) == Decimal("0")
        assert R.interquartile_range(population) > Decimal("0")
        zscore, basis, centre, scale = R.robust_zscore(Decimal("130"), population)
        assert basis == R.SCALE_BASIS_IQR
        assert zscore is not None

    def test_robust_zscore_zero_dispersion_returns_none(self):
        population = [Decimal("100")] * 6
        zscore, basis, centre, scale = R.robust_zscore(Decimal("100"), population)
        assert zscore is None
        assert scale == Decimal("0")

    def test_relative_change(self):
        assert R.relative_change(Decimal("100"), Decimal("120")) == Decimal("0.2")

    def test_relative_change_zero_base_is_none(self):
        assert R.relative_change(Decimal("0"), Decimal("120")) is None

    def test_relative_spread_is_relative_not_absolute(self):
        cheap = R.relative_spread(Decimal("1000"), Decimal("1100"))
        pricey = R.relative_spread(Decimal("10000"), Decimal("11000"))
        assert cheap == pricey

    def test_severity_for_movement_thresholds(self):
        assert R.severity_for_movement(Decimal("0.10")) == R.SEVERITY_NONE
        assert R.severity_for_movement(Decimal("0.20")) == R.SEVERITY_REVIEW
        assert R.severity_for_movement(Decimal("0.35")) == R.SEVERITY_HIGH

    def test_severity_boundaries_are_strict(self):
        assert R.severity_for_movement(Decimal("0.15")) == R.SEVERITY_NONE
        assert R.severity_for_movement(Decimal("0.30")) == R.SEVERITY_REVIEW

    def test_severity_for_zscore_thresholds(self):
        assert R.severity_for_zscore(Decimal("3.0")) == R.SEVERITY_NONE
        assert R.severity_for_zscore(Decimal("4.0")) == R.SEVERITY_REVIEW
        assert R.severity_for_zscore(Decimal("8.0")) == R.SEVERITY_HIGH

    def test_cap_severity(self):
        assert R.cap_severity(R.SEVERITY_HIGH, R.SEVERITY_REVIEW) == R.SEVERITY_REVIEW
        assert R.cap_severity(R.SEVERITY_INFO, R.SEVERITY_HIGH) == R.SEVERITY_INFO

    def test_downgrade_never_falls_below_info(self):
        assert R.downgrade_severity(R.SEVERITY_HIGH) == R.SEVERITY_REVIEW
        assert R.downgrade_severity(R.SEVERITY_REVIEW) == R.SEVERITY_INFO
        assert R.downgrade_severity(R.SEVERITY_INFO) == R.SEVERITY_INFO

    def test_widened_peer_basis_capped_at_review(self):
        assert R.PEER_BASIS_MAX_SEVERITY[R.PEER_BASIS_WIDENED] == R.SEVERITY_REVIEW
        assert R.PEER_BASIS_MAX_SEVERITY[R.PEER_BASIS_WITHIN_ROUND] == R.SEVERITY_HIGH

    def test_parse_source_fare_map_uses_semicolon(self):
        parsed = R.parse_source_fare_map("Cleartrip=12723.00;MMT=11459.00")
        assert parsed == {
            "Cleartrip": Decimal("12723.00"),
            "MMT": Decimal("11459.00"),
        }

    def test_parse_bool_is_strict(self):
        assert R.parse_bool("True") is True
        assert R.parse_bool("False") is False
        assert R.parse_bool("yes") is None

    def test_is_numeric_money(self):
        assert R.is_numeric_money("5000.00") is True
        assert R.is_numeric_money("NOT_A_FARE") is False

    def test_no_route_aggregate_level_exists(self):
        assert R.LEVEL_OBSERVATION in R.ANOMALY_LEVELS
        assert R.LEVEL_PRODUCT_SERIES in R.ANOMALY_LEVELS
        for level in R.ANOMALY_LEVELS:
            assert "ROUTE_AGGREGATE" not in level

    def test_rule_registry_has_thirteen_rules(self):
        assert len(R.RULE_IDS) == 13
        assert R.RULE_IDS[0] == "R01"
        assert R.RULE_IDS[-1] == "R13"


# ---------------------------------------------------------------------------
# R01 nonpositive fare
# ---------------------------------------------------------------------------
class TestR01NonpositiveFare(object):
    def test_negative_fare_is_flagged_high(self):
        result = _run(
            observations=[
                _observation(
                    observation_id="OBS_NEG",
                    total_fare_normalized="-4500.00",
                    fare_decomposition_complete="False",
                )
            ]
        )
        flagged = _rule_rows(result, "R01", R.STATUS_FLAGGED)
        assert len(flagged) == 1
        assert flagged[0]["severity"] == R.SEVERITY_HIGH
        assert flagged[0]["observation_id"] == "OBS_NEG"

    def test_zero_fare_is_flagged(self):
        result = _run(
            observations=[
                _observation(
                    observation_id="OBS_ZERO",
                    total_fare_normalized="0.00",
                    fare_decomposition_complete="False",
                )
            ]
        )
        assert len(_rule_rows(result, "R01", R.STATUS_FLAGGED)) == 1

    def test_positive_fare_is_not_flagged(self):
        result = _run()
        assert _rule_rows(result, "R01", R.STATUS_FLAGGED) == []

    def test_sold_out_observation_is_not_evaluable(self):
        result = _run(
            observations=[
                _observation(
                    price_state="SOLD_OUT",
                    total_fare_normalized="",
                    availability_status="Sold Out",
                    participation_status="EXCLUDED_SOLD_OUT",
                    fare_decomposition_complete="False",
                )
            ]
        )
        rows = _rule_rows(result, "R01", R.STATUS_NOT_EVALUABLE)
        assert len(rows) == 1
        assert rows[0]["evaluability_reason"] == R.REASON_NO_PRICE_TO_EVALUATE

    def test_structural_flag_is_never_downgraded_by_coherence(self):
        # Multi-source, multi-flight coherence must NOT soften a structural defect.
        result = _run(
            cells=[_cell(participating_source_count="4", flight_instance_count="3")],
            observations=[
                _observation(
                    total_fare_normalized="-1.00",
                    fare_decomposition_complete="False",
                )
            ],
        )
        flagged = _rule_rows(result, "R01", R.STATUS_FLAGGED)
        assert flagged[0]["severity"] == R.SEVERITY_HIGH


# ---------------------------------------------------------------------------
# R02 nonnumeric fare
# ---------------------------------------------------------------------------
class TestR02NonnumericFare(object):
    def test_nonnumeric_fare_is_flagged_high(self):
        result = _run(
            observations=[
                _observation(
                    observation_id="OBS_TEXT",
                    total_fare_normalized="NOT_A_FARE",
                    fare_decomposition_complete="False",
                )
            ]
        )
        flagged = _rule_rows(result, "R02", R.STATUS_FLAGGED)
        assert len(flagged) == 1
        assert flagged[0]["severity"] == R.SEVERITY_HIGH
        assert flagged[0]["metric_value"] == "NOT_A_FARE"

    def test_blank_fare_is_not_evaluable_not_flagged(self):
        result = _run(
            observations=[
                _observation(
                    total_fare_normalized="",
                    price_state="SOLD_OUT",
                    fare_decomposition_complete="False",
                )
            ]
        )
        assert _rule_rows(result, "R02", R.STATUS_FLAGGED) == []
        assert len(_rule_rows(result, "R02", R.STATUS_NOT_EVALUABLE)) == 1

    def test_numeric_fare_passes_silently(self):
        result = _run()
        assert _rule_rows(result, "R02") == []


# ---------------------------------------------------------------------------
# R03 component mismatch
# ---------------------------------------------------------------------------
class TestR03ComponentMismatch(object):
    def test_mismatch_beyond_one_rupee_is_flagged(self):
        result = _run(
            observations=[
                _observation(
                    observation_id="OBS_MISMATCH",
                    total_fare_normalized="5000.00",
                    base_fare="4000.00",
                    taxes="800.00",
                    fees="100.00",
                )
            ]
        )
        flagged = _rule_rows(result, "R03", R.STATUS_FLAGGED)
        assert len(flagged) == 1
        assert flagged[0]["severity"] == R.SEVERITY_HIGH
        assert Decimal(flagged[0]["metric_value"]) == Decimal("100.00")

    def test_within_one_rupee_tolerance_passes(self):
        result = _run(
            observations=[
                _observation(
                    total_fare_normalized="5000.00",
                    base_fare="4000.00",
                    taxes="800.00",
                    fees="199.50",
                )
            ]
        )
        assert _rule_rows(result, "R03", R.STATUS_FLAGGED) == []

    def test_tolerance_is_inherited_from_phase2(self):
        assert R.R03_TOLERANCE == Decimal("1.0")

    def test_incomplete_decomposition_is_not_evaluable(self):
        result = _run(
            observations=[
                _observation(
                    fare_decomposition_complete="False",
                    base_fare="",
                    taxes="",
                    fees="",
                )
            ]
        )
        rows = _rule_rows(result, "R03", R.STATUS_NOT_EVALUABLE)
        assert len(rows) == 1
        assert rows[0]["evaluability_reason"] == R.REASON_NO_DECOMPOSITION

    def test_missing_component_is_never_reconstructed(self):
        result = _run(
            observations=[
                _observation(fare_decomposition_complete="True", fees="")
            ]
        )
        rows = _rule_rows(result, "R03", R.STATUS_NOT_EVALUABLE)
        assert len(rows) == 1
        # No flag, and nothing invented to make the sum work.
        assert _rule_rows(result, "R03", R.STATUS_FLAGGED) == []


# ---------------------------------------------------------------------------
# R04 inactive by design
# ---------------------------------------------------------------------------
class TestR04Inactive(object):
    def test_r04_is_registered_but_inactive(self):
        assert "R04" in R.RULE_IDS
        assert "R04" in R.INACTIVE_RULES
        assert R.INACTIVE_RULES["R04"] == R.REASON_NO_FROZEN_CALIBRATION_SNAPSHOT

    def test_r04_never_flags(self):
        result = _run(
            observations=[
                _observation(total_fare_normalized="999999.00"),
                _observation(observation_id="OBS2", total_fare_normalized="1.00"),
            ]
        )
        assert _rule_rows(result, "R04", R.STATUS_FLAGGED) == []

    def test_r04_emits_single_framework_row(self):
        result = _run(
            observations=[
                _observation(observation_id="OBS1"),
                _observation(observation_id="OBS2"),
                _observation(observation_id="OBS3"),
            ]
        )
        rows = _rule_rows(result, "R04", R.STATUS_NOT_EVALUABLE)
        assert len(rows) == 1
        assert rows[0]["entity_id"] == "RULE_FRAMEWORK"
        assert rows[0]["comparison_basis"] == "affected_observations=3"

    def test_r04_reason_is_frozen_snapshot_absence(self):
        result = _run()
        rows = _rule_rows(result, "R04")
        assert rows[0]["evaluability_reason"] == (
            "NO_FROZEN_CALIBRATION_SNAPSHOT"
        )
        assert rows[0]["threshold_label"] == R.CALIBRATION_ABSENT


# ---------------------------------------------------------------------------
# Additional builders for temporal / peer scenarios
# ---------------------------------------------------------------------------
def _isolated_series(fares, alignment="ANCHORED"):
    """A product series whose cells are single-source, single-flight.

    Isolated cells are used whenever a test needs to observe the RAW rule
    severity, because coherent multi-source cells are deliberately
    downgraded by the dynamic-pricing protection.
    """
    records = []
    for index, fare in enumerate(fares):
        day = index + 1
        records.append(
            _cell(
                consolidation_cell_id="CELL::POINT%02d" % index,
                collection_round_id="ROUND::2026-09-%02dT09:00" % day,
                round_sort_key="2026-09-%02d 09:00" % day,
                round_alignment=alignment,
                consolidated_fare_normalized=fare,
                participating_source_count="1",
                participating_sources="MMT",
                flight_instance_count="1",
                source_coverage="SINGLE_SOURCE",
            )
        )
    return records


def _peer_cells(fares, round_id="ROUND::2026-09-05T09:00", alignment="ANCHORED"):
    """Cells that share an R13 peer group (origin, destination, fare_class).

    They differ by travel_date so they are distinct cells, but the peer key
    intentionally ignores travel_date and advance-purchase window.
    """
    records = []
    for index, fare in enumerate(fares):
        records.append(
            _cell(
                consolidation_cell_id="CELL::PEER%02d" % index,
                travel_date_canonical="2026-10-%02d" % (index + 1),
                collection_round_id=round_id,
                round_sort_key="2026-09-05 09:00",
                round_alignment=alignment,
                consolidated_fare_normalized=fare,
                participating_source_count="1",
                participating_sources="MMT",
                flight_instance_count="1",
                source_coverage="SINGLE_SOURCE",
            )
        )
    return records


def _cell_row_of(result, cell_id):
    """The annotated primary-output record for one cell."""
    frame = result.cells
    subset = frame[frame["consolidation_cell_id"] == cell_id]
    return subset.to_dict("records")[0]


# ---------------------------------------------------------------------------
# R05 round-over-round movement
# ---------------------------------------------------------------------------
class TestR05RoundOverRoundMovement(object):
    def test_movement_above_fifteen_percent_is_review(self):
        cells = _isolated_series(["5000.00", "5100.00", "5200.00", "5300.00", "6500.00"])
        result = _run(cells=cells)
        flagged = _rule_rows(result, "R05", R.STATUS_FLAGGED)
        assert len(flagged) == 1
        assert flagged[0]["severity"] == R.SEVERITY_REVIEW
        assert Decimal(flagged[0]["metric_value"]) > Decimal("0.15")

    def test_movement_above_thirty_percent_is_high(self):
        cells = _isolated_series(["5000.00", "5100.00", "5200.00", "5300.00", "7500.00"])
        result = _run(cells=cells)
        flagged = _rule_rows(result, "R05", R.STATUS_FLAGGED)
        assert len(flagged) == 1
        assert flagged[0]["severity"] == R.SEVERITY_HIGH
        assert Decimal(flagged[0]["metric_value"]) > Decimal("0.30")

    def test_small_movement_is_not_flagged(self):
        cells = _isolated_series(["5000.00", "5100.00", "5200.00", "5300.00", "5400.00"])
        result = _run(cells=cells)
        assert _rule_rows(result, "R05", R.STATUS_FLAGGED) == []

    def test_requires_three_prior_priced_rounds(self):
        cells = _isolated_series(["5000.00", "9000.00"])
        result = _run(cells=cells)
        assert _rule_rows(result, "R05", R.STATUS_FLAGGED) == []
        not_evaluable = _rule_rows(result, "R05", R.STATUS_NOT_EVALUABLE)
        assert len(not_evaluable) == 2
        assert (
            not_evaluable[0]["evaluability_reason"]
            == R.REASON_INSUFFICIENT_PRIOR_ROUNDS
        )

    def test_fourth_point_is_the_first_evaluable_one(self):
        cells = _isolated_series(["5000.00", "5100.00", "5200.00", "5300.00"])
        result = _run(cells=cells)
        # 3 points are not evaluable, the 4th is evaluable and passes.
        assert len(_rule_rows(result, "R05", R.STATUS_NOT_EVALUABLE)) == 3

    def test_unaligned_round_is_excluded_from_temporal_history(self):
        # An extreme unaligned fare must not become part of the R05 history,
        # otherwise it would manufacture a fictitious price movement.
        cells = _isolated_series(
            ["5000.00", "5100.00", "5200.00", "5300.00", "5400.00"]
        )
        cells.append(
            _cell(
                consolidation_cell_id="CELL::UNALIGNED",
                collection_round_id="ROUND-UNALIGNED::2026-09-03 23:59",
                round_sort_key="2026-09-03 23:59",
                round_alignment="UNALIGNED",
                consolidated_fare_normalized="99000.00",
                participating_source_count="1",
                participating_sources="MMT",
                flight_instance_count="1",
            )
        )
        result = _run(cells=cells)
        assert _rule_rows(result, "R05", R.STATUS_FLAGGED) == []
        # The unaligned cell is never silently discarded: R12 records it.
        r12 = _rule_rows(result, "R12", R.STATUS_FLAGGED)
        assert len(r12) == 1
        assert r12[0]["entity_id"] == "CELL::UNALIGNED"

    def test_no_r05_evaluation_is_emitted_for_unaligned_cells(self):
        cells = _isolated_series(
            ["5000.00", "5100.00", "5200.00", "5300.00"], alignment="UNALIGNED"
        )
        result = _run(cells=cells)
        assert _rule_rows(result, "R05") == []

    def test_threshold_is_labelled_prototype_calibration(self):
        assert R.RULE_THRESHOLD_LABELS["R05"] == R.CALIBRATION_PROTOTYPE

    def test_evaluation_is_backward_looking_only(self):
        # Appending a later round must not change an earlier verdict.
        base = _isolated_series(
            ["5000.00", "5100.00", "5200.00", "5300.00", "6500.00"]
        )
        first = _rule_rows(_run(cells=base), "R05", R.STATUS_FLAGGED)
        extended = _isolated_series(
            ["5000.00", "5100.00", "5200.00", "5300.00", "6500.00", "6600.00"]
        )
        second = _rule_rows(_run(cells=extended), "R05", R.STATUS_FLAGGED)
        assert first[0]["metric_value"] == second[0]["metric_value"]
        assert first[0]["entity_id"] == second[0]["entity_id"]


# ---------------------------------------------------------------------------
# R06 sustained drift
# ---------------------------------------------------------------------------
class TestR06SustainedDrift(object):
    def test_three_same_sign_deltas_beyond_cumulative_threshold_flags(self):
        cells = _isolated_series(
            ["5000.00", "5200.00", "5400.00", "5600.00", "6600.00"]
        )
        result = _run(cells=cells)
        flagged = _rule_rows(result, "R06", R.STATUS_FLAGGED)
        assert len(flagged) == 1
        assert Decimal(flagged[0]["metric_value"]) > Decimal("0.15")
        assert flagged[0]["severity"] in (R.SEVERITY_REVIEW, R.SEVERITY_HIGH)

    def test_alternating_signs_do_not_flag(self):
        cells = _isolated_series(
            ["5000.00", "5200.00", "5000.00", "5200.00", "6600.00"]
        )
        result = _run(cells=cells)
        assert _rule_rows(result, "R06", R.STATUS_FLAGGED) == []

    def test_same_sign_but_small_cumulative_change_does_not_flag(self):
        cells = _isolated_series(
            ["5000.00", "5010.00", "5020.00", "5030.00", "5040.00"]
        )
        result = _run(cells=cells)
        assert _rule_rows(result, "R06", R.STATUS_FLAGGED) == []

    def test_requires_four_prior_points(self):
        cells = _isolated_series(["5000.00", "5200.00", "5400.00", "6600.00"])
        result = _run(cells=cells)
        assert _rule_rows(result, "R06", R.STATUS_FLAGGED) == []
        assert len(_rule_rows(result, "R06", R.STATUS_NOT_EVALUABLE)) == 4

    def test_downward_drift_also_flags(self):
        cells = _isolated_series(
            ["7000.00", "6800.00", "6600.00", "6400.00", "5400.00"]
        )
        result = _run(cells=cells)
        flagged = _rule_rows(result, "R06", R.STATUS_FLAGGED)
        assert len(flagged) == 1
        assert Decimal(flagged[0]["metric_value"]) < Decimal("0")

    def test_run_length_and_minimum_are_locked(self):
        assert R.R06_RUN_LENGTH == 3
        assert R.R06_MIN_PRIOR_PRICED_ROUNDS == 4
        assert R.R06_CUMULATIVE_THRESHOLD == Decimal("0.15")
        assert R.RULE_THRESHOLD_LABELS["R06"] == R.CALIBRATION_PROTOTYPE


# ---------------------------------------------------------------------------
# R07 source dispersion
# ---------------------------------------------------------------------------
class TestR07SourceDispersion(object):
    def test_dispersion_above_fifteen_percent_flags(self):
        result = _run(
            cells=[_cell(participating_source_count="1", flight_instance_count="1")],
            flights=[
                _flight(
                    flight_min_fare="5000.00",
                    flight_max_fare="6000.00",
                    flight_source_level_fares="Goibibo=5000.00;MMT=6000.00",
                )
            ],
        )
        flagged = _rule_rows(result, "R07", R.STATUS_FLAGGED)
        assert len(flagged) == 1
        assert Decimal(flagged[0]["metric_value"]) == Decimal("0.200000")

    def test_dispersion_below_threshold_passes(self):
        result = _run(
            flights=[
                _flight(
                    flight_min_fare="5000.00",
                    flight_max_fare="5500.00",
                    flight_source_level_fares="Goibibo=5000.00;MMT=5500.00",
                )
            ]
        )
        assert _rule_rows(result, "R07", R.STATUS_FLAGGED) == []

    def test_uses_relative_not_absolute_spread(self):
        # Absolute spread of INR 1500 on an expensive flight does NOT flag,
        # while an absolute spread of INR 200 on a cheap one DOES.
        expensive = _run(
            flights=[
                _flight(
                    flight_min_fare="30000.00",
                    flight_max_fare="31500.00",
                    flight_source_level_fares="Goibibo=30000.00;MMT=31500.00",
                )
            ]
        )
        cheap = _run(
            cells=[_cell(participating_source_count="1", flight_instance_count="1")],
            flights=[
                _flight(
                    flight_min_fare="1000.00",
                    flight_max_fare="1200.00",
                    flight_source_level_fares="Goibibo=1000.00;MMT=1200.00",
                )
            ],
        )
        assert _rule_rows(expensive, "R07", R.STATUS_FLAGGED) == []
        assert len(_rule_rows(cheap, "R07", R.STATUS_FLAGGED)) == 1

    def test_single_source_is_not_evaluable(self):
        result = _run(
            flights=[
                _flight(
                    flight_source_count="1",
                    flight_sources="MMT",
                    flight_source_level_fares="MMT=5000.00",
                )
            ]
        )
        rows = _rule_rows(result, "R07", R.STATUS_NOT_EVALUABLE)
        assert len(rows) == 1
        assert rows[0]["evaluability_reason"] == R.REASON_SINGLE_SOURCE

    def test_sold_out_flight_cell_is_not_evaluable(self):
        result = _run(
            flights=[
                _flight(
                    price_state="SOLD_OUT",
                    flight_min_fare="",
                    flight_max_fare="",
                    flight_source_level_fares="",
                    flight_source_count="0",
                    flight_sources="",
                )
            ]
        )
        rows = _rule_rows(result, "R07", R.STATUS_NOT_EVALUABLE)
        assert len(rows) == 1
        assert rows[0]["evaluability_reason"] == R.REASON_NO_PRICE_TO_EVALUATE

    def test_threshold_is_prototype_calibration(self):
        assert R.R07_DISPERSION_THRESHOLD == Decimal("0.15")
        assert R.RULE_THRESHOLD_LABELS["R07"] == R.CALIBRATION_PROTOTYPE


# ---------------------------------------------------------------------------
# R08 source-level deviation
# ---------------------------------------------------------------------------
class TestR08SourceLevelDeviation(object):
    def test_two_sources_are_not_evaluable(self):
        result = _run()
        rows = _rule_rows(result, "R08", R.STATUS_NOT_EVALUABLE)
        assert len(rows) == 1
        assert rows[0]["evaluability_reason"] == (
            "INSUFFICIENT_SOURCE_COUNT_FOR_ATTRIBUTION"
        )

    def test_two_source_difference_is_never_attributed(self):
        result = _run(
            flights=[
                _flight(
                    flight_min_fare="5000.00",
                    flight_max_fare="9000.00",
                    flight_source_level_fares="Goibibo=5000.00;MMT=9000.00",
                )
            ]
        )
        assert _rule_rows(result, "R08", R.STATUS_FLAGGED) == []

    def test_three_sources_enable_attribution(self):
        result = _run(
            cells=[_cell(participating_source_count="1", flight_instance_count="1")],
            flights=[
                _flight(
                    flight_source_count="3",
                    flight_sources="Cleartrip;Goibibo;MMT",
                    flight_source_level_fares=(
                        "Cleartrip=7000.00;Goibibo=5000.00;MMT=5000.00"
                    ),
                    flight_min_fare="5000.00",
                    flight_max_fare="7000.00",
                )
            ],
        )
        flagged = _rule_rows(result, "R08", R.STATUS_FLAGGED)
        assert len(flagged) == 1
        assert "Cleartrip" in flagged[0]["comparison_basis"]

    def test_three_agreeing_sources_do_not_flag(self):
        result = _run(
            flights=[
                _flight(
                    flight_source_count="3",
                    flight_sources="Cleartrip;Goibibo;MMT",
                    flight_source_level_fares=(
                        "Cleartrip=5050.00;Goibibo=5000.00;MMT=5025.00"
                    ),
                    flight_min_fare="5000.00",
                    flight_max_fare="5050.00",
                )
            ]
        )
        assert _rule_rows(result, "R08", R.STATUS_FLAGGED) == []

    def test_minimum_source_count_is_three(self):
        assert R.R08_MIN_SOURCES == 3


# ---------------------------------------------------------------------------
# R09 thin source coverage
# ---------------------------------------------------------------------------
class TestR09ThinSourceCoverage(object):
    def test_single_source_cell_is_info(self):
        result = _run(
            cells=[
                _cell(
                    participating_source_count="1",
                    participating_sources="MMT",
                    source_coverage="SINGLE_SOURCE",
                )
            ]
        )
        flagged = _rule_rows(result, "R09", R.STATUS_FLAGGED)
        assert len(flagged) == 1
        assert flagged[0]["severity"] == R.SEVERITY_INFO

    def test_multi_source_cell_is_not_flagged(self):
        result = _run()
        assert _rule_rows(result, "R09", R.STATUS_FLAGGED) == []

    def test_thin_coverage_can_never_exceed_info(self):
        assert R.RULE_MAX_SEVERITY["R09"] == R.SEVERITY_INFO

    def test_thin_coverage_does_not_recommend_review(self):
        result = _run(
            cells=[_cell(participating_source_count="1", source_coverage="SINGLE_SOURCE")]
        )
        flagged = _rule_rows(result, "R09", R.STATUS_FLAGGED)
        assert flagged[0]["recommended_review"] == "False"


# ---------------------------------------------------------------------------
# R10 insufficient history
# ---------------------------------------------------------------------------
class TestR10InsufficientHistory(object):
    def test_short_series_is_flagged_info_at_series_level(self):
        result = _run(cells=_isolated_series(["5000.00", "5100.00"]))
        flagged = _rule_rows(result, "R10", R.STATUS_FLAGGED)
        assert len(flagged) == 1
        assert flagged[0]["severity"] == R.SEVERITY_INFO
        assert flagged[0]["entity_id"].startswith("SERIES::")
        assert flagged[0]["anomaly_level"] == R.LEVEL_PRODUCT_SERIES

    def test_sufficient_series_is_not_flagged(self):
        result = _run(
            cells=_isolated_series(
                ["5000.00", "5100.00", "5200.00", "5300.00", "5400.00"]
            )
        )
        assert _rule_rows(result, "R10", R.STATUS_FLAGGED) == []

    def test_no_history_is_manufactured(self):
        result = _run(cells=_isolated_series(["5000.00"]))
        series = result.series.to_dict("records")
        assert len(series) == 1
        assert series[0]["anchored_priced_round_count"] == "1"
        assert series[0]["history_status"] == "INSUFFICIENT_FOR_R05"
        assert series[0]["max_abs_round_over_round_change"] == ""


# ---------------------------------------------------------------------------
# R11 no-price cell
# ---------------------------------------------------------------------------
class TestR11NoPriceCell(object):
    def test_no_price_cell_is_info(self):
        result = _run(
            cells=[
                _cell(
                    price_state="NO_PRICE_CELL",
                    consolidated_fare_normalized="",
                    consolidation_status="NO_PRICE_ALL_SOLD_OUT",
                    participating_source_count="0",
                    participating_sources="",
                    source_coverage="NO_PRICED_SOURCE",
                )
            ]
        )
        flagged = _rule_rows(result, "R11", R.STATUS_FLAGGED)
        assert len(flagged) == 1
        assert flagged[0]["severity"] == R.SEVERITY_INFO

    def test_no_price_cell_is_retained_without_imputation(self):
        result = _run(
            cells=[
                _cell(
                    price_state="NO_PRICE_CELL",
                    consolidated_fare_normalized="",
                    consolidation_status="NO_PRICE_ALL_SOLD_OUT",
                )
            ]
        )
        assert len(result.cells.index) == 1
        record = result.cells.to_dict("records")[0]
        assert record["retained"] == "True"
        # No imputation and no zero price were substituted.
        assert record["consolidated_fare_normalized"] == ""

    def test_priced_cell_is_not_flagged(self):
        result = _run()
        assert _rule_rows(result, "R11", R.STATUS_FLAGGED) == []


# ---------------------------------------------------------------------------
# R12 unaligned round context
# ---------------------------------------------------------------------------
class TestR12UnalignedRoundContext(object):
    def test_unaligned_cell_is_info(self):
        result = _run(
            cells=[
                _cell(
                    round_alignment="UNALIGNED",
                    collection_round_id="ROUND-UNALIGNED::2026-09-05 23:59",
                    round_sort_key="2026-09-05 23:59",
                )
            ]
        )
        flagged = _rule_rows(result, "R12", R.STATUS_FLAGGED)
        assert len(flagged) == 1
        assert flagged[0]["severity"] == R.SEVERITY_INFO

    def test_anchored_cell_is_not_flagged(self):
        result = _run()
        assert _rule_rows(result, "R12", R.STATUS_FLAGGED) == []

    def test_unaligned_cell_is_never_discarded(self):
        result = _run(
            cells=[
                _cell(round_alignment="UNALIGNED", collection_round_id="ROUND-UNALIGNED::x")
            ]
        )
        assert len(result.cells.index) == 1
        assert result.cells.to_dict("records")[0]["retained"] == "True"


# ---------------------------------------------------------------------------
# R13 robust peer outlier
# ---------------------------------------------------------------------------
class TestR13RobustPeerOutlier(object):
    def test_within_round_mad_outlier_can_reach_high(self):
        cells = _peer_cells(
            ["5000.00", "5100.00", "5200.00", "5300.00", "9000.00"]
        )
        result = _run(cells=cells)
        flagged = _rule_rows(result, "R13", R.STATUS_FLAGGED)
        assert len(flagged) == 1
        assert flagged[0]["severity"] == R.SEVERITY_HIGH
        assert "peer_basis=%s" % R.PEER_BASIS_WITHIN_ROUND in (
            flagged[0]["comparison_basis"]
        )

    def test_peer_basis_is_recorded_on_the_cell(self):
        cells = _peer_cells(
            ["5000.00", "5100.00", "5200.00", "5300.00", "9000.00"]
        )
        result = _run(cells=cells)
        record = _cell_row_of(result, "CELL::PEER04")
        assert record["r13_peer_basis"] == R.PEER_BASIS_WITHIN_ROUND
        assert record["r13_scale_basis"] == R.SCALE_BASIS_MAD
        assert Decimal(record["r13_modified_zscore"]) > R.R13_Z_REVIEW

    def test_widened_peer_group_is_capped_at_review(self):
        # Only 3 peers in the round, so the comparison widens across rounds
        # and can never be HIGH however extreme the z-score is.
        cells = _peer_cells(["5000.00", "5100.00", "20000.00"])
        result = _run(cells=cells)
        flagged = _rule_rows(result, "R13", R.STATUS_FLAGGED)
        assert len(flagged) == 1
        assert flagged[0]["severity"] == R.SEVERITY_REVIEW
        assert flagged[0]["severity_before_context"] == R.SEVERITY_HIGH
        record = _cell_row_of(result, "CELL::PEER02")
        assert record["r13_peer_basis"] == R.PEER_BASIS_WIDENED

    def test_mad_zero_uses_iqr_fallback(self):
        cells = _peer_cells(
            ["5000.00", "5000.00", "5000.00", "5000.00", "5000.00",
             "6000.00", "6500.00"]
        )
        result = _run(cells=cells)
        record = _cell_row_of(result, "CELL::PEER06")
        assert record["r13_scale_basis"] == R.SCALE_BASIS_IQR
        assert record["r13_modified_zscore"] != ""

    def test_zero_dispersion_is_not_evaluable(self):
        cells = _peer_cells(["5000.00"] * 6)
        result = _run(cells=cells)
        rows = _rule_rows(result, "R13", R.STATUS_NOT_EVALUABLE)
        assert len(rows) == 6
        assert rows[0]["evaluability_reason"] == R.REASON_ZERO_DISPERSION

    def test_too_few_peers_is_not_evaluable(self):
        cells = _peer_cells(["5000.00", "9000.00"])
        result = _run(cells=cells)
        rows = _rule_rows(result, "R13", R.STATUS_NOT_EVALUABLE)
        assert len(rows) == 2
        assert rows[0]["evaluability_reason"] == R.REASON_INSUFFICIENT_PEERS

    def test_unaligned_rounds_are_still_evaluated_cross_sectionally(self):
        # This is what keeps engineered cases such as OBS00776 detectable.
        cells = _peer_cells(
            ["5000.00", "5100.00", "5200.00", "5300.00", "9000.00"],
            round_id="ROUND-UNALIGNED::2026-09-05 23:59",
            alignment="UNALIGNED",
        )
        result = _run(cells=cells)
        flagged = _rule_rows(result, "R13", R.STATUS_FLAGGED)
        assert len(flagged) == 1
        assert flagged[0]["round_alignment"] == "UNALIGNED"

    def test_no_price_cell_is_not_evaluable_for_r13(self):
        result = _run(
            cells=[
                _cell(price_state="NO_PRICE_CELL", consolidated_fare_normalized="")
            ]
        )
        rows = _rule_rows(result, "R13", R.STATUS_NOT_EVALUABLE)
        assert len(rows) == 1
        assert rows[0]["evaluability_reason"] == R.REASON_NO_PRICE_TO_EVALUATE

    def test_expensive_fare_is_flagged_but_never_replaced(self):
        cells = _peer_cells(
            ["5000.00", "5100.00", "5200.00", "5300.00", "9000.00"]
        )
        result = _run(cells=cells)
        record = _cell_row_of(result, "CELL::PEER04")
        # The fare itself is untouched: Phase 9 annotates, it does not correct.
        assert record["consolidated_fare_normalized"] == "9000.00"
        assert record["retained"] == "True"

    def test_peer_group_ignores_travel_date_and_window(self):
        first = R.peer_group_key("DEL", "BOM", "Economy Saver")
        assert first == "PEER::DEL|BOM|Economy Saver"

    def test_mad_constant_and_threshold_are_locked(self):
        assert R.R13_MAD_SCALE == Decimal("0.6745")
        assert R.R13_Z_REVIEW == Decimal("3.5")
        assert R.R13_Z_HIGH == Decimal("7.0")
        assert R.R13_MIN_PEER_COUNT == 5


# ---------------------------------------------------------------------------
# Dynamic pricing protection
# ---------------------------------------------------------------------------
def _coherent_series(fares):
    """A series whose cells are corroborated by many sources and flights."""
    records = []
    for index, fare in enumerate(fares):
        day = index + 1
        records.append(
            _cell(
                consolidation_cell_id="CELL::COH%02d" % index,
                collection_round_id="ROUND::2026-09-%02dT09:00" % day,
                round_sort_key="2026-09-%02d 09:00" % day,
                consolidated_fare_normalized=fare,
                participating_source_count="4",
                participating_sources="AirlineSite;Cleartrip;Goibibo;MMT",
                flight_instance_count="3",
                source_coverage="FULL_COVERAGE",
            )
        )
    return records


class TestDynamicPricingProtection(object):
    def test_coherent_movement_is_downgraded(self):
        cells = _coherent_series(
            ["5000.00", "5100.00", "5200.00", "5300.00", "6500.00"]
        )
        result = _run(cells=cells)
        flagged = _rule_rows(result, "R05", R.STATUS_FLAGGED)
        assert len(flagged) == 1
        assert flagged[0]["severity_before_context"] == R.SEVERITY_REVIEW
        assert flagged[0]["severity"] == R.SEVERITY_INFO
        assert flagged[0]["market_movement_class"] == R.MARKET_COHERENT

    def test_isolated_movement_keeps_its_severity(self):
        cells = _isolated_series(
            ["5000.00", "5100.00", "5200.00", "5300.00", "6500.00"]
        )
        result = _run(cells=cells)
        flagged = _rule_rows(result, "R05", R.STATUS_FLAGGED)
        assert flagged[0]["severity"] == R.SEVERITY_REVIEW
        assert flagged[0]["market_movement_class"] == R.MARKET_ISOLATED

    def test_sharp_move_alone_is_not_treated_as_suspicious(self):
        # Same 22.6 percent move: corroborated becomes INFO, isolated stays REVIEW.
        coherent = _rule_rows(
            _run(cells=_coherent_series(
                ["5000.00", "5100.00", "5200.00", "5300.00", "6500.00"]
            )),
            "R05",
            R.STATUS_FLAGGED,
        )
        isolated = _rule_rows(
            _run(cells=_isolated_series(
                ["5000.00", "5100.00", "5200.00", "5300.00", "6500.00"]
            )),
            "R05",
            R.STATUS_FLAGGED,
        )
        assert coherent[0]["metric_value"] == isolated[0]["metric_value"]
        assert R.SEVERITY_RANK[coherent[0]["severity"]] < (
            R.SEVERITY_RANK[isolated[0]["severity"]]
        )

    def test_context_never_escalates_severity(self):
        for rule_id in ("R05", "R06", "R07", "R13"):
            for severity in (R.SEVERITY_INFO, R.SEVERITY_REVIEW, R.SEVERITY_HIGH):
                for market in (
                    R.MARKET_COHERENT,
                    R.MARKET_ISOLATED,
                    R.MARKET_INDETERMINATE,
                ):
                    adjusted = R.apply_market_context(rule_id, severity, market)
                    assert R.SEVERITY_RANK[adjusted] <= R.SEVERITY_RANK[severity]

    def test_structural_rules_are_immune_to_context(self):
        for rule_id in R.STRUCTURAL_RULE_IDS:
            adjusted = R.apply_market_context(
                rule_id, R.SEVERITY_HIGH, R.MARKET_COHERENT
            )
            assert adjusted == R.SEVERITY_HIGH

    def test_downgrade_never_removes_the_flag(self):
        cells = _coherent_series(
            ["5000.00", "5100.00", "5200.00", "5300.00", "6500.00"]
        )
        result = _run(cells=cells)
        flagged = _rule_rows(result, "R05", R.STATUS_FLAGGED)
        # Downgraded, but still recorded and still auditable.
        assert len(flagged) == 1
        assert flagged[0]["evaluation_status"] == R.STATUS_FLAGGED


# ---------------------------------------------------------------------------
# Retention, scope and schema boundaries
# ---------------------------------------------------------------------------
class TestRetentionAndScope(object):
    def test_row_counts_are_invariant(self):
        cells = _isolated_series(["5000.00", "5100.00", "5200.00"])
        observations = [
            _observation(observation_id="OBS1"),
            _observation(observation_id="OBS2", total_fare_normalized="-5.00",
                         fare_decomposition_complete="False"),
            _observation(observation_id="OBS3"),
        ]
        result = _run(cells=cells, observations=observations)
        assert len(result.cells.index) == 3
        assert len(result.observations.index) == 3

    def test_structurally_anomalous_observation_is_retained(self):
        result = _run(
            observations=[
                _observation(
                    observation_id="OBS_BAD",
                    total_fare_normalized="-4500.00",
                    fare_decomposition_complete="False",
                )
            ]
        )
        records = result.observations.to_dict("records")
        assert len(records) == 1
        assert records[0]["observation_id"] == "OBS_BAD"
        assert records[0]["retained"] == "True"
        assert records[0]["observation_severity_max"] == R.SEVERITY_HIGH
        assert records[0]["total_fare_normalized"] == "-4500.00"

    def test_no_index_eligibility_field_is_produced(self):
        result = _run()
        for frame in (
            result.cells,
            result.report,
            result.observations,
            result.series,
            result.sources,
        ):
            assert "index_eligible" not in frame.columns

    def test_forbidden_fields_are_absent(self):
        result = _run()
        for name in R.FORBIDDEN_OUTPUT_FIELDS:
            for frame in (
                result.cells,
                result.report,
                result.observations,
                result.series,
                result.sources,
            ):
                assert name not in frame.columns

    def test_phase8_input_frame_is_not_mutated(self):
        cells = _frame([_cell()])
        before = cells.copy(deep=True)
        E.run_anomaly_detection(cells, _frame([_flight()]), _frame([_observation()]))
        assert list(cells.columns) == list(before.columns)
        assert cells.equals(before)

    def test_every_phase8_column_is_carried_through(self):
        cells = _frame([_cell()])
        result = E.run_anomaly_detection(
            cells, _frame([_flight()]), _frame([_observation()])
        )
        for name in cells.columns:
            assert name in result.cells.columns

    def test_report_only_contains_flagged_or_not_evaluable(self):
        result = _run(
            cells=_isolated_series(["5000.00", "5100.00", "5200.00", "5300.00"])
        )
        statuses = set(result.report["evaluation_status"].tolist())
        assert statuses.issubset({R.STATUS_FLAGGED, R.STATUS_NOT_EVALUABLE})

    def test_every_report_row_is_traceable_and_versioned(self):
        result = _run(
            cells=_isolated_series(["5000.00", "5100.00", "5200.00", "5300.00"])
        )
        for record in result.report.to_dict("records"):
            assert record["entity_id"] != ""
            assert record["rule_id"] in R.RULE_IDS
            assert record["anomaly_level"] in R.ANOMALY_LEVELS
            assert record["phase9_schema_version"] == R.PHASE9_SCHEMA_VERSION
            assert record["explanation"] != ""

    def test_no_route_aggregate_output_exists(self):
        result = _run()
        for frame in (result.cells, result.report, result.series):
            for name in frame.columns:
                assert "route_aggregate" not in name

    def test_engine_declares_no_ml_and_no_randomness(self):
        assert R.USES_MACHINE_LEARNING is False
        assert R.USES_RANDOMNESS is False
        assert R.DELETES_OBSERVATIONS is False
        assert R.PERFORMS_IMPUTATION is False
        assert R.ALT_SOURCE_FIRST_FARE_IS_DIAGNOSTIC_ONLY is True

    def test_missing_required_column_fails_loudly(self):
        broken = _frame([_cell()]).drop(columns=["price_state"])
        with pytest.raises(R.AnomalyRuleError):
            E.run_anomaly_detection(
                broken, _frame([_flight()]), _frame([_observation()])
            )


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------
class TestDeterminism(object):
    def test_running_twice_gives_identical_output(self):
        cells = _peer_cells(
            ["5000.00", "5100.00", "5200.00", "5300.00", "9000.00"]
        )
        first = _run(cells=cells)
        second = _run(cells=cells)
        assert first.report.equals(second.report)
        assert first.cells.equals(second.cells)
        assert first.series.equals(second.series)
        assert first.sources.equals(second.sources)

    def test_input_order_does_not_change_results(self):
        cells = _peer_cells(
            ["5000.00", "5100.00", "5200.00", "5300.00", "9000.00"]
        )
        forward = _run(cells=cells)
        backward = _run(cells=list(reversed(cells)))
        assert forward.report.equals(backward.report)
        # The primary output follows input order, so compare it as a set.
        forward_ids = sorted(forward.cells["anomaly_rule_ids"].tolist())
        backward_ids = sorted(backward.cells["anomaly_rule_ids"].tolist())
        assert forward_ids == backward_ids

    def test_temporal_order_uses_round_sort_key_not_round_id(self):
        # 'ROUND-UNALIGNED::' sorts lexically BEFORE 'ROUND::' because '-' is
        # 0x2D and ':' is 0x3A, so raw round ids must never drive ordering.
        assert "ROUND-UNALIGNED::2026-09-30" < "ROUND::2026-09-01"

    def test_report_is_sorted_deterministically(self):
        result = _run(
            cells=_isolated_series(["5000.00", "5100.00", "5200.00", "5300.00"])
        )
        keys = [
            (
                record["rule_id"],
                record["anomaly_level"],
                record["entity_id"],
                record["evaluation_status"],
            )
            for record in result.report.to_dict("records")
        ]
        assert keys == sorted(keys)


# ---------------------------------------------------------------------------
# Code quality guards
# ---------------------------------------------------------------------------
PHASE9_SOURCES = (
    os.path.join(REPO_ROOT, "src", "anomaly_detection", "rules.py"),
    os.path.join(REPO_ROOT, "src", "anomaly_detection", "anomaly_engine.py"),
    os.path.join(REPO_ROOT, "src", "anomaly_detection", "__init__.py"),
    os.path.join(REPO_ROOT, "scripts", "run_anomaly_detection.py"),
    os.path.join(REPO_ROOT, "tests", "test_anomaly_detection.py"),
)


def _source_text(path):
    handle = open(path, "r", encoding="utf-8")
    try:
        return handle.read()
    finally:
        handle.close()


class TestCodeQualityGuard(object):
    def test_no_attribute_style_row_access(self):
        pattern = re.compile(r"\b" + "row" + r"\.[A-Za-z_]")
        for path in PHASE9_SOURCES:
            if not os.path.exists(path):
                continue
            assert pattern.search(_source_text(path)) is None, (
                "attribute-style row access in %s" % path
            )

    def test_no_tuple_row_iteration(self):
        token = "iter" + "tuples"
        for path in PHASE9_SOURCES:
            if not os.path.exists(path):
                continue
            assert token not in _source_text(path)

    def test_no_float_in_economic_path(self):
        token = "float" + "("
        for name in ("rules.py", "anomaly_engine.py"):
            path = os.path.join(REPO_ROOT, "src", "anomaly_detection", name)
            assert token not in _source_text(path)

    def test_no_machine_learning_or_randomness(self):
        for path in PHASE9_SOURCES:
            if not os.path.exists(path):
                continue
            text = _source_text(path)
            # Tokens are assembled at runtime so this guard cannot match itself.
            banned_tokens = (
                "sk" + "learn",
                "Isolation" + "Forest",
                "numpy." + "random",
            )
            for banned in banned_tokens:
                assert banned not in text, "%s found in %s" % (banned, path)
            assert "import " + "random" not in text

    def test_upstream_tolerances_are_not_imported(self):
        for name in ("rules.py", "anomaly_engine.py"):
            path = os.path.join(REPO_ROOT, "src", "anomaly_detection", name)
            text = _source_text(path)
            assert "TIME_TOLERANCE_MINUTES" not in text
            assert "ROUND_TOLERANCE_MINUTES" not in text

    def test_alt_source_first_fare_is_never_read(self):
        path = os.path.join(
            REPO_ROOT, "src", "anomaly_detection", "anomaly_engine.py"
        )
        text = _source_text(path)
        assert 'row["alt_source_first_fare"]' not in text
