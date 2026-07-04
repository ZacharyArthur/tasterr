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

### Requirement: Hello-world SPA calls the API through the typed client
The frontend SHALL render a minimal page that fetches `/api/v1/health` through the
OpenAPI-generated client via TanStack Query and displays the result.

#### Scenario: SPA shows backend health
- **WHEN** the SPA loads with the backend running
- **THEN** it displays the health status returned by `/api/v1/health`

