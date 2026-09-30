#!/usr/bin/env python3
"""
VAYU INDEX — Phase 2: Validation CLI
=======================================

Runs the validation engine against the raw synthetic observations,
writes a validated CSV (original fields + verdict fields), prints a
summary, and audits the result against the Phase 1 edge_case_log.csv
ground truth.

Usage:
    python scripts/run_validation.py
    python scripts/run_validation.py --input path/to/raw.csv --output path/to/validated.csv
"""

from __future__ import annotations

import argparse
import os
import sys

# Allow running this script directly (python scripts/run_validation.py)
# without having installed the package.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.validation import (
    load_raw_observations,
    validate_dataframe,
    save_validated_observations,
    summarize,
    print_summary,
    run_edge_case_audit,
)
import pandas as pd


DEFAULT_INPUT = os.path.join("data", "synthetic", "vayu_synthetic_observations.csv")
DEFAULT_OUTPUT = os.path.join("outputs", "validated_airfare_observations.csv")
DEFAULT_EDGE_CASE_LOG = os.path.join("data", "synthetic", "edge_case_log.csv")
DEFAULT_AUDIT_OUTPUT = os.path.join("outputs", "edge_case_audit_report.csv")


def main() -> None:
    parser = argparse.ArgumentParser(description="VAYU INDEX Phase 2 — Validation Engine")
    parser.add_argument("--input", default=DEFAULT_INPUT, help="Path to raw observations CSV")
    parser.add_argument("--output", default=DEFAULT_OUTPUT, help="Path to write validated CSV")
    parser.add_argument(
        "--edge-case-log", default=DEFAULT_EDGE_CASE_LOG, help="Path to edge_case_log.csv"
    )
    parser.add_argument(
        "--audit-output", default=DEFAULT_AUDIT_OUTPUT, help="Path to write the audit report CSV"
    )
    parser.add_argument(
        "--skip-audit", action="store_true", help="Skip the edge-case ground-truth audit"
    )
    args = parser.parse_args()

    print(f"Loading raw observations from: {args.input}")
    raw_df = load_raw_observations(args.input)
    print(f"Loaded {len(raw_df)} raw rows.")
    print()

    print("Running validation engine...")
    validated_df = validate_dataframe(raw_df)

    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    save_validated_observations(validated_df, args.output)
    print(f"Validated dataset written to: {args.output}")
    print()

    summary = summarize(validated_df)
    print("=" * 60)
    print("VALIDATION SUMMARY")
    print("=" * 60)
    print_summary(summary)
    print()

    if not args.skip_audit:
        if os.path.exists(args.edge_case_log):
            edge_case_log_df = pd.read_csv(args.edge_case_log, dtype=str)
            audit_df = run_edge_case_audit(validated_df, edge_case_log_df)
            os.makedirs(os.path.dirname(args.audit_output), exist_ok=True)
            audit_df.to_csv(args.audit_output, index=False)

            print("=" * 60)
            print("EDGE-CASE GROUND-TRUTH AUDIT")
            print("=" * 60)
            pass_count = (audit_df["pass_fail"] == "PASS").sum()
            fail_count = (audit_df["pass_fail"] == "FAIL").sum()
            na_count = (audit_df["pass_fail"] == "NOT_APPLICABLE").sum()
            unknown_count = (audit_df["pass_fail"] == "UNKNOWN_CATEGORY").sum()
            total_cases = len(audit_df)

            print(f"Total logged edge cases: {total_cases}")
            print(f"  PASS:             {pass_count}")
            print(f"  FAIL:             {fail_count}")
            print(f"  NOT_APPLICABLE:   {na_count}")
            print(f"  UNKNOWN_CATEGORY: {unknown_count}")
            print()

            if fail_count > 0:
                print("FAILED CASES:")
                failed = audit_df[audit_df["pass_fail"] == "FAIL"]
                for _, r in failed.iterrows():
                    print(
                        f"  [{r['edge_case_category']}] {r['observation_id']}: "
                        f"expected={r['expected_behavior']}, "
                        f"actual_status={r['actual_validation_status']}, "
                        f"actual_reason={r['actual_validation_reason']}"
                    )
                print()

            print(f"Full audit report written to: {args.audit_output}")
        else:
            print(f"(Edge case log not found at {args.edge_case_log} — skipping audit.)")


if __name__ == "__main__":
    main()
