"""VAYU INDEX - Phase 9 anomaly-detection rules and primitives.

Phase 9 SCREENS. It never repairs, imputes, deletes or re-prices anything.

This module holds only pure, deterministic primitives and the locked rule
contract (R01..R13). All engine orchestration lives in anomaly_engine.py.

Hard boundaries enforced by tests:
  * no machine learning, no random numbers, no RNG seeding
  * no index eligibility decision (Phase 10 owns that)
  * no route aggregation, no source weighting, no basket membership
  * no deletion or mutation of any observation
  * monetary math uses Decimal only

THRESHOLD HONESTY
-----------------
The 15% / 30% threshold family below is PROTOTYPE CALIBRATION. It was
informed by the same synthetic corpus that Phase 9 screens, which is a real
in-sample limitation and is recorded on every emitted row via
`threshold_label`. These are NOT official MoSPI thresholds and must never be
presented as universal statistical truths.

R04 deliberately stays inactive because there is no independently frozen
calibration snapshot. Deriving a plausible-fare range from the very
observations being screened would let the data define its own anomaly
boundary, which is circular.
"""

from decimal import Decimal, InvalidOperation
from typing import Dict, List, Optional, Sequence, Tuple

from ..validation.rules import FARE_COMPONENT_TOLERANCE
from ..normalization.rules import (
    MONEY_QUANTUM,
    PRICE_STATE_MISSING_PRICE,
    PRICE_STATE_NO_PRICE_CELL,
    PRICE_STATE_PRICED,
    PRICE_STATE_SOLD_OUT,
)
from ..consolidation.rules import (
    ROUND_ALIGNMENT_ANCHORED,
    ROUND_ALIGNMENT_UNALIGNED,
    ROUND_ALIGNMENT_UNRESOLVED,
)


class AnomalyRuleError(Exception):
    """Raised when Phase 9 receives structurally unusable input."""


PHASE9_SCHEMA_VERSION = "phase9-v1"

# ---------------------------------------------------------------------------
# Anomaly levels (route aggregate is intentionally absent - out of scope)
# ---------------------------------------------------------------------------
LEVEL_OBSERVATION = "OBSERVATION"
LEVEL_FLIGHT_CELL = "FLIGHT_CELL"
LEVEL_CONSOLIDATION_CELL = "CONSOLIDATION_CELL"
LEVEL_PRODUCT_SERIES = "PRODUCT_SERIES"

ANOMALY_LEVELS: Tuple[str, ...] = (
    LEVEL_OBSERVATION,
    LEVEL_FLIGHT_CELL,
    LEVEL_CONSOLIDATION_CELL,
    LEVEL_PRODUCT_SERIES,
)

# ---------------------------------------------------------------------------
# Severity ladder
# ---------------------------------------------------------------------------
SEVERITY_NONE = "NONE"
SEVERITY_INFO = "INFO"
SEVERITY_REVIEW = "REVIEW"
SEVERITY_HIGH = "HIGH"

SEVERITY_ORDER: Tuple[str, ...] = (
    SEVERITY_NONE,
    SEVERITY_INFO,
    SEVERITY_REVIEW,
    SEVERITY_HIGH,
)
SEVERITY_RANK: Dict[str, int] = {name: i for i, name in enumerate(SEVERITY_ORDER)}

# Only these severities ask a human to look.
REVIEW_SEVERITIES: Tuple[str, ...] = (SEVERITY_REVIEW, SEVERITY_HIGH)

# ---------------------------------------------------------------------------
# Evaluation status
# ---------------------------------------------------------------------------
STATUS_PASS = "PASS"
STATUS_FLAGGED = "FLAGGED"
STATUS_NOT_EVALUABLE = "NOT_EVALUABLE"

EVALUATION_STATUSES: Tuple[str, ...] = (
    STATUS_PASS,
    STATUS_FLAGGED,
    STATUS_NOT_EVALUABLE,
)

