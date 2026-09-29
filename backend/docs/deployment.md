# Deployment

The API and supplied dashboard can run from Docker Compose or from a container platform that builds the included `Dockerfile`. The image runs as a non-root user, keeps the application filesystem read-only, checks `/api/v1/health`, and stores live quote files in a persistent volume.

## Docker Compose

From the backend project directory:

```powershell
Copy-Item .env.example .env
docker compose config --quiet
docker compose up --build -d
```

Open `http://localhost:8000/`. The backend serves the provided dashboard pages with a runtime data bridge; the original HTML, CSS, and images are included unchanged. Check API readiness at `http://localhost:8000/api/v1/health`, see the CPI metrics at `/api/v1/cpi-comparison`, and see live-provider readiness at `/api/v1/collection/live`.

Compose binds the port to `127.0.0.1` by default for use behind a reverse proxy. Set `VAYU_BIND_ADDRESS=0.0.0.0` only when the host firewall and deployment platform are configured to expose the service directly. Set `VAYU_PUBLISH_PORT` if host port 8000 is already in use. For a separate frontend origin, set `VAYU_ALLOWED_ORIGINS` to a comma-separated list of exact origins; same-origin hosting needs no extra CORS origin.

The named `vayu-live-quotes` volume persists normalized quote artifacts across container replacement. The collectors enforce their configured short retention periods and the API removes expired artifacts. Keep this volume attached to the same deployment and include it in the operator's retention/back-up policy.

## Container platforms

Build from this directory using the included `Dockerfile`. Configure the platform to run the image's default command, provide its assigned `PORT` environment variable, and allow the process to bind to `0.0.0.0`. Configure a persistent disk at `/var/lib/vayu/live_collection` if live quotes should survive redeploys. Add the platform's public browser origin to `VAYU_ALLOWED_ORIGINS` when the frontend is hosted separately.

Never commit `.env`; use the platform's secret manager for provider credentials. The `.env.example` file documents every supported setting.

## Enable SerpApi Google Flights live prices

Sign up at [SerpApi](https://serpapi.com/google-flights-api) and store the resulting API key in the deployment's secret manager as `SERPAPI_API_KEY`. No partner approval or manual email verification barrier is required. Check planned searches and run bounded collections:

```powershell
docker compose exec vayu-api python scripts/run_live_serpapi_collection.py --dry-run
docker compose exec vayu-api python scripts/run_live_serpapi_collection.py --confirm-live --route DEL-BOM --max-searches 2
```

Inspect `/api/v1/collection/live` and `/api/v1/collection/serpapi` for collector readiness, unexpired quote counts, and provider price insights. Detailed parameters and budget ceilings are documented in [docs/live_collection_serpapi.md](live_collection_serpapi.md).

## Enable self-service Ignav live prices

Create an [Ignav account](https://ignav.com/signup), verify its email, and store the resulting API key in the deployment's secret manager as `IGNAV_API_KEY`. No partner-approval reference is needed. Review the provider terms and check your routes in its playground before collecting. The first command below is local planning only; the second deliberately limits collection to two DEL-BOM searches:

```powershell
docker compose exec vayu-api python scripts/run_live_ignav_collection.py --dry-run
docker compose exec vayu-api python scripts/run_live_ignav_collection.py --confirm-live --route DEL-BOM --max-searches 2
```

Only after reviewing that sample should an operator run the full 150-search basket with `--confirm-live`. Monitor `/api/v1/collection/live` for run state, coverage, verification counts, and quote expiry. The collector retains quotes for two hours by default and never more than three hours.

The previous Skyscanner connector remains available separately at `/api/v1/collection/skyscanner`; it still requires partner approval and the signed-agreement settings described in [its collection guide](live_collection_skyscanner.md).

## CPI comparison and publication status

`/api/v1/cpi-comparison` compares exact, complete monthly Vayu periods with the packaged MoSPI domestic-airfare CPI series. It exposes rebased levels, paired monthly changes, correlation, absolute gaps, directional agreement, and coverage exclusions. The comparison intentionally reports unavailable metrics until Vayu has complete overlapping monthly periods with at least 80% route-basket coverage. The CPI source file is a versioned deployment input; refresh it from an official MoSPI release, run the CPI processing/publication workflow, and rebuild the image to publish a newer benchmark snapshot.

This deployment serves a synthetic prototype snapshot. Real-time quotes are served separately by `/api/v1/collection/ignav` and remain diagnostic until fare-brand mapping, recurring collection, full pipeline processing, and production coverage/backtest gates are satisfied. Deploying the API does not certify the index as an official CPI or market index.
