"""Route catalog service for 15 monitored basket routes with complete fare records.

Supports:
- Verified live quotes from Ignav Flight API when configured.
- Deterministic DEMO mode with illustrative INR fares clearly marked as
  'DEMO / SYNTHETIC — NOT LIVE'.
- Honest reporting of missing observations in live mode without fabrication.
"""
from __future__ import annotations

import os
from collections import defaultdict
from typing import Any

BASKET_ROUTES_CONFIG = (
    {
        "route_id": "BOM-DEL",
        "basket_rank": 1,
        "origin_code": "BOM",
        "destination_code": "DEL",
        "origin_name": "Mumbai",
        "destination_name": "Delhi",
        "traffic_weight": "0.162603",
        "airline": "Air India",
        "carrier_code": "AI",
        "flight_number": "AI-865",
        "demo_fare": "7407.11",
        "base_fare": "6100.00",
        "taxes": "1307.11",
        "quote_count": 3,
        "change_pct": "+2.66",
        "travel_date": "2026-10-15",
    },
    {
        "route_id": "BLR-DEL",
        "basket_rank": 2,
        "origin_code": "BLR",
        "destination_code": "DEL",
        "origin_name": "Bengaluru",
        "destination_name": "Delhi",
        "traffic_weight": "0.111103",
        "airline": "IndiGo",
        "carrier_code": "6E",
        "flight_number": "6E-5011",
        "demo_fare": "7680.12",
        "base_fare": "6350.00",
        "taxes": "1330.12",
        "quote_count": 3,
        "change_pct": "+10.99",
        "travel_date": "2026-10-15",
    },
    {
        "route_id": "BLR-BOM",
        "basket_rank": 3,
        "origin_code": "BLR",
        "destination_code": "BOM",
        "origin_name": "Bengaluru",
        "destination_name": "Mumbai",
        "traffic_weight": "0.097658",
        "airline": "Akasa Air",
        "carrier_code": "QP",
        "flight_number": "QP-1302",
        "demo_fare": "4850.00",
        "base_fare": "3950.00",
        "taxes": "900.00",
        "quote_count": 2,
        "change_pct": "+1.85",
        "travel_date": "2026-10-15",
    },
    {
        "route_id": "DEL-HYD",
        "basket_rank": 4,
        "origin_code": "DEL",
        "destination_code": "HYD",
        "origin_name": "Delhi",
        "destination_name": "Hyderabad",
        "traffic_weight": "0.078228",
        "airline": "IndiGo",
        "carrier_code": "6E",
        "flight_number": "6E-2041",
        "demo_fare": "5620.00",
        "base_fare": "4600.00",
        "taxes": "1020.00",
        "quote_count": 2,
        "change_pct": "+3.20",
        "travel_date": "2026-10-15",
    },
    {
        "route_id": "DEL-PNQ",
        "basket_rank": 5,
        "origin_code": "DEL",
        "destination_code": "PNQ",
        "origin_name": "Delhi",
        "destination_name": "Pune",
        "traffic_weight": "0.069402",
        "airline": "SpiceJet",
        "carrier_code": "SG",
        "flight_number": "SG-8185",
        "demo_fare": "5180.00",
        "base_fare": "4200.00",
        "taxes": "980.00",
        "quote_count": 2,
        "change_pct": "-1.45",
        "travel_date": "2026-10-15",
    },
    {
        "route_id": "CCU-DEL",
        "basket_rank": 6,
        "origin_code": "CCU",
        "destination_code": "DEL",
        "origin_name": "Kolkata",
        "destination_name": "Delhi",
        "traffic_weight": "0.065754",
        "airline": "Air India",
        "carrier_code": "AI",
        "flight_number": "AI-763",
        "demo_fare": "6240.00",
        "base_fare": "5100.00",
        "taxes": "1140.00",
        "quote_count": 2,
        "change_pct": "+0.80",
        "travel_date": "2026-10-15",
    },
    {
        "route_id": "AMD-DEL",
        "basket_rank": 7,
        "origin_code": "AMD",
        "destination_code": "DEL",
        "origin_name": "Ahmedabad",
        "destination_name": "Delhi",
        "traffic_weight": "0.060216",
        "airline": "IndiGo",
        "carrier_code": "6E",
        "flight_number": "6E-188",
        "demo_fare": "4150.00",
        "base_fare": "3350.00",
        "taxes": "800.00",
        "quote_count": 2,
        "change_pct": "-2.10",
        "travel_date": "2026-10-15",
    },
    {
        "route_id": "DEL-MAA",
        "basket_rank": 8,
        "origin_code": "DEL",
        "destination_code": "MAA",
        "origin_name": "Delhi",
        "destination_name": "Chennai",
        "traffic_weight": "0.058216",
        "airline": "IndiGo",
        "carrier_code": "6E",
        "flight_number": "6E-205",
        "demo_fare": "6490.00",
        "base_fare": "5300.00",
        "taxes": "1190.00",
        "quote_count": 2,
        "change_pct": "+4.15",
        "travel_date": "2026-10-15",
    },
    {
        "route_id": "BOM-HYD",
        "basket_rank": 9,
        "origin_code": "BOM",
        "destination_code": "HYD",
        "origin_name": "Mumbai",
        "destination_name": "Hyderabad",
        "traffic_weight": "0.055855",
        "airline": "Air India",
        "carrier_code": "AI",
        "flight_number": "AI-619",
        "demo_fare": "4320.00",
        "base_fare": "3500.00",
        "taxes": "820.00",
        "quote_count": 2,
        "change_pct": "+1.90",
        "travel_date": "2026-10-15",
    },
    {
        "route_id": "BLR-CCU",
        "basket_rank": 10,
        "origin_code": "BLR",
        "destination_code": "CCU",
        "origin_name": "Bengaluru",
        "destination_name": "Kolkata",
        "traffic_weight": "0.055230",
        "airline": "IndiGo",
        "carrier_code": "6E",
        "flight_number": "6E-6512",
        "demo_fare": "6850.00",
        "base_fare": "5600.00",
        "taxes": "1250.00",
        "quote_count": 2,
        "change_pct": "-0.95",
        "travel_date": "2026-10-15",
    },
    {
        "route_id": "DEL-SXR",
        "basket_rank": 11,
        "origin_code": "DEL",
        "destination_code": "SXR",
        "origin_name": "Delhi",
        "destination_name": "Srinagar",
        "traffic_weight": "0.054956",
        "airline": "SpiceJet",
        "carrier_code": "SG",
        "flight_number": "SG-160",
        "demo_fare": "5980.00",
        "base_fare": "4900.00",
        "taxes": "1080.00",
        "quote_count": 2,
        "change_pct": "+2.30",
        "travel_date": "2026-10-15",
    },
    {
        "route_id": "DEL-GOI",
        "basket_rank": 12,
        "origin_code": "DEL",
        "destination_code": "GOI",
        "origin_name": "Delhi",
        "destination_name": "Dabolim",
        "traffic_weight": "0.037070",
        "airline": "Akasa Air",
        "carrier_code": "QP",
        "flight_number": "QP-1411",
        "demo_fare": "6120.00",
        "base_fare": "5000.00",
        "taxes": "1120.00",
        "quote_count": 2,
        "change_pct": "+5.10",
        "travel_date": "2026-10-15",
    },
    {
        "route_id": "DEL-GAU",
        "basket_rank": 13,
        "origin_code": "DEL",
        "destination_code": "GAU",
        "origin_name": "Delhi",
        "destination_name": "Guwahati",
        "traffic_weight": "0.036519",
        "airline": "Air India",
        "carrier_code": "AI",
        "flight_number": "AI-889",
        "demo_fare": "7150.00",
        "base_fare": "5850.00",
        "taxes": "1300.00",
        "quote_count": 2,
        "change_pct": "+1.40",
        "travel_date": "2026-10-15",
    },
    {
        "route_id": "BLR-COK",
        "basket_rank": 14,
        "origin_code": "BLR",
        "destination_code": "COK",
        "origin_name": "Bengaluru",
        "destination_name": "Kochi",
        "traffic_weight": "0.035250",
        "airline": "IndiGo",
        "carrier_code": "6E",
        "flight_number": "6E-354",
        "demo_fare": "3920.00",
        "base_fare": "3150.00",
        "taxes": "770.00",
        "quote_count": 2,
        "change_pct": "-1.70",
        "travel_date": "2026-10-15",
    },
    {
        "route_id": "DEL-IDR",
        "basket_rank": 15,
        "origin_code": "DEL",
        "destination_code": "IDR",
        "origin_name": "Delhi",
        "destination_name": "Indore",
        "traffic_weight": "0.021940",
        "airline": "IndiGo",
        "carrier_code": "6E",
        "flight_number": "6E-2415",
        "demo_fare": "3780.00",
        "base_fare": "3050.00",
        "taxes": "730.00",
        "quote_count": 2,
        "change_pct": "+0.50",
        "travel_date": "2026-10-15",
    },
)

