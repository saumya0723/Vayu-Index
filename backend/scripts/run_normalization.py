#!/usr/bin/env python3
"""
VAYU INDEX — Phase 8: Normalization CLI
=========================================

Runs the normalization engine against the Phase 7 outputs and writes the four
Phase 8 outputs.

Governing principle: canonicalize representation, never economic content,
never group membership.

This script READS Phase 6 and Phase 7 outputs and never writes to them.

Usage:
    python scripts/run_normalization.py
    python scripts/run_normalization.py --consolidated path/to/consolidated.csv
"""

from __future__ import annotations

import argparse
import collections
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.normalization import (  # noqa: E402
    read_phase7_csv,
    run_normalization,
    rules as R,
)


DEFAULT_CONSOLIDATED = os.path.join("outputs", "consolidated_airfare_observations.csv")
DEFAULT_FLIGHT_CELLS = os.path.join("outputs", "phase7_flight_cell_report.csv")
DEFAULT_OBSERVATION_MAP = os.path.join("outputs", "phase7_observation_map.csv")
DEFAULT_CANONICAL = os.path.join("outputs", "canonical_airfare_observations.csv")

DEFAULT_OUTPUT = os.path.join("outputs", "normalized_airfare_observations.csv")
DEFAULT_OUTPUT_MAP = os.path.join("outputs", "normalized_observation_map.csv")
DEFAULT_OUTPUT_FLIGHT = os.path.join("outputs", "phase8_flight_cell_normalized.csv")
DEFAULT_OUTPUT_REPORT = os.path.join("outputs", "phase8_normalization_report.csv")


def _count_flags(series) -> collections.Counter:
    counter: collections.Counter = collections.Counter()
    for value in series:
        text = str(value).strip()
        if not text:
            continue
        for flag in text.split("|"):
            if flag:
                counter[flag] += 1
    return counter


def main() -> None:
    parser = argparse.ArgumentParser(
        description="VAYU INDEX Phase 8 — Normalization Engine"
    )
    parser.add_argument("--consolidated", default=DEFAULT_CONSOLIDATED)
    parser.add_argument("--flight-cells", default=DEFAULT_FLIGHT_CELLS)
    parser.add_argument("--observation-map", default=DEFAULT_OBSERVATION_MAP)
    parser.add_argument("--canonical", default=DEFAULT_CANONICAL)
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    parser.add_argument("--output-map", default=DEFAULT_OUTPUT_MAP)
    parser.add_argument("--output-flight", default=DEFAULT_OUTPUT_FLIGHT)
    parser.add_argument("--output-report", default=DEFAULT_OUTPUT_REPORT)
    args = parser.parse_args()

    consolidated = read_phase7_csv(args.consolidated)
    flight_cells = read_phase7_csv(args.flight_cells)
    observation_map = read_phase7_csv(args.observation_map)
    canonical = read_phase7_csv(args.canonical)

    result = run_normalization(consolidated, flight_cells, observation_map, canonical)

    for path in (args.output, args.output_map, args.output_flight, args.output_report):
        directory = os.path.dirname(path)
        if directory:
            os.makedirs(directory, exist_ok=True)

    result.normalized.to_csv(args.output, index=False)
    result.observation_map.to_csv(args.output_map, index=False)
    result.flight_cells.to_csv(args.output_flight, index=False)
    result.report.to_csv(args.output_report, index=False)

    cell_flags = _count_flags(result.normalized["normalization_flags"])
    observation_flags = _count_flags(result.observation_map["normalization_flags"])
    flight_flags = _count_flags(result.flight_cells["normalization_flags"])
    actions = collections.Counter(result.report["action"]) if len(result.report) else {}
    price_states = collections.Counter(result.normalized["price_state"])

    print("VAYU INDEX — Phase 8 Normalization")
    print("=" * 62)
    print("Principle        : canonicalize representation, never economic content")
    print("Currency         : %s (%s)" % (R.CURRENCY_CODE, R.CURRENCY_SOURCE))
    print("Alias maps       : EMPTY BY APPROVAL (fare_class/source/carrier)")
    print("Schema version   : %s" % R.PHASE8_SCHEMA_VERSION)
    print("-" * 62)
    print("Consolidated cells  : %d in -> %d out" % (len(consolidated), len(result.normalized)))
    print("Flight cells        : %d in -> %d out" % (len(flight_cells), len(result.flight_cells)))
    print("Observations        : %d in -> %d out" % (len(observation_map), len(result.observation_map)))
    print("Normalization report: %d row(s)" % len(result.report))
    print("-" * 62)
    print("price_state (consolidated cells):")
    for key, count in sorted(price_states.items()):
        print("  %-28s %d" % (key, count))
    print("Report actions:")
    if actions:
        for key, count in sorted(actions.items()):
            print("  %-28s %d" % (key, count))
    else:
        print("  (none — inputs were already canonical)")
    print("Normalization flags (cells):")
    if cell_flags:
        for key, count in sorted(cell_flags.items()):
            print("  %-28s %d" % (key, count))
    else:
        print("  (none)")
    print("Normalization flags (flight cells):")
    if flight_flags:
        for key, count in sorted(flight_flags.items()):
            print("  %-28s %d" % (key, count))
    else:
        print("  (none)")
    print("Normalization flags (observations):")
    if observation_flags:
        for key, count in sorted(observation_flags.items()):
            print("  %-28s %d" % (key, count))
    else:
        print("  (none)")
    print("-" * 62)
    print("Wrote %s" % args.output)
    print("Wrote %s" % args.output_map)
    print("Wrote %s" % args.output_flight)
    print("Wrote %s" % args.output_report)
    print("NOTE: Phase 8 performs no anomaly detection, no outlier removal, no")
    print("      imputation, no route reversal, no route aggregation and no index")
    print("      calculation. No row is ever added, merged or deleted.")


if __name__ == "__main__":
    main()
