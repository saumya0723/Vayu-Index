"""
VAYU INDEX — Phase 7 Source Consolidation Test Suite
======================================================

Covers the full approved Phase 7 test plan:
  median definition (2/4/odd/decimal midpoint), Stage 0, Stage 1, Stage 2,
  the flight-first hierarchy, no accidental source weighting, no flight
  double-counting, Option B diagnostic non-influence, collection-round
  assignment, +/-30 inclusive / 31 exclusive, unaligned rounds, missing
  timestamp, missing source, single-source fallback, source coverage,
  sold-out handling, missing price, high-price preservation, dispersion,
  audit completeness, raw observation preservation, deterministic reruns,
  shuffled-input equivalence, route-direction preservation, and Phase 6
  regression.

Run from the repository root.
"""

import hashlib
import os
import sys
from decimal import Decimal

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.consolidation import consolidation_engine as E
from src.consolidation import rules as R


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURE_CSV = os.path.join(REPO_ROOT, "tests", "fixtures", "phase7_synthetic.csv")
CANONICAL_CSV = os.path.join(REPO_ROOT, "outputs", "canonical_airfare_observations.csv")
DEDUPLICATED_CSV = os.path.join(
    REPO_ROOT, "outputs", "deduplicated_airfare_observations.csv"
)
AUDIT_CSV = os.path.join(REPO_ROOT, "outputs", "phase6_duplicate_audit_report.csv")

