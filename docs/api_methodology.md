# Phase 14 API Methodology

Phase 14 is a read-only publication layer. It validates a hard-coded CSV allowlist against SHA-256 hashes and exact headers, loads one immutable in-memory snapshot at startup, and exposes `/api/v1`. It does not invoke or reproduce Phases 6–13 computations. Responses disclose `SYNTHETIC_PROTOTYPE`, `NOT_OFFICIAL`, source hashes, upstream schema versions, and request IDs. Only GET, HEAD, and OPTIONS are permitted. Exports are generated in memory and never written to `outputs/`.