# ---------------------------------------------------------------------------
# Evaluability reasons
# ---------------------------------------------------------------------------
REASON_EVALUATED = "EVALUATED"
REASON_INSUFFICIENT_PRIOR_ROUNDS = "INSUFFICIENT_PRIOR_ROUNDS"
REASON_EXCLUDED_UNALIGNED_ROUND = "EXCLUDED_UNALIGNED_ROUND"
REASON_NO_FROZEN_CALIBRATION_SNAPSHOT = "NO_FROZEN_CALIBRATION_SNAPSHOT"
REASON_INSUFFICIENT_SOURCE_COUNT = "INSUFFICIENT_SOURCE_COUNT_FOR_ATTRIBUTION"
REASON_NO_PRICE_TO_EVALUATE = "NO_PRICE_TO_EVALUATE"
REASON_INSUFFICIENT_PEERS = "INSUFFICIENT_PEER_COUNT"
REASON_ZERO_DISPERSION = "ZERO_PEER_DISPERSION"
REASON_NO_DECOMPOSITION = "FARE_DECOMPOSITION_INCOMPLETE"
REASON_SINGLE_SOURCE = "SINGLE_SOURCE_CELL"

# ---------------------------------------------------------------------------
# Threshold calibration labels
# ---------------------------------------------------------------------------
CALIBRATION_PROTOTYPE = "PROTOTYPE_CALIBRATION"
CALIBRATION_STRUCTURAL = "STRUCTURAL_INVARIANT"
CALIBRATION_INHERITED_PHASE2 = "INHERITED_PHASE2_TOLERANCE"
CALIBRATION_ROBUST_STATISTIC = "ROBUST_STATISTIC_CONVENTION"
CALIBRATION_NONE = "NOT_APPLICABLE"
CALIBRATION_ABSENT = "NO_FROZEN_CALIBRATION_SNAPSHOT"

# Provenance of the prototype family, recorded in the methodology doc too.
CALIBRATION_SOURCE = "VAYU synthetic screening corpus (783 raw / 778 canonical)"
CALIBRATION_DATE = "2026-09-10"
CALIBRATION_IS_IN_SAMPLE = True

# ---------------------------------------------------------------------------
# Locked thresholds
# ---------------------------------------------------------------------------
# R03 - reused verbatim from Phase 2, not re-derived here.
R03_TOLERANCE = Decimal(str(FARE_COMPONENT_TOLERANCE))

# R05 - round-over-round movement
R05_MIN_PRIOR_PRICED_ROUNDS = 3
R05_REVIEW_THRESHOLD = Decimal("0.15")
R05_HIGH_THRESHOLD = Decimal("0.30")

# R06 - sustained drift
R06_MIN_PRIOR_PRICED_ROUNDS = 4
R06_RUN_LENGTH = 3
R06_CUMULATIVE_THRESHOLD = Decimal("0.15")

# R07 - source dispersion (relative, never absolute rupees)
R07_DISPERSION_THRESHOLD = Decimal("0.15")

# R08 - source-level attribution
R08_MIN_SOURCES = 3

# R09 - thin coverage
R09_THIN_SOURCE_COUNT = 1

# R13 - robust peer outlier
R13_MIN_PEER_COUNT = 5
R13_MAD_SCALE = Decimal("0.6745")
R13_Z_REVIEW = Decimal("3.5")
R13_Z_HIGH = Decimal("7.0")
# Converts an IQR into an approximate standard deviation for the MAD==0 path.
R13_IQR_TO_SIGMA = Decimal("1.349")

# ---------------------------------------------------------------------------
# R13 peer basis
# ---------------------------------------------------------------------------
PEER_BASIS_WITHIN_ROUND = "WITHIN_ROUND"
PEER_BASIS_WIDENED = "WIDENED_ALL_ROUNDS"
PEER_BASIS_NONE = ""

# A widened comparison mixes rounds and is therefore weaker evidence.
PEER_BASIS_MAX_SEVERITY: Dict[str, str] = {
    PEER_BASIS_WITHIN_ROUND: SEVERITY_HIGH,
    PEER_BASIS_WIDENED: SEVERITY_REVIEW,
}

SCALE_BASIS_MAD = "MAD"
SCALE_BASIS_IQR = "IQR_FALLBACK"
SCALE_BASIS_NONE = ""

# ---------------------------------------------------------------------------
# Dynamic-pricing protection
# ---------------------------------------------------------------------------
MARKET_COHERENT = "COHERENT_MARKET_MOVEMENT"
MARKET_ISOLATED = "ISOLATED_DEVIATION"
MARKET_INDETERMINATE = "INDETERMINATE"
MARKET_NOT_APPLICABLE = "NOT_APPLICABLE"

