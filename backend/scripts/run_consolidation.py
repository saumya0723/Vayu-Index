#!/usr/bin/env python3
"""
VAYU INDEX — Phase 7: Source Consolidation CLI
================================================

Runs the source-consolidation engine against the Phase 6 canonical
observations and writes the three Phase 7 outputs.

Primary estimator: flight-first, two-stage median — cross-source median
within each flight cell, followed by median across flight-level
representative fares within each economic product and collection round.

This script READS the Phase 6 canonical output and never writes to it.

Usage:
    python scripts/run_consolidation.py
    python scripts/run_consolidation.py --input path/to/canonical.csv
"""

from __future__ import annotations

import argparse
import collections
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.consolidation import (  # noqa: E402
    run_consolidation,
    read_canonical_csv,
    rules as R,
)


DEFAULT_INPUT = os.path.join("outputs", "canonical_airfare_observations.csv")
DEFAULT_OUTPUT = os.path.join("outputs", "consolidated_airfare_observations.csv")
DEFAULT_FLIGHT_REPORT = os.path.join("outputs", "phase7_flight_cell_report.csv")
DEFAULT_OBSERVATION_MAP = os.path.join("outputs", "phase7_observation_map.csv")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="VAYU INDEX Phase 7 — Source Consolidation Engine"
    )
    parser.add_argument(
        "--input", default=DEFAULT_INPUT, help="Path to the Phase 6 canonical CSV"
    )
    parser.add_argument(
        "--output", default=DEFAULT_OUTPUT, help="Path to write the consolidated dataset"
    )
    parser.add_argument(
        "--flight-report",
        default=DEFAULT_FLIGHT_REPORT,
        help="Path to write the flight-cell report (source dispersion detail)",
    )
    parser.add_argument(
        "--observation-map",
        default=DEFAULT_OBSERVATION_MAP,
        help="Path to write the per-observation lineage map",
    )
    args = parser.parse_args()

    df = read_canonical_csv(args.input)
    result = run_consolidation(df)

    for path in (args.output, args.flight_report, args.observation_map):
        directory = os.path.dirname(path)
        if directory:
            os.makedirs(directory, exist_ok=True)

    result.consolidated.to_csv(args.output, index=False)
    result.flight_cells.to_csv(args.flight_report, index=False)
    result.observation_map.to_csv(args.observation_map, index=False)

    coverage = collections.Counter(result.consolidated["source_coverage"])
    status = collections.Counter(result.consolidated["consolidation_status"])
    alignment = collections.Counter(result.consolidated["round_alignment"])
    participation = collections.Counter(result.observation_map["participation_status"])
    rounds = sorted(set(result.consolidated["collection_round_id"]))
    unaligned_rounds = [
        value for value in rounds if value.startswith(R.UNALIGNED_ROUND_ID_PREFIX)
    ]
    anchored_rounds = [value for value in rounds if value.startswith(R.ROUND_ID_PREFIX)]

    print("VAYU INDEX — Phase 7 Source Consolidation")
    print("=" * 62)
    print("Primary estimator : flight-first, two-stage median")
    print("                    (cross-source median within each flight cell,")
    print("                     then median across flight representative fares)")
    print("Round anchors     : %s  (+/- %d min)" % (
        ", ".join(R.ROUND_ANCHORS), R.ROUND_TOLERANCE_MINUTES))
    print("                    %s" % R.ROUND_ANCHORS_PROVENANCE)
    print("-" * 62)
    print("Input observations          : %d" % len(df))
    print("Observation map rows        : %d" % len(result.observation_map))
    print("Flight cells                : %d" % len(result.flight_cells))
    print("Consolidation cells         : %d" % len(result.consolidated))
    print("Anchored rounds             : %d" % len(anchored_rounds))
    print("Unaligned singleton rounds  : %d" % len(unaligned_rounds))
    print("-" * 62)
    print("Consolidation status:")
    for key, count in sorted(status.items()):
        print("  %-28s %d" % (key, count))
    print("Source coverage distribution:")
    for key, count in sorted(coverage.items()):
        print("  %-28s %d" % (key, count))
    print("Round alignment (cells):")
    for key, count in sorted(alignment.items()):
        print("  %-28s %d" % (key, count))
    print("Observation participation:")
    for key, count in sorted(participation.items()):
        print("  %-28s %d" % (key, count))
    print("-" * 62)
    print("Wrote %s" % args.output)
    print("Wrote %s" % args.flight_report)
    print("Wrote %s" % args.observation_map)
    print("NOTE: Phase 7 performs no anomaly detection, no normalization, no")
    print("      route aggregation and no index calculation. Route direction is")
    print("      preserved exactly as stored.")


if __name__ == "__main__":
    main()
