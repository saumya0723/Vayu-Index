# Live airfare collection: Skyscanner Flights Live Prices

The backend includes an opt-in connector for Skyscanner's Flights Live Prices API. It uses the provider's documented `create` / `poll` workflow, the locked 15-route basket, both travel directions, economy cabin, INR, and the five configured advance-purchase windows. A full basket run plans 150 searches. Only direct-flight economy quotes are kept in the live observation output.

Skyscanner documents live search results from its airline and inventory partners. Access to the Travel API requires application review and a commercial agreement. The backend therefore makes no live request unless partner access, the API key, explicit authorization, a recent terms review, the agreement hash, and the agreement's retention period are configured.

## Configure partner access

1. Apply for the [Skyscanner Travel API](https://www.partners.skyscanner.net/product/travel-api) and obtain partner approval and a key.
2. Review the signed agreement and current API terms. Set the `VAYU_SKYSCANNER_*` values in your process environment using the `.env.example` field names. Store the API key in a secret manager or private environment variable.
3. Set `VAYU_SKYSCANNER_AUTHORIZED=true` only after the review and approval are complete. Do not invent an authorization reference or retention period.
4. Review the plan without making any request:

   ```powershell
   python scripts/run_live_skyscanner_collection.py --dry-run
   ```

5. Start a confirmed collection after checking API costs and partner limits:

   ```powershell
   python scripts/run_live_skyscanner_collection.py --confirm-live
   ```

   To limit an initial collection:

   ```powershell
   python scripts/run_live_skyscanner_collection.py --confirm-live --route DEL-BOM --max-searches 2
   ```

The latest normalized quote set is written to `outputs/live_collection/skyscanner_latest.json`; each run also receives its own JSON file. API keys and raw provider responses are not written to those files. The responses include a SHA-256 fingerprint for provenance. Quotes are tagged with provider, agent, flight, travel date, lead time, completion state, and fare-class mapping status. `VAYU_SKYSCANNER_MAX_HTTP_REQUESTS` caps create and poll calls combined; the collector stops and records a partial run when it reaches that cap. The API hides quotes at expiry, and the backend removes expired files during startup and periodic cleanup using the configured agreement retention.

## Fare-class and index handoff

Provider brand labels are not presumed to match Vayu's locked `Economy Saver`, `Economy Standard`, and `Economy Flexi` categories. The default `config/phase13_fare_class_mappings.json` leaves Skyscanner unmapped, so collected quotes remain diagnostic until a reviewed mapping is supplied. Live provider quotes are not silently blended into the synthetic snapshot or its published index.

A production Vayu series still requires recurring real observations, a validated fare-class mapping, all required processing stages, adequate basket coverage, and the existing production gates. The CPI comparison only pairs exact complete months with at least 80% locked-basket coverage. No interpolation or synthetic replacement is used.

The packaged domestic-airfare CPI item series currently ends in July 2026. The dashboard reports that snapshot period; it does not substitute the newer general CPI release for the airfare-specific benchmark.

## API endpoints

- `GET /api/v1/collection/skyscanner` — legacy partner-connector readiness and latest run/quotes.
- `GET /api/v1/cpi-comparison` — exact-month CPI comparison, thresholds, coverage exclusions, and paired series.

## Source references

- [Skyscanner Flights Live Prices API](https://developers.skyscanner.net/api/flights-live-pricing)
- [Skyscanner Live Prices overview](https://developers.skyscanner.net/docs/flights-live-prices/overview)
- [Skyscanner API authentication](https://developers.skyscanner.net/docs/getting-started/authentication)
