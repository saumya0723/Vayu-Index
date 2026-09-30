"""
STEP 4 – DGCA City-Pair PDF Extraction & Validation
====================================================
Source : TABLE 5.01 (INDIAN CITY-WISE PASSENGER TRAFFIC).pdf
Output : data/official/dgca/processed/
           dgca_city_pair_passenger_traffic_2024_25.csv
           metadata.json

Rules
-----
- No values are altered, rounded, scaled or invented.
- "-" in the PDF is preserved as NaN in numeric columns and documented.
- Original directional columns are preserved intact.
- total_bidirectional_passengers is a DERIVED field (not from source).
- Records where either directional value is NaN are flagged for review.
"""

import os
import re
import json
import math
import hashlib
import pdfplumber
import pandas as pd
from datetime import datetime, timezone

# -- Paths -------------------------------------------------------------------
BASE_DIR   = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW_DIR    = os.path.join(BASE_DIR, "data", "official", "dgca", "raw")
PROC_DIR   = os.path.join(BASE_DIR, "data", "official", "dgca", "processed")
PDF_NAME   = "TABLE 5.01 (INDIAN CITY-WISE PASSENGER TRAFFIC).pdf"
PDF_PATH   = os.path.join(RAW_DIR, PDF_NAME)
CSV_PATH   = os.path.join(PROC_DIR, "dgca_city_pair_passenger_traffic_2024_25.csv")
META_PATH  = os.path.join(PROC_DIR, "metadata.json")

FINANCIAL_YEAR = "2024-25"
TABLE_TITLE    = "CITY PAIR WISE SCHEDULED DOMESTIC PASSENGER TRAFFIC STATISTICS FOR THE YEAR 2024-25"

# Patterns found in header/sub-header rows that must be skipped
SKIP_PATTERNS = [
    "CITY PAIR WISE SCHEDULED DOMESTIC PASSENGER TRAFFIC STATISTICS",
    "PASSENGERS ( IN NUMBER )",
    "S.No.",
    "S.No",
]

# ── PDF Parsing Artifact: long airport-name column bleed ─────────────────────
# pdfplumber's automatic column-boundary detection on this PDF produces the
# same underlying failure in two different column positions: a long airport
# name does not fit its column, and the tail characters bleed into the START
# of the NEXT column's cell.
#
# VARIANT 1 — city_2 -> pax_to_city_2 boundary (CITY 2 column overflow):
#   Confirmed on 12 rows, every one involving "Ayodhya International Airport"
#   placed in the CITY 2 column. This name is NEVER seen intact anywhere in
#   the raw table extraction — it overflows on every single occurrence.
#     city_2  cell -> "Ayodhya International Airp"   (truncated, missing "ort")
#     pax_to  cell -> "ort <value>" or "ort -"         (continuation glued to
#                                                        the real passenger value)
#
# VARIANT 2 — city_1 -> city_2 boundary (CITY 1 column overflow):
#   Confirmed on exactly 1 row (S.No 825), involving "Rajkot International
#   Airport" placed in the CITY 1 column. Verified directly against
#   pdfplumber's raw extract_tables() output: this exact name appears CORRECTLY
#   in every one of its other 7 occurrences, all of which place it in the
#   (wider) CITY 2 column — it only overflows here because it lands in the
#   narrower CITY 1 column.
#     city_1  cell -> "Rajkot International Airpor"   (truncated, missing final "t")
#     city_2  cell -> "tUDAIPUR"                        (leftover "t" glued
#                                                        directly onto the
#                                                        real next city, with
#                                                        no separating space)
#
# Both variants were verified against the actual PDF (not inferred from the
# processed CSV or guessed). A full scan of all 835 extracted rows for any
# other cell that is a truncated prefix of a longer cell value found found no
# further occurrences of either pattern — this appears to be the complete set
# for this table.
#
# KNOWN_LONG_NAMES holds the canonical (correctly capitalized, as seen intact
# elsewhere in this same PDF) form of every name known to trigger this
# overflow. Adding a new confirmed case in future extractions only requires
# adding an entry here — the two variant-detectors below are already general.
KNOWN_LONG_NAMES = [
    "Ayodhya International Airport",
    "Rajkot International Airport",
]
_KNOWN_LONG_NAMES_UPPER = {n.upper(): n for n in KNOWN_LONG_NAMES}


