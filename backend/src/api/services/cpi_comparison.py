"""Exact-month CPI comparison with explicit sample and coverage gates."""
from __future__ import annotations

from datetime import date
from math import sqrt


MIN_COVERAGE_PCT = 80.0
MIN_MAE_CHANGES = 6
MIN_CORRELATION_CHANGES = 12
REFERENCE_SERIES_ID = "MOSPI-AIRFARE-CPI-07331201"


def _number(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number and abs(number) != float("inf") else None


def _month_key(value):
    return str(value or "")[:7]


def _previous_month(key):
    try:
        year, month = map(int, key.split("-"))
        return f"{year - (month == 1):04d}-{12 if month == 1 else month - 1:02d}"
    except (ValueError, TypeError):
        return ""


def _sample_status(count, required):
    return "AVAILABLE" if count >= required else "INSUFFICIENT_SAMPLE"


def _pearson(left, right):
    count = len(left)
    if count < 2:
        return None
    mean_left = sum(left) / count
    mean_right = sum(right) / count
    centered_left = [item - mean_left for item in left]
    centered_right = [item - mean_right for item in right]
    left_sum = sum(item * item for item in centered_left)
    right_sum = sum(item * item for item in centered_right)
    if left_sum == 0 or right_sum == 0:
        return None
    return sum(a * b for a, b in zip(centered_left, centered_right)) / sqrt(left_sum * right_sum)


def compare_cpi(period_rows, cpi_rows):
    """Compare PRIMARY Vayu monthly levels with the official domestic-airfare CPI.

    Only exact, complete, >=80%-basket-coverage months enter comparison metrics.
    No partial periods, interpolation, forward fill, or synthetic rows are used.
    """
    cpi_by_month = {}
    for row in cpi_rows:
        if row.get("code") not in {"", "07.3.3.1.2.01"}:
            continue
        if row.get("item") not in {"", "Airfare"}:
            continue
        value = _number(row.get("cpi_index"))
        key = _month_key(row.get("period"))
        if key and value is not None and value > 0:
            cpi_by_month[key] = {"value": value, "row": row}

    cpi_periods = sorted(cpi_by_month)
    cpi_latest = cpi_by_month[cpi_periods[-1]] if cpi_periods else None
    latest_mom = latest_yoy = None
    if cpi_periods:
        last_key = cpi_periods[-1]
        prior = cpi_by_month.get(_previous_month(last_key))
        year_prior_key = f"{int(last_key[:4]) - 1:04d}-{last_key[5:7]}"
        year_prior = cpi_by_month.get(year_prior_key)
        if prior:
            latest_mom = 100 * (cpi_latest["value"] / prior["value"] - 1)
        if year_prior:
            latest_yoy = 100 * (cpi_latest["value"] / year_prior["value"] - 1)

    primary_months = {}
    excluded = {"partial_month": 0, "low_basket_coverage": 0, "missing_index": 0}
    for row in period_rows:
        if row.get("series_variant") != "PRIMARY" or row.get("period_grain") != "MONTHLY":
            continue
        key = _month_key(row.get("period_id"))
        if not key:
            continue
        is_partial = row.get("period_is_partial") != "False"
        coverage = _number(row.get("basket_coverage_pct_min"))
        has_low_coverage = coverage is None or coverage < MIN_COVERAGE_PCT
        if is_partial:
            excluded["partial_month"] += 1
        if has_low_coverage:
            excluded["low_basket_coverage"] += 1
        if is_partial or has_low_coverage:
            continue
        vayu = _number(row.get("period_end_index_level"))
        if vayu is None or vayu <= 0:
            excluded["missing_index"] += 1
            continue
        primary_months[key] = {"value": vayu, "coverage_pct": coverage}

    months = sorted(set(primary_months) & set(cpi_by_month))
    base_key = months[0] if months else None
    timeline = []
    for key in months:
        vayu_raw = primary_months[key]["value"]
        cpi_raw = cpi_by_month[key]["value"]
        timeline.append({
            "period": key,
            "vayu_index_original": round(vayu_raw, 6),
            "cpi_index_original": round(cpi_raw, 6),
            "vayu_index_rebased": round(100 * vayu_raw / primary_months[base_key]["value"], 6),
            "cpi_index_rebased": round(100 * cpi_raw / cpi_by_month[base_key]["value"], 6),
            "basket_coverage_pct": primary_months[key]["coverage_pct"],
            "vayu_mom_pct": None,
            "cpi_mom_pct": None,
            "mom_gap_percentage_points": None,
        })

    by_month = {row["period"]: row for row in timeline}
    paired_vayu_changes = []
    paired_cpi_changes = []
    change_rows = []
    for row in timeline:
        previous = by_month.get(_previous_month(row["period"]))
        if previous is None:
            continue
        vayu_change = 100 * (row["vayu_index_original"] / previous["vayu_index_original"] - 1)
        cpi_change = 100 * (row["cpi_index_original"] / previous["cpi_index_original"] - 1)
        row["vayu_mom_pct"] = round(vayu_change, 6)
        row["cpi_mom_pct"] = round(cpi_change, 6)
        row["mom_gap_percentage_points"] = round(vayu_change - cpi_change, 6)
        paired_vayu_changes.append(vayu_change)
        paired_cpi_changes.append(cpi_change)
        change_rows.append(row)

    gaps = [abs(a - b) for a, b in zip(paired_vayu_changes, paired_cpi_changes)]
    correlation = None
    distinct_vayu = len({round(value, 10) for value in paired_vayu_changes})
    distinct_cpi = len({round(value, 10) for value in paired_cpi_changes})
    corr_status = _sample_status(len(gaps), MIN_CORRELATION_CHANGES)
    if corr_status == "AVAILABLE" and distinct_vayu >= 3 and distinct_cpi >= 3:
        correlation = _pearson(paired_vayu_changes, paired_cpi_changes)
        if correlation is None:
            corr_status = "ZERO_VARIANCE"
    elif corr_status == "AVAILABLE":
        corr_status = "INSUFFICIENT_VARIATION"

    mae_status = _sample_status(len(gaps), MIN_MAE_CHANGES)
    mae = sum(gaps) / len(gaps) if mae_status == "AVAILABLE" else None
    peak = max(gaps) if gaps else None
    directional = None
    if len(gaps) >= MIN_MAE_CHANGES:
        directional = sum(
            (a > 0 and b > 0) or (a < 0 and b < 0) or (a == 0 and b == 0)
            for a, b in zip(paired_vayu_changes, paired_cpi_changes)
        ) / len(gaps) * 100

    level_gaps = [abs(row["vayu_index_rebased"] - row["cpi_index_rebased"]) for row in timeline]
    positive_level_mape = None
    if len(timeline) >= 6 and all(row["cpi_index_rebased"] > 0 for row in timeline):
        positive_level_mape = sum(
            abs(row["vayu_index_rebased"] - row["cpi_index_rebased"])
            / row["cpi_index_rebased"] * 100
            for row in timeline
        ) / len(timeline)

    return {
        "reference_series_id": REFERENCE_SERIES_ID,
        "reference_name": "MoSPI Domestic Airfare CPI (All India, Combined; base 2024=100)",
        "comparison_status": "AVAILABLE" if months else "NO_OVERLAPPING_COMPLETE_PERIODS",
        "comparison_rule": "EXACT_MONTH_PRIMARY_COMPLETE_MONTH_AT_LEAST_80_PERCENT_BASKET_COVERAGE",
        "base_period": base_key,
        "overlap_period_start": months[0] if months else None,
        "overlap_period_end": months[-1] if months else None,
        "overlapping_complete_month_count": len(months),
        "paired_monthly_change_count": len(gaps),
        "minimum_basket_coverage_pct": MIN_COVERAGE_PCT,
        "excluded_vayu_months": excluded,
        "metrics": {
            "pearson_correlation_of_mom_changes": {
                "value": round(correlation, 6) if correlation is not None else None,
                "status": corr_status,
                "observations_available": len(gaps),
                "observations_required": MIN_CORRELATION_CHANGES,
                "unit": "correlation",
            },
            "mean_absolute_mom_change_gap": {
                "value": round(mae, 6) if mae is not None else None,
                "status": mae_status,
                "observations_available": len(gaps),
                "observations_required": MIN_MAE_CHANGES,
                "unit": "percentage_points",
            },
            "peak_absolute_mom_change_gap": {
                "value": round(peak, 6) if peak is not None else None,
                "status": "AVAILABLE" if peak is not None else "INSUFFICIENT_SAMPLE",
                "observations_available": len(gaps),
                "observations_required": 1,
                "unit": "percentage_points",
            },
            "directional_agreement": {
                "value": round(directional, 6) if directional is not None else None,
                "status": "AVAILABLE" if directional is not None else "INSUFFICIENT_SAMPLE",
                "observations_available": len(gaps),
                "observations_required": MIN_MAE_CHANGES,
                "unit": "percent",
            },
            "mean_absolute_rebased_level_gap": {
                "value": round(sum(level_gaps) / len(level_gaps), 6) if len(level_gaps) >= 1 else None,
                "status": "AVAILABLE" if level_gaps else "INSUFFICIENT_SAMPLE",
                "observations_available": len(level_gaps),
                "observations_required": 1,
                "unit": "index_points",
            },
            "peak_absolute_rebased_level_gap": {
                "value": round(max(level_gaps), 6) if level_gaps else None,
                "status": "AVAILABLE" if level_gaps else "INSUFFICIENT_SAMPLE",
                "observations_available": len(level_gaps),
                "observations_required": 1,
                "unit": "index_points",
            },
            "mean_absolute_percentage_error_on_rebased_levels": {
                "value": round(positive_level_mape, 6) if positive_level_mape is not None else None,
                "status": "AVAILABLE" if positive_level_mape is not None else "INSUFFICIENT_SAMPLE",
                "observations_available": len(timeline),
                "observations_required": 6,
                "unit": "percent",
            },
        },
        "mospi_latest": ({
            "period": cpi_periods[-1],
            "index": round(cpi_latest["value"], 6),
            "mom_change_pct": round(latest_mom, 6) if latest_mom is not None else None,
            "yoy_change_pct": round(latest_yoy, 6) if latest_yoy is not None else None,
            "snapshot_latest_period": cpi_periods[-1],
            "source_code": cpi_latest["row"].get("code"),
            "base_year": cpi_latest["row"].get("base_year"),
        } if cpi_latest else None),
        "timeline": timeline,
        "methodology_note": (
            "Exact YYYY-MM pairing; Vayu period-end levels only; partial months and months below 80% "
            "basket coverage excluded; both levels rebased to 100 at first paired month. "
            "Monthly changes are paired only when adjacent calendar months are both present. "
            "Correlation requires 12 paired changes; mean absolute change gap requires 6."
        ),
    }
