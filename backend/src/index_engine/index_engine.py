"""VAYU INDEX Phase 11 -- index engine.

Reads the Phase 10 route-level series (Grain A), the Phase 10 coverage report
and the locked Phase 5 basket, then emits the Phase 11 index tables. Every
Phase 1-10 artefact is opened read-only; nothing upstream is written, renamed
or mutated, and no route aggregation logic is moved backward into Phase 10.

ESTIMATOR
---------
Two-stage chained weighted Jevons (locked decisions D1-D4):

    r_i,t  = p_i,t / p_i,t-1                       matched item relative
    G_r,t  = exp( mean_i in M_r,t ( ln r_i,t ) )    route elementary Jevons
    J_t    = exp( sum_r ( w~_r,t * ln G_r,t ) )     weighted Jevons link
    I_t    = I_t-1 * J_t,  I_base = 100.000000      chained level

w~_r,t is the locked Phase 5 traffic weight renormalized per link over the
contributing routes only. The weights multiply LOG price relatives; a traffic
weight is never multiplied into a price level. Within a route every matched
item carries equal weight (1/n), because no booking, revenue or seat data
exists anywhere in Phases 1-10 from which any other item weight could be
derived without inventing it.

BASE ROUND DISCLOSURE
---------------------
The base round has no chain link, so chain_factor and the change column are
empty for it. Its coverage columns describe the eligible route set observed in
the base round itself, so that every published round row satisfies the D5
disclosure contract with no blank coverage fields.

DETERMINISTIC ORDERING (contract)
---------------------------------
Output order is part of this contract: identical inputs in any input order
must serialize byte for byte identically. No table inherits the incoming row
order of the Phase 10 files or the basket. Every builder terminates in an
explicit total sort, and basket_rank is always compared NUMERICALLY:

  round index        (variant order, link_sequence)
  route components   (variant order, link_sequence, basket_rank, route_id)
  item relatives     (variant order, link_sequence, basket_rank, route_id,
                     fare_class, advance_purchase_window, travel_date,
                     item_status, item_id)
  period index       (variant order, grain order, period_id)
  coverage report    (variant order, link_sequence, basket_rank)
  lineage map        (variant order, link_sequence, basket_rank, route_id,
                     fare_class, advance_purchase_window, travel_date)
  unaligned rounds   (round_sort_key, collection_round_id)

round_sort_key precedes collection_round_id in every key because unaligned
round ids sort before anchored ones lexically, which is not chronological
order. Packed list columns are emitted sorted and de-duplicated.
"""

import csv
import datetime
import os
from decimal import Decimal
from decimal import localcontext

from . import rules as R

# Ordering device only; never serialized.
OFF_BASKET_RANK_SENTINEL = 10 ** 9
LIST_SEPARATOR = ";"

REQUIRED_GRAIN_A_COLUMNS = (
    "route_series_id",
    "route_id",
    "fare_class",
    "advance_purchase_window",
    "travel_date",
    "collection_round_id",
    "round_sort_key",
    "round_alignment",
    "basket_membership",
    "basket_rank",
    "traffic_weight",
    "route_coverage_status",
    "route_price_state",
    "route_fare_median",
    "anomaly_severity_max",
    "consolidation_cell_ids",
    "contributing_observation_ids",
    "contributing_observation_count",
    "phase10_schema_version",
)

REQUIRED_BASKET_COLUMNS = ("basket_rank", "route_id", "traffic_weight")

REQUIRED_COVERAGE_COLUMNS = (
    "basket_rank",
    "route_id",
    "traffic_weight",
    "route_coverage_status",
)

ROUND_INDEX_COLUMNS = (
    "series_variant",
    "index_series_id",
    "index_inclusion_rule_id",
    "collection_round_id",
    "round_sort_key",
    "round_alignment",
    "link_sequence",
    "link_id",
    "is_base_period",
    "base_round_id",
    "base_round_sort_key",
    "base_period_label",
    "index_base_level",
    "prev_round_id",
    "chain_factor",
    "index_level",
    "index_change_pct_vs_prev_round",
    "matched_product_count",
    "entering_product_count",
    "leaving_product_count",
    "missing_product_count",
    "excluded_product_count",
    "anomaly_excluded_product_count",
    "unpriced_product_count",
    "eligible_product_count",
    "basket_routes_represented",
    "basket_routes_total",
    "basket_weight_represented",
    "basket_weight_missing",
    "basket_coverage_pct",
    "effective_weight_sum",
    "renormalization_applied",
    "coverage_status",
    "none_count",
    "info_count",
    "review_count",
    "high_count",
    "aggregation_statistic",
    "elementary_aggregation_statistic",
    "weight_basis",
    "weight_application",
    "phase10_schema_version",
    "phase11_schema_version",
)

ROUTE_COMPONENT_COLUMNS = (
    "series_variant",
    "index_series_id",
    "link_sequence",
    "link_id",
    "prev_round_id",
    "collection_round_id",
    "round_sort_key",
    "route_id",
    "basket_rank",
    "route_coverage_status",
    "traffic_weight",
    "renormalized_weight",
    "contributed_to_index",
    "matched_product_count",
    "route_elementary_jevons",
    "route_log_relative",
    "weighted_log_contribution",
    "entering_product_count",
    "leaving_product_count",
    "eligible_product_count_prev",
    "eligible_product_count_curr",
    "none_count",
    "info_count",
    "review_count",
    "high_count",
    "fare_class_matched_counts",
    "advance_purchase_window_matched_counts",
    "elementary_aggregation_statistic",
    "within_route_weighting",
    "phase11_schema_version",
)

ITEM_RELATIVE_COLUMNS = (
    "series_variant",
    "index_series_id",
    "link_sequence",
    "link_id",
    "prev_round_id",
    "prev_round_sort_key",
    "collection_round_id",
    "round_sort_key",
    "item_id",
    "route_id",
    "basket_rank",
    "fare_class",
    "advance_purchase_window",
    "travel_date",
    "prev_route_series_id",
    "curr_route_series_id",
    "prev_fare",
    "curr_fare",
    "price_relative",
    "log_price_relative",
    "item_status",
    "index_eligibility_status",
    "index_inclusion_rule_id",
    "anomaly_severity_max",
    "exclusion_reason",
    "phase11_schema_version",
)

PERIOD_INDEX_COLUMNS = (
    "series_variant",
    "index_series_id",
    "period_grain",
    "period_id",
    "period_start_round_id",
    "period_end_round_id",
    "round_count",
    "expected_round_count",
    "period_is_partial",
    "period_end_index_level",
    "period_average_level",
    "period_primary_measure",
    "period_secondary_measure",
    "period_average_is_chain_consistent",
    "index_change_pct_vs_prev_period",
    "matched_product_count_total",
    "basket_routes_represented_min",
    "basket_routes_represented_max",
    "basket_coverage_pct_min",
    "basket_coverage_pct_max",
    "coverage_status",
    "derivation_rule",
    "phase11_schema_version",
)

