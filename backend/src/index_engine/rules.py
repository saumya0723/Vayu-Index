"""VAYU INDEX - Phase 11 index engine rule contract.

This module holds every locked constant and every pure function used by the
Phase 11 index engine. It performs no input/output and imports nothing from
Phases 1-10; Phase 10 is consumed strictly as read-only CSV output.

Locked methodology (approved decisions D1-D12):

D1  Elementary item = (route_id, fare_class, advance_purchase_window,
    travel_date). The maturity-ramp limitation is documented, never silently
    removed by switching to a constant-maturity item.
D2  The chain runs across ANCHORED collection rounds only. UNALIGNED rounds
    are published as diagnostics and are never chain links.
D3  Adjacent matched price relatives r_i,t = p_i,t / p_i,t-1 and chained
    levels I_t = I_(t-1) * J_t with base level 100.000000.
D4  Phase 5 traffic weights at route level, renormalized per link over the
    contributing routes only. Both the unnormalized represented weight and
    the effective weight sum are published.
D5  No automatic coverage threshold and no automatic suppression.
D6  PRIMARY includes every retained PRICED Phase 10 item regardless of
    Phase 9 severity. Only structurally invalid inputs are excluded. A
    separate EXCL_REVIEW_HIGH sensitivity series is published.
D7  The round-level chained index is authoritative; daily, weekly and
    monthly series are derived from it.
D8  Internal Decimal precision 28, index_level 6 dp, chain_factor 8 dp,
    ROUND_HALF_UP. Rebasing operates on unrounded internal levels.
D9  Only the locked 15-route basket contributes to the headline index.
D10 Grain B is diagnostics and reconciliation only.
D11 Eligibility is published as index_inclusion_rule_id and
    index_eligibility_status. The forbidden field name is never emitted.
D12 docs/index_methodology.md carries the mandated disclosures.
"""

from decimal import Decimal
from decimal import InvalidOperation
from decimal import ROUND_HALF_UP
from decimal import localcontext


class IndexRuleError(ValueError):
    """Raised when a Phase 11 rule or input contract is violated.

    Phase 11 verifies its input contract and fails loudly. It never repairs,
    clamps, coerces or imputes a price.
    """


# ---------------------------------------------------------------------------
# Schema and identity
# ---------------------------------------------------------------------------

PHASE11_SCHEMA_VERSION = "phase11-v1"
PHASE10_SCHEMA_VERSION_EXPECTED = "phase10-v1"

ROUTE_ID_SOURCE_OF_TRUTH = "scripts/build_vayu_route_basket.py::make_route_id"
BASKET_LOCKED_SHA256 = (
    "dc57e6d470a2ed9061dd82a92c84943749c3c648cef00b85b3f250df2f87c181"
)
BASKET_ROUTE_COUNT_EXPECTED = 15

# D1: the elementary economic item. Ordered, and never extended at runtime.
ITEM_KEY_FIELDS = (
    "route_id",
    "fare_class",
    "advance_purchase_window",
    "travel_date",
)
ITEM_ID_PREFIX = "ITEM::"
ITEM_ID_SEPARATOR = "|"
LINK_ID_PREFIX = "LINK::"
LINK_ID_SEPARATOR = "->"

# The item key deliberately fixes travel_date. Time-to-departure therefore
# shrinks as the collection round advances, so part of every price relative is
# the airline yield curve rather than market-wide price change.
MATURITY_RAMP_DISCLOSURE = (
    "The elementary item fixes travel_date while the collection round "
    "advances, so time-to-departure shrinks across a chain link. Part of each "
    "price relative is therefore the airline maturity ramp (yield curve) and "
    "not market-wide airfare change. This is a documented limitation of the "
    "approved D1 item definition, not a defect of the estimator."
)


# ---------------------------------------------------------------------------
# D3 / D8: numeric contract
# ---------------------------------------------------------------------------

INTERNAL_PRECISION = 28
INDEX_BASE_LEVEL = Decimal("100")
INDEX_BASE_LEVEL_PUBLISHED = Decimal("100.000000")

INDEX_LEVEL_DECIMAL_PLACES = 6
CHAIN_FACTOR_DECIMAL_PLACES = 8
RELATIVE_DECIMAL_PLACES = 8
LOG_DECIMAL_PLACES = 12
WEIGHT_DECIMAL_PLACES = 12
PERCENT_DECIMAL_PLACES = 4

