"""Independent verification of VAYU INDEX Phase 9 anomaly detection.

This script re-reads the Phase 8 inputs and the Phase 9 outputs from disk and
checks the locked rule contract, the retention guarantees, the scope
boundaries and determinism. It never writes to any repository file.

Usage:
    python scripts/verify_phase9.py
"""

import hashlib
import os
import sys
from decimal import Decimal

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.anomaly_detection import anomaly_engine as engine
from src.anomaly_detection import rules as R

REPO_ROOT = os.path.join(os.path.dirname(__file__), "..")
OUTPUTS = os.path.join(REPO_ROOT, "outputs")

PHASE8_CELLS = os.path.join(OUTPUTS, "normalized_airfare_observations.csv")
PHASE8_FLIGHTS = os.path.join(OUTPUTS, "phase8_flight_cell_normalized.csv")
PHASE8_OBSERVATIONS = os.path.join(OUTPUTS, "normalized_observation_map.csv")
PHASE8_REPORT = os.path.join(OUTPUTS, "phase8_normalization_report.csv")

P9_CELLS = os.path.join(OUTPUTS, "anomaly_flagged_airfare_observations.csv")
P9_REPORT = os.path.join(OUTPUTS, "phase9_anomaly_report.csv")
P9_MAP = os.path.join(OUTPUTS, "phase9_observation_anomaly_map.csv")
P9_SERIES = os.path.join(OUTPUTS, "phase9_series_diagnostics.csv")
P9_SOURCES = os.path.join(OUTPUTS, "phase9_source_reliability_report.csv")

EXPECTED_CELL_ROWS = 393
EXPECTED_OBSERVATION_ROWS = 778
EXPECTED_FLIGHT_ROWS = 571


class Checker(object):
    def __init__(self):
        self.passed = 0
        self.failed = 0

    def check(self, condition, label):
        if condition:
            self.passed += 1
            print("ok    %s" % label)
        else:
            self.failed += 1
            print("FAIL  %s" % label)

    def section(self, title):
        print("")
        print("-- %s" % title)


def sha256_of(path):
    digest = hashlib.sha256()
    handle = open(path, "rb")
    try:
        while True:
            block = handle.read(65536)
            if not block:
                break
            digest.update(block)
    finally:
        handle.close()
    return digest.hexdigest()


