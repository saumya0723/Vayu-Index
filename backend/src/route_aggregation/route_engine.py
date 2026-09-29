"""VAYU INDEX Phase 10 -- route-level aggregation engine.

Reads Phase 9 consolidation cells plus the Phase 9 observation map, groups
them to ROUTE level using the Phase 5 canonical undirected route identity,
and emits basket-scoped and off-basket tables.  Phase 1-9 artefacts are read
only; nothing upstream is written, renamed or mutated.

DETERMINISTIC ORDERING (contract)
---------------------------------
Output order is a first-class part of this contract: identical inputs in any
input order must serialize byte for byte identically.  No table ever inherits
the incoming row order of the cells, the observation map, or the basket file.
Every builder terminates in an explicit total sort:

  build_grain_a   basket rows -> (numeric basket_rank, route_id, fare_class,
                  advance_purchase_window, travel_date, round_sort_key,
                  collection_round_id)
                  off-basket rows -> the same tuple without basket_rank
  build_grain_b   basket rows -> (numeric basket_rank, route_id, fare_class,
                  round_sort_key, collection_round_id)
                  off-basket rows -> the same tuple without basket_rank
  build_crosswalk (basket-first flag, numeric basket_rank, route_id,
                  observed_directed_pair)
  build_coverage  (numeric basket_rank) -- always 1..15 for the locked basket
  build_lineage   (scope flag, numeric basket_rank, route_id, fare_class,
                  advance_purchase_window, travel_date, round_sort_key,
                  collection_round_id, consolidation_cell_id)

basket_rank is compared NUMERICALLY, never lexically, so rank 10 always
follows rank 9.  Off-basket rows carry no rank and sort after basket rows
using a sentinel that is never written to disk.  round_sort_key precedes
collection_round_id in every key because unaligned round ids sort before
anchored ones lexically, which is not chronological order.

Packed list columns are emitted sorted and de-duplicated for the same reason.
"""

import csv
import os

from . import rules as R

# Rows that are not part of the locked basket sort after every basket row.
# This sentinel is an ordering device only; it is never serialized.
OFF_BASKET_RANK_SENTINEL = 10 ** 9

PARTICIPATION_PARTICIPATED = "PARTICIPATED"
PARTICIPATION_EXCLUDED_SOLD_OUT = "EXCLUDED_SOLD_OUT"
MIXED_DIRECTIONS = "MIXED"

REQUIRED_CELL_COLUMNS = (
    "consolidation_cell_id",
    "origin_canonical",
    "destination_canonical",
    "travel_date_canonical",
    "fare_class_canonical",
    "advance_purchase_window",
    "collection_round_id",
    "round_sort_key",
    "round_alignment",
    "consolidated_fare_normalized",
    "price_state",
    "observation_count",
    "participating_observation_count",
    "sold_out_observation_count",
    "missing_price_observation_count",
    "contributing_observation_ids",
    "source_coverage",
    "participating_source_count",
    "anomaly_rule_ids",
    "anomaly_severity_max",
    "not_evaluable_rule_ids",
    "market_movement_class",
    "recommended_review",
    "retained",
)

REQUIRED_OBSERVATION_COLUMNS = (
    "observation_id",
    "consolidation_cell_id",
    "flight_cell_id",
    "price_state",
    "participation_status",
    "inherited_severity_max",
)

REQUIRED_BASKET_COLUMNS = (
    "basket_rank",
    "traffic_rank",
    "route_id",
    "city_1",
    "city_2",
    "traffic_weight",
)

# -- output schemas --------------------------------------------------------
DIRECTION_COLUMNS = (
    "observed_origin",
    "observed_destination",
    "observed_directed_pair",
    "route_direction_relation",
    "canonicalization_source",
    "observed_direction_preserved",
    "basket_membership",
    "basket_scope",
    "basket_rank",
    "traffic_weight",
    "traffic_weight_is_metadata_only",
)

SHARED_MEASURE_COLUMNS = (
    "route_coverage_status",
    "route_price_state",
    "route_fare_median",
    "route_fare_min",
    "route_fare_max",
    "route_fare_relative_spread",
    "contributing_cell_count",
    "contributing_priced_cell_count",
    "contributing_unpriced_cell_count",
    "anomaly_excluded_cell_count",
    "high_severity_cell_count",
    "review_severity_cell_count",
    "info_severity_cell_count",
    "none_severity_cell_count",
    "anomaly_severity_max",
    "anomaly_rule_ids",
    "not_evaluable_cell_count",
    "not_evaluable_rule_ids",
    "recommended_review",
    "recommended_review_cell_count",
    "market_movement_classes",
    "contributing_observation_count",
    "contributing_observation_id_count",
    "contributing_observation_ids",
    "sold_out_observation_count",
    "excluded_sold_out_observation_count",
    "mapped_observation_count",
    "flight_cell_count",
    "flight_cell_ids",
    "contributing_travel_dates",
    "contributing_travel_date_count",
    "contributing_advance_purchase_windows",
    "contributing_advance_purchase_window_count",
    "consolidation_cell_ids",
)

