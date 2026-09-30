"""VAYU INDEX Phase 11 -- index engine package.

Phase 11 is read-only with respect to Phases 1-10. It consumes the Phase 10
route-level series (Grain A), the Phase 10 coverage report and the locked
Phase 5 basket, and produces chained weighted Jevons index measures at round,
daily, weekly and monthly grain.

Phase 11 owns index eligibility and index calculation. Route aggregation stays
in Phase 10 and is never moved backward into it.

Exposes the two Phase 11 modules:
    rules         -- locked constants, eligibility, Jevons and chaining maths
    index_engine  -- IO, chain construction and deterministic output ordering
"""

from . import index_engine
from . import rules
from .index_engine import (
    INDEX_COVERAGE_COLUMNS,
    INDEX_LINEAGE_COLUMNS,
    ITEM_RELATIVE_COLUMNS,
    PERIOD_INDEX_COLUMNS,
    ROUND_INDEX_COLUMNS,
    ROUTE_COMPONENT_COLUMNS,
    UNALIGNED_DIAGNOSTIC_COLUMNS,
    aggregate,
    load_basket,
    load_grain_a,
    load_phase10_coverage,
    read_csv,
    rebase_round_index,
    run_index_engine,
    write_csv,
)
from .rules import (
    INDEX_BASE_LEVEL,
    ITEM_KEY_FIELDS,
    PHASE11_SCHEMA_VERSION,
    IndexRuleError,
    elementary_jevons,
    evaluate_index_eligibility,
    price_relative,
    rebase_levels,
    renormalize_weights,
    weighted_jevons,
)

__all__ = [
    "rules",
    "index_engine",
    "PHASE11_SCHEMA_VERSION",
    "INDEX_BASE_LEVEL",
    "ITEM_KEY_FIELDS",
    "IndexRuleError",
    "elementary_jevons",
    "evaluate_index_eligibility",
    "price_relative",
    "rebase_levels",
    "renormalize_weights",
    "weighted_jevons",
    "INDEX_COVERAGE_COLUMNS",
    "INDEX_LINEAGE_COLUMNS",
    "ITEM_RELATIVE_COLUMNS",
    "PERIOD_INDEX_COLUMNS",
    "ROUND_INDEX_COLUMNS",
    "ROUTE_COMPONENT_COLUMNS",
    "UNALIGNED_DIAGNOSTIC_COLUMNS",
    "aggregate",
    "load_basket",
    "load_grain_a",
    "load_phase10_coverage",
    "read_csv",
    "rebase_round_index",
    "run_index_engine",
    "write_csv",
]
