"""
VAYU INDEX - MoSPI Airfare CPI Processing Script
==================================================

PURPOSE
-------
Processes the official MoSPI Consumer Price Index (CPI) dataset for the
Airfare sub-class (code 07.3.3.1.2.01) into a clean, analytics-ready CSV
plus a JSON provenance record.

IMPORTANT CONSTRAINTS
---------------------
- The raw Excel file is NEVER modified. It is opened read-only and the
  processed output is written to a separate directory.
- CPI index values are preserved EXACTLY as they appear in the workbook.
  No rounding, smoothing, normalisation, or recalculation is performed.
- Missing inflation values remain NaN in the output; they are NOT filled
  with zero or estimated in any way.
- This dataset is an official benchmark/reference series. It is SEPARATE
  from the synthetic Phase 1 observation dataset and must NEVER be merged
  into the observation pipeline.

USAGE
-----
    python scripts/process_mospi_airfare_cpi.py [--raw-path PATH]

OUTPUT
------
    data/official/mospi/processed/mospi_airfare_cpi.csv
    data/official/mospi/processed/metadata.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone

import pandas as pd

DEFAULT_RAW_PATH = os.path.join("data", "official", "mospi", "raw", "cpi_1822(final).xlsx")
DEFAULT_OUTPUT_DIR = os.path.join("data", "official", "mospi", "processed")
PROCESSED_CSV_NAME = "mospi_airfare_cpi.csv"
METADATA_JSON_NAME = "metadata.json"

EXPECTED_SHEET = "CPI Data"

EXPECTED_IDENTITY = {
    "base_year": 2024,
    "series":    "Current",
    "state":     "All India",
    "sector":    "Combined",
    "division":  "Transport",
    "group":     "Passenger transport services",
    "class":     "Passenger transport by air",
    "sub_class": "Passenger transport by air, domestic",
    "item":      "Airfare",
    "code":      "07.3.3.1.2.01",
}

MONTH_ORDER = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]

OUTPUT_COLUMNS = [
    "period", "year", "month",
    "cpi_index", "inflation",
    "base_year", "series",
    "state", "sector",
    "division", "group", "class", "sub_class",
    "item", "code",
    "imputation",
]


def sha256_of_file(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def month_to_int(month_name):
    return MONTH_ORDER.index(month_name) + 1


def build_period(year, month_name):
    m = month_to_int(month_name)
    return "%04d-%02d-01" % (year, m)


def process(raw_path, output_dir):
    print()
    print("=" * 50)
    print("MoSPI AIRFARE CPI PROCESSING REPORT")
    print("=" * 50)
    print()

    if not os.path.isfile(raw_path):
        sys.exit("ERROR: Raw file not found: %s" % raw_path)

    raw_hash = sha256_of_file(raw_path)
    raw_size = os.path.getsize(raw_path)
    print("Source file   :", raw_path)
    print("File size     :", raw_size, "bytes")
    print("SHA-256 (pre) :", raw_hash)
    print()

    import openpyxl
    wb = openpyxl.load_workbook(raw_path, read_only=True, data_only=True)
    available_sheets = wb.sheetnames
    wb.close()

    print("Sheet names   :", available_sheets)
    if EXPECTED_SHEET not in available_sheets:
        sys.exit("ERROR: Expected sheet '%s' not found.\nAvailable: %s" % (EXPECTED_SHEET, available_sheets))
    print("Target sheet  :", EXPECTED_SHEET, "  [FOUND]")
    print()

    df_raw = pd.read_excel(raw_path, sheet_name=EXPECTED_SHEET, header=0)
    print("Raw shape     : %d rows x %d columns" % df_raw.shape)
    print("Raw columns   :", list(df_raw.columns))
    print()

    identity_mismatches = []
    for field, expected_val in EXPECTED_IDENTITY.items():
        if field not in df_raw.columns:
            identity_mismatches.append("  MISSING COLUMN: '%s'" % field)
            continue
        unique_vals = df_raw[field].dropna().unique()
        if len(unique_vals) == 0:
            identity_mismatches.append("  EMPTY COLUMN: '%s'" % field)
        elif len(unique_vals) > 1:
            identity_mismatches.append("  MULTIPLE VALUES in '%s': %s" % (field, unique_vals))
        else:
            actual_val = unique_vals[0]
            if str(actual_val).strip() != str(expected_val).strip():
                identity_mismatches.append(
                    "  MISMATCH '%s': expected=%r, actual=%r" % (field, expected_val, actual_val)
                )

    if identity_mismatches:
        print("IDENTITY VERIFICATION FAILED:")
        for msg in identity_mismatches:
            print(msg)
        sys.exit(1)

    print("Series identity verified:")
    for field, val in EXPECTED_IDENTITY.items():
        print("  %-12s: %s" % (field, val))
    print()

    n_full_dupes = int(df_raw.duplicated().sum())
    print("Duplicate rows (fully identical):", n_full_dupes)
    if n_full_dupes > 0:
        print(df_raw[df_raw.duplicated(keep=False)].to_string())
        sys.exit("ERROR: Duplicate rows detected. Review before proceeding.")

    period_dupes = df_raw.duplicated(subset=["year", "month"], keep=False)
    n_period_dupes = int(period_dupes.sum())
    print("Duplicate year+month combos     :", n_period_dupes)
    if n_period_dupes > 0:
        print(df_raw[period_dupes][["year","month"]].to_string())
        sys.exit("ERROR: Duplicate month/year periods detected.")
    print()

    missing_per_col = df_raw.isnull().sum()
    total_missing = int(missing_per_col.sum())
    print("Missing values per column:")
    for col, n in missing_per_col.items():
        tag = ""
        if col == "inflation" and n > 0:
            tag = "  <- expected: YoY requires prior-year baseline"
        print("  %-14s: %d%s" % (col, n, tag))
    print("Total missing cells:", total_missing)
    print()

    unknown_months = set(df_raw["month"].dropna().unique()) - set(MONTH_ORDER)
    if unknown_months:
        sys.exit("ERROR: Unrecognised month names: %s" % unknown_months)

    df = df_raw.copy()
    df["period"] = df.apply(lambda r: build_period(int(r["year"]), str(r["month"])), axis=1)
    df["_month_num"] = df["month"].apply(month_to_int)
    df = df.sort_values(["year", "_month_num"]).reset_index(drop=True)
    df = df.drop(columns=["_month_num"])
    df = df.rename(columns={"index": "cpi_index"})

    all_periods = sorted(df["period"].tolist())
    date_start = all_periods[0]
    date_end   = all_periods[-1]
    n_obs      = len(all_periods)

    print("Date range    : %s -> %s" % (date_start, date_end))
    print("Observations  : %d months" % n_obs)

    from dateutil.relativedelta import relativedelta
    from datetime import date as date_type
    cursor = datetime.strptime(date_start, "%Y-%m-%d").date()
    end_dt = datetime.strptime(date_end,   "%Y-%m-%d").date()
    expected_periods = []
    while cursor <= end_dt:
        expected_periods.append(cursor.strftime("%Y-%m-%d"))
        cursor += relativedelta(months=1)

    actual_set   = set(all_periods)
    expected_set = set(expected_periods)
    missing_periods = sorted(expected_set - actual_set)
    extra_periods   = sorted(actual_set   - expected_set)

    if missing_periods:
        print("  WARNING - MISSING MONTHS:", missing_periods)
    else:
        print("  No missing months in sequence  [OK]")
    if extra_periods:
        print("  WARNING - EXTRA MONTHS:", extra_periods)
    else:
        print("  No unexpected extra months  [OK]")
    print()

    missing_output_cols = [c for c in OUTPUT_COLUMNS if c not in df.columns]
    if missing_output_cols:
        sys.exit("ERROR: Output columns missing from dataframe: %s" % missing_output_cols)

    df_out = df[OUTPUT_COLUMNS].copy()

    os.makedirs(output_dir, exist_ok=True)
    csv_path = os.path.join(output_dir, PROCESSED_CSV_NAME)
    df_out.to_csv(csv_path, index=False, float_format="%.10g")
    print("Processed CSV :", csv_path)
    print("Rows written  :", len(df_out))
    print()

    now_utc = datetime.now(timezone.utc).isoformat()
    missing_inflation_count = int(df_out["inflation"].isnull().sum())
    missing_cpi_count       = int(df_out["cpi_index"].isnull().sum())

    metadata = {
        "dataset_name": "MoSPI Consumer Price Index - Airfare (Domestic)",
        "source_organization": "Ministry of Statistics and Programme Implementation",
        "source_portal": "e-Sankhyiki",
        "source_url": "https://esankhyiki.mospi.gov.in/",
        "raw_filename": "cpi_1822(final).xlsx",
        "raw_filepath_relative": raw_path.replace("\\", "/"),
        "raw_file_sha256": raw_hash,
        "raw_file_preserved": True,
        "sheet_name": EXPECTED_SHEET,
        "series_code": EXPECTED_IDENTITY["code"],
        "item": EXPECTED_IDENTITY["item"],
        "base_year": str(EXPECTED_IDENTITY["base_year"]),
        "series": EXPECTED_IDENTITY["series"],
        "state": EXPECTED_IDENTITY["state"],
        "sector": EXPECTED_IDENTITY["sector"],
        "division": EXPECTED_IDENTITY["division"],
        "group": EXPECTED_IDENTITY["group"],
        "class": EXPECTED_IDENTITY["class"],
        "sub_class": EXPECTED_IDENTITY["sub_class"],
        "date_start": date_start,
        "date_end": date_end,
        "row_count": n_obs,
        "missing_values": {
            "cpi_index": missing_cpi_count,
            "inflation": missing_inflation_count,
            "inflation_note": (
                "Inflation (YoY%) requires a prior-year baseline. "
                "Months before the first complete prior-year window have no "
                "inflation value. This is expected, not a data error. "
                "Missing values are preserved as NaN (empty) in the CSV."
            ),
        },
        "imputation_values_present": bool((df_out["imputation"].dropna() != "N").any()),
        "duplicate_rows": n_full_dupes,
        "duplicate_periods": n_period_dupes,
        "missing_months_in_sequence": missing_periods,
        "processing_timestamp": now_utc,
        "processed_csv": os.path.join(output_dir, PROCESSED_CSV_NAME).replace("\\", "/"),
        "output_columns": OUTPUT_COLUMNS,
    }

    meta_path = os.path.join(output_dir, METADATA_JSON_NAME)
    with open(meta_path, "w", encoding="utf-8") as fh:
        json.dump(metadata, fh, indent=2, ensure_ascii=False)
    print("Metadata JSON :", meta_path)
    print()

    raw_hash_post = sha256_of_file(raw_path)
    if raw_hash_post != raw_hash:
        sys.exit("CRITICAL: Raw file hash changed!\n  Pre : %s\n  Post: %s" % (raw_hash, raw_hash_post))
    print("SHA-256 (post):", raw_hash_post, "  [unchanged]")
    print()

    print("First 5 processed rows:")
    print(df_out.head(5)[["period","year","month","cpi_index","inflation","base_year","imputation"]].to_string(index=False))
    print()
    print("=" * 50)
    print()

    return {
        "metadata": metadata,
        "df_out": df_out,
        "csv_path": csv_path,
        "meta_path": meta_path,
        "raw_hash_pre": raw_hash,
        "raw_hash_post": raw_hash_post,
    }


def main():
    parser = argparse.ArgumentParser(description="VAYU INDEX - Process MoSPI Airfare CPI dataset")
    parser.add_argument("--raw-path",   default=DEFAULT_RAW_PATH,   help="Path to raw Excel workbook")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR, help="Output directory")
    args = parser.parse_args()
    process(args.raw_path, args.output_dir)


if __name__ == "__main__":
    main()
