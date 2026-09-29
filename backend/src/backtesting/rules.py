"""Locked constants and pure functions for VAYU Phase 12 backtesting."""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP, getcontext, localcontext
from typing import Iterable, Sequence

getcontext().prec = 28
SCHEMA_VERSION = "phase12-v1"
BACKTEST_ID = "BT12-MOSPI-MONTHLY"
PROTOTYPE_STATUS = "PROTOTYPE_BACKTEST"
PRODUCTION_STATUS = "PRODUCTION_BACKTEST_REQUIRED"
NO_OVERLAP = "NO_OVERLAPPING_COMPLETE_PERIODS"
INSUFFICIENT = "INSUFFICIENT_SAMPLE"
PARTIAL_EXCLUSION = "PARTIAL_MONTH_EXCLUDED_FROM_REFERENCE_COMPARISON"
REFERENCE_MOSPI = "MOSPI-AIRFARE-CPI-07331201"
REFERENCE_DGCA = "DGCA-CITY-PAIR-PASSENGER-TRAFFIC-2024-25"
PRIMARY_VARIANT = "PRIMARY"
ANOMALY_VARIANT = "EXCL_REVIEW_HIGH"
COMPARISON_GRAIN = "MONTHLY"
REBASING_RULE = "P12-REBASE-01_FIRST_COMPLETE_OVERLAP_EQUALS_100"
ALIGNMENT_RULE = "P12-ALIGN-01_EXACT_YYYY_MM_COMPLETE_MONTH_ONLY"
INCLUSION_RULE = "P12-INCL-01_COMPLETE_MONTH_PERIOD_END_ONLY"
EXCLUSION_RULE_PARTIAL = "P12-EXCL-01_PARTIAL_MONTH"
NO_INTERPOLATION_RULE = "P12-MISS-01_NO_INTERPOLATION_FILL_OR_NEAREST_MATCH"
COVERAGE_THRESHOLD = Decimal("80")

SENSITIVITY_RULES = {
    "SENS-COV-01": "PRIMARY",
    "SENS-COV-02": "EQUAL_ROUTE_DIAGNOSTIC",
    "SENS-COV-03": "OBSERVED_COVERAGE_LOG_CONTRIBUTION",
    "SENS-COV-04": "LOW_COVERAGE_EXCLUSION_80_PERCENT",
    "SENS-ANOM-01": "PRIMARY_VS_EXCL_REVIEW_HIGH",
}

METRIC_RULES = (
    ("MET-DESC-01", "DESCRIPTIVE_LEVEL_DIFFERENCE", "LEVEL", 1),
    ("MET-MAE-01", "MEAN_ABSOLUTE_ERROR_MOM_PP", "CHANGE", 6),
    ("MET-RMSE-01", "ROOT_MEAN_SQUARED_ERROR_MOM_PP", "CHANGE", 6),
    ("MET-BIAS-01", "MEAN_SIGNED_ERROR_MOM_PP", "CHANGE", 6),
    ("MET-MAPE-01", "MAPE_REBASED_POSITIVE_LEVELS", "LEVEL", 6),
    ("MET-DIR-01", "DIRECTIONAL_AGREEMENT_MOM", "CHANGE", 6),
    ("MET-PEARSON-01", "PEARSON_CORRELATION_MOM", "CHANGE", 12),
    ("MET-SPEARMAN-01", "SPEARMAN_CORRELATION_MOM", "CHANGE", 12),
    ("MET-SD-VAYU-01", "VAYU_CHANGE_STANDARD_DEVIATION", "CHANGE", 12),
    ("MET-SD-REF-01", "REFERENCE_CHANGE_STANDARD_DEVIATION", "CHANGE", 12),
    ("MET-VOL-01", "VOLATILITY_RATIO", "CHANGE", 12),
    ("MET-TURN-01", "TURNING_POINT_AGREEMENT", "CHANGE", 12),
    ("MET-PEAK-01", "PEAK_TROUGH_TIMING_DIFFERENCE", "LEVEL", 12),
    ("MET-YOY-01", "YEAR_OVER_YEAR_CHANGE_COMPARISON", "CHANGE", 12),
    ("MET-LAG-M1", "LEAD_LAG_MINUS_ONE_MONTH", "CHANGE", 18),
    ("MET-LAG-00", "LEAD_LAG_ZERO_MONTH", "CHANGE", 18),
    ("MET-LAG-P1", "LEAD_LAG_PLUS_ONE_MONTH", "CHANGE", 18),
)

