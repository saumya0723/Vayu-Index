"""
VAYU INDEX — Phase 8: Normalization Rules
=========================================

GOVERNING PRINCIPLE (approved wording, do not paraphrase):
    Canonicalize representation. Never alter economic content. Never change
    group membership.

Phase 8 sits between Phase 7 (source consolidation) and Phase 9 (anomaly
detection). It makes economically comparable observations REPRESENTATIONALLY
consistent. It performs no anomaly detection, removes no outliers, deletes no
observations, calculates no index, performs no route aggregation, never
reverses a route, never re-consolidates and never re-deduplicates.

HONEST CHARACTERISATION OF THE CURRENT CORPUS:
    On the verified Phase 7 corpus, Phase 8 is overwhelmingly a NO-OP
    VERIFICATION LAYER, not a transformation layer. Every categorical field is
    already canonical (measured: zero whitespace fixes, zero case collisions
    across fare_class, source, carrier, advance_purchase_window, origin and
    destination), all dates and times are format-uniform, and the fare
    components reconcile exactly on every complete row. The value delivered
    here is CONTRACT ENFORCEMENT, an AUDIT RECORD, and LOUD FLAGGING of unknown
    values — not data change.

ALIAS POLICY (explicitly approved):
    The alias maps are EMPTY BY APPROVAL. No alias may be invented. A wrong
    alias map is more dangerous than no alias map, because it silently merges
    genuinely different fare products or economically distinct sources. New
    aliases require explicit written approval.

UNKNOWN VALUE POLICY (explicitly approved):
    FLAG AND CONTINUE. An unrecognised categorical value preserves its original
    text, sets the corresponding *_is_known flag to False, appends a
    normalization flag, and DOES NOT abort the run. A future unknown fare class
    or source must never take down the pipeline.

CURRENCY POLICY (explicitly approved):
    currency is DECLARED, not inferred. No currency column exists anywhere
    upstream. There is no FX table, no exchange-rate logic and no conversion
    code path in this module or anywhere in Phase 8.

COUPLING RULES:
    - normalize_departure_time is REUSED from Phase 6, never re-implemented.
    - Phase 8 must NEVER import the Phase 6 duplicate-time tolerance (15 min)
      or the Phase 7 round-assignment tolerance (30 min). Those tolerances
      belong to their own phases and carry no meaning here. Enforced by test,
      including a check that their identifiers never appear in this source.
    - Phase 8 imports from Phase 6/7/2 READ-ONLY and modifies nothing.
"""

from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Dict, List, Optional, Sequence, Tuple

from ..consolidation.rules import (
    ROUND_ALIGNMENT_ANCHORED,
    ROUND_ID_PREFIX,
    UNALIGNED_ROUND_ID_PREFIX,
    UNRESOLVED_ROUND_ID_PREFIX,
)
from ..deduplication.rules import normalize_departure_time
from ..validation.rules import FARE_COMPONENT_TOLERANCE


class NormalizationRuleError(ValueError):
    """Programming errors only. Unknown DATA values never raise (flag and continue)."""


PHASE8_SCHEMA_VERSION = "phase8-v1"

# --------------------------------------------------------------------------
# Currency — declared, never inferred, never converted
# --------------------------------------------------------------------------
CURRENCY_CODE = "INR"
CURRENCY_SOURCE = "DECLARED_PROTOTYPE_CONSTANT"
FX_CONVERSION_SUPPORTED = False

# --------------------------------------------------------------------------
# Money
# --------------------------------------------------------------------------
MONEY_QUANTUM = Decimal("0.01")
MONEY_ROUNDING = ROUND_HALF_UP
FARE_COMPONENT_TOLERANCE_DECIMAL = Decimal(str(FARE_COMPONENT_TOLERANCE))

# --------------------------------------------------------------------------
# Frozen known value sets (verified against the real Phase 7 corpus)
# --------------------------------------------------------------------------
KNOWN_FARE_CLASSES = ("Economy Flexi", "Economy Saver", "Economy Standard")
KNOWN_SOURCES = ("AirlineSite", "Cleartrip", "Goibibo", "MMT")
KNOWN_CARRIERS = ("6E", "AI", "QP", "SG", "UK")
KNOWN_ADVANCE_PURCHASE_WINDOWS = (
    "T1(0-2)",
    "T7(5-9)",
    "T15(12-18)",
    "T30(25-35)",
    "T45(40-50)",
)

