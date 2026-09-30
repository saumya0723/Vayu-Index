"""Opt-in, bounded live fare collection from SerpApi Google Flights."""
from __future__ import annotations

import argparse
from datetime import date
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.collection.serpapi_live import (
    PROVIDER_NAME,
    run_live_collection,
)
from src.collection.skyscanner_live import (
    LiveCollectionBlocked,
    live_output_directory,
    planned_searches,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=f"Collect bounded live airfare quotes from {PROVIDER_NAME}."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show planned request count and parameters without making network calls.",
    )
    parser.add_argument(
        "--confirm-live",
        action="store_true",
        help="Confirm that this run may issue live SerpApi API requests.",
    )
    parser.add_argument(
        "--route",
        action="append",
        dest="routes",
        help="Limit to a locked basket route such as DEL-BOM or BOM-DEL; may be repeated.",
    )
    parser.add_argument(
        "--max-searches",
        type=int,
        help="Bound successful fare searches for this run, up to the configured cap.",
    )
    parser.add_argument(
        "--departure-date",
        type=str,
        help="Departure date in YYYY-MM-DD format (defaults to configured or +14 days).",
    )
    parser.add_argument(
        "--return-date",
        type=str,
        help="Return date in YYYY-MM-DD format (required for round-trip).",
    )
    parser.add_argument(
        "--passengers",
        type=int,
        help="Number of adult passengers (1-9).",
    )
    parser.add_argument(
        "--cabin-class",
        choices=["economy", "premium_economy", "business", "first"],
        help="Cabin class preference.",
    )
    parser.add_argument(
        "--trip-type",
        choices=["one_way", "round_trip"],
        help="Trip type: one_way or round_trip.",
    )
    args = parser.parse_args()

    # Parse departure date if specified
    outbound_date = None
    if args.departure_date:
        try:
            outbound_date = date.fromisoformat(args.departure_date)
        except ValueError:
            parser.error(f"Invalid departure-date: {args.departure_date}. Must be YYYY-MM-DD.")

    if args.return_date and not args.departure_date:
        parser.error("--return-date requires --departure-date.")

    if args.dry_run:
        search_date = outbound_date or date.today()
        planned = planned_searches(ROOT, search_date, args.routes)
        configured_cap = int(os.environ.get("VAYU_SERPAPI_MAX_SEARCHES", "150"))
        ceiling = args.max_searches if args.max_searches is not None else configured_cap
        planned_count = min(max(ceiling, 0), configured_cap, len(planned))
        print(f"Dry run only: {planned_count} fare search(es) would be scheduled; no network requests were made.")
        if planned:
            sample = planned[0]
            print(f"Sample planned search: route={sample['route_id']} date={sample['travel_date']}")
        return 0

    if not args.confirm_live:
        parser.error("Live collection requires --confirm-live. Use --dry-run to inspect the plan first.")

    try:
        kwargs = {}
        if args.passengers:
            kwargs["passengers"] = args.passengers
        if args.cabin_class:
            kwargs["cabin_class"] = args.cabin_class
        if args.trip_type:
            kwargs["trip_type"] = args.trip_type
        result = run_live_collection(
            ROOT,
            selected_routes=args.routes,
            max_searches=args.max_searches,
            **kwargs,
        )
    except (LiveCollectionBlocked, ValueError) as exc:
        print(f"Collection blocked: {exc}", file=sys.stderr)
        return 2

    print(f"Run: {result.get('run_id')}")
    print(f"Status: {result.get('run_status')}")
    print(f"Completed searches: {result.get('searches_completed')} / {result.get('searches_planned')}")
    print(f"Failed searches: {result.get('searches_failed')}")
    print(f"Live quote observations: {result.get('observation_count')}")
    print(f"Verified INR quotes: {result.get('verified_observation_count')}")
    print(f"Output: {live_output_directory(ROOT) / 'serpapi_latest.json'}")
    return 0 if result.get("run_status") == "LIVE_COLLECTION_COMPLETE" else 1


if __name__ == "__main__":
    raise SystemExit(main())
