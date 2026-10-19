# account-linking Specification (delta)

## MODIFIED Requirements

### Requirement: Account page for every member

The SPA SHALL provide an `/account` route for every signed-in user, reached from
the avatar menu, while `/settings` stays admin-only. It SHALL show a Connected
accounts section with one card per configured provider (linked state, account
name, Link or Unlink in the sign-in button style) and a danger zone with "Delete
my Tasterr account". Unconfigured providers SHALL be hidden unless the member has them linked or still
has imported signals from them; an unlinked one kept for its signals shows only
its taste-source controls, and a linked provider that is no longer configured SHALL keep a card marked "no longer
available on this server" with Unlink. Unlink SHALL confirm
with an unticked "Also delete history imported from this account" option and
SHALL be disabled with "This is your only way to sign in" when no other link can
currently sign in. Deletion SHALL require
typing the display name and SHALL state that nothing is deleted in Plex, Jellyfin, or Seerr.
A link conflict SHALL show the resolution steps without naming the other user:
sign in with each account, keep the one you want, delete the other Tasterr
account from its account page, then link again.

#### Scenario: Member opens the account page

- **WHEN** a non-admin chooses Account from the avatar menu
- **THEN** `/account` shows their connected accounts and the danger zone

#### Scenario: Last link unlink is disabled

- **WHEN** a member has only one linked account
- **THEN** its Unlink control is disabled with an explanation

#### Scenario: Conflict explains the way out

- **WHEN** linking fails because the account belongs to another Tasterr user
- **THEN** the page explains how to keep one Tasterr account, delete the other,
  and relink, without naming the other user

#### Scenario: Retained history keeps a card after the provider is removed

- **WHEN** a member unlinked Jellyfin, kept its history, and the operator then
  removed Jellyfin
- **THEN** a Jellyfin card with only the taste-source toggle and clear action
  remains

### Requirement: Members view and manage their own linked accounts

`GET /api/v1/account` SHALL require the shared session dependency and return,
for each provider configured on this server (a provider is configured when its
sign-in method is available as `/auth/methods` reports it: Plex when
`PLEX_SERVER_ID` is set or Seerr is configured, Jellyfin when its URL and API key
are set, Seerr when Seerr is configured, each also requiring
`TASTERR_SECRET_KEY`), whether the caller has
it linked and
that link's display name and link time, plus whether unlinking is allowed. A
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
  longer configured, and any unconfigured provider with retained imported
  signals, the last two flagged `available: false`, each with linked state,
  display name, link time, and unlink eligibility, and no ids or credentials

#### Scenario: Link Seerr with the stored Plex token

- **WHEN** a member with a Plex link and no Seerr link chooses "Use my Plex
  account"
- **THEN** Seerr is logged into with the stored token and linked without any
  credential entry

#### Scenario: Link Jellyfin from the account page

- **WHEN** a member submits Jellyfin credentials the server accepts
- **THEN** that Jellyfin user is linked by id, no Jellyfin token or password is
  stored, and its history sync becomes eligible

#### Scenario: Plex account the gate would refuse cannot be linked

- **WHEN** a member links a Plex account that Plex sign-in would currently refuse
- **THEN** the response is a generic 403 and no link or token is stored

#### Scenario: Wrong Seerr password stays generic

- **WHEN** a member submits Seerr local credentials that Seerr rejects
- **THEN** the response is a generic 401 and nothing is linked or stored
