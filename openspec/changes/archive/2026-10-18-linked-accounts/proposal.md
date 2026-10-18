# Proposal: linked-accounts

## Why

A Tasterr user is currently a mirror of a Seerr user: `users.seerr_user_id` is
the identity, both sign-in paths log into Seerr, and Seerr decides who is admin.
Upstream credentials (Seerr cookie, Plex token) live on each Tasterr session, so
Plex features work only in a session that started with Plex sign-in. That makes
Seerr a hard dependency and blocks two community asks: households without Seerr
(GitHub #34) and Jellyfin watch history (GitHub #47).

This is the first of four changes (`linked-accounts` → `plex-direct-login` →
`jellyfin-integration` → `taste-source-preferences`). It makes users
Tasterr-owned and turns Seerr and Plex into **linked accounts**, without changing
what members see at sign-in. Seerr stays required for sign-in until
`plex-direct-login`. It advances the existing `user-auth`,
`plex-personalization`, `taste-recommendations`, and `media-requests`
capabilities.

## What Changes

- **Data model:** new `linked_accounts` table (`provider`, `external_id`, display
  name, avatar, Fernet-encrypted credential, sync timestamps). One link per
  provider per user; one user per provider account. `users` loses
  `seerr_user_id`, `auth_type`, and the `plex_history_*` columns; `sessions` loses
  `seerr_cookie` and `plex_token_enc`.
- **Per-account credentials:** the Plex token and Seerr cookie move from the
  session to the user's link, both encrypted. They survive logout and are
  deleted on unlink or account deletion. Plex history, Continue Watching, and
  silent Seerr re-auth work for any user with a Plex link, whichever method they
  signed in with.
- **Sign-in resolution:** (1) user already linked to the sign-in account →
  (2) user linked to the Seerr account this sign-in auto-linked → (3) new user.
  Step 2 carries existing members across the upgrade with no manual step.
- **Seerr auto-link:** every Plex sign-in logs into Seerr with the same token,
  linking it when unlinked and refreshing the stored cookie when it matches.
- **Admin:** any linked account can grant admin (Seerr ADMIN bit in this
  change), re-derived from all links at each sign-in; total upstream outage keeps
  the previous value.
- **Display identity:** Seerr → Plex priority, refreshed at sign-in; no override.
- **Seerr request history becomes an incremental sync** like Plex history
  (six-hour throttle, 24-hour overlap, skips titles already requested in
  Tasterr), replacing the one-time cold-start seed for signal-less users.
- **Reset** clears state and lets the normal syncs re-import in the background
  (no inline import, no double sync); its response becomes `204`.
- **`/account` page** for every member (avatar menu): connected accounts with
  link and unlink (Plex via PIN; Seerr via "Use my Plex account" or Seerr
  email/password), an unticked "also delete imported history" option on unlink,
  an unlinked Seerr account staying unlinked (auto-link skips it),
  unlinking blocked unless another link can still sign in, and self-service
  "Delete my Tasterr account".
- **Request control:** `re_auth_required` (no Seerr link, or a lapsed cookie
  without a Plex link to refresh it) opens an inline "Connect Seerr" dialog and
  retries the request once after linking.
- **Migration `0007`:** creates a Seerr link per existing user and deletes all
  sessions, so every member signs in once after upgrading. Signals, profiles,
  watchlists, and onboarding are kept. Downgrade supported.

## Capabilities

### New Capabilities

- `account-linking`: Tasterr-owned users, linked accounts, sign-in resolution,
  Seerr auto-link, admin and display derivation, account page, unlink, and
  account deletion.

### Modified Capabilities

- `user-auth`: Plex and local sign-in resolve users through links; upstream
  credentials live on links; "User records mirror Seerr identity" is removed.
- `app-database`: sync timestamps move to links; migration `0007`.
- `taste-recommendations`: incremental Seerr history sync replaces the cold-start
  seed; reset clears link timestamps; rails use linked-account capabilities.
- `taste-signals`: `seed_request_history` comes from the incremental sync;
  `watched_plex` tied to the Plex link.
- `taste-onboarding`: `pending` follows the Seerr history sync instead of the
  removed cold-start seed.
- `plex-personalization`: Plex reads, history sync, and Continue Watching use the
  Plex link's token instead of the session's.
- `media-requests`: requests use the Seerr link's cookie; the re-auth ladder keys
  on a Plex link; "Connect Seerr" dialog.
- `app-shell`: Account entry in the avatar menu for every user.
- `media-browse`: `re_auth_required` opens the "Connect Seerr" dialog instead of
  prompting a re-login.

## Impact

- **Backend:** `db/models.py` + migration `0007`; `db/migrate.py` (foreign keys off
  during migrations); `auth/login.py` (resolution,
  auto-link, admin, display), `auth/sessions.py` (no upstream material);
  `api/auth.py`; new `api/account.py`; `api/request.py`, `api/destinations.py`,
  `api/home.py`, `api/recommendations.py`, `api/taste.py` read links instead of
  session/user columns; `recommend/seed.py` becomes the incremental Seerr sync.
- **Frontend:** new `routes/Account.tsx`; avatar-menu entry in `Navbar.tsx`;
  "Connect Seerr" dialog in `RequestButton.tsx`; regenerated `api.gen.ts`.
- **Docs:** `docs/SECURITY.md` auth/session and database checklists updated for
  per-account credentials; release notes call out the one-time sign-in.
- **Operators:** every member must sign in once after upgrading.
- **No new dependency.**

## Non-goals

- Sign-in without Seerr, `PLEX_SERVER_ID`, and the new sign-in screen
  (`plex-direct-login`).
- Jellyfin anything (`jellyfin-integration`).
- Per-user taste-source toggles (`taste-source-preferences`); unlink's optional
  history deletion is the only source control here.
- Seerr API-key impersonation (`X-Api-User`): requests stay cookie-based, as in
  the founding design.
- Merging two Tasterr users, admin user management, and user-chosen display names.
- Re-deriving admin between sign-ins (a demoted admin stays admin until the next
  sign-in, as today).