# --------------------------------------------------------------------------
# Alias maps — EMPTY BY EXPLICIT APPROVAL. Do not populate without sign-off.
# --------------------------------------------------------------------------
FARE_CLASS_ALIASES: Dict[str, str] = {}
SOURCE_ALIASES: Dict[str, str] = {}
CARRIER_ALIASES: Dict[str, str] = {}
ALIAS_MAPS_EMPTY_BY_APPROVAL = True

# --------------------------------------------------------------------------
# fare_class_tier_rank — DERIVED METADATA ONLY.
# Hard constraint: must never enter economic identity, consolidation keys,
# product keys, or any Phase 9 peer-group key. Enforced by test.
# --------------------------------------------------------------------------
FARE_CLASS_TIER_RANK: Dict[str, int] = {
    "Economy Saver": 1,
    "Economy Standard": 2,
    "Economy Flexi": 3,
}
FARE_CLASS_TIER_RANK_IS_IDENTITY_FIELD = False

# --------------------------------------------------------------------------
# Price state — four mutually exclusive values
# --------------------------------------------------------------------------
PRICE_STATE_PRICED = "PRICED"
PRICE_STATE_SOLD_OUT = "SOLD_OUT"
PRICE_STATE_MISSING_PRICE = "MISSING_PRICE"
PRICE_STATE_NO_PRICE_CELL = "NO_PRICE_CELL"
PRICE_STATES = (
    PRICE_STATE_PRICED,
    PRICE_STATE_SOLD_OUT,
    PRICE_STATE_MISSING_PRICE,
    PRICE_STATE_NO_PRICE_CELL,
)

SOLD_OUT_STATUS = "Sold Out"
AVAILABLE_STATUS = "Available"
CONSOLIDATION_STATUS_CONSOLIDATED = "CONSOLIDATED"

# --------------------------------------------------------------------------
# Formats. collection_timestamp is NAIVE LOCAL. No timezone is ever inferred,
# attached, or fabricated.
# --------------------------------------------------------------------------
TRAVEL_DATE_FORMAT = "%Y-%m-%d"
COLLECTION_TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M"
COLLECTION_TIMESTAMP_ISO_FORMAT = "%Y-%m-%dT%H:%M:%S"
ROUND_SORT_KEY_FORMAT = "%Y-%m-%d %H:%M"
COLLECTION_TIMESTAMP_IS_NAIVE_LOCAL = True
TIMEZONE_INFERENCE_PERFORMED = False

_TIMESTAMP_INPUT_FORMATS = (
    "%Y-%m-%d %H:%M",
    "%Y-%m-%dT%H:%M",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S",
)

_WHITESPACE_RE = re.compile(r"\s+")

# --------------------------------------------------------------------------
# Action codes for the normalization report, grain = (entity_id, field, action)
# --------------------------------------------------------------------------
ACTION_TRIM_WHITESPACE = "TRIM_WHITESPACE"
ACTION_COLLAPSE_WHITESPACE = "COLLAPSE_INTERNAL_WHITESPACE"
ACTION_CASE_NORMALIZED = "CASE_NORMALIZED"
ACTION_UPPERCASE = "UPPERCASE"
ACTION_ALIAS_APPLIED = "ALIAS_APPLIED"
ACTION_MONEY_QUANTIZED = "MONEY_QUANTIZED"
ACTION_UNKNOWN_VALUE_FLAGGED = "UNKNOWN_VALUE_FLAGGED"
ACTION_INVALID_FORMAT_FLAGGED = "INVALID_FORMAT_FLAGGED"
ACTION_MISSING_VALUE_FLAGGED = "MISSING_VALUE_FLAGGED"

