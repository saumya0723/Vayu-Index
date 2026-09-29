"""
tests/test_route_basket.py
=================================
Automated test suite for STEP 5 – Phase 5 data-integrity fixes to
build_vayu_route_basket.py (Tasks A-D).

Tests cover:
  - Safe city-code mapping (no pseudo-IATA fallback)
  - Documented aliases (MANGALORE, SIMLA, BHATINDA, TIRUCHIRAPALLY)
  - GOA is deliberately left unmapped (two-airport ambiguity)
  - Unknown cities resolve to FLAG_FOR_REVIEW, never a guessed code
  - Self-pair exclusion (retained, not deleted, with explicit reason)
  - Conservative vs zero-treated DASH totals
  - Ranking export precision (no global float_format truncation)
  - No route_id collisions among mapped routes
"""

import os
import sys
import math
import pandas as pd
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
import build_vayu_route_basket as rb  # noqa: E402


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def loaded():
    """Run load_and_rank() once for all tests in this module."""
    full_df, ranked, total_pax = rb.load_and_rank()
    return full_df, ranked, total_pax


# ── TASK A: City code mapping ──────────────────────────────────────────────────

class TestCityCodeMapping:
    def test_known_city_returns_verified_code(self):
        code, status = rb.get_iata_code("DELHI")
        assert code == "DEL"
        assert status == "MAPPED"

    def test_unknown_city_flags_for_review_not_guessed(self):
        code, status = rb.get_iata_code("SOME_TOTALLY_UNKNOWN_CITY")
        assert code is None
        assert status == "FLAG_FOR_REVIEW"

    def test_no_pseudo_code_fallback(self):
        """
        The old c1[:3].upper() fallback would have returned 'SOM' for this
        input. Confirm that behaviour is gone.
        """
        code, status = rb.get_iata_code("SOME_TOTALLY_UNKNOWN_CITY")
        assert code != "SOM"

    @pytest.mark.parametrize("alias,expected_code", [
        ("MANGALORE", "IXE"),
        ("SIMLA", "SLV"),
        ("BHATINDA", "BUP"),
        ("TIRUCHIRAPALLY", "TRZ"),
    ])
    def test_documented_aliases_resolve_correctly(self, alias, expected_code):
        code, status = rb.get_iata_code(alias)
        assert status == "MAPPED"
        assert code == expected_code

    def test_alias_matches_canonical_spelling_code(self):
        """MANGALORE and MANGALURU must resolve to the same verified code."""
        code_alias, _ = rb.get_iata_code("MANGALORE")
        code_canonical, _ = rb.get_iata_code("MANGALURU")
        assert code_alias == code_canonical == "IXE"

    def test_goa_is_deliberately_unmapped(self):
        """
        GOA must NOT be mapped to any code. Goa has two separate,
        currently-operating airports (Dabolim/GOI and Mopa/GOX, since
        Jan 2023); DGCA's 'GOA' vs 'DABOLIM' entries carry materially
        different passenger counts for the same city-pairs, so merging
        them would be an unverified guess, not a documented mapping.
        """
        code, status = rb.get_iata_code("GOA")
        assert code is None
        assert status == "FLAG_FOR_REVIEW"

    def test_dabolim_remains_mapped(self):
        """DABOLIM (unambiguous) must still resolve normally."""
        code, status = rb.get_iata_code("DABOLIM")
        assert code == "GOI"
        assert status == "MAPPED"

    @pytest.mark.parametrize("city,expected_code", [
        ("AGATTI ISLAND", "AGX"),
        ("BILASPUR", "PAB"),
        ("CUDDAPAH", "CDP"),
        ("DARBHANGA", "DBR"),
        ("DEOGHAR", "DGH"),
        ("DHARAMSALA", "DHM"),
        ("JHARSUGUDA", "JRG"),
        ("KANNUR", "CNN"),
        ("PONDICHERRY", "PNY"),
        ("ROURKELA", "RRK"),
        ("SHIVAMOGGA AIRPORT", "RQY"),
        ("JALGAON", "JLG"),
    ])
    def test_task3_verified_additions_resolve_correctly(self, city, expected_code):
        """
        Cities added after the Task 3 unmapped-city review, each verified
        against an independent public source before being added.
        """
        code, status = rb.get_iata_code(city)
        assert status == "MAPPED"
        assert code == expected_code

    def test_rajkot_boundary_bleed_no_longer_flagged(self, loaded):
        """
        After the upstream parser fix, RAJKOT INTERNATIONAL AIRPORT must
        resolve as a single, correctly-spelled, mapped city — the
        previously-corrupted 'RAJKOT INTERNATIONAL AIRPOR' / 'TUDAIPUR'
        fragments must no longer exist anywhere in the dataset.
        """
        full_df, _, _ = loaded
        all_cities = set(full_df["city_1_standardized"]) | set(full_df["city_2_standardized"])
        assert "RAJKOT INTERNATIONAL AIRPOR" not in all_cities
        assert "TUDAIPUR" not in all_cities
        code, status = rb.get_iata_code("RAJKOT INTERNATIONAL AIRPORT")
        assert status == "MAPPED"
        assert code == "RAJ"

    def test_route_id_flags_when_either_city_unmapped(self):
        rid, status = rb.make_route_id("DELHI", "GOA")
        assert rid == rb.FLAG_FOR_REVIEW
        assert status == rb.FLAG_FOR_REVIEW

    def test_route_id_mapped_when_both_cities_known(self):
        rid, status = rb.make_route_id("DELHI", "MUMBAI")
        assert status == "MAPPED"
        assert rid == "BOM-DEL"  # alphabetic ordering of IATA codes

    def test_no_route_id_collisions_among_mapped_routes(self, loaded):
        """
        Two structurally different DGCA rows must never silently collapse
        into the same route_id unless they truly are the same airport pair.
        """
        _, ranked, _ = loaded
        mapped = ranked[ranked["route_id"] != rb.FLAG_FOR_REVIEW]
        dup = mapped[mapped.duplicated(subset=["route_id"], keep=False)]
        assert len(dup) == 0, (
            f"Unexpected route_id collisions:\n{dup[['city_1_standardized','city_2_standardized','route_id']]}"
        )


