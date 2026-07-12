# Deferred work

Known gaps consciously postponed, with where they land. Living document —
remove entries when they ship.

| Item | Why deferred | Lands with |
|---|---|---|
| Automated container smoke test in CI (build image, curl `/api/v1/health`, assert non-root + healthy) | Belongs beside the image-publish workflow; until then the manual pre-tag verification stands (see release checklist in docs/SECURITY.md) | M6 hardening/release |
| Branch-protection enforcement of the gate ("PR blocked on `just check`") | No GitHub remote exists yet; nothing enforceable in-repo | GitHub setup |
| starlette TestClient → httpx2 migration (currently a deprecation warning under pytest) | Upstream transition, non-failing today | dependency-bump chore |
| `static_dir` default is a CWD-relative path | Container sets an absolute `STATIC_DIR`; only affects non-container runs, which are not a supported workflow yet | If local uvicorn runs ever become supported |
| `container-deploy` spec wording — "example SHALL show Tasterr beside Seerr" vs. the commented-out Seerr service | Wording/reality mismatch is deliberate (see docs/IGNORED.md); soften the spec text in the next change touching that spec | Next container change |
| Compose startup + volume persistence test | Rides with the container smoke-test work | M6 hardening/release |
| Frontend rendering against a real running backend (Playwright e2e smoke) | Already planned by SPEC §11's testing pyramid | M6 hardening/release |
| Per-user Seerr calls + silent re-auth with the stored Plex token | M3 scope by design (SPEC §4.3); M1 already persists everything it needs (`sessions.seerr_cookie`, Fernet-encrypted Plex token) but nothing reads them yet | M3 request-as-user |
| First live run of the `/auth/plex` stored-token contract test | Needs an operator-supplied `TASTERR_LIVE_PLEX_TOKEN`; the local-login live path passed against Seerr 3.3.0 (2026-07-04) | M3 (which builds on that call), and every release per the SECURITY.md checklist |
| Forwarded-header trust (`forwarded_allow_ips`) so rate limiting sees real client IPs behind the tunnel | Per-IP login buckets degrade to one shared bucket behind cloudflared — acceptable at household scale; deciding which proxies to trust is deployment hardening (the limiter now fails closed for new keys under key floods, so spoofed-header floods cannot reset existing state) | M6 hardening/release |
| Rate limiting on mutations beyond the login endpoints | SPEC §13 places the broad rate-limit pass at M6; M1 shipped the tight login-only bucket | M6 hardening/release |
| True region-scoping of the "Popular Movies" rail (region + service-filtered discover) | TMDB `watch_region`/`with_watch_providers` only take effect with an admin-selected service list; the M2 rail is labelled honestly ("Popular Movies") until that exists | M5 admin & settings |
| Richer where-to-watch — rent/buy/free/ad-supported provider categories (M2 shows streaming/flatrate only) | The detail "where/how to watch" section is reworked with Seerr availability, in-library status, and the request button; expanding categories first then reworking is churn | M3 Seerr integration |
| Full modal focus-trap (Tab cycling) + `inert` background | M2 ships Escape/close + focus-on-open/restore; the complete a11y/10-foot pass is scoped to M5 | M5 admin & polish |
| Navbar user-menu Escape/outside-click dismissal | The complete keyboard/a11y pass is scoped to M5 (SPEC §13); the menu is dismissible today via its toggle button | M5 admin & polish |
| Live multi-page request-history walk (the live contract test reads `skip=0` only) | Deeper pages need an operator account with >50 requests — data-dependent; the pagination walk, cap, and malformed-page bound are pinned by mocked unit tests | The release-checklist live run, once the account's history is deep enough |
