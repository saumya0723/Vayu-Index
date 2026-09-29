"""VAYU INDEX validation package (Phase 2)."""

from .rules import run_all_rules, RuleFindings
from .validator import (
    validate_row,
    validate_dataframe,
    load_raw_observations,
    save_validated_observations,
    summarize,
    print_summary,
    run_edge_case_audit,
    ValidationVerdict,
    VALID,
    INVALID,
    VALID_WITH_MISSING_OPTIONAL_FIELDS,
    NON_PRICE_AVAILABILITY,
)

__all__ = [
    "run_all_rules",
    "RuleFindings",
    "validate_row",
    "validate_dataframe",
    "load_raw_observations",
    "save_validated_observations",
    "summarize",
    "print_summary",
    "run_edge_case_audit",
    "ValidationVerdict",
    "VALID",
    "INVALID",
    "VALID_WITH_MISSING_OPTIONAL_FIELDS",
    "NON_PRICE_AVAILABILITY",
]
