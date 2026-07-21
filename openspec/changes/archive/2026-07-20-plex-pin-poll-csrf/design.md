## Context

The Plex PIN flow is two endpoints in `backend/src/tasterr/api/auth.py`:

1. `POST /api/v1/auth/plex/pin` — creates a plex.tv PIN, stores an opaque handle
   → plex.tv PIN id in the in-process `PinStore`, returns `{pin_id, auth_url}`.
   Gated by `require_same_origin` + `login_rate_limit`.
2. `GET /api/v1/auth/plex/pin/{pin_id}` — polls. Peeks the handle, calls
   `plex.poll_pin`; on a claimed PIN it pops the handle, calls `seerr.login_plex`,
   runs `complete_login`, sets the session cookie, returns `{status:"ok", user}`.
   **Not** gated by `require_same_origin` — the gap this change closes.

The frontend (`Login.tsx`) drives the poll with a 2s `refetchInterval` via
`pollPlexPin(pinId)` in `api.ts`, a plain `GET` to the path-param URL.

The same-origin guard (`require_same_origin` in `auth/deps.py`) already protects
every other mutation: `Sec-Fetch-Site` `same-origin`/`none` pass, `same-site`/
`cross-site` reject 403, falling back to a full `Origin` (scheme+host+port)
comparison when fetch metadata is absent; headerless non-browser clients pass
(CSRF is a browser attack). `SameSite=Lax` on the session cookie is the
independent second layer for *sending* cookies.

## Goals & non-goals

- Close the login-CSRF / session-swap hole with the smallest robust change.
- Keep opaque, expiring, single-use handles and concurrent-poll safety intact.
- Keep the poll exempt from the tight login bucket (it polls every ~2s by design).
- No new dependency, no pre-auth cookie, no schema change.
- Move the opaque handle out of access-log URLs as a side benefit.

## The fix: POST + same-origin, fixed URL

Replace the GET with:

```
POST /api/v1/auth/plex/pin/poll
Content-Type: application/json

{"pin_id": "<opaque-handle>"}
```

guarded by `dependencies=[Depends(require_same_origin)]` and **not** by
`login_rate_limit` (the polling cadence is legitimate; the 256-bit unguessable
expiring single-use handle plus the same-origin check are its protection).

The handler body is unchanged: `ctx.pins.get(pin_id)` → `ctx.plex.poll_pin` →
`ctx.pins.pop(pin_id)` (atomic single-use claim) → `ctx.seerr.login_plex` →
`complete_login` → `_set_cookie`. Pending returns `{status:"pending"}` with no
cookie; all error bodies stay generic (`PIN_NOT_FOUND`, `UPSTREAM_DOWN`,
`"Sign-in failed"`).

The request body is a Pydantic model (`PinPollRequest{pin_id: str}`) — no raw
passthrough, matching the existing `LocalLoginRequest` convention.

## Why POST + existing origin guard is sufficient

The same-origin guard is already the proven CSRF defense for every other
Tasterr mutation (logout, requests, signals, settings, local login, PIN
creation). It is sufficient here because:

1. **A cross-site `<form>` POST** (the classic CSRF vector that defeats
   SameSite=Lax *storing* because it is a top-level navigation) sends
   `Sec-Fetch-Site: cross-site`, which `require_same_origin` rejects 403
   before any upstream call, handle consumption, or cookie change. (SameSite=Lax
   would *send* the victim's cookie on the top-level GET redirect; the POST guard
   is what blocks the swap.)
2. **A cross-site `fetch(..., {credentials:"include"})` with a JSON body** would
   not send `Sec-Fetch-Site: same-origin`, and would require a CORS preflight
   (custom header / JSON content type) that the backend — which serves no CORS
   headers at all — never answers, so the browser blocks it before it fires.
3. **A same-site GET redirect to the old URL** cannot synthesize a same-origin
   POST with `Content-Type: application/json` and a body — and there is no longer
   a GET that mints a session.

No double-submit token or pre-auth cookie is needed: the guard is the same one
already trusted for the rest of the auth surface, and the same-origin invariant
is mechanically enforced by `test_mutation_guards.py`.

## What changes in each file

- `backend/src/tasterr/api/auth.py`
  - Add `class PinPollRequest(BaseModel): pin_id: str`.
  - Delete the `@router.get("/auth/plex/pin/{pin_id}")` route.
  - Add `@router.post("/auth/plex/pin/poll", dependencies=[Depends(require_same_origin)])`
    taking `payload: PinPollRequest`; rename the local from `pin_id` (path) to
    `payload.pin_id`. Comment updated to explain the same-origin guard replaces
    the prior handle-only reliance and that the login bucket is still exempt.