INDEX_COVERAGE_COLUMNS = (
    "series_variant",
    "index_series_id",
    "collection_round_id",
    "round_sort_key",
    "link_sequence",
    "is_base_period",
    "route_id",
    "basket_rank",
    "traffic_weight",
    "route_coverage_status",
    "eligible_product_count",
    "matched_product_count",
    "contributed_to_index",
    "coverage_contribution_status",
    "renormalized_weight",
    "weight_represented",
    "weight_excluded",
    "basket_routes_total",
    "coverage_status",
    "phase11_schema_version",
)

INDEX_LINEAGE_COLUMNS = (
    "series_variant",
    "index_series_id",
    "link_sequence",
    "link_id",
    "route_id",
    "basket_rank",
    "fare_class",
    "advance_purchase_window",
    "travel_date",
    "item_id",
    "prev_round_id",
    "curr_round_id",
    "prev_route_series_id",
    "curr_route_series_id",
    "prev_fare",
    "curr_fare",
    "price_relative",
    "log_price_relative",
    "renormalized_weight",
    "matched_product_count",
    "contribution_weight",
    "prev_consolidation_cell_ids",
    "curr_consolidation_cell_ids",
    "prev_contributing_observation_ids",
    "curr_contributing_observation_ids",
    "prev_contributing_observation_count",
    "curr_contributing_observation_count",
    "anomaly_severity_max",
    "phase11_schema_version",
)

UNALIGNED_DIAGNOSTIC_COLUMNS = (
    "collection_round_id",
    "round_sort_key",
    "round_alignment",
    "diagnostic_basis",
    "chain_eligible",
    "excluded_from_chain_reason",
    "eligible_product_count",
    "route_count",
    "route_ids",
    "nearest_anchored_round_id",
    "nearest_anchored_round_sort_key",
    "minutes_to_nearest_anchored_round",
    "matched_product_count_vs_nearest_anchored",
    "phase11_schema_version",
)

ALL_OUTPUT_COLUMN_SETS = (
    ROUND_INDEX_COLUMNS,
    ROUTE_COMPONENT_COLUMNS,
    ITEM_RELATIVE_COLUMNS,
    PERIOD_INDEX_COLUMNS,
    INDEX_COVERAGE_COLUMNS,
    INDEX_LINEAGE_COLUMNS,
    UNALIGNED_DIAGNOSTIC_COLUMNS,
)


# ---------------------------------------------------------------------------
# IO helpers
# ---------------------------------------------------------------------------


def read_csv(path):
    with open(path, "r", encoding="utf-8-sig", newline="") as handle:
        return [dict(item) for item in csv.DictReader(handle)]


def write_csv(path, columns, rows):
    R.assert_no_forbidden_fields(columns)
    directory = os.path.dirname(os.path.abspath(path))
    if directory and not os.path.isdir(directory):
        os.makedirs(directory)
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(columns), lineterminator="\n")
        writer.writeheader()
        for record in rows:
            writer.writerow(record)
    return path


def require_columns(records, required, label):
    if not records:
        return
    present = set(records[0])
    missing = [name for name in required if name not in present]
    if missing:
        raise R.IndexRuleError(
            "%s is missing required column(s): %s" % (label, ", ".join(missing))
        )


def text_of(mapping, name):
    value = mapping.get(name, "")
    if value is None:
        return ""
    return str(value).strip()


def packed_list(text):
    if not text:
        return []
    parts = [part.strip() for part in str(text).split(LIST_SEPARATOR)]
    return sorted({part for part in parts if part})


def pack_list(values):
    return LIST_SEPARATOR.join(sorted({str(value) for value in values if str(value)}))


def pack_counts(counter):
    parts = []
    for name in sorted(counter):
        parts.append("%s=%d" % (name, counter[name]))
    return LIST_SEPARATOR.join(parts)


def format_decimal(value):
    if value is None:
        return ""
    return str(value)


def format_bool(value):
    return "True" if value else "False"


def parse_round_moment(round_sort_key):
    """Parse a 'YYYY-MM-DD HH:MM' naive local key. No timezone inference."""
    text = str(round_sort_key).strip()
    try:
        return datetime.datetime.strptime(text[0:16], "%Y-%m-%d %H:%M")
    except ValueError:
        raise R.IndexRuleError("unparsable round_sort_key %r" % (round_sort_key,))


# ---------------------------------------------------------------------------
# Loaders and input contract (verify, never repair)
# ---------------------------------------------------------------------------


def load_basket(path):
    """Load the locked Phase 5 basket read-only.

    The basket is never rewritten, reordered on disk, reweighted or extended.
    """
    records = read_csv(path)
    require_columns(records, REQUIRED_BASKET_COLUMNS, "locked basket")
    if len(records) != R.BASKET_ROUTE_COUNT_EXPECTED:
        raise R.IndexRuleError(
            "locked basket must carry exactly %d routes, found %d"
            % (R.BASKET_ROUTE_COUNT_EXPECTED, len(records))
        )
    basket = []
    seen = set()
    total = Decimal(0)
    for entry in records:
        route_id = text_of(entry, "route_id")
        if route_id in seen:
            raise R.IndexRuleError("duplicate basket route_id %r" % (route_id,))
        seen.add(route_id)
        weight = R.parse_decimal(text_of(entry, "traffic_weight"))
        if weight is None or weight <= 0:
            raise R.IndexRuleError(
                "basket route %r has a non-positive or unparsable traffic weight"
                % (route_id,)
            )
        rank_text = text_of(entry, "basket_rank")
        if not rank_text.isdigit():
            raise R.IndexRuleError(
                "basket route %r has a non-numeric basket_rank %r"
                % (route_id, rank_text)
            )
        total = total + weight
        basket.append(
            {
                "route_id": route_id,
                "basket_rank": int(rank_text),
                "traffic_weight": weight,
            }
        )
    if total != Decimal("1.000000"):
        raise R.IndexRuleError(
            "locked basket weights must sum to 1.000000, found %s" % (total,)
        )
    basket.sort(key=lambda entry: (entry["basket_rank"], entry["route_id"]))
    return basket


def load_grain_a(path, basket):
    """Load and contract-check the Phase 10 Grain A route series."""
    records = read_csv(path)
    require_columns(records, REQUIRED_GRAIN_A_COLUMNS, "phase10 route series")
    basket_ids = {entry["route_id"] for entry in basket}
    seen_keys = set()
    rounds = {}
    for entry in records:
        schema_version = text_of(entry, "phase10_schema_version")
        if schema_version != R.PHASE10_SCHEMA_VERSION_EXPECTED:
            raise R.IndexRuleError(
                "phase10_schema_version must be %r, found %r"
                % (R.PHASE10_SCHEMA_VERSION_EXPECTED, schema_version)
            )
        route_id = text_of(entry, "route_id")
        if route_id not in basket_ids:
            raise R.IndexRuleError(
                "route %r is not in the locked basket; off-basket routes must "
                "never reach the headline index input" % (route_id,)
            )
        coverage_status = text_of(entry, "route_coverage_status")
        round_id = text_of(entry, "collection_round_id")
        if coverage_status == R.COVERAGE_STATUS_NO_OBSERVATIONS:
            continue
        key = (R.item_key(entry), round_id)
        if key in seen_keys:
            raise R.IndexRuleError(
                "duplicate (item, round) key in phase10 route series: %s @ %s"
                % (R.item_id(key[0]), round_id)
            )
        seen_keys.add(key)
        sort_key = text_of(entry, "round_sort_key")
        alignment = text_of(entry, "round_alignment")
        if round_id in rounds:
            if rounds[round_id] != (sort_key, alignment):
                raise R.IndexRuleError(
                    "round %r carries inconsistent sort key or alignment"
                    % (round_id,)
                )
        else:
            rounds[round_id] = (sort_key, alignment)
            parse_round_moment(sort_key)
        if text_of(entry, "route_price_state") == R.PRICE_STATE_PRICED:
            fare = R.parse_decimal(text_of(entry, "route_fare_median"))
            if fare is None:
                raise R.IndexRuleError(
                    "PRICED row %s @ %s has a missing or unparsable fare"
                    % (text_of(entry, "route_series_id"), round_id)
                )
            if fare <= 0:
                raise R.IndexRuleError(
                    "PRICED row %s @ %s has a non-positive fare %s"
                    % (text_of(entry, "route_series_id"), round_id, fare)
                )
            places = R.money_decimal_places(fare)
            if places is None or places > R.MONEY_DECIMAL_PLACES:
                raise R.IndexRuleError(
                    "PRICED row %s @ %s carries more than %d decimal places"
                    % (
                        text_of(entry, "route_series_id"),
                        round_id,
                        R.MONEY_DECIMAL_PLACES,
                    )
                )
    return records


