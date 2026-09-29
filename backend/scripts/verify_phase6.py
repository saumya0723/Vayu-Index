#!/usr/bin/env python3
"""
VAYU INDEX — Phase 6: Acceptance Verification
================================================

Independent, read-only verification of the Phase 6 outputs. This does NOT
re-derive the answer from the engine's own internals — it re-reads the CSVs
from disk and checks the acceptance conditions against them, so a bug in the
engine cannot make its own output look correct.

Run AFTER scripts/run_deduplication.py:

    python scripts/verify_phase6.py

Exit code 0 = every check passed.
"""

from __future__ import annotations

import hashlib
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

INPUT_CSV = os.path.join("outputs", "validated_airfare_observations.csv")
AUDITED_CSV = os.path.join("outputs", "deduplicated_airfare_observations.csv")
CANONICAL_CSV = os.path.join("outputs", "canonical_airfare_observations.csv")
AUDIT_REPORT_CSV = os.path.join("outputs", "phase6_duplicate_audit_report.csv")

# The Phase 2 input is an INPUT to Phase 6 and must never be rewritten by it.
EXPECTED_INPUT_SHA256 = "f1220617f380f645b8cb21dc4e8e93a069d17a5b8333835558df33e0b43cf45b"

EXPECTED_TOTAL_ROWS = 783
EXPECTED_VALID_ROWS = 779
EXPECTED_INVALID_ROWS = 4
EXPECTED_CANONICAL_ROWS = 778
EXPECTED_DUPLICATE_GROUPS = 1
EXPECTED_CANONICAL_ID = "OBS00769"
EXPECTED_DUPLICATE_ID = "OBS00770"
INVALID_IDS = ["OBS00775", "OBS00779", "OBS00780", "OBS00781"]

ORIGINAL_COLUMNS = [
    "observation_id", "capture_signature", "economic_signature", "origin",
    "destination", "carrier", "flight_number", "travel_date", "departure_time",
    "collection_timestamp", "advance_purchase_days", "advance_purchase_window",
    "fare_class", "base_fare", "taxes", "fees", "total_fare", "source",
    "availability_status", "is_valid", "validation_status", "validation_reason",
    "validation_errors",
]

AUDIT_COLUMNS = [
    "duplicate_group_id", "is_duplicate", "duplicate_of", "duplicate_reason",
    "retained", "capture_signature_agreement",
]

results = []


def check(label, condition, detail=""):
    results.append((label, bool(condition), detail))
    print("%s  %s%s" % ("PASS" if condition else "FAIL", label,
                        (" — " + detail) if detail else ""))


