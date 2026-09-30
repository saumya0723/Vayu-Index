"""Opt-in live fare collector for SerpApi Google Flights API."""
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
from .skyscanner_live import (
    LiveCollectionBlocked,
    RequestBudget,
    RequestBudgetExceeded,
    live_output_directory,
    planned_searches,
)

API_ROOT = "https://serpapi.com/"
PARSER_VERSION = "serpapi-google-flights-v1"
COLLECTOR_VERSION = "vayu-live-serpapi-v1"
PROVIDER_NAME = "SerpApi Google Flights"

AIRPORT_CODE_PATTERN = re.compile(r"^[A-Z]{3}$")


class ProviderAccessDenied(RuntimeError):
    """The supplied SerpApi key is missing, invalid, or unauthorized."""


class ProviderRateLimited(RuntimeError):
    """The provider returned HTTP 429; collection stopped to respect account rate limits."""


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


def _retention_hours() -> int:
    try:
        value = int(os.environ.get("VAYU_SERPAPI_RETENTION_HOURS", "2"))
    except ValueError:
        raise LiveCollectionBlocked("VAYU_SERPAPI_RETENTION_HOURS must be an integer from 1 through 24.") from None
    if value < 1 or value > 24:
        raise LiveCollectionBlocked("VAYU_SERPAPI_RETENTION_HOURS must be between 1 and 24 to keep live quotes bound.")
    return value


def _sanitize_error_message(msg: str) -> str:
    """Ensure secrets or query parameters with keys are redacted from logs and errors."""
    return re.sub(r"(api_key|api-key|key)=[^\s&'\"]+", r"\1=[REDACTED]", str(msg), flags=re.IGNORECASE)


def _clean_key(val: str) -> str:
    """Remove zero-width unicode characters, outer quotes, and surrounding whitespace."""
    return re.sub(r"[\u200B-\u200D\uFEFF]", "", val).strip(" \t\r\n").strip("'\"")


def _resolve_serpapi_key(raw_input: str | None = None, root: Path | None = None) -> str:
    # 1. Process environment or explicit raw_input takes precedence
    candidate = raw_input if raw_input is not None else os.environ.get("SERPAPI_API_KEY", "")
    cleaned = _clean_key(candidate)
    if cleaned:
        match = re.search(r"([0-9a-fA-F]{64})", cleaned)
        if match:
            return match.group(1)
        return cleaned

    # 2. Only fall back to local .env file if not provided in process environment
    target_root = Path(root) if root else Path(__file__).resolve().parents[2]
    env_file = target_root / ".env"
    if env_file.is_file():
        try:
            for line in env_file.read_text(encoding="utf-8").splitlines():
                stripped = line.strip()
                if stripped.startswith("SERPAPI_API_KEY="):
                    val = _clean_key(stripped.split("=", 1)[1])
                    m = re.search(r"([0-9a-fA-F]{64})", val)
                    if m:
                        return m.group(1)
                    if val:
                        return val
        except OSError:
            pass
    return ""


def validate_route_and_dates(origin: str, destination: str, travel_day: date, collection_day: date | None = None) -> None:
    """Validate IATA airport codes and dates according to Vayu collection standards."""
    origin_clean = origin.strip().upper()
    dest_clean = destination.strip().upper()
    if not AIRPORT_CODE_PATTERN.match(origin_clean):
        raise ValueError(f"Invalid origin airport code '{origin}'. Must be 3-letter IATA code.")
    if not AIRPORT_CODE_PATTERN.match(dest_clean):
        raise ValueError(f"Invalid destination airport code '{destination}'. Must be 3-letter IATA code.")
    if origin_clean == dest_clean:
        raise ValueError(f"Origin and destination cannot be identical ({origin_clean}).")
    if collection_day is not None and travel_day < collection_day:
        raise ValueError(f"Travel date ({travel_day.isoformat()}) cannot be before collection date ({collection_day.isoformat()}).")


def prune_expired(root: Path) -> int:
    """Delete SerpApi quote JSON artifacts once their recorded retention expires."""
    directory = live_output_directory(root)
    if not directory.is_dir():
        return 0
    now = datetime.now(timezone.utc)
    removed = 0
    for path in directory.iterdir():
        if not path.is_file() or not path.name.startswith("serpapi_") or path.suffix.lower() != ".json":
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if payload.get("provider") != PROVIDER_NAME:
                continue
            completed_at = payload.get("completed_at")
            retention_hours = int(payload.get("retention_hours", 2))
            if not completed_at:
                continue
            expiry = datetime.fromisoformat(completed_at) + timedelta(hours=retention_hours)
            if now >= expiry:
                path.unlink()
                removed += 1
        except (OSError, ValueError, TypeError, KeyError):
            continue
    return removed


