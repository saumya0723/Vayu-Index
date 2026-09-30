"""
VAYU INDEX — Phase 2: Validation Engine Tests
================================================

Unit tests for src/validation. Each test builds a minimal row dict
representing one scenario and checks the resulting ValidationVerdict.

Run with:
    pytest tests/test_validation.py -v
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.validation import validate_row, VALID, INVALID, VALID_WITH_MISSING_OPTIONAL_FIELDS, NON_PRICE_AVAILABILITY


def base_row(**overrides):
    """A fully valid baseline row; tests override only the field(s) they
    care about, so each test stays focused on one scenario."""
    row = {
        "observation_id": "TEST001",
        "origin": "DEL",
        "destination": "BOM",
        "carrier": "6E",
        "flight_number": "6E-2341",
        "travel_date": "2026-09-20",
        "departure_time": "08:10",
        "collection_timestamp": "2026-09-05 10:32",
        "advance_purchase_days": "15",
        "advance_purchase_window": "T15(12-18)",
        "fare_class": "Economy Saver",
        "base_fare": "4200",
        "taxes": "1050",
        "fees": "150",
        "total_fare": "5400",
        "source": "AirlineSite",
        "availability_status": "Available",
    }
    row.update(overrides)
    return row


# ---------------------------------------------------------------------------
# 1. A clean valid observation
# ---------------------------------------------------------------------------

def test_valid_observation():
    verdict = validate_row(base_row())
    assert verdict.is_valid is True
    assert verdict.validation_status == VALID
    assert verdict.validation_reason == ""
    assert verdict.validation_errors == ""


# ---------------------------------------------------------------------------
# 2. Missing route
# ---------------------------------------------------------------------------

def test_missing_origin():
    verdict = validate_row(base_row(origin=""))
    assert verdict.is_valid is False
    assert verdict.validation_status == INVALID
    assert "MISSING_ROUTE" in verdict.validation_errors


def test_missing_destination():
    verdict = validate_row(base_row(destination=""))
    assert verdict.is_valid is False
    assert "MISSING_ROUTE" in verdict.validation_errors


def test_origin_equals_destination():
    verdict = validate_row(base_row(destination="DEL"))
    assert verdict.is_valid is False
    assert "ORIGIN_EQUALS_DESTINATION" in verdict.validation_errors


# ---------------------------------------------------------------------------
# 3. Missing collection timestamp
# ---------------------------------------------------------------------------

def test_missing_collection_timestamp():
    verdict = validate_row(base_row(collection_timestamp=""))
    assert verdict.is_valid is False
    assert verdict.validation_status == INVALID
    assert "MISSING_COLLECTION_TIMESTAMP" in verdict.validation_errors


# ---------------------------------------------------------------------------
# 4. Missing source
# ---------------------------------------------------------------------------

def test_missing_source():
    verdict = validate_row(base_row(source=""))
    assert verdict.is_valid is False
    assert verdict.validation_status == INVALID
    assert "MISSING_SOURCE" in verdict.validation_errors


# ---------------------------------------------------------------------------
# 5. Negative base fare
# ---------------------------------------------------------------------------

def test_negative_base_fare():
    verdict = validate_row(base_row(base_fare="-500", total_fare="700"))
    assert verdict.is_valid is False
    assert "NEGATIVE_BASE_FARE" in verdict.validation_errors


# ---------------------------------------------------------------------------
# 6. Zero / negative total fare
# ---------------------------------------------------------------------------

def test_zero_total_fare():
    verdict = validate_row(base_row(total_fare="0"))
    assert verdict.is_valid is False
    assert "INVALID_TOTAL_FARE" in verdict.validation_errors


def test_negative_total_fare():
    verdict = validate_row(base_row(total_fare="-100"))
    assert verdict.is_valid is False
    assert "INVALID_TOTAL_FARE" in verdict.validation_errors


# ---------------------------------------------------------------------------
# 7. Missing OPTIONAL fare sub-fields (total present) -> VALID, not rejected
# ---------------------------------------------------------------------------

def test_missing_base_fare_with_valid_total():
    verdict = validate_row(base_row(base_fare=""))
    assert verdict.is_valid is True
    assert verdict.validation_status == VALID_WITH_MISSING_OPTIONAL_FIELDS
    assert "OPTIONAL_MISSING_BASE_FARE" in verdict.validation_reason


def test_missing_taxes_with_valid_total():
    verdict = validate_row(base_row(taxes=""))
    assert verdict.is_valid is True
    assert verdict.validation_status == VALID_WITH_MISSING_OPTIONAL_FIELDS
    assert "OPTIONAL_MISSING_TAXES" in verdict.validation_reason


def test_missing_fees_with_valid_total():
    verdict = validate_row(base_row(fees=""))
    assert verdict.is_valid is True
    assert verdict.validation_status == VALID_WITH_MISSING_OPTIONAL_FIELDS
    assert "OPTIONAL_MISSING_FEES" in verdict.validation_reason


def test_missing_all_optional_subfields_still_valid():
    verdict = validate_row(base_row(base_fare="", taxes="", fees=""))
    assert verdict.is_valid is True
    assert verdict.validation_status == VALID_WITH_MISSING_OPTIONAL_FIELDS
    assert "OPTIONAL_MISSING_BASE_FARE" in verdict.validation_reason
    assert "OPTIONAL_MISSING_TAXES" in verdict.validation_reason
    assert "OPTIONAL_MISSING_FEES" in verdict.validation_reason


# ---------------------------------------------------------------------------
# 8. Sold-out observation
# ---------------------------------------------------------------------------

def test_sold_out_observation():
    verdict = validate_row(
        base_row(
            availability_status="Sold Out",
            base_fare="",
            taxes="",
            fees="",
            total_fare="",
        )
    )
    assert verdict.is_valid is True
    assert verdict.validation_status == NON_PRICE_AVAILABILITY


def test_available_with_missing_total_fare_is_invalid():
    """Contrast case: missing total_fare is only acceptable when NOT
    'Available'. If availability says Available but there's no price,
    that's a genuine problem, not a sold-out situation."""
    verdict = validate_row(base_row(total_fare=""))
    assert verdict.is_valid is False
    assert "MISSING_TOTAL_FARE" in verdict.validation_errors


