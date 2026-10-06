## Why

The existing CodeQL default setup skips fork pull requests while the main ruleset requires its result, blocking contributor PRs. This advances the existing dev-tooling capability by making the required security scan runnable on every PR.

## What Changes

- Add one pinned CodeQL workflow for pull requests, main pushes and weekly scans.
- Scan the existing Actions, JavaScript/TypeScript and Python languages on standard public-repository runners.
- Replace GitHub default setup with this workflow at publication while retaining the required CodeQL check.
- Extend workflow tests to cover fork-safe triggers, bounded runtime and least-privilege analysis uploads.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `dev-tooling`: fork-capable security scanning and explicit analysis-upload permissions.

## Impact

One CI workflow, workflow regression tests, living dev-tooling specs and repository CodeQL setup. No application dependencies, config or migrations. Standard runners and CodeQL are free for this public repository.

## Non-goals

Changing branch protections, using privileged pull_request_target, altering scan query coverage, or bypassing required checks.