# Byte-level Phase 6 baseline recorded before any Phase 7 work started.
PHASE6_BASELINE_SHA256 = {
    DEDUPLICATED_CSV: "6c51ea30d1728d959afdd91c1fea3fc6f2524c8b49875ecfea7791cf79a0a7d9",
    CANONICAL_CSV: "1223c7b15e7a2eec4798565f9d5013085e8cb3c64b82c17dca9f5375178c488c",
    AUDIT_CSV: "86afc9b8378ddd127d10002537669ae263da5f7dca86548aaca84a32f8d14030",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _base_row(**overrides):
    """A single canonical-shaped observation. All fields overridable."""
    row = {
        "observation_id": "OBS00001",
        "capture_signature": "sig-0001",
        "economic_signature": "econ-0001",
        "origin": "DEL",
        "destination": "BOM",
        "carrier": "6E",
        "flight_number": "6E-2341",
        "travel_date": "2026-09-20",
        "departure_time": "08:10",
        "collection_timestamp": "2026-09-05 09:00",
        "advance_purchase_days": "15",
        "advance_purchase_window": "T15(12-18)",
        "fare_class": "Economy Saver",
        "base_fare": "4700",
        "taxes": "500",
        "fees": "200",
        "total_fare": "5400",
        "source": "AirlineSite",
        "availability_status": "Available",
        "is_valid": "True",
        "validation_status": "VALID",
        "validation_reason": "",
        "validation_errors": "",
        "duplicate_group_id": "SINGLETON::OBS00001",
        "is_duplicate": "False",
        "duplicate_of": "",
        "duplicate_reason": "RETAINED_UNIQUE",
        "retained": "True",
        "capture_signature_agreement": "",
    }
    row.update(overrides)
    return row


def _run(*rows):
    return E.run_consolidation(pd.DataFrame(list(rows)))


def _cell(result, index=0):
    return result.consolidated.iloc[index]


def _only_cell(result):
    assert len(result.consolidated) == 1, (
        "expected exactly one consolidation cell, got %d" % len(result.consolidated)
    )
    return result.consolidated.iloc[0]


def _map_row(result, observation_id):
    matches = result.observation_map[
        result.observation_map["observation_id"] == observation_id
    ]
    assert len(matches) == 1
    return matches.iloc[0]


def _sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _fixture_df():
    return E.read_canonical_csv(FIXTURE_CSV)


def _fixture_result():
    return E.run_consolidation(_fixture_df())


def _cell_by_travel_date(result, travel_date, origin=None):
    frame = result.consolidated[result.consolidated["travel_date"] == travel_date]
    if origin is not None:
        frame = frame[frame["origin"] == origin]
    assert len(frame) == 1, "expected 1 cell for %s, got %d" % (travel_date, len(frame))
    return frame.iloc[0]


# ---------------------------------------------------------------------------
# 1. Median definition
# ---------------------------------------------------------------------------


class TestMidpointMedian:
    def test_midpoint_median_two_values(self):
        assert R.midpoint_median([Decimal("5300"), Decimal("5500")]) == Decimal("5400.00")

    def test_midpoint_median_four_values(self):
        values = [Decimal("5000"), Decimal("5200"), Decimal("5600"), Decimal("6000")]
        assert R.midpoint_median(values) == Decimal("5400.00")

    def test_midpoint_median_odd_count(self):
        values = [Decimal("5000"), Decimal("5200"), Decimal("6000")]
        assert R.midpoint_median(values) == Decimal("5200.00")

    def test_midpoint_median_single_value(self):
        assert R.midpoint_median([Decimal("7000")]) == Decimal("7000.00")

    def test_midpoint_median_is_order_independent(self):
        forward = [Decimal("5000"), Decimal("5200"), Decimal("5600"), Decimal("6000")]
        assert R.midpoint_median(forward) == R.midpoint_median(list(reversed(forward)))

    def test_midpoint_median_produces_half_rupee_midpoint(self):
        # A derived statistic may legitimately be a non-observed midpoint.
        assert R.midpoint_median([Decimal("5300"), Decimal("5550")]) == Decimal("5425.00")

    def test_midpoint_median_retains_two_decimal_places(self):
        result = R.midpoint_median([Decimal("11041"), Decimal("11042.50")])
        assert R.format_money(result) == "11041.75"

    def test_no_lower_median_downward_bias(self):
        # The rejected lower-median rule would have returned 5300.
        assert R.midpoint_median([Decimal("5300"), Decimal("5500")]) != Decimal("5300")

    def test_money_path_uses_decimal_not_float(self):
        assert isinstance(R.parse_money("5400"), Decimal)
        assert isinstance(R.midpoint_median([Decimal("1"), Decimal("2")]), Decimal)

    def test_missing_price_is_none_never_zero(self):
        assert R.parse_money("") is None
        assert R.parse_money(None) is None
        assert R.parse_money("n/a") is None


# ---------------------------------------------------------------------------
# 2. Collection-round assignment
# ---------------------------------------------------------------------------


class TestCollectionRoundAssignment:
    def test_exact_anchor_is_anchored(self):
        round_id, alignment, anchor = R.assign_collection_round(
            "2026-09-05 14:30", "OBS1"
        )
        assert alignment == R.ROUND_ALIGNMENT_ANCHORED
        assert round_id == "ROUND::2026-09-05T14:30"
        assert anchor == "2026-09-05 14:30"

    def test_nearest_anchor_is_selected(self):
        round_id, alignment, _ = R.assign_collection_round("2026-09-05 20:00", "OBS1")
        assert alignment == R.ROUND_ALIGNMENT_ANCHORED
        assert round_id == "ROUND::2026-09-05T20:15"

    def test_plus_thirty_minutes_is_inclusive(self):
        _, alignment, _ = R.assign_collection_round("2026-09-05 09:30", "OBS1")
        assert alignment == R.ROUND_ALIGNMENT_ANCHORED

    def test_minus_thirty_minutes_is_inclusive(self):
        _, alignment, _ = R.assign_collection_round("2026-09-05 08:30", "OBS1")
        assert alignment == R.ROUND_ALIGNMENT_ANCHORED

    def test_thirty_one_minutes_is_exclusive(self):
        round_id, alignment, anchor = R.assign_collection_round(
            "2026-09-05 09:31", "OBS1"
        )
        assert alignment == R.ROUND_ALIGNMENT_UNALIGNED
        assert round_id == "ROUND-UNALIGNED::2026-09-05 09:31"
        assert anchor == ""

    def test_far_capture_becomes_unaligned_singleton_round(self):
        round_id, alignment, _ = R.assign_collection_round("2026-09-05 23:59", "OBS1")
        assert alignment == R.ROUND_ALIGNMENT_UNALIGNED
        assert round_id.startswith(R.UNALIGNED_ROUND_ID_PREFIX)

    def test_missing_timestamp_is_unresolved(self):
        round_id, alignment, _ = R.assign_collection_round("", "OBS00781")
        assert alignment == R.ROUND_ALIGNMENT_UNRESOLVED
        assert round_id == "ROUND-UNRESOLVED::OBS00781"

    def test_unparseable_timestamp_is_unresolved(self):
        _, alignment, _ = R.assign_collection_round("not-a-timestamp", "OBS1")
        assert alignment == R.ROUND_ALIGNMENT_UNRESOLVED

    def test_rounds_are_date_scoped(self):
        first, _, _ = R.assign_collection_round("2026-09-05 09:00", "A")
        second, _, _ = R.assign_collection_round("2026-09-06 09:00", "B")
        assert first != second

    def test_phase7_tolerance_is_independent_of_phase6(self):
        from src.deduplication import rules as dedup_rules

        assert R.ROUND_TOLERANCE_MINUTES == 30
        assert dedup_rules.TIME_TOLERANCE_MINUTES == 15
        assert R.ROUND_TOLERANCE_MINUTES != dedup_rules.TIME_TOLERANCE_MINUTES

    def test_anchors_documented_as_prototype_configuration(self):
        assert R.ROUND_ANCHORS_ARE_PROTOTYPE_CONFIG is True
        assert "not a finalized production sampling schedule" in R.ROUND_ANCHORS_PROVENANCE


# ---------------------------------------------------------------------------
# 3. Stage 0 / Stage 1 / Stage 2
# ---------------------------------------------------------------------------


class TestStage0WithinSource:
    def test_same_source_same_flight_collapses_to_one_vote(self):
        result = _run(
            _base_row(
                observation_id="OBS1",
                source="Goibibo",
                total_fare="4000",
                collection_timestamp="2026-09-05 14:20",
            ),
            _base_row(
                observation_id="OBS2",
                source="Goibibo",
                total_fare="4200",
                collection_timestamp="2026-09-05 14:40",
            ),
            _base_row(
                observation_id="OBS3",
                source="Cleartrip",
                total_fare="5000",
                collection_timestamp="2026-09-05 14:30",
            ),
        )
        flight = result.flight_cells.iloc[0]
        # Goibibo -> midpoint(4000, 4200) = 4100; then midpoint(4100, 5000).
        assert flight["flight_source_level_fares"] == "Cleartrip=5000.00;Goibibo=4100.00"
        assert flight["flight_representative_fare"] == "4550.00"
        assert _only_cell(result)["consolidated_fare"] == "4550.00"

    def test_stage0_prevents_multiple_votes_for_one_source(self):
        # Naive pooling of [4000, 4200, 5000] would give 4200, not 4550.
        result = _run(
            _base_row(observation_id="OBS1", source="Goibibo", total_fare="4000"),
            _base_row(observation_id="OBS2", source="Goibibo", total_fare="4200"),
            _base_row(observation_id="OBS3", source="Cleartrip", total_fare="5000"),
        )
        assert _only_cell(result)["consolidated_fare"] != "4200.00"
        assert _only_cell(result)["consolidated_fare"] == "4550.00"

    def test_stage0_helper_returns_one_value_per_source(self):
        result = _run(
            _base_row(observation_id="OBS1", source="Goibibo", total_fare="4000"),
            _base_row(observation_id="OBS2", source="Goibibo", total_fare="4200"),
        )
        flight_cell = list(result.flight_cell_model.values())[0]
        values = E.stage0_within_source_values(flight_cell.observations)
        assert list(values.keys()) == ["Goibibo"]
        assert values["Goibibo"] == Decimal("4100.00")


class TestStage1CrossSourceWithinFlight:
    def test_cross_source_median_within_flight(self):
        result = _run(
            _base_row(observation_id="OBS1", source="AirlineSite", total_fare="5300"),
            _base_row(observation_id="OBS2", source="Cleartrip", total_fare="5500"),
        )
        assert result.flight_cells.iloc[0]["flight_representative_fare"] == "5400.00"

    def test_stage1_returns_none_without_prices(self):
        assert E.stage1_flight_representative_fare({}) is None

    def test_sources_only_compared_within_the_same_flight(self):
        result = _run(
            _base_row(
                observation_id="OBS1",
                source="AirlineSite",
                flight_number="6E-1111",
                total_fare="5000",
            ),
            _base_row(
                observation_id="OBS2",
                source="Cleartrip",
                flight_number="6E-2222",
                total_fare="9000",
            ),
        )
        assert len(result.flight_cells) == 2
        for _, row in result.flight_cells.iterrows():
            assert int(row["flight_source_count"]) == 1
            assert row["flight_source_spread"] == "0.00"


class TestStage2AcrossFlights:
    def test_median_across_flight_representative_fares(self):
        result = _run(
            _base_row(observation_id="OBS1", flight_number="6E-1", total_fare="5000"),
            _base_row(observation_id="OBS2", flight_number="6E-2", total_fare="5200"),
            _base_row(observation_id="OBS3", flight_number="6E-3", total_fare="6000"),
        )
        assert _only_cell(result)["consolidated_fare"] == "5200.00"

    def test_stage2_uses_midpoint_for_even_flight_counts(self):
        result = _run(
            _base_row(observation_id="OBS1", flight_number="6E-1", total_fare="5000"),
            _base_row(observation_id="OBS2", flight_number="6E-2", total_fare="5200"),
            _base_row(observation_id="OBS3", flight_number="6E-3", total_fare="5600"),
            _base_row(observation_id="OBS4", flight_number="6E-4", total_fare="6000"),
        )
        assert _only_cell(result)["consolidated_fare"] == "5400.00"

    def test_consolidated_fare_is_observed_value_flag(self):
        observed = _run(
            _base_row(observation_id="OBS1", flight_number="6E-1", total_fare="5000"),
            _base_row(observation_id="OBS2", flight_number="6E-2", total_fare="5200"),
            _base_row(observation_id="OBS3", flight_number="6E-3", total_fare="6000"),
        )
        assert _only_cell(observed)["consolidated_fare_is_observed_value"] == "True"

        derived = _run(
            _base_row(observation_id="OBS1", flight_number="6E-1", total_fare="5300"),
            _base_row(observation_id="OBS2", flight_number="6E-2", total_fare="5550"),
        )
        row = _only_cell(derived)
        assert row["consolidated_fare"] == "5425.00"
        assert row["consolidated_fare_is_observed_value"] == "False"


# ---------------------------------------------------------------------------
# 4. Flight-first hierarchy
# ---------------------------------------------------------------------------


class TestFlightFirstHierarchy:
    def _asymmetric_coverage_rows(self):
        return [
            _base_row(
                observation_id="OBS1",
                source="AirlineSite",
                flight_number="6E-1",
                departure_time="06:00",
                total_fare="5000",
            ),
            _base_row(
                observation_id="OBS2",
                source="AirlineSite",
                flight_number="6E-2",
                departure_time="07:00",
                total_fare="5100",
            ),
            _base_row(
                observation_id="OBS3",
                source="AirlineSite",
                flight_number="6E-3",
                departure_time="08:00",
                total_fare="5200",
            ),
            _base_row(
                observation_id="OBS4",
                source="AirlineSite",
                flight_number="6E-4",
                departure_time="09:00",
                total_fare="5300",
            ),
            _base_row(
                observation_id="OBS5",
                source="MMT",
                flight_number="6E-1",
                departure_time="06:00",
                total_fare="6000",
            ),
        ]

    def test_no_accidental_source_weighting(self):
        result = _run(*self._asymmetric_coverage_rows())
        row = _only_cell(result)
        # Flight reps: 5500 (both sources), 5100, 5200, 5300 -> midpoint(5200,5300)
        assert row["consolidated_fare"] == "5250.00"
        # A source-first estimator would have produced 5575.
        assert row["alt_source_first_fare"] == "5575.00"
        assert row["consolidated_fare"] != row["alt_source_first_fare"]

    def test_no_flight_double_counting(self):
        result = _run(*self._asymmetric_coverage_rows())
        row = _only_cell(result)
        assert int(row["flight_instance_count"]) == 4
        assert int(row["priced_flight_instance_count"]) == 4
        assert int(row["observation_count"]) == 5
        # 5 observations but only 4 values entered Stage 2.
        assert len(row["flight_representative_fares"].split(";")) == 4

    def test_second_source_on_one_flight_moves_only_that_flight(self):
        without = _run(*self._asymmetric_coverage_rows()[:4])
        with_extra = _run(*self._asymmetric_coverage_rows())
        assert _only_cell(without)["consolidated_fare"] == "5150.00"
        assert _only_cell(with_extra)["consolidated_fare"] == "5250.00"

    def test_residual_coverage_asymmetry_is_visible(self):
        # A uniquely exposed flight still determines its own representative
        # value; this is disclosed, not hidden.
        result = _run(*self._asymmetric_coverage_rows())
        solo = result.flight_cells[result.flight_cells["flight_number"] == "6E-4"].iloc[0]
        assert int(solo["flight_source_count"]) == 1
        assert solo["flight_sources"] == "AirlineSite"
        assert solo["flight_representative_fare"] == "5300.00"


# ---------------------------------------------------------------------------
# 5. Option B diagnostic
# ---------------------------------------------------------------------------


class TestOptionBDiagnostic:
    def test_alt_source_first_fare_is_emitted(self):
        result = _run(
            _base_row(observation_id="OBS1", source="AirlineSite", flight_number="6E-1", total_fare="5000"),
            _base_row(observation_id="OBS2", source="AirlineSite", flight_number="6E-2", total_fare="5100"),
            _base_row(observation_id="OBS3", source="MMT", flight_number="6E-1", total_fare="6000"),
        )
        assert _only_cell(result)["alt_source_first_fare"] != ""

    def test_alt_source_first_fare_never_influences_consolidated_fare(self):
        rows = [
            _base_row(observation_id="OBS1", source="AirlineSite", flight_number="6E-1", total_fare="5000"),
            _base_row(observation_id="OBS2", source="AirlineSite", flight_number="6E-2", total_fare="5100"),
            _base_row(observation_id="OBS3", source="MMT", flight_number="6E-1", total_fare="6000"),
        ]
        baseline = _only_cell(_run(*rows))["consolidated_fare"]

        original = E.alt_source_first_fare
        try:
            E.alt_source_first_fare = lambda observations: (
                Decimal("999999"),
                {"TAMPERED": Decimal("999999")},
            )
            tampered_row = _only_cell(_run(*rows))
        finally:
            E.alt_source_first_fare = original

        assert tampered_row["alt_source_first_fare"] == "999999.00"
        assert tampered_row["consolidated_fare"] == baseline

    def test_consolidated_fare_survives_diagnostic_removal(self):
        rows = [
            _base_row(observation_id="OBS1", source="AirlineSite", flight_number="6E-1", total_fare="5000"),
            _base_row(observation_id="OBS2", source="MMT", flight_number="6E-1", total_fare="6000"),
        ]
        result = _run(*rows)
        cells = list(result.cell_model.values())
        assert E.stage2_consolidated_fare(cells[0].flight_cells) == Decimal("5500.00")


# ---------------------------------------------------------------------------
# 6. Sources, coverage, exclusions
# ---------------------------------------------------------------------------


class TestSourceCoverage:
    def test_single_source_is_labelled(self):
        result = _run(_base_row(observation_id="OBS1"))
        row = _only_cell(result)
        assert row["source_coverage"] == R.SOURCE_COVERAGE_SINGLE
        assert row["consolidated_fare"] == "5400.00"
        assert int(row["participating_source_count"]) == 1

    def test_partial_coverage_is_labelled(self):
        result = _run(
            _base_row(observation_id="OBS1", source="AirlineSite"),
            _base_row(observation_id="OBS2", source="MMT", total_fare="5600"),
        )
        row = _only_cell(result)
        assert row["source_coverage"] == R.SOURCE_COVERAGE_PARTIAL
        assert row["missing_sources"] == "Cleartrip;Goibibo"

    def test_full_coverage_is_labelled(self):
        result = _run(
            *[
                _base_row(observation_id="OBS%d" % index, source=source, total_fare="5400")
                for index, source in enumerate(R.EXPECTED_SOURCES, start=1)
            ]
        )
        row = _only_cell(result)
        assert row["source_coverage"] == R.SOURCE_COVERAGE_FULL
        assert row["missing_sources"] == ""
        assert row["source_coverage_ratio"] == "1.0000"

    def test_missing_sources_are_never_imputed_or_zero(self):
        result = _run(_base_row(observation_id="OBS1"))
        row = _only_cell(result)
        assert int(row["participating_observation_count"]) == 1
        assert row["consolidated_fare"] == "5400.00"
        assert "0.00" not in row["flight_representative_fares"].split(";")

    def test_missing_source_observation_is_excluded_but_retained(self):
        result = _run(
            _base_row(observation_id="OBS1"),
            _base_row(observation_id="OBS00779", source="", total_fare="5600"),
        )
        mapped = _map_row(result, "OBS00779")
        assert mapped["participation_status"] == R.PARTICIPATION_EXCLUDED_MISSING_SOURCE
        assert mapped["consolidation_cell_id"] == ""
        assert _only_cell(result)["consolidated_fare"] == "5400.00"

    def test_missing_timestamp_observation_is_excluded_but_retained(self):
        result = _run(
            _base_row(observation_id="OBS1"),
            _base_row(observation_id="OBS00781", collection_timestamp=""),
        )
        mapped = _map_row(result, "OBS00781")
        assert mapped["participation_status"] == R.PARTICIPATION_EXCLUDED_NO_ROUND
        assert mapped["round_alignment"] == R.ROUND_ALIGNMENT_UNRESOLVED
        assert mapped["collection_round_id"].startswith(R.UNRESOLVED_ROUND_ID_PREFIX)
        assert mapped["consolidation_cell_id"] == ""
        assert len(result.consolidated) == 1

    def test_missing_identity_observation_is_excluded_but_retained(self):
        result = _run(
            _base_row(observation_id="OBS1"),
            _base_row(observation_id="OBS00780", origin="", destination=""),
        )
        mapped = _map_row(result, "OBS00780")
        assert mapped["participation_status"] == R.PARTICIPATION_EXCLUDED_MISSING_IDENTITY

    def test_unaligned_capture_forms_its_own_round(self):
        result = _run(
            _base_row(observation_id="OBS1", collection_timestamp="2026-09-05 09:00"),
            _base_row(observation_id="OBS2", collection_timestamp="2026-09-05 10:32"),
        )
        assert len(result.consolidated) == 2
        alignments = sorted(result.consolidated["round_alignment"])
        assert alignments == [R.ROUND_ALIGNMENT_ANCHORED, R.ROUND_ALIGNMENT_UNALIGNED]

    def test_near_anchor_captures_share_a_round(self):
        result = _run(
            _base_row(observation_id="OBS1", source="AirlineSite", collection_timestamp="2026-09-05 08:45"),
            _base_row(
                observation_id="OBS2",
                source="Cleartrip",
                total_fare="5600",
                collection_timestamp="2026-09-05 09:20",
            ),
        )
        row = _only_cell(result)
        assert int(row["participating_source_count"]) == 2
        assert row["round_time_spread_minutes"] == "35"


# ---------------------------------------------------------------------------
# 7. Prices: sold out, missing, high
# ---------------------------------------------------------------------------


class TestPriceHandling:
    def test_sold_out_is_excluded_from_median_but_counted(self):
        result = _run(
            _base_row(observation_id="OBS1", source="AirlineSite", total_fare="5400"),
            _base_row(
                observation_id="OBS00778",
                source="Cleartrip",
                total_fare="",
                availability_status="Sold Out",
            ),
        )
        row = _only_cell(result)
        assert row["consolidated_fare"] == "5400.00"
        assert int(row["sold_out_observation_count"]) == 1
        assert int(row["observation_count"]) == 2
        assert int(row["participating_observation_count"]) == 1
        assert (
            _map_row(result, "OBS00778")["participation_status"]
            == R.PARTICIPATION_EXCLUDED_SOLD_OUT
        )

    def test_all_sold_out_cell_has_no_fare(self):
        result = _run(
            _base_row(
                observation_id="OBS1",
                source="AirlineSite",
                total_fare="",
                availability_status="Sold Out",
            ),
            _base_row(
                observation_id="OBS2",
                source="Cleartrip",
                total_fare="",
                availability_status="Sold Out",
            ),
        )
        row = _only_cell(result)
        assert row["consolidated_fare"] == ""
        assert row["consolidation_status"] == R.STATUS_NO_PRICE_ALL_SOLD_OUT
        assert row["source_coverage"] == R.SOURCE_COVERAGE_NONE
        assert row["consolidated_fare_is_observed_value"] == ""
        assert int(row["sold_out_observation_count"]) == 2

    def test_sold_out_row_is_retained_in_lineage(self):
        result = _run(
            _base_row(
                observation_id="OBS1",
                total_fare="",
                availability_status="Sold Out",
            )
        )
        mapped = _map_row(result, "OBS1")
        assert mapped["flight_cell_id"] != ""
        assert mapped["consolidation_cell_id"] != ""

    def test_missing_total_fare_is_excluded_and_counted(self):
        result = _run(
            _base_row(observation_id="OBS1", source="AirlineSite", total_fare=""),
            _base_row(observation_id="OBS2", source="Cleartrip", total_fare="5500"),
        )
        row = _only_cell(result)
        assert row["consolidated_fare"] == "5500.00"
        assert int(row["missing_price_observation_count"]) == 1
        assert row["source_coverage"] == R.SOURCE_COVERAGE_SINGLE
        assert (
            _map_row(result, "OBS1")["participation_status"]
            == R.PARTICIPATION_EXCLUDED_MISSING_PRICE
        )

    def test_missing_price_never_becomes_zero(self):
        result = _run(
            _base_row(observation_id="OBS1", source="AirlineSite", total_fare=""),
            _base_row(observation_id="OBS2", source="Cleartrip", total_fare="5500"),
        )
        assert _only_cell(result)["min_participating_fare"] == "5500.00"

    def test_high_price_is_retained_and_participates(self):
        result = _run(
            _base_row(observation_id="OBS1", source="MMT", total_fare="5000"),
            _base_row(observation_id="OBS00776", source="Goibibo", total_fare="99000"),
        )
        row = _only_cell(result)
        assert row["consolidated_fare"] == "52000.00"
        assert row["max_participating_fare"] == "99000.00"
        assert (
            _map_row(result, "OBS00776")["participation_status"]
            == R.PARTICIPATION_PARTICIPATED
        )

    def test_no_anomaly_flag_columns_exist(self):
        result = _run(_base_row(observation_id="OBS1"))
        for column in result.consolidated.columns:
            assert "anomaly" not in column.lower()
            assert "outlier" not in column.lower()

    def test_raw_fare_formatting_is_preserved_in_the_map(self):
        result = _run(_base_row(observation_id="OBS1", total_fare="5400"))
        assert _map_row(result, "OBS1")["total_fare"] == "5400"


# ---------------------------------------------------------------------------
# 8. Dispersion
# ---------------------------------------------------------------------------


class TestDispersion:
    def test_flight_source_spread_is_measured(self):
        result = _run(
            _base_row(observation_id="OBS1", source="AirlineSite", total_fare="5000"),
            _base_row(observation_id="OBS2", source="Cleartrip", total_fare="5600"),
        )
        flight = result.flight_cells.iloc[0]
        assert flight["flight_source_spread"] == "600.00"
        assert flight["flight_min_fare"] == "5000.00"
        assert flight["flight_max_fare"] == "5600.00"

    def test_identical_prices_produce_zero_spread(self):
        result = _run(
            _base_row(observation_id="OBS1", source="AirlineSite", total_fare="4500"),
            _base_row(observation_id="OBS2", source="MMT", total_fare="4500"),
        )
        row = _only_cell(result)
        assert result.flight_cells.iloc[0]["flight_source_spread"] == "0.00"
        assert row["consolidated_fare"] == "4500.00"
        assert row["consolidated_fare_is_observed_value"] == "True"

    def test_dispersion_never_drops_observations(self):
        result = _run(
            _base_row(observation_id="OBS1", source="AirlineSite", total_fare="5000"),
            _base_row(observation_id="OBS2", source="Cleartrip", total_fare="99000"),
        )
        row = _only_cell(result)
        assert int(row["participating_observation_count"]) == 2
        assert row["consolidated_fare"] == "52000.00"

    def test_cross_flight_spread_is_separate_from_source_spread(self):
        result = _run(
            _base_row(observation_id="OBS1", flight_number="6E-1", total_fare="5000"),
            _base_row(observation_id="OBS2", flight_number="6E-2", total_fare="7000"),
        )
        row = _only_cell(result)
        assert row["cross_flight_spread"] == "2000.00"
        assert row["max_flight_source_spread"] == "0.00"


# ---------------------------------------------------------------------------
# 9. Cell separation rules
# ---------------------------------------------------------------------------


class TestCellSeparation:
    def test_route_direction_is_preserved(self):
        result = _run(
            _base_row(observation_id="OBS1", origin="DEL", destination="BOM"),
            _base_row(observation_id="OBS2", origin="BOM", destination="DEL"),
        )
        assert len(result.consolidated) == 2
        pairs = sorted(
            (row["origin"], row["destination"])
            for _, row in result.consolidated.iterrows()
        )
        assert pairs == [("BOM", "DEL"), ("DEL", "BOM")]

    def test_fare_classes_are_never_combined(self):
        result = _run(
            _base_row(observation_id="OBS1", fare_class="Economy Saver"),
            _base_row(observation_id="OBS2", fare_class="Economy Flexi"),
        )
        assert len(result.consolidated) == 2

    def test_advance_purchase_windows_are_never_combined(self):
        result = _run(
            _base_row(observation_id="OBS1", advance_purchase_window="T15(12-18)"),
            _base_row(observation_id="OBS2", advance_purchase_window="T30(25-35)"),
        )
        assert len(result.consolidated) == 2

    def test_travel_dates_are_never_combined(self):
        result = _run(
            _base_row(observation_id="OBS1", travel_date="2026-09-20"),
            _base_row(observation_id="OBS2", travel_date="2026-09-21"),
        )
        assert len(result.consolidated) == 2

    def test_equivalent_departure_time_formats_share_a_flight_cell(self):
        result = _run(
            _base_row(observation_id="OBS1", source="AirlineSite", departure_time="08:10"),
            _base_row(
                observation_id="OBS2",
                source="Cleartrip",
                departure_time="8:10",
                total_fare="5600",
            ),
        )
        assert len(result.flight_cells) == 1
        assert result.flight_cells.iloc[0]["flight_representative_fare"] == "5500.00"

    def test_different_carriers_are_different_flight_cells(self):
        result = _run(
            _base_row(observation_id="OBS1", carrier="6E"),
            _base_row(observation_id="OBS2", carrier="AI"),
        )
        assert len(result.consolidated) == 1
        assert len(result.flight_cells) == 2

    def test_source_is_not_part_of_the_cell_key(self):
        result = _run(
            _base_row(observation_id="OBS1", source="AirlineSite"),
            _base_row(observation_id="OBS2", source="MMT"),
        )
        assert len(result.consolidated) == 1


# ---------------------------------------------------------------------------
# 10. Auditability and determinism
# ---------------------------------------------------------------------------


class TestAuditability:
    def test_every_observation_appears_exactly_once(self):
        rows = [_base_row(observation_id="OBS%03d" % index) for index in range(1, 11)]
        result = _run(*rows)
        assert len(result.observation_map) == 10
        assert result.observation_map["observation_id"].nunique() == 10

    def test_every_observation_has_a_participation_status(self):
        result = _fixture_result()
        statuses = set(result.observation_map["participation_status"])
        assert "" not in statuses
        known = {
            R.PARTICIPATION_PARTICIPATED,
            R.PARTICIPATION_EXCLUDED_SOLD_OUT,
            R.PARTICIPATION_EXCLUDED_MISSING_PRICE,
            R.PARTICIPATION_EXCLUDED_NO_ROUND,
            R.PARTICIPATION_EXCLUDED_MISSING_SOURCE,
            R.PARTICIPATION_EXCLUDED_MISSING_IDENTITY,
        }
        assert statuses.issubset(known)

    def test_no_observation_is_physically_deleted(self):
        df = _fixture_df()
        result = E.run_consolidation(df)
        assert len(result.observation_map) == len(df)
        assert set(result.observation_map["observation_id"]) == set(df["observation_id"])

    def test_lineage_links_observation_to_flight_and_cell(self):
        result = _run(
            _base_row(observation_id="OBS1", source="AirlineSite", total_fare="5000"),
            _base_row(observation_id="OBS2", source="Cleartrip", total_fare="5600"),
        )
        mapped = _map_row(result, "OBS1")
        assert mapped["flight_cell_id"] in set(result.flight_cells["flight_cell_id"])
        assert mapped["consolidation_cell_id"] in set(
            result.consolidated["consolidation_cell_id"]
        )
        assert mapped["flight_representative_fare"] == "5300.00"
        assert mapped["consolidated_fare"] == "5300.00"

    def test_contributing_observation_ids_are_recorded(self):
        result = _run(
            _base_row(observation_id="OBS2", source="Cleartrip", total_fare="5600"),
            _base_row(observation_id="OBS1", source="AirlineSite", total_fare="5000"),
        )
        assert _only_cell(result)["contributing_observation_ids"] == "OBS1;OBS2"

    def test_output_schemas_are_fixed(self):
        result = _run(_base_row(observation_id="OBS1"))
        assert tuple(result.consolidated.columns) == E.CONSOLIDATED_COLUMNS
        assert tuple(result.flight_cells.columns) == E.FLIGHT_CELL_COLUMNS
        assert tuple(result.observation_map.columns) == E.OBSERVATION_MAP_COLUMNS


class TestDeterminism:
    def test_deterministic_rerun(self):
        df = _fixture_df()
        first = E.run_consolidation(df)
        second = E.run_consolidation(df)
        assert first.consolidated.to_csv(index=False) == second.consolidated.to_csv(
            index=False
        )
        assert first.flight_cells.to_csv(index=False) == second.flight_cells.to_csv(
            index=False
        )
        assert first.observation_map.to_csv(
            index=False
        ) == second.observation_map.to_csv(index=False)

    def test_shuffled_input_equivalence(self):
        df = _fixture_df()
        shuffled = df.sample(frac=1, random_state=20260910).reset_index(drop=True)
        baseline = E.run_consolidation(df)
        reordered = E.run_consolidation(shuffled)
        assert baseline.consolidated.to_csv(
            index=False
        ) == reordered.consolidated.to_csv(index=False)
        assert baseline.flight_cells.to_csv(
            index=False
        ) == reordered.flight_cells.to_csv(index=False)
        assert baseline.observation_map.to_csv(
            index=False
        ) == reordered.observation_map.to_csv(index=False)

    def test_reversed_input_equivalence(self):
        df = _fixture_df()
        reversed_df = df.iloc[::-1].reset_index(drop=True)
        assert E.run_consolidation(df).consolidated.to_csv(index=False) == (
            E.run_consolidation(reversed_df).consolidated.to_csv(index=False)
        )

    def test_outputs_are_sorted_deterministically(self):
        result = _fixture_result()
        assert list(result.consolidated["consolidation_cell_id"]) == sorted(
            result.consolidated["consolidation_cell_id"]
        )
        assert list(result.flight_cells["flight_cell_id"]) == sorted(
            result.flight_cells["flight_cell_id"]
        )
        assert list(result.observation_map["observation_id"]) == sorted(
            result.observation_map["observation_id"]
        )


# ---------------------------------------------------------------------------
# 11. Fixture-driven end-to-end scenarios
# ---------------------------------------------------------------------------


class TestSyntheticFixture:
    def test_fixture_loads(self):
        df = _fixture_df()
        assert len(df) == 22
        assert "observation_id" in df.columns

    def test_fixture_asymmetric_coverage_cell(self):
        row = _cell_by_travel_date(_fixture_result(), "2026-10-01", origin="DEL")
        assert row["consolidated_fare"] == "5250.00"
        assert row["alt_source_first_fare"] == "5575.00"
        assert int(row["flight_instance_count"]) == 4

    def test_fixture_stage0_cell(self):
        row = _cell_by_travel_date(_fixture_result(), "2026-10-02")
        assert row["consolidated_fare"] == "4550.00"
        assert int(row["observation_count"]) == 3
        assert int(row["participating_source_count"]) == 2

    def test_fixture_single_source_cell(self):
        row = _cell_by_travel_date(_fixture_result(), "2026-10-03")
        assert row["source_coverage"] == R.SOURCE_COVERAGE_SINGLE
        assert row["consolidated_fare"] == "7000.00"

    def test_fixture_all_sold_out_cell(self):
        row = _cell_by_travel_date(_fixture_result(), "2026-10-04")
        assert row["consolidation_status"] == R.STATUS_NO_PRICE_ALL_SOLD_OUT
        assert row["consolidated_fare"] == ""

    def test_fixture_missing_price_cell(self):
        row = _cell_by_travel_date(_fixture_result(), "2026-10-05")
        assert row["consolidated_fare"] == "5500.00"
        assert int(row["missing_price_observation_count"]) == 1

    def test_fixture_boundary_rows_split_rounds(self):
        result = _fixture_result()
        frame = result.consolidated[result.consolidated["travel_date"] == "2026-10-07"]
        assert len(frame) == 2
        assert sorted(frame["round_alignment"]) == [
            R.ROUND_ALIGNMENT_ANCHORED,
            R.ROUND_ALIGNMENT_UNALIGNED,
        ]

    def test_fixture_route_direction_not_merged(self):
        result = _fixture_result()
        frame = result.consolidated[result.consolidated["travel_date"] == "2026-10-01"]
        assert len(frame) == 2
        assert sorted(frame["origin"]) == ["BOM", "DEL"]

    def test_fixture_excluded_observations(self):
        result = _fixture_result()
        assert (
            _map_row(result, "SYN014")["participation_status"]
            == R.PARTICIPATION_EXCLUDED_MISSING_SOURCE
        )
        assert (
            _map_row(result, "SYN015")["participation_status"]
            == R.PARTICIPATION_EXCLUDED_NO_ROUND
        )

    def test_fixture_high_price_cell(self):
        row = _cell_by_travel_date(_fixture_result(), "2026-10-08")
        assert row["consolidated_fare"] == "52000.00"
        assert row["max_participating_fare"] == "99000.00"


# ---------------------------------------------------------------------------
# 12. Phase 6 regression — nothing upstream may change
# ---------------------------------------------------------------------------


class TestPhase6Regression:
    def test_phase6_outputs_are_byte_identical(self):
        for path, expected in sorted(PHASE6_BASELINE_SHA256.items()):
            if not os.path.exists(path):
                continue
            assert _sha256(path) == expected, "Phase 6 output changed: %s" % path

    def test_phase6_canonical_row_count_unchanged(self):
        if not os.path.exists(CANONICAL_CSV):
            return
        df = E.read_canonical_csv(CANONICAL_CSV)
        assert len(df) == 778

    def test_phase6_audited_row_count_unchanged(self):
        if not os.path.exists(DEDUPLICATED_CSV):
            return
        df = E.read_canonical_csv(DEDUPLICATED_CSV)
        assert len(df) == 783

    def test_phase7_does_not_reuse_phase6_tolerance(self):
        source_path = os.path.join(REPO_ROOT, "src", "consolidation", "rules.py")
        with open(source_path, "r", encoding="utf-8") as handle:
            text = handle.read()
        assert "import TIME_TOLERANCE_MINUTES" not in text
        assert "TIME_TOLERANCE_MINUTES," not in text

    def test_phase7_reuses_phase6_normalizers(self):
        from src.deduplication import rules as dedup_rules

        assert R.normalize_departure_time is dedup_rules.normalize_departure_time
        assert R.normalize_total_fare is dedup_rules.normalize_total_fare

    def test_real_canonical_dataset_consolidates(self):
        if not os.path.exists(CANONICAL_CSV):
            return
        df = E.read_canonical_csv(CANONICAL_CSV)
        result = E.run_consolidation(df)
        assert len(result.observation_map) == len(df)
        assert len(result.consolidated) > 0
        assert set(result.observation_map["observation_id"]) == set(df["observation_id"])

    def test_phase7_does_not_implement_later_phases(self):
        module_path = os.path.join(
            REPO_ROOT, "src", "consolidation", "consolidation_engine.py"
        )
        with open(module_path, "r", encoding="utf-8") as handle:
            text = handle.read().lower()
        for forbidden in ("def normalize_index", "def detect_anomal", "def compute_index"):
            assert forbidden not in text