def load_phase10_coverage(path, basket):
    """Load the Phase 10 coverage report and check it against the basket."""
    records = read_csv(path)
    require_columns(records, REQUIRED_COVERAGE_COLUMNS, "phase10 coverage report")
    if len(records) != R.BASKET_ROUTE_COUNT_EXPECTED:
        raise R.IndexRuleError(
            "phase10 coverage report must carry exactly %d rows, found %d"
            % (R.BASKET_ROUTE_COUNT_EXPECTED, len(records))
        )
    basket_ids = {entry["route_id"] for entry in basket}
    coverage = {}
    for entry in records:
        route_id = text_of(entry, "route_id")
        if route_id not in basket_ids:
            raise R.IndexRuleError(
                "phase10 coverage report route %r is not in the locked basket"
                % (route_id,)
            )
        coverage[route_id] = text_of(entry, "route_coverage_status")
    return coverage


def observed_records(records):
    """Phase 10 rows that carry an actual observation, in no particular order."""
    kept = []
    for entry in records:
        if text_of(entry, "route_coverage_status") != R.COVERAGE_STATUS_NO_OBSERVATIONS:
            kept.append(entry)
    return kept


def collect_rounds(records):
    """Ordered round table built from observed Phase 10 rows."""
    rounds = {}
    for entry in observed_records(records):
        round_id = text_of(entry, "collection_round_id")
        rounds[round_id] = {
            "collection_round_id": round_id,
            "round_sort_key": text_of(entry, "round_sort_key"),
            "round_alignment": text_of(entry, "round_alignment"),
        }
    ordered = sorted(
        rounds.values(),
        key=lambda entry: (entry["round_sort_key"], entry["collection_round_id"]),
    )
    return ordered


def anchored_rounds(rounds):
    """D2: only ANCHORED rounds are chain links."""
    return [
        entry
        for entry in rounds
        if R.is_chain_eligible_round(entry["round_alignment"])
    ]


def unaligned_rounds(rounds):
    return [
        entry
        for entry in rounds
        if not R.is_chain_eligible_round(entry["round_alignment"])
    ]


# ---------------------------------------------------------------------------
# D6 / D11: per-round eligibility classification
# ---------------------------------------------------------------------------


def classify_round_items(records, variant):
    """Classify every observed Phase 10 row for one series variant.

    Returns (eligible, rejected) where
      eligible[round_id][item_key] = item payload including the Decimal price
      rejected[round_id] = list of payloads whose status is not ELIGIBLE

    No value is ever repaired, substituted, carried forward or imputed; a row
    that cannot be used is recorded with an explicit status instead.
    """
    eligible = {}
    rejected = {}
    for entry in observed_records(records):
        round_id = text_of(entry, "collection_round_id")
        status, price = R.evaluate_index_eligibility(entry, variant)
        key = R.item_key(entry)
        severity = text_of(entry, "anomaly_severity_max") or R.SEVERITY_NONE
        rank_text = text_of(entry, "basket_rank")
        payload = {
            "item_key": key,
            "item_id": R.item_id(key),
            "route_id": key[0],
            "fare_class": key[1],
            "advance_purchase_window": key[2],
            "travel_date": key[3],
            "collection_round_id": round_id,
            "round_sort_key": text_of(entry, "round_sort_key"),
            "round_alignment": text_of(entry, "round_alignment"),
            "route_series_id": text_of(entry, "route_series_id"),
            "route_coverage_status": text_of(entry, "route_coverage_status"),
            "route_price_state": text_of(entry, "route_price_state"),
            "anomaly_severity_max": severity,
            "basket_rank": int(rank_text) if rank_text.isdigit() else None,
            "consolidation_cell_ids": text_of(entry, "consolidation_cell_ids"),
            "contributing_observation_ids": text_of(
                entry, "contributing_observation_ids"
            ),
            "contributing_observation_count": text_of(
                entry, "contributing_observation_count"
            ),
            "index_eligibility_status": status,
            "price": price,
        }
        if status == R.ELIGIBILITY_ELIGIBLE:
            bucket = eligible.setdefault(round_id, {})
            bucket[key] = payload
        else:
            rejected.setdefault(round_id, []).append(payload)
    return (eligible, rejected)


def severity_counter(payloads):
    counts = {name: 0 for name in R.SEVERITY_LEVELS}
    for payload in payloads:
        severity = payload["anomaly_severity_max"]
        if severity not in counts:
            counts[severity] = 0
        counts[severity] = counts[severity] + 1
    return counts


def count_by(payloads, field):
    counts = {}
    for payload in payloads:
        name = payload[field]
        counts[name] = counts.get(name, 0) + 1
    return counts


# ---------------------------------------------------------------------------
# D3 / D4: one chain link
# ---------------------------------------------------------------------------