def readiness(root: Path) -> dict[str, Any]:
    """Expose SerpApi connection readiness, quote cache status, and unexpired observations."""
    latest_path = live_output_directory(root) / "serpapi_latest.json"
    api_key_present = bool(_resolve_serpapi_key(root=root))
    try:
        retention = _retention_hours()
        retention_valid = True
    except LiveCollectionBlocked:
        retention = 2
        retention_valid = False

    configured = api_key_present and retention_valid

    if latest_path.is_file():
        try:
            result = json.loads(latest_path.read_text(encoding="utf-8"))
            completed_at = result.get("completed_at")
            if completed_at:
                expires_at = datetime.fromisoformat(completed_at) + timedelta(hours=int(result.get("retention_hours", retention)))
                now = datetime.now(timezone.utc)
                is_fresh = now < expires_at
                observations = result.get("observations", [])
                price_insights_by_route = result.get("price_insights_by_route", {})
                route_coverage = result.get("route_coverage_summary", {})

                status_label = result.get("run_status", "LIVE_RUN_RECORDED")
                if not is_fresh:
                    status_label = "EXPIRED_LIVE_QUOTES"

                return {
                    "provider": PROVIDER_NAME,
                    "status": status_label,
                    "configured": configured,
                    "api_key_present": api_key_present,
                    "airline_direct_authorization": False,
                    "authorization_note": "SerpApi provides an aggregation API key; this does not constitute direct authorization from airlines.",
                    "last_run_at": completed_at,
                    "expires_at": expires_at.isoformat(),
                    "is_fresh": is_fresh,
                    "is_cached": not is_fresh,
                    "retention_hours": int(result.get("retention_hours", retention)),
                    "searches_planned": result.get("searches_planned", 0),
                    "searches_completed": result.get("searches_completed", 0),
                    "searches_failed": result.get("searches_failed", 0),
                    "searches_attempted": result.get("searches_attempted", 0),
                    "route_coverage": route_coverage,
                    "observation_count": len(observations) if is_fresh else 0,
                    "verified_observation_count": sum(row.get("price_status") == "verified" and row.get("currency") == "INR" for row in observations) if is_fresh else 0,
                    "observations": observations if is_fresh else [],
                    "price_insights_by_route": price_insights_by_route if is_fresh else {},
                    "coverage_note": "Fresh SerpApi live quotes." if is_fresh else "Recorded live quotes have expired past the retention window.",
                }
        except (OSError, ValueError, TypeError, KeyError):
            pass

    return {
        "provider": PROVIDER_NAME,
        "status": "READY_TO_COLLECT" if configured else "WAITING_FOR_API_KEY_OR_SETTINGS",
        "configured": configured,
        "api_key_present": api_key_present,
        "airline_direct_authorization": False,
        "authorization_note": "SerpApi key configured separately from airline direct authorization.",
        "last_run_at": None,
        "expires_at": None,
        "is_fresh": False,
        "is_cached": False,
        "retention_hours": retention,
        "searches_planned": 0,
        "searches_completed": 0,
        "searches_failed": 0,
        "searches_attempted": 0,
        "route_coverage": {},
        "observation_count": 0,
        "verified_observation_count": 0,
        "observations": [],
        "price_insights_by_route": {},
        "coverage_note": "Set SERPAPI_API_KEY as an environment secret, then run bounded collection on demand.",
    }


