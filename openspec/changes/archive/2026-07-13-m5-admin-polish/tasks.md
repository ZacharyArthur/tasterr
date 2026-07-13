## 1. Runtime settings foundation

- [x] 1.1 Add Alembic revision `0004` and the SQLAlchemy `Setting` model for the
  empty `settings(key, value, updated_at)` table; add migration/model tests that
  cover upgrade, downgrade, primary-key behavior, and confirm no existing table
  or row is rewritten.
- [x] 1.2 Define the typed runtime document, appearance/rail enums, defaults, and
  server-owned rail descriptors with unit tests for region normalization,
  service-id uniqueness/bounds, enum rejection, full serialization, and the
  absence of every deployment-secret/URL/token field.
- [x] 1.3 Implement the one-row runtime settings store (default on absence,
  validated read, atomic full upsert, invalid-stored-value fallback) with async
  SQLite tests for default resolution, round-trip replacement, last-write-wins,
  invalid JSON fallback without value logging, and unchanged data after rejected
  input.
- [x] 1.4 Resolve runtime settings once through the request DB dependency and add
  allowlisted appearance to `PublicConfig`; extend meta/dependency and
  PublicConfig regression tests for authenticated/default/custom appearance,
  unauthenticated 401, request-consistent snapshots, and schema/value secret
  scrubbing with fully populated deployment settings.

## 2. Catalog clients and household context

- [x] 2.1 Extend the TMDB client with typed region/provider/probe operations,
  long-lived cache options, and selected-service discover parameters; add client
  tests for typed parsing, unknown-field dropping, OR-separated positive ids,
  flatrate semantics, region/media cache keys, fresh/stale/single-flight behavior,
  timeout/retry bounds, and generic cold failures.
- [x] 2.2 Add secret-free region/service domain models and catalog normalization
  for the movie/TV provider union; add pure tests for de-duplication, best display
  priority, stable ordering, logo/name mapping, and empty provider lists.
- [x] 2.3 Pass the resolved region/service ids into `CatalogService` and all
  discovery/detail/facts operations; add service tests proving configured/default
  region use, selected-service filtering, empty-selection omission, region-aware
  detail normalization, and cache reuse with distinct settings parameters.
- [x] 2.4 Add a configured Seerr connection probe within `clients/` and focused
  client tests for configured success, unconfigured/down/rejected generic failure,
  explicit timeout, typed parsing, and absence of credential/internal-URL data in
  returned values or exception text.

## 3. Admin BFF

- [x] 3.1 Implement `GET/PUT /api/v1/settings` with explicit models, `require_admin`,
  full-document replacement, same-origin protection, and a separate 30-per-minute
  admin-mutation bucket; add API tests for defaults/custom round-trip, rail
  descriptors, 401/403, validation 422 with no write, cross-origin 403, rate-limit
  429, and secret-free OpenAPI/response payloads.
- [x] 3.2 Implement admin-only `GET /api/v1/regions` and `GET /api/v1/services`
  over the catalog/client boundary; add API tests for successful typed output,
  case-normalized valid regions, invalid-region short-circuit, 401/403, generic
  unconfigured/down errors, and no upstream JSON/URL leakage.
- [x] 3.3 Implement rate-limited, same-origin `POST /api/v1/connection-test` with a
  target enum and generic result model; add API tests for TMDB/Seerr success,
  unconfigured/down/rejected results, invalid target, 401/403, CSRF, bucket
  exhaustion, and proof that ordinary browse endpoints remain unaffected.
- [x] 3.4 Register the admin router and bucket in the app factory and extend app
  boundary tests so every new route declares an explicit response model, only
  `clients/` imports httpx, deployment settings cannot enter the runtime store,
  and the existing admin-session cookie still slides on 403/error responses.

## 4. Settings-aware rails and recommendations

- [x] 4.1 Thread the same runtime snapshot through browse dependencies,
  `RailContext`, taste services, and background cold-start seeding; add dependency
  and service tests showing one request cannot mix settings versions and a
  background job uses its own resolved snapshot with safe defaults.
- [x] 4.2 Add stable `rail_type` metadata to every fixed/dynamic provider and gate
  hero/home/extra providers before fetching; extend registry/composer tests for
  default-enabled new types, disabled providers making zero calls, dynamic group
  gates, all-disabled empty feed, unaffected de-duplication/degradation, and
  filtering before cursor pagination.
