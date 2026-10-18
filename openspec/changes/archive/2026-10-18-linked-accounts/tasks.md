# Tasks: linked-accounts

The gate is per change: this change is one branch and one PR. Work the tasks in
order; a task is done when its code and named tests are written, and the final task's
checks must pass before the PR.

## 1. Data model and migration

- [x] 1.1 `db/models.py`: add `LinkedAccount`; drop moved columns from `User` and
      `UserSession`. Migration `0007` per the app-database delta (Seerr links
      from `seerr_user_id` with display name, avatar, and `linked_at` from the user row, delete
      sessions, drop columns) with downgrade.
      One `db/migrate.py` helper runs a migration with `PRAGMA foreign_keys=OFF`
      before its transaction, `PRAGMA foreign_key_check` after, and enforcement
      back on; `upgrade_to_head`, the test helpers in `test_db_migrations.py`,
      and the Alembic CLI path in `env.py` all use it. Update the fixtures that
      build users or sessions with the moved columns.
      Tests (with the app engine's foreign keys on): upgrade from a `0006`
      fixture seeded with signals, profiles, and sessions keeps signals/profiles
      and leaves no sessions; downgrade round-trip keeps them too; a downgrade that removes a link-less
      user with signals leaves no orphan rows and an empty
      `foreign_key_check`; unique constraints reject duplicates. A deleted
      highest user id is never reused (AUTOINCREMENT). Alembic batch mode drops
      AUTOINCREMENT on rebuild, so the `users` rebuild passes
      `table_kwargs={"sqlite_autoincrement": True}`.

## 2. Sign-in and linking core

- [x] 2.1 `auth/login.py`: resolution order, Seerr auto-link, credential
      encryption on links, `IntegrityError` retry. Upstream calls never run inside a write
      transaction (resolution commit, then admin/display reads, then a short
      update + session mint). Tests: returning account,
      existing-member bridge via Seerr, new user, concurrent first sign-in,
      mismatched Seerr result discarded, cookie refresh, no auto-link after a
      Seerr unlink and manual link clearing the flag, Plex sign-in replaces the
      stored Plex token, concurrent Seerr-local +
      Plex bridge sign-ins converge on one user (full-resolution retry), Seerr
      outage refuses a would-be new user, bridged user with the provider
      already linked gets 409. `clients/seerr.py` login errors expose enough to
      tell an outage (transport, timeout, 502/503/504) from a refusal (any
      other status, including 500, a login that sets no session cookie, and an
      `/auth/me` follow-up with any status other than 200 or 502/503/504); test each. Plex sign-in reads the plex.tv
      account after the PIN claim; a failed read is the generic upstream error
      (test). Extend the opt-in live Seerr
      suite: `/auth/plex` refuses a Plex account with no access to Seerr's
      server, the session cookie's expiry is recorded, and the status for a
      disabled local login classifies as a refusal (each case skipped unless
      the test instance is set up for it).
- [x] 2.2 Admin derivation from all links (Seerr check), keep-previous when any
      check errors without a grant. `SeerrClient.user()` classifies per the
      spec: transport error, timeout, and 502/503/504 are an outage; any other
      status (404, 500), a malformed body, or an id mismatch completes without
      a grant. Callers in `api/request.py` and `api/destinations.py` keep
      treating both as an upstream error. Tests: grant, demote at next sign-in, total
      and partial outage keep the value,
      deleted upstream user (404) is demoted, a 500 demotes.
- [x] 2.3 Display identity Seerr → Plex; `PlexCloudAccount` parses `title` and
      `thumb`. Tests: priority and Plex-only fallback.
- [x] 2.4 `auth/sessions.py` and `api/auth.py`: sessions carry no upstream
      material; both sign-in routes call the resolver. Update existing auth tests;
      add one that the stored credential survives logout and unlink deletes it.

## 3. Callers read links

- [x] 3.1 `api/request.py` + `api/destinations.py`: cookie and Seerr id from the
      Seerr link; `re_auth_required` without a link; re-auth via the Plex link,
      persisting and retrying only when Seerr returns the linked account. Tests per
      ladder scenario, including the different-account no-retry case, and a
      member without a Seerr link gets unavailable destinations with no Seerr call.
- [x] 3.2 `api/home.py` + `api/taste.py`: Plex token and history timestamps from
      the Plex link; trigger runs for any user with a Plex link. Tests: sign-in
      method independence, no-link no-work.
- [x] 3.3 `recommend/seed.py` → incremental Seerr sync on the Seerr link
      (throttle, watermark, overlap, skip `request` titles); Plex waits on it.
      Tests: first sync, later-link import, overlap idempotence, skip, failure
      retry, a Home read schedules the Seerr sync (`api/home.py`) and a second
      within the six-hour throttle does not. `api/onboarding.py`: `pending` while any history sync is reserved or
      running; tests for Seerr pending, Plex-only pending, nothing running `show`.
      A user with signals is `done` even while a sync runs.
- [x] 3.4 `api/recommendations.py` reset: cancel and await both syncs, clear
      signals/profile/link timestamps, evaluate the Seerr then Plex triggers
      (no inline import); respond `204`. Update `frontend/src/lib/api.ts` for the
      empty response and the `Navbar.test.tsx` reset mock. Update reset tests; add a no-double-import test.

## 4. Account API

- [x] 4.1 `api/account.py`: `GET /account`; Plex PIN link; Seerr link (`plex`,
      `local`); unlink (cancel and await the provider sync first, atomic last-link
      check) with `delete_history`; account deletion with task cancellation;
      link PIN poll exempt from the login bucket. Linking requires the same admission
      as signing in with that account (Plex: Seerr accepts the token, and that
      Seerr login is discarded); a refused
      link is a generic 403 that stores nothing. Seerr `plex` method without a
      Plex link is 409. Dormant links: `GET /account`
      returns them with `available: false`, unlink works, and sync, Continue
      Watching, admin checks, and re-auth skip them. Add every mutation to the mutation-inventory
      regression. Tests: guards (401/403/429), owner scoping, conflict 409 is
      generic, unlink history option, unlink during an in-flight sync writes
      nothing afterward, a Home read during unlink or deletion schedules no
      new sync (scheduling guard), concurrent unlink of the last two links leaves one,
      unlink refused when the only other link's method is unconfigured,
      deletion cascade and server-side session invalidation without a cookie header
      (including delayed responses after a newer sign-in and sliding expiry),
      Plex unlink and account deletion clear the
      Continue Watching cache entry, wrong deletion confirmation is 422, wrong
      Seerr password on link is a generic 401, relinking the same account
      refreshes it in place, a sign-in PIN handle polled on the link poll (and
      the reverse) fails as unknown, Plex link admission creates no Seerr link
      or cookie, Seerr `plex` method without a Plex link, a new Plex link
      triggers the Plex sync and a new Seerr link the Seerr sync, a link PIN
      handle polled from another session fails as unknown, an admission check
      that hits an outage is the generic upstream error and stores nothing, a
      dormant link gets no sync or Continue Watching, and `GET /account` returns
      it with `available: false`.

## 5. Frontend

- [x] 5.1 Regenerate `api.gen.ts` (`just types`).
- [x] 5.2 `routes/Account.tsx` + `/account` route + avatar-menu entry: the
      avatar-menu button shows the user's initials (no avatar image), keeps the
      display name as its accessible name, and the open menu shows the name; connected
      account cards, unlink dialog with the history checkbox, disabled last
      unlink, conflict guidance, "no longer available on this server" card with Unlink for a
      dormant link, delete-account danger zone. Vitest for each.
- [x] 5.3 `RequestButton.tsx`: "Connect Seerr" dialog on `re_auth_required`,
      single retry with the same selection, cancel. Vitest.
- [x] 5.4 `routes/Login.tsx`: a 409 from the Plex poll or the Seerr form shows
      the server's conflict guidance instead of "try again", and polling stops.
      Vitest for both forms.

## 6. Docs

- [x] 6.1 `docs/SECURITY.md`: auth/session and database checklists reflect
      per-account encrypted credentials and proven-only links.
- [x] 6.2 Release-notes entry: one-time sign-in after upgrade.
- [x] 6.3 `docs/ARCHITECTURE.md` and the README feature summary ("Plex-backed
      sessions…"): rewrite the identity, session, and seed paragraphs (users and linked accounts, per-account credentials, the
      incremental Seerr sync, Plex sync for any Plex link), keeping the terms
      `test_docs.py` checks. `docs/CONFIGURATION.md` "Upgrade and rollback":
      migration `0007` signs everyone out, its downgrade deletes users without a
      Seerr link and every session, and an image-only rollback across it is
      unsupported.

## 7. Gate

- [x] 7.1 `just check`, `just e2e`, and `just container-smoke` pass inside the
      devcontainer (the PR gate runs all three); fix any failures.
