# Releasing

This procedure is for stable v1 releases. The current package version is
`1.0.1`, its Git tag is `v1.0.1`, and its image is published by the `image` workflow
only after all release changes are squash-merged to protected `main`. The published
`v1.0.0` tag is retained for provenance, but no GitHub Release was announced for it;
`v1.0.1` is the immutable-tag fix-forward and first announced release.

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
storage, database/migration handling, dependency provenance, logs, HTTP hardening,
container build, workflow pins/permissions, licensing, and public-release controls.
Confirm Uvicorn access logs are disabled and the deployment proxy omits or redacts
request query strings.

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

Record the date and result in `docs/releases/v1.0.1.md`. This command intentionally
does not imply that audits, security review, or live contracts passed.

For subsequent releases, the committed evidence file is the pre-tag record. Write
it so it remains true after publication: use an `approved for release` disposition,
not a pending post-tag state, and do not predict a manifest digest or publication
time. The GitHub Release is the authoritative post-tag record for the final digest
and post-tag smoke results.

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
request may not be skipped within a performed v1.0 run.

The release owner may waive a release-candidate rerun only when a complete prior v1.0
baseline passed, the reviewed delta does not change Seerr clients, authentication or
session behavior, request/availability contracts, or the live harness, and the
release evidence records the baseline date/version/scope plus the waiver rationale
without claiming a fresh pass. Any change to those surfaces invalidates the waiver.
Remove the temporary secret file after a run.

## 6. Validate and archive any OpenSpec change

When the release contains an OpenSpec change, run strict validation on its change
branch:

```console
npx @devcontainers/cli exec --workspace-folder . npx --yes @fission-ai/openspec@1.5.0 validate <change-id> --strict --no-interactive
```

After every task is complete, archive before merging so the implementation and
living specs land atomically:

```console
npx @devcontainers/cli exec --workspace-folder . npx --yes @fission-ai/openspec@1.5.0 archive <change-id>
```

Review the archive diff and rerun `just check`. Do not use `--skip-specs` or
`--no-validate`. A release containing only bug fixes, documentation, chores, or
dependency bumps may record OpenSpec as `n/a` and skip this section.

## 7. Bootstrap GitHub, open the PR, and squash merge

Review `git diff --check`, the full diff, and the exact Conventional Commit subject
and pull-request text before executing any external git action. The PR title becomes
the squash commit on `main`; its body names the OpenSpec change, states what/why, and
checks the gate only after it passes.

For the first publication, use this order:

1. Create an empty **public** `ZacharyArthur/tasterr` repository only; do not push
   yet, and do not use a create-and-push shortcut such as `gh repo create --push`.
   Do not generate a README, license, or `.gitignore`. Set the description to
   `Self-hosted TMDB and Seerr discovery with per-user learned taste profiles.` and
   add the topics `self-hosted`, `seerr`, `tmdb`, `plex`, `recommendations`,
   `fastapi`, `react`, and `docker`. The source history must have passed the
   documented secret review before this public creation.
2. Enable Issues. Disable Wiki, Projects, and Discussions. Allow squash merging
   only, enable automatic head-branch deletion, keep the default `GITHUB_TOKEN`
   permissions read-only, and leave workflow pull-request creation/approval
   disabled. Require external Actions to be pinned to full commit SHAs.
3. Disable Actions before the first push. Push the existing base `main` and the
   reviewed `change/v1-public-release-readiness` branch, then re-enable Actions.
   This prevents the old `main` commit from publishing a container during import.
4. Enable the dependency graph, Dependabot alerts, Dependabot security updates,
   secret scanning, push protection, and private vulnerability reporting. The image
   workflow's publishing job is the only job granted `packages: write`; all other
   workflow permissions remain read-only.
5. Open the readiness PR against `main` and let `check`, `e2e`, and
   `container-smoke` report at least once.
6. Configure an active `main` ruleset that requires a pull request with zero approving
   reviews, successful `check`, `e2e`, and `container-smoke` jobs, linear history,
   conversation resolution, and blocks force pushes and deletion. Restrict merge
   type to squash. Public repositories support this ruleset on GitHub Free.