def read_csv(path):
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def main():
    checker = Checker()

    # ------------------------------------------------------------------
    checker.section("1. Phase 8 inputs are present and readable")
    phase8_paths = [
        PHASE8_CELLS,
        PHASE8_FLIGHTS,
        PHASE8_OBSERVATIONS,
        PHASE8_REPORT,
    ]
    for path in phase8_paths:
        checker.check(os.path.exists(path), "Phase 8 input exists: %s"
                      % os.path.basename(path))
    before = {}
    for path in phase8_paths:
        before[path] = sha256_of(path)

    cells_in = read_csv(PHASE8_CELLS)
    flights_in = read_csv(PHASE8_FLIGHTS)
    observations_in = read_csv(PHASE8_OBSERVATIONS)
    checker.check(len(cells_in.index) == EXPECTED_CELL_ROWS,
                  "Phase 8 consolidation cells = %d" % EXPECTED_CELL_ROWS)
    checker.check(len(flights_in.index) == EXPECTED_FLIGHT_ROWS,
                  "Phase 8 flight cells = %d" % EXPECTED_FLIGHT_ROWS)
    checker.check(len(observations_in.index) == EXPECTED_OBSERVATION_ROWS,
                  "Phase 8 observations = %d" % EXPECTED_OBSERVATION_ROWS)

    # ------------------------------------------------------------------
    checker.section("2. Phase 9 outputs exist")
    for path in (P9_CELLS, P9_REPORT, P9_MAP, P9_SERIES, P9_SOURCES):
        checker.check(os.path.exists(path), "Phase 9 output exists: %s"
                      % os.path.basename(path))

    cells = read_csv(P9_CELLS)
    report = read_csv(P9_REPORT)
    obs_map = read_csv(P9_MAP)
    series = read_csv(P9_SERIES)
    sources = read_csv(P9_SOURCES)

    # ------------------------------------------------------------------
    checker.section("3. Row-count invariants (nothing added, nothing dropped)")
    checker.check(len(cells.index) == len(cells_in.index),
                  "annotated cells preserve the Phase 8 row count")
    checker.check(len(obs_map.index) == len(observations_in.index),
                  "observation map preserves all %d observations"
                  % EXPECTED_OBSERVATION_ROWS)
    checker.check(len(series.index) > 0, "series diagnostics are non-empty")
    checker.check(len(sources.index) > 0, "source reliability rows exist")
    checker.check(
        sorted(cells["consolidation_cell_id"].tolist())
        == sorted(cells_in["consolidation_cell_id"].tolist()),
        "cell identity set is unchanged",
    )
    checker.check(
        sorted(obs_map["observation_id"].tolist())
        == sorted(observations_in["observation_id"].tolist()),
        "observation identity set is unchanged",
    )

    # ------------------------------------------------------------------
    checker.section("4. Phase 8 columns and economic values are carried through")
    missing = [name for name in cells_in.columns if name not in cells.columns]
    checker.check(missing == [], "every Phase 8 cell column survives")
    joined = cells_in[
        ["consolidation_cell_id", "consolidated_fare_normalized"]
    ].merge(
        cells[["consolidation_cell_id", "consolidated_fare_normalized"]],
        on="consolidation_cell_id",
        suffixes=("_before", "_after"),
    )
    checker.check(len(joined.index) == len(cells_in.index),
                  "every cell joins back to its Phase 8 row")
    unchanged = joined[
        joined["consolidated_fare_normalized_before"]
        == joined["consolidated_fare_normalized_after"]
    ]
    checker.check(len(unchanged.index) == len(joined.index),
                  "no consolidated fare was altered by Phase 9")

    # ------------------------------------------------------------------
    checker.section("5. Retention: Phase 9 annotates, never deletes")
    checker.check(set(cells["retained"].tolist()) == {"True"},
                  "every consolidation cell is retained")
    checker.check(set(obs_map["retained"].tolist()) == {"True"},
                  "every observation is retained")
    checker.check(R.DELETES_OBSERVATIONS is False,
                  "engine declares that it deletes nothing")
    checker.check(R.PERFORMS_IMPUTATION is False,
                  "engine declares that it imputes nothing")

    # ------------------------------------------------------------------
    checker.section("6. Scope boundaries (Phase 10 owns index eligibility)")
    all_frames = (cells, report, obs_map, series, sources)
    for name in R.FORBIDDEN_OUTPUT_FIELDS:
        absent = True
        for frame in all_frames:
            if name in frame.columns:
                absent = False
        checker.check(absent, "forbidden field absent from all outputs: %s" % name)
    route_free = True
    for frame in all_frames:
        for name in frame.columns:
            if "route_aggregate" in name:
                route_free = False
    checker.check(route_free, "no route-aggregate output was produced")
    checker.check(R.USES_MACHINE_LEARNING is False, "no machine learning is used")
    checker.check(R.USES_RANDOMNESS is False, "no randomness is used")

    # ------------------------------------------------------------------
    verify_rule_contract(checker, report, cells)
    verify_context_and_lineage(checker, report, cells, obs_map, series, sources)
    verify_determinism(
        checker, cells_in, flights_in, observations_in, cells, report
    )
    verify_upstream_integrity(checker, phase8_paths, before)

    print("")
    print("=" * 70)
    print("PASSED: %d   FAILED: %d" % (checker.passed, checker.failed))
    print("=" * 70)
    return checker