GRAIN_A_COLUMNS = (
    (
        "route_series_id",
        "route_id",
        "fare_class",
        "advance_purchase_window",
        "travel_date",
        "collection_round_id",
        "round_sort_key",
        "round_alignment",
    )
    + DIRECTION_COLUMNS
    + SHARED_MEASURE_COLUMNS
    + ("aggregation_statistic", "phase10_schema_version")
)

GRAIN_B_COLUMNS = (
    (
        "route_class_round_series_id",
        "route_id",
        "fare_class",
        "collection_round_id",
        "round_sort_key",
        "round_alignment",
        "contributing_grain_a_series_count",
        "contributing_grain_a_series_ids",
    )
    + DIRECTION_COLUMNS
    + SHARED_MEASURE_COLUMNS
    + ("aggregation_statistic", "phase10_schema_version")
)

CROSSWALK_COLUMNS = (
    "observed_directed_pair",
    "observed_origin",
    "observed_destination",
    "route_id",
    "route_direction_relation",
    "canonicalization_source",
    "observed_direction_preserved",
    "basket_membership",
    "basket_scope",
    "basket_rank",
    "traffic_weight",
    "traffic_weight_is_metadata_only",
    "route_coverage_status",
    "observed_cell_count",
    "contributing_observation_count",
    "route_id_ordering",
    "phase10_schema_version",
)

LINEAGE_COLUMNS = (
    "consolidation_cell_id",
    "route_series_id",
    "route_class_round_series_id",
    "route_id",
    "observed_origin",
    "observed_destination",
    "observed_directed_pair",
    "route_direction_relation",
    "canonicalization_source",
    "observed_direction_preserved",
    "basket_membership",
    "basket_scope",
    "basket_rank",
    "fare_class",
    "advance_purchase_window",
    "travel_date",
    "collection_round_id",
    "round_sort_key",
    "round_alignment",
    "consolidated_fare_normalized",
    "price_state",
    "anomaly_severity_max",
    "anomaly_rule_ids",
    "not_evaluable_rule_ids",
    "market_movement_class",
    "recommended_review",
    "retained",
    "contributing_observation_ids",
    "contributing_observation_id_count",
    "excluded_sold_out_observation_ids",
    "excluded_sold_out_observation_count",
    "sold_out_observation_count",
    "mapped_observation_count",
    "flight_cell_ids",
    "flight_cell_count",
    "phase10_schema_version",
)

COVERAGE_COLUMNS = (
    "basket_rank",
    "traffic_rank",
    "route_id",
    "city_1",
    "city_2",
    "traffic_weight",
    "traffic_weight_is_metadata_only",
    "basket_membership",
    "basket_scope",
    "route_coverage_status",
    "route_price_state",
    "observed_directed_pairs",
    "observed_direction_relations",
    "canonicalization_source",
    "observed_direction_preserved",
    "route_fare_median",
    "route_fare_min",
    "route_fare_max",
    "route_fare_relative_spread",
    "observed_cell_count",
    "priced_cell_count",
    "unpriced_cell_count",
    "grain_a_series_count",
    "grain_b_series_count",
    "high_severity_cell_count",
    "review_severity_cell_count",
    "info_severity_cell_count",
    "none_severity_cell_count",
    "not_evaluable_cell_count",
    "recommended_review_cell_count",
    "anomaly_excluded_cell_count",
    "contributing_observation_count",
    "contributing_observation_id_count",
    "excluded_sold_out_observation_count",
    "mapped_observation_count",
    "contributing_travel_date_count",
    "contributing_advance_purchase_window_count",
    "phase10_schema_version",
)


# ==========================================================================
# IO helpers
# ==========================================================================
def read_csv(path):
    with open(path, "r", encoding="utf-8-sig", newline="") as handle:
        return [dict(item) for item in csv.DictReader(handle)]


def write_csv(path, columns, rows):
    directory = os.path.dirname(os.path.abspath(path))
    if directory and not os.path.isdir(directory):
        os.makedirs(directory)
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(columns), lineterminator="\n")
        writer.writeheader()
        for record in rows:
            writer.writerow(record)
    return path


def require_columns(rows, required, label):
    if not rows:
        return
    present = set(rows[0])
    missing = [name for name in required if name not in present]
    if missing:
        raise R.RouteAggregationRuleError(
            "%s is missing required columns: %s" % (label, ", ".join(missing))
        )