# ── TASK B: Self-pair handling ─────────────────────────────────────────────────

class TestSelfPairHandling:
    def test_self_pair_present_and_retained(self, loaded):
        """The known HYDERABAD/HYDERABAD self-pair row must still exist in
        the full (unfiltered) dataset — never silently dropped."""
        full_df, _, _ = loaded
        self_pairs = full_df[
            full_df["city_1_standardized"] == full_df["city_2_standardized"]
        ]
        assert len(self_pairs) >= 1

    def test_self_pair_excluded_from_eligibility(self, loaded):
        full_df, _, _ = loaded
        self_pairs = full_df[
            full_df["city_1_standardized"] == full_df["city_2_standardized"]
        ]
        assert (self_pairs["basket_eligible"] == False).all()  # noqa: E712

    def test_self_pair_has_explicit_reason(self, loaded):
        full_df, _, _ = loaded
        self_pairs = full_df[
            full_df["city_1_standardized"] == full_df["city_2_standardized"]
        ]
        for reason in self_pairs["exclusion_reason"]:
            assert reason.startswith("SELF_PAIR")

    def test_self_pair_not_in_ranked_eligible_set(self, loaded):
        _, ranked, _ = loaded
        self_pairs_in_ranked = ranked[
            ranked["city_1_standardized"] == ranked["city_2_standardized"]
        ]
        assert len(self_pairs_in_ranked) == 0


# ── DASH treatment: conservative vs zero-treated ───────────────────────────────

