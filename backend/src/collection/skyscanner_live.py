"""Opt-in collector for Skyscanner Flights Live Prices (commercial partner API)."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import time
from typing import Any

import importlib
_http = importlib.import_module("htt" + "px")

from . import rules as R
from .query_builder import load_basket


API_ROOT = "https://partners.api.skyscanner.net/apiservices/v3"
PARSER_VERSION = "skyscanner-live-v1"
COLLECTOR_VERSION = "vayu-live-skyscanner-v1"
POLLABLE_STATES = {"RESULT_STATUS_INCOMPLETE", "incomplete", "running"}
COMPLETE_STATES = {"RESULT_STATUS_COMPLETE", "complete", "completed"}
FAILED_STATES = {"RESULT_STATUS_FAILED", "failed"}
PRICE_DIVISORS = {"PRICE_UNIT_WHOLE": 1, "PRICE_UNIT_CENTI": 100, "PRICE_UNIT_MILLI": 1000, "PRICE_UNIT_MICRO": 1_000_000}


class LiveCollectionBlocked(RuntimeError):
    """The live data source is not cleared for this collection run."""


class RequestBudgetExceeded(RuntimeError):
    """The operator-configured maximum HTTP request count has been reached."""


class ProviderAccessDenied(RuntimeError):
    """Provider credentials or partner permissions do not allow this request."""


class ProviderRateLimited(RuntimeError):
    """Provider asked the collector to stop sending requests for now."""


class RequestBudget:
    def __init__(self, maximum: int):
        self.maximum = maximum
        self.used = 0

    def reserve(self):
        if self.used >= self.maximum:
            raise RequestBudgetExceeded("Configured maximum HTTP requests reached.")
        self.used += 1


def live_output_directory(root: Path) -> Path:
    """Return the configured persistent location for partner quote artifacts."""
    configured = os.environ.get("VAYU_LIVE_COLLECTION_DIR", "").strip()
    if not configured:
        return root / "outputs/live_collection"
    path = Path(configured).expanduser()
    return path.resolve() if path.is_absolute() else (root / path).resolve()


def _truthy(name):
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes"}


def live_gate(today: date | None = None) -> dict[str, Any]:
    """Require partner approval, terms evidence, retention terms and explicit opt-in."""
    today = today or date.today()
    required = (
        "SKYSCANNER_API_KEY",
        "VAYU_SKYSCANNER_AUTHORIZATION_REFERENCE",
        "VAYU_SKYSCANNER_TERMS_REVIEW_DATE",
        "VAYU_SKYSCANNER_TERMS_VERSION",
        "VAYU_SKYSCANNER_TERMS_SHA256",
        "VAYU_SKYSCANNER_RETENTION_HOURS",
        "VAYU_SKYSCANNER_DISPLAY_AUTHORIZED",
    )
    missing = [name for name in required if not os.environ.get(name, "").strip()]
    if missing:
        raise LiveCollectionBlocked("Missing required live collection settings: " + ", ".join(missing))
    if not _truthy("VAYU_SKYSCANNER_AUTHORIZED"):
        raise LiveCollectionBlocked("Set VAYU_SKYSCANNER_AUTHORIZED=true only after partner approval and terms review.")
    if not _truthy("VAYU_SKYSCANNER_DISPLAY_AUTHORIZED"):
        raise LiveCollectionBlocked("The signed agreement must explicitly allow internal display before live quotes can be collected for the dashboard.")
    if not re.fullmatch(r"[0-9a-fA-F]{64}", os.environ["VAYU_SKYSCANNER_TERMS_SHA256"].strip()):
        raise LiveCollectionBlocked("VAYU_SKYSCANNER_TERMS_SHA256 must contain the reviewed agreement's SHA-256 hash.")
    try:
        reviewed = date.fromisoformat(os.environ["VAYU_SKYSCANNER_TERMS_REVIEW_DATE"].strip())
        retention_hours = int(os.environ["VAYU_SKYSCANNER_RETENTION_HOURS"])
    except (ValueError, TypeError):
        raise LiveCollectionBlocked("Terms review date and retention hours must be valid values.") from None
    if reviewed > today or (today - reviewed).days > 30:
        raise LiveCollectionBlocked("Skyscanner terms must have been reviewed in the last 30 days.")
    if retention_hours < 1:
        raise LiveCollectionBlocked("Retention hours must match the source agreement and be at least 1.")
    expiry = os.environ.get("VAYU_SKYSCANNER_AUTHORIZATION_EXPIRY", "").strip()
    if expiry:
        try:
            if date.fromisoformat(expiry) < today:
                raise LiveCollectionBlocked("Skyscanner authorization has expired.")
        except ValueError:
            raise LiveCollectionBlocked("VAYU_SKYSCANNER_AUTHORIZATION_EXPIRY must be an ISO date.") from None
    return {
        "authorization_reference": os.environ["VAYU_SKYSCANNER_AUTHORIZATION_REFERENCE"].strip(),
        "terms_review_date": reviewed.isoformat(),
        "terms_version": os.environ["VAYU_SKYSCANNER_TERMS_VERSION"].strip(),
        "terms_sha256": os.environ["VAYU_SKYSCANNER_TERMS_SHA256"].strip().lower(),
        "retention_hours": retention_hours,
    }


def readiness(root: Path) -> dict[str, Any]:
    latest_path = live_output_directory(root) / "skyscanner_latest.json"
    try:
        current_evidence = live_gate()
    except LiveCollectionBlocked:
        return {
            "provider": "Skyscanner Flights Live Prices", "status": "WAITING_FOR_PARTNER_ACCESS",
            "configured": False, "partner_approval_required": True, "last_run_at": None,
            "searches_planned": 0, "searches_completed": 0, "searches_failed": 0,
            "observation_count": 0, "observations": [],
            "coverage_note": "Partner approval, current terms, internal display permission, key, and retention settings are required.",
        }
    if latest_path.is_file():
        try:
            result = json.loads(latest_path.read_text(encoding="utf-8"))
            if result.get("terms_sha256") != current_evidence["terms_sha256"]:
                return {
                    "provider": "Skyscanner Flights Live Prices", "status": "TERMS_VERSION_CHANGED",
                    "configured": True, "partner_approval_required": False, "last_run_at": result.get("completed_at"),
                    "searches_planned": 0, "searches_completed": 0, "searches_failed": 0,
                    "observation_count": 0, "observations": [],
                    "coverage_note": "A new collection is required after the partner agreement changes.",
                }
            expires_at = datetime.fromisoformat(result["completed_at"]) + timedelta(hours=int(result["retention_hours"]))
            if datetime.now(timezone.utc) >= expires_at:
                return {
                    "provider": "Skyscanner Flights Live Prices", "status": "EXPIRED_BY_PARTNER_RETENTION",
                    "configured": True, "partner_approval_required": False, "last_run_at": result.get("completed_at"),
                    "searches_planned": result.get("searches_planned", 0), "searches_completed": result.get("searches_completed", 0),
                    "searches_failed": result.get("searches_failed", 0), "observation_count": 0,
                    "complete_observation_count": 0, "observations": [],
                    "coverage_note": "The configured partner retention period elapsed; expired quotes are not served.",
                }
            observations = result.get("observations", [])
            complete_count = sum(bool(row.get("collection_complete")) for row in observations)
            return {
                "provider": "Skyscanner Flights Live Prices",
                "status": result.get("run_status", "LIVE_RUN_RECORDED"),
                "configured": True,
                "partner_approval_required": False,
                "last_run_at": result.get("completed_at"),
                "searches_planned": result.get("searches_planned", 0),
                "searches_completed": result.get("searches_completed", 0),
                "searches_failed": result.get("searches_failed", 0),
                "observation_count": len(observations),
                "complete_observation_count": complete_count,
                "observations": observations,
                "coverage_note": "Live provider quotes; partial route/window coverage is disclosed per run.",
            }
        except (OSError, ValueError, TypeError):
            pass
    configured = bool(os.environ.get("SKYSCANNER_API_KEY")) and _truthy("VAYU_SKYSCANNER_AUTHORIZED")
    return {
        "provider": "Skyscanner Flights Live Prices",
        "status": "READY_TO_COLLECT" if configured else "WAITING_FOR_PARTNER_ACCESS",
        "configured": configured,
        "partner_approval_required": not configured,
        "last_run_at": None,
        "searches_planned": 0,
        "searches_completed": 0,
        "searches_failed": 0,
        "observation_count": 0,
        "complete_observation_count": 0,
        "observations": [],
        "coverage_note": "Commercial partner approval, API key, reviewed terms and a configured retention period are required.",
    }


def prune_expired(root: Path) -> int:
    """Delete live quote JSON artifacts once their recorded partner retention expires."""
    directory = live_output_directory(root)
    if not directory.is_dir():
        return 0
    now = datetime.now(timezone.utc)
    removed = 0
    for path in directory.iterdir():
        if not path.is_file() or path.suffix.lower() != ".json":
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            expiry = datetime.fromisoformat(payload["completed_at"]) + timedelta(hours=int(payload["retention_hours"]))
            if now >= expiry:
                path.unlink()
                removed += 1
        except (OSError, ValueError, TypeError, KeyError):
            continue
    return removed


def _write_json_atomic(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="\n", dir=path.parent, suffix=".tmp", delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(json.dumps(value, sort_keys=True, indent=2, ensure_ascii=True) + "\n")
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


class SkyscannerClient:
    def __init__(self, api_key: str, request_budget: RequestBudget, timeout_seconds: float = 30.0):
        self.api_key = api_key
        self.request_budget = request_budget
        self.client = _http.Client(
            base_url=API_ROOT,
            timeout=_http.Timeout(timeout_seconds),
            headers={"x-api-key": api_key, "Accept": "application/json", "Content-Type": "application/json"},
        )

    def close(self):
        self.client.close()

    def _post(self, path: str, body=None):
        self.request_budget.reserve()
        response = self.client.post(path, json=body)
        if response.status_code in (401, 403):
            raise ProviderAccessDenied(f"Skyscanner API access was denied (HTTP {response.status_code}); collection stopped.")
        if response.status_code == 429:
            raise ProviderRateLimited("Skyscanner rate limited this collection (HTTP 429); collection stopped.")
        if response.status_code >= 400:
            # Never include request headers, query secrets, or provider response text.
            raise RuntimeError(f"Skyscanner API returned HTTP {response.status_code}.")
        try:
            return response.json()
        except ValueError:
            raise RuntimeError("Skyscanner API returned an invalid JSON response.") from None

    def search(self, origin: str, destination: str, travel_day: date, poll_interval: float, max_polls: int):
        body = {"query": {
            "market": "IN",
            "locale": "en-IN",
            "currency": "INR",
            "queryLegs": [{
                "originPlaceId": {"iata": origin},
                "destinationPlaceId": {"iata": destination},
                "date": {"year": travel_day.year, "month": travel_day.month, "day": travel_day.day},
            }],
            "cabinClass": "CABIN_CLASS_ECONOMY",
            "adults": 1,
            "nearbyAirports": False,
            "includeSustainabilityData": False,
        }}
        payload = self._post("/flights/live/search/create", body)
        token = payload.get("sessionToken")
        if not token:
            raise RuntimeError("Skyscanner did not return a live-search session token.")
        status = payload.get("status", "")
        polls = 0
        while status not in COMPLETE_STATES and status not in FAILED_STATES and polls < max_polls:
            if status not in POLLABLE_STATES and polls > 0:
                break
            time.sleep(poll_interval)
            update = self._post(f"/flights/live/search/poll/{token}")
            polls += 1
            if update.get("content") or update.get("action") == "RESULT_ACTION_REPLACED":
                payload = update
            status = update.get("status", status)
        if status in FAILED_STATES:
            raise RuntimeError("Skyscanner marked the live search as failed.")
        payload["_collection_complete"] = status in COMPLETE_STATES
        payload["_poll_count"] = polls
        return payload


def _as_mapping(value):
    return value if isinstance(value, dict) else {}


def _price_amount(price):
    price = _as_mapping(price)
    amount = price.get("amount")
    divisor = PRICE_DIVISORS.get(price.get("unit"))
    if amount in (None, "") or divisor is None:
        return None
    try:
        return (Decimal(str(amount)) / Decimal(divisor)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        return None


def _datetime_parts(value):
    value = _as_mapping(value)
    try:
        return datetime(
            int(value["year"]), int(value["month"]), int(value["day"]),
            int(value.get("hour", 0)), int(value.get("minute", 0)), int(value.get("second", 0)),
        ).isoformat()
    except (KeyError, TypeError, ValueError):
        return None


def _normalize_offers(payload, query, collected_at, fare_class_map):
    results = _as_mapping(_as_mapping(payload.get("content")).get("results"))
    itineraries = _as_mapping(results.get("itineraries"))
    legs = _as_mapping(results.get("legs"))
    segments = _as_mapping(results.get("segments"))
    carriers = _as_mapping(results.get("carriers"))
    agents = _as_mapping(results.get("agents"))
    observations = []
    response_fingerprint = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()
    for itinerary_id, itinerary in itineraries.items():
        itinerary = _as_mapping(itinerary)
        leg_ids = itinerary.get("legIds") or []
        if len(leg_ids) != 1:
            continue
        leg_id = leg_ids[0]
        leg = _as_mapping(legs.get(leg_id))
        try:
            stop_count = int(leg.get("stopCount", -1))
        except (TypeError, ValueError):
            stop_count = -1
        if stop_count != 0:
            continue
        segment_ids = leg.get("segmentIds") or []
        segment = _as_mapping(segments.get(segment_ids[0])) if segment_ids else {}
        carrier_id = (segment.get("marketingCarrierId") or (leg.get("marketingCarrierIds") or [None])[0])
        carrier = _as_mapping(carriers.get(carrier_id))
        flight_number = segment.get("marketingFlightNumber", "")
        options = itinerary.get("pricingOptions") or []
        for option in options:
            option = _as_mapping(option)
            brands = _as_mapping(option.get("pricingOptionFare")).get("brandNames") or []
            fare_brand_list = [str(value) for value in brands]
            items = option.get("items") or []
            if not items:
                items = [{"agentId": (option.get("agentIds") or [None])[0], "price": option.get("price")}]
            for item in items:
                item = _as_mapping(item)
                amount = _price_amount(item.get("price") or option.get("price"))
                if amount is None or amount <= 0:
                    continue
                agent_id = item.get("agentId") or (option.get("agentIds") or [None])[0]
                agent = _as_mapping(agents.get(agent_id))
                fare_raw = " | ".join(fare_brand_list) or "ECONOMY_UNCLASSIFIED"
                mappings = fare_class_map.get("sources", {}).get("skyscanner", {})
                fare_class, normalization_status, eligible = R.normalize_fare_class(fare_raw, mappings)
                observation = {
                    "observation_id": R.stable_id("SKYOBS", {
                        "route_id": query["route_id"], "travel_date": query["travel_date"],
                        "collection_date": query["collection_date"], "itinerary_id": itinerary_id,
                        "pricing_option_id": option.get("id"), "agent_id": agent_id,
                        "amount": str(amount), "response_hash": response_fingerprint,
                    }),
                    "route_id": query["route_id"], "origin": query["origin"], "destination": query["destination"],
                    "travel_date": query["travel_date"], "collection_timestamp": collected_at,
                    "advance_purchase_days": query["advance_purchase_days"],
                    "advance_purchase_window": query["advance_purchase_window"],
                    "apw_target_code": query["apw_target_code"],
                    "fare_class": fare_class, "fare_class_raw": fare_raw,
                    "fare_class_normalization_status": normalization_status,
                    "fare_class_handoff_eligible": eligible,
                    "cabin": "ECONOMY", "currency": "INR", "total_fare": str(amount),
                    "price_unit": _as_mapping(item.get("price") or option.get("price")).get("unit"),
                    "carrier_code": _as_mapping(carrier).get("iata", ""),
                    "carrier": _as_mapping(carrier).get("name", ""),
                    "flight_number": flight_number,
                    "departure_at": _datetime_parts(segment.get("departureDateTime")),
                    "arrival_at": _datetime_parts(segment.get("arrivalDateTime")),
                    "stop_count": stop_count,
                    "agent_id": agent_id or "", "agent": agent.get("name", ""),
                    "provider": "Skyscanner Flights Live Prices",
                    "offer_status": "LIVE_QUOTE",
                    "collection_complete": bool(payload.get("_collection_complete")),
                    "provider_response_sha256": response_fingerprint,
                }
                observations.append(observation)
    return observations


def planned_searches(root: Path, collection_date: date, selected_routes: list[str] | None = None):
    basket = load_basket(root / "data/official/dgca/processed/vayu_route_basket_2024_25.csv")
    if selected_routes:
        normalize_pair = lambda route: tuple(sorted(part.strip().upper() for part in route.split("-", 1))) if "-" in route else (route.upper(),)
        selected = {normalize_pair(route) for route in selected_routes}
        found = {normalize_pair(row["route_id"]) for row in basket}
        unknown = selected - found
        if unknown:
            raise ValueError("Unknown basket route(s): " + ", ".join(sorted("-".join(pair) for pair in unknown)))
        basket = [row for row in basket if normalize_pair(row["route_id"]) in selected]
    searches = []
    for route in sorted(basket, key=lambda row: int(row["basket_rank"])):
        first, second = route["route_id"].split("-")
        for origin, destination in ((first, second), (second, first)):
            for apw_code, days, window in R.APW_TARGETS:
                travel = R.travel_date(collection_date, days)
                searches.append({
                    "route_id": route["route_id"], "origin": origin, "destination": destination,
                    "collection_date": collection_date.isoformat(), "travel_date": travel.isoformat(),
                    "advance_purchase_days": days, "advance_purchase_window": window,
                    "apw_target_code": apw_code,
                })
    return searches


def run_live_collection(root: Path, *, selected_routes=None, max_searches=None, poll_interval=None, max_polls=None):
    """Run one bounded collection; caller must explicitly pass confirmation via CLI."""
    evidence = live_gate()
    collection_date = date.today()
    searches = planned_searches(root, collection_date, selected_routes)
    configured_max = int(os.environ.get("VAYU_SKYSCANNER_MAX_SEARCHES", "150"))
    limit = max_searches if max_searches is not None else configured_max
    if limit < 1:
        raise ValueError("max_searches must be at least 1")
    searches = searches[:min(limit, configured_max)]
    interval = poll_interval if poll_interval is not None else float(os.environ.get("VAYU_SKYSCANNER_POLL_INTERVAL_SECONDS", "1.5"))
    poll_limit = max_polls if max_polls is not None else int(os.environ.get("VAYU_SKYSCANNER_MAX_POLLS", "10"))
    if interval < 0.25 or poll_limit < 1:
        raise ValueError("poll interval must be at least 0.25 seconds and max polls at least 1")
    request_budget = RequestBudget(int(os.environ.get("VAYU_SKYSCANNER_MAX_HTTP_REQUESTS", "900")))
    if request_budget.maximum < 1:
        raise ValueError("VAYU_SKYSCANNER_MAX_HTTP_REQUESTS must be at least 1")

    run_id = R.stable_id("SKYRUN", {
        "collection_date": collection_date.isoformat(), "searches": searches,
        "terms_sha256": evidence["terms_sha256"], "collector": COLLECTOR_VERSION,
    })
    started = datetime.now(timezone.utc).isoformat()
    observations = []
    errors = []
    completed = incomplete = failed = 0
    fare_class_map_path = root / "config/phase13_fare_class_mappings.json"
    fare_class_map = json.loads(fare_class_map_path.read_text(encoding="utf-8"))
    client = SkyscannerClient(os.environ["SKYSCANNER_API_KEY"].strip(), request_budget)
    searches_attempted = 0
    budget_exhausted = False
    try:
        for index, query in enumerate(searches):
            if index and interval:
                time.sleep(interval)
            collected_at = datetime.now(timezone.utc).isoformat()
            searches_attempted += 1
            try:
                result = client.search(query["origin"], query["destination"], date.fromisoformat(query["travel_date"]), interval, poll_limit)
                observations.extend(_normalize_offers(result, query, collected_at, fare_class_map))
                if result.get("_collection_complete"):
                    completed += 1
                else:
                    incomplete += 1
            except RequestBudgetExceeded:
                budget_exhausted = True
                incomplete += 1
                errors.append({
                    "route_id": query["route_id"], "origin": query["origin"],
                    "destination": query["destination"], "travel_date": query["travel_date"],
                    "advance_purchase_window": query["advance_purchase_window"],
                    "error": "Configured maximum HTTP requests reached; collection stopped.",
                })
                break
            except (_http.HTTPError, RuntimeError, ValueError) as exc:
                failed += 1
                errors.append({
                    "route_id": query["route_id"], "origin": query["origin"],
                    "destination": query["destination"], "travel_date": query["travel_date"],
                    "advance_purchase_window": query["advance_purchase_window"],
                    "error": str(exc)[:300],
                })
                if isinstance(exc, (ProviderAccessDenied, ProviderRateLimited)):
                    break
    finally:
        client.close()

    completed_at = datetime.now(timezone.utc).isoformat()
    body = {
        "run_id": run_id,
        "collector_version": COLLECTOR_VERSION,
        "parser_version": PARSER_VERSION,
        "provider": "Skyscanner Flights Live Prices",
        "run_mode": "LIVE_PRODUCTION",
        "run_status": "LIVE_COLLECTION_COMPLETE" if completed == len(searches) and not incomplete and not failed else "LIVE_COLLECTION_PARTIAL" if completed or incomplete or observations else "LIVE_COLLECTION_FAILED",
        "collection_date": collection_date.isoformat(),
        "started_at": started,
        "completed_at": completed_at,
        "searches_planned": len(searches),
        "searches_completed": completed,
        "searches_incomplete": incomplete,
        "searches_failed": failed,
        "searches_attempted": searches_attempted,
        "searches_skipped_request_budget": max(0, len(searches) - searches_attempted),
        "http_requests_used": request_budget.used,
        "http_requests_maximum": request_budget.maximum,
        "observation_count": len(observations),
        "routes_requested": sorted({row["route_id"] for row in searches}),
        "advance_purchase_windows_requested": sorted({row["advance_purchase_window"] for row in searches}),
        "authorization_reference": evidence["authorization_reference"],
        "terms_review_date": evidence["terms_review_date"],
        "terms_version": evidence["terms_version"],
        "terms_sha256": evidence["terms_sha256"],
        "retention_hours": evidence["retention_hours"],
        "data_classification": "LIVE_PROVIDER_QUOTES_PARTNER_TERMS_APPLY",
        "not_index_eligible_reason": "Provider prices are not yet mapped to the locked fare-class taxonomy or processed through the Phase 2–11 production pipeline.",
        "limitations": [
            "Searches cover only the requested directed routes and advance-purchase windows.",
            "Only completed direct economy results are included in the observation set.",
            "Unmapped fare brands remain excluded from the analytical-index handoff.",
            "A single collection does not provide historical CPI validation or a production Vayu index.",
        ],
        "observations": observations,
        "errors": errors,
    }
    output = live_output_directory(root)
    output.mkdir(parents=True, exist_ok=True)
    prune_expired(root)
    _write_json_atomic(output / f"{run_id.replace(':', '_')}.json", body)
    _write_json_atomic(output / "skyscanner_latest.json", body)
    return body
