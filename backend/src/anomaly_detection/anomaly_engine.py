"""VAYU INDEX - Phase 9 anomaly-detection engine.

Reads Phase 8 outputs READ-ONLY and produces five annotated outputs. Phase 8
input frames are never mutated; every Phase 9 field is additive.

DESIGN RULINGS (deviations worth reviewing)
-------------------------------------------
1. ADDITIVE ANNOTATION, NOT REWRITING.
   The primary output is the Phase 8 consolidated frame carried through
   byte-identically plus a compact annotation block. No Phase 8 column is
   edited, reordered or dropped, so Phase 8 remains the single source of
   truth for normalized values.

2. NORMALIZED RULE-LEVEL REPORT.
   Rather than widening the primary output with 13 rule columns x several
   fields each, per-rule detail lives in phase9_anomaly_report.csv, one row
   per emitted evaluation. The primary output stays narrow and the report
   stays fully auditable.

3. REPORT GRAIN: FLAGGED and NOT_EVALUABLE only.
   PASS evaluations are not emitted. Emitting every passing evaluation would
   add thousands of rows that say 'nothing happened'. Per-entity coverage is
   still recoverable from the `not_evaluable_rule_ids` column on the primary
   output. This mirrors the Phase 8 report-grain ruling.

4. R04 EMITS ONE FRAMEWORK ROW.
   R04 is inactive for identical reasons on every observation. 777 identical
   NOT_EVALUABLE rows would be pure noise, so R04 emits a single
   rule-framework row recording the affected entity count. This is the only
   rule granted that exception, and it is stated in the methodology doc.

5. PEER POPULATION INCLUDES SELF.
   R13 computes the median/MAD over a population that contains the value
   being tested. This is the standard modified-z convention and is stated
   explicitly so nobody has to guess.

DETERMINISM: no randomness, no ML, no floats in the economic path, explicit
row["column"] access only, and output ordering fixed by declared sort keys.
"""

import os
from decimal import Decimal
from typing import Dict, List, Optional, Sequence, Tuple

import pandas as pd

from . import rules as R


# ---------------------------------------------------------------------------
# Required input columns (validated, never assumed)
# ---------------------------------------------------------------------------
REQUIRED_CELL_COLUMNS: Tuple[str, ...] = (
    "consolidation_cell_id",
    "origin_canonical",
    "destination_canonical",
    "travel_date_canonical",
    "fare_class_canonical",
    "advance_purchase_window",
    "collection_round_id",
    "round_alignment",
    "round_sort_key",
    "consolidated_fare_normalized",
    "price_state",
    "participating_source_count",
    "participating_sources",
    "flight_instance_count",
    "source_coverage",
    "currency",
)

REQUIRED_FLIGHT_CELL_COLUMNS: Tuple[str, ...] = (
    "flight_cell_id",
    "consolidation_cell_id",
    "collection_round_id",
    "round_sort_key",
    "carrier_canonical",
    "flight_number_canonical",
    "flight_representative_fare_normalized",
    "flight_source_count",
    "flight_sources",
    "flight_source_level_fares",
    "flight_min_fare",
    "flight_max_fare",
    "price_state",
)

REQUIRED_OBSERVATION_COLUMNS: Tuple[str, ...] = (
    "observation_id",
    "source_canonical",
    "total_fare_normalized",
    "availability_status",
    "participation_status",
    "price_state",
    "flight_cell_id",
    "consolidation_cell_id",
    "collection_round_id",
    "round_alignment",
    "round_sort_key",
    "base_fare",
    "taxes",
    "fees",
    "fare_decomposition_complete",
    "origin_canonical",
    "destination_canonical",
    "travel_date_canonical",
    "fare_class_canonical",
    "advance_purchase_window",
)


# ---------------------------------------------------------------------------
# Output column contracts
# ---------------------------------------------------------------------------
# Additive annotation block appended to the Phase 8 consolidated frame.
CELL_ANNOTATION_COLUMNS: Tuple[str, ...] = (
    "series_id",
    "anomaly_rule_ids",
    "anomaly_flag_count",
    "anomaly_severity_max",
    "not_evaluable_rule_ids",
    "market_movement_class",
    "r13_peer_basis",
    "r13_modified_zscore",
    "r13_scale_basis",
    "recommended_review",
    "retained",
    "phase9_schema_version",
)

ANOMALY_REPORT_COLUMNS: Tuple[str, ...] = (
    "anomaly_id",
    "rule_id",
    "rule_name",
    "anomaly_level",
    "entity_id",
    "observation_id",
    "flight_cell_id",
    "consolidation_cell_id",
    "collection_round_id",
    "round_sort_key",
    "round_alignment",
    "series_id",
    "metric_name",
    "metric_value",
    "threshold_value",
    "threshold_label",
    "comparison_basis",
    "severity",
    "severity_before_context",
    "evaluation_status",
    "evaluability_reason",
    "source_set",
    "market_movement_class",
    "recommended_review",
    "explanation",
    "phase9_schema_version",
)

OBSERVATION_MAP_COLUMNS: Tuple[str, ...] = (
    "observation_id",
    "source_canonical",
    "total_fare_normalized",
    "availability_status",
    "price_state",
    "participation_status",
    "flight_cell_id",
    "consolidation_cell_id",
    "collection_round_id",
    "round_sort_key",
    "round_alignment",
    "series_id",
    "observation_rule_ids",
    "observation_severity_max",
    "flight_cell_severity_max",
    "consolidation_cell_severity_max",
    "inherited_severity_max",
    "recommended_review",
    "retained",
    "phase9_schema_version",
)

SERIES_DIAGNOSTICS_COLUMNS: Tuple[str, ...] = (
    "series_id",
    "origin",
    "destination",
    "travel_date",
    "fare_class",
    "advance_purchase_window",
    "total_cell_count",
    "anchored_priced_round_count",
    "unaligned_round_count",
    "no_price_cell_count",
    "first_round_sort_key",
    "last_round_sort_key",
    "min_fare",
    "max_fare",
    "median_fare",
    "history_status",
    "r05_evaluable_count",
    "r05_flag_count",
    "r06_evaluable_count",
    "r06_flag_count",
    "max_abs_round_over_round_change",
    "max_abs_cumulative_drift",
    "persistent_flag_count",
    "persistent_flag_rounds",
    "phase9_schema_version",
)

SOURCE_RELIABILITY_COLUMNS: Tuple[str, ...] = (
    "source",
    "observation_count",
    "priced_observation_count",
    "sold_out_observation_count",
    "participating_observation_count",
    "flight_cell_participation_count",
    "observation_flag_count",
    "high_severity_observation_count",
    "r07_involvement_count",
    "r13_involvement_count",
    "median_abs_relative_deviation_from_flight_median",
    "max_abs_relative_deviation_from_flight_median",
    "phase9_schema_version",
)


class AnomalyOutput(object):
    """Container for the five Phase 9 outputs."""

    def __init__(self, cells, report, observations, series, sources):
        self.cells = cells
        self.report = report
        self.observations = observations
        self.series = series
        self.sources = sources


# ---------------------------------------------------------------------------
# Input handling
# ---------------------------------------------------------------------------
def read_phase8_csv(path: str) -> pd.DataFrame:
    """Read a Phase 8 output as strings, preserving blanks verbatim.

    dtype=str and keep_default_na=False match the Phase 7/8 readers exactly,
    so an empty cell stays an empty string instead of becoming NaN.
    """
    if not os.path.exists(path):
        raise R.AnomalyRuleError("Phase 8 input not found: %s" % path)
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def require_columns(
    frame: pd.DataFrame, columns: Sequence[str], label: str
) -> None:
    """Fail loudly when an expected Phase 8 column is absent."""
    missing = [name for name in columns if name not in frame.columns]
    if missing:
        raise R.AnomalyRuleError(
            "%s is missing required column(s): %s" % (label, ", ".join(missing))
        )


