## Context

The reviewed tooling, Plex recovery, and discovery-rail changes are merged on
`main`. The protected-branch, immutable-tag, GHCR, attestation, and release-check
machinery already supports a minor release. See `proposal.md` for motivation and
`specs/release-readiness/spec.md` for the updated contract.

## Goals / Non-Goals

**Goals:**

- Make `2.1.0` the single current version across manifests, lockfiles, regressions,
  current operator docs, support policy, and release evidence.
- Produce a redacted, reviewable pre-tag record for changes since `v2.0.0`.
- Reuse the existing candidate-first release pipeline and immutable publication
  order.

**Non-Goals:**

- Runtime, API, dependency, database, migration, or workflow changes.
- Rewriting historical v2.0 evidence or its `0006` migration boundary.
- Recording secrets, private coordinates, household data, or raw logs.

## Decisions

### 1. Reuse the existing release pipeline unchanged

Only version-bearing metadata, assertions, current docs/specs, and a new evidence
file change. Existing SemVer, main-ancestry, multi-architecture, attestation, and
stable-alias rules already cover `v2.1.0`.

Alternative: add minor-release workflow logic. Rejected because generic SemVer rules
already produce the required aliases.

### 2. Change only current-version references

Package roots, current deployment examples, support policy, regressions, the living
release spec, and release runbook move to `2.1.0`. The published v2.0 evidence and
historical statements about migration `0006` remain unchanged.

Alternative: mechanically replace every `2.0.0` occurrence. Rejected because that
would corrupt dependency data and release history.

### 3. Keep pre-tag and post-tag evidence separate

The committed record contains branch-verifiable gates and an approved disposition.
The exact merged SHA candidate, final digest, stable aliases, attestations, and
tagged-image smoke belong in the immutable GitHub Release after they exist.

Alternative: commit post-merge facts. Rejected because that creates a new candidate
and invalidates the facts being recorded.

### 4. Preserve migration-aware rollback

The v2.1 delta adds no migration, so rollback to v2.0 uses its immutable digest.
Rollback to v1.1 still requires the existing `0006` to `0005` downgrade with a v2
image or restoration of the matching validated pre-upgrade backup.

Alternative: describe all rollback as image-only. Rejected because that is unsafe
across the v2 schema boundary.

### 5. Apply the existing live-contract exception narrowly

A fresh `just test-live` run remains the default. The release-owner baseline plus
fresh integrated-manual-test exception is available only if credentials cannot
complete the run and this release-prep delta remains behavior-free. Evidence must
distinguish the exception from an automated pass.

Alternative: treat retained baselines as a fresh pass. Rejected because that would
misstate measured evidence.

## Security considerations

- No API, auth/session, outbound HTTP, frontend rendering, or database code changes
  in release preparation; the merged runtime scope is reviewed against the full
  applicable `docs/SECURITY.md` checklists.
- Both frozen dependency sets are audited; any advisory is fixed or documented with
  its identifier, affected surface, and explicit disposition before tagging.
- Placeholder fixtures, staged files, logs, and evidence are checked for secrets,
  private URLs, identities, viewing data, and generated failure artifacts.
- GitHub vulnerability reporting, secret scanning/push protection, dependency
  alerts/updates, protected `main`, immutable releases, and immutable `v*` tags are
  verified before publication.
- Candidate and stable images must be public, anonymously pullable,
  multi-architecture, repository-linked, and covered by valid artifact attestations.
- No dependency is added.

## Risks / Trade-offs

- **Live credentials may be stale** → Prefer a fresh rerun; otherwise require the
  documented complete baseline, fresh owner manual test, release-only delta, and
  explicit exception.
- **Post-merge images may differ from branch-local builds** → Verify the exact SHA
  candidate before tagging, then verify stable aliases after tagging.
- **Publication may fail after the immutable tag exists** → Never move or reuse the
  tag; fix forward through protected `main`.
- **Rollback guidance may obscure the old schema boundary** → State both the simple
  v2.1-to-v2.0 path and the required v2-to-v1.1 downgrade path.

## Migration Plan

1. Update version metadata, current docs/specs, regressions, and redacted evidence.
2. Run audits, deterministic release checks, live-contract disposition, full-tree
   security/repository review, strict OpenSpec validation, and archive this change.
3. Commit, push, review, and squash-merge through the required protected-branch
   gates.
4. On merged `main`, rerun the release gate and verify the exact SHA candidate.
5. Create and push `v2.1.0`; verify `2.1.0`, `2.1`, `2`, `latest`, attestation, and a
   fresh tagged deployment.
6. Publish the immutable GitHub Release with the post-tag facts.

Rollback before tagging is an ordinary correction through the release PR. After
tagging, preserve the tag and fix forward. Runtime rollback follows decision 4.