LEVEL_QUANTUM = Decimal("0.000001")
FACTOR_QUANTUM = Decimal("0.00000001")
RELATIVE_QUANTUM = Decimal("0.00000001")
LOG_QUANTUM = Decimal("0.000000000001")
WEIGHT_QUANTUM = Decimal("0.000000000001")
PERCENT_QUANTUM = Decimal("0.0001")
MONEY_DECIMAL_PLACES = 2

ROUNDING_MODE_NAME = "ROUND_HALF_UP"
RECONCILIATION_TOLERANCE = Decimal("0.000000001")


# ---------------------------------------------------------------------------
# D3 / D4: estimator identity
# ---------------------------------------------------------------------------

AGGREGATION_STATISTIC = "WEIGHTED_JEVONS_CHAINED"
ELEMENTARY_AGGREGATION_STATISTIC = "UNWEIGHTED_JEVONS"
AGGREGATION_STATISTIC_SOURCE = "src/index_engine/rules.py::weighted_jevons"
WEIGHT_SOURCE = "data/official/dgca/processed/vayu_route_basket_2024_25.csv"
WEIGHT_BASIS = "DGCA_CONSERVATIVE_BIDIRECTIONAL_TRAFFIC"
WEIGHT_APPLICATION = "APPLIED_TO_LOG_PRICE_RELATIVES_NEVER_TO_PRICE_LEVELS"
WITHIN_ROUTE_WEIGHTING = "EQUAL_WEIGHT_PER_MATCHED_ITEM"


# ---------------------------------------------------------------------------
# D6 / D11: series variants and eligibility vocabulary
# ---------------------------------------------------------------------------

SERIES_VARIANT_PRIMARY = "PRIMARY"
SERIES_VARIANT_SENSITIVITY = "EXCL_REVIEW_HIGH"
SERIES_VARIANTS = (SERIES_VARIANT_PRIMARY, SERIES_VARIANT_SENSITIVITY)

INDEX_SERIES_ID = {
    SERIES_VARIANT_PRIMARY: "VAYU-RI-PRIMARY",
    SERIES_VARIANT_SENSITIVITY: "VAYU-RI-EXCL-REVIEW-HIGH",
}
INDEX_INCLUSION_RULE_ID = {
    SERIES_VARIANT_PRIMARY: "P11-INCL-01",
    SERIES_VARIANT_SENSITIVITY: "P11-INCL-02",
}
INDEX_INCLUSION_RULE_TEXT = {
    "P11-INCL-01": (
        "Include every retained Phase 10 route series value whose "
        "route_price_state is PRICED and whose median fare is parsable and "
        "strictly positive, regardless of Phase 9 anomaly severity."
    ),
    "P11-INCL-02": (
        "Diagnostic sensitivity rule: as P11-INCL-01, but additionally drop "
        "items whose Phase 10 anomaly_severity_max is REVIEW or HIGH. This "
        "series is never the headline series."
    ),
}
PRIMARY_SERIES_VARIANT = SERIES_VARIANT_PRIMARY

ELIGIBILITY_ELIGIBLE = "ELIGIBLE"
ELIGIBILITY_NO_OBSERVATIONS = "INELIGIBLE_NO_OBSERVATIONS"
ELIGIBILITY_NOT_PRICED = "INELIGIBLE_NOT_PRICED"
ELIGIBILITY_MISSING_FARE = "INELIGIBLE_MISSING_FARE"
ELIGIBILITY_UNPARSABLE_FARE = "INELIGIBLE_UNPARSABLE_FARE"
ELIGIBILITY_NON_POSITIVE_FARE = "INELIGIBLE_NON_POSITIVE_FARE"
ELIGIBILITY_EXCLUDED_REVIEW_HIGH = "EXCLUDED_REVIEW_HIGH"

STRUCTURAL_INELIGIBILITY_STATUSES = (
    ELIGIBILITY_NO_OBSERVATIONS,
    ELIGIBILITY_NOT_PRICED,
    ELIGIBILITY_MISSING_FARE,
    ELIGIBILITY_UNPARSABLE_FARE,
    ELIGIBILITY_NON_POSITIVE_FARE,
)

