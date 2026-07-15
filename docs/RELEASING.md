# Releasing

This procedure is for stable v1 releases. The first stable package version is
`1.0.0`, its Git tag is `v1.0.0`, and its image is published by the `image` workflow
only after the OpenSpec change and code are archived and squash-merged together.

## 1. Prepare the required devcontainer

From the repository root on the host, start the pinned development environment:

```console
npx @devcontainers/cli up --workspace-folder .
```

All following build, test, audit, OpenSpec, and git commands run through
`npx @devcontainers/cli exec --workspace-folder .`; no host uv, Python, Node, npm,
just, or Docker build tooling is used.

## 2. Review security and repository contents

Walk every applicable item in [docs/SECURITY.md](SECURITY.md) against the full tree,
not only the final diff. Confirm endpoint auth/CSRF/rate limits and response models,
session and trusted-proxy behavior, outbound HTTP boundaries, frontend rendering and
storage, database/migration handling, dependency provenance, logs, container build,
workflow pins/permissions, and public-release controls.

Before any public announcement, enable GitHub private vulnerability reporting,
secret scanning (including push protection where available), and Dependabot alerts.
Confirm `.env.example` and test fixtures contain invented placeholders only, and
review staged files for live URLs, identities, viewing data, credentials, and
generated failure artifacts.

## 3. Run deterministic checks

`release-check` runs the ordinary quality gate, real-backend Chromium smoke, and
native image/Compose smoke sequentially. Any failure blocks the release.

```console
npx @devcontainers/cli exec --workspace-folder . just release-check
```

Record the date and result in `docs/releases/v1.0.0.md`. This command intentionally
does not imply that audits, security review, or live contracts passed.

## 4. Audit locked dependencies

Run both ecosystem audits separately so findings can be reviewed:

```console
npx @devcontainers/cli exec --workspace-folder . just audit
```

Resolve actionable findings. A release may proceed with a non-applicable or accepted
finding only when its advisory identifier, affected surface, and concise rationale
are recorded in the release evidence. Never copy audit output containing private
registry coordinates or environment data into the repository.

## 5. Run live Seerr contracts

Create `/tmp/tasterr-live.env` inside the devcontainer with mode `600`; never place it
under the repository. It must supply the live Seerr URL, local account email/password,
Seerr API key, a stored Plex token, and a disposable movie identifier that the account
may request. An optional known-available movie identifier enables the data-dependent
availability case. Then run:

```console
npx @devcontainers/cli exec --workspace-folder . bash -lc 'set -a; . /tmp/tasterr-live.env; set +a; just test-live'
```

The mandatory v1.0 cases are local auth, invalid-session status, stored-Plex-token
auth, availability read, request-history read, and request-as-user attribution. The
request case creates a real Seerr request and attempts cleanup, so choose a disposable
title and verify cleanup afterward. Record only the Seerr version and generic passed/
skipped case names. A deeper pagination or available-title case may be skipped only
when its documented data precondition is absent; stored-token auth and attributed
request may not be skipped for v1.0. Remove the temporary secret file after the run.

## 6. Validate and archive the OpenSpec change

Run strict validation on the change branch:

```console
npx @devcontainers/cli exec --workspace-folder . npx --yes @fission-ai/openspec@1.5.0 validate m6-hardening-release --strict --no-interactive
```

After every task and release-evidence field is complete, archive before merging so
the implementation and living specs land atomically:

```console
npx @devcontainers/cli exec --workspace-folder . npx --yes @fission-ai/openspec@1.5.0 archive m6-hardening-release
```

Review the archive diff and rerun `just check`. Do not use `--skip-specs` or
`--no-validate` for this change.

## 7. Commit, PR, and squash merge

Review `git diff --check`, the full diff, and the exact Conventional Commit subject
and pull-request text before executing any external git action. The PR title becomes
the squash commit on `main`; its body names the OpenSpec change, states what/why, and
checks the gate only after it passes. Push the change branch, open the PR, require the
three blocking gate jobs, then self-approve and squash merge.

The stable tag must not point at the unmerged change branch. Update local `main` to
the squash commit and rerun the deterministic release check there:

```console
npx @devcontainers/cli exec --workspace-folder . git switch main
npx @devcontainers/cli exec --workspace-folder . git pull --ff-only
npx @devcontainers/cli exec --workspace-folder . just release-check
```

## 8. Tag and verify GHCR

After the release record is final and all required checks pass on the releasable main
commit, create and push the annotated tag:

```console
npx @devcontainers/cli exec --workspace-folder . git tag -a v1.0.0 -m "v1.0.0"
npx @devcontainers/cli exec --workspace-folder . git push origin v1.0.0
```

Wait for the image workflow. It must publish `1.0.0`, `1.0`, `1`, `latest`, and the
immutable `sha-<full-commit>` tag. Inspect the manifest and confirm both platforms:

```console
npx @devcontainers/cli exec --workspace-folder . docker buildx imagetools inspect ghcr.io/OWNER/REPOSITORY:1.0.0
```

Perform a fresh install in an empty directory with a new external network, disposable
`.env`, and new Compose project. Set
`TASTERR_IMAGE=ghcr.io/OWNER/REPOSITORY:1.0.0`, run `docker compose pull` and
`docker compose up -d --no-build`, then verify health, SPA serving, non-root uid, and
named-volume persistence. Delete every disposable resource after verification.

Publish release notes only after the manifest and fresh install pass. Summarize user-
visible changes, upgrade steps, known limitations, and the immutable image digest;
do not reproduce private release evidence.

## 9. Roll back

Before upgrade, record the running digest and take a validated SQLite backup as
documented in [CONFIGURATION.md](CONFIGURATION.md). To roll back an image-only change,
set `TASTERR_IMAGE` to the preceding known-good digest and force-recreate the service
against the existing volume. If a migration is not backward-compatible, stop the
writer and restore the matching pre-upgrade backup before starting the old digest.
Version 1.0's M6 change has no migration, so its rollback basis is the prior image
digest with the same database file.
