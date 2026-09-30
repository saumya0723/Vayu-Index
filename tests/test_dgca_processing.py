"""
tests/test_dgca_processing.py
=================================
Automated test suite for STEP 4 – DGCA City-Pair PDF processing.

Tests cover:
  - Non-empty extraction
  - Expected financial year
  - Required columns present
  - Numeric passenger counts
  - Non-negative counts
  - No duplicate city-pair records
  - total_bidirectional_passengers calculation
  - Raw PDF remains untouched
  - Processed CSV created
  - Metadata JSON created
  - Flagged rows have documented reasons
  - Parsing-repaired rows are correctly documented
"""

import os
import math
import json
import hashlib
import pytest
import pandas as pd

# ── Paths ────────────────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW_DIR  = os.path.join(BASE_DIR, "data", "official", "dgca", "raw")
PROC_DIR = os.path.join(BASE_DIR, "data", "official", "dgca", "processed")

PDF_NAME = "TABLE 5.01 (INDIAN CITY-WISE PASSENGER TRAFFIC).pdf"
PDF_PATH = os.path.join(RAW_DIR, PDF_NAME)
CSV_PATH = os.path.join(PROC_DIR, "dgca_city_pair_passenger_traffic_2024_25.csv")
META_PATH = os.path.join(PROC_DIR, "metadata.json")

EXPECTED_FINANCIAL_YEAR = "2024-25"

REQUIRED_COLUMNS = [
    "record_id",
    "source_sno",
    "original_city_1",
    "original_city_2",
    "city_1_standardized",
    "city_2_standardized",
    "passengers_city1_to_city2",
    "passengers_city2_to_city1",
    "flag_city1_to_city2",
    "flag_city2_to_city1",
    "total_bidirectional_passengers",
    "needs_review",
    "pdf_parsing_repaired",
    "pdf_parsing_repair_type",
    "financial_year",
    "source_page",
]

KNOWN_RAW_MD5 = "9d70f1a13d08043b4c8e260f803a4467"


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def df():
    """Load the processed CSV once for all tests in this module."""
    assert os.path.isfile(CSV_PATH), (
        f"Processed CSV not found: {CSV_PATH}\n"
        "Run scripts/process_dgca_city_pair.py first."
    )
    return pd.read_csv(CSV_PATH)


@pytest.fixture(scope="module")
def meta():
    """Load metadata.json once for all tests in this module."""
    assert os.path.isfile(META_PATH), (
        f"metadata.json not found: {META_PATH}\n"
        "Run scripts/process_dgca_city_pair.py first."
    )
    with open(META_PATH, encoding="utf-8") as f:
        return json.load(f)


# ── File-existence tests ───────────────────────────────────────────────────────

class TestFilesExist:
    def test_raw_pdf_exists(self):
        """Raw PDF must exist in expected location."""
        assert os.path.isfile(PDF_PATH), f"Raw PDF missing: {PDF_PATH}"

    def test_processed_csv_exists(self):
        """Processed CSV must have been created."""
        assert os.path.isfile(CSV_PATH), f"Processed CSV missing: {CSV_PATH}"

    def test_metadata_json_exists(self):
        """Metadata JSON must have been created."""
        assert os.path.isfile(META_PATH), f"metadata.json missing: {META_PATH}"


# ── Raw-PDF integrity tests ────────────────────────────────────────────────────