ROUTE_MAP = {r["route_id"]: r for r in BASKET_ROUTES_CONFIG}


def is_demo_mode(request: Any = None) -> bool:
    """Determine whether DEMO mode is active.

    Priority:
    1. Query param ?demo=true/1 or ?mode=demo (if request provided)
    2. Query param ?demo=false/0 or ?mode=live -> False
    3. Environment variable VAYU_DEMO_MODE=true/1 -> True
    4. Environment variable VAYU_DEMO_MODE=false/0 -> False
    5. Default: If IGNAV_API_KEY is not configured or no verified live quotes,
       default to True for display completeness during dashboard video presentation.
    """
    if request is not None:
        try:
            qp = getattr(request, "query_params", {})
            demo_qp = qp.get("demo") or qp.get("mode")
            if demo_qp:
                val = str(demo_qp).strip().lower()
                if val in ("1", "true", "yes", "demo"):
                    return True
                if val in ("0", "false", "no", "live"):
                    return False
        except Exception:
            pass

    env_val = os.environ.get("VAYU_DEMO_MODE", "").strip().lower()
    if env_val in ("1", "true", "yes", "demo"):
        return True
    if env_val in ("0", "false", "no", "live"):
        return False

    # Default: active when no live key is set, enabling full 15-route video presentation
    has_key = bool(
        os.environ.get("SERPAPI_API_KEY", "").strip()
        or os.environ.get("IGNAV_API_KEY", "").strip()
    )
    return not has_key