SUMMARY_COLUMNS = (
    "backtest_id","backtest_category","backtest_status","production_status",
    "vayu_series_variant","vayu_series_id","reference_series_id","comparison_grain",
    "vayu_period_start","vayu_period_end","reference_period_start","reference_period_end",
    "overlap_period_start","overlap_period_end","vayu_complete_month_count",
    "reference_period_count","overlapping_level_count","overlapping_change_count",
    "coverage_rule_id","inclusion_rule_id","reference_eligibility_status",
    "overall_evaluation_status","limitation_codes","phase12_schema_version",
)
PERIOD_COLUMNS = (
    "comparison_row_id","backtest_id","period_grain","period_id","vayu_source_file",
    "vayu_source_row_key","vayu_series_variant","vayu_original_level","vayu_period_is_partial",
    "vayu_round_count","vayu_expected_round_count","vayu_coverage_pct","reference_source_file",
    "reference_source_row_key","reference_series_id","reference_original_level","period_match_status",
    "period_exclusion_reason","comparison_base_period","vayu_rebased_level","reference_rebased_level",
    "vayu_change_pct","reference_change_pct","change_difference_pp","level_difference_rebased",
    "direction_vayu","direction_reference","direction_match_status","phase12_schema_version",
)
METRIC_COLUMNS = (
    "metric_record_id","backtest_id","metric_id","metric_name","metric_family","input_measure",
    "vayu_series_variant","reference_series_id","comparison_grain","comparison_period_start",
    "comparison_period_end","observations_available","observations_required","distinct_vayu_values",
    "distinct_reference_values","metric_value","metric_unit","metric_status",
    "insufficient_sample_reason","metric_definition","zero_handling_rule","missing_handling_rule",
    "inclusion_rule_id","coverage_rule_id","phase12_schema_version",
)
SENSITIVITY_COLUMNS = (
    "sensitivity_record_id","backtest_id","period_id","sensitivity_type","primary_series_id",
    "alternative_series_id","alternative_method_id","primary_index_level","alternative_index_level",
    "observed_coverage_log_contribution","level_difference","level_difference_pct","primary_change_pct",
    "alternative_change_pct","change_difference_pp","primary_direction","alternative_direction",
    "turning_point_difference","primary_route_count","alternative_route_count","primary_weight_represented",
    "alternative_weight_represented","route_contribution_difference","sensitivity_status",
    "diagnostic_only","corpus_disclosure","phase12_schema_version",
)
COVERAGE_COLUMNS = (
    "coverage_record_id","backtest_id","period_id","series_variant","coverage_policy_id","route_id",
    "basket_rank","locked_traffic_weight","route_observation_status","eligible_product_count",
    "matched_product_count","route_contributed","route_relative_available","weight_represented",
    "weight_missing","basket_routes_observed","basket_routes_total","basket_weight_represented",
    "basket_weight_missing","coverage_pct","coverage_gate","coverage_gate_passed",
    "period_comparison_eligible","exclusion_reason","phase12_schema_version",
)
REFERENCE_COLUMNS = (
    "reference_series_id","reference_name","source_organization","source_file","source_url",
    "reference_type","price_or_traffic_classification","series_code","item","geography","sector",
    "frequency","base_year","date_start","date_end","observation_count","missing_value_count",
    "imputation_present","valid_comparison_target","valid_comparison_grains","invalid_use_codes",
    "processed_data_sha256","phase12_schema_version",
)
LINEAGE_COLUMNS = (
    "lineage_record_id","backtest_id","metric_record_id","sensitivity_record_id","comparison_row_id",
    "input_role","source_file","source_sha256","source_schema_version","source_row_key","vayu_series_id",
    "vayu_series_variant","reference_series_id","period_id","base_period","rebasing_rule_id",
    "alignment_rule_id","aggregation_rule_id","metric_id","coverage_rule_id","inclusion_rule_id",
    "exclusion_rule_id","source_value","derived_value","derivation_expression","lineage_status",
    "phase12_schema_version",
)
GATE_COLUMNS = (
    "gate_record_id","gate_id","requirement","comparison_operator","required_value","observed_value",
    "unit","gate_status","failure_reason","production_status","phase12_schema_version",
)

OUTPUT_SCHEMAS = {
    "phase12_backtest_summary.csv": SUMMARY_COLUMNS,
    "phase12_period_comparison.csv": PERIOD_COLUMNS,
    "phase12_metric_report.csv": METRIC_COLUMNS,
    "phase12_sensitivity_report.csv": SENSITIVITY_COLUMNS,
    "phase12_coverage_report.csv": COVERAGE_COLUMNS,
    "phase12_reference_metadata.csv": REFERENCE_COLUMNS,
    "phase12_backtest_lineage.csv": LINEAGE_COLUMNS,
    "phase12_thirty_day_gate.csv": GATE_COLUMNS,
}


def dec(value: object) -> Decimal | None:
    text = "" if value is None else str(value).strip()
    if not text:
        return None
    try:
        return Decimal(text)
    except Exception:
        return None


def q(value: Decimal | None, places: str = "0.000000") -> str:
    if value is None:
        return ""
    return format(value.quantize(Decimal(places), rounding=ROUND_HALF_UP), "f")


def month_id(period: str) -> str:
    text = str(period).strip()
    if len(text) < 7 or text[4] != "-":
        raise ValueError("period must begin YYYY-MM")
    year, month = text[:4], text[5:7]
    if not (year.isdigit() and month.isdigit() and 1 <= int(month) <= 12):
        raise ValueError("invalid YYYY-MM period")
    return text[:7]


