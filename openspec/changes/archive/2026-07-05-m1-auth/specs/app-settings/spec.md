# app-settings Specification (delta)

## ADDED Requirements

### Requirement: PublicConfig is served via a session-gated endpoint
`GET /api/v1/config` SHALL return the `PublicConfig` projection to authenticated
clients only, using the shared session dependency. It remains the only settings
shape ever serialized toward the client.

#### Scenario: Authenticated client fetches config
- **WHEN** a client with a valid session requests `GET /api/v1/config`
- **THEN** it receives the `PublicConfig` projection with no secret material

#### Scenario: Unauthenticated config request
- **WHEN** a client without a valid session requests `GET /api/v1/config`
- **THEN** the response is 401