def load_basket(path):
    """Read the locked Phase 5 basket READ-ONLY, ordered by numeric rank.

    The file itself is never written, and the caller receives copies so that
    aggregation can never mutate basket state.
    """
    rows = read_csv(path)
    require_columns(rows, REQUIRED_BASKET_COLUMNS, "Phase 5 basket")
    return sorted(
        [dict(item) for item in rows], key=lambda item: R.parse_int(item["basket_rank"])
    )


# ==========================================================================
# cell model
# ==========================================================================
class CellRecord(object):
    """One Phase 9 consolidation cell, projected onto route identity."""

    __slots__ = (
        "cell_id",
        "origin",
        "destination",
        "observed_pair",
        "route_id",
        "travel_date",
        "fare_class",
        "window",
        "round_id",
        "round_sort_key",
        "round_alignment",
        "fare",
        "price_state",
        "severity",
        "anomaly_rule_ids",
        "not_evaluable_rule_ids",
        "market_movement_class",
        "recommended_review",
        "retained",
        "grain_a_key",
        "grain_b_key",
    )

    def __init__(self, record):
        self.cell_id = R.clean_str(record["consolidation_cell_id"])
        self.origin = R.clean_str(record["origin_canonical"]).upper()
        self.destination = R.clean_str(record["destination_canonical"]).upper()
        self.observed_pair = R.directed_pair(self.origin, self.destination)
        self.route_id = R.canonical_route_id(self.origin, self.destination)
        self.travel_date = R.clean_str(record["travel_date_canonical"])
        self.fare_class = R.clean_str(record["fare_class_canonical"])
        self.window = R.clean_str(record["advance_purchase_window"])
        self.round_id = R.clean_str(record["collection_round_id"])
        self.round_sort_key = R.clean_str(record["round_sort_key"])
        self.round_alignment = R.clean_str(record["round_alignment"])
        self.fare = R.parse_money(record["consolidated_fare_normalized"])
        self.price_state = R.clean_str(record["price_state"])
        self.severity = R.normalize_severity(record["anomaly_severity_max"])
        self.anomaly_rule_ids = R.split_list(record["anomaly_rule_ids"])
        self.not_evaluable_rule_ids = R.split_list(record["not_evaluable_rule_ids"])
        self.market_movement_class = R.clean_str(record["market_movement_class"])
        self.recommended_review = R.parse_bool(record["recommended_review"])
        self.retained = R.clean_str(record["retained"])
        self.grain_a_key = R.grain_a_key(
            self.route_id,
            self.fare_class,
            self.window,
            self.travel_date,
            self.round_id,
        )
        self.grain_b_key = R.grain_b_key(self.route_id, self.fare_class, self.round_id)


class ObservationBundle(object):
    """Observation-level lineage for one consolidation cell."""

    __slots__ = (
        "contributing_ids",
        "excluded_sold_out_ids",
        "sold_out_count",
        "mapped_count",
        "flight_cell_ids",
    )

    def __init__(self):
        self.contributing_ids = []
        self.excluded_sold_out_ids = []
        self.sold_out_count = 0
        self.mapped_count = 0
        self.flight_cell_ids = []


def build_cell_records(cells):
    require_columns(cells, REQUIRED_CELL_COLUMNS, "Phase 9 consolidation cells")
    return [CellRecord(record) for record in cells]


def build_observation_index(observations):
    """Group the Phase 9 observation map by consolidation cell.

    Every observation is accounted for: participating observations feed the
    aggregate, EXCLUDED_SOLD_OUT observations are counted separately, and
    neither is ever deleted.
    """
    require_columns(observations, REQUIRED_OBSERVATION_COLUMNS, "Phase 9 observation map")
    index = {}
    for record in observations:
        cell_id = R.clean_str(record["consolidation_cell_id"])
        bundle = index.get(cell_id)
        if bundle is None:
            bundle = ObservationBundle()
            index[cell_id] = bundle
        observation_id = R.clean_str(record["observation_id"])
        status = R.clean_str(record["participation_status"])
        bundle.mapped_count += 1
        if status == PARTICIPATION_PARTICIPATED:
            bundle.contributing_ids.append(observation_id)
        elif status == PARTICIPATION_EXCLUDED_SOLD_OUT:
            bundle.excluded_sold_out_ids.append(observation_id)
        if R.clean_str(record["price_state"]) == R.PRICE_STATE_SOLD_OUT:
            bundle.sold_out_count += 1
        flight_cell_id = R.clean_str(record["flight_cell_id"])
        if flight_cell_id != "":
            bundle.flight_cell_ids.append(flight_cell_id)
    for bundle in index.values():
        bundle.contributing_ids = sorted(set(bundle.contributing_ids))
        bundle.excluded_sold_out_ids = sorted(set(bundle.excluded_sold_out_ids))
        bundle.flight_cell_ids = sorted(set(bundle.flight_cell_ids))
    return index


