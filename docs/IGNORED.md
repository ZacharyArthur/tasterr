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
| Local-login double-submit could race the user upsert (two concurrent first logins → unique-constraint error) | The submit button disables while pending, SQLite serializes writes, and the worst case is one failed request the user retries. ON CONFLICT upsert plumbing costs more than the failure it prevents at household scale. Revisit if ever observed. |
| SECURITY.md's "constant-time comparison (`secrets.compare_digest`)" has no literal call site | Session validation is an exact-match unique-index lookup of a SHA-256 hash — no comparison of secret material exists in our code at all, which satisfies the checklist's intent more strongly than a `compare_digest` call would. Noted in `auth/sessions.py` so reviews stop re-flagging it. |
| `sessions.seerr_cookie` is stored plaintext | Explicit SPEC §5 decision: the value must be sent verbatim on every M3 per-user Seerr call, and an attacker with host file access is outside the threat model (SECURITY.md). Fernet is reserved for the Plex token, whose blast radius extends beyond Seerr. |
| The live suite cannot exercise the interactive PIN half of the Plex flow | Claiming a PIN requires a human approving at plex.tv — unattendable by construction. The Seerr side (`/auth/plex` with a token) is covered by the optional stored-token live test; the PIN mechanics by recorded fixtures and the 2026-07-02 spike. |
