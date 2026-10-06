## Context

The main ruleset requires CodeQL, but GitHub default setup excludes fork PRs. PR #40 is a fork contribution. Ordinary gate, browser and container checks already pass.

## Goals / Non-Goals

Keep required scanning, the original PR and contributor credit. Use the current default query suite and language coverage. Do not weaken protections or grant PR package/publish permissions.

## Decisions

Use one advanced workflow with a three-language matrix (Actions, JavaScript/TypeScript, Python), standard ubuntu-latest runners, a 15-minute job timeout, normal pull_request/main-push events and one weekly schedule. Reuse the existing immutable checkout pin and pin official CodeQL init/analyze to v4.38.2's resolved commit. No app dependency is added; the action is needed to run the already-required scanner on forks. Removing the check would weaken coverage and has not been chosen.

## Security considerations

The dependencies/build checklist applies. Third-party actions are pinned to full reviewed SHAs with version comments. Checkout persists no credentials. Workflow defaults to contents:read; only analysis jobs request security-events:write for SARIF upload. Fork pull_request tokens are restricted by GitHub. There is no pull_request_target, project build script, secrets input, package write or publish step. Scan only with normal unprivileged PR context. Existing API/auth/outbound/DB/frontend security behavior is unchanged.

## Risks / Trade-offs

- Default setup blocks advanced uploads: switch it off immediately before publishing the prepared workflow, with the required CodeQL check retained throughout.
- Actual hosted analysis requires publication: verify native CodeQL success on the exact final PR head before merging; local tests validate workflow structure and permission boundaries.
- Free availability depends on the repository remaining public and using standard runners; no larger runner is configured.

## Migration Plan

Prepare and verify locally, disable default setup at publication, push the workflow on this PR, and wait for native CodeQL plus ordinary checks. Merge only without bypass. If rollout fails, restore default setup and leave the PR unmerged while fixing the workflow.