EMPTY_BUNDLE = ObservationBundle()


# ==========================================================================
# formatting helpers
# ==========================================================================
def _money_text(value):
    if value is None:
        return ""
    return format(value, "f")


def _ratio_text(value):
    if value is None:
        return ""
    return format(value, "f")


def _count_text(value):
    return str(int(value))


def _bool_text(value):
    return "True" if value else "False"


def _basket_rank_value(basket_row):
    """Numeric basket rank used for ordering. Never lexical."""
    if basket_row is None:
        return OFF_BASKET_RANK_SENTINEL
    return R.parse_int(basket_row["basket_rank"], OFF_BASKET_RANK_SENTINEL)


def _bundle_for(index, cell_id):
    return index.get(cell_id, EMPTY_BUNDLE)


def _direction_fields(cells, route_id, basket_row):
    """Observed direction is reported, never rewritten."""
    pairs = sorted({cell.observed_pair for cell in cells})
    in_basket = basket_row is not None
    if not pairs:
        origin = ""
        destination = ""
        pair = ""
        relation = ""
    elif len(pairs) == 1:
        pair = pairs[0]
        origin = cells[0].origin
        destination = cells[0].destination
        relation = R.direction_relation(pair, route_id, in_basket)
    else:
        pair = MIXED_DIRECTIONS
        origin = MIXED_DIRECTIONS
        destination = MIXED_DIRECTIONS
        relation = (
            R.DIRECTION_OFF_BASKET if not in_basket else R.DIRECTION_CANONICALIZED
        )
    return {
        "observed_origin": origin,
        "observed_destination": destination,
        "observed_directed_pair": pair,
        "route_direction_relation": relation,
        "canonicalization_source": R.ROUTE_ID_SOURCE_OF_TRUTH,
        "observed_direction_preserved": "True",
        "basket_membership": R.BASKET_MEMBER if in_basket else R.BASKET_NON_MEMBER,
        "basket_scope": R.BASKET_SCOPE_IN if in_basket else R.BASKET_SCOPE_OUT,
        "basket_rank": R.clean_str(basket_row["basket_rank"]) if in_basket else "",
        "traffic_weight": R.clean_str(basket_row["traffic_weight"]) if in_basket else "",
        "traffic_weight_is_metadata_only": "True",
    }


def _measures(cells, index):
    """Aggregate one group of cells. Every cell participates (D6)."""
    priced = [cell for cell in cells if cell.fare is not None]
    fares = [cell.fare for cell in priced]
    counts = R.severity_counts([cell.severity for cell in cells])

    contributing_ids = []
    excluded_count = 0
    sold_out_count = 0
    mapped_count = 0
    flight_cell_ids = []
    for cell in cells:
        bundle = _bundle_for(index, cell.cell_id)
        contributing_ids.extend(bundle.contributing_ids)
        excluded_count += len(bundle.excluded_sold_out_ids)
        sold_out_count += bundle.sold_out_count
        mapped_count += bundle.mapped_count
        flight_cell_ids.extend(bundle.flight_cell_ids)
    unique_ids = sorted(set(contributing_ids))
    unique_flight_cells = sorted(set(flight_cell_ids))

    anomaly_rules = set()
    not_evaluable_rules = set()
    not_evaluable_cells = 0
    review_cells = 0
    for cell in cells:
        anomaly_rules.update(cell.anomaly_rule_ids)
        if cell.not_evaluable_rule_ids:
            not_evaluable_cells += 1
            not_evaluable_rules.update(cell.not_evaluable_rule_ids)
        if cell.recommended_review:
            review_cells += 1

    if fares:
        median_value = R.route_median(fares)
        min_value = R.minimum(fares)
        max_value = R.maximum(fares)
        spread_value = R.relative_spread(fares)
        price_state = R.ROUTE_PRICE_STATE_PRICED
    else:
        median_value = None
        min_value = None
        max_value = None
        spread_value = None
        price_state = R.ROUTE_PRICE_STATE_NO_PRICE

    return {
        "route_price_state": price_state,
        "route_fare_median": _money_text(median_value),
        "route_fare_min": _money_text(min_value),
        "route_fare_max": _money_text(max_value),
        "route_fare_relative_spread": _ratio_text(spread_value),
        "contributing_cell_count": _count_text(len(cells)),
        "contributing_priced_cell_count": _count_text(len(priced)),
        "contributing_unpriced_cell_count": _count_text(len(cells) - len(priced)),
        "anomaly_excluded_cell_count": "0",
        "high_severity_cell_count": _count_text(counts[R.SEVERITY_HIGH]),
        "review_severity_cell_count": _count_text(counts[R.SEVERITY_REVIEW]),
        "info_severity_cell_count": _count_text(counts[R.SEVERITY_INFO]),
        "none_severity_cell_count": _count_text(counts[R.SEVERITY_NONE]),
        "anomaly_severity_max": R.max_severity([cell.severity for cell in cells]),
        "anomaly_rule_ids": R.join_list(sorted(anomaly_rules)),
        "not_evaluable_cell_count": _count_text(not_evaluable_cells),
        "not_evaluable_rule_ids": R.join_list(sorted(not_evaluable_rules)),
        "recommended_review": _bool_text(review_cells > 0),
        "recommended_review_cell_count": _count_text(review_cells),
        "market_movement_classes": R.join_list(
            R.sorted_unique([cell.market_movement_class for cell in cells])
        ),
        "contributing_observation_count": _count_text(len(contributing_ids)),
        "contributing_observation_id_count": _count_text(len(unique_ids)),
        "contributing_observation_ids": R.join_list(unique_ids),
        "sold_out_observation_count": _count_text(sold_out_count),
        "excluded_sold_out_observation_count": _count_text(excluded_count),
        "mapped_observation_count": _count_text(mapped_count),
        "flight_cell_count": _count_text(len(unique_flight_cells)),
        "flight_cell_ids": R.join_list(unique_flight_cells),
        "contributing_travel_dates": R.join_list(
            R.sorted_unique([cell.travel_date for cell in cells])
        ),
        "contributing_travel_date_count": _count_text(
            len(R.sorted_unique([cell.travel_date for cell in cells]))
        ),
        "contributing_advance_purchase_windows": R.join_list(
            R.sorted_unique([cell.window for cell in cells])
        ),
        "contributing_advance_purchase_window_count": _count_text(
            len(R.sorted_unique([cell.window for cell in cells]))
        ),
        "consolidation_cell_ids": R.join_list(sorted({cell.cell_id for cell in cells})),
    }