# ---------------------------------------------------------------------------
# Report emission
# ---------------------------------------------------------------------------
def _emit(
    rows: List[Dict[str, str]],
    rule_id: str,
    entity_id: str,
    status: str,
    severity: str = R.SEVERITY_NONE,
    severity_before: str = "",
    reason: str = R.REASON_EVALUATED,
    metric_name: str = "",
    metric_value: str = "",
    threshold_value: str = "",
    comparison_basis: str = "",
    source_set: str = "",
    market_class: str = R.MARKET_NOT_APPLICABLE,
    explanation: str = "",
    observation_id: str = "",
    flight_cell_id: str = "",
    consolidation_cell_id: str = "",
    collection_round_id: str = "",
    round_sort_key: str = "",
    round_alignment: str = "",
    series_id: str = "",
) -> Dict[str, str]:
    """Append one fully-explained rule evaluation to the report.

    Only FLAGGED and NOT_EVALUABLE evaluations are emitted (see ruling 3 in
    the module docstring).
    """
    if status not in R.EVALUATION_STATUSES:
        raise R.AnomalyRuleError("unknown evaluation status: %s" % status)
    if rule_id not in R.RULE_IDS:
        raise R.AnomalyRuleError("unknown rule id: %s" % rule_id)

    ceiling = R.RULE_MAX_SEVERITY[rule_id]
    capped = R.cap_severity(severity, ceiling)

    row = {
        "anomaly_id": R.anomaly_id(rule_id, entity_id),
        "rule_id": rule_id,
        "rule_name": R.RULE_NAMES[rule_id],
        "anomaly_level": R.RULE_LEVELS[rule_id],
        "entity_id": entity_id,
        "observation_id": observation_id,
        "flight_cell_id": flight_cell_id,
        "consolidation_cell_id": consolidation_cell_id,
        "collection_round_id": collection_round_id,
        "round_sort_key": round_sort_key,
        "round_alignment": round_alignment,
        "series_id": series_id,
        "metric_name": metric_name,
        "metric_value": metric_value,
        "threshold_value": threshold_value,
        "threshold_label": R.RULE_THRESHOLD_LABELS[rule_id],
        "comparison_basis": comparison_basis,
        "severity": capped,
        "severity_before_context": severity_before,
        "evaluation_status": status,
        "evaluability_reason": reason,
        "source_set": source_set,
        "market_movement_class": market_class,
        "recommended_review": str(
            status == R.STATUS_FLAGGED and R.requires_review(capped)
        ),
        "explanation": explanation,
        "phase9_schema_version": R.PHASE9_SCHEMA_VERSION,
    }
    rows.append(row)
    return row


def _accumulate(
    summary: Dict[str, Dict[str, object]], entity_id: str, row: Dict[str, str]
) -> None:
    """Fold an emitted evaluation into a per-entity annotation summary."""
    bucket = summary.setdefault(
        entity_id,
        {"flagged": [], "not_evaluable": [], "severities": []},
    )
    if row["evaluation_status"] == R.STATUS_FLAGGED:
        flagged = bucket["flagged"]
        if isinstance(flagged, list):
            flagged.append(row["rule_id"])
        severities = bucket["severities"]
        if isinstance(severities, list):
            severities.append(row["severity"])
    elif row["evaluation_status"] == R.STATUS_NOT_EVALUABLE:
        not_evaluable = bucket["not_evaluable"]
        if isinstance(not_evaluable, list):
            not_evaluable.append(row["rule_id"])


def _joined(values: Sequence[str]) -> str:
    """Deterministic packed list of unique rule ids."""
    return R.LIST_SEPARATOR.join(sorted(set(values)))


# ---------------------------------------------------------------------------
# Observation-level rules: R01, R02, R03 (+ R04 framework row)
# ---------------------------------------------------------------------------
def evaluate_observations(
    observations: pd.DataFrame,
) -> Tuple[List[Dict[str, str]], Dict[str, Dict[str, object]]]:
    """Evaluate the structural observation-level rules.

    Structural rules are immune to dynamic-pricing protection: a nonpositive
    or nonnumeric fare, or a decomposition that does not add up, is a defect
    regardless of how many sources or flights agree.
    """
    require_columns(observations, REQUIRED_OBSERVATION_COLUMNS, "observation map")
    rows: List[Dict[str, str]] = []
    summary: Dict[str, Dict[str, object]] = {}

    for _, row in observations.iterrows():
        observation_id = R.clean_str(row["observation_id"])
        raw_fare = row["total_fare_normalized"]
        price_state = R.clean_str(row["price_state"])
        priced = R.is_priced(price_state)
        fare = R.parse_money(raw_fare)
        lineage = {
            "observation_id": observation_id,
            "flight_cell_id": R.clean_str(row["flight_cell_id"]),
            "consolidation_cell_id": R.clean_str(row["consolidation_cell_id"]),
            "collection_round_id": R.clean_str(row["collection_round_id"]),
            "round_sort_key": R.clean_str(row["round_sort_key"]),
            "round_alignment": R.clean_str(row["round_alignment"]),
            "series_id": R.product_series_key(
                row["origin_canonical"],
                row["destination_canonical"],
                row["travel_date_canonical"],
                row["fare_class_canonical"],
                row["advance_purchase_window"],
            ),
            "source_set": R.clean_str(row["source_canonical"]),
        }

        # --- R01 nonpositive fare -----------------------------------------
        if not priced:
            emitted = _emit(
                rows,
                "R01",
                observation_id,
                R.STATUS_NOT_EVALUABLE,
                reason=R.REASON_NO_PRICE_TO_EVALUATE,
                metric_name="total_fare_normalized",
                comparison_basis="price_state=%s" % price_state,
                explanation=(
                    "No price to test for positivity; the observation is "
                    "%s. It is retained, not dropped." % price_state
                ),
                **lineage
            )
            _accumulate(summary, observation_id, emitted)
        elif fare is None:
            emitted = _emit(
                rows,
                "R01",
                observation_id,
                R.STATUS_NOT_EVALUABLE,
                reason=R.REASON_NO_PRICE_TO_EVALUATE,
                metric_name="total_fare_normalized",
                metric_value=R.clean_str(raw_fare),
                explanation=(
                    "Fare does not parse as a number, so positivity cannot "
                    "be tested. R02 reports the nonnumeric value itself."
                ),
                **lineage
            )
            _accumulate(summary, observation_id, emitted)
        elif fare <= 0:
            emitted = _emit(
                rows,
                "R01",
                observation_id,
                R.STATUS_FLAGGED,
                severity=R.SEVERITY_HIGH,
                severity_before=R.SEVERITY_HIGH,
                metric_name="total_fare_normalized",
                metric_value=R.quantize_money(fare),
                threshold_value="0.00",
                comparison_basis="fare <= 0",
                explanation=(
                    "Structural anomaly: a priced observation cannot have a "
                    "fare of zero or less. Flagged HIGH and RETAINED for "
                    "review; Phase 9 never deletes it."
                ),
                **lineage
            )
            _accumulate(summary, observation_id, emitted)

        # --- R02 nonnumeric fare ------------------------------------------
        if R.is_missing(raw_fare):
            emitted = _emit(
                rows,
                "R02",
                observation_id,
                R.STATUS_NOT_EVALUABLE,
                reason=R.REASON_NO_PRICE_TO_EVALUATE,
                metric_name="total_fare_normalized",
                comparison_basis="price_state=%s" % price_state,
                explanation=(
                    "Fare is blank. A blank is an absence, not a nonnumeric "
                    "value, so R02 does not flag it and nothing is imputed."
                ),
                **lineage
            )
            _accumulate(summary, observation_id, emitted)
        elif not R.is_numeric_money(raw_fare):
            emitted = _emit(
                rows,
                "R02",
                observation_id,
                R.STATUS_FLAGGED,
                severity=R.SEVERITY_HIGH,
                severity_before=R.SEVERITY_HIGH,
                metric_name="total_fare_normalized",
                metric_value=R.clean_str(raw_fare),
                comparison_basis="Decimal parse",
                explanation=(
                    "Structural anomaly: fare value is non-empty but does "
                    "not parse as a number. Flagged HIGH and RETAINED."
                ),
                **lineage
            )
            _accumulate(summary, observation_id, emitted)

        # --- R03 component mismatch ---------------------------------------
        complete = R.parse_bool(row["fare_decomposition_complete"])
        base = R.parse_money(row["base_fare"])
        taxes = R.parse_money(row["taxes"])
        fees = R.parse_money(row["fees"])
        if complete is not True or base is None or taxes is None or fees is None:
            emitted = _emit(
                rows,
                "R03",
                observation_id,
                R.STATUS_NOT_EVALUABLE,
                reason=R.REASON_NO_DECOMPOSITION,
                metric_name="base_fare+taxes+fees",
                comparison_basis="fare_decomposition_complete=%s"
                % R.clean_str(row["fare_decomposition_complete"]),
                explanation=(
                    "Fare decomposition is incomplete. Phase 9 does NOT "
                    "reconstruct the missing component; the check is simply "
                    "not evaluable."
                ),
                **lineage
            )
            _accumulate(summary, observation_id, emitted)
        elif fare is None:
            emitted = _emit(
                rows,
                "R03",
                observation_id,
                R.STATUS_NOT_EVALUABLE,
                reason=R.REASON_NO_PRICE_TO_EVALUATE,
                metric_name="base_fare+taxes+fees",
                explanation="Total fare is unusable, so no comparison is possible.",
                **lineage
            )
            _accumulate(summary, observation_id, emitted)
        else:
            component_sum = base + taxes + fees
            difference = abs(fare - component_sum)
            if difference > R.R03_TOLERANCE:
                emitted = _emit(
                    rows,
                    "R03",
                    observation_id,
                    R.STATUS_FLAGGED,
                    severity=R.SEVERITY_HIGH,
                    severity_before=R.SEVERITY_HIGH,
                    metric_name="abs(total_fare - components)",
                    metric_value=R.quantize_money(difference),
                    threshold_value=R.quantize_money(R.R03_TOLERANCE),
                    comparison_basis="components=%s total=%s"
                    % (R.quantize_money(component_sum), R.quantize_money(fare)),
                    explanation=(
                        "Structural anomaly: decomposed components do not "
                        "reconcile with the total beyond the inherited "
                        "Phase 2 tolerance of INR 1.00. Flagged HIGH and "
                        "RETAINED; nothing is corrected."
                    ),
                    **lineage
                )
                _accumulate(summary, observation_id, emitted)

    # --- R04 single framework row (ruling 4) -------------------------------
    _emit(
        rows,
        "R04",
        "RULE_FRAMEWORK",
        R.STATUS_NOT_EVALUABLE,
        reason=R.REASON_NO_FROZEN_CALIBRATION_SNAPSHOT,
        metric_name="plausible_fare_range",
        comparison_basis="affected_observations=%d" % len(observations.index),
        explanation=(
            "R04 exists in the framework but is INACTIVE. No independently "
            "frozen calibration snapshot exists, and deriving a plausible "
            "range from the very observations being screened would let the "
            "data define its own anomaly boundary. One framework row is "
            "emitted instead of an identical row per observation."
        ),
    )

    return (rows, summary)


