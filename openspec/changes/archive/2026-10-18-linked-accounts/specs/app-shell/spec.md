# app-shell Specification (delta)

## MODIFIED Requirements

### Requirement: SPA shell is auth-gated

The SPA SHALL resolve auth state from `GET /api/v1/auth/me` on load.
Unauthenticated visitors see the login screen; authenticated users see the routed
application shell — a navigation bar (current user, logout control, search entry
point, an Account entry for every user, and an admin-only Settings entry) hosting
the browse routes — rendered
through the OpenAPI-generated typed client via TanStack Query. The `/settings`
route SHALL render only after the admin settings request succeeds; hiding its link
SHALL NOT replace the backend admin gate.

#### Scenario: Unauthenticated visitor
- **WHEN** the SPA loads and `/api/v1/auth/me` returns 401
- **THEN** the login screen is shown and no authenticated content renders

#### Scenario: Authenticated user sees the routed shell
- **WHEN** the SPA loads with a valid session
- **THEN** it shows the navigation bar with the current user's display name and a
  logout control, and renders the application route matching the current URL

#### Scenario: Admin sees Settings entry
- **WHEN** the authenticated user's local identity has `is_admin=true`
- **THEN** the shell offers a Settings navigation entry that opens `/settings`

#### Scenario: Non-admin cannot open Settings
- **WHEN** a non-admin directly navigates to `/settings`
- **THEN** no settings form/data renders and the backend settings request remains
  forbidden with 403

#### Scenario: Every user sees the Account entry
- **WHEN** any authenticated user opens the avatar menu
- **THEN** it offers an Account entry that opens `/account`
