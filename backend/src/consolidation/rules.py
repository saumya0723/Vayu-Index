"""
VAYU INDEX — Phase 7: Source Consolidation Rules / Configuration
==================================================================

This module defines ONLY the consolidation identity keys, the collection-round
assignment rule, and the median definition used by the Phase 7 engine.

It deliberately does NOT:
- perform anomaly / price-plausibility detection (a later, separate stage)
- normalize fares, windows, or currencies (Phase 8, a later separate stage)
- aggregate to route level or apply route weights (a later, separate stage)
- compute the index (a later, separate stage)
- resolve route directionality (deferred, requires explicit approval)

Methodology reference: docs/source_consolidation_methodology.md (approved
2026-09-10). Every constant/rule below traces back to an explicit approved
rule in that document — nothing here is invented at implementation time.


APPROVED PRIMARY ESTIMATOR
--------------------------
Phase 7 primary estimator = flight-first, two-stage median: cross-source
median within each flight cell, followed by median across flight-level
representative fares within each economic product and collection round.

This is a MEDIAN-BASED SOURCE-CONSOLIDATION METHOD WITH A FLIGHT-FIRST
AGGREGATION HIERARCHY. It must NOT be described as equal-weighting of
sources.


TIME TOLERANCES — TWO DIFFERENT CONCEPTS, TWO DIFFERENT NUMBERS
---------------------------------------------------------------
  Phase 6 technical deduplication tolerance = 15 minutes
      Question: "are these the SAME capture of the SAME flight by the
      SAME source at the SAME fare?"  -> record identity.

  Phase 7 collection-round comparability tolerance = 30 minutes
      Question: "were these captures by DIFFERENT sources close enough to
      reflect the same market state?"  -> economic comparability.

These are distinct concepts. This module deliberately declares its own
ROUND_TOLERANCE_MINUTES and must NEVER import or reuse Phase 6's
TIME_TOLERANCE_MINUTES. A test asserts that the two values remain
independent.


PROTOTYPE CONFIGURATION NOTICE
------------------------------
ROUND_ANCHORS and EXPECTED_SOURCES below are PROTOTYPE CONFIGURATION
DERIVED FROM THE CURRENT SYNTHETIC COLLECTION SCHEDULE, NOT A FINALIZED
PRODUCTION SAMPLING SCHEDULE. The production scraping cadence may later
replace these configuration values without changing the Phase 7
methodology. They are declared (not inferred from the data at runtime) so
that round identity is reproducible and does not mutate as data grows.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, List, Optional, Sequence, Tuple

# Phase 6 helpers are imported READ-ONLY and reused so that Phase 7 uses the
# identical departure-time and fare canonicalization as Phase 6. Only these
# two pure helpers are imported. Phase 6's TIME_TOLERANCE_MINUTES is
# deliberately NOT imported (see the tolerance note above).
from ..deduplication.rules import (  # noqa: F401  (re-exported on purpose)
    normalize_departure_time,
    normalize_total_fare,
)


# ---------------------------------------------------------------------------
# Consolidation cell identity (economic product + collection round)
# ---------------------------------------------------------------------------

# APPROVED RULE — the economic identity, unchanged from Phase 1 / Phase 6.
# Route direction is used EXACTLY as stored: DEL-BOM is never reversed into
# BOM-DEL, and no route ids are created or altered here.
ECONOMIC_IDENTITY_FIELDS = (
    "origin",
    "destination",
    "travel_date",
    "fare_class",
    "advance_purchase_window",
)

# APPROVED RULE — the consolidation cell adds the collection round. `source`
# is deliberately NOT part of the key: it is the dimension being consolidated
# WITHIN a cell, and is preserved as diagnostics.
CONSOLIDATION_CELL_FIELDS = ECONOMIC_IDENTITY_FIELDS + ("collection_round_id",)

# APPROVED RULE — the flight cell reuses Phase 6's product-instance identity.
FLIGHT_INSTANCE_EXTRA_FIELDS = ("carrier", "flight_number", "departure_time")

# `advance_purchase_days` is METADATA ONLY and must never become a key.
METADATA_ONLY_FIELDS = ("advance_purchase_days",)


# ---------------------------------------------------------------------------
# Collection rounds (PROTOTYPE CONFIGURATION — see module docstring)
# ---------------------------------------------------------------------------

# PROTOTYPE CONFIGURATION, NOT A FINALIZED PRODUCTION SAMPLING SCHEDULE.
# Evidence: 768 of the 778 canonical observations land exactly on these three
# clock times across 2026-09-05/06/07, with all four sources present in every
# one of the nine resulting rounds.
ROUND_ANCHORS: Tuple[str, ...] = ("09:00", "14:30", "20:15")
ROUND_ANCHORS_ARE_PROTOTYPE_CONFIG = True
ROUND_ANCHORS_PROVENANCE = (
    "prototype configuration derived from the current synthetic collection "
    "schedule, not a finalized production sampling schedule"
)

# APPROVED RULE — Phase 7 collection-round comparability tolerance.
# Justification (all three must hold for the value to be defensible):
#   1. It cannot merge two rounds: the minimum gap between anchors is 330
#      minutes, so the collision threshold is 165 minutes. 30 is 5.5x below
#      it, making nearest-anchor assignment provably unique.
#   2. It covers a realistic multi-source crawl sweep.
#   3. It is empirically calibrated on the real data: it absorbs the two
#      near-anchor stragglers (09:20 = +20 min, 20:00 = -15 min) while
#      correctly leaving the genuinely distant edge cases (10:32-10:44,
#      18:47, 23:59) unaligned.
# It is deliberately DIFFERENT from Phase 6's 15-minute deduplication window.
ROUND_TOLERANCE_MINUTES = 30

# Parsed as a NAIVE LOCAL datetime, exactly as represented in the input,
# inheriting the Phase 6 rule. Phase 7 never infers, assigns, converts, or
# fabricates a timezone.
COLLECTION_TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M"
COLLECTION_TIMESTAMP_IS_NAIVE_LOCAL = True

ROUND_ID_PREFIX = "ROUND::"
UNALIGNED_ROUND_ID_PREFIX = "ROUND-UNALIGNED::"
UNRESOLVED_ROUND_ID_PREFIX = "ROUND-UNRESOLVED::"

ROUND_ALIGNMENT_ANCHORED = "ANCHORED"
ROUND_ALIGNMENT_UNALIGNED = "UNALIGNED"
ROUND_ALIGNMENT_UNRESOLVED = "UNRESOLVED"


# ---------------------------------------------------------------------------
# Cell / flight id namespaces
# ---------------------------------------------------------------------------

CONSOLIDATION_CELL_ID_PREFIX = "CELL::"
FLIGHT_CELL_ID_INFIX = "::FLT::"
MISSING_FIELD_MARKER = "<MISSING>"


# ---------------------------------------------------------------------------
# Source roster (PROTOTYPE CONFIGURATION — see module docstring)
# ---------------------------------------------------------------------------

# PROTOTYPE CONFIGURATION. Verified from the canonical dataset: exactly four
# distinct source labels, no blanks. `AirlineSite` is a single collapsed
# label, not per-carrier airline sites — which is one reason an
# airline-priority estimator was rejected.
EXPECTED_SOURCES: Tuple[str, ...] = ("AirlineSite", "Cleartrip", "Goibibo", "MMT")
EXPECTED_SOURCE_COUNT = len(EXPECTED_SOURCES)

SOURCE_COVERAGE_FULL = "FULL_COVERAGE"
SOURCE_COVERAGE_PARTIAL = "PARTIAL_COVERAGE"
SOURCE_COVERAGE_SINGLE = "SINGLE_SOURCE"
SOURCE_COVERAGE_NONE = "NO_PRICED_SOURCE"


# ---------------------------------------------------------------------------
# Availability
# ---------------------------------------------------------------------------

SOLD_OUT_STATUS = "Sold Out"
AVAILABLE_STATUS = "Available"


# ---------------------------------------------------------------------------
# Consolidation status vocabulary
# ---------------------------------------------------------------------------

STATUS_CONSOLIDATED = "CONSOLIDATED"
STATUS_NO_PRICE_ALL_SOLD_OUT = "NO_PRICE_ALL_SOLD_OUT"
STATUS_NO_PRICE_ALL_MISSING = "NO_PRICE_ALL_MISSING"
STATUS_NO_PRICE_NO_USABLE_FARE = "NO_PRICE_NO_USABLE_FARE"


# ---------------------------------------------------------------------------
# Observation participation vocabulary (every observation gets exactly one)
# ---------------------------------------------------------------------------

PARTICIPATION_PARTICIPATED = "PARTICIPATED"
PARTICIPATION_EXCLUDED_SOLD_OUT = "EXCLUDED_SOLD_OUT"
PARTICIPATION_EXCLUDED_MISSING_PRICE = "EXCLUDED_MISSING_PRICE"
PARTICIPATION_EXCLUDED_NO_ROUND = "EXCLUDED_NO_ROUND"
PARTICIPATION_EXCLUDED_MISSING_SOURCE = "EXCLUDED_MISSING_SOURCE"
PARTICIPATION_EXCLUDED_MISSING_IDENTITY = "EXCLUDED_MISSING_IDENTITY"

# Statuses whose observations still belong to a consolidation cell (they are
# excluded from the PRICE median but retained, counted, and reported).
CELL_MEMBER_PARTICIPATION_STATUSES = (
    PARTICIPATION_PARTICIPATED,
    PARTICIPATION_EXCLUDED_SOLD_OUT,
    PARTICIPATION_EXCLUDED_MISSING_PRICE,
)


# ---------------------------------------------------------------------------
# Money handling — Decimal throughout, never float
# ---------------------------------------------------------------------------

# APPROVED RULE — the derived consolidated statistic is retained to 2 decimal
# places. Raw observation amounts are NEVER modified, rescaled, or rounded.
MONEY_QUANTUM = Decimal("0.01")


class ConsolidationRuleError(ValueError):
    """Raised when a Phase 7 rule is asked to operate on impossible input."""


def is_missing(value: Any) -> bool:
    """True when a field carries no usable value.

    Treats None, NaN, the empty string and the literal text 'nan' as missing.
    A missing price is NEVER interpreted as a price of zero.
    """
    if value is None:
        return True
    if isinstance(value, float) and value != value:  # NaN
        return True
    text = str(value).strip()
    return text == "" or text.lower() == "nan"


def clean_str(value: Any) -> str:
    """Canonical string form of a field: stripped, missing -> ''."""
    if is_missing(value):
        return ""
    return str(value).strip()


def parse_money(value: Any) -> Optional[Decimal]:
    """Parse a fare into an exact Decimal.

    Returns None when the value is missing or non-numeric. Callers MUST treat
    None as "no usable price" and never as zero. No float ever appears in the
    monetary path.
    """
    if is_missing(value):
        return None
    try:
        return Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return None


def quantize_money(value: Decimal) -> Decimal:
    """Quantize a derived monetary statistic to 2 decimal places."""
    return value.quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)


def format_money(value: Optional[Decimal]) -> str:
    """Render a derived monetary statistic for output, or '' when absent."""
    if value is None:
        return ""
    return format(quantize_money(value), "f")


def midpoint_median(values: Sequence[Decimal]) -> Decimal:
    """APPROVED RULE — STANDARD MIDPOINT MEDIAN.

    For an odd count, the middle value. For an EVEN count:

        median = (lower_middle + upper_middle) / 2

    Examples (from the approved decision):
        [5300, 5500]             -> 5400
        [5000, 5200, 5600, 6000] -> 5400

    A lower-median rule was explicitly rejected because it would
    systematically select the lower middle value and introduce a downward
    tendency. `consolidated_fare` is a DERIVED STATISTIC, not a claim that a
    source actually quoted that exact amount, so a midpoint such as 5425 or
    11041.75 is acceptable and is retained to 2 decimal places.

    Computed in Decimal on an explicitly sorted copy, so the result is exact
    and independent of the order the values were supplied in.
    """
    if not values:
        raise ConsolidationRuleError("midpoint_median() requires at least one value")
    ordered: List[Decimal] = sorted(values)
    count = len(ordered)
    middle = count // 2
    if count % 2 == 1:
        return quantize_money(ordered[middle])
    return quantize_money((ordered[middle - 1] + ordered[middle]) / Decimal(2))


# ---------------------------------------------------------------------------
# Collection-round assignment
# ---------------------------------------------------------------------------


def parse_collection_timestamp(value: Any) -> Optional[datetime]:
    """Parse collection_timestamp as a NAIVE LOCAL datetime.

    Returns None when missing or unparseable. No timezone is ever inferred,
    assigned, converted, or fabricated.
    """
    if is_missing(value):
        return None
    text = str(value).strip()
    try:
        return datetime.strptime(text, COLLECTION_TIMESTAMP_FORMAT)
    except ValueError:
        pass
    # Tolerate a seconds component without inventing precision.
    try:
        return datetime.strptime(text, COLLECTION_TIMESTAMP_FORMAT + ":%S")
    except ValueError:
        return None


def assign_collection_round(value: Any, observation_id: str) -> Tuple[str, str, str]:
    """APPROVED RULE — nearest-anchor round assignment within +/-30 minutes.

    Returns ``(collection_round_id, round_alignment, round_anchor_timestamp)``.

    - An observation joins the anchor ON ITS OWN CALENDAR DATE that minimises
      |timestamp - anchor|, if that distance is <= ROUND_TOLERANCE_MINUTES
      (30 inclusive; 31 is outside).
    - Anything further than the tolerance from every anchor becomes its OWN
      unaligned singleton round. It is never merged and never dropped.
    - A missing or unparseable timestamp becomes an unresolved round: it is
      excluded from cross-source consolidation but retained in the
      observation map.

    Exact ties are impossible at a 30-minute tolerance against a 330-minute
    anchor gap, but the rule is defined anyway: the earlier anchor wins.
    """
    stamp = parse_collection_timestamp(value)
    if stamp is None:
        return (
            UNRESOLVED_ROUND_ID_PREFIX + clean_str(observation_id),
            ROUND_ALIGNMENT_UNRESOLVED,
            "",
        )

    best_delta: Optional[Decimal] = None
    best_anchor = ""
    for anchor in sorted(ROUND_ANCHORS):  # sorted -> earlier anchor wins ties
        hour_text, minute_text = anchor.split(":")
        anchor_stamp = stamp.replace(
            hour=int(hour_text), minute=int(minute_text), second=0, microsecond=0
        )
        delta_minutes = abs(Decimal((stamp - anchor_stamp).total_seconds())) / Decimal(60)
        if best_delta is None or delta_minutes < best_delta:
            best_delta = delta_minutes
            best_anchor = anchor

    if best_delta is not None and best_delta <= Decimal(ROUND_TOLERANCE_MINUTES):
        day = stamp.date().isoformat()
        return (
            "%s%sT%s" % (ROUND_ID_PREFIX, day, best_anchor),
            ROUND_ALIGNMENT_ANCHORED,
            "%s %s" % (day, best_anchor),
        )

    return (
        UNALIGNED_ROUND_ID_PREFIX + stamp.strftime(COLLECTION_TIMESTAMP_FORMAT),
        ROUND_ALIGNMENT_UNALIGNED,
        "",
    )


def source_coverage_label(participating_source_count: int) -> str:
    """APPROVED RULE — label source coverage; never impute a missing source.

    A single available source CAN form the consolidated value (the
    alternative is discarding real market information), but the result is
    explicitly labelled SINGLE_SOURCE so any consumer can filter on it.
    """
    if participating_source_count <= 0:
        return SOURCE_COVERAGE_NONE
    if participating_source_count == 1:
        return SOURCE_COVERAGE_SINGLE
    if participating_source_count >= EXPECTED_SOURCE_COUNT:
        return SOURCE_COVERAGE_FULL
    return SOURCE_COVERAGE_PARTIAL


def is_sold_out(value: Any) -> bool:
    """True when an availability_status marks the capture as sold out."""
    return clean_str(value).lower() == SOLD_OUT_STATUS.lower()