# ---------------------------------------------------------------------------
# Flight-cell rules: R07, R08
# ---------------------------------------------------------------------------
def evaluate_flight_cells(
    flight_cells: pd.DataFrame,
    cell_context: Dict[str, Dict[str, object]],
) -> Tuple[List[Dict[str, str]], Dict[str, Dict[str, object]]]:
    """Evaluate source dispersion and source-level attribution.

    R07 measures RELATIVE dispersion so that expensive routes are not flagged
    merely for being expensive. R08 refuses to attribute a deviation to a
    specific source unless at least three sources are present.
    """
    require_columns(flight_cells, REQUIRED_FLIGHT_CELL_COLUMNS, "flight cell report")
    rows: List[Dict[str, str]] = []
    summary: Dict[str, Dict[str, object]] = {}

    for _, row in flight_cells.iterrows():
        flight_cell_id = R.clean_str(row["flight_cell_id"])
        cell_id = R.clean_str(row["consolidation_cell_id"])
        context = cell_context.get(cell_id, {})
        market_class = str(context.get("market_movement_class", R.MARKET_INDETERMINATE))
        lineage = {
            "flight_cell_id": flight_cell_id,
            "consolidation_cell_id": cell_id,
            "collection_round_id": R.clean_str(row["collection_round_id"]),
            "round_sort_key": R.clean_str(row["round_sort_key"]),
            "round_alignment": str(context.get("round_alignment", "")),
            "series_id": str(context.get("series_id", "")),
            "source_set": R.clean_str(row["flight_sources"]),
        }

        source_count = R.parse_int(row["flight_source_count"])
        priced = R.is_priced(row["price_state"])
        minimum = R.parse_money(row["flight_min_fare"])
        maximum = R.parse_money(row["flight_max_fare"])
        source_fares = R.parse_source_fare_map(row["flight_source_level_fares"])

        # --- R07 abnormal source dispersion -------------------------------
        if not priced:
            emitted = _emit(
                rows,
                "R07",
                flight_cell_id,
                R.STATUS_NOT_EVALUABLE,
                reason=R.REASON_NO_PRICE_TO_EVALUATE,
                metric_name="relative_source_spread",
                comparison_basis="price_state=%s" % R.clean_str(row["price_state"]),
                market_class=market_class,
                explanation="No priced sources, so dispersion is undefined.",
                **lineage
            )
            _accumulate(summary, flight_cell_id, emitted)
        elif source_count is None or source_count < 2:
            emitted = _emit(
                rows,
                "R07",
                flight_cell_id,
                R.STATUS_NOT_EVALUABLE,
                reason=R.REASON_SINGLE_SOURCE,
                metric_name="relative_source_spread",
                comparison_basis="flight_source_count=%s"
                % R.clean_str(row["flight_source_count"]),
                market_class=market_class,
                explanation=(
                    "Dispersion needs at least two priced sources. A single "
                    "source cannot disagree with itself."
                ),
                **lineage
            )
            _accumulate(summary, flight_cell_id, emitted)
        else:
            spread = R.relative_spread(minimum, maximum)
            if spread is None:
                emitted = _emit(
                    rows,
                    "R07",
                    flight_cell_id,
                    R.STATUS_NOT_EVALUABLE,
                    reason=R.REASON_NO_PRICE_TO_EVALUATE,
                    metric_name="relative_source_spread",
                    market_class=market_class,
                    explanation="Min/max fares unusable for a relative spread.",
                    **lineage
                )
                _accumulate(summary, flight_cell_id, emitted)
            elif spread > R.R07_DISPERSION_THRESHOLD:
                before = R.SEVERITY_REVIEW
                after = R.apply_market_context("R07", before, market_class)
                emitted = _emit(
                    rows,
                    "R07",
                    flight_cell_id,
                    R.STATUS_FLAGGED,
                    severity=after,
                    severity_before=before,
                    metric_name="relative_source_spread",
                    metric_value=R.quantize_ratio(spread),
                    threshold_value=R.quantize_ratio(R.R07_DISPERSION_THRESHOLD),
                    comparison_basis="(max-min)/min over %d sources" % source_count,
                    market_class=market_class,
                    explanation=(
                        "Sources disagree by more than the prototype "
                        "dispersion threshold of 15 percent for the same "
                        "flight. Relative spread is used so that costly "
                        "routes are not flagged for being costly."
                    ),
                    **lineage
                )
                _accumulate(summary, flight_cell_id, emitted)

        # --- R08 source-level deviation -----------------------------------
        if source_count is None or source_count < R.R08_MIN_SOURCES:
            emitted = _emit(
                rows,
                "R08",
                flight_cell_id,
                R.STATUS_NOT_EVALUABLE,
                reason=R.REASON_INSUFFICIENT_SOURCE_COUNT,
                metric_name="source_level_deviation",
                comparison_basis="flight_source_count=%s min_required=%d"
                % (R.clean_str(row["flight_source_count"]), R.R08_MIN_SOURCES),
                market_class=market_class,
                explanation=(
                    "Attribution needs at least 3 sources. With 2 sources "
                    "there is a difference but no way to say which source "
                    "is deviant, and Phase 9 will not pretend otherwise."
                ),
                **lineage
            )
            _accumulate(summary, flight_cell_id, emitted)
        else:
            fares = sorted(source_fares.values())
            centre = R.median(fares)
            worst_source = ""
            worst_deviation: Optional[Decimal] = None
            for name in sorted(source_fares.keys()):
                if centre is None or centre <= 0:
                    continue
                deviation = abs((source_fares[name] - centre) / centre)
                if worst_deviation is None or deviation > worst_deviation:
                    worst_deviation = deviation
                    worst_source = name
            if worst_deviation is None:
                emitted = _emit(
                    rows,
                    "R08",
                    flight_cell_id,
                    R.STATUS_NOT_EVALUABLE,
                    reason=R.REASON_NO_PRICE_TO_EVALUATE,
                    metric_name="source_level_deviation",
                    market_class=market_class,
                    explanation="Source-level fares unusable for attribution.",
                    **lineage
                )
                _accumulate(summary, flight_cell_id, emitted)
            elif worst_deviation > R.R07_DISPERSION_THRESHOLD:
                before = R.SEVERITY_REVIEW
                after = R.apply_market_context("R08", before, market_class)
                emitted = _emit(
                    rows,
                    "R08",
                    flight_cell_id,
                    R.STATUS_FLAGGED,
                    severity=after,
                    severity_before=before,
                    metric_name="max_abs_source_deviation_from_median",
                    metric_value=R.quantize_ratio(worst_deviation),
                    threshold_value=R.quantize_ratio(R.R07_DISPERSION_THRESHOLD),
                    comparison_basis="source=%s median=%s over %d sources"
                    % (worst_source, R.quantize_money(centre), source_count),
                    market_class=market_class,
                    explanation=(
                        "With 3 or more sources a specific source can be "
                        "attributed as the deviant one relative to the "
                        "source median."
                    ),
                    **lineage
                )
                _accumulate(summary, flight_cell_id, emitted)

    return (rows, summary)