def _repair_city2_pax_boundary_bleed(row):
    """
    VARIANT 1: a known long name in CITY 2 bleeds into the PASSENGERS-TO-CITY2
    cell. Generalizes the original Ayodhya-only check to any name in
    KNOWN_LONG_NAMES, so a second confirmed case of this same variant would
    not require a new hand-written detector.
    """
    if len(row) != 5 or row[2] is None or row[3] is None:
        return row, False

    c2_raw = str(row[2]).strip()
    pax_raw = str(row[3]).strip()

    for full_upper, full_canonical in _KNOWN_LONG_NAMES_UPPER.items():
        if c2_raw.upper() == full_upper:
            continue  # already intact, nothing to repair
        if full_upper.startswith(c2_raw.upper()) and 0 < len(full_upper) - len(c2_raw.upper()) <= 6:
            missing_suffix = full_upper[len(c2_raw):]
            if pax_raw.upper().startswith(missing_suffix):
                repaired = list(row)
                repaired[2] = full_canonical
                repaired[3] = pax_raw[len(missing_suffix):].strip()
                return repaired, True
    return row, False


def _repair_city1_city2_boundary_bleed(row):
    """
    VARIANT 2: a known long name in CITY 1 bleeds into the CITY 2 cell.
    Newly added to fix the Rajkot/Udaipur corruption (S.No 825) and to
    generalize against any future case of the same class.
    """
    if len(row) != 5 or row[1] is None or row[2] is None:
        return row, False

    c1_raw = str(row[1]).strip()
    c2_raw = str(row[2]).strip()

    for full_upper, full_canonical in _KNOWN_LONG_NAMES_UPPER.items():
        if c1_raw.upper() == full_upper:
            continue  # already intact, nothing to repair
        if full_upper.startswith(c1_raw.upper()) and 0 < len(full_upper) - len(c1_raw.upper()) <= 6:
            missing_suffix = full_upper[len(c1_raw):]
            if c2_raw.upper().startswith(missing_suffix):
                repaired = list(row)
                repaired[1] = full_canonical
                repaired[2] = c2_raw[len(missing_suffix):].strip()
                return repaired, True
    return row, False


def repair_column_bleed(row):
    """
    Apply both known column-bleed repair variants to a raw table row.

    Returns (possibly repaired row, repair_type) where repair_type is one of:
      ""                              - no repair needed
      "CITY2_PAX_BOUNDARY_BLEED"      - Variant 1 (e.g. Ayodhya)
      "CITY1_CITY2_BOUNDARY_BLEED"    - Variant 2 (e.g. Rajkot/Udaipur)

    A row can only match one variant; each check is independent and
    order-safe since they inspect different column boundaries.
    """
    row, repaired1 = _repair_city2_pax_boundary_bleed(row)
    if repaired1:
        return row, "CITY2_PAX_BOUNDARY_BLEED"

    row, repaired2 = _repair_city1_city2_boundary_bleed(row)
    if repaired2:
        return row, "CITY1_CITY2_BOUNDARY_BLEED"

    return row, ""


def is_skip_row(row):
    """Return True if this row is a repeated page header, not a data row."""
    if not row or not row[0]:
        return True
    first = str(row[0]).strip()
    for pat in SKIP_PATTERNS:
        if pat in first:
            return True
    return False


def clean_city_name(raw):
    """
    Minimal deterministic city-name cleaning:
      - strip leading/trailing whitespace
      - collapse internal multiple spaces to one
      - convert to UPPER CASE
    No semantic renaming done here.
    """
    if raw is None:
        return ""
    cleaned = re.sub(r"\s+", " ", str(raw).strip())
    return cleaned.upper()


