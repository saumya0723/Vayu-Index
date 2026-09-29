"""
tests/test_deduplication.py
=================================
Test suite for Phase 6 deduplication (src/deduplication).

Uses two kinds of fixtures:
  - REAL rows from outputs/validated_airfare_observations.csv, specifically
    the deliberately-engineered edge-case block (OBS00765-OBS00783), cross-
    checked against data/synthetic/edge_case_log.csv ground truth.
  - HAND-BUILT rows for scenarios not present (or not cleanly isolated) in
    the real dataset, e.g. the Flight-A/Flight-B counterexample from the
    Phase 6 methodology revision, and the defensive missing-timestamp path.
"""

import os
import sys
import pandas as pd
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from src.deduplication import (  # noqa: E402
    run_deduplication,
    build_canonical_view,
    build_duplicate_audit_report,
    build_row_identity,
    group_and_mark,
    capture_signature_agreement,
    group_capture_signature_agreement,
    AUDIT_REPORT_COLUMNS,
    rules as R,
)

VALIDATED_CSV = os.path.join("outputs", "validated_airfare_observations.csv")


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def validated_df():
    df = pd.read_csv(VALIDATED_CSV, dtype=str, keep_default_na=True)
    df["is_valid"] = df["is_valid"].map({"True": True, "False": False})
    return df


@pytest.fixture(scope="module")
def deduped_df(validated_df):
    return run_deduplication(validated_df)


@pytest.fixture(scope="module")
def canonical_df(deduped_df):
    return build_canonical_view(deduped_df)


def _row(obs_id, deduped_df):
    match = deduped_df[deduped_df["observation_id"] == obs_id]
    assert len(match) == 1, f"Expected exactly one row for {obs_id}, found {len(match)}"
    return match.iloc[0]


def _base_row(**overrides):
    """A minimal, fully-valid-shaped row dict for hand-built test cases."""
    row = {
        "observation_id": "TEST0001",
        "capture_signature": "abc123",
        "economic_signature": "econ123",
        "origin": "DEL",
        "destination": "BOM",
        "carrier": "6E",
        "flight_number": "6E-2341",
        "travel_date": "2026-09-20",
        "departure_time": "08:10",
        "collection_timestamp": "2026-09-05 10:00",
        "advance_purchase_days": "15",
        "advance_purchase_window": "T15(12-18)",
        "fare_class": "Economy Saver",
        "base_fare": "4200",
        "taxes": "800",
        "fees": "400",
        "total_fare": "5400",
        "source": "AirlineSite",
        "availability_status": "Available",
        "is_valid": True,
        "validation_status": "VALID",
        "validation_reason": "",
        "validation_errors": "",
    }
    row.update(overrides)
    return row


def _run(*rows):
    df = pd.DataFrame(rows)
    return run_deduplication(df)


# ── Exact technical duplicate (real fixture: OBS00769/770) ─────────────────────

class TestExactTechnicalDuplicate:
    def test_obs770_marked_duplicate_of_obs769(self, deduped_df):
        r769 = _row("OBS00769", deduped_df)
        r770 = _row("OBS00770", deduped_df)
        assert r769["is_duplicate"] == False  # noqa: E712
        assert r769["retained"] == True  # noqa: E712
        assert r769["duplicate_reason"] == R.REASON_RETAINED_CANONICAL_OF_DUPLICATE_GROUP
        assert r770["is_duplicate"] == True  # noqa: E712
        assert r770["duplicate_of"] == "OBS00769"
        assert r770["retained"] == False  # noqa: E712
        assert r770["duplicate_reason"] == R.REASON_TECHNICAL_DUPLICATE

    def test_same_duplicate_group_id(self, deduped_df):
        r769 = _row("OBS00769", deduped_df)
        r770 = _row("OBS00770", deduped_df)
        assert r769["duplicate_group_id"] == r770["duplicate_group_id"]


# ── Genuine repricing (real fixture: OBS00771) ──────────────────────────────────

class TestGenuineRepricing:
    def test_repriced_observation_not_marked_duplicate(self, deduped_df):
        r771 = _row("OBS00771", deduped_df)
        assert r771["is_duplicate"] == False  # noqa: E712
        assert r771["retained"] == True  # noqa: E712
        assert r771["duplicate_reason"] != R.REASON_TECHNICAL_DUPLICATE

    def test_hand_built_same_product_different_price_never_duplicate(self):
        r1 = _base_row(observation_id="A1", total_fare="5400", collection_timestamp="2026-09-05 10:00")
        r2 = _base_row(observation_id="A2", total_fare="5800", collection_timestamp="2026-09-05 10:05")
        out = _run(r1, r2)
        assert not out[out["observation_id"] == "A2"].iloc[0]["is_duplicate"]
        assert not out[out["observation_id"] == "A1"].iloc[0]["is_duplicate"]


