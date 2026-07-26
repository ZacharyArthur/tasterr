## 1. Production logging and response hardening

- [x] 1.1 Disable Uvicorn access/server metadata, remove household identifiers from
  application log messages, and add focused entrypoint/log privacy regressions.
- [x] 1.2 Add the dependency-free outer security-header wrapper with CSP and
  trusted-HTTPS-only HSTS, plus API/SPA/error/header regressions.

## 2. Secure deployment defaults

- [x] 2.1 Default the Compose host publication to loopback, retain an explicit LAN
  override, and update the native container/documentation contract tests.

## 3. Supply chain and licensing

- [x] 3.1 Refresh the dependency tree with the narrowest compatible patched
  versions; regenerate/check types, verify full and production-only npm audit
  results, and precisely disposition findings without a safe published fix.
- [x] 3.2 Add the unmodified AGPL-3.0-only license, backend package metadata, and
  concise README attribution without inventing the future GitHub coordinate.

## 4. Documentation and release evidence

- [x] 4.1 Update configuration, security, release, and quick-start guidance for
  loopback/LAN binds, proxy query-log privacy, response headers, licensing, and the
  remaining repository-host steps.
- [x] 4.2 Replace stale v1.0.0 date/tag/test/audit/security claims with accurate
  release-candidate evidence and preserve any not-yet-run live/GHCR work as explicit
  operator steps.

## 5. Verification

- [x] 5.1 Run strict OpenSpec validation, `just audit`, and focused privacy/header
  probes; resolve or precisely document every finding.
- [x] 5.2 Run the full credentialed live contract suite when its external secret file
  is available; otherwise verify it remains explicitly pending before tagging.
- [x] 5.3 Run `just release-check` in the devcontainer and fix every failure.
- [x] 5.4 Run `just check` in the devcontainer and fix any failures.

## 6. Reviewer-driven public polish

- [x] 6.1 Extend an exercised authentication regression to prove successful login
  logs contain neither credentials nor a household user identifier.
- [x] 6.2 Replace the publication coordinate, add a compact badge treatment, and
  replace the scaffolded favicon with a dependency-free Tasterr SVG mark.
- [x] 6.3 Correct the tag/GHCR evidence order, record reviewer approval and the
  operator's explicit acceptance of the historical live baseline, and remove the
  brittle hand-counted regression total.
- [x] 6.4 Restore YouTube trailer playback with an origin-only cross-origin referrer
  policy and regression coverage while keeping household routes and queries private.
- [x] 6.5 Integrate the operator-supplied sanitized home, detail, and search
  screenshots into the README.
- [x] 6.6 Rerun focused checks, strict OpenSpec validation, audits, `just check`, and
  `just release-check` after the final screenshot assets land.

## 7. Final review corrections

- [x] 7.1 Replace `react-router-dom` with published `react-router` 8.3, update
  declarative imports, regenerate the lockfile, and prove the production advisory is
  gone.
- [x] 7.2 Align the live-suite waiver procedure and release evidence, scope the
  Redocly override, exercise HSTS through trusted-proxy processing, and pin the
  README/browser favicon relationship.
- [x] 7.3 Rerun focused checks, strict OpenSpec validation, audits, `just check`, and
  `just release-check` after the final review corrections.

## 8. Publication bootstrap polish

- [x] 8.1 Add a copyable README Compose example that pulls the selected
  `ghcr.io/zacharyarthur/tasterr` release, preserves loopback publication, and uses
  the named data volume.
- [x] 8.2 Document the private-first GitHub bootstrap, repository metadata and
  security policy, protected squash merge, immutable candidate verification, public
  visibility transition, stable tagging, and final release checks.
- [x] 8.3 Add focused documentation contracts, run strict OpenSpec validation, and
  pass the full `just check` gate.

## 9. Final documentation corrections

- [x] 9.1 Clarify that Tasterr accepts ordinary process environment variables while
  the bundled Compose file requires its configured `env_file`, and document the
  explicit Compose mapping for file-free host-variable injection.
- [x] 9.2 Correct the final gate/review evidence and make the private repository
  creation step explicitly forbid a create-and-push shortcut before Actions is
  disabled.
- [x] 9.3 Run focused documentation checks, strict OpenSpec validation, and the full
  deterministic release gate after the final documentation corrections.
