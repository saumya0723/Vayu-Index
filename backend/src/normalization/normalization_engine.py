"""
VAYU INDEX — Phase 8: Normalization Engine
===========================================

Pipeline position:

    PHASE 7 OUTPUTS
        outputs/consolidated_airfare_observations.csv   (393 cells)
        outputs/phase7_flight_cell_report.csv           (571 flight cells)
        outputs/phase7_observation_map.csv              (778 observations)
        outputs/canonical_airfare_observations.csv      (778, joined for the
                                                         fare decomposition)
        -> PHASE 8 NORMALIZATION
        -> outputs/normalized_airfare_observations.csv  (393) PRIMARY
        -> outputs/normalized_observation_map.csv       (778) AUDIT/LINEAGE
        -> outputs/phase8_flight_cell_normalized.csv    (571) DIAGNOSTIC
        -> outputs/phase8_normalization_report.csv      (var) DIAGNOSTIC

TWO-TIER CANONICALISATION MODEL (important, deliberate):

    CELL LEVEL (consolidated + flight cells)
        Phase 7 identity fields are VERIFIED, not rewritten in place. The
        canonical form is emitted into a NEW *_canonical column and any
        deviation is flagged. The original columns are left byte-identical
        because consolidation_cell_id and flight_cell_id are built FROM those
        values — rewriting them in place would desynchronise every cell key and
        silently break lineage back to Phase 7.

    OBSERVATION LEVEL (observation map)
        The canonical form is emitted into a NEW *_canonical column and the
        original is preserved alongside it, so lineage is complete in both
        directions.

    In both tiers the rule is identical: ADD the canonical representation,
    never destroy the original.

ROW-COUNT INVARIANTS (enforced here and re-checked by scripts/verify_phase8.py):
    consolidated  393 in -> 393 out
    flight cells  571 in -> 571 out
    observations  778 in -> 778 out
    Phase 8 is row-count preserving BY CONSTRUCTION. It cannot drop, merge or
    create a row: every output row is produced from exactly one input row.

WHAT THIS MODULE NEVER DOES:
    no anomaly detection, no outlier removal, no deletion, no index
    calculation, no route aggregation, no route reversal, no re-consolidation,
    no re-deduplication, no imputation, no reconstruction of missing fare
    components, no FX conversion, no basket membership annotation, no live
    scraping, no Amadeus, no API, no dashboard.

DETERMINISM:
    The engine is a pure function of the input field values. Output row order
    is produced by an explicit semantic sort (never by input order, and never
    by lexical collection_round_id — see rules.derive_round_sort_key). Running
    twice on the same input yields byte-identical files. Shuffling the input
    rows yields byte-identical files.

CODE QUALITY GUARD (mandated):
    pandas rows are ALWAYS read with explicit column indexing, row["name"].
    Dotted attribute access on a row object is banned throughout Phase 8: for
    column names such as prod, min, max, count or size it silently resolves to
    a pandas Series METHOD instead of the column value, which fails silently
    rather than raising. Enforced by test.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

import pandas as pd

from . import rules as R


# ==========================================================================
# Input contracts — exact Phase 7 schemas (verified, do not re-guess)
# ==========================================================================
PHASE7_CONSOLIDATED_COLUMNS: Tuple[str, ...] = (
    "consolidation_cell_id", "origin", "destination", "travel_date", "fare_class",
    "advance_purchase_window", "collection_round_id", "round_anchor_timestamp",
    "round_alignment", "round_time_spread_minutes", "consolidated_fare",
    "consolidation_status", "consolidated_fare_is_observed_value",
    "participating_source_count", "participating_sources", "expected_source_count",
    "source_coverage", "source_coverage_ratio", "missing_sources",
    "flight_instance_count", "priced_flight_instance_count",
    "flight_representative_fares", "observation_count",
    "participating_observation_count", "contributing_observation_ids",
    "sold_out_observation_count", "missing_price_observation_count",
    "min_participating_fare", "max_participating_fare", "source_level_fares",
    "min_source_fare", "max_source_fare", "alt_source_first_fare",
    "max_flight_source_spread", "median_flight_source_spread", "cross_flight_spread",
)

PHASE7_FLIGHT_CELL_COLUMNS: Tuple[str, ...] = (
    "flight_cell_id", "consolidation_cell_id", "origin", "destination",
    "travel_date", "fare_class", "advance_purchase_window", "collection_round_id",
    "carrier", "flight_number", "departure_time_normalized",
    "flight_representative_fare", "flight_source_count", "flight_sources",
    "flight_source_level_fares", "flight_min_fare", "flight_max_fare",
    "flight_source_spread", "flight_source_relative_spread",
    "flight_observation_count", "flight_priced_observation_count",
    "flight_sold_out_observation_count", "flight_missing_price_observation_count",
    "flight_observation_ids",
)

PHASE7_OBSERVATION_MAP_COLUMNS: Tuple[str, ...] = (
    "observation_id", "source", "total_fare", "availability_status",
    "collection_timestamp", "collection_round_id", "round_alignment",
    "round_anchor_timestamp", "origin", "destination", "travel_date",
    "fare_class", "advance_purchase_window", "carrier", "flight_number",
    "departure_time_normalized", "flight_cell_id", "flight_representative_fare",
    "consolidation_cell_id", "consolidated_fare", "participation_status",
)

# Columns pulled from the Phase 6 canonical output purely for lineage. The
# Phase 7 observation map does not carry the fare decomposition.
CANONICAL_JOIN_COLUMNS: Tuple[str, ...] = (
    "observation_id", "base_fare", "taxes", "fees", "departure_time",
    "advance_purchase_days",
)


# ==========================================================================
# Output contracts
# ==========================================================================
NORMALIZED_CELL_NEW_COLUMNS: Tuple[str, ...] = (
    "origin_canonical", "destination_canonical", "travel_date_canonical",
    "fare_class_canonical", "fare_class_is_known", "fare_class_tier_rank",
    "advance_purchase_window_is_known", "consolidated_fare_normalized",
    "price_state", "round_sort_key", "round_sort_key_source",
    "currency", "currency_source", "normalization_flags", "phase8_schema_version",
)
NORMALIZED_CELL_COLUMNS: Tuple[str, ...] = (
    PHASE7_CONSOLIDATED_COLUMNS + NORMALIZED_CELL_NEW_COLUMNS
)

NORMALIZED_FLIGHT_CELL_NEW_COLUMNS: Tuple[str, ...] = (
    "origin_canonical", "destination_canonical", "travel_date_canonical",
    "fare_class_canonical", "fare_class_is_known", "fare_class_tier_rank",
    "advance_purchase_window_is_known", "carrier_canonical", "carrier_is_known",
    "flight_number_canonical", "departure_time_canonical",
    "flight_representative_fare_normalized", "price_state", "round_sort_key",
    "currency", "currency_source", "normalization_flags", "phase8_schema_version",
)
NORMALIZED_FLIGHT_CELL_COLUMNS: Tuple[str, ...] = (
    PHASE7_FLIGHT_CELL_COLUMNS + NORMALIZED_FLIGHT_CELL_NEW_COLUMNS
)

NORMALIZED_OBSERVATION_NEW_COLUMNS: Tuple[str, ...] = (
    "origin_canonical", "destination_canonical", "travel_date_canonical",
    "fare_class_canonical", "fare_class_is_known", "fare_class_tier_rank",
    "advance_purchase_window_is_known", "source_canonical", "source_is_known",
    "carrier_canonical", "carrier_is_known", "flight_number_canonical",
    "departure_time", "departure_time_canonical", "collection_timestamp_iso",
    "round_sort_key", "total_fare_normalized", "base_fare", "taxes", "fees",
    "advance_purchase_days", "fare_decomposition_complete",
    "fare_components_reconcile", "price_state", "currency", "currency_source",
    "normalization_flags", "phase8_schema_version",
)
NORMALIZED_OBSERVATION_COLUMNS: Tuple[str, ...] = (
    PHASE7_OBSERVATION_MAP_COLUMNS + NORMALIZED_OBSERVATION_NEW_COLUMNS
)

# Grain approved as the finest useful audit granularity: (entity_id, field, action)
NORMALIZATION_REPORT_COLUMNS: Tuple[str, ...] = (
    "entity_type", "entity_id", "field", "action", "original_value",
    "normalized_value", "detail",
)

ENTITY_CONSOLIDATION_CELL = "CONSOLIDATION_CELL"
ENTITY_FLIGHT_CELL = "FLIGHT_CELL"
ENTITY_OBSERVATION = "OBSERVATION"


@dataclass
class NormalizationOutput:
    normalized: pd.DataFrame
    observation_map: pd.DataFrame
    flight_cells: pd.DataFrame
    report: pd.DataFrame


# ==========================================================================
# IO helpers
# ==========================================================================
def read_phase7_csv(path: str) -> pd.DataFrame:
    """Read a Phase 7 CSV as pure text. No type inference, no NaN coercion."""
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def require_columns(df: pd.DataFrame, columns: Sequence[str], label: str) -> None:
    missing = [name for name in columns if name not in df.columns]
    if missing:
        raise R.NormalizationRuleError(
            "%s is missing required column(s): %s" % (label, ", ".join(missing))
        )


def _report_row(
    entity_type: str,
    entity_id: str,
    field: str,
    action: str,
    original: Any,
    normalized: Any,
    detail: str = "",
) -> Dict[str, Any]:
    return {
        "entity_type": entity_type,
        "entity_id": entity_id,
        "field": field,
        "action": action,
        "original_value": "" if original is None else str(original),
        "normalized_value": "" if normalized is None else str(normalized),
        "detail": detail,
    }


def _emit(
    report: List[Dict[str, Any]],
    entity_type: str,
    entity_id: str,
    field: str,
    actions: Sequence[str],
    original: Any,
    normalized: Any,
    detail: str = "",
) -> None:
    """Emit one report row per (entity_id, field, action).

    Only real representation CHANGES and real FLAGS are reported. Derived
    columns are documented in docs/normalization_methodology.md rather than
    enumerated once per row, which would produce thousands of noise rows and
    bury the handful of entries that actually matter.
    """
    for action in actions:
        report.append(
            _report_row(entity_type, entity_id, field, action, original, normalized, detail)
        )


# ==========================================================================
# Shared per-row canonicalisation of the economic identity fields
# ==========================================================================
def _canonicalize_identity(
    row: Dict[str, Any],
    entity_type: str,
    entity_id: str,
    report: List[Dict[str, Any]],
) -> Tuple[Dict[str, Any], List[str]]:
    """Canonicalise origin/destination/travel_date/fare_class/AP window.

    ROUTE DIRECTION IS NEVER CHANGED. origin stays origin and destination
    stays destination. DEL-BOM is never rewritten to BOM-DEL under any
    circumstance, and the Phase 5 basket is neither consulted nor modified.
    """
    flags: List[str] = []
    out: Dict[str, Any] = {}

    origin, origin_actions = R.canonicalize_airport(row["origin"])
    _emit(report, entity_type, entity_id, "origin", origin_actions, row["origin"], origin)
    out["origin_canonical"] = origin
    if origin == "":
        flags.append(R.FLAG_MISSING_ORIGIN)

    destination, destination_actions = R.canonicalize_airport(row["destination"])
    _emit(
        report, entity_type, entity_id, "destination", destination_actions,
        row["destination"], destination,
    )
    out["destination_canonical"] = destination
    if destination == "":
        flags.append(R.FLAG_MISSING_DESTINATION)

    travel_date, travel_date_ok, travel_date_actions = R.normalize_travel_date(
        row["travel_date"]
    )
    _emit(
        report, entity_type, entity_id, "travel_date", travel_date_actions,
        row["travel_date"], travel_date,
    )
    out["travel_date_canonical"] = travel_date
    if not travel_date_ok and travel_date != "":
        flags.append(R.FLAG_INVALID_TRAVEL_DATE)

    fare_class, fare_class_known, fare_class_actions = R.canonicalize_categorical(
        row["fare_class"], R.KNOWN_FARE_CLASSES, R.FARE_CLASS_ALIASES
    )
    _emit(
        report, entity_type, entity_id, "fare_class", fare_class_actions,
        row["fare_class"], fare_class,
    )
    out["fare_class_canonical"] = fare_class
    out["fare_class_is_known"] = fare_class_known
    # Derived metadata ONLY. Never an identity field, never a grouping key.
    out["fare_class_tier_rank"] = R.fare_class_tier_rank(fare_class)
    if fare_class == "":
        flags.append(R.FLAG_MISSING_FARE_CLASS)
    elif not fare_class_known:
        flags.append(R.FLAG_UNKNOWN_FARE_CLASS)

    window, window_known, window_actions = R.canonicalize_categorical(
        row["advance_purchase_window"], R.KNOWN_ADVANCE_PURCHASE_WINDOWS
    )
    _emit(
        report, entity_type, entity_id, "advance_purchase_window", window_actions,
        row["advance_purchase_window"], window,
    )
    # NOTE: no re-binning. The window label is verified, never recomputed and
    # never moved. An observation never changes AP window in Phase 8.
    out["advance_purchase_window_is_known"] = window_known
    if window != "" and not window_known:
        flags.append(R.FLAG_UNKNOWN_ADVANCE_PURCHASE_WINDOW)

    return out, flags


def _sort_key(row: Dict[str, Any], tiebreaker_field: str) -> Tuple:
    return (
        row["origin_canonical"],
        row["destination_canonical"],
        row["travel_date_canonical"],
        row["fare_class_canonical"],
        str(row["advance_purchase_window"]),
    ) + R.round_sort_tuple(row["round_sort_key"], str(row[tiebreaker_field]))


# ==========================================================================
# 1. Consolidated cells (PRIMARY analytical dataset)
# ==========================================================================
def normalize_consolidated(
    consolidated: pd.DataFrame,
) -> Tuple[pd.DataFrame, List[Dict[str, Any]]]:
    require_columns(consolidated, PHASE7_CONSOLIDATED_COLUMNS, "consolidated input")
    report: List[Dict[str, Any]] = []
    rows: List[Dict[str, Any]] = []

    for _, source_row in consolidated.iterrows():
        row = {name: source_row[name] for name in PHASE7_CONSOLIDATED_COLUMNS}
        entity_id = str(row["consolidation_cell_id"])

        derived, flags = _canonicalize_identity(
            row, ENTITY_CONSOLIDATION_CELL, entity_id, report
        )
        out = dict(row)
        out.update(derived)

        fare_decimal, fare_text, fare_actions = R.normalize_money(row["consolidated_fare"])
        _emit(
            report, ENTITY_CONSOLIDATION_CELL, entity_id, "consolidated_fare",
            fare_actions, row["consolidated_fare"], fare_text,
        )
        out["consolidated_fare_normalized"] = fare_text
        if not R.is_missing(row["consolidated_fare"]) and fare_decimal is None:
            flags.append(R.FLAG_UNPARSEABLE_MONETARY_VALUE)

        price_state = R.derive_cell_price_state(
            row["consolidation_status"], row["consolidated_fare"]
        )
        out["price_state"] = price_state
        if price_state == R.PRICE_STATE_NO_PRICE_CELL:
            flags.append(R.FLAG_MISSING_PRICE)

        sort_key, sort_key_source = R.derive_round_sort_key(
            row["round_anchor_timestamp"], row["collection_round_id"]
        )
        out["round_sort_key"] = sort_key
        out["round_sort_key_source"] = sort_key_source
        if sort_key == "":
            flags.append(R.FLAG_MISSING_ROUND_SORT_KEY)
            _emit(
                report, ENTITY_CONSOLIDATION_CELL, entity_id, "round_sort_key",
                [R.ACTION_MISSING_VALUE_FLAGGED], row["collection_round_id"], "",
                R.FLAG_MISSING_ROUND_SORT_KEY,
            )

        out["currency"] = R.CURRENCY_CODE
        out["currency_source"] = R.CURRENCY_SOURCE
        out["normalization_flags"] = R.join_flags(flags)
        out["phase8_schema_version"] = R.PHASE8_SCHEMA_VERSION
        rows.append(out)

    rows.sort(key=lambda item: _sort_key(item, "consolidation_cell_id"))
    frame = pd.DataFrame(rows, columns=list(NORMALIZED_CELL_COLUMNS))
    return frame, report


# ==========================================================================
# 2. Flight cells (DIAGNOSTIC)
# ==========================================================================
def normalize_flight_cells(
    flight_cells: pd.DataFrame,
) -> Tuple[pd.DataFrame, List[Dict[str, Any]]]:
    require_columns(flight_cells, PHASE7_FLIGHT_CELL_COLUMNS, "flight cell input")
    report: List[Dict[str, Any]] = []
    rows: List[Dict[str, Any]] = []

    for _, source_row in flight_cells.iterrows():
        row = {name: source_row[name] for name in PHASE7_FLIGHT_CELL_COLUMNS}
        entity_id = str(row["flight_cell_id"])

        derived, flags = _canonicalize_identity(row, ENTITY_FLIGHT_CELL, entity_id, report)
        out = dict(row)
        out.update(derived)

        carrier, carrier_known, carrier_actions = R.canonicalize_categorical(
            row["carrier"], R.KNOWN_CARRIERS, R.CARRIER_ALIASES
        )
        _emit(
            report, ENTITY_FLIGHT_CELL, entity_id, "carrier", carrier_actions,
            row["carrier"], carrier,
        )
        out["carrier_canonical"] = carrier
        out["carrier_is_known"] = carrier_known
        if carrier == "":
            flags.append(R.FLAG_MISSING_CARRIER)
        elif not carrier_known:
            flags.append(R.FLAG_UNKNOWN_CARRIER)

        flight_number, flight_number_actions = R.canonicalize_flight_number(
            row["flight_number"]
        )
        _emit(
            report, ENTITY_FLIGHT_CELL, entity_id, "flight_number",
            flight_number_actions, row["flight_number"], flight_number,
        )
        out["flight_number_canonical"] = flight_number

        # Reuse of the Phase 6 implementation, never a re-implementation.
        departure = R.normalize_departure_time(row["departure_time_normalized"])
        out["departure_time_canonical"] = "" if departure is None else departure
        if departure is None and not R.is_missing(row["departure_time_normalized"]):
            flags.append(R.FLAG_INVALID_DEPARTURE_TIME)
            _emit(
                report, ENTITY_FLIGHT_CELL, entity_id, "departure_time_normalized",
                [R.ACTION_INVALID_FORMAT_FLAGGED], row["departure_time_normalized"], "",
            )

        fare_decimal, fare_text, fare_actions = R.normalize_money(
            row["flight_representative_fare"]
        )
        _emit(
            report, ENTITY_FLIGHT_CELL, entity_id, "flight_representative_fare",
            fare_actions, row["flight_representative_fare"], fare_text,
        )
        out["flight_representative_fare_normalized"] = fare_text
        if not R.is_missing(row["flight_representative_fare"]) and fare_decimal is None:
            flags.append(R.FLAG_UNPARSEABLE_MONETARY_VALUE)

        out["price_state"] = R.derive_flight_cell_price_state(
            row["flight_representative_fare"],
            row["flight_sold_out_observation_count"],
            row["flight_priced_observation_count"],
        )

        sort_key, _ = R.derive_round_sort_key("", row["collection_round_id"])
        out["round_sort_key"] = sort_key
        if sort_key == "":
            flags.append(R.FLAG_MISSING_ROUND_SORT_KEY)

        out["currency"] = R.CURRENCY_CODE
        out["currency_source"] = R.CURRENCY_SOURCE
        out["normalization_flags"] = R.join_flags(flags)
        out["phase8_schema_version"] = R.PHASE8_SCHEMA_VERSION
        rows.append(out)

    rows.sort(key=lambda item: _sort_key(item, "flight_cell_id"))
    frame = pd.DataFrame(rows, columns=list(NORMALIZED_FLIGHT_CELL_COLUMNS))
    return frame, report


# ==========================================================================
# 3. Observation map (AUDIT / LINEAGE dataset)
# ==========================================================================
def build_canonical_lookup(canonical: pd.DataFrame) -> Dict[str, Dict[str, Any]]:
    """Index the Phase 6 canonical rows by observation_id for the join."""
    require_columns(canonical, CANONICAL_JOIN_COLUMNS, "canonical input")
    lookup: Dict[str, Dict[str, Any]] = {}
    for _, source_row in canonical.iterrows():
        key = str(source_row["observation_id"])
        lookup[key] = {
            name: source_row[name] for name in CANONICAL_JOIN_COLUMNS if name != "observation_id"
        }
    return lookup


def normalize_observation_map(
    observation_map: pd.DataFrame,
    canonical: pd.DataFrame,
) -> Tuple[pd.DataFrame, List[Dict[str, Any]]]:
    require_columns(
        observation_map, PHASE7_OBSERVATION_MAP_COLUMNS, "observation map input"
    )
    lookup = build_canonical_lookup(canonical)
    report: List[Dict[str, Any]] = []
    rows: List[Dict[str, Any]] = []

    for _, source_row in observation_map.iterrows():
        row = {name: source_row[name] for name in PHASE7_OBSERVATION_MAP_COLUMNS}
        entity_id = str(row["observation_id"])
        joined = lookup.get(entity_id, {})

        derived, flags = _canonicalize_identity(row, ENTITY_OBSERVATION, entity_id, report)
        out = dict(row)
        out.update(derived)

        source_value, source_known, source_actions = R.canonicalize_categorical(
            row["source"], R.KNOWN_SOURCES, R.SOURCE_ALIASES
        )
        _emit(
            report, ENTITY_OBSERVATION, entity_id, "source", source_actions,
            row["source"], source_value,
        )
        out["source_canonical"] = source_value
        out["source_is_known"] = source_known
        if source_value == "":
            flags.append(R.FLAG_MISSING_SOURCE)
        elif not source_known:
            flags.append(R.FLAG_UNKNOWN_SOURCE)

        carrier, carrier_known, carrier_actions = R.canonicalize_categorical(
            row["carrier"], R.KNOWN_CARRIERS, R.CARRIER_ALIASES
        )
        _emit(
            report, ENTITY_OBSERVATION, entity_id, "carrier", carrier_actions,
            row["carrier"], carrier,
        )
        out["carrier_canonical"] = carrier
        out["carrier_is_known"] = carrier_known
        if carrier == "":
            flags.append(R.FLAG_MISSING_CARRIER)
        elif not carrier_known:
            flags.append(R.FLAG_UNKNOWN_CARRIER)

        flight_number, flight_number_actions = R.canonicalize_flight_number(
            row["flight_number"]
        )
        _emit(
            report, ENTITY_OBSERVATION, entity_id, "flight_number",
            flight_number_actions, row["flight_number"], flight_number,
        )
        out["flight_number_canonical"] = flight_number

        raw_departure = joined.get("departure_time", "")
        out["departure_time"] = raw_departure
        departure = R.normalize_departure_time(row["departure_time_normalized"])
        out["departure_time_canonical"] = "" if departure is None else departure
        if departure is None and not R.is_missing(row["departure_time_normalized"]):
            flags.append(R.FLAG_INVALID_DEPARTURE_TIME)

        iso_text, iso_ok, iso_actions = R.collection_timestamp_iso(
            row["collection_timestamp"]
        )
        _emit(
            report, ENTITY_OBSERVATION, entity_id, "collection_timestamp",
            iso_actions, row["collection_timestamp"], iso_text,
        )
        out["collection_timestamp_iso"] = iso_text
        if R.is_missing(row["collection_timestamp"]):
            flags.append(R.FLAG_MISSING_COLLECTION_TIMESTAMP)
        elif not iso_ok:
            flags.append(R.FLAG_UNPARSEABLE_COLLECTION_TIMESTAMP)

        sort_key, _ = R.derive_round_sort_key(
            row["round_anchor_timestamp"], row["collection_round_id"]
        )
        out["round_sort_key"] = sort_key
        if sort_key == "":
            flags.append(R.FLAG_MISSING_ROUND_SORT_KEY)

        total_decimal, total_text, total_actions = R.normalize_money(row["total_fare"])
        _emit(
            report, ENTITY_OBSERVATION, entity_id, "total_fare", total_actions,
            row["total_fare"], total_text,
        )
        out["total_fare_normalized"] = total_text
        if not R.is_missing(row["total_fare"]) and total_decimal is None:
            flags.append(R.FLAG_UNPARSEABLE_MONETARY_VALUE)

        # Fare decomposition is VERIFIED, never reconstructed.
        base_fare = joined.get("base_fare", "")
        taxes = joined.get("taxes", "")
        fees = joined.get("fees", "")
        out["base_fare"] = base_fare
        out["taxes"] = taxes
        out["fees"] = fees
        out["advance_purchase_days"] = joined.get("advance_purchase_days", "")

        complete, reconciles, decomposition_flags = R.fare_decomposition_state(
            base_fare, taxes, fees, row["total_fare"]
        )
        out["fare_decomposition_complete"] = complete
        out["fare_components_reconcile"] = reconciles
        flags.extend(decomposition_flags)
        if R.FLAG_FARE_COMPONENTS_MISMATCH in decomposition_flags:
            _emit(
                report, ENTITY_OBSERVATION, entity_id, "fare_components",
                [R.ACTION_INVALID_FORMAT_FLAGGED],
                "%s+%s+%s" % (base_fare, taxes, fees), row["total_fare"],
                R.FLAG_FARE_COMPONENTS_MISMATCH,
            )

        price_state = R.derive_observation_price_state(
            row["availability_status"], row["total_fare"]
        )
        out["price_state"] = price_state
        if price_state == R.PRICE_STATE_MISSING_PRICE:
            flags.append(R.FLAG_MISSING_PRICE)

        out["currency"] = R.CURRENCY_CODE
        out["currency_source"] = R.CURRENCY_SOURCE
        out["normalization_flags"] = R.join_flags(flags)
        out["phase8_schema_version"] = R.PHASE8_SCHEMA_VERSION
        rows.append(out)

    rows.sort(key=lambda item: str(item["observation_id"]))
    frame = pd.DataFrame(rows, columns=list(NORMALIZED_OBSERVATION_COLUMNS))
    return frame, report


# ==========================================================================
# Orchestrator
# ==========================================================================
def run_normalization(
    consolidated: pd.DataFrame,
    flight_cells: pd.DataFrame,
    observation_map: pd.DataFrame,
    canonical: pd.DataFrame,
) -> NormalizationOutput:
    """Run Phase 8. Pure function of the input values; inputs are never mutated."""
    normalized, cell_report = normalize_consolidated(consolidated)
    flights, flight_report = normalize_flight_cells(flight_cells)
    observations, observation_report = normalize_observation_map(observation_map, canonical)

    if len(normalized) != len(consolidated):
        raise R.NormalizationRuleError("consolidated row count changed during Phase 8")
    if len(flights) != len(flight_cells):
        raise R.NormalizationRuleError("flight cell row count changed during Phase 8")
    if len(observations) != len(observation_map):
        raise R.NormalizationRuleError("observation row count changed during Phase 8")

    report_rows = cell_report + flight_report + observation_report
    report_rows.sort(
        key=lambda item: (
            item["entity_type"], item["entity_id"], item["field"], item["action"]
        )
    )
    report = pd.DataFrame(report_rows, columns=list(NORMALIZATION_REPORT_COLUMNS))

    return NormalizationOutput(
        normalized=normalized,
        observation_map=observations,
        flight_cells=flights,
        report=report,
    )
