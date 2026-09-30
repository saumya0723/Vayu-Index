#!/usr/bin/env python3
"""
VAYU INDEX — Phase 6: Deduplication CLI
===========================================

Runs the deduplication engine against the Phase 2 validated observations,
writes the full audited output (all rows preserved) and a derived
canonical/deduplicated view.

Usage:
    python scripts/run_deduplication.py
    python scripts/run_deduplication.py --input path/to/validated.csv --output path/to/deduped.csv
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pandas as pd
from src.deduplication import (
    run_deduplication,
    build_canonical_view,
    build_duplicate_audit_report,
    rules as R,
)


DEFAULT_INPUT = os.path.join("outputs", "validated_airfare_observations.csv")
DEFAULT_OUTPUT = os.path.join("outputs", "deduplicated_airfare_observations.csv")
DEFAULT_CANONICAL_OUTPUT = os.path.join("outputs", "canonical_airfare_observations.csv")
DEFAULT_AUDIT_REPORT = os.path.join("outputs", "phase6_duplicate_audit_report.csv")


def main() -> None:
    parser = argparse.ArgumentParser(description="VAYU INDEX Phase 6 — Deduplication Engine")
    parser.add_argument("--input", default=DEFAULT_INPUT, help="Path to Phase 2 validated CSV")
    parser.add_argument("--output", default=DEFAULT_OUTPUT, help="Path to write full audited CSV")
    parser.add_argument(
        "--canonical-output", default=DEFAULT_CANONICAL_OUTPUT,
        help="Path to write the derived canonical (deduplicated) view",
    )
    parser.add_argument(
        "--audit-report", default=DEFAULT_AUDIT_REPORT,
        help="Path to write the per-duplicate-group audit report",
    )
    args = parser.parse_args()

    print(f"Loading Phase 2 validated observations from: {args.input}")
    validated_df = pd.read_csv(args.input, dtype=str, keep_default_na=True)
    # is_valid was written by Phase 2 as a Python bool then serialized to CSV
    # as the strings "True"/"False" — normalize back to real booleans here
    # so downstream boolean logic is unambiguous. rules.parse_is_valid is
    # strict: an unrecognized verdict raises instead of silently becoming
    # False and quietly shrinking the grouping population.
    validated_df["is_valid"] = validated_df["is_valid"].apply(R.parse_is_valid)
    print(f"Loaded {len(validated_df)} validated rows.")
    print(f"  is_valid=True : {int((validated_df['is_valid'] == True).sum())}")   # noqa: E712
    print(f"  is_valid=False: {int((validated_df['is_valid'] == False).sum())}")  # noqa: E712
    print()

    print("Running deduplication engine...")
    deduped_df = run_deduplication(validated_df)

    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    deduped_df.to_csv(args.output, index=False)
    print(f"Full audited deduplication output written to: {args.output}")

    canonical_df = build_canonical_view(deduped_df)
    os.makedirs(os.path.dirname(args.canonical_output), exist_ok=True)
    canonical_df.to_csv(args.canonical_output, index=False)
    print(f"Canonical (deduplicated) view written to: {args.canonical_output}")

    audit_report_df = build_duplicate_audit_report(deduped_df)
    os.makedirs(os.path.dirname(args.audit_report), exist_ok=True)
    audit_report_df.to_csv(args.audit_report, index=False)
    print(f"Duplicate audit report written to: {args.audit_report}")
    print()

    total = len(deduped_df)
    invalid = int((~(deduped_df["is_valid"] == True)).sum())  # noqa: E712
    valid = total - invalid
    technical_dupes = int(
        (deduped_df["duplicate_reason"].isin(
            [R.REASON_TECHNICAL_DUPLICATE, R.REASON_SOLD_OUT_TECHNICAL_DUPLICATE]
        )).sum()
    )
    ambiguous = int((deduped_df["duplicate_reason"] == R.REASON_AMBIGUOUS_MISSING_TIMESTAMP).sum())
    canonical_count = len(canonical_df)

    print("=" * 60)
    print("PHASE 6 DEDUPLICATION SUMMARY")
    print("=" * 60)
    print(f"Total input observations:        {total}")
    print(f"Valid (Phase 2) processed:       {valid}")
    print(f"Invalid (Phase 2) passed through:{invalid:>6}")
    print(f"Technical duplicates found:      {technical_dupes}")
    print(f"Ambiguous missing-timestamp:      {ambiguous}")
    print(f"Canonical observations retained: {canonical_count}")
    print(f"Confirmed duplicate groups:      {len(audit_report_df)}")
    print()
    print("Duplicate reason breakdown:")
    print(deduped_df["duplicate_reason"].value_counts().to_string())


if __name__ == "__main__":
    main()
