## Context

See proposal.md for motivation. Current state:

- `SeerrClient.request_settings()` already reads `GET /api/v1/settings/public`
  with the API key and a 5 s timeout, parsing only `enableSpecialEpisodes` and
  `partialRequestsEnabled` (`extra="ignore"`). Any failure raises
  `UpstreamUnavailable`. It is called uncached on season requests.
- The same response carries `mediaServerType` (1 Plex, 2 Jellyfin, 3 Emby,
  4 not configured), `mediaServerLogin`, and `localLogin` on Seerr 3.5.0. The
  local live harness asserts only the season-policy fields today
  (`tests/live/test_seerr_live.py:298-302`); task 1.3 adds the live-contract
  assertions for these three.
- Seerr auto-link runs in `api/auth.py` (`poll_plex_pin`, `jellyfin_login`).
  Manual links run in `api/account.py` (`link_seerr`, and `poll_link_pin` whose
  admission falls back to Seerr when `PLEX_SERVER_ID` is unset).
- `ConnectSeerr.tsx` is shared by the Account page and the request control. It
  shows Plex when the member has a Plex link, Jellyfin when Tasterr's Jellyfin
  is configured, and local always.
- Settings has a "Connections" section with connection tests.
- `app.state.seerr_cache` is the in-process Seerr cache; `Cache.cached` serves
  stale values within `ttl + stale` when a refresh raises `UpstreamUnavailable`.

## Goals / Non-Goals

**Goals:**
- One cached Seerr settings read feeds sign-in, linking, the account summary,
  and the admin summary.
- Unknown always means today's behavior; only a positive Seerr statement hides
  or skips anything.

**Non-Goals:**
- Changing the season-policy read path or its freshness.
- Detecting anything beyond media server type and the three login toggles.

## Decisions

1. **Extend the existing wire model, don't add a second read.** Rename
   `SeerrRequestSettings` to `SeerrPublicSettings` and add optional, strict
   fields `media_server_type: int | None`, `media_server_login: bool | None`,
   `local_login: bool | None`. Add a typed property returning a small frozen
   `SeerrLoginSupport(plex, jellyfin, local)` of `bool | None` plus a
   `media_server` literal (`plex|jellyfin|emby|none|unknown`). Rationale: one
   upstream contract and pure, network-free logic that unit-tests directly.
   Alternative: a separate client method and model for the same endpoint,
   rejected as two homes for one contract.

2. **Cached read in one API helper.** A helper next to `provider_available`
   (renamed `provider_configured` by `sign-in-method-allowlist`; use whichever
   name exists when this lands) in `api/auth.py` returns `SeerrLoginSupport` (all `None` when Seerr is
   unconfigured or the read fails), using a dedicated one-entry
   `seerr_settings_cache.cached` with `CacheOpts(ttl=300, stale=3600)` under
   one fixed key. This isolates the last good settings from per-title
   availability churn, preserving the bounded stale window. The call site catches
   `UpstreamUnavailable` and returns all-`None`. `api/account.py` already imports
   from `api/auth.py`; `api/admin.py` gains that import. The season-request path
   keeps its uncached call. The Seerr connection test invalidates the key, so an
   admin who just changed Seerr sees fresh values right away. Alternative:
   reading at boot only, rejected because Seerr can change at runtime and
   may be down at boot.

3. **Unknown means accepted.** Callers test `is not False`. The account summary
   collapses to plain booleans; only the admin summary exposes `null`, because
   admins need to tell "unknown" from "on".

4. **Skip, don't special-case.** At sign-in, a known-refused method simply sets
   the Seerr login result to "rejected" without calling Seerr, reusing existing
   branches: Jellyfin sign-in proceeds without a Seerr link; Plex sign-in with
   `PLEX_SERVER_ID` proceeds; Plex sign-in without it fails 401 exactly as a
   Seerr refusal does today. `poll_link_pin`'s Seerr admission fallback follows
   the same rule (403, no call), keeping "a link is a real way to sign in".

5. **Manual link refusal is explicit, not generic.** `link_seerr` returns 409
   "Seerr does not accept this sign-in method" before decrypting or forwarding
   anything. This describes server configuration, not an account, so it
   reveals nothing enumerable, and it lets the UI explain itself.