# --------------------------------------------------------------------------
# Normalization flags (pipe-delimited, sorted, deterministic)
# --------------------------------------------------------------------------
FLAG_UNKNOWN_FARE_CLASS = "UNKNOWN_FARE_CLASS"
FLAG_UNKNOWN_SOURCE = "UNKNOWN_SOURCE"
FLAG_UNKNOWN_CARRIER = "UNKNOWN_CARRIER"
FLAG_UNKNOWN_ADVANCE_PURCHASE_WINDOW = "UNKNOWN_ADVANCE_PURCHASE_WINDOW"
FLAG_MISSING_FARE_CLASS = "MISSING_FARE_CLASS"
FLAG_MISSING_SOURCE = "MISSING_SOURCE"
FLAG_MISSING_CARRIER = "MISSING_CARRIER"
FLAG_MISSING_ORIGIN = "MISSING_ORIGIN"
FLAG_MISSING_DESTINATION = "MISSING_DESTINATION"
FLAG_INVALID_TRAVEL_DATE = "INVALID_TRAVEL_DATE_FORMAT"
FLAG_MISSING_COLLECTION_TIMESTAMP = "MISSING_COLLECTION_TIMESTAMP"
FLAG_UNPARSEABLE_COLLECTION_TIMESTAMP = "UNPARSEABLE_COLLECTION_TIMESTAMP"
FLAG_INVALID_DEPARTURE_TIME = "INVALID_DEPARTURE_TIME"
FLAG_MISSING_ROUND_SORT_KEY = "MISSING_ROUND_SORT_KEY"
FLAG_UNPARSEABLE_MONETARY_VALUE = "UNPARSEABLE_MONETARY_VALUE"
FLAG_FARE_DECOMPOSITION_INCOMPLETE = "FARE_DECOMPOSITION_INCOMPLETE"
FLAG_FARE_COMPONENTS_MISMATCH = "FARE_COMPONENTS_MISMATCH"
FLAG_MISSING_PRICE = "MISSING_PRICE"

ROUND_SORT_KEY_SOURCE_ANCHOR = "ANCHOR_TIMESTAMP"
ROUND_SORT_KEY_SOURCE_ROUND_ID = "ROUND_ID"
ROUND_SORT_KEY_SOURCE_UNRESOLVED = "UNRESOLVED"


# ==========================================================================
# Primitive helpers
# ==========================================================================
def is_missing(value) -> bool:
    """True when a value is absent or blank. Never treats 0 as missing."""
    return value is None or str(value).strip() == ""


def clean_str(value) -> str:
    """Trim and collapse internal whitespace. Pure representation change."""
    if value is None:
        return ""
    return _WHITESPACE_RE.sub(" ", str(value)).strip()


def quantize_money(amount: Decimal) -> Decimal:
    return amount.quantize(MONEY_QUANTUM, rounding=MONEY_ROUNDING)


def format_money(amount: Optional[Decimal]) -> str:
    if amount is None:
        return ""
    return str(quantize_money(amount))


def parse_money(value) -> Optional[Decimal]:
    """Parse a monetary string to Decimal.

    Whitespace is stripped. Nothing else is stripped or substituted: currency
    symbols and thousands separators are NOT invented away, because doing so
    would silently accept malformed economic input. Unparseable input returns
    None and is flagged; Phase 9 R02 owns the anomaly decision.
    """
    if is_missing(value):
        return None
    try:
        return Decimal(str(value).strip())
    except (InvalidOperation, ValueError, ArithmeticError):
        return None


def normalize_money(value) -> Tuple[Optional[Decimal], str, List[str]]:
    """Return (decimal_or_none, canonical_2dp_string, actions)."""
    actions: List[str] = []
    if is_missing(value):
        return None, "", actions
    parsed = parse_money(value)
    if parsed is None:
        actions.append(ACTION_INVALID_FORMAT_FLAGGED)
        return None, "", actions
    canonical = format_money(parsed)
    if canonical != str(value).strip():
        actions.append(ACTION_MONEY_QUANTIZED)
    return quantize_money(parsed), canonical, actions


# ==========================================================================
# Categorical canonicalisation
# ==========================================================================
def canonicalize_categorical(
    value,
    known_values: Sequence[str],
    aliases: Optional[Dict[str, str]] = None,
) -> Tuple[str, bool, List[str]]:
    """Canonicalise one categorical value.

    Order of operations:
      1. trim + collapse internal whitespace
      2. apply an approved alias, if any (the maps are empty by approval)
      3. exact match against the frozen known set
      4. case-insensitive match against the frozen known set -> known casing
      5. otherwise: keep the cleaned original and mark it unknown

    Step 4 is CASE NORMALISATION, not aliasing. It never merges two distinct
    known values, because the known sets contain no case-insensitive
    collisions (verified).

    Returns (canonical_value, is_known, actions).
    """
    original = "" if value is None else str(value)
    actions: List[str] = []

    cleaned = clean_str(original)
    if cleaned != original:
        if original.strip() != original:
            actions.append(ACTION_TRIM_WHITESPACE)
        if _WHITESPACE_RE.sub(" ", original.strip()) != original.strip():
            actions.append(ACTION_COLLAPSE_WHITESPACE)

    if cleaned == "":
        return "", False, actions

    canonical = cleaned
    if aliases and canonical in aliases:
        canonical = aliases[canonical]
        actions.append(ACTION_ALIAS_APPLIED)

    if canonical in known_values:
        return canonical, True, actions

    lowered = canonical.casefold()
    for candidate in known_values:
        if candidate.casefold() == lowered:
            actions.append(ACTION_CASE_NORMALIZED)
            return candidate, True, actions

    actions.append(ACTION_UNKNOWN_VALUE_FLAGGED)
    return canonical, False, actions