# ── Different flight / carrier / departure time (methodology counterexample) ───

class TestProductInstanceDifferences:
    def test_different_flight_number_not_duplicate(self):
        """The exact counterexample from the Phase 6 methodology revision:
        same economic identity, source, price, and close timestamp, but a
        different flight_number — must NOT be collapsed."""
        r1 = _base_row(observation_id="B1", flight_number="6E-2341",
                        collection_timestamp="2026-09-05 10:00")
        r2 = _base_row(observation_id="B2", flight_number="6E-9999",
                        collection_timestamp="2026-09-05 10:01")
        out = _run(r1, r2)
        assert not out[out["observation_id"] == "B2"].iloc[0]["is_duplicate"]
        assert out[out["observation_id"] == "B1"].iloc[0]["duplicate_reason"] == R.REASON_RETAINED_UNIQUE
        assert out[out["observation_id"] == "B2"].iloc[0]["duplicate_reason"] == R.REASON_RETAINED_UNIQUE

    def test_different_carrier_not_duplicate(self):
        r1 = _base_row(observation_id="C1", carrier="6E", flight_number="6E-2341")
        r2 = _base_row(observation_id="C2", carrier="AI", flight_number="AI-865",
                        collection_timestamp="2026-09-05 10:02")
        out = _run(r1, r2)
        assert not out[out["observation_id"] == "C2"].iloc[0]["is_duplicate"]

    def test_different_departure_time_not_duplicate(self):
        r1 = _base_row(observation_id="D1", departure_time="08:10")
        r2 = _base_row(observation_id="D2", departure_time="09:30",
                        collection_timestamp="2026-09-05 10:03")
        out = _run(r1, r2)
        assert not out[out["observation_id"] == "D2"].iloc[0]["is_duplicate"]

    def test_equivalent_departure_time_formatting_normalized(self):
        """08:10, 08:10:00, and 08:10:00.000 must be treated as identical
        after normalization, not as artificial differences."""
        r1 = _base_row(observation_id="E1", departure_time="08:10",
                        collection_timestamp="2026-09-05 10:00")
        r2 = _base_row(observation_id="E2", departure_time="08:10:00",
                        collection_timestamp="2026-09-05 10:01")
        r3 = _base_row(observation_id="E3", departure_time="08:10:00.000",
                        collection_timestamp="2026-09-05 10:02")
        out = _run(r1, r2, r3)
        e2 = out[out["observation_id"] == "E2"].iloc[0]
        e3 = out[out["observation_id"] == "E3"].iloc[0]
        assert e2["is_duplicate"] and e2["duplicate_of"] == "E1"
        assert e3["is_duplicate"] and e3["duplicate_of"] == "E1"

    def test_normalize_departure_time_function_directly(self):
        assert R.normalize_departure_time("08:10") == "08:10"
        assert R.normalize_departure_time("08:10:00") == "08:10"
        assert R.normalize_departure_time("08:10:00.000") == "08:10"
        assert R.normalize_departure_time("8:10") == "08:10"
        assert R.normalize_departure_time(None) is None
        assert R.normalize_departure_time("") is None
        assert R.normalize_departure_time("not a time") is None


# ── Different source (real fixture: OBS00772/773, OBS00782/783) ────────────────

class TestDifferentSource:
    def test_obs772_773_different_source_not_duplicate(self, deduped_df):
        r772 = _row("OBS00772", deduped_df)
        r773 = _row("OBS00773", deduped_df)
        assert not r772["is_duplicate"]
        assert not r773["is_duplicate"]

    def test_obs782_783_same_price_close_time_different_source_not_duplicate(self, deduped_df):
        """Same product, same price, 8 minutes apart, different source —
        must remain distinct despite looking duplicate-like."""
        r782 = _row("OBS00782", deduped_df)
        r783 = _row("OBS00783", deduped_df)
        assert not r782["is_duplicate"]
        assert not r783["is_duplicate"]

    def test_missing_source_treated_as_own_category(self):
        r1 = _base_row(observation_id="F1", source="AirlineSite")
        r2 = _base_row(observation_id="F2", source=None, is_valid=False,
                        validation_status="INVALID", validation_errors="MISSING_SOURCE")
        out = _run(r1, r2)
        f2 = out[out["observation_id"] == "F2"].iloc[0]
        assert f2["duplicate_reason"] == R.REASON_SKIPPED_INVALID_BY_PHASE2
        assert f2["retained"] == True  # noqa: E712


# ── Different fare class (real fixture: OBS00774) ───────────────────────────────