# ---------------------------------------------------------------------------
# Cell context
# ---------------------------------------------------------------------------
def build_cell_context(cells: pd.DataFrame) -> Dict[str, Dict[str, object]]:
    """Derive per-cell lineage and the dynamic-pricing coherence class.

    The consolidated fare used everywhere is `consolidated_fare_normalized`.
    `alt_source_first_fare` is DIAGNOSTIC ONLY and is deliberately never read
    by any rule.
    """
    require_columns(cells, REQUIRED_CELL_COLUMNS, "consolidated cells")
    context: Dict[str, Dict[str, object]] = {}

    for _, row in cells.iterrows():
        cell_id = R.clean_str(row["consolidation_cell_id"])
        source_count = R.parse_int(row["participating_source_count"])
        flight_count = R.parse_int(row["flight_instance_count"])
        context[cell_id] = {
            "consolidation_cell_id": cell_id,
            "series_id": R.product_series_key(
                row["origin_canonical"],
                row["destination_canonical"],
                row["travel_date_canonical"],
                row["fare_class_canonical"],
                row["advance_purchase_window"],
            ),
            "peer_key": R.peer_group_key(
                row["origin_canonical"],
                row["destination_canonical"],
                row["fare_class_canonical"],
            ),
            "collection_round_id": R.clean_str(row["collection_round_id"]),
            "round_sort_key": R.clean_str(row["round_sort_key"]),
            "round_alignment": R.clean_str(row["round_alignment"]),
            "price_state": R.clean_str(row["price_state"]),
            "fare": R.parse_money(row["consolidated_fare_normalized"]),
            "source_count": source_count,
            "flight_instance_count": flight_count,
            "participating_sources": R.clean_str(row["participating_sources"]),
            "source_coverage": R.clean_str(row["source_coverage"]),
            "market_movement_class": R.classify_market_movement(
                source_count, flight_count
            ),
            "r13_peer_basis": R.PEER_BASIS_NONE,
            "r13_zscore": "",
            "r13_scale_basis": R.SCALE_BASIS_NONE,
        }
    return context


def _lineage_of(context: Dict[str, object]) -> Dict[str, str]:
    """Standard lineage kwargs for an emitted cell-level evaluation."""
    return {
        "consolidation_cell_id": str(context.get("consolidation_cell_id", "")),
        "collection_round_id": str(context.get("collection_round_id", "")),
        "round_sort_key": str(context.get("round_sort_key", "")),
        "round_alignment": str(context.get("round_alignment", "")),
        "series_id": str(context.get("series_id", "")),
        "source_set": str(context.get("participating_sources", "")),
    }


