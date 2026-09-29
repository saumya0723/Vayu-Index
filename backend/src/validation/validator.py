"""
VAYU INDEX — Phase 2: Validation Engine
==========================================

Turns raw rule findings (rules.py) into a final per-row validation verdict,
and orchestrates running that verdict across an entire CSV of observations.

Pipeline implemented here:

    RAW CSV -> VALIDATION ENGINE -> VALIDATED DATASET (original fields + verdict)

This module never modifies or drops raw fields. It only ADDS these four
columns to a copy of the data:

    is_valid                 bool
    validation_status        one of: VALID, INVALID,
                              VALID_WITH_MISSING_OPTIONAL_FIELDS,
                              NON_PRICE_AVAILABILITY
    validation_reason        semicolon-joined summary of what determined
                              the status (empty string for a clean VALID row)
    validation_errors        semicolon-joined list of every hard-error code
                              triggered (empty string if none)

Design choice on validation_reason vs validation_errors (documented since
neither is dictated in full by the spec):
- validation_errors always lists every HARD error code triggered, and
  nothing else. Empty for any row without hard errors.
- validation_reason is the human-facing summary: for INVALID rows it
  equals validation_errors (nothing new is lost); for
  VALID_WITH_MISSING_OPTIONAL_FIELDS rows it lists the OPTIONAL_MISSING_*
  notes; for NON_PRICE_AVAILABILITY rows it is "NON_PRICE_AVAILABILITY";
  for a fully clean VALID row it is empty.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Any, List
import pandas as pd

from .rules import run_all_rules, RuleFindings

VALID = "VALID"
INVALID = "INVALID"
VALID_WITH_MISSING_OPTIONAL_FIELDS = "VALID_WITH_MISSING_OPTIONAL_FIELDS"
NON_PRICE_AVAILABILITY = "NON_PRICE_AVAILABILITY"


@dataclass
class ValidationVerdict:
    is_valid: bool
    validation_status: str
    validation_reason: str
    validation_errors: str


def decide_verdict(findings: RuleFindings) -> ValidationVerdict:
    """Turn a RuleFindings object into the final four-field verdict."""
    errors_str = ";".join(findings.hard_errors)

    if findings.hard_errors:
        return ValidationVerdict(
            is_valid=False,
            validation_status=INVALID,
            validation_reason=errors_str,
            validation_errors=errors_str,
        )

    if findings.is_non_price_availability:
        return ValidationVerdict(
            is_valid=True,
            validation_status=NON_PRICE_AVAILABILITY,
            validation_reason=NON_PRICE_AVAILABILITY,
            validation_errors="",
        )

    if findings.optional_notes:
        notes_str = ";".join(findings.optional_notes)
        return ValidationVerdict(
            is_valid=True,
            validation_status=VALID_WITH_MISSING_OPTIONAL_FIELDS,
            validation_reason=notes_str,
            validation_errors="",
        )

    return ValidationVerdict(
        is_valid=True,
        validation_status=VALID,
        validation_reason="",
        validation_errors="",
    )


def validate_row(row: Dict[str, Any]) -> ValidationVerdict:
    """Convenience wrapper: run rules + decide verdict for one row dict.
    This is the function unit tests call directly."""
    findings = run_all_rules(row)
    return decide_verdict(findings)


def validate_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """
    Validate every row of a raw observations DataFrame.

    Returns a NEW DataFrame: all original columns preserved unchanged,
    plus is_valid / validation_status / validation_reason / validation_errors
    appended. The input DataFrame is never mutated.
    """
    validated = df.copy(deep=True)

    statuses: List[bool] = []
    status_labels: List[str] = []
    reasons: List[str] = []
    errors: List[str] = []

    for _, row in df.iterrows():
        verdict = validate_row(row.to_dict())
        statuses.append(verdict.is_valid)
        status_labels.append(verdict.validation_status)
        reasons.append(verdict.validation_reason)
        errors.append(verdict.validation_errors)

    validated["is_valid"] = statuses
    validated["validation_status"] = status_labels
    validated["validation_reason"] = reasons
    validated["validation_errors"] = errors

    return validated


def load_raw_observations(path: str) -> pd.DataFrame:
    """Load the raw observations CSV. Read everything as string so that
    validation rules control all parsing/typing decisions explicitly,
    rather than letting pandas silently coerce types on load."""
    return pd.read_csv(path, dtype=str, keep_default_na=True)


def save_validated_observations(validated: pd.DataFrame, path: str) -> None:
    validated.to_csv(path, index=False)


def summarize(validated: pd.DataFrame) -> Dict[str, Any]:
    """Build the summary statistics printed at the end of a validation run."""
    total = len(validated)
    status_counts = validated["validation_status"].value_counts().to_dict()

    # Count every individual hard-error code across all rows (a row with
    # two errors contributes to two counts here).
    error_counter: Dict[str, int] = {}
    for errors_str in validated["validation_errors"]:
        if not errors_str:
            continue
        for code in errors_str.split(";"):
            error_counter[code] = error_counter.get(code, 0) + 1

    top_failures = sorted(error_counter.items(), key=lambda kv: kv[1], reverse=True)

    return {
        "total": total,
        "valid": status_counts.get(VALID, 0),
        "invalid": status_counts.get(INVALID, 0),
        "valid_with_missing_optional_fields": status_counts.get(
            VALID_WITH_MISSING_OPTIONAL_FIELDS, 0
        ),
        "non_price_availability": status_counts.get(NON_PRICE_AVAILABILITY, 0),
        "top_failures": top_failures,
    }


def print_summary(summary: Dict[str, Any]) -> None:
    print(f"Total observations: {summary['total']}")
    print()
    print(f"Valid: {summary['valid']}")
    print(f"Invalid: {summary['invalid']}")
    print(f"Valid with optional missing fields: {summary['valid_with_missing_optional_fields']}")
    print(f"Non-price availability records: {summary['non_price_availability']}")
    print()
    print("Top validation failures:")
    print()
    if not summary["top_failures"]:
        print("  (none)")
    for code, count in summary["top_failures"]:
        print(f"  {code}: {count}")


def run_edge_case_audit(
    validated: pd.DataFrame, edge_case_log: pd.DataFrame
) -> pd.DataFrame:
    """
    Cross-check every logged Phase 1 edge case against what the validator
    actually produced. Returns an audit DataFrame with one row per logged
    edge case (rows with observation_id == "N/A" are reported as
    NOT_APPLICABLE / not automatically checkable, since they describe an
    absence rather than a specific row).

    This does not modify edge_case_log.csv — it is only read.
    """
    validated_by_id = validated.set_index("observation_id")

    audit_rows = []
    for _, case in edge_case_log.iterrows():
        edge_case_id = case.get("observation_id")
        category = case.get("category")
        expected_handling = case.get("expected_handling")
        note = case.get("note")

        if edge_case_id == "N/A" or edge_case_id not in validated_by_id.index:
            audit_rows.append(
                {
                    "edge_case_category": category,
                    "observation_id": edge_case_id,
                    "expected_behavior": expected_handling,
                    "actual_validation_status": "N/A",
                    "actual_validation_reason": "N/A",
                    "pass_fail": "NOT_APPLICABLE",
                    "note": note,
                }
            )
            continue

        actual = validated_by_id.loc[edge_case_id]
        actual_status = actual["validation_status"]
        actual_reason = actual["validation_reason"]

        pass_fail = _judge_edge_case(category, expected_handling, actual_status, actual_reason)

        audit_rows.append(
            {
                "edge_case_category": category,
                "observation_id": edge_case_id,
                "expected_behavior": expected_handling,
                "actual_validation_status": actual_status,
                "actual_validation_reason": actual_reason,
                "pass_fail": pass_fail,
                "note": note,
            }
        )

    return pd.DataFrame(audit_rows)


def _judge_edge_case(
    category: str, expected_handling: str, actual_status: str, actual_reason: str
) -> str:
    """
    Map a Phase 1 edge-case category to what the VALIDATION stage (only)
    should produce, and compare against what actually happened.

    Categories that belong to LATER stages (duplicate handling, source
    consolidation, anomaly review, poolability) are intentionally judged
    only on whether validation left them structurally usable and did NOT
    wrongly reject them — this engine has no opinion on dedup/anomaly/
    aggregation outcomes, by design.
    """
    # Categories whose correct Phase-2 outcome is a hard INVALID:
    invalid_categories = {
        "INVALID_NEGATIVE_FARE": "NEGATIVE_BASE_FARE",
        "MISSING_SOURCE": "MISSING_SOURCE",
        "MISSING_ROUTE": "MISSING_ROUTE",
        "MISSING_TIMESTAMP": "MISSING_COLLECTION_TIMESTAMP",
    }
    # Categories whose correct Phase-2 outcome is VALID (structurally fine;
    # whatever else is special about them is a later stage's job):
    valid_categories = {
        "BASELINE",
        "GENUINE_REPRICE",
        "DIFFERENT_SOURCE_SAME_PRODUCT",
        "DIFFERENT_PRODUCT",
        "DIFFERENT_FLIGHT_SAME_ROUTE_CLASS",
    }
    # Categories with their own distinct expected validation_status:
    special_categories = {
        "STATISTICAL_OUTLIER": VALID,  # validation must NOT invalidate a high fare
        "MISSING_SUBFIELDS": VALID_WITH_MISSING_OPTIONAL_FIELDS,
        "SOLD_OUT": NON_PRICE_AVAILABILITY,
        "DUPLICATE": VALID,  # validation does not dedupe; duplicate row is still structurally valid
    }

    if category in invalid_categories:
        expected_code = invalid_categories[category]
        ok = actual_status == INVALID and expected_code in actual_reason.split(";")
        return "PASS" if ok else "FAIL"

    if category in valid_categories:
        ok = actual_status in (VALID, VALID_WITH_MISSING_OPTIONAL_FIELDS)
        return "PASS" if ok else "FAIL"

    if category in special_categories:
        ok = actual_status == special_categories[category]
        return "PASS" if ok else "FAIL"

    return "UNKNOWN_CATEGORY"