- `frontend/src/lib/api.ts`
  - `pollPlexPin(pinId)` → `postJson("/api/v1/auth/plex/pin/poll", { pin_id: pinId })`.
- `frontend/src/lib/api.gen.ts`
  - Regenerated via `just types` (path entries + the new request schema).
- `backend/tests/test_auth_api.py`
  - Switch every existing poll call from `client.get(f".../pin/{handle}")` to
    `client.post("/api/v1/auth/plex/pin/poll", json={"pin_id": handle})`.
  - Add a focused block of regressions (see tasks).
- `backend/tests/test_mutation_guards.py`
  - `EXPECTED_GUARDS` gains `("POST", "/api/v1/auth/plex/pin/poll"): {"require_same_origin"}`.
  - The exemption test now asserts the old GET route **no longer exists** (the
    inventory test would otherwise keep passing on a stale GET).
- `openspec/specs/user-auth/spec.md`
  - Rewrite the "Plex PIN login flow" requirement and the "Login endpoints are
    hardened" requirement to describe the POST poll, the same-origin guard, and
    that the GET cannot mint a session.

## Concurrency and ordering invariants preserved

- `PinStore.pop` is synchronous, so two overlapping successful polls cannot
  interleave between awaits: exactly one wins the handle, the other gets the
  generic 404. Unchanged.
- The single-use claim (`pop`) happens **before** the Seerr exchange, so a
  Seerr-side failure on the winning poll still consumes the handle (retry would
  hit `PIN_NOT_FOUND`). Unchanged.
- Pending polls never touch the cookie or the DB. Unchanged.

## Security considerations

Walked the relevant `docs/SECURITY.md` checklists:

**Any new or changed API endpoint**

- *Auth dependency present / default-deny:* the poll is intentionally
  unauthenticated — it is the pre-auth step that *produces* a session, and it
  cannot work without an opaque handle the caller can only have obtained from
  their own `POST /auth/plex/pin`. Justified.
- *Mutations: CSRF origin check + rate limit:* **CSRF origin check now applied**
  (`require_same_origin`). The tight login rate limit is deliberately exempt and
  justified: the SPA polls every ~2s, the handle is 256-bit unguessable + 10-min
  TTL + single-use, and the same-origin check defeats the CSRF vector. The
  exemption is pinned by `test_mutation_guards.py`.
- *Input validated through Pydantic:* `PinPollRequest{pin_id: str}` — no raw
  passthrough.
- *Explicit `response_model`:* `-> PinPollResponse` (unchanged).
- *Errors carry no stack/internal/upstream bodies:* unchanged — generic
  `PIN_NOT_FOUND`, `UPSTREAM_DOWN`, `"Sign-in failed"`.
- *Logs carry no tokens/cookies/PII:* unchanged — only `user_id` on success.
- *Mutation inventory:* the new POST is added to `EXPECTED_GUARDS`; the
  removed GET is asserted absent.

**Auth & session code**

- Credentials/tokens never stored or logged — unchanged.
- Fresh session token on every login (no fixation) — unchanged
  (`complete_login` → `mint_session` → `secrets.token_urlsafe(32)`).
- Cookie flags `HttpOnly`/`SameSite=Lax`/`Secure`-behind-HTTPS — unchanged.
- Failures generic, no enumeration — unchanged.
- The swap vector itself is closed: a cross-site poll is now 403 before any
  Seerr call, handle consumption, cookie change, or session creation.

**Outbound HTTP (`clients/`)** — no change; the poll still calls
`plex.poll_pin` and `seerr.login_plex` through the typed `clients/` layer with
timeouts and no header forwarding.

**Frontend** — the handle was already never put in client-visible storage; it
now also leaves the URL path. The POST uses `credentials: same-origin` (default
for same-origin `fetch`).

**Database & migrations** — none.

**Dependencies & build** — none added.

**Residual risk:** the cross-site `<form>` POST defense depends on browsers
sending `Sec-Fetch-Site`. Every modern browser does; the `Origin` fallback covers
browsers with fetch metadata disabled. A browser that sent *neither* header would
fall back to the `SameSite=Lax` *send* rule, which would not attach the victim's
cookie to a cross-site POST — so the swap still cannot complete. No known
residual exploitation path.