def compute_link(previous_round, current_round, eligible, rejected, basket_by_route):
    """Compute one chain link between two adjacent ANCHORED rounds.

    Matched set M_r,t is the intersection of the eligible item keys of the two
    rounds, evaluated within each route. An item present in only one of the
    two rounds is ENTERING or LEAVING and contributes nothing to this link; it
    is never bridged with an imputed or carried-forward price.
    """
    previous_id = previous_round["collection_round_id"]
    current_id = current_round["collection_round_id"]
    previous_items = eligible.get(previous_id, {})
    current_items = eligible.get(current_id, {})

    matched_keys = sorted(set(previous_items) & set(current_items))
    entering_keys = sorted(set(current_items) - set(previous_items))
    leaving_keys = sorted(set(previous_items) - set(current_items))

    matched_by_route = {}
    for key in matched_keys:
        previous_payload = previous_items[key]
        current_payload = current_items[key]
        relative = R.price_relative(
            current_payload["price"], previous_payload["price"]
        )
        matched_by_route.setdefault(key[0], []).append(
            {
                "item_key": key,
                "item_id": current_payload["item_id"],
                "previous": previous_payload,
                "current": current_payload,
                "price_relative": relative,
                "log_price_relative": R.natural_log(relative),
            }
        )

    contributing_weights = {}
    for route_id in sorted(matched_by_route):
        contributing_weights[route_id] = basket_by_route[route_id]["traffic_weight"]
    normalized = R.renormalize_weights(contributing_weights)

    route_components = []
    contributions = []
    for route_id in sorted(matched_by_route):
        matches = sorted(
            matched_by_route[route_id], key=lambda match: match["item_key"]
        )
        relatives = [match["price_relative"] for match in matches]
        route_index = R.elementary_jevons(relatives)
        weight = normalized[route_id]
        route_components.append(
            {
                "route_id": route_id,
                "matches": matches,
                "route_elementary_jevons": route_index,
                "route_log_relative": R.natural_log(route_index),
                "renormalized_weight": weight,
                "traffic_weight": basket_by_route[route_id]["traffic_weight"],
                "weighted_log_contribution": R.weighted_log_contribution(
                    weight, route_index
                ),
            }
        )
        contributions.append((route_id, weight, route_index))

    chain_factor = R.weighted_jevons(contributions)

    current_rejected = rejected.get(current_id, [])
    structural = [
        payload
        for payload in current_rejected
        if R.is_structurally_ineligible(payload["index_eligibility_status"])
    ]
    severity_excluded = [
        payload
        for payload in current_rejected
        if payload["index_eligibility_status"] == R.ELIGIBILITY_EXCLUDED_REVIEW_HIGH
    ]
    unpriced = [
        payload
        for payload in current_rejected
        if payload["route_price_state"] != R.PRICE_STATE_PRICED
    ]

    matched_payloads = [
        current_items[key] for key in matched_keys
    ]

    return {
        "previous_round": previous_round,
        "current_round": current_round,
        "link_id": R.link_id(previous_id, current_id),
        "matched_keys": matched_keys,
        "entering_keys": entering_keys,
        "leaving_keys": leaving_keys,
        "previous_items": previous_items,
        "current_items": current_items,
        "route_components": route_components,
        "contributing_weights": contributing_weights,
        "normalized_weights": normalized,
        "chain_factor": chain_factor,
        "structural_rejected": structural,
        "severity_rejected": severity_excluded,
        "unpriced_rejected": unpriced,
        "severity_counts": severity_counter(matched_payloads),
    }


def coverage_disclosure(contributing_weights, basket):
    """D5: the seven mandatory coverage disclosure values for a round."""
    total_weight = Decimal(0)
    with localcontext() as context:
        context.prec = R.INTERNAL_PRECISION
        for entry in basket:
            total_weight = total_weight + entry["traffic_weight"]
    represented = R.represented_weight(contributing_weights)
    with localcontext() as context:
        context.prec = R.INTERNAL_PRECISION
        missing = +(total_weight - represented)
    routes_represented = len(contributing_weights)
    routes_total = len(basket)
    return {
        "basket_routes_represented": routes_represented,
        "basket_routes_total": routes_total,
        "basket_weight_represented": R.quantize_weight(represented),
        "basket_weight_missing": R.quantize_weight(missing),
        "basket_coverage_pct": R.coverage_percentage(represented, total_weight),
        "effective_weight_sum": (
            Decimal("1.000000") if routes_represented else Decimal("0.000000")
        ),
        "renormalization_applied": (
            routes_represented > 0 and routes_represented < routes_total
        ),
        "coverage_status": R.coverage_status(routes_represented, routes_total),
    }


def build_chain(records, basket, variant):
    """D2 / D3: build the anchored-only chain for one series variant."""
    rounds = collect_rounds(records)
    chain_rounds = anchored_rounds(rounds)
    if not chain_rounds:
        raise R.IndexRuleError(
            "no ANCHORED collection round is available; the anchored-only "
            "chain contract cannot be satisfied"
        )
    eligible, rejected = classify_round_items(records, variant)
    basket_by_route = {entry["route_id"]: entry for entry in basket}

    base_round = chain_rounds[0]
    base_id = base_round["collection_round_id"]
    base_items = eligible.get(base_id, {})
    base_weights = {}
    for key in sorted(base_items):
        route_id = key[0]
        base_weights[route_id] = basket_by_route[route_id]["traffic_weight"]

    base_rejected = rejected.get(base_id, [])
    base_structural = [
        payload
        for payload in base_rejected
        if R.is_structurally_ineligible(payload["index_eligibility_status"])
    ]
    base_severity = [
        payload
        for payload in base_rejected
        if payload["index_eligibility_status"] == R.ELIGIBILITY_EXCLUDED_REVIEW_HIGH
    ]
    base_unpriced = [
        payload
        for payload in base_rejected
        if payload["route_price_state"] != R.PRICE_STATE_PRICED
    ]

    levels = [(base_id, R.INDEX_BASE_LEVEL)]
    steps = [
        {
            "link_sequence": 0,
            "is_base_period": True,
            "round": base_round,
            "previous_round": None,
            "link_id": "",
            "chain_factor": None,
            "level": R.INDEX_BASE_LEVEL,
            "matched_keys": [],
            "entering_keys": [],
            "leaving_keys": [],
            "route_components": [],
            "contributing_weights": base_weights,
            "normalized_weights": R.renormalize_weights(base_weights),
            "eligible_items": base_items,
            "structural_rejected": base_structural,
            "severity_rejected": base_severity,
            "unpriced_rejected": base_unpriced,
            "severity_counts": severity_counter(
                [base_items[key] for key in sorted(base_items)]
            ),
        }
    ]

    previous_round = base_round
    previous_level = R.INDEX_BASE_LEVEL
    for position in range(1, len(chain_rounds)):
        current_round = chain_rounds[position]
        link = compute_link(
            previous_round, current_round, eligible, rejected, basket_by_route
        )
        factor = link["chain_factor"]
        if factor is None:
            # A link with no matched product cannot move the index. The level
            # is held at its previous value and the break is disclosed as a
            # zero matched count; nothing is imputed to manufacture a factor.
            level = previous_level
        else:
            level = R.chain_level(previous_level, factor)
        current_id = current_round["collection_round_id"]
        steps.append(
            {
                "link_sequence": position,
                "is_base_period": False,
                "round": current_round,
                "previous_round": previous_round,
                "link_id": link["link_id"],
                "chain_factor": factor,
                "level": level,
                "matched_keys": link["matched_keys"],
                "entering_keys": link["entering_keys"],
                "leaving_keys": link["leaving_keys"],
                "route_components": link["route_components"],
                "contributing_weights": link["contributing_weights"],
                "normalized_weights": link["normalized_weights"],
                "eligible_items": link["current_items"],
                "previous_items": link["previous_items"],
                "structural_rejected": link["structural_rejected"],
                "severity_rejected": link["severity_rejected"],
                "unpriced_rejected": link["unpriced_rejected"],
                "severity_counts": link["severity_counts"],
            }
        )
        levels.append((current_id, level))
        previous_round = current_round
        previous_level = level

    return {
        "variant": variant,
        "rounds": rounds,
        "chain_rounds": chain_rounds,
        "unaligned_rounds": unaligned_rounds(rounds),
        "base_round": base_round,
        "steps": steps,
        "levels": levels,
        "eligible": eligible,
        "rejected": rejected,
    }


