"""
VAYU INDEX — Phase 6: Deduplication Rules / Configuration
============================================================

This module defines ONLY the identity keys, the technical-duplicate
decision, and the deterministic tie-break used to pick a canonical
record within a duplicate group.

It deliberately does NOT:
- perform anomaly / price-plausibility detection (a later, separate stage)
- consolidate across sources (a later, separate stage)
- normalize fares or currencies (a later, separate stage)
- compute the index (a later, separate stage)

Methodology reference: docs/deduplication_methodology.md (approved
2026-09-09). Every constant/rule below traces back to an explicit,
approved rule in that document — nothing here is invented at
implementation time.

APPROVED RULE — economic identity (route + product-class level, matches
the pre-existing `economic_signature` field's own construction, verified
by direct inspection of vayu_synthetic_observations.csv):
    (origin, destination, travel_date, fare_class, advance_purchase_window)

APPROVED RULE — product-instance identity (economic identity + the three
fields the existing economic_signature deliberately excludes):
    economic identity + (carrier, flight_number, normalized departure_time)

APPROVED RULE — technical duplicate requires ALL FIVE:
    1. same economic identity
    2. same product-instance identity
    3. same source
    4. same total_fare (exact)
    5. collection_timestamp difference <= TIME_TOLERANCE_MINUTES

capture_signature is NEVER used as the hard identity key (its exact
construction formula could not be confirmed — generate_synthetic_dataset.py
was not available for inspection). It is retained only as a secondary,
informational cross-check field (capture_signature_agreement).
"""

from __future__ import annotations

from typing import Any, Optional
import re

# ---------------------------------------------------------------------------
# Economic identity fields (route + product-class level)
# ---------------------------------------------------------------------------

ECONOMIC_IDENTITY_FIELDS = (
    "origin",
    "destination",
    "travel_date",
    "fare_class",
    "advance_purchase_window",
)

# ---------------------------------------------------------------------------
# Product-instance identity fields (economic identity + flight-level fields)
# ---------------------------------------------------------------------------

PRODUCT_INSTANCE_EXTRA_FIELDS = (
    "carrier",
    "flight_number",
    "departure_time",  # compared in its NORMALIZED form, see normalize_departure_time()
)

PRODUCT_INSTANCE_IDENTITY_FIELDS = ECONOMIC_IDENTITY_FIELDS + PRODUCT_INSTANCE_EXTRA_FIELDS

# ---------------------------------------------------------------------------
# Time tolerance
# ---------------------------------------------------------------------------

# APPROVED, justified against the real observed collection cadence in the
# synthetic dataset (fixed daily schedule 09:00 / 14:30 / 20:15, i.e.
# ~345 minutes apart). 15 minutes gives a >20x safety margin below that gap
# (so two genuinely separate scheduled scrapes are never merged) while
# comfortably covering realistic single-pass retry/pagination/clock-skew
# latency (the one deliberately-planted true-duplicate case, OBS00769/770,
# is 1 minute apart). MUST be recalibrated once real (non-synthetic)
# scraper cadence is known — this is not asserted as a universal constant.
TIME_TOLERANCE_MINUTES = 15

# ---------------------------------------------------------------------------
# Duplicate reason codes (audit field values)
# ---------------------------------------------------------------------------

REASON_RETAINED_UNIQUE = "RETAINED_UNIQUE"
REASON_RETAINED_CANONICAL_OF_DUPLICATE_GROUP = "RETAINED_CANONICAL_OF_DUPLICATE_GROUP"
REASON_TECHNICAL_DUPLICATE = "TECHNICAL_DUPLICATE"
REASON_GENUINE_REPRICE_NOT_DUPLICATE = "GENUINE_REPRICE_NOT_DUPLICATE"
REASON_DIFFERENT_PRODUCT_INSTANCE_NOT_DUPLICATE = "DIFFERENT_PRODUCT_INSTANCE_NOT_DUPLICATE"
REASON_DIFFERENT_SOURCE_NOT_DUPLICATE = "DIFFERENT_SOURCE_NOT_DUPLICATE"
REASON_EXCLUDED_MISSING_IDENTITY = "EXCLUDED_MISSING_IDENTITY"
REASON_EXCLUDED_UNUSABLE_PRICE = "EXCLUDED_UNUSABLE_PRICE"
REASON_SKIPPED_INVALID_BY_PHASE2 = "SKIPPED_INVALID_BY_PHASE2"
REASON_AMBIGUOUS_MISSING_TIMESTAMP = "AMBIGUOUS_MISSING_TIMESTAMP_POSSIBLE_DUPLICATE"
REASON_SOLD_OUT_TECHNICAL_DUPLICATE = "SOLD_OUT_TECHNICAL_DUPLICATE"

SOLD_OUT_STATUS = "Sold Out"
AVAILABLE_STATUS = "Available"


# ---------------------------------------------------------------------------
# departure_time normalization
# ---------------------------------------------------------------------------
# APPROVED RULE 14: normalize before exact comparison so "08:10", "08:10:00",
# and "08:10:00.000" are not treated as artificially different. Canonical
# form: zero-padded "HH:MM" (seconds/milliseconds truncated, not rounded —
# a real-world scrape is never sub-minute-precision-meaningful for a
# scheduled departure time).