def parse_passenger_value(raw):
    """
    Parse a single passenger cell from the PDF.

    Rules:
      - Numeric string  -> int
      - "-" or empty    -> NaN  (DGCA convention for zero/not-operated)
      - Anything else   -> NaN  + warning flag

    Returns (value, flag)
      value : int or float('nan')
      flag  : str reason or ""
    """
    if raw is None or str(raw).strip() == "":
        return float("nan"), "MISSING_EMPTY"
    s = str(raw).strip()
    if s == "-":
        return float("nan"), "DGCA_DASH"
    # Remove commas used as thousands separator (safety)
    s_clean = s.replace(",", "")
    try:
        val = int(s_clean)
        return val, ""
    except ValueError:
        return float("nan"), "UNPARSEABLE:" + repr(s)


def md5_file(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def extract_rows_from_pdf():
    """
    Extract all city-pair data rows from the PDF.

    Returns:
        rows     : list of raw dicts
        pdf_meta : dict with page-level metadata
    """
    os.makedirs(PROC_DIR, exist_ok=True)

    rows = []
    page_row_counts = {}
    pages_with_data = 0

    with pdfplumber.open(PDF_PATH) as pdf:
        total_pages = len(pdf.pages)

        for page_num, page in enumerate(pdf.pages, 1):
            tables = page.extract_tables()
            page_data_count = 0

            for table in tables:
                for row in table:
                    if is_skip_row(row):
                        continue

                    # Expect exactly 5 columns; skip malformed rows
                    if len(row) != 5:
                        continue

                    # Repair column-bleed artifact before parsing
                    row, repair_type = repair_column_bleed(row)
                    was_repaired = bool(repair_type)

                    sno_raw, city1_raw, city2_raw, pax_to_c2_raw, pax_from_c2_raw = row

                    # S.No must look like a number
                    sno_str = str(sno_raw).strip() if sno_raw else ""
                    if not sno_str.isdigit():
                        continue

                    city1_orig = str(city1_raw).strip() if city1_raw else ""
                    city2_orig = str(city2_raw).strip() if city2_raw else ""

                    pax_to, flag_to     = parse_passenger_value(pax_to_c2_raw)
                    pax_from, flag_from = parse_passenger_value(pax_from_c2_raw)

                    rows.append({
                        "source_sno"                 : int(sno_str),
                        "original_city_1"            : city1_orig,
                        "original_city_2"            : city2_orig,
                        "city_1_standardized"        : clean_city_name(city1_orig),
                        "city_2_standardized"        : clean_city_name(city2_orig),
                        "passengers_city1_to_city2"  : pax_to,
                        "passengers_city2_to_city1"  : pax_from,
                        "flag_city1_to_city2"        : flag_to,
                        "flag_city2_to_city1"        : flag_from,
                        "pdf_parsing_repaired"       : was_repaired,
                        "pdf_parsing_repair_type"    : repair_type,
                        "source_page"                : page_num,
                    })
                    page_data_count += 1

            if page_data_count > 0:
                pages_with_data += 1
            page_row_counts[str(page_num)] = page_data_count

    pdf_meta = {
        "total_pages"     : total_pages,
        "pages_with_data" : pages_with_data,
        "page_row_counts" : page_row_counts,
    }
    return rows, pdf_meta


def build_dataframe(rows):
    df = pd.DataFrame(rows)

    # Assign record_id (1-based sequential)
    df.insert(0, "record_id", range(1, len(df) + 1))

    # Derive total bidirectional (NaN if either direction is NaN)
    def derive_total(r):
        c1 = r["passengers_city1_to_city2"]
        c2 = r["passengers_city2_to_city1"]
        if math.isnan(c1) or math.isnan(c2):
            return float("nan")
        return c1 + c2

    df["total_bidirectional_passengers"] = df.apply(derive_total, axis=1)

    # Needs review flag
    df["needs_review"] = (
        df["flag_city1_to_city2"].ne("") | df["flag_city2_to_city1"].ne("")
    )

    # Financial year
    df["financial_year"] = FINANCIAL_YEAR

    return df


def validate_dataframe(df):
    """Run validation checks; return a summary dict."""
    issues = []

    if len(df) == 0:
        issues.append("CRITICAL: No rows extracted")

    required_cols = [
        "record_id", "original_city_1", "original_city_2",
        "passengers_city1_to_city2", "passengers_city2_to_city1",
        "total_bidirectional_passengers", "financial_year", "source_page",
    ]
    for col in required_cols:
        if col not in df.columns:
            issues.append("MISSING COLUMN: " + col)

    blank_c1 = df["original_city_1"].eq("").sum()
    if blank_c1 > 0:
        issues.append("BLANK city_1: " + str(blank_c1) + " rows")

    blank_c2 = df["original_city_2"].eq("").sum()
    if blank_c2 > 0:
        issues.append("BLANK city_2: " + str(blank_c2) + " rows")

    same_city = (df["city_1_standardized"] == df["city_2_standardized"]).sum()
    if same_city > 0:
        issues.append("CITY1 == CITY2: " + str(same_city) + " rows")

    header_rows = df["original_city_1"].str.contains(
        "CITY PAIR|S\\.No", na=False, regex=True
    ).sum()
    if header_rows > 0:
        issues.append("HEADER ROWS in data: " + str(header_rows))

    dup = df.duplicated(subset=["city_1_standardized", "city_2_standardized"]).sum()
    if dup > 0:
        issues.append("DUPLICATE (city1, city2) pairs: " + str(dup))

    for col in ["passengers_city1_to_city2", "passengers_city2_to_city1"]:
        neg = (df[col].dropna() < 0).sum()
        if neg > 0:
            issues.append("NEGATIVE values in " + col + ": " + str(neg))

    wrong_fy = (df["financial_year"] != FINANCIAL_YEAR).sum()
    if wrong_fy > 0:
        issues.append("WRONG financial year: " + str(wrong_fy) + " rows")

    total        = len(df)
    valid_rows   = int(df[~df["needs_review"]].shape[0])
    invalid_rows = int(df["needs_review"].sum())
    dup_pairs    = int(df.duplicated(
        subset=["city_1_standardized", "city_2_standardized"]
    ).sum())

    missing_c1_pax = int(df["passengers_city1_to_city2"].isna().sum())
    missing_c2_pax = int(df["passengers_city2_to_city1"].isna().sum())

    numeric_pax  = df["passengers_city1_to_city2"].dropna()
    min_pax      = int(numeric_pax.min()) if not numeric_pax.empty else None
    max_pax      = int(numeric_pax.max()) if not numeric_pax.empty else None

    total_bidir  = int(df["total_bidirectional_passengers"].dropna().sum())
    unique_pairs = int(df[["city_1_standardized", "city_2_standardized"]].drop_duplicates().shape[0])

    return {
        "issues"                : issues,
        "total_rows"            : total,
        "valid_rows"            : valid_rows,
        "invalid_rows"          : invalid_rows,
        "duplicate_pairs"       : dup_pairs,
        "missing_c1_to_c2_pax" : missing_c1_pax,
        "missing_c2_to_c1_pax" : missing_c2_pax,
        "min_pax_single_dir"   : min_pax,
        "max_pax_single_dir"   : max_pax,
        "total_bidirectional"  : total_bidir,
        "unique_city_pairs"    : unique_pairs,
    }


def save_csv(df):
    out_cols = [
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
    df[out_cols].to_csv(CSV_PATH, index=False, float_format="%.0f")
    print("[OK] CSV saved -> " + CSV_PATH)


def save_metadata(pdf_meta, validation, raw_md5):
    meta = {
        "source_organization"   : "Directorate General of Civil Aviation",
        "source_portal"         : "https://www.dgca.gov.in",
        "dataset_name"          : "City Pair Wise Scheduled Domestic Passenger Traffic Statistics",
        "report_year"           : FINANCIAL_YEAR,
        "raw_filename"          : PDF_NAME,
        "source_url"            : (
            "Not available - file provided directly; "
            "refer to https://www.dgca.gov.in for official portal"
        ),
        "download_date"         : "2026-09-07",
        "table_title"           : TABLE_TITLE,
        "parsing_repair_notes"  : (
            "Two variants of the same underlying column-boundary-overflow "
            "artifact were found and repaired, both verified directly against "
            "pdfplumber's raw extract_tables() output (not inferred or guessed).\n"
            "VARIANT 1 (repair_type=CITY2_PAX_BOUNDARY_BLEED): 12 rows affected. "
            "The long airport name 'Ayodhya International Airport', placed in "
            "the CITY 2 column, does not fit and bleeds into the adjacent "
            "PASSENGERS-TO-CITY2 cell on every single occurrence. city_2 was "
            "truncated to 'Ayodhya International Airp' and the leading 'ort ' "
            "prefix from the continuation was glued onto the pax_to_city2 cell. "
            "Repaired deterministically: city_2 restored to 'Ayodhya "
            "International Airport', passenger value extracted from the "
            "'ort <value>' remainder.\n"
            "VARIANT 2 (repair_type=CITY1_CITY2_BOUNDARY_BLEED): 1 row affected "
            "(S.No 825). The long airport name 'Rajkot International Airport', "
            "placed in the (narrower) CITY 1 column, overflows into the CITY 2 "
            "cell — this same name renders correctly in all 7 of its other "
            "occurrences, all in the wider CITY 2 column. city_1 was truncated "
            "to 'Rajkot International Airpor' (missing final 't') and that "
            "missing 't' was glued directly onto the start of the real next "
            "city name 'UDAIPUR' with no separating space, producing "
            "'tUDAIPUR' in the city_2 cell. Repaired deterministically: city_1 "
            "restored to 'Rajkot International Airport', city_2 restored to "
            "'UDAIPUR'.\n"
            "All repaired rows have pdf_parsing_repaired=True and "
            "pdf_parsing_repair_type set to the variant above. A full scan of "
            "all 835 extracted rows for any other cell that is a truncated "
            "prefix of a longer cell value elsewhere in the dataset found no "
            "further occurrences of either variant."
        ),
        "pages"                 : pdf_meta["total_pages"],
        "pages_with_data"       : pdf_meta["pages_with_data"],
        "page_row_counts"       : pdf_meta["page_row_counts"],
        "extracted_rows"        : validation["total_rows"],
        "valid_rows"            : validation["valid_rows"],
        "invalid_rows_flagged"  : validation["invalid_rows"],
        "duplicate_pairs"       : validation["duplicate_pairs"],
        "missing_c1_to_c2_pax" : validation["missing_c1_to_c2_pax"],
        "missing_c2_to_c1_pax" : validation["missing_c2_to_c1_pax"],
        "unique_city_pairs"     : validation["unique_city_pairs"],
        "total_bidirectional_passengers" : validation["total_bidirectional"],
        "dash_interpretation"   : (
            "The symbol '-' in the source PDF is used by DGCA to indicate "
            "zero or not-operated traffic on that direction. "
            "It has been preserved as NaN in the numeric columns and flagged via "
            "flag_city1_to_city2 / flag_city2_to_city1 = 'DGCA_DASH'. "
            "Do NOT automatically substitute 0 without confirming intent."
        ),
        "derived_fields"        : {
            "total_bidirectional_passengers": (
                "passengers_city1_to_city2 + passengers_city2_to_city1. "
                "NaN when either directional value is NaN."
            )
        },
        "processing_timestamp"  : datetime.now(timezone.utc).isoformat(),
        "raw_file_preserved"    : True,
        "raw_file_md5"          : raw_md5,
        "processed_csv"         : CSV_PATH,
        "validation_issues"     : validation["issues"],
    }
    with open(META_PATH, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)
    print("[OK] Metadata saved -> " + META_PATH)


def print_quality_report(df, validation, pdf_name, total_pages):
    sep = "=" * 72

    print("\n" + sep)
    print("  DGCA CITY-PAIR DATA - QUALITY REPORT")
    print(sep)
    print("  PDF filename   : " + pdf_name)
    print("  Financial year : " + FINANCIAL_YEAR)
    print("  Pages          : " + str(total_pages))
    print("  Extracted rows : " + str(validation["total_rows"]))
    print("  Valid rows     : " + str(validation["valid_rows"]))
    print("  Flagged rows   : " + str(validation["invalid_rows"]))
    print("  Duplicate pairs: " + str(validation["duplicate_pairs"]))
    print("  Missing C1->C2 : " + str(validation["missing_c1_to_c2_pax"]) + " rows")
    print("  Missing C2->C1 : " + str(validation["missing_c2_to_c1_pax"]) + " rows")
    if validation["min_pax_single_dir"] is not None:
        print("  Min pax(1-dir) : " + "{:,}".format(validation["min_pax_single_dir"]))
        print("  Max pax(1-dir) : " + "{:,}".format(validation["max_pax_single_dir"]))
    print("  Total bidir pax: " + "{:,}".format(validation["total_bidirectional"]))
    print("  Unique pairs   : " + str(validation["unique_city_pairs"]))

    if validation["issues"]:
        print("\n  VALIDATION ISSUES (" + str(len(validation["issues"])) + "):")
        for iss in validation["issues"]:
            print("    [!] " + iss)
    else:
        print("\n  [OK] All validation checks passed.")

    # Top 20
    ranked = (
        df[["city_1_standardized", "city_2_standardized",
            "passengers_city1_to_city2", "passengers_city2_to_city1",
            "total_bidirectional_passengers"]]
        .dropna(subset=["total_bidirectional_passengers"])
        .sort_values("total_bidirectional_passengers", ascending=False)
        .head(20)
        .reset_index(drop=True)
    )

    print("\n" + sep)
    print("  TOP 20 CITY-PAIRS BY TOTAL BIDIRECTIONAL PASSENGER TRAFFIC")
    print(sep)
    print("  {:<3}  {:<28}  {:<28}  {:>12}  {:>12}  {:>14}".format(
        "#", "CITY 1", "CITY 2", "-> CITY2", "<- CITY1", "TOTAL BIDIR"
    ))
    print("  {:<3}  {:<28}  {:<28}  {:>12}  {:>12}  {:>14}".format(
        "---", "-"*28, "-"*28, "-"*12, "-"*12, "-"*14
    ))
    for i, row in ranked.iterrows():
        c1  = str(row["city_1_standardized"])[:28]
        c2  = str(row["city_2_standardized"])[:28]
        p12 = row["passengers_city1_to_city2"]
        p21 = row["passengers_city2_to_city1"]
        tot = row["total_bidirectional_passengers"]
        p12s = "{:,}".format(int(p12)) if not math.isnan(p12) else "N/A"
        p21s = "{:,}".format(int(p21)) if not math.isnan(p21) else "N/A"
        tots = "{:,}".format(int(tot))
        print("  {:<3}  {:<28}  {:<28}  {:>12}  {:>12}  {:>14}".format(
            i+1, c1, c2, p12s, p21s, tots
        ))

    print("\n" + sep + "\n")


def main():
    print("[START] Processing DGCA PDF: " + PDF_NAME)

    # Record raw file MD5 before any processing
    raw_md5 = md5_file(PDF_PATH)
    print("[INFO]  Raw PDF MD5 (before): " + raw_md5)

    # Extract
    rows, pdf_meta = extract_rows_from_pdf()
    print("[INFO]  Extracted " + str(len(rows)) + " raw data rows from "
          + str(pdf_meta["total_pages"]) + " pages.")

    # Build DataFrame
    df = build_dataframe(rows)

    # Validate
    validation = validate_dataframe(df)

    # Save outputs
    save_csv(df)
    save_metadata(pdf_meta, validation, raw_md5)

    # Quality report
    print_quality_report(df, validation, PDF_NAME, pdf_meta["total_pages"])

    # Verify raw PDF is untouched
    raw_md5_after = md5_file(PDF_PATH)
    if raw_md5 == raw_md5_after:
        print("[OK]  Raw PDF is UNTOUCHED (MD5 verified).")
    else:
        print("[FAIL] Raw PDF MD5 changed! Investigate immediately.")

    print("[DONE] STEP 4 processing complete.")


if __name__ == "__main__":
    main()