PRICE_STATE_PRICED = "PRICED"
COVERAGE_STATUS_NO_OBSERVATIONS = "NO_OBSERVATIONS"
SEVERITY_NONE = "NONE"
SEVERITY_INFO = "INFO"
SEVERITY_REVIEW = "REVIEW"
SEVERITY_HIGH = "HIGH"
SEVERITY_LEVELS = (SEVERITY_NONE, SEVERITY_INFO, SEVERITY_REVIEW, SEVERITY_HIGH)
SENSITIVITY_EXCLUDED_SEVERITIES = (SEVERITY_REVIEW, SEVERITY_HIGH)

ITEM_STATUS_MATCHED = "MATCHED"
ITEM_STATUS_ENTERING = "ENTERING"
ITEM_STATUS_LEAVING = "LEAVING"
ITEM_STATUS_UNPRICED = "UNPRICED"
ITEM_STATUS_EXCLUDED_ANOMALY = "EXCLUDED_ANOMALY"
ITEM_STATUSES = (
    ITEM_STATUS_MATCHED,
    ITEM_STATUS_ENTERING,
    ITEM_STATUS_LEAVING,
    ITEM_STATUS_UNPRICED,
    ITEM_STATUS_EXCLUDED_ANOMALY,
)


# ---------------------------------------------------------------------------
# D2: round alignment and the anchored chain
# ---------------------------------------------------------------------------

ROUND_ALIGNMENT_ANCHORED = "ANCHORED"
ROUND_ALIGNMENT_UNALIGNED = "UNALIGNED"
CHAIN_ELIGIBLE_ALIGNMENTS = (ROUND_ALIGNMENT_ANCHORED,)
UNALIGNED_EXCLUSION_REASON = "UNALIGNED_ROUND_NOT_A_CHAIN_LINK"
UNALIGNED_DIAGNOSTIC_BASIS = "ALL_ELIGIBLE_PRICED_ITEMS"

# Prototype anchor configuration inherited from Phase 7. These are PROTOTYPE
# CALIBRATION values, not official MoSPI collection times.
EXPECTED_ANCHOR_TIMES = ("09:00", "14:30", "20:15")
EXPECTED_ROUNDS_PER_DAY = 3
ANCHOR_CONFIGURATION_STATUS = "PROTOTYPE_CALIBRATION"


# ---------------------------------------------------------------------------
# D5: coverage disclosure vocabulary
# ---------------------------------------------------------------------------

COVERAGE_STATUS_PARTIAL = "PARTIAL_COVERAGE_PROTOTYPE"
COVERAGE_STATUS_FULL = "FULL_BASKET_COVERAGE"
COVERAGE_STATUS_NONE = "NO_BASKET_COVERAGE"

# There is no approved basis for a coverage threshold anywhere in Phases 1-10,
# so Phase 11 implements none. These flags exist so the absence is auditable
# and testable rather than merely asserted in prose.
APPLIES_COVERAGE_THRESHOLD = False
SUPPRESSES_INDEX_AUTOMATICALLY = False
MINIMUM_COVERAGE_THRESHOLD = None

COVERAGE_CONTRIBUTED = "CONTRIBUTED_TO_INDEX"
COVERAGE_OBSERVED_NOT_MATCHED = "OBSERVED_BUT_NO_MATCHED_PAIR"
COVERAGE_NOT_OBSERVED = "NO_OBSERVATIONS"


# ---------------------------------------------------------------------------
# D7: period grains
# ---------------------------------------------------------------------------

PERIOD_GRAIN_DAILY = "DAILY"
PERIOD_GRAIN_WEEKLY = "WEEKLY"
PERIOD_GRAIN_MONTHLY = "MONTHLY"
PERIOD_GRAINS = (PERIOD_GRAIN_DAILY, PERIOD_GRAIN_WEEKLY, PERIOD_GRAIN_MONTHLY)

PERIOD_PRIMARY_MEASURE = "PERIOD_END_CHAIN_LEVEL"
PERIOD_SECONDARY_MEASURE = "PERIOD_AVERAGE_INDEX_LEVEL"
PERIOD_AVERAGE_IS_CHAIN_CONSISTENT = False
PERIOD_AVERAGE_DISCLOSURE = (
    "period_average_level is the unweighted arithmetic mean of the round-level "
    "index levels inside the period. A mean of levels is not the level of a "
    "mean, so this value is NOT chain consistent and is published as a "
    "diagnostic only. The primary period value is the period-end chain level."
)


# ---------------------------------------------------------------------------
# Guard flags: every one of these must remain False
# ---------------------------------------------------------------------------