# A genuine fare surge corroborated by breadth is still a real market move.
COHERENCE_MIN_SOURCES = 2
COHERENCE_MIN_FLIGHT_INSTANCES = 2

# Structural rules can never be softened by market coherence.
STRUCTURAL_RULE_IDS: Tuple[str, ...] = ("R01", "R02", "R03")

# Rules that consume backward-only temporal history.
TEMPORAL_RULE_IDS: Tuple[str, ...] = ("R05", "R06")

# ---------------------------------------------------------------------------
# Rule registry - the locked contract. Do not renumber or remove entries.
# ---------------------------------------------------------------------------
RULE_IDS: Tuple[str, ...] = (
    "R01",
    "R02",
    "R03",
    "R04",
    "R05",
    "R06",
    "R07",
    "R08",
    "R09",
    "R10",
    "R11",
    "R12",
    "R13",
)

RULE_NAMES: Dict[str, str] = {
    "R01": "R01_NONPOSITIVE_FARE",
    "R02": "R02_NONNUMERIC_FARE",
    "R03": "R03_COMPONENT_MISMATCH",
    "R04": "R04_FARE_OUT_OF_PLAUSIBLE_RANGE",
    "R05": "R05_ROUND_OVER_ROUND_JUMP",
    "R06": "R06_SUSTAINED_DRIFT",
    "R07": "R07_ABNORMAL_SOURCE_DISPERSION",
    "R08": "R08_SOURCE_LEVEL_DEVIATION",
    "R09": "R09_THIN_SOURCE_COVERAGE",
    "R10": "R10_INSUFFICIENT_HISTORY",
    "R11": "R11_NO_PRICE_CELL",
    "R12": "R12_UNALIGNED_ROUND_CONTEXT",
    "R13": "R13_CROSS_SECTIONAL_OUTLIER",
}

RULE_LEVELS: Dict[str, str] = {
    "R01": LEVEL_OBSERVATION,
    "R02": LEVEL_OBSERVATION,
    "R03": LEVEL_OBSERVATION,
    "R04": LEVEL_OBSERVATION,
    "R05": LEVEL_PRODUCT_SERIES,
    "R06": LEVEL_PRODUCT_SERIES,
    "R07": LEVEL_FLIGHT_CELL,
    "R08": LEVEL_FLIGHT_CELL,
    "R09": LEVEL_CONSOLIDATION_CELL,
    "R10": LEVEL_PRODUCT_SERIES,
    "R11": LEVEL_CONSOLIDATION_CELL,
    "R12": LEVEL_CONSOLIDATION_CELL,
    "R13": LEVEL_CONSOLIDATION_CELL,
}

# Maximum severity each rule may ever emit.
RULE_MAX_SEVERITY: Dict[str, str] = {
    "R01": SEVERITY_HIGH,
    "R02": SEVERITY_HIGH,
    "R03": SEVERITY_HIGH,
    "R04": SEVERITY_NONE,
    "R05": SEVERITY_HIGH,
    "R06": SEVERITY_HIGH,
    "R07": SEVERITY_REVIEW,
    "R08": SEVERITY_REVIEW,
    "R09": SEVERITY_INFO,
    "R10": SEVERITY_INFO,
    "R11": SEVERITY_INFO,
    "R12": SEVERITY_INFO,
    "R13": SEVERITY_HIGH,
}

RULE_THRESHOLD_LABELS: Dict[str, str] = {
    "R01": CALIBRATION_STRUCTURAL,
    "R02": CALIBRATION_STRUCTURAL,
    "R03": CALIBRATION_INHERITED_PHASE2,
    "R04": CALIBRATION_ABSENT,
    "R05": CALIBRATION_PROTOTYPE,
    "R06": CALIBRATION_PROTOTYPE,
    "R07": CALIBRATION_PROTOTYPE,
    "R08": CALIBRATION_NONE,
    "R09": CALIBRATION_STRUCTURAL,
    "R10": CALIBRATION_STRUCTURAL,
    "R11": CALIBRATION_STRUCTURAL,
    "R12": CALIBRATION_STRUCTURAL,
    "R13": CALIBRATION_ROBUST_STATISTIC,
}