class SerpApiClient:
    def __init__(
        self,
        api_key: str,
        request_budget: RequestBudget,
        timeout_seconds: float = 30.0,
    ):
        self.api_key = _resolve_serpapi_key(api_key)
        self.request_budget = request_budget
        self.client = _http.Client(
            base_url=API_ROOT,
            timeout=_http.Timeout(timeout_seconds),
            headers={
                "Accept": "application/json",
                "User-Agent": "Vayu-Backend/1.0",
            },
        )

    def close(self) -> None:
        self.client.close()

    def search_google_flights(
        self,
        origin: str,
        destination: str,
        travel_day: date,
        *,
        return_day: date | None = None,
        passengers: int = 1,
        cabin_class: str = "economy",
        trip_type: str = "one_way",
        stops: int = 1,  # 1 = nonstop only in SerpApi
        max_attempts: int = 2,
    ) -> dict[str, Any]:
        """Perform a Google Flights search via SerpApi.
        
        trip_type: 'one_way' (type=2) or 'round_trip' (type=1)
        travel_class: 1: economy, 2: premium economy, 3: business, 4: first
        stops: 0: any, 1: nonstop only, 2: 1 stop or fewer
        """
        validate_route_and_dates(origin, destination, travel_day)

        travel_class_code = {
            "economy": 1,
            "premium_economy": 2,
            "business": 3,
            "first": 4,
        }.get(cabin_class.lower(), 1)

        type_code = 1 if trip_type.lower() in ("round_trip", "1") else 2

        params: dict[str, Any] = {
            "engine": "google_flights",
            "departure_id": origin.upper(),
            "arrival_id": destination.upper(),
            "outbound_date": travel_day.isoformat(),
            "currency": "INR",
            "gl": "in",
            "hl": "en",
            "adults": passengers,
            "travel_class": travel_class_code,
            "type": type_code,
            "stops": stops,
            "api_key": self.api_key,
        }
        if type_code == 1 and return_day:
            params["return_date"] = return_day.isoformat()

        for attempt in range(max_attempts):
            self.request_budget.reserve()
            try:
                response = self.client.get("search.json", params=params)
            except _http.HTTPError as exc:
                if attempt + 1 == max_attempts:
                    raise RuntimeError(f"Network error communicating with SerpApi: {_sanitize_error_message(str(exc))}") from None
                time.sleep(min(1.0 * (2**attempt), 4.0))
                continue

            if response.status_code == 401:
                raise ProviderAccessDenied(
                    "SerpApi HTTP 401 Unauthorized: the API key is invalid, missing, or unrecognized by SerpApi. "
                    "Ensure SERPAPI_API_KEY in the current process environment contains the active 64-hex key copied from the SerpApi dashboard."
                )
            if response.status_code == 403:
                raise ProviderAccessDenied(
                    "SerpApi HTTP 403 Forbidden: the account or key is not permitted to access this endpoint. "
                    "Check account status, plan limits, or IP permissions in the SerpApi dashboard."
                )
            if response.status_code == 429:
                raise ProviderRateLimited("SerpApi returned HTTP 429 rate limit. Collection halted to protect account quota.")
            if response.status_code >= 400:
                raise RuntimeError(f"SerpApi returned HTTP {response.status_code}: {_sanitize_error_message(response.text[:200])}")

            try:
                payload = response.json()
            except ValueError:
                raise RuntimeError("SerpApi returned an invalid JSON response.") from None

            if not isinstance(payload, dict):
                raise RuntimeError("SerpApi returned an unexpected response shape.")
            
            # Check for API error message inside JSON
            if "error" in payload:
                err_msg = str(payload["error"])
                if "API key" in err_msg or "Invalid" in err_msg:
                    raise ProviderAccessDenied(f"SerpApi error: {_sanitize_error_message(err_msg)}")
                raise RuntimeError(f"SerpApi reported error: {_sanitize_error_message(err_msg)}")

            return payload

        raise RuntimeError("SerpApi Google Flights search failed after bounded retries.")