def _empty_measures():
    """An explicit NO_OBSERVATIONS placeholder (D4).

    Money stays blank: absent is absent. Zero is never substituted.
    """
    empty = {
        "route_price_state": R.ROUTE_PRICE_STATE_NO_OBSERVATIONS,
        "route_fare_median": "",
        "route_fare_min": "",
        "route_fare_max": "",
        "route_fare_relative_spread": "",
        "anomaly_severity_max": R.SEVERITY_NONE,
        "anomaly_rule_ids": "",
        "not_evaluable_rule_ids": "",
        "recommended_review": "False",
        "market_movement_classes": "",
        "contributing_observation_ids": "",
        "flight_cell_ids": "",
        "contributing_travel_dates": "",
        "contributing_advance_purchase_windows": "",
        "consolidation_cell_ids": "",
    }
    for name in SHARED_MEASURE_COLUMNS:
        if name in empty or name == "route_coverage_status":
            continue
        empty[name] = "0"
    return empty


def _grain_row(columns, identity, measures, coverage, extra):
    record = {name: "" for name in columns}
    record.update(identity)
    record.update(measures)
    record.update(extra)
    record["route_coverage_status"] = coverage
    record["aggregation_statistic"] = R.AGGREGATION_STATISTIC
    record["phase10_schema_version"] = R.PHASE10_SCHEMA_VERSION
    return record


# ==========================================================================
# builders -- every one ends in an explicit deterministic sort
# ==========================================================================
def build_grain_a(route_cells, basket_index, index, in_basket):
    rows = []
    for route_id in route_cells:
        basket_row = basket_index.get(route_id)
        if (basket_row is not None) != in_basket:
            continue
        groups = {}
        for cell in route_cells[route_id]:
            groups.setdefault(cell.grain_a_key, []).append(cell)
        for key in groups:
            cells = groups[key]
            identity = _direction_fields(cells, route_id, basket_row)
            coverage = R.coverage_status(
                [cell.observed_pair for cell in cells], route_id
            )
            rows.append(
                _grain_row(
                    GRAIN_A_COLUMNS,
                    identity,
                    _measures(cells, index),
                    coverage,
                    {
                        "route_series_id": R.grain_a_id(key),
                        "route_id": route_id,
                        "fare_class": cells[0].fare_class,
                        "advance_purchase_window": cells[0].window,
                        "travel_date": cells[0].travel_date,
                        "collection_round_id": cells[0].round_id,
                        "round_sort_key": cells[0].round_sort_key,
                        "round_alignment": cells[0].round_alignment,
                    },
                )
            )
    if in_basket:
        for route_id in basket_index:
            if route_id in route_cells:
                continue
            basket_row = basket_index[route_id]
            rows.append(
                _grain_row(
                    GRAIN_A_COLUMNS,
                    _direction_fields([], route_id, basket_row),
                    _empty_measures(),
                    R.COVERAGE_NONE,
                    {"route_id": route_id},
                )
            )
        # DETERMINISTIC ORDERING: numeric basket_rank first, never input order.
        rows.sort(
            key=lambda record: (
                R.parse_int(record["basket_rank"], OFF_BASKET_RANK_SENTINEL),
                record["route_id"],
                record["fare_class"],
                record["advance_purchase_window"],
                record["travel_date"],
                record["round_sort_key"],
                record["collection_round_id"],
            )
        )
    else:
        rows.sort(
            key=lambda record: (
                record["route_id"],
                record["fare_class"],
                record["advance_purchase_window"],
                record["travel_date"],
                record["round_sort_key"],
                record["collection_round_id"],
            )
        )
    return rows