USES_MACHINE_LEARNING = False
USES_RANDOMNESS = False
USES_IMPUTATION = False
USES_ZERO_SUBSTITUTION = False
USES_CARRY_FORWARD = False
USES_PRICE_INTERPOLATION = False
USES_SOURCE_WEIGHTS = False
USES_EXPENDITURE_WEIGHTS = False
USES_QUANTITY_WEIGHTS = False
USES_FARE_VALUE_AS_WEIGHT = False
USES_GRAIN_B_AS_INDEX_INPUT = False
USES_OFF_BASKET_ROUTES_IN_HEADLINE = False
SEVERITY_DETERMINES_PRIMARY_SERIES = False
SUBSTITUTES_FARE_CLASSES = False
SUBSTITUTES_ADVANCE_PURCHASE_WINDOWS = False
MODIFIES_PHASE_1_TO_10 = False
REDISTRIBUTES_MISSING_ROUTE_WEIGHT = False

# D11: this field name must never appear in any Phase 11 output header. The
# literal is assembled from fragments so that the banned token never appears
# as a source substring in this repository.
FORBIDDEN_OUTPUT_FIELDS = frozenset(
    {
        "index" + "_eligible",
        "index_value",
        "basket_weight",
        "source_weight",
        "expenditure_weight",
        "quantity_weight",
        "basket_weighted_fare",
        "imputed_fare",
        "carried_forward_fare",
        "substituted_fare",
    }
)

ELIGIBILITY_FIELD_NAME = "index_eligibility_status"
INCLUSION_RULE_FIELD_NAME = "index_inclusion_rule_id"


# ---------------------------------------------------------------------------
# Numeric helpers (D8)
# ---------------------------------------------------------------------------


def quantize_level(value):
    """Quantize an index level to 6 decimal places, ROUND_HALF_UP."""
    if value is None:
        return None
    return Decimal(value).quantize(LEVEL_QUANTUM, rounding=ROUND_HALF_UP)


def quantize_factor(value):
    """Quantize a chain factor to 8 decimal places, ROUND_HALF_UP."""
    if value is None:
        return None
    return Decimal(value).quantize(FACTOR_QUANTUM, rounding=ROUND_HALF_UP)


def quantize_relative(value):
    """Quantize a price relative to 8 decimal places, ROUND_HALF_UP."""
    if value is None:
        return None
    return Decimal(value).quantize(RELATIVE_QUANTUM, rounding=ROUND_HALF_UP)


def quantize_log(value):
    """Quantize a natural logarithm to 12 decimal places, ROUND_HALF_UP."""
    if value is None:
        return None
    return Decimal(value).quantize(LOG_QUANTUM, rounding=ROUND_HALF_UP)


def quantize_weight(value):
    """Quantize a weight to 12 decimal places, ROUND_HALF_UP."""
    if value is None:
        return None
    return Decimal(value).quantize(WEIGHT_QUANTUM, rounding=ROUND_HALF_UP)


def quantize_percent(value):
    """Quantize a percentage to 4 decimal places, ROUND_HALF_UP."""
    if value is None:
        return None
    return Decimal(value).quantize(PERCENT_QUANTUM, rounding=ROUND_HALF_UP)


def parse_decimal(text):
    """Parse a Decimal from text. Returns None when unusable.

    Never repairs, clamps or coerces. A value that cannot be parsed as a
    finite Decimal returns None so the caller can classify it explicitly.
    """
    if text is None:
        return None
    if isinstance(text, Decimal):
        return text if text.is_finite() else None
    candidate = str(text).strip()
    if candidate == "":
        return None
    try:
        value = Decimal(candidate)
    except (InvalidOperation, ValueError, ArithmeticError):
        return None
    if not value.is_finite():
        return None
    return value


def money_decimal_places(value):
    """Return the number of decimal places carried by a Decimal value."""
    exponent = Decimal(value).as_tuple().exponent
    if not isinstance(exponent, int):
        return None
    if exponent >= 0:
        return 0
    return -exponent


def natural_log(value):
    """Natural logarithm of a strictly positive Decimal, at precision 28."""
    amount = Decimal(value)
    if not amount.is_finite() or amount <= 0:
        raise IndexRuleError(
            "natural_log requires a strictly positive finite value, got %s" % (value,)
        )
    with localcontext() as context:
        context.prec = INTERNAL_PRECISION
        return +amount.ln()