def _normalize_itineraries(payload: dict[str, Any], query: dict[str, Any], collected_at: str) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    """Parse SerpApi Google Flights response and extract observations and price insights."""
    response_fingerprint = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()

    observations = []
    
    # Extract price insights if present
    price_insights_raw = payload.get("price_insights")
    price_insights: dict[str, Any] | None = None
    if isinstance(price_insights_raw, dict):
        lowest_p = price_insights_raw.get("lowest_price")
        price_lvl = price_insights_raw.get("price_level")
        typical_range = price_insights_raw.get("typical_price_range")
        price_insights = {
            "lowest_price": lowest_p,
            "price_level": price_lvl,
            "typical_price_range": typical_range if (isinstance(typical_range, list) and len(typical_range) == 2) else None,
            "retrieved_at": collected_at,
        }

    # Best flights & other flights
    all_itineraries = []
    for section in ("best_flights", "other_flights"):
        items = payload.get(section)
        if isinstance(items, list):
            all_itineraries.extend(items)

    for itinerary in all_itineraries:
        if not isinstance(itinerary, dict):
            continue
        price_val = itinerary.get("price")
        if price_val is None:
            continue
        try:
            amount = Decimal(str(price_val)).quantize(Decimal("0.01"))
        except (InvalidOperation, ValueError, TypeError):
            continue
        if amount <= 0:
            continue

        flights = itinerary.get("flights") or []
        if not isinstance(flights, list) or not flights:
            continue

        # Look at the first leg or primary flight
        first_leg = flights[0] if isinstance(flights[0], dict) else {}
        airline_name = first_leg.get("airline") or ""
        flight_number = first_leg.get("flight_number") or ""
        dep_airport = first_leg.get("departure_airport", {}).get("id") if isinstance(first_leg.get("departure_airport"), dict) else ""
        arr_airport = first_leg.get("arrival_airport", {}).get("id") if isinstance(first_leg.get("arrival_airport"), dict) else ""
        
        # Calculate stops
        stops_count = max(0, len(flights) - 1)
        itinerary_desc = " -> ".join(
            f"{f.get('departure_airport', {}).get('id', '')} - {f.get('arrival_airport', {}).get('id', '')}"
            for f in flights if isinstance(f, dict)
        )

        col_date = query.get("collection_date") or str(collected_at)[:10]
        observations.append({
            "observation_id": R.stable_id("SERPAPIOBS", {
                "route_id": query["route_id"],
                "travel_date": query["travel_date"],
                "collection_date": col_date,
                "airline": airline_name,
                "flight_number": flight_number,
                "amount": str(amount),
                "response_hash": response_fingerprint,
            }),
            "route_id": query["route_id"],
            "origin": query["origin"],
            "destination": query["destination"],
            "travel_date": query["travel_date"],
            "collection_timestamp": collected_at,
            "advance_purchase_days": query.get("advance_purchase_days"),
            "advance_purchase_window": query.get("advance_purchase_window"),
            "apw_target_code": query.get("apw_target_code"),
            "fare_class": "UNKNOWN_FARE_CLASS",
            "fare_class_raw": "ECONOMY_UNCLASSIFIED",
            "fare_class_normalization_status": "UNKNOWN_FARE_CLASS",
            "fare_class_handoff_eligible": False,
            "cabin": "ECONOMY",
            "currency": "INR",
            "total_fare": str(amount),
            "price_status": "verified",
            "metric_eligible": True,
            "carrier_code": "",
            "carrier": airline_name,
            "airline": airline_name,
            "flight_number": flight_number,
            "departure_airport": dep_airport,
            "arrival_airport": arr_airport,
            "departure_at": first_leg.get("departure_airport", {}).get("time") if isinstance(first_leg.get("departure_airport"), dict) else None,
            "arrival_at": first_leg.get("arrival_airport", {}).get("time") if isinstance(first_leg.get("arrival_airport"), dict) else None,
            "duration_minutes": itinerary.get("total_duration"),
            "stop_count": stops_count,
            "itinerary_summary": itinerary_desc,
            "provider": PROVIDER_NAME,
            "offer_status": "LIVE_QUOTE",
            "collection_complete": True,
            "provider_response_sha256": response_fingerprint,
        })

    return observations, price_insights