class TestDifferentFareClass:
    def test_obs774_different_fare_class_not_duplicate(self, deduped_df):
        r774 = _row("OBS00774", deduped_df)
        assert not r774["is_duplicate"]

    def test_hand_built_different_fare_class(self):
        r1 = _base_row(observation_id="G1", fare_class="Economy Saver")
        r2 = _base_row(observation_id="G2", fare_class="Economy Flexi",
                        collection_timestamp="2026-09-05 10:01")
        out = _run(r1, r2)
        assert not out[out["observation_id"] == "G2"].iloc[0]["is_duplicate"]


# ── Different travel date / advance-purchase window ─────────────────────────────

class TestDifferentEconomicIdentity:
    def test_different_travel_date_not_duplicate(self):
        r1 = _base_row(observation_id="H1", travel_date="2026-09-20")
        r2 = _base_row(observation_id="H2", travel_date="2026-09-21",
                        collection_timestamp="2026-09-05 10:01")
        out = _run(r1, r2)
        assert not out[out["observation_id"] == "H2"].iloc[0]["is_duplicate"]

    def test_different_advance_purchase_window_not_duplicate(self):
        r1 = _base_row(observation_id="I1", advance_purchase_window="T15(12-18)")
        r2 = _base_row(observation_id="I2", advance_purchase_window="T30(25-35)",
                        collection_timestamp="2026-09-05 10:01")
        out = _run(r1, r2)
        assert not out[out["observation_id"] == "I2"].iloc[0]["is_duplicate"]

    def test_different_route_not_duplicate(self):
        r1 = _base_row(observation_id="J1", origin="DEL", destination="BOM")
        r2 = _base_row(observation_id="J2", origin="BLR", destination="HYD",
                        collection_timestamp="2026-09-05 10:01")
        out = _run(r1, r2)
        assert not out[out["observation_id"] == "J2"].iloc[0]["is_duplicate"]


# ── Sold-out handling (real fixture: OBS00778) ──────────────────────────────────

class TestSoldOut:
    def test_obs778_sold_out_retained(self, deduped_df):
        r778 = _row("OBS00778", deduped_df)
        assert r778["is_valid"]
        assert not r778["is_duplicate"]
        assert r778["retained"]

    def test_sold_out_duplicate_pair(self):
        r1 = _base_row(observation_id="K1", availability_status="Sold Out",
                        total_fare=None, base_fare=None, taxes=None, fees=None,
                        validation_status="NON_PRICE_AVAILABILITY",
                        collection_timestamp="2026-09-05 10:00")
        r2 = _base_row(observation_id="K2", availability_status="Sold Out",
                        total_fare=None, base_fare=None, taxes=None, fees=None,
                        validation_status="NON_PRICE_AVAILABILITY",
                        collection_timestamp="2026-09-05 10:05")
        out = _run(r1, r2)
        k2 = out[out["observation_id"] == "K2"].iloc[0]
        assert k2["is_duplicate"]
        assert k2["duplicate_of"] == "K1"
        assert k2["duplicate_reason"] == R.REASON_SOLD_OUT_TECHNICAL_DUPLICATE

    def test_sold_out_never_compared_to_priced_row(self):
        """A sold-out row and a priced row for the exact same product/source
        must never be treated as duplicates of each other."""
        r1 = _base_row(observation_id="L1", availability_status="Sold Out",
                        total_fare=None, base_fare=None, taxes=None, fees=None,
                        validation_status="NON_PRICE_AVAILABILITY",
                        collection_timestamp="2026-09-05 10:00")
        r2 = _base_row(observation_id="L2", availability_status="Available",
                        total_fare="5400", collection_timestamp="2026-09-05 10:01")
        out = _run(r1, r2)
        assert not out[out["observation_id"] == "L1"].iloc[0]["is_duplicate"]
        assert not out[out["observation_id"] == "L2"].iloc[0]["is_duplicate"]


# ── Missing timestamp (real fixture: OBS00781 — already invalid) ───────────────

class TestMissingTimestamp:
    def test_obs781_missing_timestamp_skipped_as_invalid(self, deduped_df):
        r781 = _row("OBS00781", deduped_df)
        assert r781["is_valid"] == False  # noqa: E712
        assert r781["duplicate_reason"] == R.REASON_SKIPPED_INVALID_BY_PHASE2
        assert r781["retained"] == True  # noqa: E712
        assert not r781["is_duplicate"]

    def test_ambiguous_missing_timestamp_defensive_path(self):
        """
        Defensive / future-proofing test: under CURRENT Phase 2 rules a
        missing collection_timestamp always yields is_valid=False, so this
        scenario cannot occur via run_deduplication() on real Phase-2
        output today. This test exercises group_and_mark() DIRECTLY with a
        hand-built is_valid=True row that has a missing timestamp (bypassing
        the Phase 2 gate) to prove the AMBIGUOUS_MISSING_TIMESTAMP code path
        itself works correctly, so it is not untested dead code.
        """
        matching_candidate = _base_row(
            observation_id="M1", collection_timestamp="2026-09-05 10:00"
        )
        missing_ts_row = _base_row(
            observation_id="M2", collection_timestamp=None
        )
        results = group_and_mark([matching_candidate, missing_ts_row])
        assert results["M2"].duplicate_reason == R.REASON_AMBIGUOUS_MISSING_TIMESTAMP
        assert results["M2"].is_duplicate == False  # noqa: E712 -- never auto-merged
        assert results["M2"].retained == True  # noqa: E712

    def test_missing_timestamp_no_candidate_retained_unique(self):
        """Same defensive path, but with no matching candidate present at
        all — must resolve to RETAINED_UNIQUE, not ambiguous."""
        lone_row = _base_row(observation_id="N1", collection_timestamp=None)
        results = group_and_mark([lone_row])
        assert results["N1"].duplicate_reason == R.REASON_RETAINED_UNIQUE


