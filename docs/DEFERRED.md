# Deferred work

Known gaps consciously postponed, with where they land. Living document—remove
entries when they ship.

| Item | Why deferred | Lands with |
|---|---|---|
| Branch-protection enforcement of the gate ("PR blocked on `just check`") | No GitHub remote exists yet; nothing enforceable in-repo | GitHub setup |
| Starlette TestClient → httpx2 migration (currently a deprecation warning under pytest) | Upstream transition, non-failing today | dependency-bump chore |
| `static_dir` default is a CWD-relative path | Container sets an absolute `STATIC_DIR`; only affects non-container runs, which are not a supported workflow yet | If local uvicorn runs ever become supported |
| Richer where-to-watch—rent/buy/free/ad-supported provider categories (M2 shows streaming/flatrate only) | The detail "where/how to watch" section is reworked with Seerr availability, in-library status, and the request button; expanding categories first then reworking is churn | M3 Seerr integration |
| Browser-level long-detail modal scroll regression | jsdom cannot verify layout scrolling; the unchanged overlay scroll CSS and body-lock lifecycle have unit coverage | Browser interaction E2E expansion |
| Direct-detail Close then browser Back reopens the last detail | This is pre-existing history behavior outside the feedback fix; Close still returns Home as specified | Route-history UX polish, with a browser Back regression |
| Stable desktop scrollbar gutter while a modal is open | Locking body scroll can cause a small width shift; it is cosmetic and has not been reported by users | If layout shift is reported |
| Per-server Plex history watermarks | One global success timestamp plus a six-hour attempt throttle is sufficient at household scale; successful siblings may be reread after one server fails | If repeated multi-server failures materially omit history beyond the bounded newest-first cap |
| Plex JWT device-flow migration | The live gate proved current PIN-issued traditional tokens can perform every required read | A supported token can no longer satisfy the account/resource/PMS contracts |
| Persisted household groups or blend weights | Ephemeral caller-inclusive selection avoids durable social state and keeps privacy review bounded | Repeated household use demonstrates a concrete need |
