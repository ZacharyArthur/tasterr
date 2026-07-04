# Ignored review findings

Findings consciously rejected, with rationale — recorded so future reviews
don't re-litigate them. If the rationale stops holding, move the item to
docs/DEFERRED.md or fix it.

| Finding | Rationale |
|---|---|
| `docker-compose.yml` ships the Seerr service commented out | Deliberate: the target household already runs Seerr, and an example that starts a second instance would be actively wrong for the primary deployment. The commented block documents the wiring. Spec-wording follow-up tracked in docs/DEFERRED.md. |
| Devcontainer creation + gate verified in CI | CI runs the identical `just check` on the same toolchain versions; devcontainer breakage surfaces immediately in daily development. A duplicate container-in-CI gate doubles CI time for no new signal. |
| Negative test that every `just check` sub-step propagates failure | Sequential just recipes propagate exit codes by the tool's own contract — a test would exercise `just`, not Tasterr. Demonstrated empirically during review: a failing boundary probe failed the whole gate. |
| Archived m0-scaffold design.md says `node:22-slim`; the image uses `node:24-slim` | Archives are historical records and are not rewritten. Every executable reference (Dockerfile, CI, devcontainer) agrees on node 24. |
