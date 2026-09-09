## Context

The reviewed Plex connection-discovery fix is merged on `main`. The protected
branch, immutable tag, GHCR, attestation, and release-check machinery already
supports patch releases. See `proposal.md` for motivation and
`specs/release-readiness/spec.md` for the updated contract.

## Goals / Non-Goals

**Goals:**

- Make `2.1.1` the single current version across manifests, lockfiles,
  regressions, current operator docs, and release evidence.
- Produce a redacted, reviewable pre-tag record for the change since `v2.1.0`.
- Reuse the existing candidate-first release pipeline and immutable publication
  order.

**Non-Goals:**

- Runtime, API, runtime-dependency, database, migration, or workflow changes
  during release preparation.
- Rewriting historical release evidence or its migration boundaries.
- Recording secrets, private coordinates, household data, or raw logs.

## Decisions

### 1. Publish a patch release

Use `2.1.1` because the release fixes backward-compatible Plex discovery and adds
an optional bounded server setting without breaking public contracts.

Alternative: publish a new minor version. Rejected because the change does not
add a new public capability or break compatibility.

### 2. Reuse the existing release pipeline unchanged

Only version-bearing metadata, assertions, current docs/specs, and a new evidence
file change. Existing SemVer, main-ancestry, multi-architecture, attestation, and
stable-alias rules already cover `v2.1.1`.

Alternative: add patch-specific workflow logic. Rejected because generic SemVer
rules already produce the required aliases.

### 3. Change only current-version references

Package roots, current deployment examples, regressions, the living release spec,
and release runbook move to `2.1.1`. Published evidence and historical migration
statements remain unchanged.

Alternative: mechanically replace every `2.1.0` occurrence. Rejected because that
would corrupt release history and the prior-version rollback reference.

### 4. Keep pre-tag and post-tag evidence separate

The committed record contains branch-verifiable gates and an approved disposition.
The exact merged SHA candidate, final digest, stable aliases, attestations, and
tagged-image smoke belong in the immutable GitHub Release after they exist.

Alternative: commit post-merge facts. Rejected because that creates a new candidate
and invalidates the facts being recorded.

### 5. Require fresh verification for changed integrations

The release changes Plex server discovery, so the mandatory owner, managed, and
shared Plex contracts require a fresh pass. Seerr request/response behavior is
unchanged; if its retained local-account credentials are unavailable, the release
owner may explicitly accept the recent complete baseline plus a fresh integrated
manual test and any safe automated cases the configured environment still permits.
The evidence records the exception without claiming a fresh complete Seerr pass.

Alternative: treat live verification as all-or-nothing across every integration.
Rejected because it would rerun an unchanged integration without improving coverage
of the changed Plex path, while preventing a narrowly recorded owner exception.

### 6. Apply only compatible audit fixes

Advance the existing Vitest and `js-yaml` development dependency chain to the
first patched compatible versions reported by their reviewed advisories. Keep all
runtime dependencies unchanged and add no package.

Alternative: accept the findings as development-only. Rejected because compatible
patches exist and the release policy requires actionable findings to be resolved.

## Security considerations

- The merged Plex change retains HTTPS-only advertised URLs, normal TLS and
  hostname verification, disabled redirects, unauthenticated identity checks,
  exact machine matching, post-verification header-only tokens, bounded resource
  and connection probes, caller-scoped data, and no connection cache.
- Release preparation changes no API, auth/session, outbound HTTP, frontend
  rendering, or database behavior; the full `v2.1.0..HEAD` scope is reviewed
  against the applicable `docs/SECURITY.md` checklists.
- Both frozen dependency sets are audited; any advisory is fixed or documented
  with its identifier, affected surface, and explicit disposition before tagging.
- Placeholder fixtures, staged files, logs, and evidence are checked for secrets,
  private URLs, identities, viewing data, and generated failure artifacts.
- GitHub vulnerability reporting, secret scanning/push protection, dependency
  alerts/updates, protected `main`, immutable releases, and immutable `v*` tags
  are verified before publication.
- Candidate and stable images must be public, anonymously pullable,
  multi-architecture, repository-linked, and covered by valid artifact
  attestations.
- No dependency is added; only existing development dependencies receive
  compatible security patches.

## Risks / Trade-offs

- **Live upstream state may be unavailable** → Block tagging until every changed
  integration's mandatory suite passes; allow a release-owner baseline exception
  only for an unchanged integration and record only generic outcomes.
- **Post-merge images may differ from branch-local builds** → Verify the exact SHA
  candidate before tagging, then verify stable aliases after tagging.
- **Publication may fail after the immutable tag exists** → Never move or reuse the
  tag; fix forward through protected `main`.
- **Rollback guidance may obscure the v2 schema boundary** → State both the simple
  v2.1.1-to-v2.1.0 path and the required v2-to-v1.1 downgrade path.

## Migration Plan

1. Update version metadata, current docs/specs, regressions, and redacted evidence.
2. Run audits, deterministic release checks, mandatory live contracts, full-tree
   security/repository review, strict OpenSpec validation, and archive this change.
3. Commit, push, review, and squash-merge through the required protected-branch
   gates.
4. On merged `main`, rerun the release gate and verify the exact SHA candidate.
5. Create and push `v2.1.1`; verify `2.1.1`, `2.1`, `2`, `latest`, attestation, and
   a fresh tagged deployment.
6. Publish the immutable GitHub Release with the post-tag facts.

Rollback before tagging is an ordinary correction through the release PR. After
tagging, preserve the tag and fix forward. Runtime rollback uses the prior immutable
v2.1.0 image digest; rollback to v1.1 retains the documented migration downgrade.
