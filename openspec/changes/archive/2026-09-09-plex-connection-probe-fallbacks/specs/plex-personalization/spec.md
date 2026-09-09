## MODIFIED Requirements

### Requirement: Advertised Plex server connections are verified before use

Resource discovery SHALL request HTTPS and relay connection data, retain at most
four Plex Media Server resources in deterministic owned-first, machine-identifier
order. For each resource, the backend SHALL retain only connections that pass the
existing URL validation, partition them into local, remote-direct, and relay
categories, reserve the first candidate from each available category, fill the
remaining configured probe slots from the unselected candidates, and restore
local, remote-direct, relay, then stable URI priority before probing. The selected
resources and connections SHALL be probed concurrently, while the accepted result
SHALL remain the first verified connection in that deterministic priority order.
The per-resource connection probe limit SHALL default to six, accept only values
from 3 through 12 inclusive, and bound the number of identity probes for both
Continue Watching and Plex history discovery.

Before an authenticated PMS read, the backend SHALL reject connections with an
unapproved scheme, host, port, credentials, query, or fragment; require standard
TLS certificate and hostname verification; and verify through unauthenticated
`/identity` that the connection's machine identifier matches the resource.
Redirects SHALL NOT be followed. Resource access tokens SHALL be sent only after
identity verification and only in `X-Plex-Token`. Connection URLs, machine
identifiers, and resource tokens SHALL remain call-local and SHALL NOT be
persisted or stored in the general cache. Resource pagination SHALL be implemented
only when the live gate proves the endpoint paginates; otherwise one bounded
response SHALL be used.

#### Scenario: Local verified HTTPS connection wins

- **WHEN** one resource advertises valid local HTTPS, remote-direct, and relay connections
- **THEN** the first verified connection in deterministic local, remote-direct, relay, then URI priority is used

#### Scenario: Hostile advertised URL is skipped

- **WHEN** an advertised connection contains plain HTTP, credentials, an unapproved hostname/port, a query/fragment, or a mismatched machine identity
- **THEN** no authenticated request or credential is sent to that connection

#### Scenario: TLS verification cannot be bypassed

- **WHEN** an advertised HTTPS connection has an invalid or hostname-mismatched certificate
- **THEN** the connection is skipped even when its `/identity` body could claim the expected machine identifier

#### Scenario: One inaccessible server does not hide valid siblings

- **WHEN** one bounded resource has no usable connection and another does
- **THEN** reads continue with the usable resource without exceeding the server or configured connection-attempt bounds

#### Scenario: Local candidates cannot crowd out remote-direct fallback

- **WHEN** one resource has more eligible local connections than the configured probe limit and also has an eligible remote-direct connection
- **THEN** the remote-direct connection receives a probe slot before remaining slots are filled with local candidates

#### Scenario: Relay fallback receives a reserved slot

- **WHEN** one resource has eligible local, remote-direct, and relay connections and the local and remote-direct candidates fail
- **THEN** the relay connection receives a probe slot and can be selected without exceeding the configured limit

#### Scenario: Probe limit defaults to six

- **WHEN** the operator does not configure the connection probe limit
- **THEN** no more than six identity probes are made per resource

#### Scenario: Multi-homed server has a fixed attempt ceiling

- **WHEN** the operator configures the connection probe limit to eight
- **THEN** no more than eight identity probes are made per resource

#### Scenario: Probe limit rejects out-of-range configuration

- **WHEN** the operator configures the connection probe limit below three or above twelve
- **THEN** application settings validation fails instead of clamping the value

#### Scenario: Stalled preferred connections do not serialize fallback

- **WHEN** a lower-priority connection verifies before a slower preferred connection
- **THEN** the bounded probes overlap, the preferred verified connection still wins without summing individual timeouts, and unused pending probes are cancelled and awaited

#### Scenario: More than four servers select deterministically

- **WHEN** resource discovery returns more than four accessible PMS devices
- **THEN** the same first four owned-first, machine-id-sorted resources are used for the same response on every run

#### Scenario: Failed account validation stops sibling discovery

- **WHEN** account validation fails while resource discovery is still running
- **THEN** discovery is cancelled and awaited before the media read fails or degrades