# Rules deliberately inert on the current corpus, with the honest reason.
INACTIVE_RULES: Dict[str, str] = {
    "R04": REASON_NO_FROZEN_CALIBRATION_SNAPSHOT,
}

# Phase 10 owns index eligibility. Phase 9 must never emit this field.
FORBIDDEN_OUTPUT_FIELDS: Tuple[str, ...] = (
    "index_eligible",
    "index_value",
    "route_aggregate",
    "basket_weight",
    "source_weight",
)

USES_MACHINE_LEARNING = False
USES_RANDOMNESS = False
DELETES_OBSERVATIONS = False
PERFORMS_IMPUTATION = False
ALT_SOURCE_FIRST_FARE_IS_DIAGNOSTIC_ONLY = True


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------
def is_missing(value) -> bool:
    """True when a Phase 8 string cell carries no usable value."""
    if value is None:
        return True
    return str(value).strip() == ""


def clean_str(value) -> str:
    """Whitespace-trimmed string form. Never returns None."""
    if value is None:
        return ""
    return str(value).strip()


def parse_money(value) -> Optional[Decimal]:
    """Parse a monetary string into Decimal.

    Returns None when the value is missing OR nonnumeric. The caller decides
    whether that means 'no price to evaluate' (R01/R11) or 'nonnumeric fare'
    (R02); this primitive never guesses.
    """
    if is_missing(value):
        return None
    try:
        return Decimal(clean_str(value))
    except (InvalidOperation, ValueError, ArithmeticError):
        return None


def is_numeric_money(value) -> bool:
    """True when a non-empty value parses as a number."""
    if is_missing(value):
        return False
    return parse_money(value) is not None


def parse_int(value) -> Optional[int]:
    """Parse an integer-valued Phase 8 string column."""
    if is_missing(value):
        return None
    try:
        return int(Decimal(clean_str(value)))
    except (InvalidOperation, ValueError, ArithmeticError):
        return None


def parse_bool(value) -> Optional[bool]:
    """Strict boolean parsing of Phase 8 'True'/'False' strings."""
    text = clean_str(value)
    if text == "True":
        return True
    if text == "False":
        return False
    return None


# Phase 7/8 pack multi-valued columns with ';' (verified against the real
# outputs, e.g. flight_sources='Cleartrip;MMT'). '|' is the intra-identifier
# separator inside cell IDs and must not be used for list splitting.
LIST_SEPARATOR = ";"
SOURCE_FARE_SEPARATOR = "="


def split_list(value, separator: str = LIST_SEPARATOR) -> List[str]:
    """Split a Phase 7/8 packed list column, dropping empty members."""
    if is_missing(value):
        return []
    return [part.strip() for part in clean_str(value).split(separator) if part.strip()]


def parse_source_fare_map(value) -> Dict[str, Decimal]:
    """Parse a packed 'Source=fare;Source=fare' column into a mapping.

    Unparseable members are skipped rather than guessed at; the caller sees a
    smaller map and reports reduced evaluability instead of inventing fares.
    """
    result: Dict[str, Decimal] = {}
    for member in split_list(value):
        if SOURCE_FARE_SEPARATOR not in member:
            continue
        name, _, raw = member.partition(SOURCE_FARE_SEPARATOR)
        fare = parse_money(raw)
        if fare is None:
            continue
        result[name.strip()] = fare
    return result


# ---------------------------------------------------------------------------
# Deterministic robust statistics (Decimal only, no float, no numpy)
# ---------------------------------------------------------------------------
def median(values: Sequence[Decimal]) -> Optional[Decimal]:
    """Standard midpoint median. Even counts average the two middles.

    Matches the Phase 7 midpoint-median convention exactly so the two phases
    cannot disagree about what 'the middle' means.
    """
    if not values:
        return None
    ordered = sorted(values)
    count = len(ordered)
    mid = count // 2
    if count % 2 == 1:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / Decimal(2)


def median_absolute_deviation(values: Sequence[Decimal]) -> Optional[Decimal]:
    """MAD = median(|x - median(x)|)."""
    centre = median(values)
    if centre is None:
        return None
    return median([abs(value - centre) for value in values])