# ---------------------------------------------------------------------------
# Consolidation-cell rules: R09, R11, R12, R13
# ---------------------------------------------------------------------------
def evaluate_consolidation_cells(
    cells: pd.DataFrame, context: Dict[str, Dict[str, object]]
) -> Tuple[List[Dict[str, str]], Dict[str, Dict[str, object]]]:
    """Evaluate coverage/context diagnostics and the robust peer outlier rule.

    R09/R11/R12 are INFO diagnostics. Thin coverage, a sold-out cell and an
    unaligned round are facts about collection, not economic anomalies, and
    are never escalated above INFO.

    R13 is the one genuinely statistical rule. Unaligned rounds ARE evaluated
    here because a cross-sectional peer comparison does not depend on the
    round being anchored.
    """
    rows: List[Dict[str, str]] = []
    summary: Dict[str, Dict[str, object]] = {}

    # --- R13 peer populations, built once and reused --------------------
    within_round: Dict[Tuple[str, str], List[Decimal]] = {}
    across_rounds: Dict[str, List[Decimal]] = {}
    for cell_id in sorted(context.keys()):
        entry = context[cell_id]
        fare = entry.get("fare")
        if not R.is_priced(str(entry.get("price_state", ""))) or fare is None:
            continue
        if not isinstance(fare, Decimal):
            continue
        peer_key = str(entry.get("peer_key", ""))
        round_id = str(entry.get("collection_round_id", ""))
        within_round.setdefault((peer_key, round_id), []).append(fare)
        across_rounds.setdefault(peer_key, []).append(fare)

    for _, row in cells.iterrows():
        cell_id = R.clean_str(row["consolidation_cell_id"])
        entry = context[cell_id]
        lineage = _lineage_of(entry)
        market_class = str(entry.get("market_movement_class", R.MARKET_INDETERMINATE))
        price_state = str(entry.get("price_state", ""))
        fare = entry.get("fare")
        source_count = entry.get("source_count")

        # --- R09 thin source coverage ---------------------------------
        if isinstance(source_count, int) and source_count <= R.R09_THIN_SOURCE_COUNT:
            emitted = _emit(
                rows,
                "R09",
                cell_id,
                R.STATUS_FLAGGED,
                severity=R.SEVERITY_INFO,
                severity_before=R.SEVERITY_INFO,
                metric_name="participating_source_count",
                metric_value=str(source_count),
                threshold_value=str(R.R09_THIN_SOURCE_COUNT),
                comparison_basis="source_coverage=%s"
                % str(entry.get("source_coverage", "")),
                market_class=market_class,
                explanation=(
                    "Informational only: this cell rests on a single "
                    "source, so it has no cross-source corroboration. Thin "
                    "coverage is a collection limitation, NOT an economic "
                    "anomaly, and is never escalated above INFO."
                ),
                **lineage
            )
            _accumulate(summary, cell_id, emitted)

        # --- R11 no-price cell ----------------------------------------
        if price_state != R.PRICE_STATE_PRICED:
            emitted = _emit(
                rows,
                "R11",
                cell_id,
                R.STATUS_FLAGGED,
                severity=R.SEVERITY_INFO,
                severity_before=R.SEVERITY_INFO,
                metric_name="price_state",
                metric_value=price_state,
                comparison_basis="consolidation_status=%s"
                % R.clean_str(row["consolidation_status"])
                if "consolidation_status" in cells.columns
                else "",
                market_class=market_class,
                explanation=(
                    "Informational only: the cell carries no price because "
                    "every contributing observation was sold out. The cell "
                    "is RETAINED with no imputation and no zero price."
                ),
                **lineage
            )
            _accumulate(summary, cell_id, emitted)

        # --- R12 unaligned round context ------------------------------
        if R.is_unaligned_alignment(str(entry.get("round_alignment", ""))):
            emitted = _emit(
                rows,
                "R12",
                cell_id,
                R.STATUS_FLAGGED,
                severity=R.SEVERITY_INFO,
                severity_before=R.SEVERITY_INFO,
                metric_name="round_alignment",
                metric_value=str(entry.get("round_alignment", "")),
                comparison_basis="expected=%s" % R.ROUND_ALIGNMENT_ANCHORED,
                market_class=market_class,
                explanation=(
                    "Informational only: this cell was collected outside "
                    "the anchored round schedule, so it lacks normal "
                    "aligned-round context. It is recorded here rather "
                    "than silently discarded, and it is excluded only from "
                    "the R05/R06 temporal history."
                ),
                **lineage
            )
            _accumulate(summary, cell_id, emitted)

        # --- R13 robust cross-sectional peer outlier ------------------
        if not R.is_priced(price_state) or not isinstance(fare, Decimal):
            emitted = _emit(
                rows,
                "R13",
                cell_id,
                R.STATUS_NOT_EVALUABLE,
                reason=R.REASON_NO_PRICE_TO_EVALUATE,
                metric_name="modified_zscore",
                comparison_basis="price_state=%s" % price_state,
                market_class=market_class,
                explanation="No price, so no cross-sectional comparison is possible.",
                **lineage
            )
            _accumulate(summary, cell_id, emitted)
            continue

        peer_key = str(entry.get("peer_key", ""))
        round_id = str(entry.get("collection_round_id", ""))
        population = within_round.get((peer_key, round_id), [])
        basis = R.PEER_BASIS_WITHIN_ROUND
        if len(population) < R.R13_MIN_PEER_COUNT:
            population = across_rounds.get(peer_key, [])
            basis = R.PEER_BASIS_WIDENED

        if len(population) < 3:
            emitted = _emit(
                rows,
                "R13",
                cell_id,
                R.STATUS_NOT_EVALUABLE,
                reason=R.REASON_INSUFFICIENT_PEERS,
                metric_name="modified_zscore",
                metric_value="",
                comparison_basis="peer_basis=%s peer_count=%d"
                % (basis, len(population)),
                market_class=market_class,
                explanation=(
                    "Fewer than 3 peers even after widening, so a robust "
                    "centre and scale cannot be estimated."
                ),
                **lineage
            )
            _accumulate(summary, cell_id, emitted)
            entry["r13_peer_basis"] = basis
            continue

        zscore, scale_basis, centre, scale = R.robust_zscore(fare, population)
        entry["r13_peer_basis"] = basis
        entry["r13_scale_basis"] = scale_basis

        if zscore is None:
            emitted = _emit(
                rows,
                "R13",
                cell_id,
                R.STATUS_NOT_EVALUABLE,
                reason=R.REASON_ZERO_DISPERSION,
                metric_name="modified_zscore",
                comparison_basis="peer_basis=%s peer_count=%d MAD=0 IQR=0"
                % (basis, len(population)),
                market_class=market_class,
                explanation=(
                    "Peers are effectively identical (MAD and IQR are both "
                    "zero), so no outlier statement is possible. Phase 9 "
                    "reports NOT_EVALUABLE rather than dividing by zero."
                ),
                **lineage
            )
            _accumulate(summary, cell_id, emitted)
            continue

        entry["r13_zscore"] = R.quantize_ratio(zscore)
        magnitude = abs(zscore)
        raw_severity = R.severity_for_zscore(magnitude)
        if raw_severity == R.SEVERITY_NONE:
            continue

        # A widened comparison mixes rounds and is weaker evidence, so it can
        # never reach HIGH no matter how extreme the z-score is.
        ceiling = R.PEER_BASIS_MAX_SEVERITY[basis]
        capped = R.cap_severity(raw_severity, ceiling)
        final = R.apply_market_context("R13", capped, market_class)
        emitted = _emit(
            rows,
            "R13",
            cell_id,
            R.STATUS_FLAGGED,
            severity=final,
            severity_before=raw_severity,
            metric_name="modified_zscore",
            metric_value=R.quantize_ratio(zscore),
            threshold_value=R.quantize_ratio(R.R13_Z_REVIEW),
            comparison_basis="peer_basis=%s peer_count=%d scale=%s centre=%s"
            % (basis, len(population), scale_basis, R.quantize_money(centre)),
            market_class=market_class,
            explanation=(
                "Robust peer comparison against %d peers in the same "
                "(origin, destination, fare_class) group. This is a "
                "cross-sectional outlier statement, not a claim that the "
                "fare is wrong; an expensive fare is never rewritten."
                % len(population)
            ),
            **lineage
        )
        _accumulate(summary, cell_id, emitted)

    return (rows, summary)