def build_grain_b(route_cells, basket_index, index, in_basket):
    rows = []
    for route_id in route_cells:
        basket_row = basket_index.get(route_id)
        if (basket_row is not None) != in_basket:
            continue
        groups = {}
        for cell in route_cells[route_id]:
            groups.setdefault(cell.grain_b_key, []).append(cell)
        for key in groups:
            cells = groups[key]
            series_ids = sorted({R.grain_a_id(cell.grain_a_key) for cell in cells})
            identity = _direction_fields(cells, route_id, basket_row)
            coverage = R.coverage_status(
                [cell.observed_pair for cell in cells], route_id
            )
            rows.append(
                _grain_row(
                    GRAIN_B_COLUMNS,
                    identity,
                    _measures(cells, index),
                    coverage,
                    {
                        "route_class_round_series_id": R.grain_b_id(key),
                        "route_id": route_id,
                        "fare_class": cells[0].fare_class,
                        "collection_round_id": cells[0].round_id,
                        "round_sort_key": cells[0].round_sort_key,
                        "round_alignment": cells[0].round_alignment,
                        "contributing_grain_a_series_count": _count_text(
                            len(series_ids)
                        ),
                        "contributing_grain_a_series_ids": R.join_list(series_ids),
                    },
                )
            )
    if in_basket:
        for route_id in basket_index:
            if route_id in route_cells:
                continue
            rows.append(
                _grain_row(
                    GRAIN_B_COLUMNS,
                    _direction_fields([], route_id, basket_index[route_id]),
                    _empty_measures(),
                    R.COVERAGE_NONE,
                    {"route_id": route_id, "contributing_grain_a_series_count": "0"},
                )
            )
        rows.sort(
            key=lambda record: (
                R.parse_int(record["basket_rank"], OFF_BASKET_RANK_SENTINEL),
                record["route_id"],
                record["fare_class"],
                record["round_sort_key"],
                record["collection_round_id"],
            )
        )
    else:
        rows.sort(
            key=lambda record: (
                record["route_id"],
                record["fare_class"],
                record["round_sort_key"],
                record["collection_round_id"],
            )
        )
    return rows


def build_crosswalk(route_cells, basket_index, index):
    rows = []
    for route_id in sorted(set(list(route_cells) + list(basket_index))):
        basket_row = basket_index.get(route_id)
        cells = route_cells.get(route_id, [])
        by_pair = {}
        for cell in cells:
            by_pair.setdefault(cell.observed_pair, []).append(cell)
        if not by_pair:
            if basket_row is None:
                continue
            record = {name: "" for name in CROSSWALK_COLUMNS}
            record.update(_direction_fields([], route_id, basket_row))
            record["route_id"] = route_id
            record["route_coverage_status"] = R.COVERAGE_NONE
            record["observed_cell_count"] = "0"
            record["contributing_observation_count"] = "0"
            record["route_id_ordering"] = R.ROUTE_ID_ORDERING
            record["phase10_schema_version"] = R.PHASE10_SCHEMA_VERSION
            rows.append(record)
            continue
        for pair in sorted(by_pair):
            pair_cells = by_pair[pair]
            observations = 0
            for cell in pair_cells:
                observations += len(_bundle_for(index, cell.cell_id).contributing_ids)
            record = {name: "" for name in CROSSWALK_COLUMNS}
            record.update(_direction_fields(pair_cells, route_id, basket_row))
            record["route_id"] = route_id
            record["route_coverage_status"] = R.coverage_status([pair], route_id)
            record["observed_cell_count"] = _count_text(len(pair_cells))
            record["contributing_observation_count"] = _count_text(observations)
            record["route_id_ordering"] = R.ROUTE_ID_ORDERING
            record["phase10_schema_version"] = R.PHASE10_SCHEMA_VERSION
            rows.append(record)
    # DETERMINISTIC ORDERING: basket rows first, by numeric basket_rank.
    rows.sort(
        key=lambda record: (
            0 if record["basket_membership"] == R.BASKET_MEMBER else 1,
            R.parse_int(record["basket_rank"], OFF_BASKET_RANK_SENTINEL),
            record["route_id"],
            record["observed_directed_pair"],
        )
    )
    return rows


