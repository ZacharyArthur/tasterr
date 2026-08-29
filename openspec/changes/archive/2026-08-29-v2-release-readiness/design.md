## Context

The Plex-aware personalization product change is archived and merged at
`dd183dc`. Its `main`/SHA candidate image was built and attested, but package
metadata, the public deployment example, support policy, and stable tags remain on
v1.1. The feature design intentionally deferred `v2.0.0` packaging and publication
to this change so release evidence can be reviewed independently from runtime code.

The existing protected-branch, immutable-tag, GHCR, attestation, and release-check
machinery already supports the release. This change should configure and exercise
that machinery, not add another release system.

## Goals / Non-Goals

**Goals:**

- Make `2.0.0` the single release version across backend/frontend metadata,
  lockfiles, regression tests, documentation, and support policy.
- Produce a publishable, redacted pre-tag evidence record for the complete v2 scope.
- Run the deterministic release gate, both dependency audits, applicable security
  review, and live Seerr plus three-role Plex contracts before tagging.
- Merge through the normal protected PR, verify the immutable SHA candidate, then
  publish and verify `v2.0.0`, `2.0.0`, `2.0`, `2`, and `latest` without moving tags.

**Non-Goals:**

- Runtime, API, migration, recommendation, Plex, Seerr, or UI behavior changes.
- New dependencies, workflows, tag formats, registries, or release automation.
- Storing private live coordinates, credentials, household data, or raw logs.
- Rewriting historical v1 evidence or tags.

## Decisions

### 1. Reuse the existing release pipeline unchanged

The release change updates only version-bearing metadata, assertions, living
operator/release docs, the public support line, and a new evidence file. The current
workflow already enforces SemVer tags, main ancestry, multi-architecture publication,
stable aliases, and artifact attestations. Changing it would enlarge the security
review without improving the v2 release.

Alternative: add v2-specific workflow logic. Rejected because the existing generic
`v*`/SemVer rules already cover major releases.

### 2. Use one literal version and pin it with existing tests

`2.0.0` will replace the project version in `backend/pyproject.toml`, the local
package entry in `backend/uv.lock`, `frontend/package.json`, and the root entry in
`frontend/package-lock.json`. The release-version and documentation regressions will
point to `v2.0.0`, `docs/releases/v2.0.0.md`, the v2 README image, and the v2 support
line. Dependency versions that happen to contain `1.1.0` remain untouched.

Alternative: derive every document from one build-time source. Rejected because
that introduces generation machinery for four simple, test-pinned release fields.

### 3. Split committed pre-tag evidence from authoritative post-tag facts

The committed `v2.0.0` record will contain outcomes known on the reviewed branch:
release-check, audits, strict OpenSpec validation, security review, live contracts,
upgrade/rollback, and limitations. It will say `approved for release` and will not
predict a merged SHA, manifest digest, publication time, or tagged-image result.

After the release PR merges, candidate manifest/attestation/public-install checks
must pass before the immutable tag is created. Stable alias, final digest,
attestation, and clean tagged-install results belong in the immutable GitHub Release,
which is the only post-tag record. This avoids a documentation-only commit that
would advance `main` and publish a different candidate.

Alternative: commit the candidate digest after merge. Rejected because protected
main would require another PR and generate a new SHA candidate, invalidating the
recorded candidate.

### 4. Require live evidence without misrepresenting stale credentials

A fresh `just test-live` run from a mode-0600 temporary environment is the default.
If retained credentials no longer complete that rerun, the release owner may accept
the most recent complete automated contract baseline plus a fresh integrated manual
test only when the release delta contains no runtime behavior change. Evidence must
identify the baseline date/version, the generic failed rerun phase where a rerun was
attempted, the manual test, and the explicit exception without claiming a fresh
automated pass.