# ---------------------------------------------------------------------------
# Product-series rules: R05, R06, R10
# ---------------------------------------------------------------------------
def evaluate_series(
    context: Dict[str, Dict[str, object]]
) -> Tuple[List[Dict[str, str]], List[Dict[str, str]], Dict[str, Dict[str, object]]]:
    """Evaluate backward-only temporal rules and emit series diagnostics.

    Temporal history is ANCHORED + PRICED cells only, ordered by
    `round_sort_key`. Unaligned rounds are excluded from the history because
    an off-schedule capture is not comparable to an anchored one; they remain
    fully visible through R12 and are still screened by R13.

    Evaluation is strictly backward-looking: point i is compared only with
    points before it, so no future information can leak into a flag.
    """
    rows: List[Dict[str, str]] = []
    series_rows: List[Dict[str, str]] = []
    summary: Dict[str, Dict[str, object]] = {}

    grouped: Dict[str, List[Dict[str, object]]] = {}
    for cell_id in sorted(context.keys()):
        entry = context[cell_id]
        grouped.setdefault(str(entry.get("series_id", "")), []).append(entry)

    for series_id in sorted(grouped.keys()):
        members = grouped[series_id]
        history = [
            entry
            for entry in members
            if R.is_anchored_alignment(str(entry.get("round_alignment", "")))
            and R.is_priced(str(entry.get("price_state", "")))
            and isinstance(entry.get("fare"), Decimal)
        ]
        history.sort(
            key=lambda item: (
                str(item.get("round_sort_key", "")),
                str(item.get("consolidation_cell_id", "")),
            )
        )
        unaligned = [
            entry
            for entry in members
            if R.is_unaligned_alignment(str(entry.get("round_alignment", "")))
        ]
        no_price = [
            entry
            for entry in members
            if not R.is_priced(str(entry.get("price_state", "")))
        ]

        fares: List[Decimal] = []
        for entry in history:
            value = entry.get("fare")
            if isinstance(value, Decimal):
                fares.append(value)

        deltas: List[Optional[Decimal]] = [None]
        for index in range(1, len(history)):
            previous = history[index - 1].get("fare")
            current = history[index].get("fare")
            if isinstance(previous, Decimal) and isinstance(current, Decimal):
                deltas.append(R.relative_change(previous, current))
            else:
                deltas.append(None)

        r05_evaluable = 0
        r05_flags = 0
        r06_evaluable = 0
        r06_flags = 0
        max_movement: Optional[Decimal] = None
        max_drift: Optional[Decimal] = None
        persistent_rounds: List[str] = []

        # --- R05 / R06 over the anchored priced history -------------------
        for index in range(len(history)):
            entry = history[index]
            cell_id = str(entry.get("consolidation_cell_id", ""))
            lineage = _lineage_of(entry)
            market_class = str(
                entry.get("market_movement_class", R.MARKET_INDETERMINATE)
            )
            prior = index

            if prior < R.R05_MIN_PRIOR_PRICED_ROUNDS:
                emitted = _emit(
                    rows,
                    "R05",
                    cell_id,
                    R.STATUS_NOT_EVALUABLE,
                    reason=R.REASON_INSUFFICIENT_PRIOR_ROUNDS,
                    metric_name="round_over_round_change",
                    comparison_basis="prior_priced_rounds=%d required=%d"
                    % (prior, R.R05_MIN_PRIOR_PRICED_ROUNDS),
                    market_class=market_class,
                    explanation=(
                        "Not enough prior anchored priced rounds to judge a "
                        "movement. Phase 9 does not manufacture history."
                    ),
                    **lineage
                )
                _accumulate(summary, cell_id, emitted)
            else:
                change = deltas[index]
                if change is None:
                    emitted = _emit(
                        rows,
                        "R05",
                        cell_id,
                        R.STATUS_NOT_EVALUABLE,
                        reason=R.REASON_NO_PRICE_TO_EVALUATE,
                        metric_name="round_over_round_change",
                        market_class=market_class,
                        explanation="Previous fare is zero or unusable as a base.",
                        **lineage
                    )
                    _accumulate(summary, cell_id, emitted)
                else:
                    r05_evaluable += 1
                    magnitude = abs(change)
                    if max_movement is None or magnitude > max_movement:
                        max_movement = magnitude
                    raw_severity = R.severity_for_movement(magnitude)
                    if raw_severity != R.SEVERITY_NONE:
                        final = R.apply_market_context(
                            "R05", raw_severity, market_class
                        )
                        emitted = _emit(
                            rows,
                            "R05",
                            cell_id,
                            R.STATUS_FLAGGED,
                            severity=final,
                            severity_before=raw_severity,
                            metric_name="round_over_round_change",
                            metric_value=R.quantize_ratio(change),
                            threshold_value=R.quantize_ratio(
                                R.R05_REVIEW_THRESHOLD
                            ),
                            comparison_basis="previous=%s current=%s prior_rounds=%d"
                            % (
                                R.quantize_money(history[index - 1].get("fare")),
                                R.quantize_money(entry.get("fare")),
                                prior,
                            ),
                            market_class=market_class,
                            explanation=(
                                "Round-over-round movement exceeded the "
                                "PROTOTYPE_CALIBRATION threshold of 15 "
                                "percent (30 percent for HIGH). A sharp "
                                "move is not assumed to be an error; if it "
                                "is corroborated across sources and "
                                "flights the severity is downgraded."
                            ),
                            **lineage
                        )
                        _accumulate(summary, cell_id, emitted)
                        r05_flags += 1
                        if R.requires_review(final):
                            persistent_rounds.append(
                                str(entry.get("collection_round_id", ""))
                            )

            if prior < R.R06_MIN_PRIOR_PRICED_ROUNDS:
                emitted = _emit(
                    rows,
                    "R06",
                    cell_id,
                    R.STATUS_NOT_EVALUABLE,
                    reason=R.REASON_INSUFFICIENT_PRIOR_ROUNDS,
                    metric_name="cumulative_drift",
                    comparison_basis="prior_priced_rounds=%d required=%d"
                    % (prior, R.R06_MIN_PRIOR_PRICED_ROUNDS),
                    market_class=market_class,
                    explanation=(
                        "Sustained drift needs at least 4 prior anchored "
                        "priced rounds plus a 3-step run."
                    ),
                    **lineage
                )
                _accumulate(summary, cell_id, emitted)
            else:
                run = [deltas[index - offset] for offset in range(R.R06_RUN_LENGTH)]
                if any(value is None for value in run):
                    emitted = _emit(
                        rows,
                        "R06",
                        cell_id,
                        R.STATUS_NOT_EVALUABLE,
                        reason=R.REASON_NO_PRICE_TO_EVALUATE,
                        metric_name="cumulative_drift",
                        market_class=market_class,
                        explanation="A delta in the run window is undefined.",
                        **lineage
                    )
                    _accumulate(summary, cell_id, emitted)
                else:
                    r06_evaluable += 1
                    signs = set()
                    for value in run:
                        if isinstance(value, Decimal):
                            signs.add(R.sign_of(value))
                    start = history[index - R.R06_RUN_LENGTH].get("fare")
                    finish = entry.get("fare")
                    cumulative = None
                    if isinstance(start, Decimal) and isinstance(finish, Decimal):
                        cumulative = R.relative_change(start, finish)
                    if cumulative is not None:
                        drift_magnitude = abs(cumulative)
                        if max_drift is None or drift_magnitude > max_drift:
                            max_drift = drift_magnitude
                        same_sign = len(signs) == 1 and 0 not in signs
                        if (
                            same_sign
                            and drift_magnitude > R.R06_CUMULATIVE_THRESHOLD
                        ):
                            raw_severity = R.SEVERITY_REVIEW
                            if drift_magnitude > R.R05_HIGH_THRESHOLD:
                                raw_severity = R.SEVERITY_HIGH
                            final = R.apply_market_context(
                                "R06", raw_severity, market_class
                            )
                            emitted = _emit(
                                rows,
                                "R06",
                                cell_id,
                                R.STATUS_FLAGGED,
                                severity=final,
                                severity_before=raw_severity,
                                metric_name="cumulative_drift",
                                metric_value=R.quantize_ratio(cumulative),
                                threshold_value=R.quantize_ratio(
                                    R.R06_CUMULATIVE_THRESHOLD
                                ),
                                comparison_basis=(
                                    "run_length=%d same_sign=True start=%s end=%s"
                                    % (
                                        R.R06_RUN_LENGTH,
                                        R.quantize_money(start),
                                        R.quantize_money(finish),
                                    )
                                ),
                                market_class=market_class,
                                explanation=(
                                    "Three consecutive same-sign moves with "
                                    "cumulative change beyond the "
                                    "PROTOTYPE_CALIBRATION threshold of 15 "
                                    "percent. This detects slow drift that "
                                    "no single round-over-round step would "
                                    "reveal."
                                ),
                                **lineage
                            )
                            _accumulate(summary, cell_id, emitted)
                            r06_flags += 1
                            if R.requires_review(final):
                                persistent_rounds.append(
                                    str(entry.get("collection_round_id", ""))
                                )

        # --- R10 insufficient history (series level) ----------------------
        history_status = "SUFFICIENT_FOR_R05"
        if len(history) <= R.R05_MIN_PRIOR_PRICED_ROUNDS:
            history_status = "INSUFFICIENT_FOR_R05"
            first = members[0] if members else {}
            emitted = _emit(
                rows,
                "R10",
                series_id,
                R.STATUS_FLAGGED,
                severity=R.SEVERITY_INFO,
                severity_before=R.SEVERITY_INFO,
                metric_name="anchored_priced_round_count",
                metric_value=str(len(history)),
                threshold_value=str(R.R05_MIN_PRIOR_PRICED_ROUNDS + 1),
                comparison_basis="series has %d anchored priced round(s)"
                % len(history),
                market_class=R.MARKET_NOT_APPLICABLE,
                explanation=(
                    "Informational diagnostic: this product series has too "
                    "few anchored priced rounds for any temporal rule to "
                    "fire. Recorded honestly instead of manufacturing "
                    "historical context."
                ),
                series_id=series_id,
                round_alignment=str(first.get("round_alignment", "")),
            )
            _accumulate(summary, series_id, emitted)

        parts = series_id.replace("SERIES::", "", 1).split("|")
        while len(parts) < 5:
            parts.append("")

        series_rows.append(
            {
                "series_id": series_id,
                "origin": parts[0],
                "destination": parts[1],
                "travel_date": parts[2],
                "fare_class": parts[3],
                "advance_purchase_window": parts[4],
                "total_cell_count": str(len(members)),
                "anchored_priced_round_count": str(len(history)),
                "unaligned_round_count": str(len(unaligned)),
                "no_price_cell_count": str(len(no_price)),
                "first_round_sort_key": str(
                    history[0].get("round_sort_key", "") if history else ""
                ),
                "last_round_sort_key": str(
                    history[-1].get("round_sort_key", "") if history else ""
                ),
                "min_fare": R.quantize_money(min(fares)) if fares else "",
                "max_fare": R.quantize_money(max(fares)) if fares else "",
                "median_fare": R.quantize_money(R.median(fares)) if fares else "",
                "history_status": history_status,
                "r05_evaluable_count": str(r05_evaluable),
                "r05_flag_count": str(r05_flags),
                "r06_evaluable_count": str(r06_evaluable),
                "r06_flag_count": str(r06_flags),
                "max_abs_round_over_round_change": R.quantize_ratio(max_movement),
                "max_abs_cumulative_drift": R.quantize_ratio(max_drift),
                "persistent_flag_count": str(len(persistent_rounds)),
                "persistent_flag_rounds": R.LIST_SEPARATOR.join(
                    sorted(set(persistent_rounds))
                ),
                "phase9_schema_version": R.PHASE9_SCHEMA_VERSION,
            }
        )

    return (rows, series_rows, summary)


