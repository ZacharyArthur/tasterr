## Why

`GET /api/v1/auth/plex/pin/{pin_id}` completes Plex login — it exchanges the Plex
token at Seerr, mints a Tasterr session, and emits `Set-Cookie: tasterr_session=…`.
Unlike every other mutating auth route, it carries **no same-origin guard**, because
the design leaned on the 256-bit unguessable handle to prevent *guessing a victim's*
handle.

That reasoning covers the wrong threat. The handle does not need to be guessed for a
**login-CSRF / session swap**: an attacker creates and approves their *own* Plex PIN,
learns the opaque handle their own login produced, and lures the victim's browser to
the completion URL. `Set-Cookie` is honored on a cross-site response regardless of
`Sec-Fetch-Site` (SameSite governs when cookies are *sent*, not when they are
*stored*), so the attacker's session overwrites the victim's existing Tasterr cookie.
Subsequent requests — watch history, taste signals, request-as-user — then run as,
and are visible through, the attacker's account.

This was reproduced hermetically against the existing fake Plex/Seerr harness: a
victim with an established `Victim` session is hit cross-site
(`Sec-Fetch-Site: cross-site`) on an attacker-approved handle. The poll returns 200,
fires the Seerr login, mints an `Attacker` session row, sets `tasterr_session` for
it, and `/auth/me` then resolves to `Attacker`. Severity is **medium**: it requires
the victim to visit an attacker-controlled link (no full account takeover, no data
exfiltration beyond what the attacker's own account already shows), but it silently
attributes the victim's household taste signals and requests to the attacker.

This change closes that hole and advances the **PRD/SPEC milestone "login endpoints
are hardened"** (user-auth spec) by extending the existing same-origin guard to the
one mutation that was missed.

## What Changes

- Replace the state-changing `GET /api/v1/auth/plex/pin/{pin_id}` with a fixed
  same-origin-protected `POST /api/v1/auth/plex/pin/poll` taking
  `{"pin_id": "<handle>"}` in the JSON body. The body keeps the opaque handle out
  of access-log URLs as a side benefit.
- The new POST is guarded by the existing `require_same_origin` dependency (no new
  dependency). It stays **exempt from the login rate limit** — polling fires every
  ~2s by design and is gated by the 256-bit unguessable, expiring, single-use
  handle plus the same-origin check.
- Remove the old GET completion behavior entirely; it can no longer mint a session.
- Preserve all existing properties: opaque ≥256-bit handles, 10-minute TTL,
  single-use atomic claim, concurrent-poll safety (synchronous `pop`), encrypted
  Plex token at rest, generic error bodies, exemption from the login bucket.
- Update the SPA polling client (`pollPlexPin`) to POST the handle, and regenerate
  the OpenAPI types (`api.gen.ts`).
- Update the mutation-inventory regression (`test_mutation_guards.py`) to assert
  the new POST carries `require_same_origin` and that no GET pins a session.
- Update the `user-auth` spec to describe the POST poll and its same-origin
  requirement.

## Capabilities

### Modified Capabilities

- `user-auth`: the Plex PIN poll endpoint changes from a state-changing
  path-parameter GET to a same-origin-protected `POST /auth/plex/pin/poll` with the
  handle in the body; the same-origin guard now covers it, and the old GET cannot
  mint a session.

## Impact

**Affected surfaces:** `backend/src/tasterr/api/auth.py` (route + handler),
`backend/tests/test_auth_api.py` (existing poll tests move to POST + new
CSRF regressions), `backend/tests/test_mutation_guards.py` (inventory + exemption
assertion), `frontend/src/lib/api.ts` (`pollPlexPin`), generated
`frontend/src/lib/api.gen.ts`, `openspec/specs/user-auth/spec.md`.

**Compatibility:** the SPA is the only client of the poll endpoint (no third-party
integrations; the route is browser-facing and pre-auth). The endpoint shape changes,
so any out-of-tree client polling the GET breaks loudly with 404 — acceptable for a
security fix on an unreleased-at-this-shape route.

**Risks:** none beyond a small API shape change. No new dependency, no schema
migration, no new cookie or pre-auth state.

## Non-goals

- No change to the PIN *creation* endpoint, local login, logout, session lifecycle,
  cookie attributes, or the `PinStore` handle mechanics — only the poll transport
  and its guard.
- No CSRF token / double-submit cookie: the existing `require_same_origin` (fetch
  metadata + Origin) plus the absence of CORS is the proven guard already used by
  every other mutation, and is demonstrably sufficient here.
- No change to the live Seerr contract suite (it exercises `/auth/plex` on Seerr,
  not Tasterr's poll endpoint).
- No rework of the broader auth surface, rate-limit strategy, or rate-limit buckets.
