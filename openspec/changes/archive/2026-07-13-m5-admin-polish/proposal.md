## Why

M5 completes the PRD v1.0 product surface by replacing the remaining hard-coded
household preferences with a safe admin workflow and by making the browse
experience usable from a keyboard, reduced-motion environment, and 10-foot TV
layout. Earlier milestones deliberately left region/service awareness, rail
gating, appearance, and the full interaction audit for this milestone.

## What Changes

- Add an admin-only Settings route and typed BFF endpoints for reading and
  replacing global runtime preferences: region, selected streaming services,
  rail-type toggles, and a constrained appearance preset. Secrets and connection
  coordinates remain environment-only and never appear in the settings model or
  browser payloads.
- Add a small SQLite-backed runtime-settings store with code-owned defaults and
  atomic validation, plus admin-only TMDB region/service lookup and configured
  TMDB/Seerr connection tests.
- Resolve the configured region and selected services into catalog reads: detail
  certifications/providers use the household region, discovery rails are scoped
  to selected services when present, and selected services gain bounded
  per-service rails.
- Gate hero and rail provider types through the global admin toggles. Existing and
  newly introduced provider types default enabled, and a failing provider still
  degrades to fewer rails rather than a failed browse response.
- Extend recommendation availability scoring so titles on a selected household
  service can receive the existing subordinate availability boost alongside
  in-library titles, without making Seerr availability a browse dependency.
- Apply the selected appearance consistently across the authenticated shell using
  allowlisted theme/accent values, and refresh affected query data immediately
  after an admin saves.
- Complete the deferred accessibility and living-room polish: dialog focus trap
  and inert background, dismissible/focus-managed menus, visible focus states,
  keyboard/remote-friendly rail navigation and targets, semantic status/error
  feedback, and a full reduced-motion audit including auto-rotating content.
- Cover persistence, authorization, CSRF/rate limiting, outbound-client
  boundaries, secret scrubbing, settings-aware catalog/rail/recommendation
  behavior, and accessible frontend interactions with focused tests.

## Capabilities

### New Capabilities

None. M5 completes behavior already partitioned across the existing settings,
shell, catalog, browse, and recommendation capabilities.

### Modified Capabilities

- `app-settings`: Split environment-only deployment configuration from validated,
  DB-backed global runtime preferences and add the admin settings, discovery, and
  connection-test API contract without widening `PublicConfig` to secrets.
- `app-shell`: Add the admin-only Settings route, constrained household appearance,
  and shell-wide keyboard, focus, status, and reduced-motion behavior.
- `media-catalog`: Replace the fixed-region-only behavior with resolved household
  region/service context and typed, cached region/provider discovery through the
  TMDB client boundary.
- `media-browse`: Add service-aware and admin-toggleable feed composition and
  complete the modal, menu, rail, and 10-foot accessibility contract.
- `taste-recommendations`: Extend the availability boost to selected household
  streaming services while preserving similarity dominance and graceful
  degradation.

## Impact

- Backend: a settings migration/model/store/service, admin API router and response
  models, settings-aware dependencies, TMDB/Seerr client probes, TMDB region and
  provider wire models, catalog context, rail registry/composer, and recommendation
  availability inputs.
- Frontend: regenerated OpenAPI types, Settings route/form, shell appearance
  tokens, navbar/admin navigation, dialog/menu/rail focus behavior, reduced-motion
  handling, query invalidation, and responsive 10-foot styling.
- API: adds `GET /api/v1/regions`, `GET /api/v1/services`, `GET/PUT
  /api/v1/settings`, and `POST /api/v1/connection-test`; extends only explicit,
  secret-free browser models.
- Data: adds the non-secret `settings` table; no existing data is rewritten and
  absence of a row resolves to documented defaults.
- Dependencies: none planned. The existing FastAPI/Pydantic/SQLAlchemy/httpx and
  React/Tailwind/TanStack stack is sufficient.

## Non-goals

- Editing, revealing, or persisting TMDB/Seerr keys, internal URLs, session
  cookies, Plex tokens, or any other deployment secret in the GUI or database.
- Per-user regions, service lists, rail ordering, appearance, or administrator
  assignment; all M5 preferences are global and admin authority remains derived
  from Seerr at login.
- New request modes or changes to the established request-as-user flow; the
  server-provided Seerr redirect remains a failure fallback.
- Drag-and-drop rail ordering, arbitrary CSS/color input, custom themes, plugins,
  or a general-purpose configuration framework.
- Playwright E2E, release hardening, image publishing, deployment docs, or the
  broad mutation-rate-limit review reserved for M6. M5 hardens its own new
  mutations and verifies living-room behavior with focused tests and a manual
  check.
- v1.x/v2 work: Plex deep links, onboarding picker, Plex history,
  continue-watching, or household-blend rails.