6. **Warnings are computed in the frontend from facts.** `GET /integrations`
   returns facts; Settings derives the fixed warning strings. Rationale: the
   strings are presentation, there are three rules, and Vitest covers them.
   Alternative: backend warning codes, rejected as an extra contract for no
   reuse.

7. **Guidance text is one component.** The "what can I do" text lives in
   `ConnectSeerr.tsx` so the Account page and request dialog stay identical, as
   the existing spec already requires.

8. **Plex and Jellyfin tests use the admin's own links.** Tasterr has no
   server-wide Plex credential, and the Jellyfin API key is used only for reads
   scoped to a linked user, so each test checks through the calling admin's
   link. Plex reuses `PlexMediaClient.account` and `discover_servers` (already
   pinned and bounded) under a ten-second deadline. Jellyfin reuses the
   key-scoped `user(id)` read. Without a Jellyfin link, it calls the
   unauthenticated `GET /System/Info/Public` without the key, which proves
   reachability but not the key, so the result is not ok and the detail says
   so. Alternative: allow one unscoped `GET /System/Info` read with the key, so
   no link is needed. Rejected because it would modify the same
   jellyfin-personalization client requirement that `jellyfin-continue-watching`
   also modifies, and would loosen the key-scoping rule for convenience. Fixed
   detail strings replace the generic "Connection failed" only for these
   setup-actionable cases; TMDB and Seerr tests are unchanged.

9. **Login screen untouched.** `/auth/methods` stays upstream-free by spec. A
   member who tries Seerr local sign-in on a Seerr with local login off still
   gets the existing generic 401.

## Risks / Trade-offs

- [A future Seerr renames or drops a field] → the field is missing, the method is
  unknown, and behavior returns to today's. A live-contract assertion on 3.5.0
  pins the names.
- [A wrong positive statement hides a working method] → only well-typed, present
  fields can refuse; the summary shows the detected values so admins can spot it.
- [Up to five minutes of lag after an admin changes Seerr] → acceptable for a
  household setting; the connection test refreshes immediately.
- [Seerr down with nothing cached adds one bounded (≤5 s) read to account loads
  and sign-ins] → only during an outage that already delays those Seerr-dependent
  paths; stale values cover outages after the first successful read.

## Migration Plan

No schema or configuration change. Image-only rollback is safe; the previous
image ignores the new response fields.

## Security considerations

- **Endpoints:** `GET /api/v1/integrations` uses the admin dependency
  (default-deny), explicit `response_model`, no input, no mutation (so no CSRF or
  mutation-inventory entry). `POST /connection-test` keeps its admin
  dependency, same-origin check, and admin bucket; the new targets are enum
  values validated by Pydantic. The Plex test decrypts only the caller's own
  token server-side and returns no account, server, or connection detail.
  `GET /account` gains three booleans. The 409 on
  `POST /account/links/seerr` keeps same-origin, mutation, and login buckets,
  and runs after them. Errors carry no upstream body or URL.
- **Auth & sessions:** strictly reduces credential forwarding. Jellyfin
  passwords and Plex tokens are no longer sent to a Seerr known to refuse them.
  Nothing new is stored or logged. `/auth/methods` is unchanged and remains
  upstream-free. Admin derivation and session rules are untouched.
- **Outbound HTTP (connection tests):** Plex reuses verified discovery with all
  its existing connection rules (plex.direct only, TLS verification, no
  redirects). The Jellyfin public-info call goes through `clients/jellyfin.py`
  with the validated base URL, timeout, and no redirects, never sends the API
  key, and parses only the fields it needs.
- **Outbound HTTP:** reuses an existing call against the validated
  `SEERR_INTERNAL_URL` with its timeout and redirect behavior. New fields are
  parsed strictly; unknown fields are still dropped. Caching bounds call volume
  from the session-gated account endpoint.
- **Secrets / PublicConfig:** members see only three booleans. Admins see the
  media server kind and booleans, with no URL, server name, or id. `PLEX_SERVER_ID`
  is reported only as set/unset. Nothing changes in `PublicConfig`.
- **Frontend:** guidance and warnings are fixed strings rendered as text; no
  upstream text is rendered.
- **Database, dependencies:** not applicable. No schema change, no new
  dependency.
