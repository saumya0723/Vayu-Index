"""Opt-in, bounded live fare collection from the approved Skyscanner partner API."""
from __future__ import annotations

import argparse
from datetime import date
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.collection.skyscanner_live import LiveCollectionBlocked, live_output_directory, planned_searches, run_live_collection


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect approved live airfare quotes from Skyscanner.")
    parser.add_argument("--dry-run", action="store_true", help="Show request count without making network calls.")
    parser.add_argument("--confirm-live", action="store_true", help="Confirm that this run may issue partner API requests.")
    parser.add_argument("--route", action="append", dest="routes", help="Limit to a locked basket route such as DEL-BOM; may be repeated.")
    parser.add_argument("--max-searches", type=int, help="Bound API searches for this run (always subject to the configured maximum).")
    args = parser.parse_args()

    if args.dry_run:
        planned = planned_searches(ROOT, date.today(), args.routes)
        ceiling = args.max_searches if args.max_searches is not None else int(os.environ.get("VAYU_SKYSCANNER_MAX_SEARCHES", "150"))
        print(f"Dry run only: {min(max(ceiling, 0), len(planned))} live search(es) would be scheduled; no network requests were made.")
        return 0
    if not args.confirm_live:
        parser.error("Live collection requires --confirm-live. Use --dry-run to inspect the plan first.")
    try:
        result = run_live_collection(ROOT, selected_routes=args.routes, max_searches=args.max_searches)
    except (LiveCollectionBlocked, ValueError) as exc:
        print(f"Collection blocked: {exc}", file=sys.stderr)
        return 2
    print(f"Run: {result['run_id']}")
    print(f"Status: {result['run_status']}")
    print(f"Completed searches: {result['searches_completed']} / {result['searches_planned']}")
    print(f"Failed searches: {result['searches_failed']}")
    print(f"Live quote observations: {result['observation_count']}")
    print(f"Output: {live_output_directory(ROOT) / 'skyscanner_latest.json'}")
    return 0 if result["run_status"] == "LIVE_COLLECTION_COMPLETE" else 1


if __name__ == "__main__":
    raise SystemExit(main())