This release uses the complete 2026-08-27 owner/managed/shared Plex baseline against
PMS `1.43.3.10896-cb3ebc72d`, the complete Seerr 3.3.0 baseline from 2026-07-13, and
the release owner's fresh manual test. A 2026-08-28 automated Plex rerun could not
complete the owner history phase with the retained access and the owner identified
those credentials as potentially stale. The release-readiness delta changes only
metadata, tests, and documentation.

Alternative: report the stale-access rerun as passing. Rejected because release
evidence must distinguish measured automated results from owner-accepted exceptions.

### 5. Use migration-aware v2 upgrade and rollback guidance

Operators upgrade only after a validated backup and may roll back to v1.1 only by
using the v2 image to downgrade schema `0006` to `0005` before starting the old
image, or by restoring the matching pre-upgrade backup. README, configuration, and
release notes must not imply an image-only rollback across this schema boundary.

## Security considerations

- No API, authentication, outbound HTTP, frontend rendering, or database code is
  changed by release preparation; the corresponding runtime checklists remain
  covered by the already-reviewed v2 implementation and the full release gate.
- Both frozen dependency sets are audited. Any advisory must be fixed or recorded
  with its identifier, affected surface, and explicit disposition before tagging.
- The full diff since `v1.1.0` is reviewed against `docs/SECURITY.md`, including
  Plex URL allowlisting, TLS and machine identity, credential isolation, log privacy,
  browser cache isolation, migration downgrade, workflow permissions, and action
  SHA pinning.
- `.env.example`, fixtures, staged files, and evidence are checked for real secrets,
  URLs, identities, viewing data, raw logs, and generated failure artifacts.
- GitHub private vulnerability reporting, secret scanning/push protection,
  Dependabot alerts, immutable releases, protected `main`, and the immutable `v*`
  tag ruleset are verified before tagging.
- Candidate and stable images must be public, multi-architecture, anonymously
  pullable, linked to the repository, built by the existing least-privilege workflow,
  and covered by a valid GitHub artifact attestation.
- No dependency is added.
- The live exception records only generic outcomes and prior public-safe versions;
  no stale credential, URL, identity, viewing data, or upstream payload is retained.

## Risks / Trade-offs

- **Live integration credentials can expire during release preparation** → Prefer a
  fresh rerun; otherwise require a complete recorded baseline, a fresh owner manual
  test, a release-only delta, and an explicit evidence exception that does not claim
  fresh automation.
- **A post-merge candidate may differ from branch-local images** → Verify its exact
  SHA tag, manifest, attestation, anonymous pull, clean deployment, non-root runtime,
  and volume persistence before tagging.
- **A tag-triggered workflow or smoke can fail after publication** → Never move,
  delete, or reuse `v2.0.0`; fix forward through protected main and publish the next
  patch version.
- **Major-version upgrade cannot use image-only rollback** → Require a validated
  backup and document the `0006` to `0005` downgrade order.

## Migration Plan

1. Update metadata, tests, README/support/release/configuration docs, and the redacted
   `v2.0.0` evidence record on `change/v2-release-readiness`.
2. Run strict OpenSpec validation, `just release-check`, `just audit`, live contracts,
   repository/security review, and `git diff --check`; archive this change.
3. Obtain approval for the exact commit and PR text, then push and merge only after
   `check`, `e2e`, `container-smoke`, and CodeQL pass.
4. On merged `main`, rerun `just release-check`; verify the SHA candidate manifest,
   attestation, public visibility, anonymous pull, and disposable clean install.
5. Create and push the annotated `v2.0.0` tag. Verify `2.0.0`, `2.0`, `2`, `latest`,
   and the unchanged SHA candidate, then repeat attestation and clean-install smoke.
6. Publish the immutable GitHub Release with user-visible changes, upgrade/rollback,
   limitations, final digest, alias verification, and post-tag results.

Rollback before tagging is ordinary branch/PR correction. After tagging, preserve
the immutable tag and fix forward. Runtime rollback follows the documented schema
downgrade or validated pre-upgrade backup restore.

## Open Questions

None. The version, release scope, registry coordinate, and existing workflow are
already fixed by the archived product change and current release policy.