7. Wait for all three required jobs, self-review, resolve every conversation, and
   squash merge. Do not tag the unmerged change branch.

Update local `main` to the squash commit and rerun the deterministic release check:

```console
npx @devcontainers/cli exec --workspace-folder . git switch main
npx @devcontainers/cli exec --workspace-folder . git pull --ff-only
npx @devcontainers/cli exec --workspace-folder . just release-check
```

The image workflow on the merged `main` commit publishes public `main` and
commit-addressed `sha-<full-commit>` candidate tags. Before tagging:

1. Inspect the candidate manifest and confirm both `linux/amd64` and `linux/arm64`.
2. Confirm that the GHCR package is linked to the public repository and explicitly
   public; repository and package visibility are separate controls.
3. From an environment with no GHCR credentials, verify an anonymous pull. Then use
   a disposable empty directory, new Compose project, and `.env` to install the
   commit-SHA
   `ghcr.io/zacharyarthur/tasterr:sha-<full-commit>` candidate. Verify health, SPA
   serving, non-root uid, and named-volume persistence across recreation.
4. Remove the disposable project, volume, network, and secret file. Record the
   manifest digest and generic result in the release evidence.

Documentation-only pushes under `docs/` or to `README.md` do not trigger the image
workflow. A release-preparation merge must include the package-version changes in
backend and frontend metadata, which are outside that ignore set and therefore
publish the required candidate. GitHub does not evaluate path filters for tag
pushes.

## 8. Tag and release

After every pre-tag release-record field is final, create and push the annotated tag:

```console
npx @devcontainers/cli exec --workspace-folder . git tag -a v1.0.1 -m "v1.0.1"
npx @devcontainers/cli exec --workspace-folder . git push origin v1.0.1
```

Wait for the image workflow. It must publish `1.0.1`, `1.0`, `1`, and `latest`, and
leave the existing `sha-<full-commit>` candidate unchanged. Inspect the stable
manifest and confirm both platforms:

```console
npx @devcontainers/cli exec --workspace-folder . docker buildx imagetools inspect ghcr.io/zacharyarthur/tasterr:1.0.1
```

Perform a fresh install in an empty directory with a new external network, disposable
`.env`, and new Compose project. Set
`TASTERR_IMAGE=ghcr.io/zacharyarthur/tasterr:1.0.1`, run `docker compose pull` and
`docker compose up -d --no-build`, then verify health, SPA serving, non-root uid, and
named-volume persistence. Delete every disposable resource after verification.

Publish release notes only after the manifest and fresh install pass. Summarize user-
visible changes, upgrade steps, and known limitations; pin the `1.0.1` digest as the
released artifact and do not reproduce private release evidence. Publish the GitHub
Release only after `1.0.1`, `1.0`, `1`, and `latest` resolve to the expected release
commit, the `sha-<full-commit>` candidate still resolves to its recorded pre-tag
digest, and the tagged clean-install smoke passes.

For subsequent releases, do not create a post-release evidence commit. Record the
final digest, publication time, alias verification, and tagged-image smoke only in
the GitHub Release. This avoids advancing `main` and publishing a new candidate
image solely to describe the release that preceded it.

If any post-tag check fails, do not move, delete, or reuse the published tag.
Document the failure, fix forward through the normal protected-`main` workflow, and
issue the next patch version.

The selected public coordinate is `ZacharyArthur/tasterr` and the container path is
`ghcr.io/zacharyarthur/tasterr`; verify both before repository creation. Repository
settings and registry visibility cannot be proved by the source tree alone.

## 9. Roll back

Before upgrade, record the running digest and take a validated SQLite backup as
documented in [CONFIGURATION.md](CONFIGURATION.md). To roll back an image-only change,
set `TASTERR_IMAGE` to the preceding known-good digest and force-recreate the service
against the existing volume. If a migration is not backward-compatible, stop the
writer and restore the matching pre-upgrade backup before starting the old digest.
Version 1.0's M6 change has no migration, so its rollback basis is the prior image
digest with the same database file.
