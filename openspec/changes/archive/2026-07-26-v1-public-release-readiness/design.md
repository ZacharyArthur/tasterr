## Context

Tasterr's application behavior and native image pass the v1 deterministic gates,
but Uvicorn's default access log records the complete `/api/v1/search?q=...` target
and its default response header identifies the server. Responses do not currently
carry browser hardening headers, and the base Compose file publishes port 8000 on
all host interfaces unless the operator knows to override it. The current release
evidence also predates newly published advisories in the dev-only OpenAPI type
generator path.

The app serves both the API and compiled SPA from one ASGI process. Its existing
`Tasterr.build_middleware_stack` override already supplies an outer response wrapper
so session-cookie refresh also reaches synthesized 500 responses. The frontend uses
self-hosted scripts/styles, TMDB images, and a YouTube iframe for trailers.

## Goals / Non-Goals

**Goals:**

- Ensure production logs do not record request targets, search terms, household
  identifiers, internal URLs, credentials, or title/viewing data.
- Put a small, explicit security-header policy on API, SPA, fallback, and error
  responses without adding a dependency.
- Make accidental network exposure less likely while retaining an explicit LAN bind.
- Produce a clean dev-dependency audit where compatible patched transitive versions
  exist, or a precise release disposition where they do not.
- Apply AGPL-3.0-only consistently to the source tree and package metadata.
- Replace stale release claims with reproducible final evidence.

**Non-Goals:**

- TLS termination, certificate management, a custom request-log formatter, or proxy
  configuration owned by another project.
- A configurable CSP/header framework or a third-party middleware package.
- Changing API shapes, auth/session behavior, adding a new production dependency,
  or changing the architecture of generated frontend types.
- Creating or administering the future GitHub repository or publishing an image.

## Decisions

### 1. Disable request access logs instead of redacting them

Pass `access_log=False` and `server_header=False` to the production `uvicorn.run`
call. Remove stable per-user identifiers from application log messages and keep
generic event names and aggregate counts where operationally useful.

A logging filter or custom Uvicorn formatter would preserve request telemetry, but it
would need to parse every request-target form correctly and would still duplicate
the reverse proxy's operational logs. Tasterr has no stated access-log requirement;
disabling the source of the privacy leak is smaller and safer. Proxy documentation
will explicitly require query-string omission or redaction because the application
cannot control upstream proxy logs.

### 2. Reuse the existing outer ASGI response-wrapper pattern

Add one dependency-free ASGI wrapper alongside `SessionCookieSlide` and make it the
outermost application wrapper. On each `http.response.start` it overwrites the fixed
security headers using `MutableHeaders`; non-HTTP scopes pass through unchanged.
This placement covers router responses, static files, SPA fallback, framework 404s,
and synthesized 500s without distributing header logic across routes.

The fixed policy is:

- `Content-Security-Policy`: self by default; self-hosted scripts/styles/fonts and
  API connections; TMDB plus local/data images; YouTube trailer frames; no objects;
  no foreign base URI, form target, or framing.
- `X-Frame-Options: DENY` for legacy frame protection.
- `X-Content-Type-Options: nosniff`.
- `Referrer-Policy: strict-origin-when-cross-origin` so TMDB and YouTube receive only
  the application origin, never a SPA path or search query. YouTube requires this
  client identity for embedded playback and returns player error 153 when the
  referrer is suppressed completely.
- `Permissions-Policy` denies camera, geolocation, and microphone.

`Strict-Transport-Security: max-age=31536000` is added only when the ASGI scope's
effective scheme is `https`. Uvicorn derives that scheme from forwarding headers
only for configured trusted proxy peers, so an untrusted request cannot opt into the
HTTPS path. `includeSubDomains` and preload are omitted because a self-hosting
operator may not control every subdomain and preload is difficult to reverse.

Supplying these headers only at the proxy was considered, but Tasterr supports many
operator-selected proxies and can safely enforce the same application policy itself.
The proxy remains responsible for TLS and may add equivalent defense-in-depth.

