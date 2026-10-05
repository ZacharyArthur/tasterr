## Context

See proposal.md. Main contains request-destination override and discovery-exclusions since v2.1.1. Existing release procedures require deterministic checks, separate audits, security review, live contracts and verified candidate/tagged images. Seerr request/response behavior changed; Plex integration behavior did not.

## Goals / Non-Goals

Prepare an accurately evidenced v2.2.0 without changing product behavior or relaxing release gates. Preserve historical evidence, frozen blueprints, existing workflows and migration facts.

## Decisions

- Advance existing manifests, lock metadata, release-facing docs/tests and the living release specification to 2.2.0. Keep prior release evidence untouched and use v2.1.1 as the immediate rollback image.
- Apply compatible targeted lock updates for anyio, urllib3, undici and brace-expansion, not a broad refresh. The first is runtime; the others are existing development chains. No new dependency or override is needed. Verify actual resolved versions, lock scope, full gates and fresh audits.
- Use docs/RELEASING.md unchanged release policy: fresh automated Seerr contracts are mandatory because destination requests changed. Prefer fresh Plex contracts; any unchanged-Plex exception still needs explicit owner disposition, a complete dated baseline and fresh integrated manual evidence. Credentials and disposable request IDs remain outside the repository.
- Read fresh Seerr user capabilities in the destination live contract, as production does; the login payload can omit permissions. Missing advanced/variant permissions leave the required cases pending, not passed.
- The owner has no configured 4K destination and explicitly accepts skipping that data-dependent live case. Require a fresh standard destination persistence pass and report the 4K gap without implying an automated pass.
- Record the owner's one-time acceptance of the deployment error-log limitation without configuration, coordinates or a claim of independently verified runtime redaction. The general release checklist is unchanged.
- Maintain a pending redacted record while required outcomes are unresolved. Finalize approval status only after branch-verifiable checks finish. Archive, obtain exact commit/PR text approval and squash merge before candidate verification and an immutable annotated tag. Candidate and post-tag facts belong in the GitHub Release, not a follow-up source commit.

## Security considerations

Review the full v2.1.1..HEAD scope against docs/SECURITY.md, not just version metadata. Preserve session/admin/CSRF/rate dependencies, explicit response models and secret projection; validate destination data server-side, and keep filter preferences typed and non-secret. Outbound calls stay in existing clients with validated URLs, bounds and drained tasks. Browser rendering remains text-only; no credential storage or new endpoint/database schema is introduced by preparation.

Use existing audited packages and locked provenance, non-root production builds and SHA-pinned workflows. Verify repository reporting/scanning/immutability/rulesets and public-package attestations. Store live credentials mode 600 outside the checkout, authorize disposable request tests through operator-provided IDs, verify cleanup and remove temporary secret files. Evidence/logs contain generic outcomes only, without upstream bodies, household identifiers, viewing data, live URLs or credentials.

## Risks / Trade-offs

- Missing live credentials -> keep live tasks and release disposition pending; no speculative pass or changed-integration waiver.
- Dependency fixes may affect runtime/test behavior -> targeted updates, clean audits and full deterministic release checks.
- Entry-bounded discovery cache and cold-cache fail-open results remain -> retain documented limitations; no unmeasured memory/warmth claim.
- Immutable publication failures -> never move/reuse a tag; fix forward through protected main.

## Migration Plan

No new migration. Back up SQLite and upgrade using the pinned v2.2.0 image after publication. Roll back to the prior v2.1.1 digest against the same schema; crossing migration 0006 to v1.1 requires the existing downgrade/validated-backup procedure.