# ── Missing source (real fixture: OBS00779) ─────────────────────────────────────

class TestMissingSource:
    def test_obs779_missing_source_skipped_as_invalid(self, deduped_df):
        r779 = _row("OBS00779", deduped_df)
        assert r779["is_valid"] == False  # noqa: E712
        assert r779["duplicate_reason"] == R.REASON_SKIPPED_INVALID_BY_PHASE2
        assert r779["retained"] == True  # noqa: E712


# ── Missing identity (real fixture: OBS00780) ───────────────────────────────────

class TestMissingIdentity:
    def test_obs780_missing_route_skipped_as_invalid(self, deduped_df):
        r780 = _row("OBS00780", deduped_df)
        assert r780["is_valid"] == False  # noqa: E712
        assert r780["duplicate_reason"] == R.REASON_SKIPPED_INVALID_BY_PHASE2
        assert r780["retained"] == True  # noqa: E712

    def test_valid_row_missing_identity_field_excluded_from_grouping(self):
        """Defensive: an is_valid=True row that is nonetheless missing a
        core identity field (bypassing Phase 2, hand-built) must be
        excluded from grouping, not silently matched to anything."""
        normal_row = _base_row(observation_id="O1")
        missing_carrier_row = _base_row(observation_id="O2", carrier=None)
        results = group_and_mark([normal_row, missing_carrier_row])
        assert results["O2"].duplicate_reason == R.REASON_EXCLUDED_MISSING_IDENTITY
        assert results["O2"].is_duplicate == False  # noqa: E712
        assert results["O2"].retained == True  # noqa: E712


# ── Anomaly preservation (real fixtures: OBS00775, OBS00776) ────────────────────

class TestAnomalyPreservation:
    def test_obs775_anomalous_negative_fare_is_invalid_not_touched_by_dedup(self, deduped_df):
        """OBS00775 (negative base_fare, extreme low price) is caught by
        Phase 2 validation, not Phase 6 — dedup never evaluates it."""
        r775 = _row("OBS00775", deduped_df)
        assert r775["is_valid"] == False  # noqa: E712
        assert r775["duplicate_reason"] == R.REASON_SKIPPED_INVALID_BY_PHASE2

    def test_obs776_statistical_outlier_retained_untouched(self, deduped_df):
        """OBS00776 (₹14,050, a legitimate structural VALID row) must be
        retained normally — a high price is never a reason to drop or
        merge a row in deduplication."""
        r776 = _row("OBS00776", deduped_df)
        assert r776["is_valid"]
        assert not r776["is_duplicate"]
        assert r776["retained"]


# ── Determinism / order-independence ────────────────────────────────────────────

class TestDeterminismAndOrderIndependence:
    def test_deterministic_rerun(self, validated_df):
        out1 = run_deduplication(validated_df)
        out2 = run_deduplication(validated_df)
        cols = ["observation_id", "is_duplicate", "duplicate_of", "duplicate_reason", "retained"]
        pd.testing.assert_frame_equal(
            out1[cols].reset_index(drop=True),
            out2[cols].reset_index(drop=True),
        )

    def test_shuffled_input_produces_identical_grouping(self, validated_df):
        shuffled = validated_df.sample(frac=1, random_state=42).reset_index(drop=True)
        out_original = run_deduplication(validated_df)
        out_shuffled = run_deduplication(shuffled)

        cols = ["observation_id", "is_duplicate", "duplicate_of", "duplicate_reason", "retained"]
        a = out_original[cols].set_index("observation_id").sort_index()
        b = out_shuffled[cols].set_index("observation_id").sort_index()
        pd.testing.assert_frame_equal(a, b)


# ── Raw row preservation ─────────────────────────────────────────────────────────

