## 1. Trusted proxy configuration

- [x] 1.1 Add env-only `TASTERR_FORWARDED_ALLOW_IPS` settings parsing with a
      loopback default, normalized literal IP/CIDR values, and fail-closed rejection
      of wildcard/hostname/URL/empty/malformed entries; add settings tests for every
      accepted and rejected form plus a PublicConfig/runtime-settings non-exposure
      regression.
- [x] 1.2 Pass the trusted-peer allowlist to the production Uvicorn entrypoint and
      add focused tests proving trusted forwarding controls the effective login IP
      and `Secure` cookie scheme while identical headers from an untrusted peer are
      ignored.
- [x] 1.3 Add the proxy setting and safe reverse-proxy guidance to `.env.example`;
      extend the placeholder/completeness regression so the example cannot omit it,
      contain wildcard trust, or acquire a live value.

## 2. Mutation rate limiting

- [x] 2.1 Add the bounded shared authenticated-mutation bucket (60 capacity,
      60/minute refill) and reusable FastAPI dependency keyed only by the
      server-derived user id; change the admin bucket to key by authenticated admin
      id and add tests for auth-before-spend, continuous refill, generic 429, key
      bounds, and no double-spend on admin routes.
- [x] 2.2 Apply the shared loose limiter to `POST /auth/logout`; test allowed logout,
      exhausted-bucket 429, no session revocation/cookie change on rejection, and
      unchanged same-origin/default-deny behavior.
- [x] 2.3 Apply the shared loose limiter to `POST /request`; test 429 occurs before
      Seerr/re-auth work, taste-signal recording, or database mutation while existing
      unavailable/down degradation still browses normally.
- [x] 2.4 Apply the shared loose limiter to `POST /signals`; test both record and
      retract reject with no row/profile change after exhaustion and retain CSRF,
      input-validation, and secret-free response behavior.
- [x] 2.5 Apply the shared loose limiter to `POST /recommendations/reset`; test an
      exhausted bucket preserves the caller's signals/profile/seed state and retains
      per-user reset and Seerr-down behavior when allowed.
- [x] 2.6 Pin the mutation inventory with focused exemption tests/comments: Plex PIN
      polling remains usable at its normal cadence through an opaque single-use
      handle, and read-only `POST /availability` spends no mutation capacity; fail a
      route-inventory regression if a future state-changing API omits CSRF or its
      designated limiter.

## 3. Real-backend browser smoke

- [x] 3.1 Add pinned `@playwright/test` as the sole new dev dependency, commit the
      lockfile update, configure Chromium/failure-only artifacts, and build a
      test-only Python supervisor that runs the normal compiled-SPA FastAPI app with
      a temporary SQLite database plus minimal local typed TMDB/Seerr doubles; add
      focused harness tests for readiness, invented fixtures, and cleanup.
- [x] 3.2 Implement one accessible-locator Playwright journey for local login, home
      render, detail open, and request success through the real backend; assert no
      live `.env`/network dependency and make failure output useful without recording
      placeholder credentials in traces.
- [x] 3.3 Add `just e2e` with deterministic build/start/run/cleanup behavior, install
      Chromium inside the devcontainer only, run the command there, and fix all
      harness or journey failures.

## 4. Container and Compose verification

- [x] 4.1 Update `docker-compose.yml` to use its managed default network while
      keeping the optional Seerr service commented and SQLite on the named volume;
      add an opt-in same-host external-network override, document its optional
      network variable in `.env.example`, and render both service/network/volume
      contracts without starting a second Seerr.
- [x] 4.2 Implement the cleanup-safe native container smoke and `just
      container-smoke`: build the production image, create an isolated managed
      network/project with placeholder configuration, assert healthy API + SPA +
      non-root uid, write a disposable SQLite marker, force-recreate the container,
      prove the marker persisted, and remove every test Docker resource on success
      or failure; run it inside the devcontainer and fix failures.
- [x] 4.3 Add deterministic static/regression checks for Dockerfile and smoke safety:
      non-root runtime, no secret build args, both lockfile-frozen build stages,
      placeholder-only smoke env, isolated names, and unconditional cleanup.

## 5. CI and GHCR delivery

- [x] 5.1 Pin every existing/new third-party action in `gate.yml` to a reviewed full
      commit SHA (with version comments), declare read-only default permissions, and
      add blocking jobs that invoke the checked-in `just e2e` and `just
      container-smoke`; add workflow contract tests for triggers, commands,
      permissions, and immutable pins.
