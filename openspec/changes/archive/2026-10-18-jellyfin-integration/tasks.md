# Tasks: jellyfin-integration

The gate is per change: this change is one branch and one PR. Work the tasks in
order; a task is done when its code and named tests are written, and the final task's
checks must pass before the PR.

## 1. Settings and client

- [x] 1.1 `settings.py`: `JELLYFIN_INTERNAL_URL` (http/https with a host; embedded
      credentials rejected, with a regression test that the MediaBrowser header
      survives), `JELLYFIN_API_KEY`, `JELLYFIN_ALLOW_EMPTY_PASSWORD` (bool, default false),
      `jellyfin_configured`; nothing added to
      `PublicConfig`.
      Tests: partial config off; PublicConfig and `/auth/methods` regressions.
- [x] 1.2 `clients/jellyfin.py`: authenticate, logout token, user record, played
      movies/episodes pages via `/Items?userId=`, batched series lookup; header-only auth, timeouts,
      no redirects, typed models. Tests with mocked transport: shapes, errors,
      key never in URL.
- [x] 1.3 Opt-in live Jellyfin contract test (excluded from `just check`):
      auth + logout, user policy, played queries, series provider ids; with
      disposable accounts, an empty-password user, lockout after repeated
      failures, and a deleted user's record read (404); two users signing in back to back
      with the shared `DeviceId` both succeed when one token is logged out; records the Jellyfin
      version.

## 2. Sign-in and linking

- [x] 2.1 `POST /auth/jellyfin` + `/auth/methods` `jellyfin`. Tests: success
      links by id and logs the token out, a failed logout still signs in, generic 401, empty password refused
      before any Jellyfin call unless `JELLYFIN_ALLOW_EMPTY_PASSWORD`, same rule
      for Jellyfin and Seerr-via-Jellyfin linking, 503 unconfigured, works
      without Seerr/Plex, rate limit and same-origin.
- [x] 2.2 Seerr auto-link via Seerr's Jellyfin login; extend the live Seerr
      contract test for that endpoint, including the status Seerr
      returns when Jellyfin or Plex login is disabled (must classify as a
      refusal, not an outage). Tests: links, refusal doesn't block, outage
      blocks only a would-be new user.
- [x] 2.3 `auth/login.py`: Jellyfin admin check and display priority (no
      avatar). Tests: admin grant, deleted Jellyfin user
      (404) demoted, disabled Jellyfin admin demoted, priority, initials.
- [x] 2.4 `api/account.py`: Jellyfin link (503 while Jellyfin is unconfigured);
      it reuses the sign-in authenticate-and-logout helper;
      Seerr `jellyfin` method, offered and accepted only while Jellyfin is
      configured (503 otherwise). Tests per scenario, including that linking
      logs the Jellyfin token out.

## 3. History

- [x] 3.1 `recommend/signals.py`: `watched_jellyfin` (+2.5, server-recorded,
      unique, strong positive). Migration `0008` with downgrade; the `record_signal` conflict
      predicates in `recommend/store.py` change with the index. Jellyfin unlink
      deletes `watched_jellyfin` when asked. Tests: client
      rejection, unique index, existing watchlist and toggle writes still upsert,
      unlink history option, downgrade (a Jellyfin-only user with signals is
      removed with no orphan rows and an empty `foreign_key_check`).
- [x] 3.2 Shared latest-watch upsert parameterized by kind (refactor of the Plex
      writer). Existing Plex tests stay green.
- [x] 3.3 Jellyfin sync task: trigger, throttle, wait on Seerr sync, bounds,
      mapping (episodes → series), watermark rules; reset integration. Tests:
      first/incremental windows, episode collapse, unmapped skip, missing play
      date skip, deadline,
      outage, reset cancellation, Jellyfin unlink with `delete_history` during an
      in-flight sync writes nothing afterward, account deletion cancels it, a
      Home read during Jellyfin unlink schedules nothing, and a signal-less user
      is `pending` while a Jellyfin sync runs.
- [x] 3.4 `rails/registry.py` and the source-kind check in `recommend/service.py`:
      "Because You Watched" for `watched_jellyfin`. Test.
      Scoring excludes `watched_jellyfin` titles from recommended-for-you (via
      the strong-positive set). Test.

## 4. Frontend

- [x] 4.1 Regenerate `api.gen.ts`.
- [x] 4.2 `Login.tsx`: "Continue with Jellyfin" pill + expanding form; a 409
      shows the conflict guidance as the other forms do. Vitest, including the
      session-transition rules (query cache reset, late callbacks ignored) for
      Jellyfin sign-in.
- [x] 4.3 `Account.tsx` and the `RequestButton.tsx` "Connect Seerr" dialog:
      Jellyfin card; both Seerr link forms offer the Jellyfin method. Vitest.

## 5. Docs

- [x] 5.1 `.env.example`, `docs/CONFIGURATION.md` (required by `test_docs.py`),
      README Jellyfin setup (creating an API key), with a warning that exposing
      Tasterr exposes Jellyfin password sign-in: local-network rules don't
      apply, lockout is bounded only by the login bucket, and passwordless
      accounts need `JELLYFIN_ALLOW_EMPTY_PASSWORD`.
- [x] 5.2 `docs/SECURITY.md`: Jellyfin outbound-HTTP checklist entries; extend
      the auth checklist line "Credentials are forwarded to Seerr, never stored"
      to Jellyfin. Release checklist: the live Jellyfin contract tests pass and
      the tested Jellyfin version is recorded. `docs/RELEASING.md` §5 runs the live Jellyfin
      contracts alongside Seerr and Plex. `docs/ARCHITECTURE.md`: Jellyfin
      sign-in and history sync. `docs/CONFIGURATION.md` rollback: migration
      `0008` downgrade removes Jellyfin data and Jellyfin-only users.

## 6. Gate

- [x] 6.1 `just check`, `just e2e`, and `just container-smoke` pass inside the
      devcontainer (the PR gate runs all three); fix any failures.