def percentile(values: Sequence[Decimal], fraction: Decimal) -> Optional[Decimal]:
    """Linear-interpolation percentile on a sorted copy.

    Deterministic and dependency-free; `fraction` is in [0, 1].
    """
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (Decimal(len(ordered)) - Decimal(1)) * fraction
    lower_index = int(position)
    upper_index = min(lower_index + 1, len(ordered) - 1)
    weight = position - Decimal(lower_index)
    lower = ordered[lower_index]
    upper = ordered[upper_index]
    return lower + (upper - lower) * weight


def interquartile_range(values: Sequence[Decimal]) -> Optional[Decimal]:
    """IQR = P75 - P25."""
    if not values:
        return None
    q1 = percentile(values, Decimal("0.25"))
    q3 = percentile(values, Decimal("0.75"))
    if q1 is None or q3 is None:
        return None
    return q3 - q1


def robust_zscore(
    value: Decimal, population: Sequence[Decimal]
) -> Tuple[Optional[Decimal], str, Optional[Decimal], Optional[Decimal]]:
    """Modified z-score with a documented IQR fallback.

    Primary:  z = 0.6745 * (x - median) / MAD
    Fallback: when MAD == 0 the population is degenerate under MAD, so an
              IQR-derived scale (IQR / 1.349) approximates sigma instead.
    Neither:  when MAD and IQR are both zero the peers are effectively
              identical, so no outlier statement is possible. The caller
              records NOT_EVALUABLE / ZERO_PEER_DISPERSION rather than
              dividing by zero or inventing a verdict.

    Returns (z, scale_basis, centre, scale).
    """
    if not population:
        return (None, SCALE_BASIS_NONE, None, None)
    centre = median(population)
    if centre is None:
        return (None, SCALE_BASIS_NONE, None, None)

    mad = median_absolute_deviation(population)
    if mad is not None and mad > 0:
        return (
            R13_MAD_SCALE * (value - centre) / mad,
            SCALE_BASIS_MAD,
            centre,
            mad,
        )

    iqr = interquartile_range(population)
    if iqr is not None and iqr > 0:
        scale = iqr / R13_IQR_TO_SIGMA
        return ((value - centre) / scale, SCALE_BASIS_IQR, centre, scale)

    return (None, SCALE_BASIS_NONE, centre, Decimal(0))


def relative_change(previous: Decimal, current: Decimal) -> Optional[Decimal]:
    """Signed fractional change from `previous` to `current`.

    Returns None when `previous` is zero, because a percentage change from a
    zero base is undefined. Phase 9 reports that as NOT_EVALUABLE instead of
    emitting an infinite movement.
    """
    if previous == 0:
        return None
    return (current - previous) / previous


def sign_of(value: Decimal) -> int:
    """Return -1, 0 or +1."""
    if value > 0:
        return 1
    if value < 0:
        return -1
    return 0


def relative_spread(
    minimum: Optional[Decimal], maximum: Optional[Decimal]
) -> Optional[Decimal]:
    """Relative dispersion (max - min) / min.

    Relative by construction: an absolute rupee spread would flag expensive
    routes purely for being expensive, which R07 must not do.
    """
    if minimum is None or maximum is None or minimum <= 0:
        return None
    return (maximum - minimum) / minimum


def quantize_ratio(value: Optional[Decimal]) -> str:
    """Format a ratio for output with 6 dp, or blank when absent."""
    if value is None:
        return ""
    return str(value.quantize(Decimal("0.000001")))


def quantize_money(value: Optional[Decimal]) -> str:
    """Format money for output at Phase 8's quantum, or blank when absent."""
    if value is None:
        return ""
    return str(value.quantize(MONEY_QUANTUM))


# ---------------------------------------------------------------------------
# Severity algebra
# ---------------------------------------------------------------------------
def cap_severity(severity: str, ceiling: str) -> str:
    """Clamp `severity` so it never exceeds `ceiling`."""
    if SEVERITY_RANK[severity] <= SEVERITY_RANK[ceiling]:
        return severity
    return ceiling


def downgrade_severity(severity: str, steps: int = 1) -> str:
    """Lower a severity by `steps` rungs, never below INFO.

    Used only by the dynamic-pricing coherence protection. A flag that fired
    is never erased entirely - it stays visible at a lower severity.
    """
    rank = SEVERITY_RANK[severity] - steps
    floor = SEVERITY_RANK[SEVERITY_INFO]
    if rank < floor:
        rank = floor
    return SEVERITY_ORDER[rank]


