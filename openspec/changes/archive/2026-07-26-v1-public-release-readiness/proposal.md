## Why

The v1 release candidate passes its functional and deterministic gates, but a
pre-publication review found that request targets can disclose search terms in
logs, HTTP responses lack baseline browser hardening, the Compose example binds
to every host interface by default, and release metadata overstates the current
audit and publication state. These gaps must close before the first public
repository and stable image are announced.

This change advances the M6 hardening/release milestone and tightens the existing
`container-deploy` capability.

## What Changes

- Suppress Uvicorn access logs and its identifying `Server` header, and remove
  household user identifiers from application log messages.
- Add dependency-free application middleware that supplies a tested CSP, frame,
  MIME-sniffing, referrer, permissions, and HTTPS-only HSTS policy to every HTTP
  response, including the SPA and error responses.
- **BREAKING**: bind the Compose-published port to loopback by default; LAN
  publication now requires an explicit `TASTERR_HTTP_PORT` override.
- Remediate compatible locked dependency advisories, including replacing the
  removed React Router DOM compatibility package with the published v8 package,
  or record a precise disposition when no compatible fix exists.
- License Tasterr under AGPL-3.0-only and use the selected
  `ZacharyArthur/tasterr` public source coordinate consistently.
- Add a compact public README presentation, a native Tasterr SVG mark, and sanitized
  screenshots without introducing branding or documentation tooling.
- Add a copyable GHCR Compose example, distinguish file-based and injected process
  environment configuration, and document an explicit private-first GitHub bootstrap
  sequence that verifies the immutable candidate before public visibility and
  tagging.
- Correct release evidence and deployment guidance, then rerun the required audit,
  live contracts, deterministic release gate, and targeted privacy/header probes.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `container-deploy`: production responses and logs gain secure defaults, and the
  base Compose publication changes from all interfaces to loopback-only.
- `release-readiness`: public-release documentation and order now require the
  explicit license, private proxy logs, HTTP hardening, safe bind, accurate evidence,
  final repository-coordinate replacement, and a private bootstrap that cannot
  publish the pre-hardening `main`.

## Impact

- Backend production entrypoint, outer ASGI response handling, logging statements,
  and focused regressions.
- Compose defaults, container smoke contracts, environment examples, README,
  configuration/security/release documentation, and release evidence.
- Frontend lockfile updates for the existing OpenAPI type generator and the
  supported React Router v8 package; no additional runtime dependency.
- Root licensing and backend package metadata.
- Public README badges/screenshots and the existing code-native favicon asset.
- GitHub bootstrap, repository policy, candidate-image verification, visibility, and
  tag sequencing in the maintainer release runbook.

## Non-goals

- Running TLS in Tasterr or replacing the required reverse proxy/tunnel.
- Retaining or building a custom redacted per-request access-log pipeline.
- Adding a security-header dependency, telemetry, analytics, or multi-process
  deployment support.
- Creating a GitHub repository, pushing commits or tags, publishing GHCR images, or
  configuring repository-host settings in this change.
