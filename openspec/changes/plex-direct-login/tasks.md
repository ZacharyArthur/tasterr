# Tasks: plex-direct-login

The gate is per change: this change is one branch and one PR. Work the tasks in
order; a task is done when its code and named tests are written, and the final task's
checks must pass before the PR.

## 1. Settings and discovery

- [ ] 1.1 `settings.py`: optional `PLEX_SERVER_ID` with format validator; keep it
      out of `PublicConfig`. Tests: valid, invalid, absent; PublicConfig
      regression still passes.
- [ ] 1.2 `clients/plex.py`: discovery keeps only the pinned resource when set.
      Tests: pinned among many, absent from resources (sync not
      complete, watermark unchanged), unset keeps four.

## 2. Sign-in gate

- [ ] 2.1 `api/auth.py`: per-method availability; Plex PIN admits by server
      membership when set, else by Seerr; Seerr auto-link best-effort when gated
      by server; gate reads the plex.tv resources list only (no PMS probing);
      generic 401/502/503. Tests for every gate-table row, linked account
      losing access, Seerr refusal with server gate admits, Seerr outage admits a linked account
      but refuses a would-be new user, offline PMS still admits.
- [ ] 2.2 `GET /auth/methods`: unauthenticated booleans. Tests: each config
      combination; response carries no URL/id/secret.
- [ ] 2.3 `auth/login.py`: Plex owner admin check from the resources list (no
      probing). For this check the resources read classifies per the admin rule: transport
      error, timeout, and 502/503/504 are an outage; any other status (401,
      500, a redirect) or a malformed body completes without a grant. Tests: owner admin without Seerr, shared user not admin, an
      erroring check keeps the previous value; a revoked
      Plex token (401) or a 500 completes without a grant; a Seerr link while
      Seerr is unconfigured neither grants nor errors, so a former Seerr admin
      whose Plex check completes without a grant is demoted. Extend the live Plex suite to
      confirm a shared or Plex Home account sees the pinned server with
      `owned: false`.
- [ ] 2.4 `api/account.py`: Plex link requires server membership and Plex
      sign-in being available; without `PLEX_SERVER_ID`, Seerr must accept the
      token, and that Seerr login is discarded (no Seerr link or cookie);
      Seerr link requires the Seerr sign-in method available; otherwise
      503 (link creation only). `GET /account` uses the change-2 availability rule. Tests: refused link stores nothing;
      a dormant Seerr link (`PLEX_SERVER_ID` set, Seerr unconfigured) unlinks
      while Plex remains.
- [ ] 2.5 `auth/sessions.py` + cookie refresh: 90-day absolute cap from
      `created_at`; sliding never extends past it; cookie `Max-Age` capped to
      match. Tests: cap expiry deletes the row and 401s, sliding near the cap,
      cookie Max-Age near the cap.

## 3. Frontend

- [ ] 3.1 Regenerate `api.gen.ts`.
- [ ] 3.2 `routes/Login.tsx`: pill-button stack from `/auth/methods`, inline SVG
      marks, Seerr form expands in place, Plex popup flow unchanged. Vitest:
      only configured methods shown, expand/collapse, existing Plex flow tests
      still pass, including the 409 conflict guidance from `linked-accounts` 5.4.
      Update `frontend/e2e/smoke.spec.ts` to choose "Continue with Seerr" before
      filling the form.

## 4. Deploy and docs

- [ ] 4.1 `.env.example`, `docs/CONFIGURATION.md` (required by `test_docs.py`),
      `docker-compose.yml` comments, README: Seerr optional, `PLEX_SERVER_ID` and
      where to find it, and a warning that setting it removes Plex sign-in for
      members who can't see that server even if Seerr admitted them before.
      Note that pinning applies going forward: `watched_plex` rows already
      imported from other servers stay until cleared or reset.
      Warn that removing Seerr removes the bridge between sign-in methods:
      before unsetting it, members who sign in with Seerr email/password should
      link Plex (or Jellyfin) from `/account`, or their next sign-in creates a
      new, empty Tasterr account.
      Extend the container smoke test to boot a Plex-only env and assert
      `/auth/methods` reports `plex: true, seerr: false`.
- [ ] 4.2 `docs/SECURITY.md`: Plex connection checklist covers the pinned resource
      and the sign-in gate. `docs/ARCHITECTURE.md`: Plex sign-in without Seerr,
      the pinned server, and the 90-day session cap.

## 5. Gate

- [ ] 5.1 `just check`, `just e2e`, and `just container-smoke` pass inside the
      devcontainer (the PR gate runs all three); fix any failures.
