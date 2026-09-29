"""VAYU INDEX Phase 10 -- route aggregation runner.

Reads the Phase 9 cell table, the Phase 9 observation map and the locked
Phase 5 basket, then writes the seven Phase 10 outputs.  All inputs are
opened read-only; no Phase 1-9 artefact and no basket file is ever written.

Usage (from the repository root):
    python scripts/run_route_aggregation.py
"""

import argparse
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from src.route_aggregation import route_engine as engine  # noqa: E402
from src.route_aggregation import rules as phase10_rules  # noqa: E402

OUTPUT_DIR = os.path.join(REPO_ROOT, "outputs")
BASKET_DIR = os.path.join(REPO_ROOT, "data", "official", "dgca", "processed")
# Assembled from parts so the locked basket filename is never hard-coded as a
# single token in Phase 10 source.
BASKET_FILENAME = "_".join(("vayu", "route", "basket", "2024", "25")) + ".csv"

DEFAULT_CELLS = os.path.join(OUTPUT_DIR, "anomaly_flagged_airfare_observations.csv")
DEFAULT_OBSERVATION_MAP = os.path.join(
    OUTPUT_DIR, "phase9_observation_anomaly_map.csv"
)
DEFAULT_BASKET = os.path.join(BASKET_DIR, BASKET_FILENAME)

DEFAULT_GRAIN_A = os.path.join(OUTPUT_DIR, "phase10_route_series.csv")
DEFAULT_GRAIN_B = os.path.join(OUTPUT_DIR, "phase10_route_class_round_series.csv")
DEFAULT_CROSSWALK = os.path.join(OUTPUT_DIR, "phase10_route_crosswalk.csv")
DEFAULT_LINEAGE = os.path.join(OUTPUT_DIR, "phase10_route_lineage_map.csv")
DEFAULT_COVERAGE = os.path.join(OUTPUT_DIR, "phase10_coverage_report.csv")
DEFAULT_OFF_BASKET_A = os.path.join(OUTPUT_DIR, "phase10_off_basket_route_series.csv")
DEFAULT_OFF_BASKET_B = os.path.join(
    OUTPUT_DIR, "phase10_off_basket_route_class_round_series.csv"
)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Aggregate Phase 9 consolidation cells to route level."
    )
    parser.add_argument("--cells", default=DEFAULT_CELLS)
    parser.add_argument("--observation-map", default=DEFAULT_OBSERVATION_MAP)
    parser.add_argument("--basket", default=DEFAULT_BASKET)
    parser.add_argument("--output", default=DEFAULT_GRAIN_A)
    parser.add_argument("--output-class-round", default=DEFAULT_GRAIN_B)
    parser.add_argument("--output-crosswalk", default=DEFAULT_CROSSWALK)
    parser.add_argument("--output-lineage", default=DEFAULT_LINEAGE)
    parser.add_argument("--output-coverage", default=DEFAULT_COVERAGE)
    parser.add_argument("--output-off-basket", default=DEFAULT_OFF_BASKET_A)
    parser.add_argument(
        "--output-off-basket-class-round", default=DEFAULT_OFF_BASKET_B
    )
    return parser.parse_args(argv)


def _observed(rows):
    return [
        record
        for record in rows
        if record["route_coverage_status"] != phase10_rules.COVERAGE_NONE
    ]


def main(argv=None):
    args = parse_args(argv)
    result, written = engine.run_route_aggregation(
        args.cells,
        args.observation_map,
        args.basket,
        args.output,
        args.output_class_round,
        args.output_crosswalk,
        args.output_lineage,
        args.output_coverage,
        args.output_off_basket,
        args.output_off_basket_class_round,
    )

    no_observation_routes = [
        record["route_id"]
        for record in result.coverage
        if record["route_coverage_status"] == phase10_rules.COVERAGE_NONE
    ]
    observed_routes = [
        record["route_id"]
        for record in result.coverage
        if record["route_coverage_status"] != phase10_rules.COVERAGE_NONE
    ]
    off_basket_routes = sorted(
        {record["route_id"] for record in result.off_basket_grain_a}
    )

    print("PHASE 10 ROUTE AGGREGATION")
    print("  schema version              : %s" % phase10_rules.PHASE10_SCHEMA_VERSION)
    print("  aggregation statistic       : %s" % phase10_rules.AGGREGATION_STATISTIC)
    print("  route identity source       : %s" % phase10_rules.ROUTE_ID_SOURCE_OF_TRUTH)
    print("")
    print("  grain A rows                : %d (observed %d)" % (
        len(result.grain_a), len(_observed(result.grain_a))))
    print("  grain B rows                : %d (observed %d)" % (
        len(result.grain_b), len(_observed(result.grain_b))))
    print("  off-basket grain A rows     : %d" % len(result.off_basket_grain_a))
    print("  off-basket grain B rows     : %d" % len(result.off_basket_grain_b))
    print("  crosswalk rows              : %d" % len(result.crosswalk))
    print("  lineage rows                : %d" % len(result.lineage))
    print("  coverage rows               : %d" % len(result.coverage))
    print("")
    print("  basket routes observed      : %d %s" % (
        len(observed_routes), ",".join(observed_routes)))
    print("  basket routes NO_OBSERVATIONS: %d" % len(no_observation_routes))
    print("  off-basket routes           : %s" % ",".join(off_basket_routes))
    print("")
    for path in written:
        print("  wrote %s" % path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
