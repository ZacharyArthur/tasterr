# app-shell Specification (delta)

## MODIFIED Requirements

### Requirement: SPA shell is auth-gated
The SPA SHALL resolve auth state from `GET /api/v1/auth/me` on load.
Unauthenticated visitors see the login screen; authenticated users see the
**routed application shell** — a navigation bar (current user, logout control, and
a search entry point) hosting the browse routes — rendered through the
OpenAPI-generated typed client via TanStack Query.

#### Scenario: Unauthenticated visitor
- **WHEN** the SPA loads and `/api/v1/auth/me` returns 401
- **THEN** the login screen is shown and no authenticated content renders

#### Scenario: Authenticated user sees the routed shell
- **WHEN** the SPA loads with a valid session
- **THEN** it shows the navigation bar with the current user's display name and a
  logout control, and renders the browse route matching the current URL
