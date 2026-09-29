"""VAYU INDEX Phase 10 -- route-level aggregation rules and constants.

Phase 10 aggregates Phase 9 consolidation cells up to ROUTE level using the
Phase 5 canonical (undirected, alphabetic-IATA) route identity.

LOCKED CONTRACT
---------------
D1  route_id is UNDIRECTED and must agree with the Phase 5 make_route_id
    implementation in scripts/build_vayu_route_basket.py.  Phase 10 never
    re-implements route identity semantics; it mirrors them.
D2  Two grains are produced.  Grain A is the non-lossy series grain, Grain B
    is the coarser class/round grain.  Grain B never replaces Grain A.
D3  The route statistic is the MIDPOINT MEDIAN reused verbatim from Phase 7
    (src/consolidation/rules.py::midpoint_median): for an even count the
    result is the midpoint of the two central values.  All money is Decimal,
    ROUND_HALF_UP, 2 decimal places.
D4  All 15 Phase 5 basket routes appear in the basket-scoped outputs.  Routes
    with no observations are emitted explicitly as NO_OBSERVATIONS.  Nothing
    is imputed and nothing is zero-filled.
D5  travel_date is a real grouping key in Grain A.
D6  Anomalies are annotated and counted, never used to exclude a cell.  No
    index eligibility concept exists in Phase 10.
D7  Basket-scoped and off-basket outputs are separate tables.
D8  Phase 5 make_route_id remains the single source of truth for identity.
D9  traffic_weight is carried as METADATA ONLY and is never applied.

Observed direction is NEVER reversed.  observed_origin, observed_destination
and observed_directed_pair always report the market as it was collected; the
canonical route_id is an additional grouping key layered on top.
"""

from decimal import Decimal, InvalidOperation

from ..consolidation.rules import MONEY_QUANTUM, midpoint_median
from ..normalization.rules import (
    CURRENCY_CODE,
    CURRENCY_SOURCE,
    MONEY_ROUNDING,
    PRICE_STATE_NO_PRICE_CELL,
    PRICE_STATE_PRICED,
    PRICE_STATE_SOLD_OUT,
)

PHASE10_SCHEMA_VERSION = "phase10-v1"

# -- separators ------------------------------------------------------------
LIST_SEPARATOR = ";"
KEY_SEPARATOR = "|"
ROUTE_ID_SEPARATOR = "-"

# -- route identity (D1 / D8) ---------------------------------------------
ROUTE_ID_IS_UNDIRECTED = True
ROUTE_ID_ORDERING = "ALPHABETIC_IATA"
ROUTE_ID_SOURCE_OF_TRUTH = "scripts/build_vayu_route_basket.py::make_route_id"
CANONICALIZATION_SOURCE = "PHASE5_MAKE_ROUTE_ID"

DIRECTION_EXACT = "EXACT_KEY_MATCH"
DIRECTION_CANONICALIZED = "CANONICALIZED_FROM_REVERSE"
DIRECTION_OFF_BASKET = "OFF_BASKET"
DIRECTION_RELATIONS = (
    DIRECTION_EXACT,
    DIRECTION_CANONICALIZED,
    DIRECTION_OFF_BASKET,
)

# -- basket scope (D4 / D7) ------------------------------------------------
BASKET_MEMBER = "IN_BASKET"
BASKET_NON_MEMBER = "NOT_IN_BASKET"
BASKET_SCOPE_IN = "BASKET_SCOPED"
BASKET_SCOPE_OUT = "OFF_BASKET_DIAGNOSTIC"

COVERAGE_OBSERVED = "OBSERVED"
COVERAGE_OBSERVED_CANONICAL = "OBSERVED_VIA_CANONICAL_KEY"
COVERAGE_NONE = "NO_OBSERVATIONS"
COVERAGE_STATUSES = (COVERAGE_OBSERVED, COVERAGE_OBSERVED_CANONICAL, COVERAGE_NONE)

ROUTE_PRICE_STATE_PRICED = "PRICED"
ROUTE_PRICE_STATE_NO_PRICE = "NO_PRICE"
ROUTE_PRICE_STATE_NO_OBSERVATIONS = "NO_OBSERVATIONS"

# -- aggregation statistic (D3) -------------------------------------------
AGGREGATION_STATISTIC = "MIDPOINT_MEDIAN"
AGGREGATION_STATISTIC_SOURCE = "src/consolidation/rules.py::midpoint_median"
MONEY_DECIMAL_PLACES = 2
RATIO_QUANTUM = Decimal("0.000001")

