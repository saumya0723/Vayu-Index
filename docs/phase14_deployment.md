# Phase 14 API and Dashboard

For container/cloud deployment use [deployment.md](deployment.md). For a local run, install `requirements-phase14.txt`, run `python scripts/run_api.py --check`, then start the API with `python scripts/run_api.py --host 127.0.0.1 --port 8000`. The application also supports deployment-provided `PORT` and `VAYU_HOST` settings.

The supplied frontend is served at `/` and `/ui/`; `/dashboard` points to the same
frontend. The Phase 14 prototype dashboard remains at `/dashboard/phase14`. The
frontend's documented `/api/v1/index`, `/api/v1/routes`, `/api/v1/fares`,
`/api/v1/lead-time`, and `/api/v1/data-quality` endpoints return read-only
prototype data. The original frontend HTML and assets are included unchanged;
the backend injects a bridge at serve time to populate the existing pages and
wire their API console to the read-only endpoints.

Live prices use the self-service Ignav connector documented in
[live_collection_ignav.md](live_collection_ignav.md); the legacy Skyscanner
connector remains separately available in [live_collection_skyscanner.md](live_collection_skyscanner.md). CPI comparisons
use exact complete monthly periods and report insufficient coverage rather
than filling gaps or presenting prototype data as real observations.