- [x] 4.3 Add up to four independently degrading `New on {service}` providers from
  selected service metadata while applying all selected ids to ordinary
  discovery; add tests for selection order/cap, correct provider-specific query,
  under-filled omission, one failing service not dropping other rails, unavailable
  metadata omitting only service rails, and selected-service filtering of home and
  extra rails.
- [x] 4.4 Extend title facts and backward-compatible persisted feature records
  with watch region/flatrate provider ids, then combine selected-service and
  in-library availability into the scorer's single boolean; add catalog/store/
  scorer/service tests for same-detail reuse, old-record parsing, wrong-region
  lazy rebuild, selected-service ordering, no double boost, no-selection M4
  parity, and Seerr-Unknown degradation.
- [x] 4.5 Add API-level regression coverage that saving settings changes later
  home/rails/title behavior without restart (region, provider filtering, rail
  gates) while provider/TMDB/Seerr failures still return the specified partial or
  generic responses.

## 5. Generated contract and admin frontend

- [x] 5.1 Regenerate the OpenAPI schema/client with `just types`, add typed frontend
  API/query functions for config/settings/regions/services/probes, and extend
  fetch-wrapper tests for methods, query encoding, CSRF credentials, typed success,
  401/403/422/429, and generic failures.
- [x] 5.2 Add the admin-only `/settings` route, loading/forbidden/error states, and
  Navbar Settings entry; extend App/Navbar route tests so admins can navigate,
  non-admins neither see the link nor render protected data on a direct URL, and
  backend 403 remains authoritative.
- [x] 5.3 Build the region/service picker with accessible native controls and
  provider text/logo output; add component tests for region loading, service
  loading, clearing selections on region change, preserving admin order, bounded
  selection feedback, stale/error states, and keyboard/form labels.
- [x] 5.4 Build the sectioned Settings form for region/services, backend-provided
  rail toggles, named appearance presets, and configured connection probes; add
  component tests for draft initialization, complete save payload, disabled/pending
  states, validation/error/status announcements, probe outcomes, save success,
  and no secret/internal-URL input or display.
- [x] 5.5 On successful save, update/invalidate `config`, `settings`, `home`,
  `rails`, and title/detail queries and render a useful all-rails-disabled empty
  state; add TanStack/component tests proving appearance/feed changes apply
  without reload and only admins receive the Settings recovery link.

## 6. Appearance, accessibility, and living-room polish

- [x] 6.1 Replace fixed color usage with the bounded semantic theme/accent token
  palette and apply enum-to-attribute mappings at the authenticated shell; add
  frontend tests for default/custom appearance, cross-route/overlay/form token
  inheritance, allowlist-only mapping, readable status semantics, and no
  local/session-storage preference.
- [x] 6.2 Make the Navbar user menu dismiss on Escape and outside activation with
  correct menu semantics and focus restoration; extend Navbar tests for keyboard,
  outside pointer, tab order, expanded state, trigger focus, and visible accessible
  names/status text.
- [x] 6.3 Implement a reusable local detail focus trap and inert background
  lifecycle without a dependency; extend DetailModal/App tests for initial focus,
  forward/reverse Tab wrapping, Escape/close, route-driven cleanup, background
  inertness, and restoration to the opening card when present.
- [x] 6.4 Add labelled rail regions, Left/Right focus movement with scroll-into-view,
  consistent `focus-visible` styles, and living-room-sized controls/cards; add
  Rail/MediaCard tests for both directions, endpoints, focus retention, accessible
  labels, and the minimum-target/focus classes.
- [x] 6.5 Audit every JS/CSS auto-advance, transition, transform, animation, and
  programmatic scroll against `prefers-reduced-motion`; extend hero/menu/modal/rail
  tests to prove auto-rotation stops, navigation stays functional, and scrolling
  becomes instant without hiding loading or status information.

## 7. Verification and living documentation

- [x] 7.1 Remove the shipped M5 region-scope/focus-trap/menu entries from
  `docs/DEFERRED.md` and the now-obsolete unused-admin-gate entry from
  `docs/IGNORED.md`; confirm the frozen `docs/PRD.md` and `docs/SPEC.md` are
  unchanged.
- [x] 7.2 Run the authenticated Home, Search, Detail, and Settings paths manually
  at 1280x720 and 1920x1080 in both themes with keyboard-only navigation and
  reduced motion; fix any clipped content, lost focus, illegible contrast,
  precision-only target, unexpected motion, or unannounced status found.
- [x] 7.3 Run `just check` inside the devcontainer and fix every ruff, format,
  pyright, import-boundary, pytest, generated-type freshness, Biome, TypeScript,
  Vitest, and production-build failure.