# -- severity vocabulary (inherited verbatim from Phase 9) -----------------
SEVERITY_NONE = "NONE"
SEVERITY_INFO = "INFO"
SEVERITY_REVIEW = "REVIEW"
SEVERITY_HIGH = "HIGH"
SEVERITY_ORDER = (SEVERITY_NONE, SEVERITY_INFO, SEVERITY_REVIEW, SEVERITY_HIGH)
SEVERITY_RANK = {name: position for position, name in enumerate(SEVERITY_ORDER)}

# -- grains (D2 / D5) ------------------------------------------------------
GRAIN_A_FIELDS = (
    "route_id",
    "fare_class",
    "advance_purchase_window",
    "travel_date",
    "collection_round_id",
)
GRAIN_B_FIELDS = ("route_id", "fare_class", "collection_round_id")
GRAIN_A_ID_PREFIX = "RSERIES::"
GRAIN_B_ID_PREFIX = "RCLASS::"

# -- fields Phase 10 must never emit (D6 / D9) -----------------------------
FORBIDDEN_OUTPUT_FIELDS = (
    "index_eligible",
    "index_value",
    "index_level",
    "basket_weight",
    "source_weight",
    "basket_weighted_fare",
    "weighted_fare",
    "imputed_fare",
)

# -- declarative guard flags (asserted by tests and by the verifier) -------
APPLIES_TRAFFIC_WEIGHTS = False
APPLIES_SOURCE_WEIGHTS = False
PERFORMS_IMPUTATION = False
DELETES_OBSERVATIONS = False
EXCLUDES_BY_ANOMALY_SEVERITY = False
SUBSTITUTES_ZERO_FOR_MISSING = False
MODIFIES_BASKET = False
REVERSES_OBSERVED_DIRECTION = False
PRODUCES_ROUTE_AGGREGATE_ANOMALIES = False
USES_MACHINE_LEARNING = False
USES_RANDOMNESS = False


class RouteAggregationRuleError(ValueError):
    """Raised when a Phase 10 rule precondition is violated."""


# ==========================================================================
# small value helpers
# ==========================================================================
def clean_str(value):
    if value is None:
        return ""
    return str(value).strip()


def is_missing(value):
    return clean_str(value) == ""


def parse_money(value):
    """Return a Decimal fare, or None when the value is genuinely absent.

    Absent stays absent: Phase 10 never substitutes zero for a missing fare.
    """
    text = clean_str(value)
    if text == "":
        return None
    try:
        return Decimal(text)
    except (InvalidOperation, ArithmeticError):
        raise RouteAggregationRuleError("cannot parse money value %r" % (value,))


def parse_int(value, default=0):
    text = clean_str(value)
    if text == "":
        return default
    try:
        return int(Decimal(text))
    except (InvalidOperation, ArithmeticError, ValueError):
        raise RouteAggregationRuleError("cannot parse integer value %r" % (value,))


def parse_bool(value):
    text = clean_str(value)
    if text == "True":
        return True
    if text == "False":
        return False
    if text == "":
        return False
    raise RouteAggregationRuleError("cannot parse strict boolean %r" % (value,))


def split_list(value):
    text = clean_str(value)
    if text == "":
        return []
    return [item.strip() for item in text.split(LIST_SEPARATOR) if item.strip() != ""]


def join_list(values):
    return LIST_SEPARATOR.join(values)


def sorted_unique(values):
    return sorted({clean_str(item) for item in values if clean_str(item) != ""})


def quantize_money(value):
    if value is None:
        return None
    return Decimal(value).quantize(MONEY_QUANTUM, rounding=MONEY_ROUNDING)


def quantize_ratio(value):
    if value is None:
        return None
    return Decimal(value).quantize(RATIO_QUANTUM, rounding=MONEY_ROUNDING)


# ==========================================================================
# D1 / D8 -- canonical route identity
# ==========================================================================
def canonical_route_id(first_code, second_code):
    """Undirected alphabetic-IATA route key, mirroring Phase 5 make_route_id.

    Phase 5 body:  if code1 <= code2: return "%s-%s" % (code1, code2)
    The observed direction is preserved separately by the caller; this
    function only produces the canonical grouping key.
    """
    left = clean_str(first_code).upper()
    right = clean_str(second_code).upper()
    if left == "" or right == "":
        raise RouteAggregationRuleError(
            "canonical_route_id requires two non-empty airport codes"
        )
    if left == right:
        raise RouteAggregationRuleError(
            "canonical_route_id requires two distinct airport codes, got %r" % (left,)
        )
    if left <= right:
        return left + ROUTE_ID_SEPARATOR + right
    return right + ROUTE_ID_SEPARATOR + left


