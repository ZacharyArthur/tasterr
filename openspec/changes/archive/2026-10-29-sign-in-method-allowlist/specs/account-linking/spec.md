## MODIFIED Requirements

### Requirement: Members view and manage their own linked accounts

`GET /api/v1/account` SHALL require the shared session dependency and return,
for each provider configured on this server (a provider is configured when its
integration is set up: Plex when `PLEX_SERVER_ID` is set or Seerr is configured,
Jellyfin when its URL and API key are set, Seerr when Seerr is configured, each
also requiring `TASTERR_SECRET_KEY`; the admin sign-in allowlist does not affect
whether a provider is configured), whether the caller has
it linked and
that link's display name and link time, whether unlinking is allowed, and
whether the provider is currently available for sign-in (`sign_in`, as defined in
`user-auth`). A
provider the caller has linked but that is no longer configured SHALL also be
returned, flagged `available: false`. A provider that is neither configured nor
linked but for which the caller still has imported signals SHALL also be
returned, flagged `available: false` and unlinked, so its taste-source controls
stay reachable. It
SHALL NOT return provider account ids, credentials, sync internals, or any other
user's data. Linking SHALL be: Plex via a session-gated PIN flow
(`POST /api/v1/account/links/plex/pin` and `.../pin/poll`, mirroring sign-in
handles, popup, and same-origin rules); linking Seerr manually SHALL clear
`users.seerr_unlinked_at`; Jellyfin via
`POST /api/v1/account/links/jellyfin` (username and password forwarded once to
Jellyfin, and the resulting token logged out as at sign-in); Jellyfin credentials, for Jellyfin or Seerr linking, SHALL follow
the empty-password rule of Jellyfin sign-in; Seerr via
`POST /api/v1/account/links/seerr` with method `plex` (one step, using the
caller's stored Plex token; 409 when the caller has no Plex link), `jellyfin` (Jellyfin username and password
forwarded once to Seerr's Jellyfin login), offered and accepted only while Jellyfin is
configured (otherwise 503), or `local` (email and password forwarded
once to
Seerr). A link-creation endpoint for a provider that is not configured SHALL
return 503 and store nothing; linking a configured provider SHALL NOT depend on
whether it is offered for sign-in; unlinking is never blocked by availability. A
link SHALL be created only when the account would pass that provider's sign-in
admission checks at that moment, regardless of the sign-in allowlist (for Plex,
the active Plex sign-in gate: Seerr accepting
the token when `PLEX_SERVER_ID` is unset); otherwise the attempt SHALL fail with a
generic 403 and store nothing. When the admission check cannot complete
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
  longer configured, and any unconfigured provider with retained imported
  signals, the last two flagged `available: false`, each with linked state,
  display name, link time, unlink eligibility, and sign-in availability, and no
  ids or credentials

#### Scenario: Link Seerr with the stored Plex token

- **WHEN** a member with a Plex link and no Seerr link chooses "Use my Plex
  account"
- **THEN** Seerr is logged into with the stored token and linked without any
  credential entry

#### Scenario: Link Jellyfin from the account page

- **WHEN** a member submits Jellyfin credentials the server accepts
- **THEN** that Jellyfin user is linked by id, no Jellyfin token or password is
  stored, and its history sync becomes eligible

#### Scenario: Link a provider not offered for sign-in

- **WHEN** Plex is configured but not offered for sign-in and a member links Plex
- **THEN** the link is created, Plex history and Continue Watching work, and the
  summary reports Plex with `available: true` and `sign_in: false`

#### Scenario: Plex account the gate would refuse cannot be linked

- **WHEN** a member links a Plex account that Plex sign-in would currently refuse
- **THEN** the response is a generic 403 and no link or token is stored

#### Scenario: Wrong Seerr password stays generic

- **WHEN** a member submits Seerr local credentials that Seerr rejects
- **THEN** the response is a generic 401 and nothing is linked or stored

### Requirement: Links to an unconfigured provider are dormant

A link whose provider is no longer configured (as defined in "Members view and
manage their own linked accounts"; a provider that is configured but not offered
for sign-in is not dormant) SHALL be dormant: no history sync is scheduled for it,
no Continue Watching or other media read uses it, it takes part in no admin check,
and it is not used for silent Seerr re-authentication or Seerr linking. Its
stored credential SHALL be kept until the member unlinks it or deletes their
account, so configuring the provider again resumes everything without relinking.
A dormant link SHALL NOT count as another way to sign in for the unlink rule. The
member SHALL still be able to unlink it.

#### Scenario: Removed provider stops all activity

- **WHEN** the operator removes Plex sign-in configuration and a member with a
  Plex link loads Home
- **THEN** no Plex history sync is scheduled and no Continue Watching read runs

#### Scenario: Not offered is not dormant

- **WHEN** the admin stops offering Plex for sign-in and a member with a Plex link
  loads Home
- **THEN** Plex history sync and Continue Watching continue as before

#### Scenario: Dormant link can be unlinked

- **WHEN** a member unlinks a dormant Plex link while another link can sign in
- **THEN** the link and its stored token are deleted

#### Scenario: Re-enabling resumes without relinking

- **WHEN** the operator configures the provider again
- **THEN** the member's existing link and credential work again with no action
  from them

### Requirement: Plex links require access to the configured server

When `PLEX_SERVER_ID` is set, linking a Plex account from the account page SHALL
require that the account's plex.tv resources include that server, using the
same check as Plex sign-in; otherwise the link SHALL be refused with a generic
403 and nothing stored. Linking a Plex account SHALL be available only when Plex
is configured, and linking a Seerr account only when Seerr is configured (as
defined in "Members view and manage their own linked accounts"), whether or not
either is offered for sign-in;
otherwise the link endpoints return 503 and store nothing.

#### Scenario: Plex account without server access cannot be linked

- **WHEN** a member links a Plex account that cannot see the configured server
- **THEN** the response is a generic 403 and no link or token is stored

#### Scenario: Plex linking works while Plex is not offered for sign-in

- **WHEN** Plex is configured but not offered for sign-in and a member links a
  Plex account that can see the configured server
- **THEN** the link is created

## ADDED Requirements

### Requirement: Members without an offered sign-in method are warned

Turning a sign-in method off SHALL NOT end existing sessions. When none of a
member's linked providers is available for sign-in, the Account page SHALL show a
persistent warning that they will not be able to sign in again after this session
ends, naming the methods currently offered that they can link. The unlink rule's
"another way to sign in" SHALL count only linked providers available for sign-in,
so a member cannot unlink their last offered method.

#### Scenario: Stranded member keeps their session and is told

- **WHEN** the admin stops offering Plex and a signed-in member's only link is Plex
- **THEN** the member stays signed in and their Account page warns them to link
  Jellyfin or Seerr, whichever are offered

#### Scenario: Last offered method cannot be unlinked

- **WHEN** only Jellyfin is offered and a member with Plex and Jellyfin links
  unlinks Jellyfin
- **THEN** the response is 409 and the Jellyfin link is unchanged