def canonicalize_airport(value) -> Tuple[str, List[str]]:
    """Uppercase IATA-style code. DIRECTION IS NEVER CHANGED."""
    original = "" if value is None else str(value)
    actions: List[str] = []
    cleaned = clean_str(original)
    if cleaned != original:
        actions.append(ACTION_TRIM_WHITESPACE)
    upper = cleaned.upper()
    if upper != cleaned:
        actions.append(ACTION_UPPERCASE)
    return upper, actions


def canonicalize_flight_number(value) -> Tuple[str, List[str]]:
    original = "" if value is None else str(value)
    actions: List[str] = []
    cleaned = clean_str(original)
    if cleaned != original:
        actions.append(ACTION_TRIM_WHITESPACE)
    upper = cleaned.upper()
    if upper != cleaned:
        actions.append(ACTION_UPPERCASE)
    return upper, actions


def fare_class_tier_rank(fare_class: str) -> str:
    """Derived metadata only. Returns '' for unknown classes."""
    rank = FARE_CLASS_TIER_RANK.get(clean_str(fare_class))
    return "" if rank is None else str(rank)


# ==========================================================================
# Date / time canonicalisation — no shifting, no timezone fabrication
# ==========================================================================
def normalize_travel_date(value) -> Tuple[str, bool, List[str]]:
    """Validate and canonicalise a travel date. NEVER shifts a date."""
    original = "" if value is None else str(value)
    actions: List[str] = []
    cleaned = clean_str(original)
    if cleaned != original:
        actions.append(ACTION_TRIM_WHITESPACE)
    if cleaned == "":
        return "", False, actions
    try:
        parsed = datetime.strptime(cleaned, TRAVEL_DATE_FORMAT)
    except ValueError:
        actions.append(ACTION_INVALID_FORMAT_FLAGGED)
        return cleaned, False, actions
    return parsed.strftime(TRAVEL_DATE_FORMAT), True, actions


def parse_naive_timestamp(value) -> Optional[datetime]:
    """Parse a naive local timestamp. No timezone is ever attached."""
    cleaned = clean_str(value)
    if cleaned == "":
        return None
    for fmt in _TIMESTAMP_INPUT_FORMATS:
        try:
            return datetime.strptime(cleaned, fmt)
        except ValueError:
            continue
    return None


def collection_timestamp_iso(value) -> Tuple[str, bool, List[str]]:
    """Canonical ISO-like REPRESENTATION of a naive local timestamp.

    Carries no UTC offset and no timezone name, because none exists in the
    source data. This never replaces the original collection_timestamp.
    """
    actions: List[str] = []
    if is_missing(value):
        return "", False, actions
    parsed = parse_naive_timestamp(value)
    if parsed is None:
        actions.append(ACTION_INVALID_FORMAT_FLAGGED)
        return "", False, actions
    return parsed.strftime(COLLECTION_TIMESTAMP_ISO_FORMAT), True, actions


