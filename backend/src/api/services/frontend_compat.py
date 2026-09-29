"""Compatibility data views for the supplied Vayu Index frontend."""

from collections import defaultdict
import os
import re

from ..errors import APIError


def canonical_route_id(route: str) -> str:
    """Normalize either direction of an airport pair to the basket route ID."""
    value = route.strip().upper()
    if not re.fullmatch(r"[A-Z]{3}-[A-Z]{3}", value):
        raise APIError(422, "INVALID_PARAMETER", "Route must use AAA-BBB syntax.")
    origin, destination = value.split("-")
    return "-".join(sorted((origin, destination)))


def route_index(s, route: str, variant: str = "PRIMARY"):
    route_id = canonical_route_id(route)
    rows = [
        dict(row)
        for row in s.tables["route_components"]
        if row["route_id"] == route_id and row["series_variant"] == variant
    ]
    rows.sort(key=lambda row: int(row["link_sequence"]))
    if not rows:
        raise APIError(404, "ROUTE_INDEX_NOT_FOUND", "No route index history is available.")

    base_round_id = rows[0]["prev_round_id"]
    base_round = next(
        (
            row
            for row in s.tables["round_index"]
            if row["series_variant"] == variant
            and row["collection_round_id"] == base_round_id
        ),
        None,
    )
    level = 100.0
    history = [
        {
            "route": route.upper(),
            "route_id": route_id,
            "collection_round_id": base_round_id,
            "timestamp": base_round["round_sort_key"] if base_round else None,
            "index": "100.000000",
            "change_pct_vs_previous_round": None,
        }
    ]
    for row in rows:
        try:
            relative = float(row["route_elementary_jevons"])
        except (TypeError, ValueError):
            continue
        if relative <= 0:
            continue
        level *= relative
        history.append(
            {
                "route": route.upper(),
                "route_id": route_id,
                "collection_round_id": row["collection_round_id"],
                "timestamp": row["round_sort_key"],
                "index": f"{level:.6f}",
                "change_pct_vs_previous_round": f"{(relative - 1) * 100:.4f}",
                "route_elementary_jevons": row["route_elementary_jevons"],
            }
        )

    latest = history[-1]
    return {
        "route": route.upper(),
        "route_id": route_id,
        "index": latest["index"],
        "base_period": history[0]["timestamp"],
        "status": "available",
        "history": history,
    }


def fare_rows(s, route=None, fare_class=None, apw=None, start=None, end=None):
    route_id = canonical_route_id(route) if route else None
    rows = [
        dict(row)
        for row in s.tables["route_history"]
        if (not route_id or row["route_id"] == route_id)
        and (not fare_class or row["fare_class"] == fare_class)
        and (not apw or row["advance_purchase_window"] == apw)
        and (not start or row["round_sort_key"] >= start)
        and (not end or row["round_sort_key"] <= end)
    ]
    rows.sort(key=lambda row: (row["round_sort_key"], row["route_id"], row["fare_class"]))
    return rows


def lead_time_rows(s, route=None, apw=None):
    route_id = canonical_route_id(route) if route else None
    grouped = defaultdict(list)
    for row in s.tables["route_history"]:
        if route_id and row["route_id"] != route_id:
            continue
        if apw and row["advance_purchase_window"] != apw:
            continue
        try:
            fare = float(row["route_fare_median"])
        except (TypeError, ValueError):
            continue
        grouped[(row["route_id"], row["advance_purchase_window"])].append(fare)

    def window_order(window):
        match = re.match(r"T(\d+)", window)
        return int(match.group(1)) if match else 10_000

    result = []
    for (route_key, window), fares in grouped.items():
        result.append(
            {
                "route_id": route_key,
                "advance_purchase_window": window,
                "average_fare": f"{sum(fares) / len(fares):.2f}",
                "observation_count": len(fares),
                "currency": "INR",
            }
        )
    return sorted(result, key=lambda row: (row["route_id"], window_order(row["advance_purchase_window"])))


def data_quality_summary(s, variant="PRIMARY"):
    anomalies = s.tables["anomalies"]
    severity_counts = defaultdict(int)
    evaluation_counts = defaultdict(int)
    rule_counts = defaultdict(int)
    review_count = 0
    for row in anomalies:
        severity_counts[row["severity"]] += 1
        evaluation_counts[row["evaluation_status"]] += 1
        rule_counts[row["rule_id"]] += 1
        review_count += row["recommended_review"] == "True"

    index = next(
        (row for row in reversed(s.tables["round_index"]) if row["series_variant"] == variant),
        None,
    )
    return {
        "quality_status": "PROTOTYPE_DIAGNOSTICS",
        "data_status": "SYNTHETIC_PROTOTYPE",
        "is_real_market_collection": False,
        "validation_status": "NOT_A_LIVE_VALIDATION_FEED",
        "anomaly_record_count": len(anomalies),
        "recommended_review_count": review_count,
        "severity_counts": dict(sorted(severity_counts.items())),
        "evaluation_status_counts": dict(sorted(evaluation_counts.items())),
        "rule_counts": dict(sorted(rule_counts.items())),
        "latest_index_coverage": (
            {
                "collection_round_id": index["collection_round_id"],
                "routes_represented": int(index["basket_routes_represented"]),
                "routes_total": int(index["basket_routes_total"]),
                "coverage_pct": index["basket_coverage_pct"],
                "coverage_status": index["coverage_status"],
            }
            if index
            else None
        ),
        "live_collection_status": "LIVE_COLLECTION_NOT_STARTED",
    }