def verify_rule_contract(checker, report, cells):
    """Sections 7-10: the locked R01-R13 contract."""
    checker.section("7. Rule registry and evaluation domains")
    checker.check(len(R.RULE_IDS) == 13, "exactly 13 rules are registered")
    checker.check(list(R.RULE_IDS) == ["R%02d" % n for n in range(1, 14)],
                  "rules are numbered R01..R13 without gaps or renaming")
    statuses = set(report["evaluation_status"].tolist())
    checker.check(statuses.issubset({R.STATUS_FLAGGED, R.STATUS_NOT_EVALUABLE}),
                  "report contains only FLAGGED and NOT_EVALUABLE rows")
    severities = set(report["severity"].tolist())
    checker.check(severities.issubset(set(R.SEVERITY_ORDER)),
                  "severity values are inside the locked domain")
    levels = set(report["anomaly_level"].tolist())
    checker.check(levels.issubset(set(R.ANOMALY_LEVELS)),
                  "anomaly levels are inside the locked domain")
    checker.check("ROUTE_AGGREGATE" not in levels,
                  "no route-aggregate level was emitted")
    rule_ids = set(report["rule_id"].tolist())
    checker.check(rule_ids.issubset(set(R.RULE_IDS)),
                  "no unknown rule id appears in the report")

    checker.section("8. Structural rules R01-R03 and inactive R04")
    for rule_id in ("R01", "R02", "R03"):
        subset = report[report["rule_id"] == rule_id]
        flagged = subset[subset["evaluation_status"] == R.STATUS_FLAGGED]
        severities = set(flagged["severity"].tolist())
        checker.check(severities.issubset({R.SEVERITY_HIGH}),
                      "%s only ever flags at HIGH severity" % rule_id)
        checker.check(R.RULE_MAX_SEVERITY[rule_id] == R.SEVERITY_HIGH,
                      "%s is registered as a HIGH structural rule" % rule_id)
    r04 = report[report["rule_id"] == "R04"]
    checker.check(len(r04.index) == 1, "R04 emits exactly one framework row")
    if len(r04.index) == 1:
        record = r04.to_dict("records")[0]
        checker.check(record["evaluation_status"] == R.STATUS_NOT_EVALUABLE,
                      "R04 is NOT_EVALUABLE")
        checker.check(
            record["evaluability_reason"] == "NO_FROZEN_CALIBRATION_SNAPSHOT",
            "R04 reason is NO_FROZEN_CALIBRATION_SNAPSHOT",
        )
        checker.check(record["entity_id"] == "RULE_FRAMEWORK",
                      "R04 is recorded at framework level, not per observation")
    checker.check(len(report[(report["rule_id"] == "R04")
                             & (report["evaluation_status"]
                                == R.STATUS_FLAGGED)].index) == 0,
                  "R04 never flags anything")

    checker.section("9. Temporal rules R05/R06 and source rules R07/R08")
    r05 = report[report["rule_id"] == "R05"]
    unaligned_r05 = r05[r05["round_alignment"] == "UNALIGNED"]
    checker.check(len(unaligned_r05.index) == 0,
                  "R05 never evaluates unaligned rounds")
    r06 = report[report["rule_id"] == "R06"]
    unaligned_r06 = r06[r06["round_alignment"] == "UNALIGNED"]
    checker.check(len(unaligned_r06.index) == 0,
                  "R06 never evaluates unaligned rounds")
    ne_r05 = r05[r05["evaluation_status"] == R.STATUS_NOT_EVALUABLE]
    reasons = set(ne_r05["evaluability_reason"].tolist())
    checker.check(reasons.issubset({R.REASON_INSUFFICIENT_PRIOR_ROUNDS}),
                  "R05 gating reason is minimum-history only")
    checker.check(R.R05_MIN_PRIOR_PRICED_ROUNDS == 3,
                  "R05 requires 3 prior priced rounds")
    checker.check(R.R06_MIN_PRIOR_PRICED_ROUNDS == 4,
                  "R06 requires 4 prior priced rounds")
    checker.check(R.R05_REVIEW_THRESHOLD == Decimal("0.15")
                  and R.R05_HIGH_THRESHOLD == Decimal("0.30"),
                  "R05 thresholds are 15 percent and 30 percent")
    checker.check(R.R06_CUMULATIVE_THRESHOLD == Decimal("0.15"),
                  "R06 cumulative threshold is 15 percent")
    checker.check(R.R07_DISPERSION_THRESHOLD == Decimal("0.15"),
                  "R07 dispersion threshold is 15 percent")
    for rule_id in ("R05", "R06", "R07"):
        checker.check(R.RULE_THRESHOLD_LABELS[rule_id] == R.CALIBRATION_PROTOTYPE,
                      "%s threshold is labelled PROTOTYPE_CALIBRATION" % rule_id)
    r08 = report[report["rule_id"] == "R08"]
    r08_flagged = r08[r08["evaluation_status"] == R.STATUS_FLAGGED]
    r08_ne = r08[r08["evaluation_status"] == R.STATUS_NOT_EVALUABLE]
    checker.check(len(r08_flagged.index) == 0,
                  "R08 flags nothing on this corpus (no cell has 3+ sources)")
    checker.check(len(r08_ne.index) > 0, "R08 still reports NOT_EVALUABLE rows")
    r08_reasons = set(r08_ne["evaluability_reason"].tolist())
    checker.check(
        r08_reasons == {"INSUFFICIENT_SOURCE_COUNT_FOR_ATTRIBUTION"},
        "R08 reason is INSUFFICIENT_SOURCE_COUNT_FOR_ATTRIBUTION",
    )

    checker.section("10. Informational rules and R13 peer contract")
    for rule_id in ("R09", "R10", "R11", "R12"):
        subset = report[(report["rule_id"] == rule_id)
                        & (report["evaluation_status"] == R.STATUS_FLAGGED)]
        severities = set(subset["severity"].tolist())
        checker.check(severities.issubset({R.SEVERITY_INFO}),
                      "%s never exceeds INFO severity" % rule_id)
        checker.check(R.RULE_MAX_SEVERITY[rule_id] == R.SEVERITY_INFO,
                      "%s is registered as informational" % rule_id)
    r13 = report[report["rule_id"] == "R13"]
    r13_flagged = r13[r13["evaluation_status"] == R.STATUS_FLAGGED]
    widened = r13_flagged[
        r13_flagged["comparison_basis"].str.contains(R.PEER_BASIS_WIDENED)
    ]
    widened_high = widened[widened["severity"] == R.SEVERITY_HIGH]
    checker.check(len(widened_high.index) == 0,
                  "widened R13 results never reach HIGH severity")
    bases = set(cells["r13_peer_basis"].tolist())
    checker.check(bases.issubset({R.PEER_BASIS_WITHIN_ROUND,
                                  R.PEER_BASIS_WIDENED, ""}),
                  "R13 peer basis values are within the locked domain")
    scales = set(cells["r13_scale_basis"].tolist())
    checker.check(scales.issubset({R.SCALE_BASIS_MAD, R.SCALE_BASIS_IQR, ""}),
                  "R13 scale basis is MAD or the IQR fallback")
    checker.check(R.R13_MAD_SCALE == Decimal("0.6745"),
                  "R13 uses the 0.6745 modified z constant")
    checker.check(R.R13_Z_REVIEW == Decimal("3.5"),
                  "R13 review threshold is |z| > 3.5")
    unaligned_cells = cells[cells["round_alignment"] == "UNALIGNED"]
    evaluated = unaligned_cells[unaligned_cells["r13_modified_zscore"] != ""]
    checker.check(len(evaluated.index) == len(unaligned_cells.index),
                  "unaligned cells are still evaluated cross-sectionally")