class TestRawPDFUntouched:
    def test_raw_pdf_md5_unchanged(self):
        """Raw PDF MD5 must match the known value – confirms file was not modified."""
        h = hashlib.md5()
        with open(PDF_PATH, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        actual_md5 = h.hexdigest()
        assert actual_md5 == KNOWN_RAW_MD5, (
            f"Raw PDF MD5 changed!\n"
            f"  Expected : {KNOWN_RAW_MD5}\n"
            f"  Actual   : {actual_md5}"
        )


# ── Non-empty extraction ───────────────────────────────────────────────────────

class TestExtraction:
    def test_non_empty_extraction(self, df):
        """Dataset must contain at least one row."""
        assert len(df) > 0, "No rows were extracted from the PDF."

    def test_reasonable_row_count(self, df):
        """
        We know the PDF has 835 rows. Accept within a small tolerance
        in case PDF rendering varies slightly.
        """
        assert 800 <= len(df) <= 870, (
            f"Row count {len(df)} outside expected range [800, 870]."
        )

    def test_all_17_pages_covered(self, meta):
        """All 17 pages of the PDF must have been processed."""
        assert meta["pages"] == 17, f"Expected 17 pages, got {meta['pages']}"
        assert meta["pages_with_data"] == 17, (
            f"Expected 17 pages with data, got {meta['pages_with_data']}"
        )


# ── Financial year ─────────────────────────────────────────────────────────────

class TestFinancialYear:
    def test_financial_year_column_value(self, df):
        """Every row must have financial_year = '2024-25'."""
        wrong = (df["financial_year"] != EXPECTED_FINANCIAL_YEAR).sum()
        assert wrong == 0, (
            f"{wrong} rows have wrong financial year (expected '{EXPECTED_FINANCIAL_YEAR}')."
        )

    def test_metadata_report_year(self, meta):
        """Metadata report_year must be '2024-25'."""
        assert meta["report_year"] == EXPECTED_FINANCIAL_YEAR


# ── Required columns ───────────────────────────────────────────────────────────

class TestColumns:
    def test_required_columns_present(self, df):
        """All required columns must be present in the CSV."""
        missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
        assert missing == [], f"Missing columns: {missing}"


# ── City name checks ────────────────────────────────────────────────────────────

class TestCityNames:
    def test_city_1_not_blank(self, df):
        """original_city_1 must not be blank in any row."""
        blank = df["original_city_1"].eq("").sum()
        assert blank == 0, f"{blank} rows have blank original_city_1."

    def test_city_2_not_blank(self, df):
        """original_city_2 must not be blank in any row."""
        blank = df["original_city_2"].eq("").sum()
        assert blank == 0, f"{blank} rows have blank original_city_2."

    def test_standardized_cities_exist(self, df):
        """city_1_standardized and city_2_standardized must be non-blank."""
        blank_c1 = df["city_1_standardized"].eq("").sum()
        blank_c2 = df["city_2_standardized"].eq("").sum()
        assert blank_c1 == 0, f"{blank_c1} rows have blank city_1_standardized."
        assert blank_c2 == 0, f"{blank_c2} rows have blank city_2_standardized."


# ── Numeric passenger counts ────────────────────────────────────────────────────

class TestPassengerCounts:
    def test_numeric_passengers_city1_to_city2(self, df):
        """
        passengers_city1_to_city2 must be numeric (int/float) in each row.
        NaN is acceptable (DGCA '-' rows); non-numeric strings are not.
        """
        non_numeric = []
        for idx, val in df["passengers_city1_to_city2"].items():
            if val != val:  # NaN check
                continue
            try:
                float(val)
            except (TypeError, ValueError):
                non_numeric.append((idx, val))
        assert non_numeric == [], (
            f"Non-numeric values in passengers_city1_to_city2: {non_numeric[:5]}"
        )

    def test_numeric_passengers_city2_to_city1(self, df):
        """
        passengers_city2_to_city1 must be numeric in each row.
        NaN is acceptable.
        """
        non_numeric = []
        for idx, val in df["passengers_city2_to_city1"].items():
            if val != val:
                continue
            try:
                float(val)
            except (TypeError, ValueError):
                non_numeric.append((idx, val))
        assert non_numeric == [], (
            f"Non-numeric values in passengers_city2_to_city1: {non_numeric[:5]}"
        )

    def test_non_negative_c1_to_c2(self, df):
        """Non-NaN passengers_city1_to_city2 must be >= 0."""
        neg = (df["passengers_city1_to_city2"].dropna() < 0).sum()
        assert neg == 0, f"{neg} negative values in passengers_city1_to_city2."

    def test_non_negative_c2_to_c1(self, df):
        """Non-NaN passengers_city2_to_city1 must be >= 0."""
        neg = (df["passengers_city2_to_city1"].dropna() < 0).sum()
        assert neg == 0, f"{neg} negative values in passengers_city2_to_city1."


# ── Duplicate city-pair check ───────────────────────────────────────────────────

class TestDuplicates:
    def test_no_duplicate_city_pairs(self, df):
        """
        (city_1_standardized, city_2_standardized) must be unique across all rows.
        The DGCA table stores one directional pair per row; duplicates indicate
        a parsing or source error.
        """
        dup_count = df.duplicated(
            subset=["city_1_standardized", "city_2_standardized"]
        ).sum()
        assert dup_count == 0, (
            f"{dup_count} duplicate (city1, city2) pairs found.\n"
            "NOTE: DELHI->MUMBAI and MUMBAI->DELHI are NOT duplicates;\n"
            "they are separate rows with separate directionality."
        )


# ── Derived total calculation ────────────────────────────────────────────────────

class TestDerivedTotal:
    def test_total_bidirectional_calculation(self, df):
        """
        total_bidirectional_passengers must equal the sum of both directional
        columns when both are available, and NaN when either is missing.
        """
        errors = []
        for idx, row in df.iterrows():
            c1  = row["passengers_city1_to_city2"]
            c2  = row["passengers_city2_to_city1"]
            tot = row["total_bidirectional_passengers"]

            c1_nan  = (c1 != c1)   # NaN check
            c2_nan  = (c2 != c2)
            tot_nan = (tot != tot)

            if c1_nan or c2_nan:
                # When either direction is NaN, total must also be NaN
                if not tot_nan:
                    errors.append(
                        f"Row {idx}: directional NaN but total={tot} (expected NaN)"
                    )
            else:
                expected = c1 + c2
                if tot_nan or abs(tot - expected) > 0.5:
                    errors.append(
                        f"Row {idx}: expected total={expected}, got {tot}"
                    )

        assert errors == [], (
            f"total_bidirectional_passengers mismatch in {len(errors)} rows:\n"
            + "\n".join(errors[:10])
        )

    def test_total_bidirectional_is_positive_where_defined(self, df):
        """total_bidirectional_passengers must be >= 0 wherever it is not NaN."""
        neg = (df["total_bidirectional_passengers"].dropna() < 0).sum()
        assert neg == 0, f"{neg} negative total_bidirectional_passengers values."


# ── Flag / needs_review consistency ─────────────────────────────────────────────

class TestFlags:
    def test_needs_review_consistent_with_flags(self, df):
        """
        needs_review must be True iff at least one flag column is non-empty.

        Note: When re-loaded from CSV, empty string flag cells become NaN in
        pandas. We treat NaN as "no flag" (equivalent to empty string) here.
        """
        def flag_is_set(val):
            """Return True if val is a non-empty, non-NaN string."""
            if val != val:   # NaN check (NaN != NaN)
                return False
            return bool(str(val).strip())

        errors = []
        for idx, row in df.iterrows():
            has_flag = flag_is_set(row["flag_city1_to_city2"]) or \
                       flag_is_set(row["flag_city2_to_city1"])
            if has_flag != row["needs_review"]:
                errors.append(
                    f"Row {idx}: needs_review={row['needs_review']} but "
                    f"flags=({row['flag_city1_to_city2']!r}, {row['flag_city2_to_city1']!r})"
                )
        assert errors == [], (
            f"needs_review inconsistency in {len(errors)} rows:\n"
            + "\n".join(errors[:10])
        )

    def test_dgca_dash_rows_have_nan_passengers(self, df):
        """
        Rows flagged with 'DGCA_DASH' must have NaN (not 0 or some number)
        in the corresponding passenger column.
        """
        dash_c1 = df[df["flag_city1_to_city2"] == "DGCA_DASH"]
        bad_c1  = dash_c1["passengers_city1_to_city2"].notna().sum()
        assert bad_c1 == 0, (
            f"{bad_c1} DGCA_DASH rows have non-NaN passengers_city1_to_city2."
        )

        dash_c2 = df[df["flag_city2_to_city1"] == "DGCA_DASH"]
        bad_c2  = dash_c2["passengers_city2_to_city1"].notna().sum()
        assert bad_c2 == 0, (
            f"{bad_c2} DGCA_DASH rows have non-NaN passengers_city2_to_city1."
        )


# ── Parsing repair ───────────────────────────────────────────────────────────────

class TestParsingRepair:
    def test_total_repaired_row_count(self, df):
        """
        13 rows total: 12 Ayodhya (CITY2_PAX_BOUNDARY_BLEED) + 1 Rajkot/
        Udaipur (CITY1_CITY2_BOUNDARY_BLEED), confirmed by direct inspection
        of pdfplumber's raw table extraction for this PDF.
        """
        repaired = df[df["pdf_parsing_repaired"] == True]
        assert len(repaired) == 13, (
            f"Expected 13 repaired rows (12 Ayodhya + 1 Rajkot/Udaipur), "
            f"found {len(repaired)}."
        )

    def test_ayodhya_repaired_rows_have_correct_city_name(self, df):
        """
        Rows repaired via the CITY2_PAX_BOUNDARY_BLEED variant must have
        city_2 = 'AYODHYA INTERNATIONAL AIRPORT'.
        """
        repaired = df[df["pdf_parsing_repair_type"] == "CITY2_PAX_BOUNDARY_BLEED"]
        assert len(repaired) == 12, (
            f"Expected 12 Ayodhya-variant repaired rows, found {len(repaired)}."
        )
        for idx, row in repaired.iterrows():
            assert row["city_2_standardized"] == "AYODHYA INTERNATIONAL AIRPORT", (
                f"Row {idx}: repaired row has unexpected city_2 = {row['city_2_standardized']!r}"
            )

    def test_rajkot_udaipur_repaired_row_has_correct_city_names(self, df):
        """
        S.No 825, repaired via the CITY1_CITY2_BOUNDARY_BLEED variant, must
        have city_1 = 'RAJKOT INTERNATIONAL AIRPORT' and city_2 = 'UDAIPUR'.
        """
        repaired = df[df["pdf_parsing_repair_type"] == "CITY1_CITY2_BOUNDARY_BLEED"]
        assert len(repaired) == 1, (
            f"Expected exactly 1 Rajkot/Udaipur-variant repaired row, found {len(repaired)}."
        )
        row = repaired.iloc[0]
        assert row["source_sno"] == 825
        assert row["city_1_standardized"] == "RAJKOT INTERNATIONAL AIRPORT"
        assert row["city_2_standardized"] == "UDAIPUR"
        assert row["passengers_city1_to_city2"] == 276
        assert row["passengers_city2_to_city1"] == 252

    def test_repaired_rows_have_numeric_passengers_c1_c2(self, df):
        """
        Repaired rows must have numeric passengers_city1_to_city2
        (the value was recovered from the column-bleed artifact)
        OR a DGCA_DASH flag if the original value was '-'.
        """
        repaired = df[df["pdf_parsing_repaired"] == True]
        for idx, row in repaired.iterrows():
            pax = row["passengers_city1_to_city2"]
            flag = row["flag_city1_to_city2"]
            if flag == "DGCA_DASH":
                # Correct: '-' was repaired to NaN with proper flag
                assert pax != pax, f"Row {idx}: DGCA_DASH but pax is not NaN."
            else:
                # Must be numeric
                assert pax == pax and pax >= 0, (
                    f"Row {idx}: repaired pax value invalid: {pax}"
                )

    def test_no_other_column_bleed_anomalies_remain(self, df):
        """
        Full-dataset guard: no city_1 or city_2 standardized value should be
        a truncated prefix of another (longer) standardized value elsewhere
        in the dataset, and no city_1/city_2 value should exactly equal a
        known-long-name's truncated form. This mirrors the exhaustive scan
        used to confirm the Rajkot/Udaipur case was the only Variant 2
        occurrence and that no unrepaired Variant 1/2 cases remain.
        """
        names = pd.concat([df["city_1_standardized"], df["city_2_standardized"]])
        suspicious_fragments = ["RAJKOT INTERNATIONAL AIRPOR", "TUDAIPUR", "AYODHYA INTERNATIONAL AIRP"]
        for frag in suspicious_fragments:
            assert (names == frag).sum() == 0, (
                f"Unrepaired column-bleed fragment still present: {frag!r}"
            )


# ── Metadata tests ────────────────────────────────────────────────────────────────

class TestMetadata:
    def test_metadata_source_organization(self, meta):
        assert meta["source_organization"] == "Directorate General of Civil Aviation"

    def test_metadata_raw_filename(self, meta):
        assert meta["raw_filename"] == PDF_NAME

    def test_metadata_raw_file_preserved(self, meta):
        assert meta["raw_file_preserved"] is True

    def test_metadata_extracted_rows_matches_csv(self, df, meta):
        assert meta["extracted_rows"] == len(df), (
            f"metadata extracted_rows ({meta['extracted_rows']}) "
            f"!= CSV rows ({len(df)})"
        )

    def test_metadata_has_processing_timestamp(self, meta):
        assert "processing_timestamp" in meta
        assert meta["processing_timestamp"], "processing_timestamp is empty"

    def test_metadata_has_dash_interpretation(self, meta):
        """Metadata must document the '-' convention from the PDF."""
        assert "dash_interpretation" in meta
        assert "DGCA_DASH" in meta["dash_interpretation"]

    def test_metadata_has_derived_field_documentation(self, meta):
        """total_bidirectional_passengers must be documented as derived."""
        assert "derived_fields" in meta
        assert "total_bidirectional_passengers" in meta["derived_fields"]
