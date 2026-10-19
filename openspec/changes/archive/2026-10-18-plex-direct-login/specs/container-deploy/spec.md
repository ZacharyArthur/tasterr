# container-deploy Specification (delta)

## MODIFIED Requirements

### Requirement: Compose example wires the stack

`docker-compose.yml` SHALL start Tasterr on a Compose-managed network and, when
Seerr is configured, reach it
exclusively through `SEERR_INTERNAL_URL`, without requiring a
pre-created external network. A separate optional override SHALL let Tasterr join an
operator-named external network when Seerr runs on the same Docker host in another
Compose project and service-name discovery is desired. The base example SHALL keep
the optional Seerr service commented out rather than start a second server by
default, SHALL store the SQLite file on a named volume, and SHALL publish the host
port on loopback by default. Publishing to every interface or a LAN interface MUST
require an explicit `TASTERR_HTTP_PORT` override.

#### Scenario: Compose brings the app up

- **WHEN** `docker compose up` runs with the base example and a populated `.env`
- **THEN** Tasterr starts on its managed network, publishes port 8000 on host
  loopback only, persists its database on the named volume, and passes its healthcheck

#### Scenario: Explicit LAN publication remains available

- **WHEN** an operator sets `TASTERR_HTTP_PORT` to `8000` or a specific LAN bind
  expression
- **THEN** Compose uses that explicit host publication instead of the loopback default

#### Scenario: Routable Seerr needs no external network

- **WHEN** `docker compose up` runs with a populated `.env` whose internal URL points
  to a Seerr instance reachable through LAN routing or DNS
- **THEN** Tasterr starts, persists its database on the named volume, reaches Seerr
  through the internal URL, and passes its healthcheck without an operator-managed
  Docker network

#### Scenario: Same-host cross-stack discovery is opt-in

- **WHEN** the operator supplies `TASTERR_MEDIA_NETWORK` and includes
  `docker-compose.seerr-network.yml`
- **THEN** Tasterr joins that existing external network and can resolve the Seerr
  service name or alias without changing the base deployment path

#### Scenario: Example does not create an unsolicited Seerr

- **WHEN** an operator uses the compose file without uncommenting the optional Seerr
  block
- **THEN** Compose starts Tasterr only and leaves the household's existing Seerr
  lifecycle untouched

#### Scenario: Plex-only deployment needs no Seerr

- **WHEN** `docker compose up` runs with `PLEX_SERVER_ID` set and no Seerr values
- **THEN** Tasterr starts, passes its healthcheck, and offers Plex sign-in