def build_lineage(cell_records, basket_index, index):
    rows = []
    for cell in cell_records:
        basket_row = basket_index.get(cell.route_id)
        bundle = _bundle_for(index, cell.cell_id)
        identity = _direction_fields([cell], cell.route_id, basket_row)
        record = {name: "" for name in LINEAGE_COLUMNS}
        # Lineage is cell-level provenance; the traffic_weight metadata columns
        # deliberately do not exist here, so identity is projected onto the
        # lineage schema rather than copied wholesale.
        for name in identity:
            if name in LINEAGE_COLUMNS:
                record[name] = identity[name]
        record["consolidation_cell_id"] = cell.cell_id
        record["route_series_id"] = R.grain_a_id(cell.grain_a_key)
        record["route_class_round_series_id"] = R.grain_b_id(cell.grain_b_key)
        record["route_id"] = cell.route_id
        record["fare_class"] = cell.fare_class
        record["advance_purchase_window"] = cell.window
        record["travel_date"] = cell.travel_date
        record["collection_round_id"] = cell.round_id
        record["round_sort_key"] = cell.round_sort_key
        record["round_alignment"] = cell.round_alignment
        record["consolidated_fare_normalized"] = _money_text(cell.fare)
        record["price_state"] = cell.price_state
        record["anomaly_severity_max"] = cell.severity
        record["anomaly_rule_ids"] = R.join_list(sorted(cell.anomaly_rule_ids))
        record["not_evaluable_rule_ids"] = R.join_list(
            sorted(cell.not_evaluable_rule_ids)
        )
        record["market_movement_class"] = cell.market_movement_class
        record["recommended_review"] = _bool_text(cell.recommended_review)
        record["retained"] = cell.retained
        record["contributing_observation_ids"] = R.join_list(bundle.contributing_ids)
        record["contributing_observation_id_count"] = _count_text(
            len(bundle.contributing_ids)
        )
        record["excluded_sold_out_observation_ids"] = R.join_list(
            bundle.excluded_sold_out_ids
        )
        record["excluded_sold_out_observation_count"] = _count_text(
            len(bundle.excluded_sold_out_ids)
        )
        record["sold_out_observation_count"] = _count_text(bundle.sold_out_count)
        record["mapped_observation_count"] = _count_text(bundle.mapped_count)
        record["flight_cell_ids"] = R.join_list(bundle.flight_cell_ids)
        record["flight_cell_count"] = _count_text(len(bundle.flight_cell_ids))
        record["phase10_schema_version"] = R.PHASE10_SCHEMA_VERSION
        rows.append(record)
    # LOCKED lineage ordering: route-natural, NOT basket-rank ordered.
    # consolidation_cell_id is unique per row, so this tuple is a strict
    # total order and remains independent of input order.
    rows.sort(
        key=lambda record: (
            record["route_id"],
            record["fare_class"],
            record["advance_purchase_window"],
            record["travel_date"],
            record["round_sort_key"],
            record["consolidation_cell_id"],
        )
    )
    return rows