def exact_month_join(vayu: Sequence[dict[str, str]], reference: Sequence[dict[str, str]]) -> list[tuple[dict[str, str], dict[str, str]]]:
    ref = {month_id(item["period"]): item for item in reference}
    pairs = []
    for item in vayu:
        if item.get("period_grain") != "MONTHLY" or item.get("period_is_partial") != "False":
            continue
        key = month_id(item["period_id"])
        if key in ref:
            pairs.append((item, ref[key]))
    return sorted(pairs, key=lambda pair: month_id(pair[0]["period_id"]))


def rebase(values: Sequence[Decimal]) -> list[Decimal]:
    if not values or values[0] == 0:
        raise ValueError("positive nonzero base required")
    base = values[0]
    # Rebased levels are intermediate analytical values, not presentation
    # fields.  Compute them with guard precision so a later division of two
    # adjacent rebased levels rounds to the same Decimal result as the direct
    # ratio of the original, unrounded levels.  Presentation quantization is
    # applied only by the output renderer.
    with localcontext() as working:
        working.prec = getcontext().prec * 2
        return [Decimal("100") * value / base for value in values]


def changes(values: Sequence[Decimal]) -> list[Decimal]:
    result = []
    for previous, current in zip(values, values[1:]):
        if previous == 0:
            raise ValueError("zero denominator")
        result.append(Decimal("100") * (current / previous - Decimal("1")))
    return result


def mean(values: Sequence[Decimal]) -> Decimal:
    if not values:
        raise ValueError("empty values")
    return sum(values, Decimal("0")) / Decimal(len(values))


def mae(left: Sequence[Decimal], right: Sequence[Decimal]) -> Decimal:
    _same_size(left, right)
    return mean([abs(a - b) for a, b in zip(left, right)])


def rmse(left: Sequence[Decimal], right: Sequence[Decimal]) -> Decimal:
    _same_size(left, right)
    return mean([(a - b) ** 2 for a, b in zip(left, right)]).sqrt()


def bias(left: Sequence[Decimal], right: Sequence[Decimal]) -> Decimal:
    _same_size(left, right)
    return mean([a - b for a, b in zip(left, right)])


def mape_positive_levels(left: Sequence[Decimal], right: Sequence[Decimal]) -> Decimal:
    _same_size(left, right)
    if any(value <= 0 for value in right):
        raise ValueError("MAPE requires positive reference levels")
    return Decimal("100") * mean([abs((a - b) / b) for a, b in zip(left, right)])


def direction(value: Decimal) -> str:
    return "UP" if value > 0 else "DOWN" if value < 0 else "ZERO"


def directional_agreement(left: Sequence[Decimal], right: Sequence[Decimal]) -> Decimal:
    _same_size(left, right)
    matches = sum(1 for a, b in zip(left, right) if direction(a) == direction(b))
    return Decimal("100") * Decimal(matches) / Decimal(len(left))


def sample_sd(values: Sequence[Decimal]) -> Decimal:
    if len(values) < 2:
        raise ValueError("at least two values required")
    center = mean(values)
    return (sum(((value - center) ** 2 for value in values), Decimal("0")) / Decimal(len(values) - 1)).sqrt()


def pearson(left: Sequence[Decimal], right: Sequence[Decimal]) -> Decimal:
    _same_size(left, right)
    lm, rm = mean(left), mean(right)
    numerator = sum(((a-lm)*(b-rm) for a,b in zip(left,right)), Decimal("0"))
    ld = sum(((a-lm)**2 for a in left), Decimal("0"))
    rd = sum(((b-rm)**2 for b in right), Decimal("0"))
    if ld == 0 or rd == 0:
        raise ValueError("nonzero variance required")
    return numerator / (ld * rd).sqrt()


def _ranks(values: Sequence[Decimal]) -> list[Decimal]:
    result = [Decimal("0")] * len(values)
    ordered = sorted(enumerate(values), key=lambda item: (item[1], item[0]))
    index = 0
    while index < len(ordered):
        end = index + 1
        while end < len(ordered) and ordered[end][1] == ordered[index][1]:
            end += 1
        rank = (Decimal(index + 1) + Decimal(end)) / Decimal("2")
        for position in range(index, end):
            result[ordered[position][0]] = rank
        index = end
    return result


def spearman(left: Sequence[Decimal], right: Sequence[Decimal]) -> Decimal:
    return pearson(_ranks(left), _ranks(right))


def geometric_mean(values: Sequence[Decimal]) -> Decimal:
    if not values or any(value <= 0 for value in values):
        raise ValueError("positive values required")
    return (sum((value.ln() for value in values), Decimal("0")) / Decimal(len(values))).exp()


def _same_size(left: Sequence[Decimal], right: Sequence[Decimal]) -> None:
    if not left or len(left) != len(right):
        raise ValueError("equal nonempty sequences required")