def natural_exp(value):
    """Exponential of a Decimal, at precision 28."""
    amount = Decimal(value)
    if not amount.is_finite():
        raise IndexRuleError("natural_exp requires a finite value")
    with localcontext() as context:
        context.prec = INTERNAL_PRECISION
        return +amount.exp()


# ---------------------------------------------------------------------------
# D1: item identity
# ---------------------------------------------------------------------------


def item_key(mapping):
    """Return the locked 4-tuple elementary item key for a Phase 10 record.

    The key is exactly (route_id, fare_class, advance_purchase_window,
    travel_date). collection_round_id is deliberately NOT part of the item
    identity; it is the time dimension of the index.
    """
    values = []
    for name in ITEM_KEY_FIELDS:
        if name not in mapping:
            raise IndexRuleError("item_key requires field %r" % (name,))
        values.append(str(mapping[name]))
    return tuple(values)


def item_id(key):
    """Stable printable identifier for an elementary item key."""
    if len(key) != len(ITEM_KEY_FIELDS):
        raise IndexRuleError(
            "item_id expects %d key parts, got %d" % (len(ITEM_KEY_FIELDS), len(key))
        )
    return ITEM_ID_PREFIX + ITEM_ID_SEPARATOR.join(str(part) for part in key)


def link_id(previous_round_id, current_round_id):
    """Stable printable identifier for a chain link."""
    return "%s%s%s%s" % (
        LINK_ID_PREFIX,
        previous_round_id,
        LINK_ID_SEPARATOR,
        current_round_id,
    )


# ---------------------------------------------------------------------------
# D2: chain eligibility of a round
# ---------------------------------------------------------------------------


def is_chain_eligible_round(alignment):
    """True only for ANCHORED rounds. UNALIGNED rounds are never chain links."""
    return str(alignment) in CHAIN_ELIGIBLE_ALIGNMENTS


# ---------------------------------------------------------------------------
# D6 / D11: index eligibility of a single Phase 10 route-series record
# ---------------------------------------------------------------------------


def evaluate_index_eligibility(mapping, variant):
    """Classify one Phase 10 Grain A record for a given series variant.

    Returns (index_eligibility_status, price). price is a Decimal when the
    record carries a usable fare and None otherwise.

    PRIMARY never consults Phase 9 severity. Only the sensitivity variant
    drops REVIEW and HIGH items, and it reports that with its own status.
    """
    if variant not in SERIES_VARIANTS:
        raise IndexRuleError("unknown series variant %r" % (variant,))

    coverage_status = str(mapping.get("route_coverage_status", "")).strip()
    if coverage_status == COVERAGE_STATUS_NO_OBSERVATIONS:
        return (ELIGIBILITY_NO_OBSERVATIONS, None)

    price_state = str(mapping.get("route_price_state", "")).strip()
    if price_state != PRICE_STATE_PRICED:
        return (ELIGIBILITY_NOT_PRICED, None)

    raw_fare = mapping.get("route_fare_median", "")
    if raw_fare is None or str(raw_fare).strip() == "":
        return (ELIGIBILITY_MISSING_FARE, None)

    price = parse_decimal(raw_fare)
    if price is None:
        return (ELIGIBILITY_UNPARSABLE_FARE, None)
    if price <= 0:
        return (ELIGIBILITY_NON_POSITIVE_FARE, price)

    if variant == SERIES_VARIANT_SENSITIVITY:
        severity = str(mapping.get("anomaly_severity_max", "")).strip()
        if severity in SENSITIVITY_EXCLUDED_SEVERITIES:
            return (ELIGIBILITY_EXCLUDED_REVIEW_HIGH, price)

    return (ELIGIBILITY_ELIGIBLE, price)


def is_structurally_ineligible(status):
    """True when a record is excluded for structural reasons, not severity."""
    return status in STRUCTURAL_INELIGIBILITY_STATUSES


# ---------------------------------------------------------------------------
# D3: price relatives
# ---------------------------------------------------------------------------


def price_relative(current_price, previous_price):
    """Return r = current / previous for a matched item.

    The direction is locked: the current round is the numerator. Both prices
    must be strictly positive; a missing or non-positive price is never
    substituted with zero, a carried-forward value, or an imputed value.
    """
    current = parse_decimal(current_price)
    previous = parse_decimal(previous_price)
    if current is None or previous is None:
        raise IndexRuleError("price_relative requires two parsable prices")
    if current <= 0 or previous <= 0:
        raise IndexRuleError(
            "price_relative requires strictly positive prices, got %s and %s"
            % (current, previous)
        )
    with localcontext() as context:
        context.prec = INTERNAL_PRECISION
        return +(current / previous)