class TestRawRowPreservation:
    def test_all_783_rows_present_in_output(self, deduped_df, validated_df):
        assert len(deduped_df) == len(validated_df)

    def test_no_raw_columns_dropped(self, deduped_df, validated_df):
        for col in validated_df.columns:
            assert col in deduped_df.columns

    def test_invalid_rows_all_present_and_retained(self, deduped_df, validated_df):
        invalid_ids = set(validated_df[validated_df["is_valid"] == False]["observation_id"])  # noqa: E712
        assert len(invalid_ids) == 4
        for obs_id in invalid_ids:
            r = _row(obs_id, deduped_df)
            assert r["retained"] == True  # noqa: E712
            assert r["duplicate_reason"] == R.REASON_SKIPPED_INVALID_BY_PHASE2


# ── Audit fields ───────────────────────────────────────────────────────────────

class TestAuditFields:
    REQUIRED_COLUMNS = [
        "duplicate_group_id", "is_duplicate", "duplicate_of",
        "duplicate_reason", "retained", "capture_signature_agreement",
    ]

    def test_all_audit_columns_present(self, deduped_df):
        for col in self.REQUIRED_COLUMNS:
            assert col in deduped_df.columns

    def test_every_row_has_a_duplicate_reason(self, deduped_df):
        assert deduped_df["duplicate_reason"].isna().sum() == 0
        assert (deduped_df["duplicate_reason"].str.len() > 0).all()

    def test_duplicate_of_only_set_when_is_duplicate_true(self, deduped_df):
        for _, row in deduped_df.iterrows():
            if row["is_duplicate"]:
                assert pd.notna(row["duplicate_of"])
            else:
                assert pd.isna(row["duplicate_of"])

    def test_capture_signature_agreement_is_a_group_level_value(self, deduped_df):
        """APPROVED: the field describes whether records WITHIN a confirmed
        duplicate group share a capture_signature, so it is recorded on every
        member of that group — the canonical record included — and is empty
        for any row that is not in a confirmed group."""
        in_group_ids = set(
            deduped_df[deduped_df["is_duplicate"] == True]["duplicate_group_id"]  # noqa: E712
        )
        for _, row in deduped_df.iterrows():
            if row["duplicate_group_id"] in in_group_ids:
                assert pd.notna(row["capture_signature_agreement"])
            else:
                assert pd.isna(row["capture_signature_agreement"])

    def test_capture_signature_agreement_matches_across_the_real_group(self, deduped_df):
        r769 = _row("OBS00769", deduped_df)
        r770 = _row("OBS00770", deduped_df)
        assert r769["capture_signature_agreement"] == r770["capture_signature_agreement"]
        # The planted duplicate pair carries DIFFERENT capture_signatures —
        # concrete evidence the field must never be an authoritative key.
        assert bool(r769["capture_signature_agreement"]) is False

    def test_group_capture_signature_agreement_function_directly(self):
        same = [{"capture_signature": "x"}, {"capture_signature": "x"}]
        differ = [{"capture_signature": "x"}, {"capture_signature": "y"}]
        missing = [{"capture_signature": "x"}, {"capture_signature": ""}]
        assert group_capture_signature_agreement(same) is True
        assert group_capture_signature_agreement(differ) is False
        assert group_capture_signature_agreement(missing) is None
        assert group_capture_signature_agreement([{"capture_signature": "x"}]) is None

    def test_agreement_never_changes_the_duplicate_decision(self):
        """Two rows satisfying all five locked conditions are duplicates even
        when their capture_signatures disagree; two rows failing a condition
        are not duplicates even when their signatures agree."""
        dup_a = _base_row(observation_id="AG1", capture_signature="sig-one",
                          collection_timestamp="2026-09-05 10:00")
        dup_b = _base_row(observation_id="AG2", capture_signature="sig-two",
                          collection_timestamp="2026-09-05 10:05")
        out = _run(dup_a, dup_b)
        assert out[out["observation_id"] == "AG2"].iloc[0]["is_duplicate"]
        assert bool(out[out["observation_id"] == "AG2"].iloc[0]["capture_signature_agreement"]) is False

        same_sig_a = _base_row(observation_id="AG3", capture_signature="same",
                               total_fare="5400", collection_timestamp="2026-09-05 10:00")
        same_sig_b = _base_row(observation_id="AG4", capture_signature="same",
                               total_fare="5900", collection_timestamp="2026-09-05 10:05")
        out2 = _run(same_sig_a, same_sig_b)
        assert not out2[out2["observation_id"] == "AG4"].iloc[0]["is_duplicate"]

    def test_capture_signature_agreement_function_directly(self):
        row_a = {"capture_signature": "xyz"}
        row_b = {"capture_signature": "xyz"}
        row_c = {"capture_signature": "different"}
        row_d = {"capture_signature": None}
        assert capture_signature_agreement(row_a, row_b) is True
        assert capture_signature_agreement(row_a, row_c) is False
        assert capture_signature_agreement(row_a, row_d) is None


# ── Canonical record selection ──────────────────────────────────────────────────