### 3. Default the Compose host publication to loopback

Change the base mapping to `${TASTERR_HTTP_PORT:-127.0.0.1:8000}:8000`. An operator
who intentionally serves other LAN clients can set `TASTERR_HTTP_PORT=8000` (or a
specific LAN address), while a host proxy can continue to reach the loopback bind.
Container-to-container proxies should use the Compose network and need no direct
internet publication.

Keeping the current all-interface default plus a warning was rejected because the
safe outcome would still depend on every new operator reading the warning before
first boot.

### 4. Patch compatible dependencies and precisely triage unavailable fixes

Run a fresh audit inside the devcontainer and prefer an ordinary parent update. If
the latest compatible `openapi-typescript`/Redocly tree still pins affected versions,
use the narrowest compatible npm override. Regenerate API types and run the normal
freshness, frontend, and audit checks to prove compatibility.

Advisories published after a clean audit are handled the same way. Patch PostCSS
within its compatible range. Retain the current type generator when its Redocly
dependency requires `brace-expansion` 2.x but the only fixed release is incompatible
5.x; this path is dev-only, processes the repository's trusted generated schema, and
does not enter the runtime image. Replace the removed `react-router-dom` compatibility
package with published `react-router` 8.3, whose documented minimum Node, React, and
Vite versions the project already meets, and move declarative imports to that package.
Do not accept audit-suggested downgrades that reintroduce older high-severity
advisories. Record the remaining advisory ID, scope, compensating facts, and upgrade
trigger in the release evidence.

Replacing the type generator, adding an audit-suppression dependency, or
force-upgrading unrelated packages would create more risk than the precisely scoped
finding. The Router package replacement adds no new capability, and `npm audit`
continues to report the accepted development-only finding rather than hiding it.

### 5. Use AGPL-3.0-only, not an "or later" grant

Add the unmodified GNU Affero General Public License version 3 as root `LICENSE`,
declare `AGPL-3.0-only` in backend package metadata, and state the license in the
README. The exact future GitHub source coordinate remains a publication-time edit;
this change will not invent or expose a broken placeholder source link in the UI.

### 6. Keep public presentation native and small

Use the selected `ZacharyArthur/tasterr` coordinate for documentation, badges, and
GHCR commands. Replace the scaffolded Vite favicon with one small hand-authored SVG
that matches Tasterr's existing violet/cyan palette. Limit the README to four useful
badges and sanitized application screenshots supplied by the operator; add no logo,
image-processing, badge-generation, or documentation dependency.

State the configuration boundary precisely: Tasterr consumes ordinary process
environment variables and does not require or parse a `.env` file. The bundled
Compose file explicitly loads an environment file, while another container platform
may inject the same variable names directly. A Compose operator who wants host
variables instead must map those names into the service; host variables alone do not
enter a container.

The release-candidate Seerr suite is not rerun for this correction set by operator
decision. The release evidence records that explicit acceptance and retains the
previous ten-case live baseline without describing it as a fresh pass. Registry
manifest and tagged-image installation checks remain post-tag verification gates
before the public release announcement, not impossible prerequisites for creating
the image-producing tag.

### 7. Bootstrap privately and verify the candidate before publication

Document the first-repository sequence as an operator procedure, while keeping every
GitHub mutation outside this change. Create an empty private repository, disable
Actions before pushing the existing `main` and reviewed change branch, then re-enable
Actions and merge only through the `check`, `e2e`, and `container-smoke` pull-request
gates. Configure squash-only merging, automatic branch deletion, read-only default
workflow permissions, and a `main` ruleset requiring a pull request, the three
checks, linear history, conversation resolution, and protection from deletion and
force pushes.

After the squash, rerun the release check on updated `main` and verify the workflow's
immutable multi-architecture `sha-<full-commit>` image through an authenticated clean
install. Only then make the repository and GHCR package public, verify an anonymous
pull, and create the annotated stable tag. The tag workflow must produce `1.0.0`,
`1.0`, `1`, `latest`, and the immutable SHA tag before the GitHub Release is
published.