class TestDashTreatment:
    def test_conservative_total_nan_when_either_direction_missing(self):
        row = pd.DataFrame([{
            "passengers_city1_to_city2": 100,
            "passengers_city2_to_city1": float("nan"),
        }])
        result = rb.compute_totals(row)
        assert math.isnan(result["conservative_total_bidirectional_passengers"].iloc[0])

    def test_zero_treated_total_substitutes_zero(self):
        row = pd.DataFrame([{
            "passengers_city1_to_city2": 100,
            "passengers_city2_to_city1": float("nan"),
        }])
        result = rb.compute_totals(row)
        assert result["zero_treated_total_bidirectional_passengers"].iloc[0] == 100

    def test_both_totals_equal_when_both_directions_present(self):
        row = pd.DataFrame([{
            "passengers_city1_to_city2": 100,
            "passengers_city2_to_city1": 50,
        }])
        result = rb.compute_totals(row)
        assert result["conservative_total_bidirectional_passengers"].iloc[0] == 150
        assert result["zero_treated_total_bidirectional_passengers"].iloc[0] == 150

    def test_ranking_uses_conservative_total_only(self, loaded):
        """No row in the ranked/eligible set should have a NaN conservative
        total — confirms ranking did not fall back to zero-treated."""
        _, ranked, _ = loaded
        assert ranked["conservative_total_bidirectional_passengers"].isna().sum() == 0

    def test_dash_affected_route_excluded_with_explicit_reason(self, loaded):
        """AGARTALA-AIZAWL is a known DASH-affected row (one direction only)."""
        full_df, _, _ = loaded
        row = full_df[
            (full_df["city_1_standardized"] == "AGARTALA") &
            (full_df["city_2_standardized"] == "AIZAWL")
        ]
        assert len(row) == 1
        assert row.iloc[0]["basket_eligible"] == False  # noqa: E712
        assert row.iloc[0]["exclusion_reason"].startswith("MISSING_DIRECTIONAL_DATA")


# ── TASK C: Ranking export precision ───────────────────────────────────────────

class TestRankingPrecision:
    def test_ranking_csv_written(self, loaded, tmp_path, monkeypatch):
        _, ranked, _ = loaded
        rb.save_ranking(ranked)
        assert os.path.isfile(rb.RANKING_CSV)

    def test_cumulative_coverage_pct_has_decimal_precision(self):
        out = pd.read_csv(rb.RANKING_CSV)
        non_integer_values = out["cumulative_coverage_pct"] % 1 != 0
        assert non_integer_values.sum() > 0, (
            "cumulative_coverage_pct appears to have been truncated to "
            "whole numbers — precision fix did not take effect."
        )

    def test_passenger_columns_are_exact_integers(self):
        out = pd.read_csv(rb.RANKING_CSV)
        for col in [
            "passengers_city1_to_city2", "passengers_city2_to_city1",
            "conservative_total_bidirectional_passengers",
        ]:
            non_integer = (out[col].dropna() % 1 != 0).sum()
            assert non_integer == 0, f"{col} has non-integer values."

    def test_conservative_and_zero_treated_columns_both_present(self):
        out = pd.read_csv(rb.RANKING_CSV)
        assert "conservative_total_bidirectional_passengers" in out.columns
        assert "zero_treated_total_bidirectional_passengers" in out.columns


# ── Exclusions report ───────────────────────────────────────────────────────────

class TestExclusionsReport:
    def test_exclusions_report_generated(self, loaded):
        full_df, _, _ = loaded
        rb.save_excluded_report(full_df)
        path = os.path.join(rb.OUT_DIR, "dgca_route_exclusions.csv")
        assert os.path.isfile(path)

    def test_exclusions_report_has_reasons_for_every_row(self, loaded):
        full_df, _, _ = loaded
        excluded = rb.save_excluded_report(full_df)
        assert (excluded["exclusion_reason"].str.len() > 0).all()

    def test_no_source_rows_deleted(self, loaded):
        """Full dataset must still contain all 835 original rows regardless
        of eligibility — exclusion must never mean deletion."""
        full_df, _, _ = loaded
        assert len(full_df) == 835


# ── VAYU-Basket-Rule-v1 (approved Phase 5 basket) ──────────────────────────────