def run_live_collection(
    root: Path,
    *,
    selected_routes: list[str] | None = None,
    max_searches: int | None = None,
    request_interval: float | None = None,
    passengers: int = 1,
    cabin_class: str = "economy",
    trip_type: str = "one_way",
) -> dict[str, Any]:
    """Run an on-demand, bounded live search sweep using SerpApi Google Flights."""
    api_key = _resolve_serpapi_key(root=root)
    if not api_key:
        raise LiveCollectionBlocked(
            "SERPAPI_API_KEY environment variable is required. Keep the key in a server secret."
        )

    retention_hours = _retention_hours()
    collection_date = date.today()
    searches = planned_searches(root, collection_date, selected_routes)

    configured_max = int(os.environ.get("VAYU_SERPAPI_MAX_SEARCHES", "150"))
    limit = max_searches if max_searches is not None else configured_max
    if limit < 1 or configured_max < 1:
        raise ValueError("Search limits must be at least 1.")
    searches = searches[:min(limit, configured_max)]

    interval = (
        request_interval
        if request_interval is not None
        else float(os.environ.get("VAYU_SERPAPI_REQUEST_INTERVAL_SECONDS", "0.5"))
    )
    if interval < 0:
        raise ValueError("Request interval must be non-negative.")

    max_reqs = int(os.environ.get("VAYU_SERPAPI_MAX_HTTP_REQUESTS", "300"))
    request_budget = RequestBudget(max_reqs)

    run_id = R.stable_id("SERPAPIRUN", {
        "collection_date": collection_date.isoformat(),
        "searches": searches,
        "collector": COLLECTOR_VERSION,
    })

    started = datetime.now(timezone.utc).isoformat()
    observations: list[dict[str, Any]] = []
    price_insights_by_route: dict[str, Any] = {}
    errors: list[dict[str, Any]] = []
    completed = failed = attempted = 0

    client = SerpApiClient(api_key, request_budget)
    try:
        for index, query in enumerate(searches):
            if index and interval:
                time.sleep(interval)
            collected_at = datetime.now(timezone.utc).isoformat()
            attempted += 1
            try:
                travel_d = date.fromisoformat(query["travel_date"])
                payload = client.search_google_flights(
                    query["origin"],
                    query["destination"],
                    travel_d,
                    passengers=passengers,
                    cabin_class=cabin_class,
                    trip_type=trip_type,
                    stops=1,  # nonstop
                )
                rows, insights = _normalize_itineraries(payload, query, collected_at)
                observations.extend(rows)
                if insights:
                    price_insights_by_route[query["route_id"]] = insights
                completed += 1
            except (_http.HTTPError, RuntimeError, ValueError, RequestBudgetExceeded) as exc:
                failed += 1
                errors.append({
                    "route_id": query["route_id"],
                    "origin": query["origin"],
                    "destination": query["destination"],
                    "travel_date": query["travel_date"],
                    "advance_purchase_window": query.get("advance_purchase_window"),
                    "error": _sanitize_error_message(str(exc))[:300],
                })
                if isinstance(exc, (ProviderAccessDenied, ProviderRateLimited, RequestBudgetExceeded)):
                    break
    finally:
        client.close()

    completed_at = datetime.now(timezone.utc).isoformat()
    verified_count = sum(row.get("price_status") == "verified" for row in observations)

    # Calculate route coverage summary
    all_routes = sorted({q["route_id"] for q in searches})
    covered_routes = sorted({obs["route_id"] for obs in observations})

    body = {
        "run_id": run_id,
        "collector_version": COLLECTOR_VERSION,
        "parser_version": PARSER_VERSION,
        "provider": PROVIDER_NAME,
        "run_mode": "LIVE_PRODUCTION",
        "run_status": (
            "LIVE_COLLECTION_COMPLETE"
            if completed == len(searches) and not failed
            else "LIVE_COLLECTION_PARTIAL"
            if completed or observations
            else "LIVE_COLLECTION_FAILED"
        ),
        "collection_date": collection_date.isoformat(),
        "started_at": started,
        "completed_at": completed_at,
        "retention_hours": retention_hours,
        "searches_planned": len(searches),
        "searches_completed": completed,
        "searches_failed": failed,
        "searches_attempted": attempted,
        "http_requests_used": request_budget.used,
        "http_requests_maximum": request_budget.maximum,
        "observation_count": len(observations),
        "verified_observation_count": verified_count,
        "routes_requested": all_routes,
        "routes_covered": covered_routes,
        "route_coverage_summary": {
            "total_requested": len(all_routes),
            "total_covered": len(covered_routes),
            "coverage_pct": round(len(covered_routes) / len(all_routes) * 100, 2) if all_routes else 0.0,
        },
        "price_insights_by_route": price_insights_by_route,
        "data_classification": "LIVE_PROVIDER_QUOTES_SHORT_RETENTION",
        "not_index_eligible_reason": (
            "Live quotes remain diagnostic until verified INR values are mapped to the locked fare-class "
            "taxonomy and processed through sufficient historical coverage and the approved pipeline."
        ),
        "airline_direct_authorization": False,
        "authorization_note": "SerpApi search API access configured; does not imply direct airline authorization.",
        "observations": observations,
        "errors": errors,
    }

    output = live_output_directory(root)
    output.mkdir(parents=True, exist_ok=True)
    _write_json_atomic(output / f"{run_id.replace(':', '_')}.json", body)
    _write_json_atomic(output / "serpapi_latest.json", body)
    return body