GitHub Free rulesets are available for public repositories but may not be available
while a personal repository is private. When the account plan cannot apply the
ruleset during bootstrap, require the documented checks operationally for the sole
bootstrap pull request and activate the complete ruleset immediately after making
the repository public. Private vulnerability reporting is likewise enabled after
public visibility because it is a public-repository feature.

## Security considerations

- **Endpoints/auth:** No endpoint, request model, auth dependency, session, CSRF, or
  rate-limit behavior changes. The outer middleware changes headers only.
- **Logs/privacy:** Access targets are disabled at Uvicorn. Application log messages
  retain generic outcomes only and tests use invented sentinels. Documentation tells
  operators to apply the same privacy rule to proxy logs.
- **Frontend/XSS:** The CSP keeps scripts and styles on self, permits only the two
  existing media hosts, forbids object embedding and ancestor framing, and leaves
  TMDB/Seerr text rendered normally as text. No inline-script allowance or secret is
  added to the SPA. Cross-origin referrers contain only the application origin, not
  household routes or query strings.
- **Trusted proxies/HSTS:** HSTS depends on the effective scheme after the existing
  literal-IP/CIDR trusted-proxy boundary. It is not asserted for direct HTTP.
- **Outbound HTTP/database:** No client, URL, secret, schema, migration, or database
  behavior changes.
- **Dependencies/build:** The existing Router compatibility package is replaced by
  its supported v8 package; no new third-party capability is added. Compatible
  versions are patched and verified by type generation, tests, build, and audit.
  Findings without an installable compatible fix remain visible and require
  release-specific applicability, compensating-control, and revisit documentation.
- **Public release:** The license choice is explicit. Release evidence will contain
  versions, advisory disposition, and generic pass/fail cases only; actual GitHub
  security settings and registry verification remain operator steps. Actions stay
  disabled while old `main` is first imported, the package stays private until its
  reviewed immutable candidate passes, and anonymous access is tested before the
  stable tag.

## Risks / Trade-offs

- **[Operators lose per-request Uvicorn diagnostics]** → retain generic application
  events and use privacy-configured proxy metrics when request telemetry is needed.
- **[CSP blocks a legitimate asset]** → cover TMDB images, YouTube trailers, API/SPA,
  and fallback responses in focused tests and the browser smoke.
- **[Loopback default surprises LAN-first users]** → document the one-variable
  explicit LAN override beside quick start and configuration examples.
- **[A transitive override violates a parent's hidden assumption]** → regenerate the
  schema types and run all frontend/deterministic gates; remove the override and
  record a bounded disposition if compatibility fails.
- **[The Router major upgrade changes declarative navigation]** → use only the
  official package/import migration, then run all frontend tests and the real-backend
  browser journey.
- **[HSTS on an incorrectly trusted proxy cements a bad HTTPS configuration]** → the
  existing default-deny proxy allowlist remains the only source of forwarded scheme;
  omit preload and subdomain scope.

## Migration Plan

1. Apply logging/header behavior and focused backend regressions.
2. Update Compose defaults and native container/documentation contracts.
3. Refresh and audit the frontend lockfile, migrate the Router package/imports, then
   regenerate/check API types.
4. Add AGPL-3.0-only files and correct release evidence to pending status.
5. Add the published-image Compose example and private-first repository bootstrap
   procedure.
6. Run `just check` before completing implementation tasks, followed by `just audit`,
   the available live contracts, `just release-check`, and targeted log/header probes.

Rollback is source-only: revert the change. No schema or persisted-data migration is
introduced. Operators who require LAN publication explicitly set the documented bind
expression rather than reverting the secure default.

## Open Questions

None. The selected public coordinate is `ZacharyArthur/tasterr`; repository creation
and all external publication actions remain a separate, explicitly approved run.
