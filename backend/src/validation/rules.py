"""
VAYU INDEX — Phase 2: Validation Rules
========================================

This module defines ONLY deterministic, structural/logical validity checks.

It deliberately does NOT:
- flag a fare as invalid merely because it is high or low (that is
  ANOMALY DETECTION — a later, separate stage)
- deduplicate records (that is Phase 3)
- consolidate across sources (that is a later stage)

Validation answers exactly one question per row:
    "Is this observation structurally and logically usable?"

Every check below returns a machine-readable error CODE (a short
UPPER_SNAKE_CASE string) when it fails, or contributes nothing when it
passes. All triggered codes for a row are collected — never just the
first one — so a row with three problems reports all three.

OBSERVED vs DERIVED, kept explicit throughout:
- OBSERVED (came from the source): origin, destination, carrier,
  flight_number, travel_date, departure_time, collection_timestamp,
  fare_class, base_fare, taxes, fees, total_fare, source,
  availability_status.
- DERIVED (computed, not scraped): advance_purchase_days,
  advance_purchase_window. This module RECOMPUTES both from the
  observed travel_date/collection_timestamp and cross-checks them
  against the stored values, rather than trusting the stored derived
  fields blindly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, date
from typing import Optional, List, Dict, Any
import re

# ---------------------------------------------------------------------------
# Configuration — must stay consistent with generate_synthetic_dataset.py
# ---------------------------------------------------------------------------

ALLOWED_AVAILABILITY_STATUSES = {"Available", "Sold Out"}

# (label, low_days, high_days) — same bands used by the Phase 1 generator.
# If the generator's bands ever change, update this table to match, or the
# ADVANCE_PURCHASE_WINDOW_MISMATCH rule will fire on every row.
WINDOW_BANDS = [
    ("T1", 0, 2),
    ("T7", 5, 9),
    ("T15", 12, 18),
    ("T30", 25, 35),
    ("T45", 40, 50),
]

TRAVEL_DATE_FORMAT = "%Y-%m-%d"
COLLECTION_TS_FORMAT = "%Y-%m-%d %H:%M"
DEPARTURE_TIME_PATTERN = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")

# Sanity bound for "impossible dates" — deliberately generous; this is a
# structural sanity check, not a project-specific business rule.
MIN_SANE_YEAR = 2000
MAX_SANE_YEAR = 2100

# Rounding tolerance (INR) when checking total_fare against its components.
FARE_COMPONENT_TOLERANCE = 1.0


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def is_missing(value: Any) -> bool:
    """True if value is NaN/None/empty-string/whitespace-only string."""
    if value is None:
        return True
    try:
        import pandas as pd  # local import keeps this module usable without pandas too
        if pd.isna(value):
            return True
    except (ImportError, TypeError):
        pass
    if isinstance(value, str) and value.strip() == "":
        return True
    return False


def to_float(value: Any) -> Optional[float]:
    """Parse a numeric field. Returns None if missing OR not parseable —
    callers must distinguish 'missing' from 'present but invalid' themselves
    using is_missing() first."""
    if is_missing(value):
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def parse_date(value: Any) -> Optional[date]:
    if is_missing(value):
        return None
    try:
        return datetime.strptime(str(value).strip(), TRAVEL_DATE_FORMAT).date()
    except ValueError:
        return None


def parse_collection_timestamp(value: Any) -> Optional[datetime]:
    if is_missing(value):
        return None
    try:
        return datetime.strptime(str(value).strip(), COLLECTION_TS_FORMAT)
    except ValueError:
        return None


def expected_window_for(days: int) -> str:
    for label, lo, hi in WINDOW_BANDS:
        if lo <= days <= hi:
            return f"{label}({lo}-{hi})"
    return "OUT_OF_BAND"


def year_is_sane(d: date) -> bool:
    return MIN_SANE_YEAR <= d.year <= MAX_SANE_YEAR


# ---------------------------------------------------------------------------
# Result container
# ---------------------------------------------------------------------------

@dataclass
class RuleFindings:
    """Everything the rule pass discovered about one row, before the
    validator decides on a final status."""
    hard_errors: List[str] = field(default_factory=list)      # -> INVALID
    optional_notes: List[str] = field(default_factory=list)   # -> informational only
    is_non_price_availability: bool = False


# ---------------------------------------------------------------------------
# The rule pass
# ---------------------------------------------------------------------------

def run_all_rules(row: Dict[str, Any]) -> RuleFindings:
    """
    Run every deterministic validation rule against one raw observation row
    (a plain dict of column_name -> raw value, as read from the CSV).

    Returns a RuleFindings object listing every triggered hard-error code
    and every optional/informational note. Does not decide the final
    validation_status itself — see validator.py for that.
    """
    findings = RuleFindings()

    # --- Rule 1: observation_id exists ------------------------------------
    observation_id = row.get("observation_id")
    if is_missing(observation_id):
        findings.hard_errors.append("MISSING_OBSERVATION_ID")

    # --- Rules 2/3/4: route fields --------------------------------------
    # Grouped into a single MISSING_ROUTE code per the agreed edge-case
    # treatment (Case 1), since "the route" is the thing being validated,
    # not the two fields independently.
    origin = row.get("origin")
    destination = row.get("destination")
    origin_missing = is_missing(origin)
    destination_missing = is_missing(destination)
    if origin_missing or destination_missing:
        findings.hard_errors.append("MISSING_ROUTE")
    elif str(origin).strip().upper() == str(destination).strip().upper():
        findings.hard_errors.append("ORIGIN_EQUALS_DESTINATION")

    # --- Rule 5: carrier exists -------------------------------------------
    if is_missing(row.get("carrier")):
        findings.hard_errors.append("MISSING_CARRIER")

    # --- Rule 6: flight_number exists --------------------------------------
    if is_missing(row.get("flight_number")):
        findings.hard_errors.append("MISSING_FLIGHT_NUMBER")

    # --- Rule 7: travel_date exists + parses -------------------------------
    travel_date_raw = row.get("travel_date")
    travel_date_missing = is_missing(travel_date_raw)
    travel_date_parsed: Optional[date] = None
    if travel_date_missing:
        findings.hard_errors.append("MISSING_TRAVEL_DATE")
    else:
        travel_date_parsed = parse_date(travel_date_raw)
        if travel_date_parsed is None:
            findings.hard_errors.append("IMPOSSIBLE_DATE")
        elif not year_is_sane(travel_date_parsed):
            findings.hard_errors.append("IMPOSSIBLE_DATE")

    # --- Rule 8: collection_timestamp exists + parses ----------------------
    # Uses the exact code required by the agreed edge-case treatment (Case 2).
    collection_ts_raw = row.get("collection_timestamp")
    collection_ts_missing = is_missing(collection_ts_raw)
    collection_ts_parsed: Optional[datetime] = None
    if collection_ts_missing:
        findings.hard_errors.append("MISSING_COLLECTION_TIMESTAMP")
    else:
        collection_ts_parsed = parse_collection_timestamp(collection_ts_raw)
        if collection_ts_parsed is None:
            findings.hard_errors.append("IMPOSSIBLE_DATE")
        elif not year_is_sane(collection_ts_parsed.date()):
            findings.hard_errors.append("IMPOSSIBLE_DATE")

    # --- Rule 9: departure_time valid if provided --------------------------
    departure_time = row.get("departure_time")
    if not is_missing(departure_time):
        if not DEPARTURE_TIME_PATTERN.match(str(departure_time).strip()):
            findings.hard_errors.append("INVALID_DEPARTURE_TIME")

    # --- Rules 10/11/12/13: date-derived consistency -----------------------
    # Only attempted when both dates parsed successfully; otherwise the
    # MISSING_*/IMPOSSIBLE_DATE codes above already explain the problem.
    recomputed_days: Optional[int] = None
    if travel_date_parsed is not None and collection_ts_parsed is not None:
        recomputed_days = (travel_date_parsed - collection_ts_parsed.date()).days

        # Rule 10: travel_date must not be before collection date
        if recomputed_days < 0:
            findings.hard_errors.append("TRAVEL_DATE_BEFORE_COLLECTION")

        # Rule 11: stored advance_purchase_days must match the recomputed value
        stored_days_raw = row.get("advance_purchase_days")
        if not is_missing(stored_days_raw):
            try:
                stored_days = int(float(stored_days_raw))
                if stored_days != recomputed_days:
                    findings.hard_errors.append("ADVANCE_PURCHASE_DAYS_MISMATCH")
            except (ValueError, TypeError):
                findings.hard_errors.append("NON_NUMERIC_ADVANCE_PURCHASE_DAYS")
        # (if advance_purchase_days itself is missing, that's a schema gap;
        # not separately coded here since it is always derived/populated by
        # the generator — a production ingestion pipeline may want its own
        # MISSING_ADVANCE_PURCHASE_DAYS code.)

        # Rule 12: advance_purchase_days must be non-negative (checked on the
        # recomputed value, independent of whatever was stored)
        if recomputed_days < 0 and "TRAVEL_DATE_BEFORE_COLLECTION" not in findings.hard_errors:
            findings.hard_errors.append("NEGATIVE_ADVANCE_PURCHASE_DAYS")

        # Rule 13: stored advance_purchase_window must match the band implied
        # by the recomputed days
        stored_window = row.get("advance_purchase_window")
        if not is_missing(stored_window):
            expected_window = expected_window_for(recomputed_days)
            if str(stored_window).strip() != expected_window:
                findings.hard_errors.append("ADVANCE_PURCHASE_WINDOW_MISMATCH")

    # --- Rule 14: fare_class exists -----------------------------------------
    if is_missing(row.get("fare_class")):
        findings.hard_errors.append("MISSING_FARE_CLASS")

    # --- Rule 22: availability_status is one of the allowed values ---------
    availability_status = row.get("availability_status")
    availability_missing = is_missing(availability_status)
    if availability_missing:
        findings.hard_errors.append("MISSING_AVAILABILITY_STATUS")
    elif str(availability_status).strip() not in ALLOWED_AVAILABILITY_STATUSES:
        findings.hard_errors.append("INVALID_AVAILABILITY_STATUS")

    # --- Rules 15/16/17/18/19/20/23: fare fields ----------------------------
    base_fare_raw = row.get("base_fare")
    taxes_raw = row.get("taxes")
    fees_raw = row.get("fees")
    total_fare_raw = row.get("total_fare")

    base_fare_missing = is_missing(base_fare_raw)
    taxes_missing = is_missing(taxes_raw)
    fees_missing = is_missing(fees_raw)
    total_fare_missing = is_missing(total_fare_raw)

    base_fare_val = None
    if not base_fare_missing:
        base_fare_val = to_float(base_fare_raw)
        if base_fare_val is None:
            findings.hard_errors.append("NON_NUMERIC_BASE_FARE")
        elif base_fare_val < 0:
            # Exact code required by the agreed edge-case treatment (Case 8)
            findings.hard_errors.append("NEGATIVE_BASE_FARE")

    taxes_val = None
    if not taxes_missing:
        taxes_val = to_float(taxes_raw)
        if taxes_val is None:
            findings.hard_errors.append("NON_NUMERIC_TAXES")
        elif taxes_val < 0:
            findings.hard_errors.append("NEGATIVE_TAXES")

    fees_val = None
    if not fees_missing:
        fees_val = to_float(fees_raw)
        if fees_val is None:
            findings.hard_errors.append("NON_NUMERIC_FEES")
        elif fees_val < 0:
            findings.hard_errors.append("NEGATIVE_FEES")

    total_fare_val = None
    if not total_fare_missing:
        total_fare_val = to_float(total_fare_raw)
        if total_fare_val is None:
            findings.hard_errors.append("NON_NUMERIC_TOTAL_FARE")
        elif total_fare_val <= 0:
            findings.hard_errors.append("INVALID_TOTAL_FARE")

    # Rule 15: total_fare must exist when availability is Available.
    # A missing total_fare on a non-"Available" row is NOT an error here —
    # it is the expected shape of a sold-out / non-priced observation
    # (Case 7), handled below as NON_PRICE_AVAILABILITY rather than INVALID.
    is_available = (not availability_missing) and str(availability_status).strip() == "Available"
    if is_available and total_fare_missing:
        findings.hard_errors.append("MISSING_TOTAL_FARE")
    elif (not is_available) and total_fare_missing and not findings.hard_errors:
        # Only classify as non-price-availability if nothing else about the
        # row is already broken (identity fields, dates, etc. all fine).
        findings.is_non_price_availability = True
    elif (not is_available) and total_fare_missing:
        # Sold out AND some other structural problem exists — still flag the
        # non-price nature informationally, but the row is INVALID overall
        # because of the other problem(s).
        findings.is_non_price_availability = True

    # Rule 20: total_fare must not be less than its mandatory components,
    # when base_fare + taxes + fees are ALL present.
    if (
        total_fare_val is not None
        and base_fare_val is not None
        and taxes_val is not None
        and fees_val is not None
    ):
        expected_total = base_fare_val + taxes_val + fees_val
        if total_fare_val < expected_total - FARE_COMPONENT_TOLERANCE:
            findings.hard_errors.append("TOTAL_FARE_LESS_THAN_COMPONENTS")

    # Rules 4/5/6 (Cases 4/5/6): missing OPTIONAL sub-fields are fine and are
    # recorded as informational notes only — never hard errors.
    if base_fare_missing:
        findings.optional_notes.append("OPTIONAL_MISSING_BASE_FARE")
    if taxes_missing:
        findings.optional_notes.append("OPTIONAL_MISSING_TAXES")
    if fees_missing:
        findings.optional_notes.append("OPTIONAL_MISSING_FEES")

    # --- Rule 21: source exists ---------------------------------------------
    # Exact code required by the agreed edge-case treatment (Case 3).
    if is_missing(row.get("source")):
        findings.hard_errors.append("MISSING_SOURCE")

    return findings