# ---------------------------------------------------------------------------
# Summary helpers
# ---------------------------------------------------------------------------
def _merge_summaries(
    target: Dict[str, Dict[str, object]], source: Dict[str, Dict[str, object]]
) -> None:
    """Fold one per-entity summary into another."""
    for entity_id in sorted(source.keys()):
        incoming = source[entity_id]
        bucket = target.setdefault(
            entity_id, {"flagged": [], "not_evaluable": [], "severities": []}
        )
        for key in ("flagged", "not_evaluable", "severities"):
            existing = bucket[key]
            addition = incoming.get(key, [])
            if isinstance(existing, list) and isinstance(addition, list):
                existing.extend(addition)


def _severity_max(
    summary: Dict[str, Dict[str, object]], entity_id: str
) -> str:
    """Highest flagged severity recorded for an entity."""
    bucket = summary.get(entity_id, {})
    severities = bucket.get("severities", [])
    if isinstance(severities, list) and severities:
        return R.max_severity([str(value) for value in severities])
    return R.SEVERITY_NONE


def _rule_ids(summary: Dict[str, Dict[str, object]], entity_id: str, key: str) -> str:
    """Packed sorted rule ids of a given kind for an entity."""
    bucket = summary.get(entity_id, {})
    values = bucket.get(key, [])
    if isinstance(values, list):
        return _joined([str(value) for value in values])
    return ""


