"""Phase 12 acceptance tests for locked backtesting methodology."""
from __future__ import annotations

import csv
import hashlib
import re
import sys
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.backtesting import backtest_engine as E
from src.backtesting import rules as R


def rows(name: str) -> list[dict[str, str]]:
    return E.read_csv(ROOT / "outputs" / name)


def test_exact_yyyy_mm_alignment():
    v=[{"period_grain":"MONTHLY","period_is_partial":"False","period_id":"2026-07"}]
    m=[{"period":"2026-07-01"}]
    assert len(R.exact_month_join(v,m)) == 1


def test_nearest_month_is_not_matched():
    v=[{"period_grain":"MONTHLY","period_is_partial":"False","period_id":"2026-09"}]
    m=[{"period":"2026-07-01"}]
    assert R.exact_month_join(v,m) == []


def test_partial_month_is_never_matched():
    v=[{"period_grain":"MONTHLY","period_is_partial":"True","period_id":"2026-09"}]
    m=[{"period":"2026-09-01"}]
    assert R.exact_month_join(v,m) == []


def test_current_zero_overlap():
    summary=rows("phase12_backtest_summary.csv")[0]
    assert summary["vayu_complete_month_count"] == "0"
    assert summary["reference_period_count"] == "19"
    assert summary["overlapping_level_count"] == "0"
    assert summary["overall_evaluation_status"] == R.NO_OVERLAP


def test_current_statuses():
    summary=rows("phase12_backtest_summary.csv")[0]
    assert summary["backtest_status"] == R.PROTOTYPE_STATUS
    assert summary["production_status"] == R.PRODUCTION_STATUS


def test_september_is_nine_of_ninety_and_excluded():
    row=[item for item in rows("phase12_period_comparison.csv") if item["period_id"]=="2026-09"][0]
    assert row["vayu_round_count"] == "9"
    assert row["vayu_expected_round_count"] == "90"
    assert row["period_exclusion_reason"] == R.PARTIAL_EXCLUSION


def test_all_mospi_rows_retained_in_period_union():
    result=rows("phase12_period_comparison.csv")
    assert sum(1 for item in result if item["reference_original_level"]) == 19


def test_no_interpolated_periods_created():
    periods={item["period_id"] for item in rows("phase12_period_comparison.csv")}
    assert "2026-08" not in periods


def test_no_forward_fill_or_nearest_values():
    september=[item for item in rows("phase12_period_comparison.csv") if item["period_id"]=="2026-09"][0]
    assert september["reference_original_level"] == ""
    assert september["reference_rebased_level"] == ""


def test_rebasing_sets_first_value_to_100():
    assert R.rebase([Decimal("25"),Decimal("30")])[0] == Decimal("100")


def test_rebasing_preserves_change():
    original=[Decimal("125.5"),Decimal("130.75"),Decimal("127")]
    assert R.changes(original) == R.changes(R.rebase(original))


def test_mae_formula():
    assert R.mae([Decimal("1"),Decimal("3")],[Decimal("2"),Decimal("5")]) == Decimal("1.5")


def test_rmse_formula():
    assert R.rmse([Decimal("1"),Decimal("3")],[Decimal("2"),Decimal("5")]) == Decimal("2.5").sqrt()


def test_bias_formula():
    assert R.bias([Decimal("2"),Decimal("4")],[Decimal("1"),Decimal("2")]) == Decimal("1.5")


def test_mape_positive_levels_formula():
    result=R.mape_positive_levels([Decimal("110"),Decimal("90")],[Decimal("100"),Decimal("100")])
    assert result == Decimal("10")


def test_mape_rejects_zero_reference():
    with pytest.raises(ValueError):
        R.mape_positive_levels([Decimal("1")],[Decimal("0")])


def test_direction_zero_matches_only_zero():
    assert R.directional_agreement([Decimal("0"),Decimal("1")],[Decimal("0"),Decimal("-1")]) == Decimal("50")


def test_pearson_perfect_positive():
    assert R.pearson([Decimal("1"),Decimal("2"),Decimal("3")],[Decimal("2"),Decimal("4"),Decimal("6")]) == Decimal("1")


def test_spearman_perfect_reverse():
    assert R.spearman([Decimal("1"),Decimal("2"),Decimal("3")],[Decimal("9"),Decimal("5"),Decimal("1")]) == Decimal("-1")


def test_sample_sd_formula():
    assert R.sample_sd([Decimal("1"),Decimal("2"),Decimal("3")]) == Decimal("1")


