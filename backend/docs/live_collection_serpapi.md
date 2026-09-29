# Live Airfare Collection: SerpApi Google Flights API

Vayu supports bounded live airfare quote collection using **SerpApi's Google Flights API** engine (`engine=google_flights`). This integration enables live fare observation retrieval across Vayu's 15 monitored domestic routes without web scraping or headless browsers.

## Overview & Architecture

- **Engine**: SerpApi Google Flights (`engine=google_flights`)
- **Base Endpoint**: `https://serpapi.com/search.json`
- **Authentication**: `SERPAPI_API_KEY` server environment variable (never hardcoded, never logged, never returned to browser clients).
- **Default Locale & Currency**: India market (`gl=in`, `hl=en`), INR (`currency=INR`).
- **Configurable Flight Parameters**:
  - `departure_date`: ISO YYYY-MM-DD (defaults to configured advance purchase targets: T+1, T+7, T+15, T+30, T+45).
  - `return_date`: ISO YYYY-MM-DD (optional, required when `trip_type=round_trip`).
  - `adults`: 1–9 passengers (default: 1).
  - `travel_class`: Economy (1), Premium Economy (2), Business (3), First (4). Default: Economy.
  - `trip_type`: One-way (2) or Round-trip (1). Default: One-way.
  - `stops`: Direct flights only (1) or any stops. Default: Direct (1).

## Provider Price Insights & Anomaly Detection

SerpApi Google Flights returns a `price_insights` object when available:
- `lowest_price`: Current lowest observed price for the route/date.
- `price_level`: Qualitative classification (`low`, `typical`, `high`).
- `typical_price_range`: `[min_typical, max_typical]` price band in INR.

When `typical_price_range` is returned by the provider:
- If `observed_fare > max_typical`: Flagged with potential price spike anomaly.
- If `observed_fare < min_typical`: Flagged with potential price drop anomaly.
- If comparison range is missing: Marked as `unclassified`.

## API Rate Limits and Quota Management

- SerpApi plans have bounded monthly search credits.
- **Circuit Breakers**:
  - `VAYU_SERPAPI_MAX_SEARCHES`: Hard ceiling per collection run (default: 150).
  - `VAYU_SERPAPI_MAX_HTTP_REQUESTS`: Absolute ceiling including retries (default: 300).
  - `VAYU_SERPAPI_REQUEST_INTERVAL_SECONDS`: Pacing between consecutive API requests (default: 0.5s).
  - Exponential backoff with jitter on HTTP 429 / 5xx responses.
- **Short-Lived Retention**:
  - `VAYU_SERPAPI_RETENTION_HOURS`: Cache retention window (1 to 24 hours, default: 2 hours).
  - Background sweeper automatically prunes expired quotes every 60 seconds.
  - Stale or expired quotes are never returned as verified live data.

## Environment Configuration

Add the following to your private server environment (e.g. `.env` file, NOT committed to Git):

```bash
# SerpApi API Key from https://serpapi.com/manage-api-key
SERPAPI_API_KEY=your_actual_serpapi_key_here

# Bounded search caps and pacing
VAYU_SERPAPI_MAX_SEARCHES=150
VAYU_SERPAPI_MAX_HTTP_REQUESTS=300
VAYU_SERPAPI_REQUEST_INTERVAL_SECONDS=0.5
VAYU_SERPAPI_RETENTION_HOURS=2

# Optional defaults
VAYU_SERPAPI_DEFAULT_CABIN=economy
VAYU_SERPAPI_DEFAULT_PASSENGERS=1
VAYU_SERPAPI_DEFAULT_TRIP_TYPE=one_way
```

## Running On-Demand Live Collection

### 0. Check key and account access without spending a search
After setting `SERPAPI_API_KEY` in the current terminal, run:
```powershell
python scripts/check_serpapi_account.py
```
This calls SerpApi's free account endpoint and prints only allowlisted account status/quota fields. It never prints the API key. Continue to a Google Flights search only if this check succeeds and the account is active.

### 1. Dry Run (No Network Calls)
Inspect planned searches without consuming any API quota:
```powershell
python scripts/run_live_serpapi_collection.py --dry-run
```

### 2. Single Route Test
Collect live quotes for a single route with bounded queries:
```powershell
python scripts/run_live_serpapi_collection.py --confirm-live --route DEL-BOM --max-searches 2
```

### 3. Custom Date, Cabin, and Passengers
```powershell
python scripts/run_live_serpapi_collection.py --confirm-live --route BOM-DEL --departure-date 2026-10-15 --cabin-class economy --passengers 1
```

### 4. Full 15-Route Basket Collection
```powershell
python scripts/run_live_serpapi_collection.py --confirm-live
```

### 5. Running with Docker Compose
```powershell
docker compose exec vayu-api python scripts/run_live_serpapi_collection.py --dry-run
docker compose exec vayu-api python scripts/run_live_serpapi_collection.py --confirm-live --route DEL-BOM --max-searches 2
```

## API Endpoints

- `GET /api/v1/collection/live`: Returns readiness and latest quotes (prioritizing SerpApi when active).
- `GET /api/v1/collection/serpapi`: Returns dedicated SerpApi Google Flights status, configuration, and observation stats.
- `GET /api/v1/routes`: Returns the 15 monitored basket routes. When live SerpApi quotes are present, routes are enriched with `fare_data_type="VERIFIED_LIVE"` and `provider="SerpApi Google Flights"`.
- `GET /api/v1/frontend-data`: Dashboard bundle with dynamic live quote and provider attribution.

## MoSPI CPI Integrity Guarantee

Live quotes gathered from SerpApi are strictly segregated from official MoSPI CPI inflation indices. Vayu enforces an exact-month overlapping rule: live daily/hourly fares are never substituted for complete monthly index rounds.
