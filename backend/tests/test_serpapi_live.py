"""Unit tests for SerpApi Google Flights live collector."""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import json
import os
from pathlib import Path
import pytest

from src.collection.serpapi_live import (
    PROVIDER_NAME,
    validate_route_and_dates,
    prune_expired,
    readiness,
    _sanitize_error_message,
    _normalize_itineraries,
    LiveCollectionBlocked,
    run_live_collection,
)
from src.collection.skyscanner_live import live_output_directory

ROOT = Path(__file__).resolve().parents[1]


def test_serpapi_sanitize_error_message():
    assert _sanitize_error_message("Error with api_key=secret_12345 in url") == "Error with api_key=[REDACTED] in url"
    assert _sanitize_error_message("api-key=abcdef9876") == "api-key=[REDACTED]"
    assert _sanitize_error_message("normal error") == "normal error"


def test_serpapi_validate_route_and_dates():
    validate_route_and_dates("DEL", "BOM", date(2026, 10, 15))
    with pytest.raises(ValueError, match="Invalid origin"):
        validate_route_and_dates("DELHI", "BOM", date(2026, 10, 15))
    with pytest.raises(ValueError, match="Invalid destination"):
        validate_route_and_dates("DEL", "123", date(2026, 10, 15))
    with pytest.raises(ValueError, match="cannot be identical"):
        validate_route_and_dates("DEL", "DEL", date(2026, 10, 15))
    with pytest.raises(ValueError, match="cannot be before collection date"):
        validate_route_and_dates("DEL", "BOM", date(2026, 10, 10), date(2026, 10, 15))


def test_serpapi_readiness_no_key(tmp_path, monkeypatch):
    monkeypatch.setenv("VAYU_LIVE_COLLECTION_DIR", str(tmp_path))
    monkeypatch.delenv("SERPAPI_API_KEY", raising=False)
    state = readiness(tmp_path)
    assert state["provider"] == PROVIDER_NAME
    assert state["configured"] is False
    assert state["api_key_present"] is False
    assert state["status"] == "WAITING_FOR_API_KEY_OR_SETTINGS"
    assert state["airline_direct_authorization"] is False


def test_serpapi_readiness_with_key_no_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("VAYU_LIVE_COLLECTION_DIR", str(tmp_path))
    monkeypatch.setenv("SERPAPI_API_KEY", "dummy_test_key")
    monkeypatch.setenv("VAYU_SERPAPI_RETENTION_HOURS", "2")
    state = readiness(tmp_path)
    assert state["provider"] == PROVIDER_NAME
    assert state["configured"] is True
    assert state["api_key_present"] is True
    assert state["status"] == "READY_TO_COLLECT"


def test_serpapi_normalization():
    mock_payload = {
        "best_flights": [
            {
                "flights": [
                    {
                        "airline": "Air India",
                        "flight_number": "AI 865",
                        "departure_airport": {"id": "DEL", "time": "2026-10-15 08:00"},
                        "arrival_airport": {"id": "BOM", "time": "2026-10-15 10:15"},
                    }
                ],
                "price": 7450,
                "total_duration": 135,
            }
        ],
        "other_flights": [],
        "price_insights": {
            "lowest_price": 7450,
            "price_level": "typical",
            "typical_price_range": [6500, 8500],
        },
    }
    query = {
        "route_id": "DEL-BOM",
        "origin": "DEL",
        "destination": "BOM",
        "travel_date": "2026-10-15",
        "advance_purchase_window": "T15",
        "query_id": "QRY-TEST",
    }
    now = datetime.now(timezone.utc).isoformat()
    obs, insights = _normalize_itineraries(mock_payload, query, now)
    assert len(obs) == 1
    assert obs[0]["route_id"] == "DEL-BOM"
    assert obs[0]["total_fare"] == "7450.00"
    assert obs[0]["currency"] == "INR"
    assert obs[0]["price_status"] == "verified"
    assert obs[0]["airline"] == "Air India"
    assert insights["lowest_price"] == 7450
    assert insights["typical_price_range"] == [6500, 8500]


def test_serpapi_retention_and_pruning(tmp_path, monkeypatch):
    monkeypatch.setenv("VAYU_LIVE_COLLECTION_DIR", str(tmp_path))
    monkeypatch.setenv("SERPAPI_API_KEY", "dummy")
    now = datetime.now(timezone.utc)
    expired_time = (now - timedelta(hours=3)).isoformat()
    fresh_time = (now - timedelta(minutes=30)).isoformat()

    expired_file = tmp_path / "serpapi_expired.json"
    expired_file.write_text(json.dumps({
        "provider": PROVIDER_NAME,
        "completed_at": expired_time,
        "retention_hours": 2,
    }), encoding="utf-8")

    fresh_file = tmp_path / "serpapi_fresh.json"
    fresh_file.write_text(json.dumps({
        "provider": PROVIDER_NAME,
        "completed_at": fresh_time,
        "retention_hours": 2,
    }), encoding="utf-8")

    deleted = prune_expired(tmp_path)
    assert deleted == 1
    assert not expired_file.exists()
    assert fresh_file.exists()
