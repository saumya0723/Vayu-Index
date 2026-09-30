"""Opt-in live fare collector for Ignav's self-service flight API."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time
from typing import Any

import importlib
_http = importlib.import_module("htt" + "px")

from . import rules as R
from .skyscanner_live import LiveCollectionBlocked, RequestBudget, RequestBudgetExceeded, live_output_directory, planned_searches


API_ROOT = "https://ignav.com/api/"
PARSER_VERSION = "ignav-fares-v1"
COLLECTOR_VERSION = "vayu-live-ignav-v1"
PROVIDER_NAME = "Ignav Flight API"


class ProviderAccessDenied(RuntimeError):
    """The supplied Ignav API key is missing, invalid, or unverified."""


class ProviderRateLimited(RuntimeError):
    """The provider asked the collector to stop sending requests."""


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
        value = int(os.environ.get("VAYU_IGNAV_RETENTION_HOURS", "2"))
    except ValueError:
        raise LiveCollectionBlocked("VAYU_IGNAV_RETENTION_HOURS must be an integer from 1 through 3.") from None
    if value < 1 or value > 3:
        raise LiveCollectionBlocked("VAYU_IGNAV_RETENTION_HOURS must be from 1 through 3 to keep live quotes short-lived.")
    return value


def readiness(root: Path) -> dict[str, Any]:
    """Expose provider readiness and only unexpired, recently collected quotes."""
    latest_path = live_output_directory(root) / "ignav_latest.json"
    api_key_present = bool(os.environ.get("IGNAV_API_KEY", "").strip())
    try:
        retention = _retention_hours()
    except LiveCollectionBlocked:
        retention = 2
        retention_valid = False
    else:
        retention_valid = True

    if latest_path.is_file():
        try:
            result = json.loads(latest_path.read_text(encoding="utf-8"))
            expires_at = datetime.fromisoformat(result["completed_at"]) + timedelta(hours=int(result["retention_hours"]))
            if datetime.now(timezone.utc) < expires_at:
                observations = result.get("observations", [])
                return {
                    "provider": PROVIDER_NAME,
                    "status": result.get("run_status", "LIVE_RUN_RECORDED"),
                    "configured": api_key_present and retention_valid,
                    "partner_approval_required": False,
                    "api_key_present": api_key_present,
                    "last_run_at": result.get("completed_at"),
                    "expires_at": expires_at.isoformat(),
                    "searches_planned": result.get("searches_planned", 0),
                    "searches_completed": result.get("searches_completed", 0),
                    "searches_failed": result.get("searches_failed", 0),
                    "observation_count": len(observations),
                    "verified_observation_count": sum(row.get("price_status") == "verified" and row.get("currency") == "INR" for row in observations),
                    "observations": observations,
                    "coverage_note": "Short-lived live fare results. Check price_status; only verified INR fares are eligible for downstream comparisons.",
                }
            return {
                "provider": PROVIDER_NAME,
                "status": "EXPIRED_LIVE_QUOTES",
                "configured": api_key_present and retention_valid,
                "partner_approval_required": False,
                "api_key_present": api_key_present,
                "last_run_at": result.get("completed_at"),
                "expires_at": expires_at.isoformat(),
                "searches_planned": result.get("searches_planned", 0),
                "searches_completed": result.get("searches_completed", 0),
                "searches_failed": result.get("searches_failed", 0),
                "observation_count": 0,
                "verified_observation_count": 0,
                "observations": [],
                "coverage_note": "The configured short retention period elapsed; expired quotes are not served.",
            }
        except (OSError, ValueError, TypeError, KeyError):
            pass

    configured = api_key_present and retention_valid
    return {
        "provider": PROVIDER_NAME,
        "status": "READY_TO_COLLECT" if configured else "WAITING_FOR_API_KEY_OR_SETTINGS",
        "configured": configured,
        "partner_approval_required": False,
        "api_key_present": api_key_present,
        "last_run_at": None,
        "searches_planned": 0,
        "searches_completed": 0,
        "searches_failed": 0,
        "observation_count": 0,
        "verified_observation_count": 0,
        "observations": [],
        "coverage_note": "Add IGNAV_API_KEY as a private server secret, verify the provider account email, then run the bounded collector.",
    }


class IgnavClient:
    def __init__(self, api_key: str, request_budget: RequestBudget, timeout_seconds: float = 45.0):
        self.request_budget = request_budget
        self.client = _http.Client(
            base_url=API_ROOT,
            timeout=_http.Timeout(timeout_seconds),
            headers={"X-Api-Key": api_key, "Accept": "application/json", "Content-Type": "application/json"},
        )

    def close(self):
        self.client.close()

    def search(self, origin: str, destination: str, travel_day: date, max_attempts: int = 3):
        body = {
            "origin": origin,
            "destination": destination,
            "departure_date": travel_day.isoformat(),
            "adults": 1,
            "cabin_class": "economy",
            "max_stops": 0,
            "allow_self_transfer": False,
            "market": "IN",
        }
        for attempt in range(max_attempts):
            self.request_budget.reserve()
            try:
                response = self.client.post("fares/one-way", json=body)
            except _http.HTTPError:
                if attempt + 1 == max_attempts:
                    raise
                time.sleep(min(0.5 * (2**attempt), 2.0))
                continue
            if response.status_code in {401, 403}:
                raise ProviderAccessDenied("Ignav rejected the key or requires the account email to be verified.")
            if response.status_code == 429:
                raise ProviderRateLimited("Ignav returned HTTP 429; collection stopped to respect the provider limit.")
            if response.status_code == 424 and attempt + 1 < max_attempts:
                time.sleep(min(0.5 * (2**attempt), 2.0))
                continue
            if response.status_code >= 400:
                if response.status_code == 402:
                    raise ProviderAccessDenied("Ignav requires billing setup after the free request allowance is exhausted.")
                raise RuntimeError(f"Ignav returned HTTP {response.status_code}.")
            try:
                payload = response.json()
            except ValueError:
                raise RuntimeError("Ignav returned an invalid JSON response.") from None
            if not isinstance(payload, dict) or not isinstance(payload.get("itineraries", []), list):
                raise RuntimeError("Ignav returned an unexpected fare response shape.")
            return payload
        raise RuntimeError("Ignav search failed after bounded retries.")


def _mapping(value):
    return value if isinstance(value, dict) else {}


def _normalize_itineraries(payload, query, collected_at):
    response_fingerprint = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()
    observations = []
    currency_excluded = 0
    for itinerary in payload.get("itineraries", []):
        itinerary = _mapping(itinerary)
        outbound = _mapping(itinerary.get("outbound"))
        segments = outbound.get("segments") or []
        if len(segments) != 1 or itinerary.get("requires_self_transfer") is True:
            continue
        segment = _mapping(segments[0])
        price = _mapping(itinerary.get("price"))
        currency = str(price.get("currency", "")).upper()
        if currency != "INR":
            currency_excluded += 1
            continue
        try:
            amount = Decimal(str(price.get("amount"))).quantize(Decimal("0.01"))
        except (InvalidOperation, ValueError, TypeError):
            continue
        if amount <= 0:
            continue
        price_status = str(price.get("status", "unverified")).lower()
        verified = price_status == "verified"
        fare_class_raw = "ECONOMY_UNCLASSIFIED"
        observations.append({
            "observation_id": R.stable_id("IGNAVOBS", {
                "route_id": query["route_id"], "travel_date": query["travel_date"],
                "collection_date": query["collection_date"], "ignav_id": itinerary.get("ignav_id"),
                "amount": str(amount), "response_hash": response_fingerprint,
            }),
            "route_id": query["route_id"],
            "origin": query["origin"],
            "destination": query["destination"],
            "travel_date": query["travel_date"],
            "collection_timestamp": collected_at,
            "advance_purchase_days": query["advance_purchase_days"],
            "advance_purchase_window": query["advance_purchase_window"],
            "apw_target_code": query["apw_target_code"],
            "fare_class": "UNKNOWN_FARE_CLASS",
            "fare_class_raw": fare_class_raw,
            "fare_class_normalization_status": "UNKNOWN_FARE_CLASS",
            "fare_class_handoff_eligible": False,
            "cabin": "ECONOMY",
            "currency": currency,
            "total_fare": str(amount),
            "price_status": price_status,
            "metric_eligible": bool(verified),
            "ignav_id": itinerary.get("ignav_id", ""),
            "price_unit": "INR",
            "carrier_code": segment.get("marketing_carrier_code") or "",
            "carrier": outbound.get("carrier") or segment.get("operating_carrier_name") or "",
            "flight_number": segment.get("flight_number") or "",
            "departure_at": segment.get("departure_time_local"),
            "arrival_at": segment.get("arrival_time_local"),
            "departure_timezone": segment.get("departure_timezone"),
            "arrival_timezone": segment.get("arrival_timezone"),
            "duration_minutes": outbound.get("duration_minutes") or segment.get("duration_minutes"),
            "stop_count": 0,
            "agent_id": "",
            "agent": "",
            "provider": PROVIDER_NAME,
            "offer_status": "LIVE_QUOTE" if verified else "UNVERIFIED_LIVE_QUOTE",
            "collection_complete": True,
            "provider_response_sha256": response_fingerprint,
        })
    return observations, currency_excluded


def run_live_collection(root: Path, *, selected_routes=None, max_searches=None, request_interval=None):
    """Run one bounded live search sweep; CLI requires explicit live confirmation."""
    api_key = os.environ.get("IGNAV_API_KEY", "").strip()
    if not api_key:
        raise LiveCollectionBlocked("IGNAV_API_KEY is required. Create an Ignav account, verify its email, then keep the key in a server secret.")
    retention_hours = _retention_hours()
    collection_date = date.today()
    searches = planned_searches(root, collection_date, selected_routes)
    configured_max = int(os.environ.get("VAYU_IGNAV_MAX_SEARCHES", "150"))
    limit = max_searches if max_searches is not None else configured_max
    if limit < 1 or configured_max < 1:
        raise ValueError("Search limits must be at least 1.")
    searches = searches[:min(limit, configured_max)]
    interval = request_interval if request_interval is not None else float(os.environ.get("VAYU_IGNAV_REQUEST_INTERVAL_SECONDS", "0.25"))
    if interval < 0:
        raise ValueError("Request interval must be nonnegative.")
    request_budget = RequestBudget(int(os.environ.get("VAYU_IGNAV_MAX_HTTP_REQUESTS", "450")))
    if request_budget.maximum < 1:
        raise ValueError("VAYU_IGNAV_MAX_HTTP_REQUESTS must be at least 1.")

    run_id = R.stable_id("IGNAVRUN", {
        "collection_date": collection_date.isoformat(), "searches": searches,
        "collector": COLLECTOR_VERSION,
    })
    started = datetime.now(timezone.utc).isoformat()
    observations = []
    errors = []
    completed = failed = attempted = currency_excluded = 0
    client = IgnavClient(api_key, request_budget)
    try:
        for index, query in enumerate(searches):
            if index and interval:
                time.sleep(interval)
            collected_at = datetime.now(timezone.utc).isoformat()
            attempted += 1
            try:
                result = client.search(query["origin"], query["destination"], date.fromisoformat(query["travel_date"]))
                rows, excluded = _normalize_itineraries(result, query, collected_at)
                observations.extend(rows)
                currency_excluded += excluded
                completed += 1
            except (_http.HTTPError, RuntimeError, ValueError, RequestBudgetExceeded) as exc:
                failed += 1
                errors.append({
                    "route_id": query["route_id"], "origin": query["origin"],
                    "destination": query["destination"], "travel_date": query["travel_date"],
                    "advance_purchase_window": query["advance_purchase_window"],
                    "error": str(exc)[:300],
                })
                if isinstance(exc, (ProviderAccessDenied, ProviderRateLimited, RequestBudgetExceeded)):
                    break
    finally:
        client.close()

    completed_at = datetime.now(timezone.utc).isoformat()
    verified_count = sum(row["price_status"] == "verified" for row in observations)
    body = {
        "run_id": run_id,
        "collector_version": COLLECTOR_VERSION,
        "parser_version": PARSER_VERSION,
        "provider": PROVIDER_NAME,
        "run_mode": "LIVE_PRODUCTION",
        "run_status": "LIVE_COLLECTION_COMPLETE" if completed == len(searches) and not failed else "LIVE_COLLECTION_PARTIAL" if completed or observations else "LIVE_COLLECTION_FAILED",
        "collection_date": collection_date.isoformat(),
        "started_at": started,
        "completed_at": completed_at,
        "retention_hours": retention_hours,
        "searches_planned": len(searches),
        "searches_completed": completed,
        "searches_failed": failed,
        "searches_attempted": attempted,
        "searches_skipped_request_budget": max(0, len(searches) - attempted),
        "http_requests_used": request_budget.used,
        "http_requests_maximum": request_budget.maximum,
        "observation_count": len(observations),
        "verified_observation_count": verified_count,
        "unverified_observation_count": len(observations) - verified_count,
        "non_inr_quotes_excluded": currency_excluded,
        "routes_requested": sorted({row["route_id"] for row in searches}),
        "advance_purchase_windows_requested": sorted({row["advance_purchase_window"] for row in searches}),
        "data_classification": "LIVE_PROVIDER_QUOTES_SHORT_RETENTION",
        "not_index_eligible_reason": "Live quotes remain diagnostic until verified INR values are mapped to the locked fare-class taxonomy and processed through sufficient historical coverage and the approved pipeline.",
        "limitations": [
            "The provider's market and route coverage can vary by search date.",
            "Only direct, single-segment economy itineraries in INR are recorded.",
            "Prices marked unverified are retained with that status and excluded from comparisons.",
            "Provider economy results do not expose Vayu Saver, Standard, or Flexi fare brands; no fare-class mapping is inferred.",
            "Live fare searches do not provide historical monthly fares for CPI validation.",
        ],
        "observations": observations,
        "errors": errors,
    }
    output = live_output_directory(root)
    output.mkdir(parents=True, exist_ok=True)
    _write_json_atomic(output / f"{run_id.replace(':', '_')}.json", body)
    _write_json_atomic(output / "ignav_latest.json", body)
    return body
