# app-shell Specification (delta)

## ADDED Requirements

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

## REMOVED Requirements

### Requirement: Hello-world SPA calls the API through the typed client
**Reason**: Superseded by "SPA shell is auth-gated" — the health-through-typed-client
display now lives inside the authenticated shell instead of a public hello-world page.
**Migration**: No data or API migration; the SPA gains a login screen in front of
the same shell.