_TIME_PATTERN = re.compile(
    r"^\s*([01]?\d|2[0-3]):([0-5]\d)(?::([0-5]\d)(?:\.\d+)?)?\s*$"
)


def normalize_departure_time(value: Any) -> Optional[str]:
    """
    Normalize a departure_time value to canonical 'HH:MM' form.

    Returns None if the value is missing or does not match a recognizable
    HH:MM[:SS[.ffffff]] pattern — callers must treat None as "cannot
    establish product-instance identity for this field" (i.e. this row
    is a missing-identity case for grouping purposes), not silently
    coerce it to some default time.
    """
    if value is None:
        return None
    text = str(value).strip()
    if text == "" or text.lower() == "nan":
        return None
    m = _TIME_PATTERN.match(text)
    if not m:
        return None
    hh, mm = m.group(1), m.group(2)
    return f"{int(hh):02d}:{mm}"


# ---------------------------------------------------------------------------
# collection_timestamp interpretation  (APPROVED)
# ---------------------------------------------------------------------------
# APPROVED DECISION: collection_timestamp values are compared as NAIVE LOCAL
# datetimes, exactly as represented in the Phase 2 input. Phase 6 does NOT
# infer, assign, convert, or fabricate any timezone. The Phase 2 file carries
# no timezone marker on any of its 783 rows (verified by direct inspection),
# so attaching one here would be invented information.
#
# Consequence, stated explicitly so it is never assumed away: if a future
# collection run ever mixes timezones without labelling them, the 15-minute
# tolerance would be applied to wall-clock strings that are not directly
# comparable. That is a data-contract problem to be fixed upstream, not
# something Phase 6 may paper over by guessing an offset.
#
# APPROVED DECISION: an empty or unparseable collection_timestamp must NEVER
# be treated as "within the 15-minute tolerance". Such a row is routed to the
# explicit missing-timestamp path instead (see dedup_engine.group_and_mark).

COLLECTION_TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M"
COLLECTION_TIMESTAMP_IS_NAIVE_LOCAL = True


# ---------------------------------------------------------------------------
# duplicate_group_id namespaces
# ---------------------------------------------------------------------------
# Group identifiers are derived from the CANONICAL observation_id only. They
# deliberately do NOT embed the bucket key: embedding a numeric fare in an
# identifier reintroduces float formatting (e.g. "5400.0") into an audit
# field, which conflicts with the requirement to preserve the input's integer
# fare formatting.

DUPLICATE_GROUP_ID_PREFIX = "DUPGRP-"
SINGLETON_GROUP_ID_PREFIX = "SINGLETON::"
UNGROUPED_GROUP_ID_PREFIX = "UNGROUPED::"
SKIPPED_GROUP_ID_PREFIX = "SKIPPED::"


# ---------------------------------------------------------------------------
# is_valid parsing (strict literal, never raw-string truthiness)
# ---------------------------------------------------------------------------

IS_VALID_TRUE_LITERAL = "True"
IS_VALID_FALSE_LITERAL = "False"


class IsValidParseError(ValueError):
    """Raised when an is_valid value is neither a real bool nor 'True'/'False'."""


def parse_is_valid(value: Any) -> bool:
    """
    Strictly interpret a Phase 2 `is_valid` value.

    APPROVED RULE: treat the literal booleans True/False and their exact CSV
    serializations "True"/"False" correctly, and NEVER fall back to raw-string
    truthiness. `bool("False")` is True in Python, so a truthiness-based read
    would silently invert the four INVALID rows into the grouping population.

    Anything unrecognized raises IsValidParseError rather than being silently
    coerced to False: an unreadable validation verdict is a data-contract
    failure that must surface loudly, not quietly shrink the grouping
    population and change the deduplication result.
    """
    if isinstance(value, bool):
        return value
    if value is None:
        raise IsValidParseError("is_valid is missing (None)")
    text = str(value).strip()
    if text == IS_VALID_TRUE_LITERAL:
        return True
    if text == IS_VALID_FALSE_LITERAL:
        return False
    raise IsValidParseError(
        "Unrecognized is_valid value %r — expected the literal True/False "
        "(bool) or the exact strings 'True'/'False'." % (value,)
    )


# ---------------------------------------------------------------------------
# total_fare normalization (comparison only — never rewrites the raw field)
# ---------------------------------------------------------------------------

def normalize_total_fare(value: Any) -> Optional[str]:
    """
    Normalize total_fare into a canonical STRING for exact comparison.

    APPROVED RULE: preserve the input's integer fare formatting. Every
    total_fare in the Phase 2 file is an integer with no decimal component
    (verified by direct inspection), so parsing through float and formatting
    back would turn "5400" into "5400.0" wherever the value is surfaced in an
    audit field. Decimal is used so that 5400, "5400", "5400.00" and 5400.0
    all compare equal while the canonical rendering stays "5400".

    Returns None when the value is missing or non-numeric — callers must treat
    None as "no usable price", never as a price of zero.
    """
    from decimal import Decimal, InvalidOperation

    if value is None:
        return None
    text = str(value).strip()
    if text == "" or text.lower() == "nan":
        return None
    try:
        number = Decimal(text)
    except (InvalidOperation, ValueError):
        return None
    if number == number.to_integral_value():
        return str(int(number))
    return format(number.normalize(), "f")
