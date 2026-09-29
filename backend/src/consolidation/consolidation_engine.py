"""
VAYU INDEX — Phase 7: Source Consolidation Engine
===================================================

Pipeline implemented here:

    CANONICAL CSV (Phase 6 output, 778 rows, duplicates already resolved)
        -> collection-round assignment  (nearest prototype anchor, +/-30 min)
        -> flight cells                 (Phase 6 product-instance identity)
        -> STAGE 0: within-source, within-flight representative value
        -> STAGE 1: cross-source median WITHIN a flight cell
        -> STAGE 2: median across flight-level representative fares
        -> CONSOLIDATED DATASET   (one row per economic product + round)
        -> FLIGHT CELL REPORT     (flight-level detail + dispersion)
        -> OBSERVATION MAP        (all 778 observations, full lineage)

PRIMARY ESTIMATOR (approved wording, do not paraphrase):
    Phase 7 primary estimator = flight-first, two-stage median: cross-source
    median within each flight cell, followed by median across flight-level
    representative fares within each economic product and collection round.

This is a median-based source-consolidation method with a flight-first
aggregation hierarchy. It is NOT equal-weighting of sources.

Why flight-first rather than source-first: sources frequently expose
different flight sets (verified: 151 of 232 multi-source cells in the real
data), and source-first aggregation converts those flight-coverage
differences into artificial source-price differences. Flight-first ensures
each flight counts once at Stage 2 and confines source comparison to
observations of the SAME flight. No market-share weights are invented
anywhere.

HONEST LIMITATION — RESIDUAL COVERAGE ASYMMETRY:
    Flight-first does NOT completely remove source-coverage bias. A source
    that uniquely exposes a flight still fully determines that flight's
    representative value, and therefore still influences the Stage 2 result.
    This residual is accepted deliberately: the alternatives were discarding
    unmatched flights (~64% of flight cells) or imputing prices, both
    rejected. It is disclosed via the source coverage fields rather than
    hidden.

This module never modifies a raw monetary amount, never deletes an
observation, never imputes a missing source, never treats a missing or
sold-out price as zero, and performs NO anomaly detection. Dispersion is
measured and reported only — nothing is ever dropped or altered because of
it.

Determinism / order-independence: the entire algorithm is a pure function of
the input rows' field values. Rows are sorted by observation_id before
processing, every group is materialised through an explicit sort, all list
fields are emitted in sorted order, and all monetary arithmetic runs in
Decimal. Nothing depends on the order rows appear in the input DataFrame.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional, Sequence, Tuple
import pandas as pd

from . import rules as R


# ---------------------------------------------------------------------------
# Output schemas (fixed, explicit column order -> byte-stable outputs)
# ---------------------------------------------------------------------------

CONSOLIDATED_COLUMNS: Tuple[str, ...] = (
    "consolidation_cell_id",
    "origin",
    "destination",
    "travel_date",
    "fare_class",
    "advance_purchase_window",
    "collection_round_id",
    "round_anchor_timestamp",
    "round_alignment",
    "round_time_spread_minutes",
    "consolidated_fare",
    "consolidation_status",
    "consolidated_fare_is_observed_value",
    "participating_source_count",
    "participating_sources",
    "expected_source_count",
    "source_coverage",
    "source_coverage_ratio",
    "missing_sources",
    "flight_instance_count",
    "priced_flight_instance_count",
    "flight_representative_fares",
    "observation_count",
    "participating_observation_count",
    "contributing_observation_ids",
    "sold_out_observation_count",
    "missing_price_observation_count",
    "min_participating_fare",
    "max_participating_fare",
    "source_level_fares",
    "min_source_fare",
    "max_source_fare",
    "alt_source_first_fare",
    "max_flight_source_spread",
    "median_flight_source_spread",
    "cross_flight_spread",
)

FLIGHT_CELL_COLUMNS: Tuple[str, ...] = (
    "flight_cell_id",
    "consolidation_cell_id",
    "origin",
    "destination",
    "travel_date",
    "fare_class",
    "advance_purchase_window",
    "collection_round_id",
    "carrier",
    "flight_number",
    "departure_time_normalized",
    "flight_representative_fare",
    "flight_source_count",
    "flight_sources",
    "flight_source_level_fares",
    "flight_min_fare",
    "flight_max_fare",
    "flight_source_spread",
    "flight_source_relative_spread",
    "flight_observation_count",
    "flight_priced_observation_count",
    "flight_sold_out_observation_count",
    "flight_missing_price_observation_count",
    "flight_observation_ids",
)

OBSERVATION_MAP_COLUMNS: Tuple[str, ...] = (
    "observation_id",
    "source",
    "total_fare",
    "availability_status",
    "collection_timestamp",
    "collection_round_id",
    "round_alignment",
    "round_anchor_timestamp",
    "origin",
    "destination",
    "travel_date",
    "fare_class",
    "advance_purchase_window",
    "carrier",
    "flight_number",
    "departure_time_normalized",
    "flight_cell_id",
    "flight_representative_fare",
    "consolidation_cell_id",
    "consolidated_fare",
    "participation_status",
)


# ---------------------------------------------------------------------------
# Observation record
# ---------------------------------------------------------------------------


@dataclass
class ObservationRecord:
    """One canonical Phase 6 observation, prepared for consolidation."""

    observation_id: str
    source: str
    origin: str
    destination: str
    travel_date: str
    fare_class: str
    advance_purchase_window: str
    carrier: str
    flight_number: str
    departure_time_raw: str
    departure_time_normalized: str
    collection_timestamp_raw: str
    collection_ts: Optional[datetime]
    total_fare_raw: str
    total_fare: Optional[Decimal]
    availability_status: str
    sold_out: bool
    collection_round_id: str
    round_alignment: str
    round_anchor_timestamp: str
    participation_status: str
    consolidation_cell_id: str = ""
    flight_cell_id: str = ""

    @property
    def is_cell_member(self) -> bool:
        return self.participation_status in R.CELL_MEMBER_PARTICIPATION_STATUSES

    @property
    def participated(self) -> bool:
        return self.participation_status == R.PARTICIPATION_PARTICIPATED

    @property
    def economic_identity(self) -> Tuple[str, ...]:
        return (
            self.origin,
            self.destination,
            self.travel_date,
            self.fare_class,
            self.advance_purchase_window,
        )

    @property
    def flight_identity(self) -> Tuple[str, ...]:
        return (self.carrier, self.flight_number, self.departure_time_normalized)


def build_observation_record(row: Any) -> ObservationRecord:
    """Prepare one canonical observation for consolidation.

    Assigns the collection round and the participation status. Never modifies
    a raw value: `total_fare_raw` keeps the input's own integer formatting via
    the Phase 6 canonicalizer, and `total_fare` is the exact Decimal used for
    arithmetic.
    """
    get = row.get if hasattr(row, "get") else (lambda key, default=None: row[key])

    observation_id = R.clean_str(get("observation_id"))
    source = R.clean_str(get("source"))
    departure_time_raw = R.clean_str(get("departure_time"))
    normalized_departure = R.normalize_departure_time(get("departure_time")) or ""
    collection_timestamp_raw = R.clean_str(get("collection_timestamp"))
    total_fare_raw = R.normalize_total_fare(get("total_fare")) or ""
    total_fare = R.parse_money(get("total_fare"))
    availability_status = R.clean_str(get("availability_status"))

    round_id, alignment, anchor_timestamp = R.assign_collection_round(
        get("collection_timestamp"), observation_id
    )

    record = ObservationRecord(
        observation_id=observation_id,
        source=source,
        origin=R.clean_str(get("origin")),
        destination=R.clean_str(get("destination")),
        travel_date=R.clean_str(get("travel_date")),
        fare_class=R.clean_str(get("fare_class")),
        advance_purchase_window=R.clean_str(get("advance_purchase_window")),
        carrier=R.clean_str(get("carrier")),
        flight_number=R.clean_str(get("flight_number")),
        departure_time_raw=departure_time_raw,
        departure_time_normalized=normalized_departure,
        collection_timestamp_raw=collection_timestamp_raw,
        collection_ts=R.parse_collection_timestamp(get("collection_timestamp")),
        total_fare_raw=total_fare_raw,
        total_fare=total_fare,
        availability_status=availability_status,
        sold_out=R.is_sold_out(availability_status),
        collection_round_id=round_id,
        round_alignment=alignment,
        round_anchor_timestamp=anchor_timestamp,
        participation_status="",
    )
    record.participation_status = _participation_status(record)
    if record.is_cell_member:
        record.consolidation_cell_id = _consolidation_cell_id(record)
        record.flight_cell_id = _flight_cell_id(record)
    return record


def _participation_status(record: ObservationRecord) -> str:
    """Assign exactly one explicit participation status to an observation.

    Order matters: identity/round problems prevent cell membership entirely,
    while sold-out and missing-price observations DO belong to their cell and
    are counted there — they are only excluded from the price median.
    """
    if record.round_alignment == R.ROUND_ALIGNMENT_UNRESOLVED:
        return R.PARTICIPATION_EXCLUDED_NO_ROUND
    if record.source == "":
        return R.PARTICIPATION_EXCLUDED_MISSING_SOURCE
    if any(value == "" for value in record.economic_identity):
        return R.PARTICIPATION_EXCLUDED_MISSING_IDENTITY
    if record.sold_out:
        return R.PARTICIPATION_EXCLUDED_SOLD_OUT
    if record.total_fare is None:
        return R.PARTICIPATION_EXCLUDED_MISSING_PRICE
    return R.PARTICIPATION_PARTICIPATED


def _field_or_marker(value: str) -> str:
    return value if value != "" else R.MISSING_FIELD_MARKER


def _consolidation_cell_id(record: ObservationRecord) -> str:
    parts = "|".join(_field_or_marker(value) for value in record.economic_identity)
    return "%s%s::%s" % (
        R.CONSOLIDATION_CELL_ID_PREFIX,
        parts,
        record.collection_round_id,
    )


def _flight_cell_id(record: ObservationRecord) -> str:
    parts = "|".join(_field_or_marker(value) for value in record.flight_identity)
    return "%s%s%s" % (record.consolidation_cell_id, R.FLIGHT_CELL_ID_INFIX, parts)


# ---------------------------------------------------------------------------
# Stage 0 / Stage 1 — flight cells
# ---------------------------------------------------------------------------


@dataclass
class FlightCell:
    """One flight instance within one economic product + collection round."""

    flight_cell_id: str
    consolidation_cell_id: str
    carrier: str
    flight_number: str
    departure_time_normalized: str
    observations: List[ObservationRecord] = field(default_factory=list)

    # Stage 0 output: one representative value per source for THIS flight.
    source_values: Dict[str, Decimal] = field(default_factory=dict)
    # Stage 1 output.
    representative_fare: Optional[Decimal] = None

    @property
    def priced_observations(self) -> List[ObservationRecord]:
        return [obs for obs in self.observations if obs.participated]


def stage0_within_source_values(observations: Sequence[ObservationRecord]) -> Dict[str, Decimal]:
    """STAGE 0 — within-source, within-flight representative value.

    APPROVED RULE: if multiple surviving observations from the same source and
    the same flight occur in the same consolidation round, collapse them to ONE
    value using the standard midpoint median. This is defensive (Phase 6
    leaves no such rows in the current data) and its purpose is to prevent a
    source from receiving multiple votes for the same flight.
    """
    grouped: Dict[str, List[Decimal]] = {}
    for obs in sorted(observations, key=lambda o: o.observation_id):
        if not obs.participated or obs.total_fare is None:
            continue
        grouped.setdefault(obs.source, []).append(obs.total_fare)
    return {
        source: R.midpoint_median(values)
        for source, values in sorted(grouped.items())
    }


def stage1_flight_representative_fare(source_values: Dict[str, Decimal]) -> Optional[Decimal]:
    """STAGE 1 — cross-source median WITHIN one flight cell.

    This is the ONLY place sources are compared, and the comparison is
    strictly like-for-like: same carrier, same flight number, same normalized
    departure time, same collection round. Uses the standard midpoint median
    for even source counts.

    Returns None when no source produced a usable price for this flight.
    """
    if not source_values:
        return None
    return R.midpoint_median(list(source_values.values()))


def build_flight_cells(records: Sequence[ObservationRecord]) -> Dict[str, FlightCell]:
    """Group cell-member observations into flight cells and run Stages 0 and 1."""
    cells: Dict[str, FlightCell] = {}
    for record in sorted(records, key=lambda o: o.observation_id):
        if not record.is_cell_member:
            continue
        cell = cells.get(record.flight_cell_id)
        if cell is None:
            cell = FlightCell(
                flight_cell_id=record.flight_cell_id,
                consolidation_cell_id=record.consolidation_cell_id,
                carrier=record.carrier,
                flight_number=record.flight_number,
                departure_time_normalized=record.departure_time_normalized,
            )
            cells[record.flight_cell_id] = cell
        cell.observations.append(record)

    for cell in cells.values():
        cell.source_values = stage0_within_source_values(cell.observations)
        cell.representative_fare = stage1_flight_representative_fare(cell.source_values)
    return cells


# ---------------------------------------------------------------------------
# Stage 2 — consolidation cells
# ---------------------------------------------------------------------------


@dataclass
class ConsolidationCell:
    """One economic product within one collection round."""

    consolidation_cell_id: str
    origin: str
    destination: str
    travel_date: str
    fare_class: str
    advance_purchase_window: str
    collection_round_id: str
    round_alignment: str
    round_anchor_timestamp: str
    observations: List[ObservationRecord] = field(default_factory=list)
    flight_cells: List[FlightCell] = field(default_factory=list)
    consolidated_fare: Optional[Decimal] = None
    consolidation_status: str = ""


def stage2_consolidated_fare(flight_cells: Sequence[FlightCell]) -> Optional[Decimal]:
    """STAGE 2 — median across flight-level representative fares.

    Each flight contributes EXACTLY ONE value regardless of how many sources
    listed it, which is what structurally removes flight double-counting.
    Uses the standard midpoint median for even flight counts.
    """
    values = [
        cell.representative_fare
        for cell in flight_cells
        if cell.representative_fare is not None
    ]
    if not values:
        return None
    return R.midpoint_median(values)


def alt_source_first_fare(observations: Sequence[ObservationRecord]) -> Tuple[
    Optional[Decimal], Dict[str, Decimal]
]:
    """DIAGNOSTIC ONLY — the rejected source-first (Option B) value.

    Computes, for each source, the median of ALL of that source's priced
    observations across every flight in the cell, then the median across those
    source-level values.

    This value is emitted for auditability and comparison ONLY. It MUST NEVER
    influence `consolidated_fare`. It is computed from the observation list
    independently and its result is never fed back into Stage 0, 1 or 2 — a
    test asserts this non-influence.

    Returns ``(alt_value, source_level_values)``.
    """
    grouped: Dict[str, List[Decimal]] = {}
    for obs in sorted(observations, key=lambda o: o.observation_id):
        if not obs.participated or obs.total_fare is None:
            continue
        grouped.setdefault(obs.source, []).append(obs.total_fare)
    source_values = {
        source: R.midpoint_median(values) for source, values in sorted(grouped.items())
    }
    if not source_values:
        return (None, source_values)
    return (R.midpoint_median(list(source_values.values())), source_values)


def _consolidation_status(
    cell: ConsolidationCell, consolidated_fare: Optional[Decimal]
) -> str:
    if consolidated_fare is not None:
        return R.STATUS_CONSOLIDATED
    sold_out = sum(
        1
        for obs in cell.observations
        if obs.participation_status == R.PARTICIPATION_EXCLUDED_SOLD_OUT
    )
    missing = sum(
        1
        for obs in cell.observations
        if obs.participation_status == R.PARTICIPATION_EXCLUDED_MISSING_PRICE
    )
    total = len(cell.observations)
    if total > 0 and sold_out == total:
        return R.STATUS_NO_PRICE_ALL_SOLD_OUT
    if total > 0 and missing == total:
        return R.STATUS_NO_PRICE_ALL_MISSING
    return R.STATUS_NO_PRICE_NO_USABLE_FARE


def build_consolidation_cells(
    records: Sequence[ObservationRecord], flight_cells: Dict[str, FlightCell]
) -> Dict[str, ConsolidationCell]:
    """Group observations into consolidation cells and run Stage 2."""
    cells: Dict[str, ConsolidationCell] = {}
    for record in sorted(records, key=lambda o: o.observation_id):
        if not record.is_cell_member:
            continue
        cell = cells.get(record.consolidation_cell_id)
        if cell is None:
            cell = ConsolidationCell(
                consolidation_cell_id=record.consolidation_cell_id,
                origin=record.origin,
                destination=record.destination,
                travel_date=record.travel_date,
                fare_class=record.fare_class,
                advance_purchase_window=record.advance_purchase_window,
                collection_round_id=record.collection_round_id,
                round_alignment=record.round_alignment,
                round_anchor_timestamp=record.round_anchor_timestamp,
            )
            cells[record.consolidation_cell_id] = cell
        cell.observations.append(record)

    for flight_cell in sorted(flight_cells.values(), key=lambda c: c.flight_cell_id):
        parent = cells.get(flight_cell.consolidation_cell_id)
        if parent is not None:
            parent.flight_cells.append(flight_cell)

    for cell in cells.values():
        cell.consolidated_fare = stage2_consolidated_fare(cell.flight_cells)
        cell.consolidation_status = _consolidation_status(cell, cell.consolidated_fare)
    return cells


# ---------------------------------------------------------------------------
# Dispersion — measured and reported only, never used to drop or alter data
# ---------------------------------------------------------------------------


def flight_source_spread(flight_cell: FlightCell) -> Optional[Decimal]:
    """Genuine source disagreement for ONE flight: max - min across sources.

    Measured at flight level because that is the only place the compared
    values describe the same flight. A source-first spread would conflate
    markup with flight composition.
    """
    if not flight_cell.source_values:
        return None
    values = list(flight_cell.source_values.values())
    return R.quantize_money(max(values) - min(values))


def compute_dispersion(cell: ConsolidationCell) -> Dict[str, Optional[Decimal]]:
    """Cell-level dispersion rollups. No thresholds, no flags, no removals."""
    spreads: List[Decimal] = []
    representative: List[Decimal] = []
    for flight_cell in cell.flight_cells:
        spread = flight_source_spread(flight_cell)
        if spread is not None:
            spreads.append(spread)
        if flight_cell.representative_fare is not None:
            representative.append(flight_cell.representative_fare)

    return {
        "max_flight_source_spread": max(spreads) if spreads else None,
        "median_flight_source_spread": R.midpoint_median(spreads) if spreads else None,
        # Variation ACROSS flights (time-of-day / carrier mix), a genuinely
        # different quantity. Deliberately NOT labelled source dispersion.
        "cross_flight_spread": (
            R.quantize_money(max(representative) - min(representative))
            if representative
            else None
        ),
    }


# ---------------------------------------------------------------------------
# Row rendering
# ---------------------------------------------------------------------------


def _join_sorted(values: Sequence[str]) -> str:
    return ";".join(sorted(values))


def _join_money_sorted(values: Sequence[Decimal]) -> str:
    return ";".join(R.format_money(value) for value in sorted(values))


def _join_source_values(source_values: Dict[str, Decimal]) -> str:
    return ";".join(
        "%s=%s" % (source, R.format_money(value))
        for source, value in sorted(source_values.items())
    )


def _round_time_spread_minutes(cell: ConsolidationCell) -> str:
    stamps = [obs.collection_ts for obs in cell.observations if obs.collection_ts is not None]
    if not stamps:
        return ""
    delta = max(stamps) - min(stamps)
    return str(int(delta.total_seconds() // 60))


def _bool_text(value: Optional[bool]) -> str:
    if value is None:
        return ""
    return "True" if value else "False"


def _consolidated_row(cell: ConsolidationCell) -> Dict[str, Any]:
    participating = [obs for obs in cell.observations if obs.participated]
    participating_sources = sorted({obs.source for obs in participating})
    missing_sources = sorted(
        source for source in R.EXPECTED_SOURCES if source not in set(participating_sources)
    )
    participating_fares = [
        obs.total_fare for obs in participating if obs.total_fare is not None
    ]

    alt_value, source_level_values = alt_source_first_fare(cell.observations)
    dispersion = compute_dispersion(cell)

    representative_fares = [
        flight_cell.representative_fare
        for flight_cell in cell.flight_cells
        if flight_cell.representative_fare is not None
    ]

    is_observed: Optional[bool] = None
    if cell.consolidated_fare is not None:
        target = R.quantize_money(cell.consolidated_fare)
        is_observed = any(
            R.quantize_money(fare) == target for fare in participating_fares
        )

    coverage_ratio = (
        Decimal(len(participating_sources)) / Decimal(R.EXPECTED_SOURCE_COUNT)
        if R.EXPECTED_SOURCE_COUNT
        else Decimal(0)
    )

    return {
        "consolidation_cell_id": cell.consolidation_cell_id,
        "origin": cell.origin,
        "destination": cell.destination,
        "travel_date": cell.travel_date,
        "fare_class": cell.fare_class,
        "advance_purchase_window": cell.advance_purchase_window,
        "collection_round_id": cell.collection_round_id,
        "round_anchor_timestamp": cell.round_anchor_timestamp,
        "round_alignment": cell.round_alignment,
        "round_time_spread_minutes": _round_time_spread_minutes(cell),
        "consolidated_fare": R.format_money(cell.consolidated_fare),
        "consolidation_status": cell.consolidation_status,
        "consolidated_fare_is_observed_value": _bool_text(is_observed),
        "participating_source_count": len(participating_sources),
        "participating_sources": _join_sorted(participating_sources),
        "expected_source_count": R.EXPECTED_SOURCE_COUNT,
        "source_coverage": R.source_coverage_label(len(participating_sources)),
        "source_coverage_ratio": format(
            coverage_ratio.quantize(Decimal("0.0001")), "f"
        ),
        "missing_sources": _join_sorted(missing_sources),
        "flight_instance_count": len(cell.flight_cells),
        "priced_flight_instance_count": len(representative_fares),
        "flight_representative_fares": _join_money_sorted(representative_fares),
        "observation_count": len(cell.observations),
        "participating_observation_count": len(participating),
        "contributing_observation_ids": _join_sorted(
            [obs.observation_id for obs in participating]
        ),
        "sold_out_observation_count": sum(
            1
            for obs in cell.observations
            if obs.participation_status == R.PARTICIPATION_EXCLUDED_SOLD_OUT
        ),
        "missing_price_observation_count": sum(
            1
            for obs in cell.observations
            if obs.participation_status == R.PARTICIPATION_EXCLUDED_MISSING_PRICE
        ),
        "min_participating_fare": R.format_money(
            min(participating_fares) if participating_fares else None
        ),
        "max_participating_fare": R.format_money(
            max(participating_fares) if participating_fares else None
        ),
        "source_level_fares": _join_source_values(source_level_values),
        "min_source_fare": R.format_money(
            min(source_level_values.values()) if source_level_values else None
        ),
        "max_source_fare": R.format_money(
            max(source_level_values.values()) if source_level_values else None
        ),
        "alt_source_first_fare": R.format_money(alt_value),
        "max_flight_source_spread": R.format_money(dispersion["max_flight_source_spread"]),
        "median_flight_source_spread": R.format_money(
            dispersion["median_flight_source_spread"]
        ),
        "cross_flight_spread": R.format_money(dispersion["cross_flight_spread"]),
    }


def _flight_cell_row(
    flight_cell: FlightCell, parent: Optional[ConsolidationCell]
) -> Dict[str, Any]:
    priced = flight_cell.priced_observations
    fares = [obs.total_fare for obs in priced if obs.total_fare is not None]
    spread = flight_source_spread(flight_cell)

    relative = ""
    if (
        spread is not None
        and flight_cell.representative_fare is not None
        and flight_cell.representative_fare != 0
    ):
        relative = format(
            (spread / flight_cell.representative_fare).quantize(Decimal("0.000001")), "f"
        )

    return {
        "flight_cell_id": flight_cell.flight_cell_id,
        "consolidation_cell_id": flight_cell.consolidation_cell_id,
        "origin": parent.origin if parent else "",
        "destination": parent.destination if parent else "",
        "travel_date": parent.travel_date if parent else "",
        "fare_class": parent.fare_class if parent else "",
        "advance_purchase_window": parent.advance_purchase_window if parent else "",
        "collection_round_id": parent.collection_round_id if parent else "",
        "carrier": flight_cell.carrier,
        "flight_number": flight_cell.flight_number,
        "departure_time_normalized": flight_cell.departure_time_normalized,
        "flight_representative_fare": R.format_money(flight_cell.representative_fare),
        "flight_source_count": len(flight_cell.source_values),
        "flight_sources": _join_sorted(list(flight_cell.source_values.keys())),
        "flight_source_level_fares": _join_source_values(flight_cell.source_values),
        "flight_min_fare": R.format_money(min(fares) if fares else None),
        "flight_max_fare": R.format_money(max(fares) if fares else None),
        "flight_source_spread": R.format_money(spread),
        "flight_source_relative_spread": relative,
        "flight_observation_count": len(flight_cell.observations),
        "flight_priced_observation_count": len(priced),
        "flight_sold_out_observation_count": sum(
            1
            for obs in flight_cell.observations
            if obs.participation_status == R.PARTICIPATION_EXCLUDED_SOLD_OUT
        ),
        "flight_missing_price_observation_count": sum(
            1
            for obs in flight_cell.observations
            if obs.participation_status == R.PARTICIPATION_EXCLUDED_MISSING_PRICE
        ),
        "flight_observation_ids": _join_sorted(
            [obs.observation_id for obs in flight_cell.observations]
        ),
    }


def _observation_map_row(
    record: ObservationRecord,
    flight_cells: Dict[str, FlightCell],
    consolidation_cells: Dict[str, ConsolidationCell],
) -> Dict[str, Any]:
    flight_cell = flight_cells.get(record.flight_cell_id) if record.flight_cell_id else None
    parent = (
        consolidation_cells.get(record.consolidation_cell_id)
        if record.consolidation_cell_id
        else None
    )
    return {
        "observation_id": record.observation_id,
        "source": record.source,
        "total_fare": record.total_fare_raw,
        "availability_status": record.availability_status,
        "collection_timestamp": record.collection_timestamp_raw,
        "collection_round_id": record.collection_round_id,
        "round_alignment": record.round_alignment,
        "round_anchor_timestamp": record.round_anchor_timestamp,
        "origin": record.origin,
        "destination": record.destination,
        "travel_date": record.travel_date,
        "fare_class": record.fare_class,
        "advance_purchase_window": record.advance_purchase_window,
        "carrier": record.carrier,
        "flight_number": record.flight_number,
        "departure_time_normalized": record.departure_time_normalized,
        "flight_cell_id": record.flight_cell_id,
        "flight_representative_fare": (
            R.format_money(flight_cell.representative_fare) if flight_cell else ""
        ),
        "consolidation_cell_id": record.consolidation_cell_id,
        "consolidated_fare": (R.format_money(parent.consolidated_fare) if parent else ""),
        "participation_status": record.participation_status,
    }


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


@dataclass
class ConsolidationOutput:
    """The three Phase 7 outputs plus the in-memory model behind them."""

    consolidated: pd.DataFrame
    flight_cells: pd.DataFrame
    observation_map: pd.DataFrame
    records: List[ObservationRecord]
    cell_model: Dict[str, ConsolidationCell]
    flight_cell_model: Dict[str, FlightCell]


def run_consolidation(df: pd.DataFrame) -> ConsolidationOutput:
    """Run Phase 7 source consolidation over a canonical Phase 6 DataFrame.

    Every input observation appears exactly once in the observation map with
    an explicit participation status. Nothing is physically deleted. Outputs
    are deterministically sorted, so reruns and shuffled inputs produce
    byte-identical files.
    """
    records = [build_observation_record(row) for _, row in df.iterrows()]
    records.sort(key=lambda record: record.observation_id)

    flight_cells = build_flight_cells(records)
    consolidation_cells = build_consolidation_cells(records, flight_cells)

    consolidated_rows = [
        _consolidated_row(cell)
        for cell in sorted(
            consolidation_cells.values(), key=lambda c: c.consolidation_cell_id
        )
    ]
    flight_rows = [
        _flight_cell_row(
            flight_cell, consolidation_cells.get(flight_cell.consolidation_cell_id)
        )
        for flight_cell in sorted(flight_cells.values(), key=lambda c: c.flight_cell_id)
    ]
    map_rows = [
        _observation_map_row(record, flight_cells, consolidation_cells)
        for record in records
    ]

    return ConsolidationOutput(
        consolidated=pd.DataFrame(consolidated_rows, columns=list(CONSOLIDATED_COLUMNS)),
        flight_cells=pd.DataFrame(flight_rows, columns=list(FLIGHT_CELL_COLUMNS)),
        observation_map=pd.DataFrame(map_rows, columns=list(OBSERVATION_MAP_COLUMNS)),
        records=records,
        cell_model=consolidation_cells,
        flight_cell_model=flight_cells,
    )


def read_canonical_csv(path: str) -> pd.DataFrame:
    """Read a canonical Phase 6 CSV without letting pandas rewrite values.

    `dtype=str` and `keep_default_na=False` keep integer fares as "5400"
    rather than 5400.0, and keep blank fields blank rather than NaN, so raw
    provenance survives untouched.
    """
    return pd.read_csv(path, dtype=str, keep_default_na=False)
