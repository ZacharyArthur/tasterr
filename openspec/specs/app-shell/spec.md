# app-shell Specification

## Purpose
TBD - created by archiving change m0-scaffold. Update Purpose after archive.
## Requirements
### Requirement: App factory and lifespan
The backend SHALL expose an app factory producing the FastAPI application, with a
lifespan that runs database migrations before serving traffic.

#### Scenario: App is created by the factory
- **WHEN** the app factory is invoked
- **THEN** it returns a configured FastAPI app whose lifespan migrates the database
  on startup

### Requirement: Health endpoint
The API SHALL serve `GET /api/v1/health` without authentication (explicit
decision: liveness must work pre-login and for the container healthcheck),
returning HTTP 200 with a Pydantic response model containing app status and
per-integration configured flags. It MUST NOT expose secret values or internal URLs.

#### Scenario: Health responds when up
- **WHEN** a client requests `GET /api/v1/health`
- **THEN** it receives 200 with status and configured flags (e.g. tmdb, seerr)
  and no secret material

### Requirement: SPA served with index fallback
The backend SHALL serve the built SPA's static assets and return `index.html` for
any non-`/api` path, while unknown `/api/v1/*` paths return a JSON 404.

#### Scenario: Deep link serves the SPA
- **WHEN** a browser requests a non-API path such as `/settings`
- **THEN** the backend responds with `index.html` so the SPA router takes over

#### Scenario: Unknown API route stays JSON
- **WHEN** a client requests an undefined `/api/v1/*` path
- **THEN** the backend responds 404 with a JSON body, not `index.html`

### Requirement: SPA shell is auth-gated
The SPA SHALL resolve auth state from `GET /api/v1/auth/me` on load.
Unauthenticated visitors see the login screen; authenticated users see the app
shell, which displays the current user and the backend health fetched through the
OpenAPI-generated typed client via TanStack Query.

#### Scenario: Unauthenticated visitor
- **WHEN** the SPA loads and `/api/v1/auth/me` returns 401
- **THEN** the login screen is shown and no authenticated content renders

#### Scenario: Authenticated user sees the shell
- **WHEN** the SPA loads with a valid session
- **THEN** it shows the authenticated shell with the current user's display name
  and the health status returned by `/api/v1/health`

