## 1. Configuration and contracts

- [x] 1.1 Add the validated server-side probe-limit setting and focused default, accepted-value, rejected-value, and PublicConfig/OpenAPI regression assertions; verify the settings and contract tests pass.
- [x] 1.2 Document the optional setting, valid range, probe-cost effect, and updated security bound in `.env.example`, `docs/CONFIGURATION.md`, and `docs/SECURITY.md`; verify the env-example drift test passes.

## 2. Bounded connection discovery

- [x] 2.1 Implement category-aware bounded selection and instance-level constructor validation in the Plex client while preserving concurrent probes, deterministic winner priority, cancellation, and every existing trust check; verify focused Plex client regressions pass.

## 3. Production wiring

- [x] 3.1 Pass the configured probe limit through Home Continue Watching and background Plex history client construction; verify focused wiring and existing Plex history tests pass.

## 4. Verification

- [x] 4.1 Run the requested targeted Plex, settings, rails, browse, environment, public-contract, and history-sync tests inside the devcontainer and fix failures.
- [x] 4.2 Run the configured redacted live Plex contract suite inside the devcontainer; verify server discovery succeeds and Continue Watching maps enough summaries to render without recording sensitive evidence.
- [x] 4.3 Validate the OpenSpec change strictly and resolve any artifact errors.
- [x] 4.4 Run `just check` inside the devcontainer and fix all failures.