def sha256_of(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_csv(path):
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def main():
    print("=" * 70)
    print("PHASE 6 ACCEPTANCE VERIFICATION")
    print("=" * 70)

    # 1. Expected outputs exist -------------------------------------------
    for path in (AUDITED_CSV, CANONICAL_CSV, AUDIT_REPORT_CSV):
        check("Output exists: %s" % path, os.path.exists(path))
    if not all(ok for _, ok, _ in results):
        print("\nOutputs missing — run scripts/run_deduplication.py first.")
        return 1

    # 2. Phase 2 input untouched ------------------------------------------
    actual_sha = sha256_of(INPUT_CSV)
    check("Phase 2 input CSV SHA-256 unchanged",
          actual_sha == EXPECTED_INPUT_SHA256, actual_sha)

    audited = read_csv(AUDITED_CSV)
    canonical = read_csv(CANONICAL_CSV)
    report = read_csv(AUDIT_REPORT_CSV)
    source = read_csv(INPUT_CSV)

    # 3. Row preservation ---------------------------------------------------
    check("Audited dataset contains exactly %d observations" % EXPECTED_TOTAL_ROWS,
          len(audited) == EXPECTED_TOTAL_ROWS, str(len(audited)))
    check("No observation_id lost",
          set(audited["observation_id"]) == set(source["observation_id"]))
    check("Original 23 columns preserved in order",
          list(audited.columns)[:23] == ORIGINAL_COLUMNS)
    check("Six audit columns appended",
          list(audited.columns)[23:] == AUDIT_COLUMNS)

    identical = all(
        list(audited[col]) == list(source[col]) for col in ORIGINAL_COLUMNS
    )
    check("Every original column value byte-identical to the input", identical)

    # 4. Canonical analytical view -----------------------------------------
    check("Canonical view contains exactly %d rows" % EXPECTED_CANONICAL_ROWS,
          len(canonical) == EXPECTED_CANONICAL_ROWS, str(len(canonical)))

    # 5. Exactly one confirmed duplicate group ------------------------------
    marked = audited[audited["is_duplicate"] == "True"]
    groups = sorted(set(marked["duplicate_group_id"]))
    check("Exactly %d confirmed duplicate group" % EXPECTED_DUPLICATE_GROUPS,
          len(groups) == EXPECTED_DUPLICATE_GROUPS, ", ".join(groups))
    check("Audit report has one row per confirmed group",
          len(report) == EXPECTED_DUPLICATE_GROUPS, str(len(report)))

    # 6. The specific expected decision -------------------------------------
    canonical_row = audited[audited["observation_id"] == EXPECTED_CANONICAL_ID].iloc[0]
    duplicate_row = audited[audited["observation_id"] == EXPECTED_DUPLICATE_ID].iloc[0]
    check("%s is canonical" % EXPECTED_CANONICAL_ID,
          canonical_row["is_duplicate"] == "False"
          and canonical_row["retained"] == "True"
          and canonical_row["duplicate_reason"] == R.REASON_RETAINED_CANONICAL_OF_DUPLICATE_GROUP)
    check("%s is its duplicate" % EXPECTED_DUPLICATE_ID,
          duplicate_row["is_duplicate"] == "True"
          and duplicate_row["duplicate_of"] == EXPECTED_CANONICAL_ID
          and duplicate_row["retained"] == "False")
    check("Both group members share one duplicate_group_id",
          canonical_row["duplicate_group_id"] == duplicate_row["duplicate_group_id"],
          canonical_row["duplicate_group_id"])
    check("capture_signature_agreement recorded on both members",
          canonical_row["capture_signature_agreement"]
          == duplicate_row["capture_signature_agreement"] != "",
          canonical_row["capture_signature_agreement"])

    # 7. Duplicates are marked, never physically deleted ---------------------
    check("%s still physically present in the audited dataset" % EXPECTED_DUPLICATE_ID,
          EXPECTED_DUPLICATE_ID in set(audited["observation_id"]))
    check("%s excluded from the canonical view only" % EXPECTED_DUPLICATE_ID,
          EXPECTED_DUPLICATE_ID not in set(canonical["observation_id"]))

    # 8. Invalid rows preserved ---------------------------------------------
    invalid = audited[audited["is_valid"] == "False"]
    check("All %d invalid observations present" % EXPECTED_INVALID_ROWS,
          len(invalid) == EXPECTED_INVALID_ROWS, str(len(invalid)))
    check("Invalid observations are the expected ones",
          sorted(invalid["observation_id"]) == INVALID_IDS)
    check("Invalid observations retained and never grouped",
          all(invalid["retained"] == "True")
          and all(invalid["is_duplicate"] == "False")
          and all(invalid["duplicate_reason"] == R.REASON_SKIPPED_INVALID_BY_PHASE2))
    check("Invalid observations excluded from the canonical view",
          not set(INVALID_IDS) & set(canonical["observation_id"]))

    # 9. Determinism and input-order independence ----------------------------
    validated = pd.read_csv(INPUT_CSV, dtype=str, keep_default_na=True)
    validated["is_valid"] = validated["is_valid"].apply(R.parse_is_valid)

    first = run_deduplication(validated)
    second = run_deduplication(validated)
    check("Deterministic rerun produces identical audit decisions",
          first[AUDIT_COLUMNS].equals(second[AUDIT_COLUMNS]))

    shuffled = validated.sample(frac=1.0, random_state=20260910).reset_index(drop=True)
    shuffled_out = run_deduplication(shuffled)
    left = first.set_index("observation_id")[AUDIT_COLUMNS].sort_index()
    right = shuffled_out.set_index("observation_id")[AUDIT_COLUMNS].sort_index()
    check("Shuffled input produces identical audit decisions", left.equals(right))

    check("Canonical view rebuilds identically from the audited dataset",
          len(build_canonical_view(first)) == EXPECTED_CANONICAL_ROWS)
    check("Audit report rebuilds identically",
          len(build_duplicate_audit_report(first)) == EXPECTED_DUPLICATE_GROUPS)

    # 10. Input still untouched after all of the above -----------------------
    check("Phase 2 input CSV SHA-256 still unchanged after verification",
          sha256_of(INPUT_CSV) == EXPECTED_INPUT_SHA256)

    passed = sum(1 for _, ok, _ in results if ok)
    failed = len(results) - passed
    print()
    print("=" * 70)
    print("VERIFICATION: %d passed, %d failed" % (passed, failed))
    print("=" * 70)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