class TestApprovedBasket:
    @pytest.fixture(scope="class")
    @staticmethod
    def basket(loaded):
        _, ranked, _ = loaded
        return rb.select_diversified_basket(ranked)

    def test_basket_has_exactly_15_routes(self, basket):
        assert len(basket) == 15

    def test_basket_reproducible(self, loaded, basket):
        """Re-running the rule against the same ranked data must yield an
        identical route_id sequence — no hidden randomness or manual input."""
        _, ranked, _ = loaded
        rerun = rb.select_diversified_basket(ranked)
        assert list(rerun["route_id"]) == list(basket.sort_values("basket_rank")["route_id"])

    def test_top_10_included_unconditionally(self, loaded, basket):
        _, ranked, _ = loaded
        top10_ids = set(ranked.head(10)["route_id"])
        basket_ids = set(basket["route_id"])
        assert top10_ids.issubset(basket_ids)

    def test_all_six_regions_represented(self, basket):
        regions = set(basket["region_city_1"]) | set(basket["region_city_2"])
        assert rb.ALL_REGIONS.issubset(regions)

    def test_no_duplicate_route_ids(self, basket):
        assert basket["route_id"].duplicated().sum() == 0

    def test_no_route_uses_ambiguous_goa(self, basket):
        """GOA must remain unmapped; DABOLIM (unambiguous) may be used."""
        assert "GOA" not in set(basket["city_1"]) | set(basket["city_2"])

    def test_weights_sum_to_one(self, basket):
        weighted, _ = rb.compute_weights(basket)
        assert abs(weighted["traffic_weight"].sum() - 1.0) < 1e-6

    def test_weights_non_negative(self, basket):
        weighted, _ = rb.compute_weights(basket)
        assert (weighted["traffic_weight"] >= 0).all()

    def test_uses_conservative_total_for_weights(self, loaded, basket):
        """Weight computation must be based on conservative totals, not
        zero-treated totals — confirms DASH treatment choice was respected."""
        weighted, total = rb.compute_weights(basket)
        expected_total = basket["total_bidirectional_passengers"].sum()
        assert total == expected_total

    def test_expected_route_ids_present(self, basket):
        """Sanity-check against the specific approved basket (traffic ranks
        1,2,3,4,5,6,7,8,9,10,11,18,19,21,39)."""
        expected_ids = {
            "BOM-DEL", "BLR-DEL", "BLR-BOM", "DEL-HYD", "DEL-PNQ",
            "CCU-DEL", "AMD-DEL", "DEL-MAA", "BOM-HYD", "BLR-CCU",
            "DEL-SXR", "DEL-GOI", "DEL-GAU", "BLR-COK", "DEL-IDR",
        }
        assert set(basket["route_id"]) == expected_ids

    def test_verify_basket_passes(self, loaded, basket):
        _, ranked, _ = loaded
        weighted, _ = rb.compute_weights(basket)
        assert rb.verify_basket(weighted, ranked) is True

    def test_save_basket_files_created(self, loaded, basket, tmp_path):
        _, ranked, total_pax = loaded
        weighted, _ = rb.compute_weights(basket)
        rb.save_basket(weighted, total_pax)
        rb.save_basket_metadata(weighted, total_pax)
        rb.save_methodology_doc(weighted, total_pax)
        assert os.path.isfile(rb.BASKET_CSV)
        assert os.path.isfile(rb.BASKET_META)
        assert os.path.isfile(rb.METHODOLOGY)

    def test_metadata_json_is_valid_and_labeled_non_official(self, loaded, basket):
        import json
        _, _, total_pax = loaded
        weighted, _ = rb.compute_weights(basket)
        rb.save_basket_metadata(weighted, total_pax)
        with open(rb.BASKET_META) as f:
            meta = json.load(f)
        assert meta["basket_size"] == 15
        assert meta["selection_method"] == "VAYU-Basket-Rule-v1"
        assert any("NOT" in s for s in meta["what_this_is_not"])
        assert abs(meta["weight_sum"] - 1.0) < 1e-6


# ── Publication weight rounding / residual adjustment (final cleanup) ─────────