def get_live_quotes(root: Any) -> dict[str, dict[str, Any]]:
    """Return map of route_id -> latest verified live quote details from SerpApi or Ignav."""
    result: dict[str, dict[str, Any]] = {}

    # Check SerpApi Google Flights first
    try:
        from ...collection.serpapi_live import readiness as serpapi_readiness
        serpapi_data = serpapi_readiness(root)
        if serpapi_data.get("status") in ("VERIFIED_CACHE_WARM", "LIVE_API_READY"):
            for obs in serpapi_data.get("observations", []):
                if (
                    obs.get("currency") == "INR"
                    and obs.get("price_status") == "verified"
                    and obs.get("route_id") in ROUTE_MAP
                ):
                    route_id = obs["route_id"]
                    if route_id not in result:
                        try:
                            fare_val = float(obs["total_fare"])
                            result[route_id] = {
                                "route_id": route_id,
                                "average_fare": f"{fare_val:.2f}",
                                "total_fare": f"{fare_val:.2f}",
                                "base_fare": None,
                                "taxes": None,
                                "currency": "INR",
                                "airline": obs.get("carrier") or obs.get("carrier_code") or "Commercial Airline",
                                "carrier": obs.get("carrier") or obs.get("carrier_code") or "",
                                "carrier_code": obs.get("carrier_code") or "",
                                "flight_number": obs.get("flight_number") or "",
                                "quote_count": 1,
                                "source": obs.get("source") or "SerpApi Google Flights",
                                "provider": obs.get("provider") or "SerpApi Google Flights",
                                "retrieval_timestamp": obs.get("collection_timestamp"),
                                "travel_date": obs.get("travel_date"),
                                "search_date": str(obs.get("collection_timestamp") or "")[:10],
                                "fare_data_type": "VERIFIED_LIVE",
                                "is_live": True,
                                "is_demo": False,
                                "is_cached": False,
                                "status_label": "VERIFIED LIVE",
                                "price_insights": obs.get("price_insights") or {},
                            }
                        except (KeyError, TypeError, ValueError):
                            continue
    except Exception:
        pass

    # If Ignav quotes are available, add or supplement for missing routes
    try:
        from ...collection.ignav_live import readiness as ignav_readiness
        ignav_data = ignav_readiness(root)
        observations = ignav_data.get("observations", [])
        quotes_by_route: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for obs in observations:
            if (
                obs.get("currency") == "INR"
                and obs.get("price_status") == "verified"
                and obs.get("route_id") in ROUTE_MAP
                and obs["route_id"] not in result
            ):
                quotes_by_route[obs["route_id"]].append(obs)

        for route_id, rows in quotes_by_route.items():
            fares = []
            for r in rows:
                try:
                    fares.append(float(r["total_fare"]))
                except (KeyError, TypeError, ValueError):
                    continue
            if not fares:
                continue
            first = rows[0]
            avg_fare = sum(fares) / len(fares)
            result[route_id] = {
                "route_id": route_id,
                "average_fare": f"{avg_fare:.2f}",
                "total_fare": f"{avg_fare:.2f}",
                "base_fare": None,
                "taxes": None,
                "currency": "INR",
                "airline": first.get("carrier") or first.get("carrier_code") or "Commercial Airline",
                "carrier": first.get("carrier") or first.get("carrier_code") or "",
                "carrier_code": first.get("carrier_code") or "",
                "flight_number": first.get("flight_number") or "",
                "quote_count": len(fares),
                "source": "Ignav Flight API",
                "provider": "Ignav Flight API",
                "retrieval_timestamp": first.get("collection_timestamp"),
                "travel_date": first.get("travel_date"),
                "search_date": str(first.get("collection_timestamp") or "")[:10],
                "fare_data_type": "VERIFIED_LIVE",
                "is_live": True,
                "is_demo": False,
                "is_cached": False,
                "status_label": "VERIFIED LIVE",
            }
    except Exception:
        pass

    return result