class TestCanonicalRecordSelection:
    def test_earliest_timestamp_wins(self):
        r1 = _base_row(observation_id="P1", collection_timestamp="2026-09-05 10:05")
        r2 = _base_row(observation_id="P2", collection_timestamp="2026-09-05 10:00")
        out = _run(r1, r2)
        p1 = out[out["observation_id"] == "P1"].iloc[0]
        p2 = out[out["observation_id"] == "P2"].iloc[0]
        assert not p2["is_duplicate"]
        assert p1["is_duplicate"] and p1["duplicate_of"] == "P2"

    def test_tie_break_lowest_observation_id(self):
        """Exact same timestamp -> lowest observation_id wins."""
        r1 = _base_row(observation_id="Q2", collection_timestamp="2026-09-05 10:00")
        r2 = _base_row(observation_id="Q1", collection_timestamp="2026-09-05 10:00")
        out = _run(r1, r2)
        q1 = out[out["observation_id"] == "Q1"].iloc[0]
        q2 = out[out["observation_id"] == "Q2"].iloc[0]
        assert not q1["is_duplicate"]
        assert q2["is_duplicate"] and q2["duplicate_of"] == "Q1"

    def test_canonical_view_excludes_non_retained(self, canonical_df):
        assert "OBS00770" not in set(canonical_df["observation_id"])
        assert "OBS00769" in set(canonical_df["observation_id"])

    def test_canonical_view_excludes_invalid_rows(self, canonical_df):
        for obs_id in ["OBS00775", "OBS00779", "OBS00780", "OBS00781"]:
            assert obs_id not in set(canonical_df["observation_id"])

    def test_canonical_view_row_count(self, canonical_df, validated_df):
        # 783 total - 4 invalid - 1 technical duplicate = 778
        assert len(canonical_df) == len(validated_df) - 4 - 1


# ── build_row_identity direct unit tests ────────────────────────────────────────

class TestBuildRowIdentity:
    def test_economic_key_excludes_flight_fields(self):
        ident = build_row_identity(_base_row())
        # economic key should be exactly 5 fields (no carrier/flight/dep_time)
        assert len(ident.economic_key) == 5

    def test_product_instance_key_includes_flight_fields(self):
        ident = build_row_identity(_base_row())
        assert len(ident.product_instance_key) == 8

    def test_missing_carrier_flags_missing_identity(self):
        ident = build_row_identity(_base_row(carrier=None))
        assert "carrier" in ident.missing_identity_fields
        assert ident.product_instance_key is None


# ── Anchored-sweep chaining rule (APPROVED) ────────────────────────────────

class TestAnchoredSweep:
    """The approved rule is an anchored sweep, NOT transitive chaining: a
    record joins the open group only if it is within tolerance OF THE ANCHOR.
    Without this, a slow drift of observations each 15 minutes after the last
    would chain into one unbounded group spanning hours."""

    def test_boundary_exactly_15_minutes_is_inclusive(self):
        r1 = _base_row(observation_id="S1", collection_timestamp="2026-09-05 09:00")
        r2 = _base_row(observation_id="S2", collection_timestamp="2026-09-05 09:15")
        out = _run(r1, r2)
        assert out[out["observation_id"] == "S2"].iloc[0]["is_duplicate"]
        assert out[out["observation_id"] == "S2"].iloc[0]["duplicate_of"] == "S1"

    def test_boundary_16_minutes_is_excluded(self):
        r1 = _base_row(observation_id="S3", collection_timestamp="2026-09-05 09:00")
        r2 = _base_row(observation_id="S4", collection_timestamp="2026-09-05 09:16")
        out = _run(r1, r2)
        assert not out[out["observation_id"] == "S4"].iloc[0]["is_duplicate"]

    def test_no_transitive_chaining_across_the_anchor_window(self):
        """09:00 / 09:14 / 09:28 — each is within 15 minutes of its immediate
        predecessor, but the third is 28 minutes from the ANCHOR, so it must
        start a new group rather than chain into the first one."""
        r1 = _base_row(observation_id="S5", collection_timestamp="2026-09-05 09:00")
        r2 = _base_row(observation_id="S6", collection_timestamp="2026-09-05 09:14")
        r3 = _base_row(observation_id="S7", collection_timestamp="2026-09-05 09:28")
        out = _run(r1, r2, r3)
        s5 = out[out["observation_id"] == "S5"].iloc[0]
        s6 = out[out["observation_id"] == "S6"].iloc[0]
        s7 = out[out["observation_id"] == "S7"].iloc[0]
        assert s6["is_duplicate"] and s6["duplicate_of"] == "S5"
        assert not s7["is_duplicate"]
        assert s7["duplicate_group_id"] != s5["duplicate_group_id"]

    def test_new_anchor_opens_its_own_group(self):
        """After the window closes, the next record becomes a fresh anchor and
        can itself gather duplicates."""
        rows = [
            _base_row(observation_id="S8", collection_timestamp="2026-09-05 09:00"),
            _base_row(observation_id="S9", collection_timestamp="2026-09-05 09:05"),
            _base_row(observation_id="SA", collection_timestamp="2026-09-05 10:00"),
            _base_row(observation_id="SB", collection_timestamp="2026-09-05 10:05"),
        ]
        out = _run(*rows)
        by_id = {r["observation_id"]: r for _, r in out.iterrows()}
        assert by_id["S9"]["duplicate_of"] == "S8"
        assert by_id["SB"]["duplicate_of"] == "SA"
        assert by_id["S8"]["duplicate_group_id"] != by_id["SA"]["duplicate_group_id"]

    def test_anchored_sweep_is_order_independent(self):
        rows = [
            _base_row(observation_id="S5", collection_timestamp="2026-09-05 09:00"),
            _base_row(observation_id="S6", collection_timestamp="2026-09-05 09:14"),
            _base_row(observation_id="S7", collection_timestamp="2026-09-05 09:28"),
        ]
        forward = _run(*rows).sort_values("observation_id").reset_index(drop=True)
        reverse = _run(*reversed(rows)).sort_values("observation_id").reset_index(drop=True)
        audit_cols = ["observation_id", "is_duplicate", "duplicate_of", "duplicate_reason"]
        assert forward[audit_cols].equals(reverse[audit_cols])