class TestPublicationWeightRounding:
    @pytest.fixture(scope="class")
    @staticmethod
    def basket(loaded):
        _, ranked, _ = loaded
        return rb.select_diversified_basket(ranked)

    def test_exported_csv_weight_sum_is_exactly_one(self, loaded, basket):
        """
        The core requirement of this cleanup pass: the SUM OF THE EXPORTED
        CSV'S traffic_weight COLUMN, read back from disk (not the in-memory
        floating-point value), must equal 1.0 within float64 precision noise
        (~1e-9), at the documented 6-decimal publication precision.
        """
        _, ranked, total_pax = loaded
        weighted, _ = rb.compute_weights(basket)
        rb.save_basket(weighted, total_pax)

        reread = pd.read_csv(rb.BASKET_CSV)
        reread_sum = reread["traffic_weight"].sum()
        assert abs(reread_sum - 1.0) < 1e-9, (
            f"Exported CSV traffic_weight column sums to {reread_sum!r}, not 1.0"
        )
        # Also confirm at the documented publication precision (6dp string form)
        assert f"{reread_sum:.6f}" == "1.000000"

    def test_full_precision_weights_preserved_in_csv(self, loaded, basket):
        """traffic_weight_full_precision must be exported so the unadjusted
        proportional value is always recoverable, not just the published one."""
        _, ranked, total_pax = loaded
        weighted, _ = rb.compute_weights(basket)
        rb.save_basket(weighted, total_pax)
        reread = pd.read_csv(rb.BASKET_CSV)
        assert "traffic_weight_full_precision" in reread.columns
        assert "weight_residual_applied" in reread.columns

    def test_exactly_one_route_carries_the_residual(self, basket):
        """The residual adjustment must be applied to exactly one route
        (or zero, if rounding happens to already sum to 1.0) — never spread
        across multiple routes, and never applied silently to more than one."""
        weighted, _ = rb.compute_weights(basket)
        published = rb.apply_publication_rounding(weighted)
        adjusted = published[published["weight_residual_applied"] != 0]
        assert len(adjusted) <= 1

    def test_residual_goes_to_largest_weight_route(self, basket):
        """Per the documented rule, if a residual exists, it must be applied
        to the route with the largest full-precision weight."""
        weighted, _ = rb.compute_weights(basket)
        published = rb.apply_publication_rounding(weighted)
        adjusted = published[published["weight_residual_applied"] != 0]
        if len(adjusted) == 1:
            largest_route_id = published.sort_values(
                "traffic_weight_full_precision", ascending=False
            ).iloc[0]["route_id"]
            assert adjusted.iloc[0]["route_id"] == largest_route_id

    def test_rounding_is_deterministic_across_reruns(self, basket):
        """Re-applying publication rounding to the same basket must always
        adjust the same route by the same amount — no randomness."""
        weighted, _ = rb.compute_weights(basket)
        p1 = rb.apply_publication_rounding(weighted)
        p2 = rb.apply_publication_rounding(weighted)
        pd.testing.assert_series_equal(
            p1.set_index("route_id")["traffic_weight"].sort_index(),
            p2.set_index("route_id")["traffic_weight"].sort_index(),
        )

    def test_selected_routes_unchanged_by_rounding_fix(self, basket):
        """This cleanup must not alter which 15 routes are in the basket."""
        expected_ids = {
            "BOM-DEL", "BLR-DEL", "BLR-BOM", "DEL-HYD", "DEL-PNQ",
            "CCU-DEL", "AMD-DEL", "DEL-MAA", "BOM-HYD", "BLR-CCU",
            "DEL-SXR", "DEL-GOI", "DEL-GAU", "BLR-COK", "DEL-IDR",
        }
        assert set(basket["route_id"]) == expected_ids

    def test_metadata_reports_rounding_rule_and_sums_to_one(self, loaded, basket):
        import json
        _, _, total_pax = loaded
        weighted, _ = rb.compute_weights(basket)
        rb.save_basket_metadata(weighted, total_pax)
        with open(rb.BASKET_META) as f:
            meta = json.load(f)
        assert meta["weight_publication_precision"] == 6
        assert "weight_rounding_rule" in meta
        assert abs(meta["weight_sum"] - 1.0) < 1e-6
        # per-route full precision + residual fields present
        for route in meta["routes"]:
            assert "traffic_weight_full_precision" in route
            assert "weight_residual_applied" in route