# ---------------------------------------------------------------------------
# 9. High but valid fare — must NOT be rejected by validation
# ---------------------------------------------------------------------------

def test_high_fare_is_still_valid():
    verdict = validate_row(base_row(base_fare="12000", taxes="1900", fees="150", total_fare="14050"))
    assert verdict.is_valid is True
    assert verdict.validation_status == VALID


# ---------------------------------------------------------------------------
# 10. Invalid date
# ---------------------------------------------------------------------------

def test_invalid_travel_date_format():
    verdict = validate_row(base_row(travel_date="20-09-2026"))  # wrong format
    assert verdict.is_valid is False
    assert "IMPOSSIBLE_DATE" in verdict.validation_errors


def test_nonsense_travel_date():
    verdict = validate_row(base_row(travel_date="not-a-date"))
    assert verdict.is_valid is False
    assert "IMPOSSIBLE_DATE" in verdict.validation_errors


def test_travel_date_before_collection_date():
    verdict = validate_row(
        base_row(travel_date="2026-09-01", collection_timestamp="2026-09-05 10:32")
    )
    assert verdict.is_valid is False
    assert "TRAVEL_DATE_BEFORE_COLLECTION" in verdict.validation_errors


# ---------------------------------------------------------------------------
# 11. Invalid availability status
# ---------------------------------------------------------------------------

def test_invalid_availability_status():
    verdict = validate_row(base_row(availability_status="Waitlisted"))
    assert verdict.is_valid is False
    assert "INVALID_AVAILABILITY_STATUS" in verdict.validation_errors


def test_missing_availability_status():
    verdict = validate_row(base_row(availability_status=""))
    assert verdict.is_valid is False
    assert "MISSING_AVAILABILITY_STATUS" in verdict.validation_errors


# ---------------------------------------------------------------------------
# 12. Incorrect advance_purchase_days (stored value doesn't match dates)
# ---------------------------------------------------------------------------

def test_advance_purchase_days_mismatch():
    verdict = validate_row(base_row(advance_purchase_days="99"))
    assert verdict.is_valid is False
    assert "ADVANCE_PURCHASE_DAYS_MISMATCH" in verdict.validation_errors


def test_advance_purchase_window_mismatch():
    verdict = validate_row(base_row(advance_purchase_window="T30(25-35)"))
    assert verdict.is_valid is False
    assert "ADVANCE_PURCHASE_WINDOW_MISMATCH" in verdict.validation_errors


# ---------------------------------------------------------------------------
# Additional coverage: multiple simultaneous errors must ALL be preserved
# ---------------------------------------------------------------------------

def test_multiple_errors_are_all_preserved():
    verdict = validate_row(base_row(source="", total_fare=""))
    assert verdict.is_valid is False
    assert "MISSING_SOURCE" in verdict.validation_errors
    assert "MISSING_TOTAL_FARE" in verdict.validation_errors
    # both codes present, semicolon-joined, not just the first one
    assert len(verdict.validation_errors.split(";")) >= 2


def test_negative_taxes():
    verdict = validate_row(base_row(taxes="-50"))
    assert verdict.is_valid is False
    assert "NEGATIVE_TAXES" in verdict.validation_errors


def test_negative_fees():
    verdict = validate_row(base_row(fees="-10"))
    assert verdict.is_valid is False
    assert "NEGATIVE_FEES" in verdict.validation_errors


def test_non_numeric_total_fare():
    verdict = validate_row(base_row(total_fare="not-a-number"))
    assert verdict.is_valid is False
    assert "NON_NUMERIC_TOTAL_FARE" in verdict.validation_errors


def test_invalid_departure_time_format():
    verdict = validate_row(base_row(departure_time="25:99"))
    assert verdict.is_valid is False
    assert "INVALID_DEPARTURE_TIME" in verdict.validation_errors


def test_total_fare_less_than_components():
    verdict = validate_row(
        base_row(base_fare="4200", taxes="1050", fees="150", total_fare="1000")
    )
    assert verdict.is_valid is False
    assert "TOTAL_FARE_LESS_THAN_COMPONENTS" in verdict.validation_errors


def test_missing_flight_number():
    verdict = validate_row(base_row(flight_number=""))
    assert verdict.is_valid is False
    assert "MISSING_FLIGHT_NUMBER" in verdict.validation_errors


def test_missing_carrier():
    verdict = validate_row(base_row(carrier=""))
    assert verdict.is_valid is False
    assert "MISSING_CARRIER" in verdict.validation_errors


def test_missing_fare_class():
    verdict = validate_row(base_row(fare_class=""))
    assert verdict.is_valid is False
    assert "MISSING_FARE_CLASS" in verdict.validation_errors


def test_different_source_same_product_is_valid():
    """Two rows for the same flight/date/class from different sources
    should each independently validate as fine — validation has no
    opinion on source consolidation (a later stage)."""
    row_a = base_row(source="AirlineSite", total_fare="5400")
    row_b = base_row(source="MMT", total_fare="5450")
    verdict_a = validate_row(row_a)
    verdict_b = validate_row(row_b)
    assert verdict_a.is_valid is True
    assert verdict_b.is_valid is True