# ---------------------------------------------------------------------------
# Source reliability
# ---------------------------------------------------------------------------
def build_source_reliability(
    observations: pd.DataFrame,
    flight_cells: pd.DataFrame,
    cell_context: Dict[str, Dict[str, object]],
    observation_summary: Dict[str, Dict[str, object]],
    report_rows: Sequence[Dict[str, str]],
) -> List[Dict[str, str]]:
    """Per-source diagnostics.

    This is a DIAGNOSTIC report only. It deliberately produces no weights and
    no rankings that could feed an index; Phase 9 must never imply that one
    source should count for more than another.
    """
    flight_medians: Dict[str, Optional[Decimal]] = {}
    flight_source_sets: Dict[str, List[str]] = {}
    for _, row in flight_cells.iterrows():
        flight_cell_id = R.clean_str(row["flight_cell_id"])
        fare_map = R.parse_source_fare_map(row["flight_source_level_fares"])
        flight_medians[flight_cell_id] = R.median(sorted(fare_map.values()))
        flight_source_sets[flight_cell_id] = R.split_list(row["flight_sources"])

    r07_cells = set()
    r13_cells = set()
    for row in report_rows:
        if row["evaluation_status"] != R.STATUS_FLAGGED:
            continue
        if row["rule_id"] == "R07":
            r07_cells.add(row["flight_cell_id"])
        elif row["rule_id"] == "R13":
            r13_cells.add(row["consolidation_cell_id"])

    stats: Dict[str, Dict[str, object]] = {}
    for _, row in observations.iterrows():
        source = R.clean_str(row["source_canonical"])
        bucket = stats.setdefault(
            source,
            {
                "observation_count": 0,
                "priced": 0,
                "sold_out": 0,
                "participating": 0,
                "flight_cells": set(),
                "flags": 0,
                "high": 0,
                "r07": set(),
                "r13": set(),
                "deviations": [],
            },
        )
        bucket["observation_count"] = int(bucket["observation_count"]) + 1

        price_state = R.clean_str(row["price_state"])
        if R.is_priced(price_state):
            bucket["priced"] = int(bucket["priced"]) + 1
        else:
            bucket["sold_out"] = int(bucket["sold_out"]) + 1
        if R.clean_str(row["participation_status"]) == "PARTICIPATED":
            bucket["participating"] = int(bucket["participating"]) + 1

        flight_cell_id = R.clean_str(row["flight_cell_id"])
        cell_id = R.clean_str(row["consolidation_cell_id"])
        flight_set = bucket["flight_cells"]
        if isinstance(flight_set, set) and flight_cell_id:
            flight_set.add(flight_cell_id)

        observation_id = R.clean_str(row["observation_id"])
        flagged = observation_summary.get(observation_id, {}).get("flagged", [])
        if isinstance(flagged, list) and flagged:
            bucket["flags"] = int(bucket["flags"]) + len(flagged)
        if _severity_max(observation_summary, observation_id) == R.SEVERITY_HIGH:
            bucket["high"] = int(bucket["high"]) + 1

        if flight_cell_id in r07_cells:
            involved = bucket["r07"]
            if isinstance(involved, set):
                involved.add(flight_cell_id)
        if cell_id in r13_cells:
            involved = bucket["r13"]
            if isinstance(involved, set):
                involved.add(cell_id)

        fare = R.parse_money(row["total_fare_normalized"])
        centre = flight_medians.get(flight_cell_id)
        if fare is not None and isinstance(centre, Decimal) and centre > 0:
            deviations = bucket["deviations"]
            if isinstance(deviations, list):
                deviations.append(abs((fare - centre) / centre))

    rows: List[Dict[str, str]] = []
    for source in sorted(stats.keys()):
        bucket = stats[source]
        deviations = bucket["deviations"]
        deviation_list: List[Decimal] = []
        if isinstance(deviations, list):
            for value in deviations:
                if isinstance(value, Decimal):
                    deviation_list.append(value)
        flight_set = bucket["flight_cells"]
        r07_set = bucket["r07"]
        r13_set = bucket["r13"]
        rows.append(
            {
                "source": source,
                "observation_count": str(bucket["observation_count"]),
                "priced_observation_count": str(bucket["priced"]),
                "sold_out_observation_count": str(bucket["sold_out"]),
                "participating_observation_count": str(bucket["participating"]),
                "flight_cell_participation_count": str(
                    len(flight_set) if isinstance(flight_set, set) else 0
                ),
                "observation_flag_count": str(bucket["flags"]),
                "high_severity_observation_count": str(bucket["high"]),
                "r07_involvement_count": str(
                    len(r07_set) if isinstance(r07_set, set) else 0
                ),
                "r13_involvement_count": str(
                    len(r13_set) if isinstance(r13_set, set) else 0
                ),
                "median_abs_relative_deviation_from_flight_median": R.quantize_ratio(
                    R.median(deviation_list) if deviation_list else None
                ),
                "max_abs_relative_deviation_from_flight_median": R.quantize_ratio(
                    max(deviation_list) if deviation_list else None
                ),
                "phase9_schema_version": R.PHASE9_SCHEMA_VERSION,
            }
        )
    return rows


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------
def run_anomaly_detection(
    cells: pd.DataFrame,
    flight_cells: pd.DataFrame,
    observations: pd.DataFrame,
) -> AnomalyOutput:
    """Screen Phase 8 outputs and return the five Phase 9 frames.

    Row counts are invariant by contract: every input row appears exactly
    once in the corresponding output. Phase 9 annotates, never filters.
    """
    require_columns(cells, REQUIRED_CELL_COLUMNS, "consolidated cells")
    require_columns(flight_cells, REQUIRED_FLIGHT_CELL_COLUMNS, "flight cell report")
    require_columns(observations, REQUIRED_OBSERVATION_COLUMNS, "observation map")

    input_cell_rows = len(cells.index)
    input_flight_rows = len(flight_cells.index)
    input_observation_rows = len(observations.index)

    context = build_cell_context(cells)

    cell_rows, cell_summary = evaluate_consolidation_cells(cells, context)
    series_report_rows, series_rows, series_summary = evaluate_series(context)
    flight_rows, flight_summary = evaluate_flight_cells(flight_cells, context)
    observation_rows, observation_summary = evaluate_observations(observations)

    combined_cell_summary: Dict[str, Dict[str, object]] = {}
    _merge_summaries(combined_cell_summary, cell_summary)
    _merge_summaries(combined_cell_summary, series_summary)

    report_rows: List[Dict[str, str]] = []
    report_rows.extend(cell_rows)
    report_rows.extend(series_report_rows)
    report_rows.extend(flight_rows)
    report_rows.extend(observation_rows)
    report_rows.sort(
        key=lambda item: (
            item["rule_id"],
            item["anomaly_level"],
            item["entity_id"],
            item["evaluation_status"],
        )
    )

    # --- primary output: Phase 8 cells carried through + annotations ------
    annotated = cells.copy(deep=True)
    annotation: Dict[str, List[str]] = {name: [] for name in CELL_ANNOTATION_COLUMNS}
    for _, row in cells.iterrows():
        cell_id = R.clean_str(row["consolidation_cell_id"])
        entry = context[cell_id]
        severity = _severity_max(combined_cell_summary, cell_id)
        flagged = _rule_ids(combined_cell_summary, cell_id, "flagged")
        annotation["series_id"].append(str(entry.get("series_id", "")))
        annotation["anomaly_rule_ids"].append(flagged)
        annotation["anomaly_flag_count"].append(
            str(len(flagged.split(R.LIST_SEPARATOR)) if flagged else 0)
        )
        annotation["anomaly_severity_max"].append(severity)
        annotation["not_evaluable_rule_ids"].append(
            _rule_ids(combined_cell_summary, cell_id, "not_evaluable")
        )
        annotation["market_movement_class"].append(
            str(entry.get("market_movement_class", ""))
        )
        annotation["r13_peer_basis"].append(str(entry.get("r13_peer_basis", "")))
        annotation["r13_modified_zscore"].append(str(entry.get("r13_zscore", "")))
        annotation["r13_scale_basis"].append(str(entry.get("r13_scale_basis", "")))
        annotation["recommended_review"].append(str(R.requires_review(severity)))
        # Constant True: proof that Phase 9 never removes a cell.
        annotation["retained"].append("True")
        annotation["phase9_schema_version"].append(R.PHASE9_SCHEMA_VERSION)

    for name in CELL_ANNOTATION_COLUMNS:
        annotated[name] = annotation[name]

    # --- observation anomaly map -----------------------------------------
    observation_out: List[Dict[str, str]] = []
    for _, row in observations.iterrows():
        observation_id = R.clean_str(row["observation_id"])
        flight_cell_id = R.clean_str(row["flight_cell_id"])
        cell_id = R.clean_str(row["consolidation_cell_id"])
        own = _severity_max(observation_summary, observation_id)
        flight_severity = _severity_max(flight_summary, flight_cell_id)
        cell_severity = _severity_max(combined_cell_summary, cell_id)
        inherited = R.max_severity([own, flight_severity, cell_severity])
        entry = context.get(cell_id, {})
        observation_out.append(
            {
                "observation_id": observation_id,
                "source_canonical": R.clean_str(row["source_canonical"]),
                "total_fare_normalized": R.clean_str(row["total_fare_normalized"]),
                "availability_status": R.clean_str(row["availability_status"]),
                "price_state": R.clean_str(row["price_state"]),
                "participation_status": R.clean_str(row["participation_status"]),
                "flight_cell_id": flight_cell_id,
                "consolidation_cell_id": cell_id,
                "collection_round_id": R.clean_str(row["collection_round_id"]),
                "round_sort_key": R.clean_str(row["round_sort_key"]),
                "round_alignment": R.clean_str(row["round_alignment"]),
                "series_id": str(entry.get("series_id", "")),
                "observation_rule_ids": _rule_ids(
                    observation_summary, observation_id, "flagged"
                ),
                "observation_severity_max": own,
                "flight_cell_severity_max": flight_severity,
                "consolidation_cell_severity_max": cell_severity,
                "inherited_severity_max": inherited,
                "recommended_review": str(R.requires_review(inherited)),
                "retained": "True",
                "phase9_schema_version": R.PHASE9_SCHEMA_VERSION,
            }
        )

    source_rows = build_source_reliability(
        observations, flight_cells, context, observation_summary, report_rows
    )

    report_frame = pd.DataFrame(report_rows, columns=list(ANOMALY_REPORT_COLUMNS))
    observation_frame = pd.DataFrame(
        observation_out, columns=list(OBSERVATION_MAP_COLUMNS)
    )
    series_frame = pd.DataFrame(series_rows, columns=list(SERIES_DIAGNOSTICS_COLUMNS))
    source_frame = pd.DataFrame(source_rows, columns=list(SOURCE_RELIABILITY_COLUMNS))

    # --- invariants -------------------------------------------------------
    if len(annotated.index) != input_cell_rows:
        raise R.AnomalyRuleError("consolidated row count changed during Phase 9")
    if len(observation_frame.index) != input_observation_rows:
        raise R.AnomalyRuleError("observation row count changed during Phase 9")
    if len(flight_cells.index) != input_flight_rows:
        raise R.AnomalyRuleError("flight cell row count changed during Phase 9")
    for name in R.FORBIDDEN_OUTPUT_FIELDS:
        for frame in (annotated, report_frame, observation_frame, series_frame):
            if name in frame.columns:
                raise R.AnomalyRuleError(
                    "Phase 9 must not emit forbidden field: %s" % name
                )

    return AnomalyOutput(
        annotated, report_frame, observation_frame, series_frame, source_frame
    )