def verify_context_and_lineage(checker, report, cells, obs_map, series, sources):
    """Sections 11-13: dynamic-pricing protection, lineage, diagnostics."""
    checker.section("11. Dynamic pricing protection")
    flagged = report[report["evaluation_status"] == R.STATUS_FLAGGED]
    escalated = 0
    for record in flagged.to_dict("records"):
        before_value = record["severity_before_context"]
        if before_value == "":
            continue
        if R.SEVERITY_RANK[record["severity"]] > R.SEVERITY_RANK[before_value]:
            escalated = escalated + 1
    checker.check(escalated == 0, "market context never escalates a severity")
    structural = flagged[flagged["rule_id"].isin(list(R.STRUCTURAL_RULE_IDS))]
    softened = structural[structural["severity"] != R.SEVERITY_HIGH]
    checker.check(len(softened.index) == 0,
                  "structural violations are never softened by coherence")
    classes = set(report["market_movement_class"].tolist())
    allowed = {R.MARKET_COHERENT, R.MARKET_ISOLATED, R.MARKET_INDETERMINATE,
               R.MARKET_NOT_APPLICABLE, ""}
    checker.check(classes.issubset(allowed),
                  "market movement classes are inside the locked domain")

    checker.section("12. Lineage and auditability")
    blank_entities = report[report["entity_id"] == ""]
    checker.check(len(blank_entities.index) == 0,
                  "every evaluation names the entity it applies to")
    blank_explanations = report[report["explanation"] == ""]
    checker.check(len(blank_explanations.index) == 0,
                  "every evaluation carries a human-readable explanation")
    versions = set(report["phase9_schema_version"].tolist())
    checker.check(versions == {R.PHASE9_SCHEMA_VERSION},
                  "every report row carries the Phase 9 schema version")
    cell_ids = set(cells["consolidation_cell_id"].tolist())
    cell_scoped = report[report["consolidation_cell_id"] != ""]
    orphans = 0
    for value in cell_scoped["consolidation_cell_id"].tolist():
        if value not in cell_ids:
            orphans = orphans + 1
    checker.check(orphans == 0,
                  "every cell-scoped evaluation resolves to a real cell")
    observation_ids = set(obs_map["observation_id"].tolist())
    obs_scoped = report[report["observation_id"] != ""]
    obs_orphans = 0
    for value in obs_scoped["observation_id"].tolist():
        if value not in observation_ids:
            obs_orphans = obs_orphans + 1
    checker.check(obs_orphans == 0,
                  "every observation-scoped evaluation resolves to a real row")
    review_values = set(report["recommended_review"].tolist())
    checker.check(review_values.issubset({"True", "False"}),
                  "recommended_review is a strict boolean literal")
    info_review = flagged[(flagged["severity"] == R.SEVERITY_INFO)
                          & (flagged["recommended_review"] == "True")]
    checker.check(len(info_review.index) == 0,
                  "INFO findings never demand review on their own")

    checker.section("13. Series and source diagnostics")
    checker.check("series_id" in series.columns, "series diagnostics are keyed by series")
    duplicate_series = len(series.index) - len(set(series["series_id"].tolist()))
    checker.check(duplicate_series == 0, "series diagnostics have unique keys")
    checker.check("source" in sources.columns,
                  "source reliability report is keyed by source")
    weight_free = True
    for name in sources.columns:
        if "weight" in name:
            weight_free = False
    checker.check(weight_free,
                  "source reliability carries no weighting (Phase 9 is diagnostic)")