def build_coverage(route_cells, basket, basket_index, index):
    rows = []
    for basket_row in basket:
        route_id = R.clean_str(basket_row["route_id"])
        cells = route_cells.get(route_id, [])
        record = {name: "" for name in COVERAGE_COLUMNS}
        record["basket_rank"] = R.clean_str(basket_row["basket_rank"])
        record["traffic_rank"] = R.clean_str(basket_row["traffic_rank"])
        record["route_id"] = route_id
        record["city_1"] = R.clean_str(basket_row["city_1"])
        record["city_2"] = R.clean_str(basket_row["city_2"])
        record["traffic_weight"] = R.clean_str(basket_row["traffic_weight"])
        record["traffic_weight_is_metadata_only"] = "True"
        record["basket_membership"] = R.BASKET_MEMBER
        record["basket_scope"] = R.BASKET_SCOPE_IN
        record["canonicalization_source"] = R.ROUTE_ID_SOURCE_OF_TRUTH
        record["observed_direction_preserved"] = "True"
        record["anomaly_excluded_cell_count"] = "0"
        record["phase10_schema_version"] = R.PHASE10_SCHEMA_VERSION
        pairs = sorted({cell.observed_pair for cell in cells})
        record["observed_directed_pairs"] = R.join_list(pairs)
        record["observed_direction_relations"] = R.join_list(
            sorted({R.direction_relation(pair, route_id, True) for pair in pairs})
        )
        record["route_coverage_status"] = R.coverage_status(pairs, route_id)
        if not cells:
            for name in (
                "route_fare_median",
                "route_fare_min",
                "route_fare_max",
                "route_fare_relative_spread",
            ):
                record[name] = ""
            for name in (
                "observed_cell_count",
                "priced_cell_count",
                "unpriced_cell_count",
                "grain_a_series_count",
                "grain_b_series_count",
                "high_severity_cell_count",
                "review_severity_cell_count",
                "info_severity_cell_count",
                "none_severity_cell_count",
                "not_evaluable_cell_count",
                "recommended_review_cell_count",
                "contributing_observation_count",
                "contributing_observation_id_count",
                "excluded_sold_out_observation_count",
                "mapped_observation_count",
                "contributing_travel_date_count",
                "contributing_advance_purchase_window_count",
            ):
                record[name] = "0"
            record["route_price_state"] = R.ROUTE_PRICE_STATE_NO_OBSERVATIONS
            rows.append(record)
            continue
        measures = _measures(cells, index)
        record["route_price_state"] = measures["route_price_state"]
        for name in (
            "route_fare_median",
            "route_fare_min",
            "route_fare_max",
            "route_fare_relative_spread",
            "high_severity_cell_count",
            "review_severity_cell_count",
            "info_severity_cell_count",
            "none_severity_cell_count",
            "not_evaluable_cell_count",
            "recommended_review_cell_count",
            "contributing_observation_count",
            "contributing_observation_id_count",
            "excluded_sold_out_observation_count",
            "mapped_observation_count",
            "contributing_travel_date_count",
            "contributing_advance_purchase_window_count",
        ):
            record[name] = measures[name]
        record["observed_cell_count"] = measures["contributing_cell_count"]
        record["priced_cell_count"] = measures["contributing_priced_cell_count"]
        record["unpriced_cell_count"] = measures["contributing_unpriced_cell_count"]
        record["grain_a_series_count"] = _count_text(
            len({cell.grain_a_key for cell in cells})
        )
        record["grain_b_series_count"] = _count_text(
            len({cell.grain_b_key for cell in cells})
        )
        rows.append(record)
    # DETERMINISTIC ORDERING: coverage is always numeric basket_rank 1..N.
    rows.sort(key=lambda record: R.parse_int(record["basket_rank"]))
    return rows


class RouteAggregationOutput(object):
    __slots__ = (
        "grain_a",
        "grain_b",
        "off_basket_grain_a",
        "off_basket_grain_b",
        "crosswalk",
        "lineage",
        "coverage",
    )

    def __init__(
        self,
        grain_a,
        grain_b,
        off_basket_grain_a,
        off_basket_grain_b,
        crosswalk,
        lineage,
        coverage,
    ):
        self.grain_a = grain_a
        self.grain_b = grain_b
        self.off_basket_grain_a = off_basket_grain_a
        self.off_basket_grain_b = off_basket_grain_b
        self.crosswalk = crosswalk
        self.lineage = lineage
        self.coverage = coverage


def aggregate(cells, observations, basket):
    """Aggregate Phase 9 cells to route level. Inputs are never mutated."""
    cell_records = build_cell_records(cells)
    index = build_observation_index(observations)
    basket_rows = sorted(
        [dict(item) for item in basket],
        key=lambda item: R.parse_int(item["basket_rank"]),
    )
    basket_index = {}
    for item in basket_rows:
        basket_index[R.clean_str(item["route_id"])] = item

    route_cells = {}
    for cell in cell_records:
        route_cells.setdefault(cell.route_id, []).append(cell)

    return RouteAggregationOutput(
        build_grain_a(route_cells, basket_index, index, True),
        build_grain_b(route_cells, basket_index, index, True),
        build_grain_a(route_cells, basket_index, index, False),
        build_grain_b(route_cells, basket_index, index, False),
        build_crosswalk(route_cells, basket_index, index),
        build_lineage(cell_records, basket_index, index),
        build_coverage(route_cells, basket_rows, basket_index, index),
    )


def run_route_aggregation(
    cells_path,
    observation_map_path,
    basket_path,
    output,
    output_class_round,
    output_crosswalk,
    output_lineage,
    output_coverage,
    output_off_basket,
    output_off_basket_class_round,
):
    cells = read_csv(cells_path)
    observations = read_csv(observation_map_path)
    basket = load_basket(basket_path)
    result = aggregate(cells, observations, basket)
    written = [
        write_csv(output, GRAIN_A_COLUMNS, result.grain_a),
        write_csv(output_class_round, GRAIN_B_COLUMNS, result.grain_b),
        write_csv(output_crosswalk, CROSSWALK_COLUMNS, result.crosswalk),
        write_csv(output_lineage, LINEAGE_COLUMNS, result.lineage),
        write_csv(output_coverage, COVERAGE_COLUMNS, result.coverage),
        write_csv(output_off_basket, GRAIN_A_COLUMNS, result.off_basket_grain_a),
        write_csv(
            output_off_basket_class_round, GRAIN_B_COLUMNS, result.off_basket_grain_b
        ),
    ]
    return result, written
