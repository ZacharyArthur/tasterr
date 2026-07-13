## Context

M0-M4 intentionally left four household-wide values hard-coded: the catalog
region is `US`, discovery has no watch-provider filter, every registered rail is
composed, and the SPA uses fixed dark neutral colors. `PublicConfig` currently
contains only integration-configured booleans, the database has no `settings`
table, and `require_admin` is implemented but has no production route to guard.

The browse UI already has useful accessibility pieces (semantic buttons, Escape
to close detail, focus-on-open/restore, a reduced-motion hook for hero rotation),
but not a complete interaction model. The modal does not trap focus or make its
background inert, the user menu has no Escape/outside-click handling, and rail
navigation assumes pointer or touch input. M5 must finish these seams without
turning a single-process household application into a configuration platform.

The predecessor was consulted for UX shapes: a sectioned settings form, a
region-derived service picker, constrained appearance choices, and bounded
service rails. Its secrets-in-settings, env/DB override layers, per-user rail
preferences, diagnostics export, and broader feature switches are not carried
forward because they conflict with Tasterr's env-only secret boundary and KISS
scope.

## Goals / Non-Goals

**Goals:**

- Give Seerr-derived admins one global, validated settings surface for region,
  selected streaming services, rail types, and appearance.
- Preserve the env-only deployment-settings and secret-scrubbing invariants.
- Thread an immutable settings snapshot through catalog, rails, and taste work so
  a request is internally consistent and saving requires no process restart.
- Make service-filtered discovery, bounded per-service rails, and the
  selected-service recommendation boost real while preserving independent
  degradation.
- Complete keyboard, focus, reduced-motion, responsive, and 10-foot behavior with
  focused automated coverage and a documented manual check.
- Add no production dependency.

**Non-Goals:**

- Per-user configuration, rail ordering, arbitrary theme values, secret editing,
  administrator management, request-mode switches, or a generic key/value API.
- Changing session/admin derivation, request-as-user semantics, or Seerr outage
  behavior.
- Background refreshers, cross-process cache invalidation, Redis, or another work
  queue. Settings traffic and household scale do not justify them.
- M6 E2E/release/security hardening or v1.x/v2 rail providers.

## Decisions

### 1. Persist one typed global runtime document

Add the frozen-blueprint `settings` table with `key` as the primary key, `value`
as JSON text, and `updated_at`. M5 owns one row, `global`. Its value is a Pydantic
`RuntimeSettings` document containing:

- `region`: an upper-cased two-letter country code, default `US`;
- `service_ids`: unique positive TMDB watch-provider ids in admin order, bounded
  to eight selections;
- `disabled_rail_types`: unique values from the server-owned `RailType` enum;
- `appearance`: an allowlisted `dark | light` theme and one of a small named
  accent-preset enum, defaulting to dark/crimson.

The store reads and validates the complete document. No row means the code-owned
defaults; the first successful save creates the row. Invalid stored JSON fails
closed to defaults and logs only that the global row was invalid. `PUT` replaces
the whole document atomically and returns the resolved value. Settings are rare,
there is one admin household, and last-write-wins is simpler than patch merging
or optimistic version negotiation.

This keeps the SQL table aligned with the founding data model while avoiding a
partially valid row per field. It also means a new optional setting can gain a
default without a data migration. A generic untyped value service was rejected:
it would move validation into callers and make secret persistence easier by
accident. Environment overrides and `LOCK_CONFIG` were rejected because the
blueprint deliberately splits deployment configuration from runtime preference
instead of layering them.

### 2. Keep deployment config and browser config as explicit allowlists

Rename the current conceptual boundary to `DeploymentSettings` in prose while
retaining the existing `Settings` Python type to avoid churn. It continues to
load only environment variables and continues to contain every connection and
secret value. `RuntimeSettings` lives in a separate backend settings module that
has no deployment-secret fields.

`PublicConfig` remains an explicit allowlist built from both sources. M5 adds only
the resolved `appearance` object; region, service selections, and rail toggles
are available from the admin-only settings response and are not needed by normal
browse clients. The public-config schema/value regression test is extended with
a fully populated deployment configuration and runtime document. The login page
keeps the default appearance because `/config` remains session-gated; the
authenticated shell applies the household appearance as soon as config resolves.

