# Security policy

## Supported versions

| Version | Supported |
|---|---|
| 2.0.x | Yes |
| Pre-release and older builds | No |

Security fixes are made on the current stable 2.0 line. Upgrade to the newest patch
release before reporting an issue that may already be fixed.

## Report a vulnerability privately

Use GitHub's **Security → Advisories → Report a vulnerability** form for this
repository. If the form is unavailable, contact the repository owner privately and
ask for a secure reporting channel. Do not open a public issue, discussion, or pull
request containing exploit details.

Include the affected version, impact, reproduction steps, and the smallest safe proof
of concept. Do not include real API keys, credentials, session material, internal or
live URLs, household identities, viewing history, or database contents. Replace them
with invented values and redact logs before attaching them.

The maintainer aims to acknowledge a complete report within three business days,
confirm scope and severity, and provide progress updates until a fix or documented
disposition is available. Please allow a coordinated fix and release before public
disclosure.

This file is the public reporting and support policy. The engineering threat model,
security invariants, and review checklists live in
[docs/SECURITY.md](docs/SECURITY.md).
