## 1. Seerr settings detection

- [x] 1.1 Rename `SeerrRequestSettings` to `SeerrPublicSettings` in `clients/seerr.py`, add strict optional `mediaServerType`, `mediaServerLogin`, `localLogin` fields and a `SeerrLoginSupport` property (plex/jellyfin/local as `bool | None`, plus `media_server`); update callers. Verify with unit tests in `test_clients_seerr.py` covering Plex, Jellyfin, Emby, not-configured, login toggles off, missing fields, wrong types, and unrecognized type values.
- [x] 1.2 Add the cached `seerr_login_support` helper in `api/auth.py` (ttl 300 s, stale 3600 s, all-`None` when Seerr is unconfigured or unreachable) and invalidate its key on the Seerr connection test. Verify with API tests: one Seerr read across repeated calls, stale value served during an outage, all-`None` with no cache, refresh after a connection test.
- [x] 1.3 Add `mediaServerType`, `mediaServerLogin`, and `localLogin` to the e2e server's `/seerr/api/v1/settings/public` fixture and assert those fields in the Seerr live contract. Verify by running `just e2e`; the live test is collected under `-m live`.

## 2. Sign-in and linking honor known refusals

- [x] 2.1 Skip the Seerr Jellyfin auto-link in `jellyfin_login` and the Seerr Plex login in `poll_plex_pin` when the method is known refused, treating it as a Seerr refusal. Verify with tests: no Seerr login call, Jellyfin sign-in succeeds unlinked, Plex sign-in with `PLEX_SERVER_ID` succeeds, Plex sign-in without it returns 401, and unknown support still attempts the login.
- [x] 2.2 Apply the same rule to `poll_link_pin`'s Seerr admission fallback (403, no call). Verify with an account API test.
- [x] 2.3 Return 409 with the fixed message from `link_seerr` for a known-refused method before decrypting or forwarding anything; existing 503 checks run first. Verify with tests: no Seerr call, nothing stored, and the 503 order unchanged.
- [x] 2.4 Add `seerr_accepts` (three booleans, unknown → true) to `AccountResponse`. Verify with tests for Plex-backed, Jellyfin-backed, and unreadable settings, and an assertion that no other Seerr data appears.

## 3. Admin integration summary and connection tests

- [x] 3.1 Add admin-only `GET /api/v1/integrations` in `api/admin.py` with an explicit response model (seerr configured, media server, nullable login booleans, plex server pinned, jellyfin configured). Verify with tests: 403 for members with no Seerr call, 200 with unknown/null during an outage, and no URL, id, or name in the body.

- [x] 3.2 Add `public_info()` to `clients/jellyfin.py` (`GET /System/Info/Public`, no API key, strict minimal model). Verify with client tests that no token is in the `Authorization` header and bad shapes raise typed errors.
- [x] 3.3 Extend `ConnectionTarget` with `plex` and `jellyfin` and implement both tests in `api/admin.py` per the spec (admin's own link, ten-second Plex deadline, fixed details). Verify with API tests for each outcome: not configured, no link (no upstream call), Plex discovery empty, Plex refused, Jellyfin key read ok/refused, Jellyfin public-only reachable/unreachable, and no secret, URL, or name in any body.

## 4. Frontend

- [x] 4.1 Regenerate `api.gen.ts` from the backend schema and verify the frontend typecheck passes.
- [x] 4.2 Update `ConnectSeerr.tsx` to hide known-refused methods and render the guidance text (link Plex / ask for a Seerr local account / requests unavailable) under the rule below. The dialog opens on the local form when offered, otherwise the Jellyfin form; the toggle (and its `seerr-login-mode-label` captions) shows only when both are offered; "Use my Plex account" stays whenever the `plex` method is offered and the member has a usable Plex link, and guidance shows when there is no usable Plex action and no offered Jellyfin form, alongside the local form when local is offered. Verify with Vitest cases for Plex-backed with local on, local off with no Plex link, local refused with Jellyfin accepted (opens on the Jellyfin form, no toggle, Jellyfin caption), neither form offered with no usable Plex method (guidance only), Plex-backed with local off and a usable Plex link (Plex action only, no form or guidance), a Jellyfin-only member with Seerr accepting Plex and local (local form plus guidance, no Plex action), Seerr accepting Jellyfin while Tasterr's Jellyfin is unconfigured, local refused, and no usable Plex action (guidance only), and all-accepted for a member with a usable Plex link and Jellyfin configured, which keeps today's layout.
- [x] 4.3 Add **Test Plex** and **Test Jellyfin** buttons beside the existing two in Settings → Connections, with readable labels (not `toUpperCase()` of the id). Verify with a Vitest case that all four buttons render and show the returned detail.
- [x] 4.4 Add an admin "Seerr integration" block to Settings → Connections that renders the summary and derives the three fixed warnings; unknown values produce none. Verify with Vitest cases for each warning and the no-warning outage case.

## 5. Documentation

- [x] 5.1 Add a "Mixed setups" section to `docs/CONFIGURATION.md`: a feature → requirement matrix (including a Continue Watching row: Plex or Jellyfin link, merged when both), outcomes for common combinations (Plex + Plex-backed Seerr, Jellyfin + Jellyfin-backed Seerr, Plex + Jellyfin + Plex-backed Seerr, no Seerr), the Jellyfin-only-member request path, the five-minute detection lag, and a cross-reference from "Degraded modes". Verify the docs tests pass under `just check`.

## 6. Gate

- [x] 6.1 Before archiving, compare each MODIFIED block in `specs/` with the current `openspec/specs/` text (including the "Connect Seerr dialog names the active credentials" block from `seerr-login-mode-label`) and fold in anything a change archived since this one was written added. Verify with `openspec validate seerr-media-server-awareness --strict`.
- [x] 6.2 Run `just check` inside the devcontainer and fix any failures until it passes.
