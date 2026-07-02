# Spike: Validate Seerr-delegated authentication

**Status:** Not started — **this is the first work item of the project, before M0 scaffolding.**
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

_To be filled in when the spike runs._

| # | Question | Result | Evidence / notes |
|---|---|---|---|
| 1 | Plex PIN flow | — | |
| 2 | Plex → Seerr login | — | |
| 3 | Local login | — | |
| 4 | Identity & admin | — | |
| 5 | Request as user | — | |
| 6 | Expiry & re-auth | — | |
| 7 | Seerr version | — | |