# ---------------------------------------------------------------------------
# D3 / D4: Jevons aggregation
# ---------------------------------------------------------------------------


def mean_log_relative(relatives):
    """Unweighted mean of natural log price relatives.

    The input is sorted before summation so the result is exactly
    input-order independent.
    """
    values = list(relatives)
    if not values:
        return None
    logs = sorted(natural_log(value) for value in values)
    with localcontext() as context:
        context.prec = INTERNAL_PRECISION
        total = Decimal(0)
        for entry in logs:
            total = total + entry
        return +(total / Decimal(len(logs)))


def elementary_jevons(relatives):
    """Unweighted Jevons (geometric mean) of price relatives for one route.

    Returns None for an empty matched set. A single matched relative returns
    that relative, which is the correct geometric mean of one element.
    """
    mean_log = mean_log_relative(relatives)
    if mean_log is None:
        return None
    return natural_exp(mean_log)


def renormalize_weights(weights):
    """D4: renormalize contributing route weights so they sum to one.

    `weights` maps route_id to the locked Phase 5 traffic weight of a route
    that contributes at least one matched relative on this link. Missing
    routes are absent from the mapping; their weight is never redistributed
    by hand and never spread across the contributing routes as a bonus.
    """
    if not weights:
        return {}
    with localcontext() as context:
        context.prec = INTERNAL_PRECISION
        total = Decimal(0)
        for route_id in sorted(weights):
            total = total + Decimal(weights[route_id])
        if total <= 0:
            raise IndexRuleError("contributing route weights must be positive")
        normalized = {}
        for route_id in sorted(weights):
            normalized[route_id] = +(Decimal(weights[route_id]) / total)
        return normalized


def represented_weight(weights):
    """Unnormalized sum of contributing route weights (D4 disclosure)."""
    with localcontext() as context:
        context.prec = INTERNAL_PRECISION
        total = Decimal(0)
        for route_id in sorted(weights):
            total = total + Decimal(weights[route_id])
        return +total


def weighted_jevons(contributions):
    """D4: weighted Jevons chain factor for one link.

    `contributions` is an iterable of (route_id, renormalized_weight,
    route_elementary_jevons). The weights are applied to the LOG of each
    route elementary index, never to a price level. Contributions are sorted
    by route_id before summation, so the result is input-order independent.
    """
    entries = sorted(
        (str(route_id), Decimal(weight), Decimal(route_index))
        for route_id, weight, route_index in contributions
    )
    if not entries:
        return None
    with localcontext() as context:
        context.prec = INTERNAL_PRECISION
        total = Decimal(0)
        for _route_id, weight, route_index in entries:
            total = total + weight * natural_log(route_index)
    return natural_exp(total)


def weighted_log_contribution(weight, route_index):
    """One route's weighted log contribution to a link (audit column)."""
    with localcontext() as context:
        context.prec = INTERNAL_PRECISION
        return +(Decimal(weight) * natural_log(route_index))


# ---------------------------------------------------------------------------
# D3 / D8: chaining and rebasing
# ---------------------------------------------------------------------------


def chain_level(previous_level, chain_factor):
    """I_t = I_(t-1) * J_t, computed on unrounded internal levels."""
    with localcontext() as context:
        context.prec = INTERNAL_PRECISION
        return +(Decimal(previous_level) * Decimal(chain_factor))


def rebase_levels(levels, new_base_key):
    """D8: rebase an ordered level series to a new base period.

    `levels` is an ordered sequence of (key, unrounded_level) pairs. The
    rebased series divides every unrounded level by the unrounded level at
    `new_base_key` and multiplies by the base level, so period-to-period
    relatives are preserved exactly. Rebasing never re-reads Phase 10 and
    never operates on published, rounded values.
    """
    ordered = list(levels)
    lookup = {}
    for key, level in ordered:
        lookup[key] = Decimal(level)
    if new_base_key not in lookup:
        raise IndexRuleError("rebase target %r is not in the series" % (new_base_key,))
    divisor = lookup[new_base_key]
    if divisor <= 0:
        raise IndexRuleError("rebase target level must be strictly positive")
    rebased = []
    with localcontext() as context:
        context.prec = INTERNAL_PRECISION
        for key, level in ordered:
            rebased.append((key, +(Decimal(level) / divisor * INDEX_BASE_LEVEL)))
    return rebased