Returning the entire runtime document to every user was considered safe but
unnecessary. Keeping the projection narrow makes future privacy/security review
easier.

### 3. Expose one admin router with full replacement and typed probes

Add these explicit-response-model endpoints:

- `GET /api/v1/settings` returns the resolved document plus the server-owned rail
  type descriptors used to render toggles;
- `PUT /api/v1/settings` validates and atomically replaces the document;
- `GET /api/v1/regions` returns typed TMDB region options;
- `GET /api/v1/services?region=US` returns the movie/TV provider union for that
  validated region, de-duplicated by provider id and ordered by TMDB display
  priority;
- `POST /api/v1/connection-test` accepts only `target: tmdb | seerr` and returns a
  generic typed success/failure result for the already configured integration.

All five use `require_admin`. Both mutations use `require_same_origin` and a
separate loose in-process admin-mutation bucket (30 actions per client per minute)
so connection probes cannot become an unbounded outbound trigger. The target is
an enum, never a URL or credential. A connection failure is represented by a
normal, generic result rather than exposing upstream bodies, statuses, or URLs.

Service ids submitted on `PUT` are structurally validated but saving does not
call TMDB. This lets an admin still change appearance/toggles during a TMDB
outage. The UI clears services when region changes and sources choices from
`/services`; at use time, unavailable/stale provider metadata merely omits that
provider's named service rail. Positive integer ids remain safe discover query
values and cannot alter the outbound base URL.

Separate `/settings/region`-style endpoints and partial PATCH documents were
rejected because they create more contracts, merge behavior, and partial update
states without a household-scale benefit.

### 4. Resolve settings once per request, without a process-global settings cache

A `RuntimeSettings` dependency reads the single row using the request's existing
`AsyncSession`. FastAPI dependency caching gives every downstream dependency the
same immutable snapshot. `CatalogService` receives `region` and `service_ids` in
its constructor; `RailContext` additionally receives the disabled rail types.
Background taste seeding loads a snapshot in its own database session before
constructing its catalog/taste services.

The one indexed SQLite lookup is negligible beside catalog work. Avoiding an
in-memory settings singleton removes cache-invalidation races, test reset hooks,
and “save succeeded but another request saw old settings” behavior. TMDB cache
keys already contain request parameters, so changing region/providers naturally
uses distinct keys and old entries age out of the bounded cache.

### 5. Extend the TMDB client for regions, providers, and service filtering

Only `clients/tmdb.py` adds outbound operations. It gains typed wire models and
long-lived stale-on-error cache classes for `/watch/providers/regions` and
`/watch/providers/{movie|tv}`. The catalog layer normalizes these into
secret-free region/service options and unions movie/TV services.

Discover calls receive the request-scoped service ids. A non-empty selection is
serialized as TMDB's OR-separated `with_watch_providers` value together with
`with_watch_monetization_types=flatrate`; an empty selection omits both and means
all catalog titles in the region. Detail normalization and title facts select
certifications/watch providers for the configured region. Cache keys include
region and provider parameters.

The TMDB probe uses a small typed client operation against configured TMDB; the
Seerr probe similarly lives in `clients/seerr.py`. Both reuse the shared httpx
client, configured base URL/API key, explicit timeout, typed parsing, and existing
generic upstream exception vocabulary. API code never imports httpx or returns
wire JSON.

### 6. Give each provider a stable rail type and gate before fetching

`RailProvider` gains a stable `rail_type` separate from its instance `id`.
Fixed providers use types such as `trending`, `popular`, `recent`, `my-list`,
`recommended`, and `more-like`; dynamic instances share `genres`, `services`,
`top-rated`, or `decades`. `hero` is a feed-section type even though it is not a
returned `Rail` object. The backend exposes the enum and display labels in the
admin settings response, so frontend code does not duplicate the registry.

