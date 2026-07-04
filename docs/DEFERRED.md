# Deferred work

Known gaps consciously postponed, with where they land. Living document —
remove entries when they ship.

| Item | Why deferred | Lands with |
|---|---|---|
| Automated container smoke test in CI (build image, curl `/api/v1/health`, assert non-root + healthy) | Belongs beside the image-publish workflow; until then the manual pre-tag verification stands (see release checklist in docs/SECURITY.md) | M6 hardening/release |
| Branch-protection enforcement of the gate ("PR blocked on `just check`") | No GitHub remote exists yet; nothing enforceable in-repo | GitHub setup |
| starlette TestClient → httpx2 migration (currently a deprecation warning under pytest) | Upstream transition, non-failing today | dependency-bump chore |
| `static_dir` default is a CWD-relative path | Container sets an absolute `STATIC_DIR`; only affects non-container runs, which are not a supported workflow yet | M1, if local uvicorn runs become supported |
| `container-deploy` spec wording — "example SHALL show Tasterr beside Seerr" vs. the commented-out Seerr service | Wording/reality mismatch is deliberate (see docs/IGNORED.md); soften the spec text in the next change touching that spec | M1 or next container change |
| Mechanical "response models never import secret settings" enforcement (frozen SPEC §11's second contract) | PublicConfig — the only settings-shaped response model in M0 — is covered by its regression tests; the broader class needs enforcement once more response models exist | M1 (first secret-adjacent response models) |
| OpenAPI type-freshness check in the gate (`just types` then diff) | m0-scaffold design.md deferred staleness automation (KISS); frontend typecheck catches breaking drift at call sites | M1 |
| Compose startup + volume persistence test | Rides with the container smoke-test work | M6 hardening/release |
| Frontend rendering against a real running backend (Playwright e2e smoke) | Already planned by SPEC §11's testing pyramid | M6 hardening/release |