# ---------------------------------------------------------------------------
# Builders (each terminates in an explicit total sort)
# ---------------------------------------------------------------------------


def variant_order(variant):
    return R.SERIES_VARIANTS.index(variant)


def rank_of(basket_by_route, route_id):
    entry = basket_by_route.get(route_id)
    if entry is None:
        return OFF_BASKET_RANK_SENTINEL
    return entry["basket_rank"]


def build_round_index(chains, basket):
    """D3 / D5: the authoritative round-level chained index."""
    rows = []
    for variant in R.SERIES_VARIANTS:
        chain = chains[variant]
        base_round = chain["base_round"]
        previous_level = None
        for step in chain["steps"]:
            current_round = step["round"]
            disclosure = coverage_disclosure(step["contributing_weights"], basket)
            counts = step["severity_counts"]
            matched = len(step["matched_keys"])
            entering = len(step["entering_keys"])
            leaving = len(step["leaving_keys"])
            level = step["level"]
            if previous_level is None:
                change_text = ""
            else:
                change_text = format_decimal(
                    R.percent_change(level, previous_level)
                )
            rows.append(
                {
                    "_sort": (variant_order(variant), step["link_sequence"]),
                    "series_variant": variant,
                    "index_series_id": R.INDEX_SERIES_ID[variant],
                    "index_inclusion_rule_id": R.INDEX_INCLUSION_RULE_ID[variant],
                    "collection_round_id": current_round["collection_round_id"],
                    "round_sort_key": current_round["round_sort_key"],
                    "round_alignment": current_round["round_alignment"],
                    "link_sequence": step["link_sequence"],
                    "link_id": step["link_id"],
                    "is_base_period": format_bool(step["is_base_period"]),
                    "base_round_id": base_round["collection_round_id"],
                    "base_round_sort_key": base_round["round_sort_key"],
                    "base_period_label": base_round["round_sort_key"],
                    "index_base_level": format_decimal(R.INDEX_BASE_LEVEL_PUBLISHED),
                    "prev_round_id": (
                        step["previous_round"]["collection_round_id"]
                        if step["previous_round"]
                        else ""
                    ),
                    "chain_factor": format_decimal(
                        R.quantize_factor(step["chain_factor"])
                    ),
                    "index_level": format_decimal(R.quantize_level(level)),
                    "index_change_pct_vs_prev_round": change_text,
                    "matched_product_count": matched,
                    "entering_product_count": entering,
                    "leaving_product_count": leaving,
                    "missing_product_count": entering + leaving,
                    "excluded_product_count": len(step["structural_rejected"]),
                    "anomaly_excluded_product_count": len(step["severity_rejected"]),
                    "unpriced_product_count": len(step["unpriced_rejected"]),
                    "eligible_product_count": len(step["eligible_items"]),
                    "basket_routes_represented": disclosure[
                        "basket_routes_represented"
                    ],
                    "basket_routes_total": disclosure["basket_routes_total"],
                    "basket_weight_represented": format_decimal(
                        disclosure["basket_weight_represented"]
                    ),
                    "basket_weight_missing": format_decimal(
                        disclosure["basket_weight_missing"]
                    ),
                    "basket_coverage_pct": format_decimal(
                        disclosure["basket_coverage_pct"]
                    ),
                    "effective_weight_sum": format_decimal(
                        disclosure["effective_weight_sum"]
                    ),
                    "renormalization_applied": format_bool(
                        disclosure["renormalization_applied"]
                    ),
                    "coverage_status": disclosure["coverage_status"],
                    "none_count": counts.get(R.SEVERITY_NONE, 0),
                    "info_count": counts.get(R.SEVERITY_INFO, 0),
                    "review_count": counts.get(R.SEVERITY_REVIEW, 0),
                    "high_count": counts.get(R.SEVERITY_HIGH, 0),
                    "aggregation_statistic": R.AGGREGATION_STATISTIC,
                    "elementary_aggregation_statistic": (
                        R.ELEMENTARY_AGGREGATION_STATISTIC
                    ),
                    "weight_basis": R.WEIGHT_BASIS,
                    "weight_application": R.WEIGHT_APPLICATION,
                    "phase10_schema_version": R.PHASE10_SCHEMA_VERSION_EXPECTED,
                    "phase11_schema_version": R.PHASE11_SCHEMA_VERSION,
                }
            )
            previous_level = level
    rows.sort(key=lambda record: record["_sort"])
    for record in rows:
        del record["_sort"]
    return rows


def build_route_components(chains, basket):
    """Per-route elementary Jevons and renormalized weight for every link."""
    basket_by_route = {entry["route_id"]: entry for entry in basket}
    rows = []
    for variant in R.SERIES_VARIANTS:
        chain = chains[variant]
        for step in chain["steps"]:
            if step["link_sequence"] == 0:
                continue
            current_round = step["round"]
            previous_round = step["previous_round"]
            components = {
                component["route_id"]: component
                for component in step["route_components"]
            }
            previous_items = step.get("previous_items", {})
            current_items = step["eligible_items"]
            route_ids = set()
            for key in previous_items:
                route_ids.add(key[0])
            for key in current_items:
                route_ids.add(key[0])
            for route_id in sorted(route_ids):
                component = components.get(route_id)
                matches = component["matches"] if component else []
                matched_payloads = [match["current"] for match in matches]
                counts = severity_counter(matched_payloads)
                entering = len(
                    [
                        key
                        for key in step["entering_keys"]
                        if key[0] == route_id
                    ]
                )
                leaving = len(
                    [key for key in step["leaving_keys"] if key[0] == route_id]
                )
                rows.append(
                    {
                        "_sort": (
                            variant_order(variant),
                            step["link_sequence"],
                            rank_of(basket_by_route, route_id),
                            route_id,
                        ),
                        "series_variant": variant,
                        "index_series_id": R.INDEX_SERIES_ID[variant],
                        "link_sequence": step["link_sequence"],
                        "link_id": step["link_id"],
                        "prev_round_id": previous_round["collection_round_id"],
                        "collection_round_id": current_round[
                            "collection_round_id"
                        ],
                        "round_sort_key": current_round["round_sort_key"],
                        "route_id": route_id,
                        "basket_rank": basket_by_route[route_id]["basket_rank"],
                        "route_coverage_status": R.COVERAGE_CONTRIBUTED
                        if component
                        else R.COVERAGE_OBSERVED_NOT_MATCHED,
                        "traffic_weight": format_decimal(
                            basket_by_route[route_id]["traffic_weight"]
                        ),
                        "renormalized_weight": format_decimal(
                            R.quantize_weight(component["renormalized_weight"])
                            if component
                            else None
                        ),
                        "contributed_to_index": format_bool(component is not None),
                        "matched_product_count": len(matches),
                        "route_elementary_jevons": format_decimal(
                            R.quantize_factor(component["route_elementary_jevons"])
                            if component
                            else None
                        ),
                        "route_log_relative": format_decimal(
                            R.quantize_log(component["route_log_relative"])
                            if component
                            else None
                        ),
                        "weighted_log_contribution": format_decimal(
                            R.quantize_log(component["weighted_log_contribution"])
                            if component
                            else None
                        ),
                        "entering_product_count": entering,
                        "leaving_product_count": leaving,
                        "eligible_product_count_prev": len(
                            [key for key in previous_items if key[0] == route_id]
                        ),
                        "eligible_product_count_curr": len(
                            [key for key in current_items if key[0] == route_id]
                        ),
                        "none_count": counts.get(R.SEVERITY_NONE, 0),
                        "info_count": counts.get(R.SEVERITY_INFO, 0),
                        "review_count": counts.get(R.SEVERITY_REVIEW, 0),
                        "high_count": counts.get(R.SEVERITY_HIGH, 0),
                        "fare_class_matched_counts": pack_counts(
                            count_by(matched_payloads, "fare_class")
                        ),
                        "advance_purchase_window_matched_counts": pack_counts(
                            count_by(
                                matched_payloads, "advance_purchase_window"
                            )
                        ),
                        "elementary_aggregation_statistic": (
                            R.ELEMENTARY_AGGREGATION_STATISTIC
                        ),
                        "within_route_weighting": R.WITHIN_ROUTE_WEIGHTING,
                        "phase11_schema_version": R.PHASE11_SCHEMA_VERSION,
                    }
                )
    rows.sort(key=lambda record: record["_sort"])
    for record in rows:
        del record["_sort"]
    return rows


