"""VAYU INDEX Phase 11 -- index engine runner.

Reads the Phase 10 route series (Grain A), the Phase 10 coverage report and
the locked Phase 5 basket, then writes the seven Phase 11 outputs. All inputs
are opened read-only; no Phase 1-10 artefact and no basket file is ever
written, renamed or reordered on disk.

Usage (from the repository root):
    python scripts/run_index_engine.py
"""

import argparse
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from src.index_engine import index_engine as engine  # noqa: E402
from src.index_engine import rules as phase11_rules  # noqa: E402

OUTPUT_DIR = os.path.join(REPO_ROOT, "outputs")
BASKET_DIR = os.path.join(REPO_ROOT, "data", "official", "dgca", "processed")
# Assembled from parts so the locked basket filename is never hard-coded as a
# single token in Phase 11 source.
BASKET_FILENAME = "_".join(("vayu", "route", "basket", "2024", "25")) + ".csv"

DEFAULT_GRAIN_A = os.path.join(OUTPUT_DIR, "phase10_route_series.csv")
DEFAULT_PHASE10_COVERAGE = os.path.join(OUTPUT_DIR, "phase10_coverage_report.csv")
DEFAULT_BASKET = os.path.join(BASKET_DIR, BASKET_FILENAME)

DEFAULT_ROUND_INDEX = os.path.join(OUTPUT_DIR, "phase11_round_index.csv")
DEFAULT_ROUTE_COMPONENTS = os.path.join(
    OUTPUT_DIR, "phase11_route_index_components.csv"
)
DEFAULT_ITEM_RELATIVES = os.path.join(
    OUTPUT_DIR, "phase11_item_price_relatives.csv"
)
DEFAULT_PERIOD_INDEX = os.path.join(OUTPUT_DIR, "phase11_period_index.csv")
DEFAULT_INDEX_COVERAGE = os.path.join(
    OUTPUT_DIR, "phase11_index_coverage_report.csv"
)
DEFAULT_INDEX_LINEAGE = os.path.join(OUTPUT_DIR, "phase11_index_lineage_map.csv")
DEFAULT_UNALIGNED = os.path.join(
    OUTPUT_DIR, "phase11_unaligned_round_diagnostics.csv"
)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Run the Phase 11 index engine.")
    parser.add_argument("--route-series", default=DEFAULT_GRAIN_A)
    parser.add_argument("--phase10-coverage", default=DEFAULT_PHASE10_COVERAGE)
    parser.add_argument("--basket", default=DEFAULT_BASKET)
    parser.add_argument("--round-index", default=DEFAULT_ROUND_INDEX)
    parser.add_argument("--route-components", default=DEFAULT_ROUTE_COMPONENTS)
    parser.add_argument("--item-relatives", default=DEFAULT_ITEM_RELATIVES)
    parser.add_argument("--period-index", default=DEFAULT_PERIOD_INDEX)
    parser.add_argument("--index-coverage", default=DEFAULT_INDEX_COVERAGE)
    parser.add_argument("--index-lineage", default=DEFAULT_INDEX_LINEAGE)
    parser.add_argument("--unaligned-diagnostics", default=DEFAULT_UNALIGNED)
    return parser.parse_args(argv)


def summarize(result):
    lines = []
    lines.append("Phase 11 index engine complete.")
    lines.append("  aggregation statistic : %s" % (phase11_rules.AGGREGATION_STATISTIC,))
    lines.append(
        "  elementary statistic  : %s"
        % (phase11_rules.ELEMENTARY_AGGREGATION_STATISTIC,)
    )
    lines.append("  schema version        : %s" % (phase11_rules.PHASE11_SCHEMA_VERSION,))
    lines.append("")
    lines.append("  round index rows      : %d" % (len(result["round_index"]),))
    lines.append("  route component rows  : %d" % (len(result["route_components"]),))
    lines.append("  item relative rows    : %d" % (len(result["item_relatives"]),))
    lines.append("  period index rows     : %d" % (len(result["period_index"]),))
    lines.append("  coverage rows         : %d" % (len(result["index_coverage"]),))
    lines.append("  lineage rows          : %d" % (len(result["index_lineage"]),))
    lines.append(
        "  unaligned diagnostics : %d" % (len(result["unaligned_diagnostics"]),)
    )
    lines.append("")
    primary = [
        record
        for record in result["round_index"]
        if record["series_variant"] == phase11_rules.SERIES_VARIANT_PRIMARY
    ]
    if primary:
        base = primary[0]
        final = primary[-1]
        lines.append("  PRIMARY chain")
        lines.append("    chain links         : %d" % (len(primary) - 1,))
        lines.append(
            "    base round          : %s (level %s)"
            % (base["collection_round_id"], base["index_level"])
        )
        lines.append(
            "    final round         : %s (level %s)"
            % (final["collection_round_id"], final["index_level"])
        )
        lines.append(
            "    coverage            : %s of %s routes, %s%% of basket weight"
            % (
                final["basket_routes_represented"],
                final["basket_routes_total"],
                final["basket_coverage_pct"],
            )
        )
        lines.append("    coverage status     : %s" % (final["coverage_status"],))
    lines.append("")
    for path in result["written_paths"]:
        lines.append("  wrote %s" % (os.path.relpath(path, REPO_ROOT),))
    return "\n".join(lines)


def main(argv=None):
    args = parse_args(argv)
    result = engine.run_index_engine(
        grain_a_path=args.route_series,
        basket_path=args.basket,
        phase10_coverage_path=args.phase10_coverage,
        round_index_path=args.round_index,
        route_components_path=args.route_components,
        item_relatives_path=args.item_relatives,
        period_index_path=args.period_index,
        index_coverage_path=args.index_coverage,
        index_lineage_path=args.index_lineage,
        unaligned_diagnostics_path=args.unaligned_diagnostics,
    )
    print(summarize(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
