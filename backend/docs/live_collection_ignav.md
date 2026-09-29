# Live airfare collection: Ignav Flight API

Vayu now has an opt-in backend collector for Ignav's one-way fare-search API. The provider offers self-service account signup rather than the multi-week partner application used by Skyscanner. Its signup page advertises an API key in about 30 seconds, but the account email must be verified before API requests work. The provider also offers a no-signup playground for an initial route check.

## Create an API key

1. Create an account at [Ignav signup](https://ignav.com/signup).
2. Verify the account email from the message Ignav sends.
3. Copy the API key from the Ignav dashboard. Keep it in a private deployment secret; never put it in frontend JavaScript or commit it to Git.
4. Review the provider's [terms](https://ignav.com/terms), [pricing](https://ignav.com/pricing), and [fare response guidance](https://ignav.com/docs/response-format).
5. Before collecting the full basket, check Vayu routes in the [no-signup playground](https://ignav.com/playground). Provider route availability varies by search date.

The documented search endpoint is `POST https://ignav.com/api/fares/one-way`. For Vayu, the search is one adult, economy, nonstop, no self-transfer, India market (`IN`, INR), on each direction of each basket route at T+1, T+7, T+15, T+30, and T+45 days. A full pass is 150 searches.

Example request for DEL-BOM at T+15 from 2026-09-28:

```http
POST /api/fares/one-way
Host: ignav.com
X-Api-Key: <server-side secret>
Content-Type: application/json

{
  "origin": "DEL",
  "destination": "BOM",
  "departure_date": "2026-10-13",
  "adults": 1,
  "cabin_class": "economy",
  "max_stops": 0,
  "allow_self_transfer": false,
  "market": "IN"
}
```

Responses can include price and status, airline code, flight number, airports, local and UTC times, duration, baggage when available, and the provider itinerary ID. Empty itinerary arrays are valid. Only `price.status == "verified"` fares are eligible for comparisons; unverified offers remain marked and are never promoted as confirmed values. The API does not supply Vayu's Saver, Standard, or Flexi fare-brand classification, so the collector leaves those fares unmapped.

## Run a bounded collection

Set `IGNAV_API_KEY` in the host's secret manager. Docker Compose reads it from the project `.env`; for a direct PowerShell run, set it in the current shell (for example, `$env:IGNAV_API_KEY = '<your key>'`). Do not commit `.env`. The sample `.env.example` uses a two-hour quote-retention period. Run from the backend project directory:

```powershell
python scripts/run_live_ignav_collection.py --dry-run
python scripts/run_live_ignav_collection.py --confirm-live --route DEL-BOM --max-searches 2
```

The first command makes no network requests. The second spends at most two successful search requests (retries are separately capped by `VAYU_IGNAV_MAX_HTTP_REQUESTS`). After confirming the provider returns the expected route data, run the full pass with:

```powershell
python scripts/run_live_ignav_collection.py --confirm-live
```

With Docker Compose, the equivalent commands are:

```powershell
docker compose exec vayu-api python scripts/run_live_ignav_collection.py --dry-run
docker compose exec vayu-api python scripts/run_live_ignav_collection.py --confirm-live --route DEL-BOM --max-searches 2
```

The collector stores normalized quotes in the configured `VAYU_LIVE_COLLECTION_DIR` (default: `outputs/live_collection`) as `ignav_latest.json` and removes expired run files. `GET /api/v1/collection/live` and `GET /api/v1/collection/ignav` expose readiness, run counts, expiry, and the latest unexpired quotes. A deployment should mount the existing persistent quote volume if results need to survive container replacement.

The provider advertises 1,000 free successful requests as a one-time allowance; after that it lists $2 per 1,000 successful requests and no payment card to start. One full 150-search Vayu pass therefore uses about 15% of the initial allowance. Confirm current terms and pricing before a larger run.

## Limits for Vayu and CPI

Live fares change and are search-time quotes, not historical fares. The collector retains them for no more than three hours (two by default), records price verification status, and limits the full-basket request count. Do not use unverified values in metrics.

These provider economy fares cannot be assigned to the Vayu Saver, Standard, or Flexi classes from the returned fields. Ignav quotes are therefore diagnostic only and do not replace the synthetic prototype index. One live search pass also cannot establish monthly CPI correlation or deviation; that requires a time series of complete basket collections, reviewed fare-class mapping, sufficient overlapping months, and the packaged official MoSPI CPI reference series.

The supplied frontend files remain unchanged. The backend-injected bridge puts verified Ignav fare averages into the route table when available and labels those rows as live; historical index and CPI measures continue to use their own eligible backend series.

## Provider references

- [Signup and API-key flow](https://ignav.com/signup)
- [Quickstart](https://ignav.com/docs/quickstart)
- [One-way fare-search fields](https://ignav.com/docs/one-way)
- [India market and INR](https://ignav.com/docs/markets)
- [Price verification and response fields](https://ignav.com/docs/response-format)
- [Pricing](https://ignav.com/pricing)
- [FAQ and freshness guidance](https://ignav.com/docs/faq)