def build_item_relatives(chains, basket):
    """Every item-level relative and every unmatched or excluded item."""
    basket_by_route = {entry["route_id"]: entry for entry in basket}
    rows = []

    def emit(variant, step, payload_current, payload_previous, status, reason):
        current_round = step["round"]
        previous_round = step["previous_round"]
        anchor = payload_current if payload_current else payload_previous
        route_id = anchor["route_id"]
        relative = None
        log_relative = None
        if payload_current and payload_previous and status == R.ITEM_STATUS_MATCHED:
            relative = R.price_relative(
                payload_current["price"], payload_previous["price"]
            )
            log_relative = R.natural_log(relative)
        rows.append(
            {
                "_sort": (
                    variant_order(variant),
                    step["link_sequence"],
                    rank_of(basket_by_route, route_id),
                    route_id,
                    anchor["fare_class"],
                    anchor["advance_purchase_window"],
                    anchor["travel_date"],
                    status,
                    anchor["item_id"],
                ),
                "series_variant": variant,
                "index_series_id": R.INDEX_SERIES_ID[variant],
                "link_sequence": step["link_sequence"],
                "link_id": step["link_id"],
                "prev_round_id": previous_round["collection_round_id"],
                "prev_round_sort_key": previous_round["round_sort_key"],
                "collection_round_id": current_round["collection_round_id"],
                "round_sort_key": current_round["round_sort_key"],
                "item_id": anchor["item_id"],
                "route_id": route_id,
                "basket_rank": basket_by_route[route_id]["basket_rank"],
                "fare_class": anchor["fare_class"],
                "advance_purchase_window": anchor["advance_purchase_window"],
                "travel_date": anchor["travel_date"],
                "prev_route_series_id": (
                    payload_previous["route_series_id"] if payload_previous else ""
                ),
                "curr_route_series_id": (
                    payload_current["route_series_id"] if payload_current else ""
                ),
                "prev_fare": format_decimal(
                    payload_previous["price"] if payload_previous else None
                ),
                "curr_fare": format_decimal(
                    payload_current["price"] if payload_current else None
                ),
                "price_relative": format_decimal(R.quantize_relative(relative)),
                "log_price_relative": format_decimal(R.quantize_log(log_relative)),
                "item_status": status,
                "index_eligibility_status": anchor["index_eligibility_status"],
                "index_inclusion_rule_id": R.INDEX_INCLUSION_RULE_ID[variant],
                "anomaly_severity_max": anchor["anomaly_severity_max"],
                "exclusion_reason": reason,
                "phase11_schema_version": R.PHASE11_SCHEMA_VERSION,
            }
        )

    for variant in R.SERIES_VARIANTS:
        chain = chains[variant]
        for step in chain["steps"]:
            if step["link_sequence"] == 0:
                continue
            previous_items = step.get("previous_items", {})
            current_items = step["eligible_items"]
            for key in step["matched_keys"]:
                emit(
                    variant,
                    step,
                    current_items[key],
                    previous_items[key],
                    R.ITEM_STATUS_MATCHED,
                    "",
                )
            for key in step["entering_keys"]:
                emit(
                    variant,
                    step,
                    current_items[key],
                    None,
                    R.ITEM_STATUS_ENTERING,
                    "NO_MATCHED_PRICE_IN_PREVIOUS_ROUND",
                )
            for key in step["leaving_keys"]:
                emit(
                    variant,
                    step,
                    None,
                    previous_items[key],
                    R.ITEM_STATUS_LEAVING,
                    "NO_MATCHED_PRICE_IN_CURRENT_ROUND",
                )
            for payload in step["structural_rejected"]:
                emit(
                    variant,
                    step,
                    payload,
                    None,
                    R.ITEM_STATUS_UNPRICED,
                    payload["index_eligibility_status"],
                )
            for payload in step["severity_rejected"]:
                emit(
                    variant,
                    step,
                    payload,
                    None,
                    R.ITEM_STATUS_EXCLUDED_ANOMALY,
                    "SEVERITY_EXCLUDED_BY_"
                    + R.INDEX_INCLUSION_RULE_ID[variant],
                )
    rows.sort(key=lambda record: record["_sort"])
    for record in rows:
        del record["_sort"]
    return rows