def test_minimum_thresholds_exact():
    expected={"MET-DESC-01":1,"MET-MAE-01":6,"MET-RMSE-01":6,"MET-BIAS-01":6,"MET-MAPE-01":6,
              "MET-DIR-01":6,"MET-PEARSON-01":12,"MET-SPEARMAN-01":12,"MET-SD-VAYU-01":12,
              "MET-SD-REF-01":12,"MET-VOL-01":12,"MET-TURN-01":12,"MET-PEAK-01":12,
              "MET-YOY-01":12,"MET-LAG-M1":18,"MET-LAG-00":18,"MET-LAG-P1":18}
    assert {item[0]:item[3] for item in R.METRIC_RULES} == expected


def test_all_external_metrics_blocked():
    metrics=rows("phase12_metric_report.csv")
    assert len(metrics)==17
    assert {item["metric_status"] for item in metrics} == {R.INSUFFICIENT}
    assert all(item["metric_value"]=="" for item in metrics)


def test_lead_lag_explicitly_no_overlap():
    lag=[item for item in rows("phase12_metric_report.csv") if item["metric_id"].startswith("MET-LAG")]
    assert len(lag)==3
    assert all(item["insufficient_sample_reason"]=="NOT_APPLICABLE_NO_OVERLAP" for item in lag)


def test_no_significance_fields():
    header=set(rows("phase12_metric_report.csv")[0])
    assert not {"p_value","confidence_interval","statistical_significance"} & header


def test_dgca_rejected_as_price_reference():
    dgca=[item for item in rows("phase12_reference_metadata.csv") if item["reference_series_id"]==R.REFERENCE_DGCA][0]
    assert dgca["valid_comparison_target"]=="False"
    assert dgca["invalid_use_codes"]=="INVALID_REFERENCE_TYPE_TRAFFIC_NOT_PRICE"


def test_mospi_is_only_valid_price_reference():
    refs=rows("phase12_reference_metadata.csv")
    valid=[item for item in refs if item["valid_comparison_target"]=="True"]
    assert [item["reference_series_id"] for item in valid] == [R.REFERENCE_MOSPI]


def test_mospi_inflation_self_consistency():
    data=E.read_csv(ROOT/"data/official/mospi/processed/mospi_airfare_cpi.csv")
    levels={item["period"][:7]:Decimal(item["cpi_index"]) for item in data}
    checked=0
    for item in data:
        if not item["inflation"]:
            continue
        year=int(item["period"][:4])-1
        prior=f"{year:04d}"+item["period"][4:7]
        expected=(Decimal("100")*(Decimal(item["cpi_index"])/levels[prior]-Decimal("1"))).quantize(Decimal("0.01"),rounding=ROUND_HALF_UP)
        assert abs(expected - Decimal(item["inflation"])) <= Decimal("0.01")
        checked += 1
    assert checked == 7


def test_anomaly_sensitivity_identical():
    data=[item for item in rows("phase12_sensitivity_report.csv") if item["sensitivity_type"]=="ANOMALY"]
    assert len(data)==9
    assert all(item["level_difference"]=="0.000000" for item in data)


def test_anomaly_corpus_artefact_disclosed():
    data=[item for item in rows("phase12_sensitivity_report.csv") if item["sensitivity_type"]=="ANOMALY"]
    assert all("UNALIGNED" in item["corpus_disclosure"] for item in data)


@pytest.mark.parametrize("policy",["SENS-COV-01","SENS-COV-02","SENS-COV-03","SENS-COV-04"])
def test_all_coverage_sensitivities_present(policy):
    data=[item for item in rows("phase12_sensitivity_report.csv") if item["alternative_method_id"]==policy]
    assert len(data)==9
    assert all(item["diagnostic_only"]=="True" for item in data)


def test_equal_route_is_computed():
    data=[item for item in rows("phase12_sensitivity_report.csv") if item["alternative_method_id"]=="SENS-COV-02"]
    assert all(item["alternative_index_level"] for item in data)


def test_log_contribution_is_not_full_index():
    data=[item for item in rows("phase12_sensitivity_report.csv") if item["alternative_method_id"]=="SENS-COV-03"]
    assert all(item["alternative_index_level"]=="" for item in data)
    assert all("NOT_A_FULL_BASKET_INDEX" in item["sensitivity_status"] for item in data)


def test_low_coverage_excludes_every_round():
    data=[item for item in rows("phase12_sensitivity_report.csv") if item["alternative_method_id"]=="SENS-COV-04"]
    assert all(item["sensitivity_status"]=="EXCLUDED_LOW_COVERAGE" for item in data)


def test_coverage_contains_every_policy_round_route():
    data=rows("phase12_coverage_report.csv")
    assert len(data)==4*9*15
    assert len({item["route_id"] for item in data})==15


