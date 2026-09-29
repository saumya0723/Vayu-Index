"""
VAYU INDEX - Tests for MoSPI Airfare CPI processing pipeline
=============================================================

Tests cover:
  1.  Correct workbook / sheet loaded
  2.  Series code correct
  3.  Item correct
  4.  Base year correct
  5.  State correct
  6.  Sector correct
  7.  Date range correct (Jan 2025 - Jul 2026)
  8.  Expected number of records (19)
  9.  No duplicate rows
  10. No duplicate monthly periods
  11. CPI index values preserved exactly
  12. Missing inflation values remain NaN (not filled with 0)
  13. Raw file unchanged after processing (SHA-256 comparison)
  14. Processed CSV exists after running process()
  15. metadata.json exists and contains required keys
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import sys
import tempfile

import pandas as pd
import pytest

# Allow running from project root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts.process_mospi_airfare_cpi import (
    process,
    sha256_of_file,
    EXPECTED_IDENTITY,
    EXPECTED_SHEET,
    OUTPUT_COLUMNS,
)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

RAW_PATH = os.path.join("data", "official", "mospi", "raw", "cpi_1822(final).xlsx")

# CPI values exactly as they appear in the workbook (Jan 2025 -> Jul 2026)
EXPECTED_CPI_VALUES = {
    "2025-01-01": 115.05,
    "2025-02-01": 131.66,
    "2025-03-01": 108.19,
    "2025-04-01": 110.94,
    "2025-05-01": 110.92,
    "2025-06-01": 114.48,
    "2025-07-01": 102.05,
    "2025-08-01": 112.11,
    "2025-09-01": 105.22,
    "2025-10-01": 108.19,
    "2025-11-01": 121.45,
    "2025-12-01": 124.23,
    "2026-01-01": 122.71,
    "2026-02-01": 122.43,
    "2026-03-01": 123.55,
    "2026-04-01": 123.27,
    "2026-05-01": 127.62,
    "2026-06-01": 126.09,
    "2026-07-01": 125.46,
}

EXPECTED_INFLATION_MISSING = [
    "2025-01-01", "2025-02-01", "2025-03-01", "2025-04-01",
    "2025-05-01", "2025-06-01", "2025-07-01", "2025-08-01",
    "2025-09-01", "2025-10-01", "2025-11-01", "2025-12-01",
]

EXPECTED_INFLATION_PRESENT = [
    "2026-01-01", "2026-02-01", "2026-03-01",
    "2026-04-01", "2026-05-01", "2026-06-01", "2026-07-01",
]


# ---------------------------------------------------------------------------
# Fixture: run process() once into a temp dir and cache the result
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def processed(tmp_path_factory):
    """Run the full processing pipeline and return the result dict."""
    out_dir = str(tmp_path_factory.mktemp("mospi_processed"))
    result = process(RAW_PATH, out_dir)
    return result


# ---------------------------------------------------------------------------
# Test 1: Correct workbook / sheet loaded
# ---------------------------------------------------------------------------

def test_correct_sheet_loaded(processed):
    df = processed["df_out"]
    # If the wrong sheet were loaded the identity columns would be absent or wrong
    assert "cpi_index" in df.columns, "cpi_index column missing - wrong sheet or rename failed"
    assert len(df) > 0, "DataFrame is empty"


# ---------------------------------------------------------------------------
# Test 2: Series code correct
# ---------------------------------------------------------------------------

def test_series_code(processed):
    df = processed["df_out"]
    codes = df["code"].dropna().unique().tolist()
    assert codes == ["07.3.3.1.2.01"], "Series code mismatch: %s" % codes


# ---------------------------------------------------------------------------
# Test 3: Item correct
# ---------------------------------------------------------------------------

def test_item(processed):
    df = processed["df_out"]
    items = df["item"].dropna().unique().tolist()
    assert items == ["Airfare"], "Item mismatch: %s" % items


# ---------------------------------------------------------------------------
# Test 4: Base year correct
# ---------------------------------------------------------------------------

def test_base_year(processed):
    df = processed["df_out"]
    # base_year is stored as int in the workbook
    actual = str(df["base_year"].dropna().unique()[0]).strip()
    assert actual == "2024", "Base year mismatch: %s" % actual


# ---------------------------------------------------------------------------
# Test 5: State correct
# ---------------------------------------------------------------------------

def test_state(processed):
    df = processed["df_out"]
    states = df["state"].dropna().unique().tolist()
    assert states == ["All India"], "State mismatch: %s" % states


# ---------------------------------------------------------------------------
# Test 6: Sector correct
# ---------------------------------------------------------------------------

def test_sector(processed):
    df = processed["df_out"]
    sectors = df["sector"].dropna().unique().tolist()
    assert sectors == ["Combined"], "Sector mismatch: %s" % sectors


# ---------------------------------------------------------------------------
# Test 7: Date range correct
# ---------------------------------------------------------------------------

def test_date_range(processed):
    df = processed["df_out"]
    periods = sorted(df["period"].tolist())
    assert periods[0] == "2025-01-01", "Start period wrong: %s" % periods[0]
    assert periods[-1] == "2026-07-01", "End period wrong:   %s" % periods[-1]


# ---------------------------------------------------------------------------
# Test 8: Expected number of records (19)
# ---------------------------------------------------------------------------

def test_row_count(processed):
    df = processed["df_out"]
    assert len(df) == 19, "Expected 19 rows, got %d" % len(df)


# ---------------------------------------------------------------------------
# Test 9: No duplicate rows
# ---------------------------------------------------------------------------

def test_no_duplicate_rows(processed):
    df = processed["df_out"]
    n_dupes = int(df.duplicated().sum())
    assert n_dupes == 0, "%d duplicate rows found" % n_dupes


# ---------------------------------------------------------------------------
# Test 10: No duplicate monthly periods
# ---------------------------------------------------------------------------

def test_no_duplicate_periods(processed):
    df = processed["df_out"]
    n_dupes = int(df.duplicated(subset=["period"]).sum())
    assert n_dupes == 0, "%d duplicate periods found" % n_dupes


# ---------------------------------------------------------------------------
# Test 11: CPI index values preserved exactly
# ---------------------------------------------------------------------------

def test_cpi_values_exact(processed):
    df = processed["df_out"].set_index("period")
    for period, expected_val in EXPECTED_CPI_VALUES.items():
        assert period in df.index, "Period %s missing from output" % period
        actual_val = float(df.loc[period, "cpi_index"])
        assert abs(actual_val - expected_val) < 1e-6, (
            "CPI mismatch for %s: expected=%.2f, actual=%.2f" % (period, expected_val, actual_val)
        )


# ---------------------------------------------------------------------------
# Test 12: Missing inflation values remain NaN (not filled with 0)
# ---------------------------------------------------------------------------

def test_missing_inflation_is_nan(processed):
    df = processed["df_out"].set_index("period")
    for period in EXPECTED_INFLATION_MISSING:
        val = df.loc[period, "inflation"]
        assert (val is None or (isinstance(val, float) and math.isnan(val))), (
            "Inflation for %s should be NaN/missing, got: %r" % (period, val)
        )


def test_inflation_present_where_expected(processed):
    df = processed["df_out"].set_index("period")
    for period in EXPECTED_INFLATION_PRESENT:
        val = df.loc[period, "inflation"]
        assert val is not None and not (isinstance(val, float) and math.isnan(val)), (
            "Inflation for %s should be present, got: %r" % (period, val)
        )


# ---------------------------------------------------------------------------
# Test 13: Raw file unchanged after processing (SHA-256)
# ---------------------------------------------------------------------------

def test_raw_file_unchanged(processed):
    assert processed["raw_hash_pre"] == processed["raw_hash_post"], (
        "Raw file hash changed during processing!"
    )


def test_raw_file_still_exists():
    assert os.path.isfile(RAW_PATH), "Raw file missing: %s" % RAW_PATH


# ---------------------------------------------------------------------------
# Test 14: Processed CSV exists and is non-empty
# ---------------------------------------------------------------------------

def test_processed_csv_exists(processed):
    csv_path = processed["csv_path"]
    assert os.path.isfile(csv_path), "Processed CSV not found: %s" % csv_path
    df_check = pd.read_csv(csv_path)
    assert len(df_check) == 19, "Processed CSV row count wrong: %d" % len(df_check)


def test_processed_csv_columns(processed):
    csv_path = processed["csv_path"]
    df_check = pd.read_csv(csv_path)
    for col in OUTPUT_COLUMNS:
        assert col in df_check.columns, "Column '%s' missing from processed CSV" % col


# ---------------------------------------------------------------------------
# Test 15: metadata.json exists and contains required keys
# ---------------------------------------------------------------------------

REQUIRED_META_KEYS = [
    "dataset_name", "source_organization", "source_portal", "source_url",
    "raw_filename", "raw_file_sha256", "raw_file_preserved",
    "sheet_name", "series_code", "item", "base_year", "series",
    "state", "sector", "date_start", "date_end", "row_count",
    "processing_timestamp", "processed_csv", "output_columns",
    "missing_values", "duplicate_rows", "duplicate_periods",
]


def test_metadata_json_exists(processed):
    meta_path = processed["meta_path"]
    assert os.path.isfile(meta_path), "metadata.json not found: %s" % meta_path


def test_metadata_json_keys(processed):
    meta_path = processed["meta_path"]
    with open(meta_path, encoding="utf-8") as fh:
        meta = json.load(fh)
    missing_keys = [k for k in REQUIRED_META_KEYS if k not in meta]
    assert not missing_keys, "Missing keys in metadata.json: %s" % missing_keys


def test_metadata_values(processed):
    meta_path = processed["meta_path"]
    with open(meta_path, encoding="utf-8") as fh:
        meta = json.load(fh)
    assert meta["raw_file_preserved"] is True
    assert meta["series_code"] == "07.3.3.1.2.01"
    assert meta["item"] == "Airfare"
    assert meta["base_year"] == "2024"
    assert meta["state"] == "All India"
    assert meta["sector"] == "Combined"
    assert meta["date_start"] == "2025-01-01"
    assert meta["date_end"] == "2026-07-01"
    assert meta["row_count"] == 19
    assert meta["duplicate_rows"] == 0
    assert meta["duplicate_periods"] == 0
    assert meta["missing_values"]["cpi_index"] == 0
    assert meta["missing_values"]["inflation"] == 12
