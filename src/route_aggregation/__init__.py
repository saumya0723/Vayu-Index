"""VAYU INDEX Phase 10 -- route-level aggregation package.

Phase 10 is read-only with respect to Phases 1-9. It groups Phase 9
consolidation cells to the Phase 5 canonical undirected route identity and
emits basket-scoped and off-basket diagnostic tables.

Exposes the two Phase 10 modules:
    rules         -- locked constants, canonical identity, median contract
    route_engine  -- IO, aggregation and deterministic output ordering
"""

from . import rules
from . import route_engine
from .rules import (
    PHASE10_SCHEMA_VERSION,
    RouteAggregationRuleError,
    canonical_route_id,
    route_median,
)
from .route_engine import (
    COVERAGE_COLUMNS,
    CROSSWALK_COLUMNS,
    GRAIN_A_COLUMNS,
    GRAIN_B_COLUMNS,
    LINEAGE_COLUMNS,
    aggregate,
    load_basket,
    read_csv,
    run_route_aggregation,
    write_csv,
)

__all__ = [
    "rules",
    "route_engine",
    "PHASE10_SCHEMA_VERSION",
    "RouteAggregationRuleError",
    "canonical_route_id",
    "route_median",
    "COVERAGE_COLUMNS",
    "CROSSWALK_COLUMNS",
    "GRAIN_A_COLUMNS",
    "GRAIN_B_COLUMNS",
    "LINEAGE_COLUMNS",
    "aggregate",
    "load_basket",
    "read_csv",
    "run_route_aggregation",
    "write_csv",
]