# ── Strict is_valid parsing (APPROVED) ────────────────────────────────────

class TestIsValidParsing:
    def test_literal_booleans_and_exact_strings(self):
        assert R.parse_is_valid(True) is True
        assert R.parse_is_valid(False) is False
        assert R.parse_is_valid("True") is True
        assert R.parse_is_valid("False") is False

    def test_never_raw_string_truthiness(self):
        """bool("False") is True in Python — the exact trap this guards."""
        assert R.parse_is_valid("False") is not True

    def test_unrecognized_values_raise_rather_than_silently_defaulting(self):
        for bad in ["true", "FALSE", "yes", "1", "", "  ", None, "maybe"]:
            with pytest.raises(R.IsValidParseError):
                R.parse_is_valid(bad)

    def test_engine_rejects_an_unreadable_verdict(self):
        bad = _base_row(observation_id="V1", is_valid="yes")
        with pytest.raises(R.IsValidParseError):
            _run(bad)

    def test_invalid_rows_are_excluded_from_grouping_not_misread(self):
        """An is_valid=False row that would otherwise be a perfect duplicate
        must never join a group."""
        good = _base_row(observation_id="V2", collection_timestamp="2026-09-05 10:00")
        bad = _base_row(observation_id="V3", collection_timestamp="2026-09-05 10:05",
                        is_valid=False, validation_status="INVALID")
        out = _run(good, bad)
        v3 = out[out["observation_id"] == "V3"].iloc[0]
        assert not v3["is_duplicate"]
        assert v3["retained"]
        assert v3["duplicate_reason"] == R.REASON_SKIPPED_INVALID_BY_PHASE2


# ── total_fare normalization / integer formatting (APPROVED) ──────────────────

class TestTotalFareNormalization:
    def test_integer_formatting_is_preserved(self):
        assert R.normalize_total_fare("5400") == "5400"
        assert R.normalize_total_fare(5400) == "5400"
        assert R.normalize_total_fare("5400.00") == "5400"
        assert R.normalize_total_fare(5400.0) == "5400"

    def test_genuine_decimals_are_kept(self):
        assert R.normalize_total_fare("5400.50") == "5400.5"

    def test_missing_or_non_numeric_is_none_never_zero(self):
        for value in [None, "", "   ", "nan", "n/a"]:
            assert R.normalize_total_fare(value) is None

    def test_equivalent_fare_representations_still_group(self):
        r1 = _base_row(observation_id="F1", total_fare="5400",
                       collection_timestamp="2026-09-05 10:00")
        r2 = _base_row(observation_id="F2", total_fare="5400.00",
                       collection_timestamp="2026-09-05 10:05")
        out = _run(r1, r2)
        assert out[out["observation_id"] == "F2"].iloc[0]["duplicate_of"] == "F1"

    def test_no_float_formatting_leaks_into_audit_fields(self, deduped_df):
        """The group identifier must not embed a formatted fare — that is how
        "5400" turns into "5400.0" in an audit column."""
        for value in deduped_df["duplicate_group_id"]:
            assert ".0" not in str(value)

    def test_raw_total_fare_column_is_never_rewritten(self, deduped_df, validated_df):
        assert list(deduped_df["total_fare"].fillna("")) == list(validated_df["total_fare"].fillna(""))


# ── collection_timestamp: naive local, never tz-inferred (APPROVED) ───────────

