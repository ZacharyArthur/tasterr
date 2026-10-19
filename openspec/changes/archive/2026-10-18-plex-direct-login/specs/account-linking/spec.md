# account-linking Specification (delta)

## MODIFIED Requirements

### Requirement: Admin derives from any linked account

At each sign-in, `is_admin` SHALL be re-derived from every linked account the
user holds, not only the sign-in account: a Seerr link grants admin when that
Seerr user's permissions (read by id with the global API key) include ADMIN (bit
2), and, when `PLEX_SERVER_ID` is set, a Plex link grants admin when the
link's token sees that server as `owned`. A user SHALL be admin when any check
grants it. When no check grants
admin, the previous `is_admin` SHALL be kept if any check errored, and SHALL
become false only when every check completed without granting it. A check
errors only on an outage (transport error, timeout, or HTTP 502, 503, or 504);
any other failure, including a 404 for a deleted upstream user or a 401 for a
revoked token, completes without a grant. A provider's check exists only while that
provider is configured: a link to a provider the operator has since unconfigured
neither grants admin nor counts as an error. Admin SHALL NOT be re-derived on link, unlink, or between
sign-ins.

#### Scenario: Seerr admin bit grants admin

- **WHEN** a user whose Seerr link has the ADMIN bit signs in with any method
- **THEN** `is_admin` is true

#### Scenario: Demotion applies at the next sign-in

- **WHEN** a member's Seerr ADMIN bit is removed, no other linked account grants
  admin, and they later sign in again
- **THEN** `is_admin` becomes false at that sign-in

#### Scenario: Deleted upstream admin is demoted

- **WHEN** a user's only admin grant came from a Seerr account that has since
  been deleted (Seerr answers 404) and they sign in
- **THEN** that check completes without a grant and `is_admin` becomes false

#### Scenario: Upstream outage keeps the previous admin state

- **WHEN** no admin check grants admin and at least one check errors during a
  sign-in (for example Seerr is down for a Seerr admin who is a shared Plex user)
- **THEN** the user's previous `is_admin` value is kept

#### Scenario: Plex server owner is admin without Seerr

- **WHEN** the owner of the `PLEX_SERVER_ID` server signs in on a deployment
  without Seerr
- **THEN** `is_admin` is true

#### Scenario: Shared Plex user is not admin

- **WHEN** a user whose Plex account sees the configured server as shared, not
  owned, signs in with no other admin grant
- **THEN** `is_admin` is false

### Requirement: Members view and manage their own linked accounts

`GET /api/v1/account` SHALL require the shared session dependency and return,
for each provider configured on this server (a provider is configured when its
sign-in method is available as `/auth/methods` reports it: Plex when
`PLEX_SERVER_ID` is set or Seerr is configured, Seerr when Seerr is configured,
each also requiring `TASTERR_SECRET_KEY`), whether the caller has
it linked and
that link's display name and link time, plus whether unlinking is allowed. A
provider the caller has linked but that is no longer configured SHALL also be
returned, flagged `available: false`. It
SHALL NOT return provider account ids, credentials, sync internals, or any other
user's data. Linking SHALL be: Plex via a session-gated PIN flow
(`POST /api/v1/account/links/plex/pin` and `.../pin/poll`, mirroring sign-in
handles, popup, and same-origin rules); linking Seerr manually SHALL clear
`users.seerr_unlinked_at`; Seerr via
`POST /api/v1/account/links/seerr` with method `plex` (one step, using the
caller's stored Plex token; 409 when the caller has no Plex link) or `local` (email and password forwarded once to
Seerr). A link-creation endpoint for a provider whose sign-in method is unavailable
SHALL return 503 and store nothing; unlinking is never blocked by availability. A link SHALL be created only when the account would be admitted by signing in
with it at that moment (for Plex, the active Plex sign-in gate: Seerr accepting
the token when `PLEX_SERVER_ID` is unset); otherwise the attempt SHALL fail with a
generic 403 and store nothing, so every link is a real way to sign in. When the admission check cannot complete
because of an upstream outage, the attempt SHALL fail with the generic upstream
error and store nothing. A Seerr
login made only to check a Plex link's admission SHALL be discarded: it never
links Seerr or stores a cookie ("Use my Plex account" links Seerr). Link attempts SHALL enforce the same-origin check, the authenticated
mutation bucket, and, for PIN creation and credential-forwarding links, the tight
login bucket; the link PIN poll is gated by its unguessable single-use handle and
exempt from the login bucket, as the sign-in poll is. A link PIN handle SHALL
be bound to the session that created it and to linking; a poll from any other
session, or from the sign-in poll endpoint, SHALL fail as an unknown handle, and
the link poll SHALL refuse sign-in handles the same way. Failures SHALL be generic.

#### Scenario: Account summary is owner-scoped and secret-free

- **WHEN** a member requests `/account`
- **THEN** the response lists configured providers, plus any linked provider no
  longer configured flagged `available: false`, each with linked state,
  display name, link time, and unlink eligibility, and no ids or credentials

#### Scenario: Link Seerr with the stored Plex token

- **WHEN** a member with a Plex link and no Seerr link chooses "Use my Plex
  account"
- **THEN** Seerr is logged into with the stored token and linked without any
  credential entry

#### Scenario: Plex account the gate would refuse cannot be linked

- **WHEN** a member links a Plex account that Plex sign-in would currently refuse
- **THEN** the response is a generic 403 and no link or token is stored

#### Scenario: Wrong Seerr password stays generic

- **WHEN** a member submits Seerr local credentials that Seerr rejects
- **THEN** the response is a generic 401 and nothing is linked or stored

## ADDED Requirements

### Requirement: Plex links require access to the configured server

When `PLEX_SERVER_ID` is set, linking a Plex account from the account page SHALL
require that the account's plex.tv resources include that server, using the
same check as Plex sign-in; otherwise the link SHALL be refused with a generic
403 and nothing stored. Linking a Plex account SHALL be available only when Plex
sign-in is available, and linking a Seerr account only when the Seerr sign-in
method is available;
otherwise the link endpoints return 503 and store nothing.

#### Scenario: Plex account without server access cannot be linked

- **WHEN** a member links a Plex account that cannot see the configured server
- **THEN** the response is a generic 403 and no link or token is stored
