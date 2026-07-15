# Deferred work

Known gaps consciously postponed, with where they land. Living document—remove
entries when they ship.

| Item | Why deferred | Lands with |
|---|---|---|
| Branch-protection enforcement of the gate ("PR blocked on `just check`") | No GitHub remote exists yet; nothing enforceable in-repo | GitHub setup |
| Starlette TestClient → httpx2 migration (currently a deprecation warning under pytest) | Upstream transition, non-failing today | dependency-bump chore |
| `static_dir` default is a CWD-relative path | Container sets an absolute `STATIC_DIR`; only affects non-container runs, which are not a supported workflow yet | If local uvicorn runs ever become supported |
| Richer where-to-watch—rent/buy/free/ad-supported provider categories (M2 shows streaming/flatrate only) | The detail "where/how to watch" section is reworked with Seerr availability, in-library status, and the request button; expanding categories first then reworking is churn | M3 Seerr integration |