def build_period_index(chains, basket, round_index_rows):
    """D7: daily, weekly and monthly series DERIVED from the round chain.

    The primary period value is the period-end chain level, which is a real
    level on the authoritative chain. period_average_level is the arithmetic
    mean of the round levels inside the period and is published as a
    diagnostic only, explicitly flagged as not chain consistent.
    """
    disclosure_by_round = {}
    for record in round_index_rows:
        disclosure_by_round[
            (record["series_variant"], record["collection_round_id"])
        ] = record
    rows = []
    for variant in R.SERIES_VARIANTS:
        chain = chains[variant]
        for grain in R.PERIOD_GRAINS:
            buckets = {}
            for step in chain["steps"]:
                identifier = R.period_id(step["round"]["round_sort_key"], grain)
                buckets.setdefault(identifier, []).append(step)
            ordered_ids = sorted(
                buckets,
                key=lambda identifier: min(
                    entry["round"]["round_sort_key"] for entry in buckets[identifier]
                ),
            )
            previous_end_level = None
            for identifier in ordered_ids:
                steps = sorted(
                    buckets[identifier],
                    key=lambda entry: (
                        entry["round"]["round_sort_key"],
                        entry["round"]["collection_round_id"],
                    ),
                )
                end_level = steps[-1]["level"]
                levels = [entry["level"] for entry in steps]
                matched_total = 0
                represented = []
                coverage_values = []
                statuses = []
                for entry in steps:
                    record = disclosure_by_round[
                        (variant, entry["round"]["collection_round_id"])
                    ]
                    matched_total = matched_total + int(
                        record["matched_product_count"]
                    )
                    represented.append(int(record["basket_routes_represented"]))
                    coverage_values.append(
                        Decimal(record["basket_coverage_pct"])
                    )
                    statuses.append(record["coverage_status"])
                expected = R.expected_round_count(grain, identifier)
                if previous_end_level is None:
                    change_text = ""
                else:
                    change_text = format_decimal(
                        R.percent_change(end_level, previous_end_level)
                    )
                if R.COVERAGE_STATUS_PARTIAL in statuses:
                    period_coverage_status = R.COVERAGE_STATUS_PARTIAL
                else:
                    period_coverage_status = statuses[0]
                rows.append(
                    {
                        "_sort": (
                            variant_order(variant),
                            R.PERIOD_GRAINS.index(grain),
                            identifier,
                        ),
                        "series_variant": variant,
                        "index_series_id": R.INDEX_SERIES_ID[variant],
                        "period_grain": grain,
                        "period_id": identifier,
                        "period_start_round_id": steps[0]["round"][
                            "collection_round_id"
                        ],
                        "period_end_round_id": steps[-1]["round"][
                            "collection_round_id"
                        ],
                        "round_count": len(steps),
                        "expected_round_count": expected,
                        "period_is_partial": format_bool(len(steps) < expected),
                        "period_end_index_level": format_decimal(
                            R.quantize_level(end_level)
                        ),
                        "period_average_level": format_decimal(
                            R.quantize_level(R.mean_level(levels))
                        ),
                        "period_primary_measure": R.PERIOD_PRIMARY_MEASURE,
                        "period_secondary_measure": R.PERIOD_SECONDARY_MEASURE,
                        "period_average_is_chain_consistent": format_bool(
                            R.PERIOD_AVERAGE_IS_CHAIN_CONSISTENT
                        ),
                        "index_change_pct_vs_prev_period": change_text,
                        "matched_product_count_total": matched_total,
                        "basket_routes_represented_min": min(represented),
                        "basket_routes_represented_max": max(represented),
                        "basket_coverage_pct_min": format_decimal(
                            min(coverage_values)
                        ),
                        "basket_coverage_pct_max": format_decimal(
                            max(coverage_values)
                        ),
                        "coverage_status": period_coverage_status,
                        "derivation_rule": "DERIVED_FROM_ROUND_LEVEL_CHAIN",
                        "phase11_schema_version": R.PHASE11_SCHEMA_VERSION,
                    }
                )
                previous_end_level = end_level
    rows.sort(key=lambda record: record["_sort"])
    for record in rows:
        del record["_sort"]
    return rows


def build_index_coverage(chains, basket, phase10_coverage):
    """D5: full 15-route disclosure for every published round.

    Every locked basket route appears on every round, including the 13 routes
    with no observation at all. A missing route is disclosed, never dropped
    from the table and never silently absorbed into the contributing weights.
    """
    basket_by_route = {entry["route_id"]: entry for entry in basket}
    rows = []
    for variant in R.SERIES_VARIANTS:
        chain = chains[variant]
        for step in chain["steps"]:
            current_round = step["round"]
            disclosure = coverage_disclosure(step["contributing_weights"], basket)
            components = {
                component["route_id"]: component
                for component in step["route_components"]
            }
            eligible_by_route = count_by(
                [
                    step["eligible_items"][key]
                    for key in sorted(step["eligible_items"])
                ],
                "route_id",
            )
            for entry in basket:
                route_id = entry["route_id"]
                component = components.get(route_id)
                contributed = route_id in step["normalized_weights"]
                matched_count = len(component["matches"]) if component else 0
                eligible_count = eligible_by_route.get(route_id, 0)
                if phase10_coverage.get(route_id) == R.COVERAGE_NOT_OBSERVED:
                    contribution_status = R.COVERAGE_NOT_OBSERVED
                elif contributed:
                    contribution_status = R.COVERAGE_CONTRIBUTED
                else:
                    contribution_status = R.COVERAGE_OBSERVED_NOT_MATCHED
                weight = entry["traffic_weight"]
                rows.append(
                    {
                        "_sort": (
                            variant_order(variant),
                            step["link_sequence"],
                            entry["basket_rank"],
                        ),
                        "series_variant": variant,
                        "index_series_id": R.INDEX_SERIES_ID[variant],
                        "collection_round_id": current_round[
                            "collection_round_id"
                        ],
                        "round_sort_key": current_round["round_sort_key"],
                        "link_sequence": step["link_sequence"],
                        "is_base_period": format_bool(step["is_base_period"]),
                        "route_id": route_id,
                        "basket_rank": entry["basket_rank"],
                        "traffic_weight": format_decimal(weight),
                        "route_coverage_status": phase10_coverage.get(
                            route_id, ""
                        ),
                        "eligible_product_count": eligible_count,
                        "matched_product_count": matched_count,
                        "contributed_to_index": format_bool(contributed),
                        "coverage_contribution_status": contribution_status,
                        "renormalized_weight": format_decimal(
                            R.quantize_weight(
                                step["normalized_weights"][route_id]
                            )
                            if contributed
                            else None
                        ),
                        "weight_represented": format_decimal(
                            weight if contributed else None
                        ),
                        "weight_excluded": format_decimal(
                            None if contributed else weight
                        ),
                        "basket_routes_total": disclosure["basket_routes_total"],
                        "coverage_status": disclosure["coverage_status"],
                        "phase11_schema_version": R.PHASE11_SCHEMA_VERSION,
                    }
                )
    rows.sort(key=lambda record: record["_sort"])
    for record in rows:
        del record["_sort"]
    return rows


