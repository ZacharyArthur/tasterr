## Why

The login screen offers every configured sign-in method ("Continue with Plex",
"Continue with Jellyfin", "Continue with Seerr"). A tester running the Jellyfin
build reported that this list confuses non-technical family members and asked
for a configurable list of authorized sign-in methods. Today the only way to
remove a method is to unconfigure its integration, which also switches off
linking, history, Continue Watching, and requests.

This advances the existing `user-auth` and `account-linking` capabilities.

## What Changes

- Admins choose which configured methods are **offered for sign-in**, using
  checkboxes in Settings. An optional `TASTERR_SIGN_IN_METHODS` JSON array
  overrides and locks the choice, and is the recovery path after a lockout.
- A method that isn't offered is hidden on the login screen, and its sign-in
  endpoints return the same generic 503 as an unconfigured method.
- "Configured" and "offered for sign-in" become separate concepts:
  - **Configured** still drives linking, dormancy, history, Continue Watching,
    and requests. A member can still link Plex for Continue Watching when only
    Jellyfin sign-in is offered.
  - **Offered for sign-in** drives the login screen, the sign-in endpoints, and
    the unlink rule ("you must keep another way to sign in").
- Saving is refused (409) when it would leave the saving admin with no offered
  method among their own links.
- Before saving, Settings shows how many members would have no way to sign in.
  Those members keep their current sessions, and their Account page warns them
  to link an offered method.

## Non-goals

- Reordering methods or choosing a default or primary method.
- Restyling the login screen.
- Per-member or per-role method rules.
- Controlling Seerr auto-link at Plex or Jellyfin sign-in. It still links Seerr
  even when Seerr email sign-in is not offered.
- Changing what the Connect Seerr dialog offers (linking is not sign-in).

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `user-auth`: `/auth/methods` and the sign-in endpoints honor the admin
  allowlist; "available for sign-in" is defined once.
- `account-linking`: the account summary separates configured from offered and
  reports `sign_in`; dormancy stays configuration-based; members with no offered
  method are warned.
- `app-settings`: a new runtime setting, environment lock, save guard, and
  stranded-member preview.

## Impact

- Backend: `runtime_settings.py`, `settings.py` (environment lock), `api/auth.py`
  (split configured vs offered, separate sign-in and link dependencies),
  `api/account.py` (summary flag, unlink rule), `api/admin.py` (counts, save
  guard).
- Frontend: `Login.tsx` (unchanged logic, still driven by `/auth/methods`),
  `Settings.tsx` (checkboxes, lock, preview), `Account.tsx` (warning), generated
  types.
- Docs: `docs/CONFIGURATION.md` (setting, environment variable, lockout
  recovery).
- No migration: the runtime document gains a defaulted field.
- Landing order: seerr-login-mode-label → tmdb-metadata-language →
  discovery-exclusions-everywhere → watch-history-window →
  jellyfin-continue-watching → sign-in-method-allowlist →
  seerr-media-server-awareness → trakt-watch-history. `trakt-watch-history`
  builds on this change's "Members view and manage their own linked accounts"
  text and adds the link-only `trakt` provider, which `sign_in_link_counts`
  ignores.
