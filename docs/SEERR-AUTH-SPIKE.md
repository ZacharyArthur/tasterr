# Spike: Validate Seerr-delegated authentication

**Status:** ✅ Complete — run 2026-07-02 against Seerr **3.3.0** (`703faf9`). Outcome: **PASS**;
one deviation (invalid sessions return 403, not 401) amended into SPEC §4.3; local login
deferred to M1 contract tests. → Proceed to M0.
**Type:** Throwaway spike. The script is disposable; the *findings* recorded here are the deliverable.
**References:** [SPEC.md §4](./SPEC.md) (auth design), [PRD.md §9](./PRD.md) (risk table).

## Why this comes first

Tasterr's entire identity model rests on one external assumption: **Seerr's auth endpoints
(`/api/v1/auth/plex`, `/api/v1/auth/local`, `/api/v1/auth/me`) behave the way the SPEC
assumes.** These endpoints are what Seerr's own login page uses, but they are not a
documented, stable, public contract. Every downstream decision leans on them:

- **Login flows (M1)** — both the Plex PIN flow and local credential forwarding terminate in
  these endpoints.
- **Request-as-user (M3)** — depends on Seerr returning a usable session cookie at login and
  honoring it on `POST /request`.
- **Admin gating** — depends on `/auth/me` exposing a permissions field we can map to admin.
- **Silent re-auth for Plex users** — depends on a stored Plex token being re-submittable to
  `/auth/plex` after the Seerr session expires.

If any of these assumptions is wrong, the fix is a SPEC change — cheap now, expensive after
M1–M3 are built on top of it. That's the whole argument: **one evening with a 50-line script
against the real Seerr instance buys certainty for three milestones.**

## What the spike must answer

Work through these in order; record the actual responses (status codes, response shapes,
cookie names/attributes) next to each item.

1. **Plex PIN flow** — Can we create a PIN at `plex.tv/api/v2/pins` with our own
   `X-Plex-Client-Identifier`/`X-Plex-Product`, have a user approve it at `app.plex.tv/auth`,
   and poll the PIN until it yields a Plex auth token?
2. **Plex → Seerr login** — Does `POST {SEERR}/api/v1/auth/plex` with that token return the
   user object and set a session cookie? What is the cookie's name, lifetime, and attributes?
3. **Local login** — Does `POST {SEERR}/api/v1/auth/local` with email+password behave the
   same way for a local account?
4. **Identity & admin detection** — Does `GET /api/v1/auth/me` (with the session cookie)
   return a stable user id and a permissions value from which admin can be derived? Record the
   exact field and the admin bit/value.
5. **Request as user** — Does `POST /api/v1/request` with the session cookie create a request
   attributed to that user in the Seerr UI, with the user's own quotas/auto-approve applied?
6. **Session expiry & re-auth** — What does Seerr return once the session is invalid (401?
   403? redirect?), and does re-submitting the *same stored Plex token* to `/auth/plex` mint a
   fresh session without user interaction?
7. **Version pin** — Record the exact Seerr version tested. This becomes the "known good"
   version in the SPEC's contract-test docs.

## Exit criteria

- **Pass:** All seven questions answered with evidence pasted into the Findings section below;
  SPEC §4 confirmed or amended to match reality. → Proceed to M0.
- **Fail (partial):** Some flow behaves differently — amend SPEC §4 accordingly (e.g., if
  request-as-user is unreliable, the fallback ladder is: redirect-to-Seerr for requests, or
  admin-key requests with degraded attribution). Then proceed to M0.
- **Fail (fundamental):** Auth delegation isn't viable at all → back to the drawing board on
  identity (profile-picker + PIN model) *before any code exists that assumes otherwise*.

## How (sketch, not prescription)

A single throwaway Python script (httpx, ~50 lines) run from a machine that can reach the
Seerr instance. Interactive: prints the Plex auth URL, waits for approval, then walks steps
2–6 printing raw responses. No error handling beyond what the investigation needs, no tests,
not committed to the repo — only this document's Findings section survives.

## Non-goals

- Writing any production auth code (that's M1, informed by this).
- Testing Jellyfin/Emby auth paths (out of scope for Tasterr entirely).
- Benchmarking or hardening — correctness of assumptions only.

## Findings

Run 2026-07-02, LAN URL, Plex-backed admin account. All values redacted per SECURITY.md.

| # | Question | Result | Evidence / notes |
|---|---|---|---|
| 1 | Plex PIN flow | **PASS** | `POST plex.tv/api/v2/pins?strong=true` → 201 with pin id + code; user approves at `app.plex.tv/auth#?clientID=…&code=…`; polling the pin returns the auth token. Fresh `X-Plex-Client-Identifier` per run appears as a new device in Plex settings — production must persist one stable identifier. |
| 2 | Plex → Seerr login | **PASS** | `POST /api/v1/auth/plex {authToken}` → 200 with full user object; `Set-Cookie: connect.sid=…; Path=/; HttpOnly; SameSite=Lax`, **30-day expiry**. No `Secure` flag over plain http (expected; our own session cookie handles that side). |
| 3 | Local login | **DEFERRED** | Skipped (no local-account credentials supplied at run time). Same response shape expected; validate via M1 live contract tests before building the local path UI. |
| 4 | Identity & admin | **PASS** | `GET /api/v1/auth/me` → stable `id`, `plexId`, `plexUsername`, `displayName`, `email`, and `permissions` int bitmask. Admin = bit 2 set (`permissions & 2`); observed `permissions=2` on the owner account (user id 1 = owner). Quota fields (`movieQuotaLimit` etc.) also present here. |
| 5 | Request as user | **PASS** | `POST /api/v1/request {"mediaType":"movie","mediaId":<tmdbId>}` with only the session cookie → 201. `requestedBy.id` matched the logged-in user. Request landed already approved (`status: 2`) — admin auto-approve applied server-side, confirming Seerr enforces per-user rules. Cleanup `DELETE /api/v1/request/{id}` → 204. Note: request id and `media.id` are distinct entities. |
| 6 | Expiry & re-auth | **PASS, with deviation** | Invalid session → **403** `{"status":403,"error":"You do not have permission to access this endpoint"}` — **not 401** as SPEC §4.3 assumed (§4.3 amended). Caveat: 403 is also Seerr's genuine permission-denied response, so re-auth at most once, then surface the error. Re-POSTing the *same stored Plex token* to `/auth/plex` → 200 + fresh `connect.sid`: silent re-auth confirmed. |
| 7 | Seerr version | **3.3.0** | `GET /api/v1/status` (unauthenticated) → `{"version":"3.3.0","commitTag":"703faf9…"}`. This is the pinned known-good version for contract tests. |
