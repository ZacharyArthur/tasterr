## 1. Backend: replace the GET poll with a same-origin POST

- [x] 1.1 In `backend/src/tasterr/api/auth.py`, add `PinPollRequest(BaseModel)`
  with `pin_id: str`; delete the `@router.get("/auth/plex/pin/{pin_id}")` route;
  add `@router.post("/auth/plex/pin/poll", dependencies=[Depends(require_same_origin)])`
  taking `payload: PinPollRequest` and otherwise identical handler logic (peek →
  poll → pop → login → mint → set-cookie), updating the local from the path param
  to `payload.pin_id` and the comment to explain the same-origin guard replaces
  the prior handle-only reliance while keeping the login-bucket exemption.

## 2. Backend: tests (existing + regressions)

- [x] 2.1 In `backend/tests/test_auth_api.py`, convert every existing poll call
  from `client.get(f"/api/v1/auth/plex/pin/{handle}")` to
  `client.post("/api/v1/auth/plex/pin/poll", json={"pin_id": handle})` so the
  happy-path, pending, single-use, expired, generic-404, encrypted-at-rest,
  concurrent-claim, rate-bucket-exempt, and seed-hook tests all exercise the new
  transport; keep all existing assertions (status codes, cookie presence/absence,
  generic bodies, single session row, schedule_seed fire-and-forget).
- [x] 2.2 Add a regression proving a cross-site poll (`Sec-Fetch-Site: cross-site`)
  is rejected **403 before** any Plex/Seerr call, before handle consumption, with
  no `Set-Cookie` and no session row created.
- [x] 2.3 Add a regression proving a victim's existing session survives the
  rejected cross-site poll unchanged (same cookie value, `/auth/me` still resolves
  to the victim identity, no attacker session row).
- [x] 2.4 Add a regression proving a mismatched `Origin` header is rejected 403
  with no upstream call and no cookie/session side effect.
- [x] 2.5 Add a regression proving a headerless non-browser POST still completes
  login (the guard's intentional behavior — CSRF is a browser attack), and that
  same-origin fetch metadata (`Sec-Fetch-Site: same-origin` / `none`) completes
  login while `same-site` is rejected.
- [x] 2.6 Add a regression proving the old `GET /api/v1/auth/plex/pin/{pin_id}`
  cannot mint a session: a 404 (no such route) is returned, no Seerr call fires,
  and no session row is created.
- [x] 2.7 Confirm the existing concurrent-successful-polls test still mints
  exactly one session under the POST transport (no change to `PinStore.pop`
  semantics — this is the existing test ported to POST).

## 3. Backend: mutation-inventory regression

- [x] 3.1 In `backend/tests/test_mutation_guards.py`, add
  `("POST", "/api/v1/auth/plex/pin/poll"): {"require_same_origin"}` to
  `EXPECTED_GUARDS` and remove the prior "GET poll has no same-origin guard"
  assertion, replacing it with an assertion that the old GET route is absent and
  the new POST carries `require_same_origin` but no rate-limit dependency.

## 4. Frontend: polling client + generated types

- [x] 4.1 In `frontend/src/lib/api.ts`, change `pollPlexPin(pinId)` to
  `postJson("/api/v1/auth/plex/pin/poll", { pin_id: pinId })`.
- [x] 4.2 Regenerate `frontend/src/lib/api.gen.ts` via `just types` and verify
  the new path/request-schema entries are present and the old GET path is gone.
- [x] 4.3 Update `frontend/src/routes/Login.test.tsx` so the stubbed poll route
  matches the POST URL and reads the `pin_id` from the request body; keep the
  pending→ok and expired→retry-message behaviors asserted.

## 5. Spec update

- [x] 5.1 Update `openspec/specs/user-auth/spec.md` "Plex PIN login flow" and
  "Login endpoints are hardened" requirements to describe the POST poll
  transport, the same-origin guard on it, and that the GET cannot mint a session;
  add scenarios for cross-site rejection and same-origin completion.

## 6. Quality gate

- [x] 6.1 Run `just check` inside the devcontainer and fix any failures; run
  `just e2e` to confirm the real-backend browser login journey still passes.