def frontend_data(s, request=None):
    """Return the joined, prototype-only data needed by the supplied pages."""
    from .core import backtest, collection, history, latest, routes
    from .cpi_comparison import compare_cpi
    from ...collection.serpapi_live import readiness as serpapi_readiness
    from ...collection.ignav_live import readiness as ignav_readiness
    from .route_catalog import is_demo_mode, get_lead_time_demo_rows

    demo_active = is_demo_mode(request)
    index_rows = sorted(history(s), key=lambda row: row["round_sort_key"])
    route_history = [dict(row) for row in s.tables["route_history"]]
    by_route = defaultdict(list)
    by_round = defaultdict(list)
    for row in route_history:
        by_route[row["route_id"]].append(row)
        by_round[row["round_sort_key"]].append(row)

    def fare_average(rows):
        fares = []
        for row in rows:
            try:
                fares.append(float(row["route_fare_median"]))
            except (TypeError, ValueError):
                continue
        return sum(fares) / len(fares) if fares else None

    # Keep the complete published basket in the overview, including routes
    # that do not yet have any fare observation.
    basket_routes = routes(s, request=request)
    overview_routes = []
    anomaly_routes = []
    severity_rank = {"NONE": 0, "INFO": 1, "REVIEW": 2, "HIGH": 3}
    for basket_route in basket_routes:
        route_id = basket_route["route_id"]
        rows = by_route.get(route_id, [])
        rounds = sorted({row["round_sort_key"] for row in rows})
        current_rows = [row for row in rows if rounds and row["round_sort_key"] == rounds[-1]]
        previous_rows = [row for row in rows if len(rounds) > 1 and row["round_sort_key"] == rounds[-2]]
        average = fare_average(current_rows)
        if average is None:
            if basket_route.get("total_fare") is not None:
                try:
                    average = float(basket_route["total_fare"])
                except (TypeError, ValueError):
                    average = None
            elif basket_route.get("route_fare_median") is not None:
                try:
                    average = float(basket_route["route_fare_median"])
                except (TypeError, ValueError):
                    average = None
        previous = fare_average(previous_rows)
        change_pct = ((average / previous) - 1) * 100 if average is not None and previous else None
        if change_pct is None and basket_route.get("change_pct") is not None:
            try:
                change_pct = float(basket_route["change_pct"])
            except (TypeError, ValueError):
                change_pct = None
        round_key = (
            rounds[-1]
            if rounds
            else (basket_route.get("search_date") or basket_route.get("retrieval_timestamp") or "2026-09-28")
        )
        price_src = (
            basket_route.get("source")
            or ("PROTOTYPE_SNAPSHOT" if average is not None else "NO_OBSERVATION")
        )
        overview_routes.append(
            {
                "route_id": route_id,
                "origin": basket_route["origin"],
                "destination": basket_route["destination"],
                "basket_rank": basket_route["basket_rank"],
                "traffic_weight": basket_route["traffic_weight"],
                "coverage_status": basket_route["coverage_status"],
                "average_fare": f"{average:.2f}" if average is not None else None,
                "price_source": price_src,
                "change_pct": f"{change_pct:.2f}" if change_pct is not None else None,
                "round_sort_key": round_key,
            }
        )

        severity = max(
            (row["anomaly_severity_max"] for row in rows),
            key=lambda value: severity_rank.get(value, 0),
            default="NONE",
        )
        if severity != "NONE" or any(row["recommended_review"] == "True" for row in rows):
            fares = []
            for row in current_rows:
                try:
                    fares.extend((float(row["route_fare_min"]), float(row["route_fare_max"])))
                except (TypeError, ValueError):
                    pass
            anomaly_routes.append(
                {
                    "route_id": route_id,
                    "average_fare": f"{average:.2f}" if average is not None else None,
                    "observed_min": f"{min(fares):.2f}" if fares else None,
                    "observed_max": f"{max(fares):.2f}" if fares else None,
                    "change_pct": f"{change_pct:.2f}" if change_pct is not None else None,
                    "severity": severity,
                    "review_count": sum(int(row["recommended_review_cell_count"]) for row in rows),
                    "round_sort_key": rounds[-1],
                }
            )

    anomalies = s.tables["anomalies"]
    anomaly_trend = defaultdict(int)
    for row in anomalies:
        if row["severity"] != "NONE":
            anomaly_trend[row["round_sort_key"][:10]] += 1

    validations = s.tables["validated_observations"]
    validation_status_counts = defaultdict(int)
    validation_error_counts = defaultdict(int)
    invalid_records = 0
    records_with_missing = 0
    for row in validations:
        validation_status_counts[row["validation_status"]] += 1
        errors = [code for code in row["validation_errors"].split(";") if code]
        if errors:
            invalid_records += 1
        if any(code.startswith("MISSING_") for code in errors):
            records_with_missing += 1
        for code in errors:
            validation_error_counts[code] += 1
    total_records = len(validations)
    valid_records = sum(row["is_valid"] == "True" for row in validations)
    quality_by_day = defaultdict(lambda: {"record_count": 0, "valid_record_count": 0})
    for row in validations:
        day = str(row.get("collection_timestamp") or "")[:10]
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
            continue
        quality_by_day[day]["record_count"] += 1
        quality_by_day[day]["valid_record_count"] += row["is_valid"] == "True"
    quality_trend = [
        {
            "date": day,
            "record_count": values["record_count"],
            "valid_record_count": values["valid_record_count"],
            "quality_pct": round(values["valid_record_count"] / values["record_count"] * 100, 4),
        }
        for day, values in sorted(quality_by_day.items())[-30:]
    ]

    collection_data = collection(s)
    serpapi_col = serpapi_readiness(s.root)
    ignav_col = ignav_readiness(s.root)
    live_collection = (
        serpapi_col
        if serpapi_col.get("configured")
        or serpapi_col.get("observation_count", 0) > 0
        or serpapi_col.get("status") in ("VERIFIED_CACHE_WARM", "LIVE_API_READY", "LIVE_COLLECTION_COMPLETE")
        or bool(os.environ.get("SERPAPI_API_KEY", "").strip())
        else ignav_col
    )
    live_fares_by_route = defaultdict(list)
    provider_name = live_collection.get("provider", "Live Provider")
    for observation in live_collection.get("observations", []):
        try:
            amount = float(observation["total_fare"])
        except (KeyError, TypeError, ValueError):
            continue
        if amount > 0 and observation.get("currency") == "INR" and observation.get("price_status") == "verified":
            live_fares_by_route[observation["route_id"]].append(amount)
            if observation.get("provider"):
                provider_name = observation["provider"]
    live_quote_routes = [
        {
            "route_id": route_id,
            "average_fare": f"{sum(fares) / len(fares):.2f}",
            "minimum_fare": f"{min(fares):.2f}",
            "maximum_fare": f"{max(fares):.2f}",
            "quote_count": len(fares),
            "currency": "INR",
            "provider": provider_name,
        }
        for route_id, fares in sorted(live_fares_by_route.items())
    ]
    source_status = [dict(row) for row in s.tables["source_coverage"]]
    cpi = [dict(row) for row in s.tables["mospi_cpi"]]
    cpi.sort(key=lambda row: row["period"])
    current_index = latest(s)
    latest_backtest = backtest(s)
    flagged_severity_counts = defaultdict(int)
    for row in anomaly_routes:
        flagged_severity_counts[row["severity"]] += 1

    return {
        "publication_timestamp": s.publication_timestamp,
        "data_status": "DEMO / SYNTHETIC — NOT LIVE" if demo_active else "SYNTHETIC_PROTOTYPE",
        "official_status": "NOT_OFFICIAL",
        "is_real_market_collection": False,
        "index_latest": current_index,
        "index_history": index_rows,
        "routes": basket_routes,
        "overview_routes": overview_routes,
        "route_history": route_history,
        "lead_time": get_lead_time_demo_rows() if demo_active else lead_time_rows(s),
        "anomaly_routes": anomaly_routes,
        "anomaly_trend": [
            {"date": date, "count": count}
            for date, count in sorted(anomaly_trend.items())
        ],
        "anomaly_summary": {
            "route_count": len(anomaly_routes),
            "severity_counts": dict(sorted(flagged_severity_counts.items())),
            "review_record_count": sum(
                row["recommended_review"] == "True" for row in anomalies
            ),
            "diagnostic_record_count": len(anomalies),
        },
        "validation": {
            "record_count": total_records,
            "valid_record_count": valid_records,
            "invalid_record_count": total_records - valid_records,
            "records_with_validation_errors": invalid_records,
            "records_with_missing_required_fields": records_with_missing,
            "valid_pct": f"{(valid_records / total_records * 100):.2f}" if total_records else None,
            "status_counts": dict(sorted(validation_status_counts.items())),
            "error_counts": dict(sorted(validation_error_counts.items())),
        },
        "quality_trend": quality_trend,
        "source_status": {
            "total": collection_data["source_count"],
            "authorized": collection_data["authorized_source_count"],
            "blocked": collection_data["blocked_source_count"],
            "live_observations": collection_data["observation_count"],
            "live_collection_status": collection_data["live_collection_status"],
            "live_provider_observations": live_collection["observation_count"],
            "sources": source_status,
        },
        "cpi": cpi,
        "cpi_validation": latest_backtest,
        "cpi_comparison": compare_cpi(s.tables["period_index"], cpi),
        "live_collection": live_collection,
        "live_quote_routes": live_quote_routes,
        "data_quality": data_quality_summary(s),
    }
