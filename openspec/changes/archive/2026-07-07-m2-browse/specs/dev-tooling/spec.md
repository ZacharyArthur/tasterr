# dev-tooling Specification (delta)

## MODIFIED Requirements

### Requirement: Boundary invariants are mechanically enforced
The gate SHALL include import-linter contracts asserting that only
`tasterr.clients` may import `httpx`, that `tasterr.api` is not imported by
domain or client modules, and that the **catalog and rails domain-model modules**
(the network-free typed shapes those layers build) do not import the application
settings module — so secret configuration can never be embedded in them. (`api/`
routers legitimately import settings for dependency injection; the client-facing
guarantee there is upheld by an explicit `response_model` on every route plus the
PublicConfig no-secrets regression test.)

#### Scenario: httpx import outside clients/ fails the gate
- **WHEN** a module outside `tasterr.clients` imports `httpx`
- **THEN** the import-linter step fails and `just check` exits non-zero

#### Scenario: settings import from a domain model fails the gate
- **WHEN** a catalog or rails domain-model module imports the application settings module
- **THEN** the import-linter step fails and `just check` exits non-zero

### Requirement: Frontend API types are generated from OpenAPI
Frontend API request/response types SHALL be generated from the backend's OpenAPI
schema via a `just` recipe, never hand-written a second time. The quality gate
SHALL verify that the committed generated types match what the current schema
produces, failing when they have drifted out of sync.

#### Scenario: Types regenerate from the schema
- **WHEN** the type-generation recipe runs
- **THEN** the frontend's API types file is produced from the backend OpenAPI schema
  and the frontend typechecks against it

#### Scenario: Stale generated types fail the gate
- **WHEN** the backend schema has changed but the committed generated types were
  not regenerated
- **THEN** the gate's freshness check fails and `just check` exits non-zero