def max_severity(severities: Sequence[str]) -> str:
    """Highest severity in a collection, or NONE when empty."""
    if not severities:
        return SEVERITY_NONE
    return max(severities, key=lambda name: SEVERITY_RANK[name])


def severity_for_movement(magnitude: Decimal) -> str:
    """R05 severity ladder on an absolute fractional movement."""
    if magnitude > R05_HIGH_THRESHOLD:
        return SEVERITY_HIGH
    if magnitude > R05_REVIEW_THRESHOLD:
        return SEVERITY_REVIEW
    return SEVERITY_NONE


def severity_for_zscore(magnitude: Decimal) -> str:
    """R13 severity ladder on an absolute modified z-score."""
    if magnitude > R13_Z_HIGH:
        return SEVERITY_HIGH
    if magnitude > R13_Z_REVIEW:
        return SEVERITY_REVIEW
    return SEVERITY_NONE


def requires_review(severity: str) -> bool:
    """Whether a severity warrants human review."""
    return severity in REVIEW_SEVERITIES


# ---------------------------------------------------------------------------
# Dynamic-pricing protection
# ---------------------------------------------------------------------------
def classify_market_movement(
    source_count: Optional[int], flight_instance_count: Optional[int]
) -> str:
    """Classify whether a price movement is corroborated by breadth.

    A real airfare surge normally shows up across several sources and several
    flights at once. Breadth is therefore evidence of a GENUINE market move,
    not of a data defect, and such movements are downgraded one rung.

    A movement visible in only one source or one flight is more suspicious
    and keeps its severity.

    This classifier can only ever downgrade. It never escalates, and it is
    never applied to structural rules R01/R02/R03.
    """
    if source_count is None or flight_instance_count is None:
        return MARKET_INDETERMINATE
    if (
        source_count >= COHERENCE_MIN_SOURCES
        and flight_instance_count >= COHERENCE_MIN_FLIGHT_INSTANCES
    ):
        return MARKET_COHERENT
    if source_count <= 1 or flight_instance_count <= 1:
        return MARKET_ISOLATED
    return MARKET_INDETERMINATE


def apply_market_context(rule_id: str, severity: str, market_class: str) -> str:
    """Apply coherence protection to a fired severity.

    Structural violations (R01/R02/R03) are immune: a negative fare is a
    defect no matter how many sources agree on it.
    """
    if rule_id in STRUCTURAL_RULE_IDS:
        return severity
    if severity not in REVIEW_SEVERITIES:
        return severity
    if market_class == MARKET_COHERENT:
        return downgrade_severity(severity, 1)
    return severity


def is_priced(price_state: str) -> bool:
    """Whether a Phase 8 price_state carries an economically usable price."""
    return clean_str(price_state) == PRICE_STATE_PRICED


def is_anchored_alignment(round_alignment: str) -> bool:
    """Whether a round is anchored (eligible for temporal history)."""
    return clean_str(round_alignment) == ROUND_ALIGNMENT_ANCHORED


def is_unaligned_alignment(round_alignment: str) -> bool:
    """Whether a round is unaligned or unresolved."""
    return clean_str(round_alignment) in (
        ROUND_ALIGNMENT_UNALIGNED,
        ROUND_ALIGNMENT_UNRESOLVED,
    )


def product_series_key(
    origin: str,
    destination: str,
    travel_date: str,
    fare_class: str,
    advance_purchase_window: str,
) -> str:
    """Stable identifier for an economic product time series.

    Deliberately identical in shape to the Phase 7 economic identity so a
    series never silently spans two different products.
    """
    return "SERIES::%s|%s|%s|%s|%s" % (
        clean_str(origin),
        clean_str(destination),
        clean_str(travel_date),
        clean_str(fare_class),
        clean_str(advance_purchase_window),
    )


def peer_group_key(origin: str, destination: str, fare_class: str) -> str:
    """R13 peer-group identifier: (origin, destination, fare_class)."""
    return "PEER::%s|%s|%s" % (
        clean_str(origin),
        clean_str(destination),
        clean_str(fare_class),
    )


def anomaly_id(rule_id: str, entity_id: str) -> str:
    """Deterministic anomaly identifier."""
    return "ANOM::%s::%s" % (clean_str(rule_id), clean_str(entity_id))