class TestNaiveLocalTimestamps:
    def test_documented_as_naive_local(self):
        assert R.COLLECTION_TIMESTAMP_IS_NAIVE_LOCAL is True
        assert R.COLLECTION_TIMESTAMP_FORMAT == "%Y-%m-%d %H:%M"

    def test_timestamps_compared_exactly_as_represented(self):
        ident = build_row_identity(_base_row(collection_timestamp="2026-09-05 10:00"))
        assert ident.collection_ts.tzinfo is None
        assert ident.collection_ts.hour == 10

    def test_timezone_marked_timestamp_is_not_silently_converted(self):
        """A tz-marked value does not match the declared contract; it must be
        treated as unparseable rather than quietly converted to some offset."""
        ident = build_row_identity(_base_row(collection_timestamp="2026-09-05 10:00+05:30"))
        assert ident.collection_ts is None
        assert ident.collection_ts_present_but_unparseable is True

    def test_empty_timestamp_is_never_within_tolerance(self):
        anchor = _base_row(observation_id="T1", collection_timestamp="2026-09-05 10:00")
        blank = _base_row(observation_id="T2", collection_timestamp="")
        results = group_and_mark([anchor, blank])
        assert results["T2"].is_duplicate is False
        assert results["T2"].retained is True


# ── Duplicate audit report (third approved output) ─────────────────────────

class TestDuplicateAuditReport:
    def test_columns_match_the_declared_schema(self, deduped_df):
        report = build_duplicate_audit_report(deduped_df)
        assert list(report.columns) == AUDIT_REPORT_COLUMNS

    def test_one_row_per_confirmed_group(self, deduped_df):
        report = build_duplicate_audit_report(deduped_df)
        assert len(report) == 1
        row = report.iloc[0]
        assert row["canonical_observation_id"] == "OBS00769"
        assert row["duplicate_observation_ids"] == "OBS00770"
        assert row["group_size"] == 2
        assert row["max_timestamp_delta_minutes"] == 1
        assert bool(row["capture_signature_agreement"]) is False
        assert row["duplicate_reason"] == R.REASON_TECHNICAL_DUPLICATE

    def test_report_preserves_integer_fare_formatting(self, deduped_df):
        report = build_duplicate_audit_report(deduped_df)
        assert str(report.iloc[0]["total_fare"]) == "5400"

    def test_empty_report_is_still_correctly_shaped(self):
        out = _run(_base_row(observation_id="Z1"))
        report = build_duplicate_audit_report(out)
        assert len(report) == 0
        assert list(report.columns) == AUDIT_REPORT_COLUMNS


# ── Locked five-condition rule remains exactly five conditions ────────────────

class TestLockedRuleIntegrity:
    def test_availability_status_only_guards_the_sold_out_rule(self):
        """availability_status is an implementation guard for the approved
        sold-out rule, not a sixth condition: two ordinary Available rows
        that satisfy the five conditions still deduplicate normally."""
        r1 = _base_row(observation_id="L1", availability_status="Available",
                       collection_timestamp="2026-09-05 10:00")
        r2 = _base_row(observation_id="L2", availability_status="Available",
                       collection_timestamp="2026-09-05 10:05")
        out = _run(r1, r2)
        assert out[out["observation_id"] == "L2"].iloc[0]["duplicate_of"] == "L1"

    def test_five_conditions_each_independently_block_a_duplicate(self):
        blockers = [
            {"travel_date": "2026-09-21"},        # economic identity
            {"flight_number": "6E-9999"},          # product-instance identity
            {"source": "Cleartrip"},               # source
            {"total_fare": "5900"},                # total_fare
            {"collection_timestamp": "2026-09-05 11:30"},  # 15-minute tolerance
        ]
        for i, override in enumerate(blockers):
            anchor = _base_row(observation_id="C%d" % (i * 2),
                               collection_timestamp="2026-09-05 10:00")
            other_fields = {
                "observation_id": "C%d" % (i * 2 + 1),
                "collection_timestamp": "2026-09-05 10:05",
            }
            other_fields.update(override)
            other = _base_row(**other_fields)
            out = _run(anchor, other)
            assert not out[out["observation_id"] == other["observation_id"]].iloc[0]["is_duplicate"], (
                "override %r should have blocked the duplicate" % override
            )

    def test_route_direction_is_not_normalized(self):
        """Out of Phase 6 scope: DEL-BOM must never be folded into BOM-DEL."""
        r1 = _base_row(observation_id="D1", origin="DEL", destination="BOM",
                       collection_timestamp="2026-09-05 10:00")
        r2 = _base_row(observation_id="D2", origin="BOM", destination="DEL",
                       collection_timestamp="2026-09-05 10:05")
        out = _run(r1, r2)
        assert not out[out["observation_id"] == "D2"].iloc[0]["is_duplicate"]