def build_index_lineage(chains, basket):
    """N: every matched relative traced back to Phase 10 and Phase 9 ids."""
    basket_by_route = {entry["route_id"]: entry for entry in basket}
    rows = []
    for variant in R.SERIES_VARIANTS:
        chain = chains[variant]
        for step in chain["steps"]:
            if step["link_sequence"] == 0:
                continue
            for component in step["route_components"]:
                route_id = component["route_id"]
                matches = component["matches"]
                weight = component["renormalized_weight"]
                with localcontext() as context:
                    context.prec = R.INTERNAL_PRECISION
                    contribution = +(weight / Decimal(len(matches)))
                for match in matches:
                    previous_payload = match["previous"]
                    current_payload = match["current"]
                    rows.append(
                        {
                            "_sort": (
                                variant_order(variant),
                                step["link_sequence"],
                                basket_by_route[route_id]["basket_rank"],
                                route_id,
                                current_payload["fare_class"],
                                current_payload["advance_purchase_window"],
                                current_payload["travel_date"],
                            ),
                            "series_variant": variant,
                            "index_series_id": R.INDEX_SERIES_ID[variant],
                            "link_sequence": step["link_sequence"],
                            "link_id": step["link_id"],
                            "route_id": route_id,
                            "basket_rank": basket_by_route[route_id][
                                "basket_rank"
                            ],
                            "fare_class": current_payload["fare_class"],
                            "advance_purchase_window": current_payload[
                                "advance_purchase_window"
                            ],
                            "travel_date": current_payload["travel_date"],
                            "item_id": current_payload["item_id"],
                            "prev_round_id": previous_payload[
                                "collection_round_id"
                            ],
                            "curr_round_id": current_payload[
                                "collection_round_id"
                            ],
                            "prev_route_series_id": previous_payload[
                                "route_series_id"
                            ],
                            "curr_route_series_id": current_payload[
                                "route_series_id"
                            ],
                            "prev_fare": format_decimal(
                                previous_payload["price"]
                            ),
                            "curr_fare": format_decimal(current_payload["price"]),
                            "price_relative": format_decimal(
                                R.quantize_relative(match["price_relative"])
                            ),
                            "log_price_relative": format_decimal(
                                R.quantize_log(match["log_price_relative"])
                            ),
                            "renormalized_weight": format_decimal(
                                R.quantize_weight(weight)
                            ),
                            "matched_product_count": len(matches),
                            "contribution_weight": format_decimal(
                                R.quantize_weight(contribution)
                            ),
                            "prev_consolidation_cell_ids": pack_list(
                                packed_list(
                                    previous_payload["consolidation_cell_ids"]
                                )
                            ),
                            "curr_consolidation_cell_ids": pack_list(
                                packed_list(
                                    current_payload["consolidation_cell_ids"]
                                )
                            ),
                            "prev_contributing_observation_ids": pack_list(
                                packed_list(
                                    previous_payload[
                                        "contributing_observation_ids"
                                    ]
                                )
                            ),
                            "curr_contributing_observation_ids": pack_list(
                                packed_list(
                                    current_payload[
                                        "contributing_observation_ids"
                                    ]
                                )
                            ),
                            "prev_contributing_observation_count": (
                                previous_payload[
                                    "contributing_observation_count"
                                ]
                            ),
                            "curr_contributing_observation_count": (
                                current_payload[
                                    "contributing_observation_count"
                                ]
                            ),
                            "anomaly_severity_max": current_payload[
                                "anomaly_severity_max"
                            ],
                            "phase11_schema_version": R.PHASE11_SCHEMA_VERSION,
                        }
                    )
    rows.sort(key=lambda record: record["_sort"])
    for record in rows:
        del record["_sort"]
    return rows


def build_unaligned_diagnostics(chains, basket):
    """D2: unaligned rounds are published here and never chained.

    The matched count against the nearest anchored round is reported so the
    cost of the anchored-only rule is measurable rather than assumed.
    """
    chain = chains[R.SERIES_VARIANT_PRIMARY]
    eligible = chain["eligible"]
    anchored = chain["chain_rounds"]
    rows = []
    for entry in chain["unaligned_rounds"]:
        round_id = entry["collection_round_id"]
        items = eligible.get(round_id, {})
        keys = sorted(items)
        route_ids = sorted({key[0] for key in keys})
        moment = parse_round_moment(entry["round_sort_key"])
        nearest = None
        nearest_distance = None
        for candidate in anchored:
            candidate_moment = parse_round_moment(candidate["round_sort_key"])
            distance = abs(
                int((candidate_moment - moment).total_seconds()) // 60
            )
            if nearest_distance is None or distance < nearest_distance:
                nearest = candidate
                nearest_distance = distance
        nearest_items = eligible.get(nearest["collection_round_id"], {})
        matched = len(set(keys) & set(nearest_items))
        rows.append(
            {
                "_sort": (entry["round_sort_key"], round_id),
                "collection_round_id": round_id,
                "round_sort_key": entry["round_sort_key"],
                "round_alignment": entry["round_alignment"],
                "diagnostic_basis": R.UNALIGNED_DIAGNOSTIC_BASIS,
                "chain_eligible": format_bool(False),
                "excluded_from_chain_reason": R.UNALIGNED_EXCLUSION_REASON,
                "eligible_product_count": len(keys),
                "route_count": len(route_ids),
                "route_ids": pack_list(route_ids),
                "nearest_anchored_round_id": nearest["collection_round_id"],
                "nearest_anchored_round_sort_key": nearest["round_sort_key"],
                "minutes_to_nearest_anchored_round": nearest_distance,
                "matched_product_count_vs_nearest_anchored": matched,
                "phase11_schema_version": R.PHASE11_SCHEMA_VERSION,
            }
        )
    rows.sort(key=lambda record: record["_sort"])
    for record in rows:
        del record["_sort"]
    return rows


# ---------------------------------------------------------------------------
# D8: rebasing helper (operates on unrounded internal levels)
# ---------------------------------------------------------------------------


def rebase_round_index(result, variant, new_base_round_id):
    """Rebase one variant's chain to another anchored round.

    Returns an ordered list of (collection_round_id, published_level). The
    computation starts from the unrounded internal levels held on the chain,
    so relatives between rounds are preserved exactly.
    """
    chain = result["chains"][variant]
    rebased = R.rebase_levels(chain["levels"], new_base_round_id)
    return [(round_id, R.quantize_level(level)) for round_id, level in rebased]


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def aggregate(grain_a_records, basket, phase10_coverage):
    """Build every Phase 11 table in memory. No IO, fully deterministic."""
    for columns in ALL_OUTPUT_COLUMN_SETS:
        R.assert_no_forbidden_fields(columns)
    chains = {}
    for variant in R.SERIES_VARIANTS:
        chains[variant] = build_chain(grain_a_records, basket, variant)
    round_index = build_round_index(chains, basket)
    return {
        "chains": chains,
        "round_index": round_index,
        "route_components": build_route_components(chains, basket),
        "item_relatives": build_item_relatives(chains, basket),
        "period_index": build_period_index(chains, basket, round_index),
        "index_coverage": build_index_coverage(chains, basket, phase10_coverage),
        "index_lineage": build_index_lineage(chains, basket),
        "unaligned_diagnostics": build_unaligned_diagnostics(chains, basket),
    }


def run_index_engine(
    grain_a_path,
    basket_path,
    phase10_coverage_path,
    round_index_path,
    route_components_path,
    item_relatives_path,
    period_index_path,
    index_coverage_path,
    index_lineage_path,
    unaligned_diagnostics_path,
):
    """Read Phase 10 read-only and write the seven Phase 11 outputs."""
    basket = load_basket(basket_path)
    phase10_coverage = load_phase10_coverage(phase10_coverage_path, basket)
    grain_a_records = load_grain_a(grain_a_path, basket)
    result = aggregate(grain_a_records, basket, phase10_coverage)
    written = [
        write_csv(round_index_path, ROUND_INDEX_COLUMNS, result["round_index"]),
        write_csv(
            route_components_path,
            ROUTE_COMPONENT_COLUMNS,
            result["route_components"],
        ),
        write_csv(
            item_relatives_path, ITEM_RELATIVE_COLUMNS, result["item_relatives"]
        ),
        write_csv(period_index_path, PERIOD_INDEX_COLUMNS, result["period_index"]),
        write_csv(
            index_coverage_path, INDEX_COVERAGE_COLUMNS, result["index_coverage"]
        ),
        write_csv(
            index_lineage_path, INDEX_LINEAGE_COLUMNS, result["index_lineage"]
        ),
        write_csv(
            unaligned_diagnostics_path,
            UNALIGNED_DIAGNOSTIC_COLUMNS,
            result["unaligned_diagnostics"],
        ),
    ]
    result["written_paths"] = written
    return result