- [x] 5.2 Add the least-privilege `image.yml` workflow: on `main` and stable `v*`
      pushes, run native container smoke before GHCR login, then Buildx/QEMU publish
      amd64+arm64 with main, immutable SHA, SemVer, and stable `latest` tags; extend
      workflow contract tests to reject PR publishing, mutable action refs, missing
      architectures, excessive permissions, or secret-bearing Docker build args.
- [x] 5.3 Set backend and private frontend package metadata to `1.0.0`, refresh only
      affected lock/generated metadata, and add a release-version regression tying
      package versions, the documented `v1.0.0` tag, and image-tag expectations
      together.

## 6. Operator, architecture, and security documentation

- [x] 6.1 Write root `README.md` and `docs/CONFIGURATION.md` with the v1.0 scope,
      existing-Seerr Compose quick start, every environment/Compose variable, secret
      generation, first boot, trusted proxy/HTTPS setup, degraded modes, named-volume
      backup/restore, upgrade/rollback, and troubleshooting; add/extend a docs
      completeness regression against the settings and env-example fields.
- [x] 6.2 Write `docs/ARCHITECTURE.md` covering the one-process layout, enforced
      `api/`/`clients/`/PublicConfig boundaries, auth/request/taste data flows,
      SQLite/migrations/cache/background work, generated OpenAPI types, and Seerr
      degradation; cross-link it from README without changing frozen PRD/SPEC.
- [x] 6.3 Add root `SECURITY.md` with the supported v1.0 line and GitHub private
      reporting policy; update `docs/SECURITY.md` with the trusted-proxy, public-repo,
      container/browser/release checks and keep the policy/threat-model distinction
      explicit.
- [x] 6.4 Write `docs/RELEASING.md` with the exact devcontainer commands and ordered
      security review, deterministic checks, audits, live contracts, OpenSpec
      archive, confirmed git/PR/merge, `v1.0.0` tag, GHCR manifest/fresh-install
      verification, release notes, and digest/database rollback procedure.
- [x] 6.5 Remove only fulfilled M6 rows from `docs/DEFERRED.md` and reconcile the
      Compose rationale in `docs/IGNORED.md`; retain data-dependent live history
      coverage or unrelated future work with its current rationale.

## 7. v1.0 security and release evidence

- [x] 7.1 Review the entire pre-v1.0 tree against every applicable endpoint,
      auth/session, outbound HTTP, frontend, database, dependency/build, logging, and
      public-release checklist item in `docs/SECURITY.md`; fix findings in their
      owning task with focused tests and record only redacted scope/outcomes.
- [x] 7.2 Run `just release-check` inside the devcontainer, fix every ordinary gate,
      Playwright, image, health, uid, cleanup, or persistence failure, and record the
      date/result in `docs/releases/v1.0.0.md`.
- [x] 7.3 Run `just audit`, resolve or explicitly risk-triage every backend/frontend
      advisory, verify lockfiles and placeholder-only examples, and record advisory
      ids/dispositions without copying secret-bearing command output.
- [x] 7.4 Run `just test-live` with operator-supplied Seerr coordinates and stored Plex
      token, require the mandatory auth/request/history contracts to pass, record the
      tested Seerr version and generic exercised/skipped cases, and keep all
      credentials, URLs, users, and requested titles out of the repository.
- [x] 7.5 Finalize `docs/releases/v1.0.0.md` with version/date, deterministic checks,
      audit disposition, full-tree security result, live version/cases, known
      limitations, and rollback basis; review it for prohibited tokens, cookies,
      household identities, viewing data, and live/internal URLs.

## 8. Quality gate

- [x] 8.1 Run `just check` inside the devcontainer and fix any failures.

## 9. Review corrections

- [x] 9.1 Make external Seerr networking entirely optional: keep the base Compose
      path URL-only, add and test the same-host override, and align operator docs,
      rationale, design, and delta specs with both supported topologies.
- [x] 9.2 Put invasive live-request cleanup on every post-create exit path, add a
      behavioral trusted-proxy CIDR regression, and remove the fulfilled M3 silent-
      re-auth deferral.
- [x] 9.3 Re-run strict OpenSpec validation plus the deterministic quality and
      release gates in the devcontainer; refresh generic release evidence if counts
      or outcomes change.
      Ensure a successful Playwright run cannot make a repeated gate lint generated
      reports or result artifacts.
- [x] 9.4 Pin the optional same-host Compose override's required-variable failure
      and record the required post-correction live-suite rerun before tagging.