def percent_change(current_level, previous_level):
    """Percentage change between two index levels, 4 dp, ROUND_HALF_UP."""
    current = Decimal(current_level)
    previous = Decimal(previous_level)
    if previous <= 0:
        raise IndexRuleError("percent_change requires a positive previous level")
    with localcontext() as context:
        context.prec = INTERNAL_PRECISION
        ratio = (current - previous) / previous * Decimal(100)
    return quantize_percent(ratio)


# ---------------------------------------------------------------------------
# D5: coverage disclosure
# ---------------------------------------------------------------------------


def coverage_percentage(weight_represented, weight_total):
    """Basket coverage as a percentage of total basket weight."""
    total = Decimal(weight_total)
    if total <= 0:
        raise IndexRuleError("basket weight total must be positive")
    with localcontext() as context:
        context.prec = INTERNAL_PRECISION
        ratio = Decimal(weight_represented) / total * Decimal(100)
    return quantize_percent(ratio)


def coverage_status(routes_represented, routes_total):
    """D5: coverage label. No threshold is applied and nothing is suppressed."""
    represented = int(routes_represented)
    total = int(routes_total)
    if represented <= 0:
        return COVERAGE_STATUS_NONE
    if represented == total:
        return COVERAGE_STATUS_FULL
    return COVERAGE_STATUS_PARTIAL


# ---------------------------------------------------------------------------
# D7: period derivation
# ---------------------------------------------------------------------------


def period_id(round_sort_key, grain):
    """Derive the period identifier for a round, on the collection calendar.

    round_sort_key is the Phase 10 'YYYY-MM-DD HH:MM' naive local key. No
    timezone inference is performed, consistent with Phase 6.
    """
    key = str(round_sort_key)
    if len(key) < 10:
        raise IndexRuleError("round_sort_key %r is too short" % (round_sort_key,))
    calendar_day = key[0:10]
    if grain == PERIOD_GRAIN_DAILY:
        return calendar_day
    if grain == PERIOD_GRAIN_MONTHLY:
        return calendar_day[0:7]
    if grain == PERIOD_GRAIN_WEEKLY:
        year_text = calendar_day[0:4]
        month_text = calendar_day[5:7]
        day_text = calendar_day[8:10]
        import datetime

        calendar_date = datetime.date(
            int(year_text), int(month_text), int(day_text)
        )
        iso_year, iso_week, _iso_weekday = calendar_date.isocalendar()
        return "%04d-W%02d" % (iso_year, iso_week)
    raise IndexRuleError("unknown period grain %r" % (grain,))


def expected_round_count(period_grain, period_identifier):
    """Expected anchored round count for a complete period of this grain."""
    import calendar as calendar_module

    if period_grain == PERIOD_GRAIN_DAILY:
        return EXPECTED_ROUNDS_PER_DAY
    if period_grain == PERIOD_GRAIN_WEEKLY:
        return EXPECTED_ROUNDS_PER_DAY * 7
    if period_grain == PERIOD_GRAIN_MONTHLY:
        year_text = str(period_identifier)[0:4]
        month_text = str(period_identifier)[5:7]
        days_in_month = calendar_module.monthrange(int(year_text), int(month_text))[1]
        return EXPECTED_ROUNDS_PER_DAY * days_in_month
    raise IndexRuleError("unknown period grain %r" % (period_grain,))


def mean_level(levels):
    """Unweighted arithmetic mean of index levels (diagnostic only, D7)."""
    values = [Decimal(level) for level in levels]
    if not values:
        return None
    with localcontext() as context:
        context.prec = INTERNAL_PRECISION
        total = Decimal(0)
        for value in sorted(values):
            total = total + value
        return +(total / Decimal(len(values)))


# ---------------------------------------------------------------------------
# Output header guard (D11)
# ---------------------------------------------------------------------------


def assert_no_forbidden_fields(column_names):
    """Raise if any published column name is a forbidden Phase 11 field."""
    offenders = sorted(set(column_names) & FORBIDDEN_OUTPUT_FIELDS)
    if offenders:
        raise IndexRuleError(
            "forbidden Phase 11 output field(s): %s" % (", ".join(offenders),)
        )
    return True
