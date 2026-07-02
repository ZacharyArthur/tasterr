# Tasterr — Product Requirements Document

**Status:** Founding blueprint, frozen 2026-07-01

> **Frozen founding blueprint.** This document captures the founding product design.
> Once implementation begins, `openspec/specs/` is the living source of truth for
> current behavior; this file is historical rationale and is **not updated**.
> Process and workflow rules live in [AGENTS.md](../AGENTS.md).
**Reference implementation:** [janpuc/browserr](https://github.com/janpuc/browserr), a
working Next.js implementation of the same product category. Tasterr is a clean rebuild,
not a fork; browserr is consulted for UX patterns, API-shape ideas, and lessons learned,
never copied wholesale.

---

## 1. Summary

Tasterr is a self-hosted, Netflix-style discovery front-end for a household media stack
(TMDB catalog + Seerr for library status and requests). It answers *"what can I watch?"*
with a cinematic browse experience — rotating hero billboards, genre and per-service rails,
and recommendations that **learn per person**.

The one-line differentiator vs. browserr: **every household member logs in with their Seerr
identity and gets their own taste profile, their own recommendations, and requests attributed
to them.**

The name follows the `*arr`/Seerr convention: Seerr requests it, **Tasterr** picks it.

## 2. Why rebuild instead of continuing the browserr fork

- **Ownership & understanding** — a codebase authored end-to-end, every decision deliberate.
- **Stack control** — Python backend (FastAPI) instead of a Next.js monolith; a hard
  client/server boundary instead of RSC blending.
- **Feature divergence** — multi-user identity, per-user recommendations, and Plex-aware
  features diverge far enough from upstream that the fork relationship is a liability.

**Guiding values (in priority order):** best practice, KISS, maintainable code. When a feature
and simplicity conflict, simplicity wins or the feature waits.

## 3. Users

| Persona | Description | Needs |
|---|---|---|
| Household member | Signs into Seerr with **Plex** (primary) or a local Seerr account (secondary). Browses on desktop, tablet, phone, or TV. | "Show me something *I'd* like, tell me where it streams, one click to request it." |
| Admin | Runs the media stack (Seerr, Plex, *arr, Cloudflare tunnel). Is a Seerr admin. | Zero-drama deployment, secrets never in a GUI or DB, control over region/services/rails. |

Deployment reality: primarily LAN, but may be exposed to the internet through a Cloudflare
tunnel (as the household Seerr already is). **Security is a hard requirement, not a nice-to-have.**

## 4. Goals

1. **Per-user discovery.** Each user has a taste profile that seeds from their own Seerr
   request history and shifts as they browse. Recommendations are explainable
   ("Why am I seeing this?") and resettable.
2. **Netflix-grade browse UX.** Full-bleed rotating hero, lazy horizontal rails, rich detail
   view (trailer, cast, seasons, where-to-watch), search. Dark-first, responsive
   desktop → tablet → mobile → 10-foot, keyboard/remote navigable, reduced-motion honored.
3. **Seerr-native identity.** No parallel account system. Login is delegated to Seerr
   (Plex OAuth primary, local Seerr credentials secondary). Seerr admins are Tasterr admins.
4. **Requests as the real user.** Requests go through the user's own Seerr session, so Seerr
   enforces per-user quotas/permissions/auto-approval and attribution is correct.
5. **Region & service aware.** One admin-set region and service list for the household;
   catalog and rails derive from it. Personalization happens *within* that shared catalog.
6. **Trivial to operate.** One Docker image (amd64 + arm64), one SQLite file, secrets via env
   only, drops into an existing `docker-compose` stack beside Seerr.

## 5. Non-goals

- **Direct playback.** Tasterr discovers and hands off (deep links, not a player).
- **Writing watch history back** to Plex/media servers.
- **Native mobile apps** (responsive web / PWA-ready only).
- **Per-user regions or service lists** (global, admin-set; revisit only if a real need appears).
- **Managing users.** Seerr owns accounts, passwords, and permissions; Tasterr only mirrors.
- **Telemetry.** None, ever. The app talks only to TMDB, Seerr, and Plex.

## 6. Features & phasing

### v1.0 — Lean core (first usable release)

| Feature | Notes |
|---|---|
| Sign in with Plex | Plex OAuth PIN flow → token validated against Seerr `/auth/plex` → Tasterr session. |
| Sign in with Seerr account | Email + password forwarded to Seerr `/auth/local`. Secondary path. |
| Home feed | Rotating hero + composed rails (trending, genres, per-service, "recommended for you"), infinite scroll. |
| Detail view | Poster/backdrop, trailer, cast, seasons, where-to-watch, availability badge, request button. |
| Search | Multi-search (movie + TV) with availability badges. |
| Availability badges | Live library status from Seerr; degrades to "Unknown" if Seerr is down. |
| Request as user | Proxied through the user's Seerr session; Seerr enforces quotas/permissions. Redirect-to-Seerr fallback. |
| Per-user taste engine | Weighted, time-decayed signals → sparse TMDB-metadata feature vectors → cosine scoring with popularity prior, availability boost, and diversity. Same proven design as browserr, per-user. |
| Cold start | Seed the profile from the user's Seerr request history at first login. |
| In-app signals | Detail-open (weak +), request (strong +), in-app watchlist (+), not-interested / hide (−). |
| "Why am I seeing this?" | Per-title explainer derived from the feature overlap. |
| Reset taste profile | Per-user, self-service. |
| Admin settings | Region, service selection, rail toggles, appearance. Gated to Seerr admins. Secrets are **not** here. |
| Docker image | Single multi-stage image, amd64 + arm64, GHCR via Actions. |

### v1.x — Fast follows

| Feature | Notes |
|---|---|
| Play-in-Plex deep link | If a title is in the library, detail view shows **Play** → deep link to Plex web/app. Handoff, not playback. |
| Onboarding taste picker | Skippable "pick a few titles you like" for users with thin Seerr history (esp. local accounts). |

### v2 — Plex-aware personalization

| Feature | Notes |
|---|---|
| Plex watch-history signals | Real watched-it signals via the user's Plex token; powers genuine "Because you watched X". |
| Continue-watching rail | In-progress shows from Plex on the home screen. |
| Household blend rail | "Something for everyone tonight" — scored against selected users' combined profiles. |

**Rails are a system, not hardcoded:** every rail type (including continue-watching and
household blend) is individually admin-toggleable. New rail ideas land as new toggleable
rail types.

## 7. Key user stories

1. As a household member, I open Tasterr on the TV, pick "Sign in with Plex", approve on my
   phone, and land on a home screen that already reflects my Seerr request history.
2. As a household member, I browse rails; things I open, request, or hide visibly reshape
   "Recommended for you" over the following days — and I can ask any title "why am I seeing this?"
3. As a household member, I request a title in one click and it appears in Seerr as *my*
   request, subject to *my* quota.
4. As an admin, I deploy Tasterr with a compose snippet and four env vars, and nothing about
   my TMDB/Seerr keys is ever visible in a browser, an API response, or the database.
5. As an admin, I toggle off the "continue watching" rail for the household without touching env or restarting.

## 8. Success criteria

- Household members use Tasterr (not Seerr's discover tab, not Netflix's row-surfing) to
  decide what to watch.
- A brand-new user's home feed is noticeably *theirs* within one session (cold-start seed)
  and improves within a week of light browsing (signals).
- Requests made in Tasterr are indistinguishable in Seerr from requests made in Seerr.
- Fresh deploy from compose file to browsing in under 5 minutes.
- The maintainer (a party of one) can return after 6 months away and re-orient within an hour
  — enforced by the KISS bar, typed code, and tests.

## 9. Risks & mitigations

| Risk | Mitigation |
|---|---|
| Seerr has no stable public API contract; auth endpoints could change. | Isolate all Seerr calls in one client module with contract tests against a live instance; pin known-good Seerr versions in docs. |
| Holding per-user Seerr sessions adds state & expiry handling. | Plex users: re-auth silently with the stored Plex token. Local users: prompt re-login on expiry. Degrade reads to "Unknown" availability, never block browsing. |
| Internet exposure via Cloudflare tunnel. | Real session security (HTTP-only cookies, CSRF origin checks, rate limiting), secrets env-only, admin gating — specified in SPEC §Security. |
| TMDB terms: attribution required, non-commercial API tier. | TMDB attribution in the footer/about; personal self-hosted use fits the free tier. |
| Solo-project scope creep. | The phasing table above is the contract. v1.0 ships before any v1.x work starts. |

## 10. Open items

- [ ] Confirm the Seerr instance version and its exact auth endpoint behavior before M1 (SPEC milestone plan).
- [ ] Decide GitHub repo visibility (public like browserr fork, or private).
- [ ] Logo/wordmark (nice-to-have; not blocking anything).