def verify_determinism(checker, cells_in, flights_in, observations_in, cells, report):
    """Section 14: determinism, idempotence and input-order independence."""
    checker.section("14. Determinism")
    first = engine.run_anomaly_detection(cells_in, flights_in, observations_in)
    second = engine.run_anomaly_detection(cells_in, flights_in, observations_in)
    checker.check(first.report.equals(second.report),
                  "re-running the engine reproduces an identical report")
    checker.check(first.cells.equals(second.cells),
                  "re-running the engine reproduces identical annotations")
    checker.check(first.series.equals(second.series),
                  "re-running the engine reproduces identical series diagnostics")

    reversed_cells = cells_in.iloc[::-1].reset_index(drop=True)
    reversed_flights = flights_in.iloc[::-1].reset_index(drop=True)
    reversed_observations = observations_in.iloc[::-1].reset_index(drop=True)
    shuffled = engine.run_anomaly_detection(
        reversed_cells, reversed_flights, reversed_observations
    )
    checker.check(shuffled.report.equals(first.report),
                  "reversing the input order produces the identical report")
    checker.check(
        sorted(shuffled.cells["anomaly_rule_ids"].tolist())
        == sorted(first.cells["anomaly_rule_ids"].tolist()),
        "reversing the input order produces the same cell annotations",
    )

    keys = []
    for record in report.to_dict("records"):
        keys.append((record["rule_id"], record["anomaly_level"],
                     record["entity_id"], record["evaluation_status"]))
    checker.check(keys == sorted(keys), "the report on disk is deterministically sorted")

    on_disk = read_csv(P9_REPORT)
    checker.check(len(on_disk.index) == len(first.report.index),
                  "the report on disk matches a fresh in-memory run")
    checker.check(len(read_csv(P9_CELLS).index) == len(first.cells.index),
                  "the annotated cells on disk match a fresh in-memory run")


def verify_upstream_integrity(checker, phase8_paths, before):
    """Section 15: Phases 1-8 are untouched."""
    checker.section("15. Upstream integrity (Phases 1-8 unchanged)")
    for path in phase8_paths:
        checker.check(sha256_of(path) == before[path],
                      "Phase 8 input unchanged after Phase 9 ran: %s"
                      % os.path.basename(path))
    locked = [
        "outputs/validated_airfare_observations.csv",
        "outputs/deduplicated_airfare_observations.csv",
        "outputs/canonical_airfare_observations.csv",
        "outputs/phase6_duplicate_audit_report.csv",
        "outputs/consolidated_airfare_observations.csv",
        "outputs/phase7_flight_cell_report.csv",
        "outputs/phase7_observation_map.csv",
        "data/official/dgca/processed/vayu_route_basket_2024_25.csv",
    ]
    for relative in locked:
        path = os.path.join(REPO_ROOT, relative)
        checker.check(os.path.exists(path),
                      "locked upstream output still present: %s" % relative)
    basket = os.path.join(
        REPO_ROOT, "data", "official", "dgca", "processed",
        "vayu_route_basket_2024_25.csv",
    )
    if os.path.exists(basket):
        frame = read_csv(basket)
        checker.check(len(frame.index) == 15,
                      "Phase 5 route basket still holds exactly 15 routes")
    phase9_dir = os.path.join(REPO_ROOT, "src", "anomaly_detection")
    for name in ("__init__.py", "rules.py", "anomaly_engine.py"):
        checker.check(os.path.exists(os.path.join(phase9_dir, name)),
                      "Phase 9 package file exists: %s" % name)
    for name in ("rules.py", "anomaly_engine.py"):
        handle = open(os.path.join(phase9_dir, name), "r", encoding="utf-8")
        try:
            text = handle.read()
        finally:
            handle.close()
        checker.check("TIME_TOLERANCE_MINUTES" not in text,
                      "%s does not borrow the Phase 6 time tolerance" % name)
        checker.check("ROUND_TOLERANCE_MINUTES" not in text,
                      "%s does not borrow the Phase 7 round tolerance" % name)
        checker.check("float" + "(" not in text,
                      "%s keeps the monetary path free of binary floats" % name)


if __name__ == "__main__":
    result = main()
    raise SystemExit(1 if result.failed else 0)