The composer removes disabled providers before starting their coroutines. That
both honors the setting and avoids unnecessary outbound work. Extra-rail
pagination filters the provider catalogue before slicing, keeping cursors stable
for a settings snapshot. An absent type in `disabled_rail_types` means enabled,
so existing and future registered types ship on by default. If all types are
disabled, the API returns a valid empty feed and the SPA renders a useful empty
state; there is no hidden mandatory rail.

For each of the first four selected services whose metadata is available, the
home registry adds one `New on {service}` provider. Four is an explicit latency
bound, while all up-to-eight selected ids still participate in discovery
filtering and recommendation availability. Each service provider degrades
independently. This follows the predecessor's useful bounded shape without
copying its per-user ordering or configuration layers.

### 7. Reuse persisted title facts for the selected-service boost

The scorer keeps one subordinate `availability` boolean and does not double
reward a title that is both in-library and on a selected service. To compute it
without a second outbound fan-out, `TitleFacts` and the persisted `FeatureRecord`
gain the active `watch_region` plus that region's flatrate provider ids, derived
from the same cached TMDB detail payload already used to build recommendation
vectors.

Existing JSON records parse with empty defaults. `ensure_vectors` treats a record
whose stored region is missing or differs from the active region as stale and
lazily rebuilds it. Candidate availability becomes:

`in_library OR bool(selected_service_ids ∩ candidate.flatrate_provider_ids)`.

With no selected services, behavior is exactly M4. Seerr Unknown removes only the
library half; selected-service facts can still boost. Failure to refresh a title
skips that candidate as the current vector-build seam already does. A second
per-candidate watch-provider endpoint, a new availability table, and embedding
provider ids into the cosine feature vector were rejected respectively for
outbound fan-out, persistence complexity, and distortion of taste similarity.

### 8. Apply appearance through enum-to-token mappings

The SPA maps the backend's theme/accent enums to `data-theme`/`data-accent`
attributes and CSS custom-property tokens at the authenticated shell root. The
settings form offers only those named choices and applies the server-returned
value after save. Existing hard-coded neutral colors are consolidated behind a
small semantic palette for surfaces, text, borders, focus, and accent. No value
from the API is interpolated as arbitrary CSS.

After save, TanStack Query updates/invalidate `config`, `settings`, `home`,
`rails`, and title/detail data. That immediately applies appearance and makes
subsequent feed/detail requests use the new catalog context without a reload.
There is no localStorage fallback or client-owned preference.

### 9. Complete focus, keyboard, motion, and 10-foot behavior with small hooks

The detail overlay remains route-driven, but its background becomes a distinct
shell sibling. While open, a small local focus-trap hook marks that sibling
`inert`, cycles Tab/Shift+Tab within the dialog, closes on Escape, focuses the
dialog/first actionable control, and restores the trigger on close. No dialog
library is warranted for one modal.

The navbar menu uses the same explicit principles: trigger focus is preserved,
Escape and outside pointer activation dismiss it, menu items remain reachable in
normal tab order, and Settings is present only for admins. Save/probe/reset
results use visible text with `role=status` or `role=alert`; color is not the only
signal.

Each horizontal rail has a labelled region and key handler that moves focus to
the previous/next card on Left/Right and scrolls it into view. Cards, icon
buttons, form controls, and menu items receive visible `:focus-visible` treatment
and at least a 44px target where layout permits. Responsive rules preserve useful
text/card sizes and safe spacing at both 1280x720 and 1920x1080 TV viewports.

The existing `useReducedMotion` hook remains the JS source for auto-rotation.
CSS transitions/transforms are `motion-safe`, smooth scrolling becomes instant,
and no non-essential animation/auto-advance runs under
`prefers-reduced-motion: reduce`. Native loading feedback may remain static rather
than disappear. Focus behavior is tested in Vitest; the two TV viewports and a
keyboard-only path are checked manually because Playwright remains M6.

## Security considerations

### New or changed API endpoints

- Every endpoint is default-deny with `require_admin`; unauthenticated requests
  receive 401 and authenticated non-admins 403. No new anonymous endpoint exists.
- `PUT /settings` and `POST /connection-test` require the same-origin dependency
  and the dedicated bounded admin-mutation bucket.
