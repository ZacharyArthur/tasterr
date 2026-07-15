## ADDED Requirements

### Requirement: Forwarded-header trust is env-only and narrowly validated

The deployment settings SHALL expose `TASTERR_FORWARDED_ALLOW_IPS` as an env-only,
comma-separated allowlist of literal proxy-peer IP addresses or CIDR networks. It
SHALL default to loopback only. Empty entries, hostnames, URLs, malformed IP/CIDR
values, and wildcard trust (`*`) MUST fail settings validation rather than broaden
trust. The normalized allowlist SHALL be passed only to the production server and
MUST NOT be stored in the database, editable through an API, or included in
`PublicConfig`.

#### Scenario: Direct deployment gets a narrow default
- **WHEN** `TASTERR_FORWARDED_ALLOW_IPS` is unset
- **THEN** settings trust forwarding headers from loopback only

#### Scenario: Explicit proxy peers are accepted
- **WHEN** the env value contains valid literal addresses and narrow CIDR networks
- **THEN** settings expose their normalized values to the production server

#### Scenario: Unsafe trust input fails closed
- **WHEN** the env value contains `*`, a hostname, URL, empty item, or malformed
  address/network
- **THEN** application settings validation fails and no broader forwarding trust is
  applied

#### Scenario: Proxy trust never reaches clients or runtime preferences
- **WHEN** deployment and runtime settings are fully populated and their public/API
  projections are inspected
- **THEN** the trusted-proxy allowlist appears in neither `PublicConfig` nor any
  database-backed runtime-settings shape