def test_current_coverage_values():
    data=rows("phase12_coverage_report.csv")
    assert {item["basket_routes_observed"] for item in data}=={"2"}
    assert {item["basket_weight_represented"] for item in data}=={"0.273706"}
    assert {item["basket_weight_missing"] for item in data}=={"0.726294"}


def test_basket_immutable_hash():
    path=ROOT/"data/official/dgca/processed/vayu_route_basket_2024_25.csv"
    assert hashlib.sha256(path.read_bytes()).hexdigest()=="dc57e6d470a2ed9061dd82a92c84943749c3c648cef00b85b3f250df2f87c181"


def test_deterministic_rerun_byte_identical():
    paths=[ROOT/"outputs"/name for name in R.OUTPUT_SCHEMAS]
    before={path.name:hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    E.run_backtest(ROOT)
    after={path.name:hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    assert before==after


def test_exact_join_input_order_independent():
    v=[{"period_grain":"MONTHLY","period_is_partial":"False","period_id":"2026-02"},{"period_grain":"MONTHLY","period_is_partial":"False","period_id":"2026-01"}]
    m=[{"period":"2026-01-01"},{"period":"2026-02-01"}]
    forward=R.exact_month_join(v,m)
    reverse=R.exact_month_join(list(reversed(v)),list(reversed(m)))
    assert [item[0]["period_id"] for item in forward]==[item[0]["period_id"] for item in reverse]


def test_blocked_metrics_have_lineage():
    metrics=rows("phase12_metric_report.csv")
    lineage=rows("phase12_backtest_lineage.csv")
    ids={item["metric_record_id"] for item in lineage}
    assert all(item["metric_record_id"] in ids for item in metrics)


def test_blocked_metric_lineage_covers_all_reference_rows():
    lineage=rows("phase12_backtest_lineage.csv")
    for metric in rows("phase12_metric_report.csv"):
        found=[item for item in lineage if item["metric_record_id"]==metric["metric_record_id"] and item["input_role"]=="REFERENCE_UNPAIRED_ROW"]
        assert len(found)==19


def test_partial_month_retained_in_lineage():
    lineage=rows("phase12_backtest_lineage.csv")
    assert any(item["period_id"]=="2026-09" and item["input_role"]=="VAYU_BLOCKED_PARTIAL_MONTH" for item in lineage)


def test_every_sensitivity_has_lineage():
    lineage={item["sensitivity_record_id"] for item in rows("phase12_backtest_lineage.csv")}
    assert all(item["sensitivity_record_id"] in lineage for item in rows("phase12_sensitivity_report.csv"))


def test_production_gate_has_ten_locked_requirements():
    gate=rows("phase12_thirty_day_gate.csv")
    assert len(gate)==10
    assert {item["gate_id"] for item in gate}=={f"GATE-{n:02d}" for n in range(1,11)}


def test_production_gate_not_satisfied():
    gate=rows("phase12_thirty_day_gate.csv")
    assert any(item["gate_status"]=="FAIL" for item in gate)
    assert all(item["production_status"]==R.PRODUCTION_STATUS for item in gate)


def test_real_data_gate_fails():
    row=[item for item in rows("phase12_thirty_day_gate.csv") if item["gate_id"]=="GATE-10"][0]
    assert row["observed_value"]=="False" and row["gate_status"]=="FAIL"


def test_all_output_schemas_exact():
    for name, columns in R.OUTPUT_SCHEMAS.items():
        with (ROOT/"outputs"/name).open("r",encoding="utf-8",newline="") as handle:
            assert tuple(next(csv.reader(handle)))==tuple(columns)


def test_upstream_hashes_unchanged_by_run():
    before=E.protected_hashes(ROOT)
    E.run_backtest(ROOT)
    assert before==E.protected_hashes(ROOT)


def test_no_banned_implementation_constructs():
    source="\n".join((ROOT/path).read_text(encoding="utf-8") for path in ["src/backtesting/rules.py","src/backtesting/backtest_engine.py","scripts/run_backtesting.py"])
    lowered=source.lower()
    for token in ["sklearn","tensorflow","import random","numpy.random","index_eligible","from src.index_engine","from src.route_aggregation"]:
        assert token not in lowered
    assert ("float"+"(") not in source


def test_no_row_attribute_access():
    source=(ROOT/"src/backtesting/backtest_engine.py").read_text(encoding="utf-8")
    assert re.search(r"\brow\.[A-Za-z_]",source) is None


def test_no_upstream_write_paths_in_engine():
    source=(ROOT/"src/backtesting/backtest_engine.py").read_text(encoding="utf-8")
    writes=re.findall(r"write_csv\(([^\n]+)",source)
    assert all("phase11" not in item and "data/official" not in item for item in writes)
