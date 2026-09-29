"""Run VAYU INDEX Phase 9 anomaly detection over the Phase 8 outputs.

Phase 8 inputs are opened READ-ONLY. Phase 9 writes only its own five
outputs and never modifies an upstream file.

Usage:
    python scripts/run_anomaly_detection.py
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.anomaly_detection import anomaly_engine as engine


DEFAULT_CELLS = os.path.join("outputs", "normalized_airfare_observations.csv")
DEFAULT_FLIGHT_CELLS = os.path.join("outputs", "phase8_flight_cell_normalized.csv")
DEFAULT_OBSERVATIONS = os.path.join("outputs", "normalized_observation_map.csv")

DEFAULT_OUT_CELLS = os.path.join(
    "outputs", "anomaly_flagged_airfare_observations.csv"
)
DEFAULT_OUT_REPORT = os.path.join("outputs", "phase9_anomaly_report.csv")
DEFAULT_OUT_MAP = os.path.join("outputs", "phase9_observation_anomaly_map.csv")
DEFAULT_OUT_SERIES = os.path.join("outputs", "phase9_series_diagnostics.csv")
DEFAULT_OUT_SOURCES = os.path.join(
    "outputs", "phase9_source_reliability_report.csv"
)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="VAYU INDEX Phase 9 - anomaly detection"
    )
    parser.add_argument("--cells", default=DEFAULT_CELLS)
    parser.add_argument("--flight-cells", default=DEFAULT_FLIGHT_CELLS)
    parser.add_argument("--observation-map", default=DEFAULT_OBSERVATIONS)
    parser.add_argument("--output", default=DEFAULT_OUT_CELLS)
    parser.add_argument("--output-report", default=DEFAULT_OUT_REPORT)
    parser.add_argument("--output-map", default=DEFAULT_OUT_MAP)
    parser.add_argument("--output-series", default=DEFAULT_OUT_SERIES)
    parser.add_argument("--output-sources", default=DEFAULT_OUT_SOURCES)
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)

    cells = engine.read_phase8_csv(args.cells)
    flight_cells = engine.read_phase8_csv(args.flight_cells)
    observations = engine.read_phase8_csv(args.observation_map)

    print("Phase 8 inputs (read-only):")
    print("  consolidation cells : %d rows x %d cols"
          % (len(cells.index), len(cells.columns)))
    print("  flight cells        : %d rows x %d cols"
          % (len(flight_cells.index), len(flight_cells.columns)))
    print("  observations        : %d rows x %d cols"
          % (len(observations.index), len(observations.columns)))

    result = engine.run_anomaly_detection(cells, flight_cells, observations)

    for path in (
        args.output,
        args.output_report,
        args.output_map,
        args.output_series,
        args.output_sources,
    ):
        directory = os.path.dirname(path)
        if directory and not os.path.isdir(directory):
            os.makedirs(directory)

    result.cells.to_csv(args.output, index=False)
    result.report.to_csv(args.output_report, index=False)
    result.observations.to_csv(args.output_map, index=False)
    result.series.to_csv(args.output_series, index=False)
    result.sources.to_csv(args.output_sources, index=False)

    print("\nPhase 9 outputs:")
    print("  %-52s %d rows x %d cols"
          % (args.output, len(result.cells.index), len(result.cells.columns)))
    print("  %-52s %d rows x %d cols"
          % (args.output_report, len(result.report.index),
             len(result.report.columns)))
    print("  %-52s %d rows x %d cols"
          % (args.output_map, len(result.observations.index),
             len(result.observations.columns)))
    print("  %-52s %d rows x %d cols"
          % (args.output_series, len(result.series.index),
             len(result.series.columns)))
    print("  %-52s %d rows x %d cols"
          % (args.output_sources, len(result.sources.index),
             len(result.sources.columns)))

    report = result.report
    flagged = report[report["evaluation_status"] == "FLAGGED"]
    not_evaluable = report[report["evaluation_status"] == "NOT_EVALUABLE"]
    print("\nEvaluations emitted: %d flagged, %d not evaluable"
          % (len(flagged.index), len(not_evaluable.index)))

    print("\nFlags by rule:")
    for rule_id in sorted(set(flagged["rule_id"].tolist())):
        subset = flagged[flagged["rule_id"] == rule_id]
        print("  %s %-32s %d"
              % (rule_id, subset["rule_name"].tolist()[0], len(subset.index)))

    print("\nNOT_EVALUABLE by rule:")
    for rule_id in sorted(set(not_evaluable["rule_id"].tolist())):
        subset = not_evaluable[not_evaluable["rule_id"] == rule_id]
        print("  %s %-32s %d"
              % (rule_id, subset["rule_name"].tolist()[0], len(subset.index)))

    print("\nSeverity distribution (flagged):")
    for severity in ("INFO", "REVIEW", "HIGH"):
        subset = flagged[flagged["severity"] == severity]
        print("  %-8s %d" % (severity, len(subset.index)))

    print("\nR13 peer basis distribution:")
    for basis in sorted(set(result.cells["r13_peer_basis"].tolist())):
        subset = result.cells[result.cells["r13_peer_basis"] == basis]
        print("  %-20s %d" % (basis or "(none)", len(subset.index)))

    print("\nRows recommended for review:")
    cells_flagged = result.cells[result.cells["recommended_review"] == "True"]
    obs_flagged = result.observations[
        result.observations["recommended_review"] == "True"
    ]
    print("  consolidation cells : %d" % len(cells_flagged.index))
    print("  observations        : %d" % len(obs_flagged.index))
    print("\nObservations retained: %d (Phase 9 deletes nothing)"
          % len(result.observations.index))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