def derive_round_sort_key(round_anchor_timestamp, collection_round_id) -> Tuple[str, str]:
    """Chronologically sortable key for a collection round.

    THIS IS THE MOST IMPORTANT DERIVED COLUMN IN PHASE 8.

    Naive lexical ordering of collection_round_id is chronologically WRONG,
    because '-' (0x2D) sorts before ':' (0x3A). Every 'ROUND-UNALIGNED::...'
    id therefore sorts BEFORE every 'ROUND::...' id regardless of the instant
    it actually represents: 'ROUND-UNALIGNED::2026-09-07 23:59' lands ahead of
    'ROUND::2026-09-05T09:00'. Ordering a price series that way manufactures
    entirely fictitious movements out of correctly-priced data. Phase 9's
    temporal rules must order rounds by this key and never by the raw round id.

    Returns (sort_key, provenance).
    """
    anchor = clean_str(round_anchor_timestamp)
    if anchor:
        parsed = parse_naive_timestamp(anchor)
        if parsed is not None:
            return parsed.strftime(ROUND_SORT_KEY_FORMAT), ROUND_SORT_KEY_SOURCE_ANCHOR

    round_id = clean_str(collection_round_id)
    for prefix in (
        UNALIGNED_ROUND_ID_PREFIX,
        UNRESOLVED_ROUND_ID_PREFIX,
        ROUND_ID_PREFIX,
    ):
        if round_id.startswith(prefix):
            parsed = parse_naive_timestamp(round_id[len(prefix):])
            if parsed is not None:
                return (
                    parsed.strftime(ROUND_SORT_KEY_FORMAT),
                    ROUND_SORT_KEY_SOURCE_ROUND_ID,
                )
            break

    return "", ROUND_SORT_KEY_SOURCE_UNRESOLVED


def round_sort_tuple(round_sort_key: str, tiebreaker: str = "") -> Tuple[int, str, str]:
    """Deterministic sort tuple. Rows with no resolvable key sort LAST."""
    present = 0 if clean_str(round_sort_key) else 1
    return (present, clean_str(round_sort_key), tiebreaker)


def is_anchored(round_alignment) -> bool:
    return clean_str(round_alignment) == ROUND_ALIGNMENT_ANCHORED


# ==========================================================================
# Availability / price state
# ==========================================================================
def derive_cell_price_state(consolidation_status, consolidated_fare) -> str:
    if clean_str(consolidation_status) != CONSOLIDATION_STATUS_CONSOLIDATED:
        return PRICE_STATE_NO_PRICE_CELL
    if is_missing(consolidated_fare):
        return PRICE_STATE_NO_PRICE_CELL
    return PRICE_STATE_PRICED


def derive_observation_price_state(availability_status, total_fare) -> str:
    if clean_str(availability_status) == SOLD_OUT_STATUS:
        return PRICE_STATE_SOLD_OUT
    if is_missing(total_fare) or parse_money(total_fare) is None:
        return PRICE_STATE_MISSING_PRICE
    return PRICE_STATE_PRICED


def derive_flight_cell_price_state(
    flight_representative_fare,
    flight_sold_out_observation_count,
    flight_priced_observation_count,
) -> str:
    if not is_missing(flight_representative_fare):
        return PRICE_STATE_PRICED
    sold_out = clean_str(flight_sold_out_observation_count)
    priced = clean_str(flight_priced_observation_count)
    if priced in ("", "0") and sold_out not in ("", "0"):
        return PRICE_STATE_SOLD_OUT
    return PRICE_STATE_MISSING_PRICE


# ==========================================================================
# Fare decomposition — verified, NEVER reconstructed
# ==========================================================================
def fare_decomposition_state(base_fare, taxes, fees, total_fare) -> Tuple[str, str, List[str]]:
    """Return (complete, reconciles, flags).

    Missing components are NEVER reconstructed from the total, and the total is
    NEVER reconstructed from the components. When the decomposition is
    incomplete, reconciliation is not evaluable and returns '' rather than
    False, because 'could not check' is not the same as 'failed the check'.
    """
    flags: List[str] = []
    parts = [parse_money(base_fare), parse_money(taxes), parse_money(fees)]
    total = parse_money(total_fare)

    complete = all(part is not None for part in parts) and total is not None
    if not complete:
        flags.append(FLAG_FARE_DECOMPOSITION_INCOMPLETE)
        return "False", "", flags

    difference = abs(parts[0] + parts[1] + parts[2] - total)
    if difference > FARE_COMPONENT_TOLERANCE_DECIMAL:
        flags.append(FLAG_FARE_COMPONENTS_MISMATCH)
        return "True", "False", flags
    return "True", "True", flags


def join_flags(flags: Sequence[str]) -> str:
    """Deterministic, de-duplicated, sorted, pipe-delimited flag string."""
    return "|".join(sorted(set(flag for flag in flags if flag)))


__all__ = [name for name in dir() if not name.startswith("_")]