- Query/body values use constrained Pydantic models. Region is two letters,
  service ids are bounded positive integers, toggles/appearance/targets are
  enums, and raw dictionaries are not passed upstream or persisted.
- Every route declares an explicit secret-free response model. Generic errors
  contain no upstream body/status/internal URL; logs contain target/category and
  exception class only, never cookies, tokens, credentials, or submitted PII.

### Auth and session

No login, cookie, token, or session lifecycle changes are made. Admin authority
continues to come from the locally stored Seerr-derived flag refreshed at login;
the browser's hidden Settings link is convenience only and never the security
boundary.

### Outbound HTTP

- Only `clients/` makes TMDB/Seerr calls. Base URLs and credentials come from the
  validated env-only `Settings`, never request input; connection-test target is
  an enum, eliminating an SSRF URL surface.
- Calls use the shared httpx client, explicit timeouts, bounded retry behavior,
  and typed wire models with unknown fields dropped. Browser headers are not
  forwarded and upstream headers/JSON are not returned to the browser.

### Frontend

- Settings, TMDB, and Seerr text is rendered as React text; no
  `dangerouslySetInnerHTML` is introduced.
- Appearance is mapped from enums, not inserted as arbitrary markup/CSS. No
  external URL is assembled, and the existing server-provided Seerr fallback
  remains unchanged.
- No token, secret, or preference is stored in local/session storage; the session
  remains an HttpOnly cookie.

### Database and migration

- The migration and store use SQLAlchemy expressions only. The table is
  intentionally incapable of receiving deployment `Settings`; its typed document
  contains no secret/token/URL fields.
- No existing secret material is copied or transformed. The migration creates an
  empty table and logs no values.

### Dependencies and build

No runtime or development dependency is added. Existing FastAPI/Pydantic,
SQLAlchemy/httpx, React/Tailwind/TanStack Query, and test tools cover the design,
so neither lockfile changes for M5.

## Risks / Trade-offs

- [A stale or invalid selected provider id can remain stored] → the UI sources ids
  from region services and clears them on region change; ids are bounded integers,
  invalid metadata omits only its service rail, and the admin can save a corrected
  selection even while TMDB is down.
- [Up to four service rails add home latency and TMDB load] → cap the rail count,
  compose them independently/concurrently, use existing cache/retry behavior, and
  omit failures.
- [Feature records become region-sensitive] → persist the source region with
  backward-compatible defaults and lazily rebuild only missing/mismatched records;
  no schema rewrite is needed.
- [A light theme touches many existing hard-coded colors] → introduce a small
  semantic token set and migrate component-by-component with focused render tests;
  do not build a general theme system.
- [Custom focus management can regress as modal content changes] → centralize the
  focusable selector/hook and test forward Tab, reverse Tab, Escape, inert cleanup,
  and focus restoration.
- [All rails can be disabled] → preserve the admin's explicit choice, return a
  valid empty feed, and render an explanatory empty state with a Settings link for
  admins.
- [Reading one settings row per request adds DB work] → accept the indexed local
  read; it is simpler and more consistent than mutable caching, and can be profiled
  before any cache is introduced.

## Migration Plan

1. Add Alembic revision `0004` creating the empty `settings` table. Existing
   deployments resolve defaults immediately after upgrade; no backfill or secret
   migration occurs.
2. Land the typed store/API and request-scoped resolver before switching catalog,
   rails, recommendation, and frontend consumers. Defaults preserve current
   region, enabled rails, dark appearance, and no service filter throughout.
3. Regenerate the OpenAPI schema/client after endpoint and `PublicConfig` models
   stabilize, then land the Settings UI and accessibility/theme refactor.
4. Run focused backend/frontend tests, perform the 1280x720 and 1920x1080
   keyboard/reduced-motion check, then run `just check` in the devcontainer.

Rollback to pre-M5 code safely ignores the added table. The Alembic downgrade
drops only that table and therefore discards runtime preferences; all pre-M5
behavior returns to code defaults. No user, session, signal, feature, or profile
row is touched.

## Open Questions

None blocking. The selected-service count (eight filters, first four service
rails) and named appearance presets are intentionally bounded defaults; expanding
either later is a small spec change backed by observed household need.