def directed_pair(origin, destination):
    """The observed market exactly as collected. Never reordered."""
    return clean_str(origin).upper() + ROUTE_ID_SEPARATOR + clean_str(destination).upper()


def direction_relation(observed_pair, route_id, in_basket):
    if not in_basket:
        return DIRECTION_OFF_BASKET
    if clean_str(observed_pair) == clean_str(route_id):
        return DIRECTION_EXACT
    return DIRECTION_CANONICALIZED


def coverage_status(observed_pairs, route_id):
    pairs = [clean_str(item) for item in observed_pairs if clean_str(item) != ""]
    if not pairs:
        return COVERAGE_NONE
    if all(pair == clean_str(route_id) for pair in pairs):
        return COVERAGE_OBSERVED
    return COVERAGE_OBSERVED_CANONICAL


# ==========================================================================
# D3 -- the route statistic
# ==========================================================================
def route_median(values):
    """Midpoint median reused from Phase 7, quantized to 2dp ROUND_HALF_UP."""
    materialized = [item for item in values if item is not None]
    if not materialized:
        raise RouteAggregationRuleError("route_median() requires at least one value")
    return quantize_money(midpoint_median(materialized))


def minimum(values):
    materialized = [item for item in values if item is not None]
    if not materialized:
        return None
    return quantize_money(min(materialized))


def maximum(values):
    materialized = [item for item in values if item is not None]
    if not materialized:
        return None
    return quantize_money(max(materialized))


def relative_spread(values, high=None, center=None):
    """Dispersion diagnostic: (max - min) / min, quantized to 6 dp.

    Denominated on the MINIMUM observed fare, not the median, so the ratio
    reads as how far above the cheapest observation the dearest one sits.
    Accepts either a sequence of Decimals, or an explicit (low, high, center)
    triple in which `center` is accepted and ignored so the older call form
    stays valid. Returns None when it cannot be computed; a missing
    dispersion is never reported as zero.

    Diagnostic only: this value never feeds the aggregated median.
    """
    if high is None and center is None:
        materialized = [item for item in values if item is not None]
        if not materialized:
            return None
        low_value = min(materialized)
        high_value = max(materialized)
    else:
        low_value = values
        high_value = high
    if low_value is None or high_value is None:
        return None
    if Decimal(low_value) == 0:
        return None
    return quantize_ratio(
        (Decimal(high_value) - Decimal(low_value)) / Decimal(low_value)
    )


# ==========================================================================
# D6 -- severity annotation helpers (annotate, never exclude)
# ==========================================================================
def normalize_severity(value):
    text = clean_str(value)
    if text == "":
        return SEVERITY_NONE
    if text not in SEVERITY_RANK:
        raise RouteAggregationRuleError("unknown severity %r" % (value,))
    return text


def max_severity(values):
    best = SEVERITY_NONE
    for value in values:
        candidate = normalize_severity(value)
        if SEVERITY_RANK[candidate] > SEVERITY_RANK[best]:
            best = candidate
    return best


def severity_counts(values):
    counts = {name: 0 for name in SEVERITY_ORDER}
    for value in values:
        counts[normalize_severity(value)] += 1
    return counts


# ==========================================================================
# grain keys and stable series identifiers
# ==========================================================================
def grain_a_key(route_id, fare_class, window, travel_date, round_id):
    return (
        clean_str(route_id),
        clean_str(fare_class),
        clean_str(window),
        clean_str(travel_date),
        clean_str(round_id),
    )


def grain_b_key(route_id, fare_class, round_id):
    return (clean_str(route_id), clean_str(fare_class), clean_str(round_id))


def grain_a_id(key):
    return GRAIN_A_ID_PREFIX + KEY_SEPARATOR.join(key)


def grain_b_id(key):
    return GRAIN_B_ID_PREFIX + KEY_SEPARATOR.join(key)


__all__ = [
    "CURRENCY_CODE",
    "CURRENCY_SOURCE",
    "MONEY_QUANTUM",
    "MONEY_ROUNDING",
    "PRICE_STATE_NO_PRICE_CELL",
    "PRICE_STATE_PRICED",
    "PRICE_STATE_SOLD_OUT",
    "PHASE10_SCHEMA_VERSION",
    "RouteAggregationRuleError",
    "canonical_route_id",
    "route_median",
]
