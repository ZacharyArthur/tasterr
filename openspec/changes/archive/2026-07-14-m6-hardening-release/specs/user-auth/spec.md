## ADDED Requirements

### Requirement: Forwarding headers affect auth only from trusted peers

The production server SHALL honor forwarded client IP and scheme only when the
request's direct peer matches the validated trusted-proxy allowlist. A trusted
proxy's forwarded client IP SHALL key the tight login bucket, and its forwarded
`https` scheme SHALL cause session cookies to be marked `Secure`. Forwarding headers
from any untrusted peer MUST be ignored so a direct client cannot evade rate limits
or influence cookie security.

#### Scenario: Trusted HTTPS proxy sets effective client and Secure cookie
- **WHEN** an allowlisted proxy forwards a login with a client IP and `https` scheme
- **THEN** the forwarded client IP keys the login bucket and the minted session
  cookie carries `Secure`

#### Scenario: Untrusted forwarding headers are ignored
- **WHEN** a non-allowlisted peer supplies forwarded client IP or scheme headers
- **THEN** auth uses the socket peer and direct request scheme instead

## MODIFIED Requirements

### Requirement: Current user endpoint and logout
`GET /api/v1/auth/me` SHALL return the current user (id, display name, avatar,
admin flag) from local state without calling Seerr, or 401 without a valid
session. `POST /api/v1/auth/logout` SHALL require the same-origin check and shared
loose authenticated-mutation rate limit, then delete the session row and clear the
cookie — revocation is immediate. A rate-limited logout SHALL return 429 without
revoking the session or altering the cookie.

#### Scenario: Me with a valid session
- **WHEN** an authenticated client requests `/auth/me`
- **THEN** it receives the current user without any outbound Seerr call

#### Scenario: Logout revokes server-side
- **WHEN** a client logs out and then replays the old session cookie
- **THEN** the replayed request fails 401

#### Scenario: Logout is rate-limited before revocation
- **WHEN** an authenticated user has exhausted the shared mutation bucket and posts
  logout
- **THEN** the response is 429 and the existing session remains valid