def get_enriched_routes(s: Any, request: Any = None) -> list[dict[str, Any]]:
    """Return all 15 configured basket routes with complete, sourced fare records.

    - Every route contains origin/destination codes, names, rank, and traffic weight.
    - If verified live Ignav quotes exist for a route, they are used and marked VERIFIED_LIVE.
    - If in DEMO mode, remaining routes are populated with deterministic illustrative INR fares
      and marked 'DEMO / SYNTHETIC — NOT LIVE'.
    - If in LIVE mode and no quote exists, the route is preserved with total_fare=None,
      honestly marked 'NO QUOTE AVAILABLE'.
    """
    demo_active = is_demo_mode(request)
    live_quotes = get_live_quotes(s.root)
    coverage = {r["route_id"]: r for r in s.tables["route_coverage"]}

    out = []
    for cfg in BASKET_ROUTES_CONFIG:
        route_id = cfg["route_id"]
        cov = coverage.get(route_id, {})
        cov_status = cov.get("route_coverage_status", "NO_OBSERVATIONS")
        hist_median = cov.get("route_fare_median") or None
        rev_count = int(cov.get("recommended_review_cell_count", 0))

        if route_id in live_quotes:
            # Sourced from verified live provider
            lq = live_quotes[route_id]
            out.append({
                "route_id": route_id,
                "origin": cfg["origin_code"],
                "destination": cfg["destination_code"],
                "origin_code": cfg["origin_code"],
                "destination_code": cfg["destination_code"],
                "origin_name": cfg["origin_name"],
                "destination_name": cfg["destination_name"],
                "basket_rank": cfg["basket_rank"],
                "traffic_weight": cfg["traffic_weight"],
                "coverage_status": "VERIFIED_LIVE_QUOTE",
                "route_fare_median": hist_median,
                "airline": lq["airline"],
                "carrier": lq["carrier"],
                "carrier_code": lq["carrier_code"],
                "flight_number": lq["flight_number"],
                "currency": "INR",
                "total_fare": lq["total_fare"],
                "base_fare": lq["base_fare"],
                "taxes": lq["taxes"],
                "quote_count": lq["quote_count"],
                "source": lq.get("source") or "Live Provider",
                "provider": lq.get("provider") or "Live Provider",
                "retrieval_timestamp": lq["retrieval_timestamp"],
                "travel_date": lq["travel_date"],
                "search_date": lq["search_date"],
                "fare_data_type": "VERIFIED_LIVE",
                "is_live": True,
                "is_demo": False,
                "is_cached": False,
                "status_label": "VERIFIED LIVE",
                "recommended_review_count": rev_count,
            })
        elif demo_active:
            # Deterministic DEMO mode: illustrative INR fares clearly labeled
            out.append({
                "route_id": route_id,
                "origin": cfg["origin_code"],
                "destination": cfg["destination_code"],
                "origin_code": cfg["origin_code"],
                "destination_code": cfg["destination_code"],
                "origin_name": cfg["origin_name"],
                "destination_name": cfg["destination_name"],
                "basket_rank": cfg["basket_rank"],
                "traffic_weight": cfg["traffic_weight"],
                "coverage_status": "DEMO_SYNTHETIC_NOT_LIVE",
                "route_fare_median": hist_median,
                "airline": cfg["airline"],
                "carrier": cfg["airline"],
                "carrier_code": cfg["carrier_code"],
                "flight_number": cfg["flight_number"],
                "currency": "INR",
                "total_fare": cfg["demo_fare"],
                "base_fare": cfg["base_fare"],
                "taxes": cfg["taxes"],
                "quote_count": cfg["quote_count"],
                "source": "DEMO / SYNTHETIC — NOT LIVE",
                "provider": "Vayu Deterministic Demo",
                "retrieval_timestamp": "2026-09-28T10:00:00Z",
                "travel_date": cfg["travel_date"],
                "search_date": "2026-09-28",
                "fare_data_type": "DEMO",
                "is_live": False,
                "is_demo": True,
                "is_cached": False,
                "status_label": "DEMO / SYNTHETIC — NOT LIVE",
                "recommended_review_count": rev_count,
            })
        elif hist_median is not None:
            # Historical prototype baseline
            out.append({
                "route_id": route_id,
                "origin": cfg["origin_code"],
                "destination": cfg["destination_code"],
                "origin_code": cfg["origin_code"],
                "destination_code": cfg["destination_code"],
                "origin_name": cfg["origin_name"],
                "destination_name": cfg["destination_name"],
                "basket_rank": cfg["basket_rank"],
                "traffic_weight": cfg["traffic_weight"],
                "coverage_status": cov_status,
                "route_fare_median": hist_median,
                "airline": cfg["airline"],
                "carrier": cfg["airline"],
                "carrier_code": cfg["carrier_code"],
                "flight_number": cfg["flight_number"],
                "currency": "INR",
                "total_fare": hist_median,
                "base_fare": None,
                "taxes": None,
                "quote_count": int(cov.get("contributing_observation_count", 0)),
                "source": "PROTOTYPE_SNAPSHOT",
                "provider": "DGCA / Prototype Baseline",
                "retrieval_timestamp": "2026-09-07T20:15:00Z",
                "travel_date": "2026-09-20",
                "search_date": "2026-09-07",
                "fare_data_type": "PROTOTYPE_SNAPSHOT",
                "is_live": False,
                "is_demo": False,
                "is_cached": False,
                "status_label": "PROTOTYPE SNAPSHOT — NOT LIVE",
                "recommended_review_count": rev_count,
            })
        else:
            # Live mode with no returned quote: honest preservation of missing quote
            out.append({
                "route_id": route_id,
                "origin": cfg["origin_code"],
                "destination": cfg["destination_code"],
                "origin_code": cfg["origin_code"],
                "destination_code": cfg["destination_code"],
                "origin_name": cfg["origin_name"],
                "destination_name": cfg["destination_name"],
                "basket_rank": cfg["basket_rank"],
                "traffic_weight": cfg["traffic_weight"],
                "coverage_status": cov_status,
                "route_fare_median": None,
                "airline": None,
                "carrier": None,
                "carrier_code": None,
                "flight_number": None,
                "currency": "INR",
                "total_fare": None,
                "base_fare": None,
                "taxes": None,
                "quote_count": 0,
                "source": "NO_QUOTE",
                "provider": "NONE",
                "retrieval_timestamp": None,
                "travel_date": None,
                "search_date": None,
                "fare_data_type": "NO_QUOTE",
                "is_live": False,
                "is_demo": False,
                "is_cached": False,
                "status_label": "NO QUOTE AVAILABLE",
                "recommended_review_count": rev_count,
            })
    return out


def get_lead_time_demo_rows() -> list[dict[str, Any]]:
    """Return deterministic advance-purchase curve observations for all 15 routes."""
    curve = {
        1: 1.35,   # T+1: +35% surge near departure
        7: 1.18,   # T+7: +18%
        15: 1.00,  # T+15: Baseline
        30: 0.88,  # T+30: -12% early discount
        45: 0.82,  # T+45: -18% advance discount
    }
    windows = {1: "T1", 7: "T7", 15: "T15", 30: "T30", 45: "T45"}
    rows = []
    for cfg in BASKET_ROUTES_CONFIG:
        base = float(cfg["demo_fare"])
        for day, mult in curve.items():
            fare = base * mult
            rows.append({
                "route_id": cfg["route_id"],
                "advance_purchase_window": windows[day],
                "average_fare": f"{fare:.2f}",
                "observation_count": 2,
                "currency": "INR",
            })
    return rows
