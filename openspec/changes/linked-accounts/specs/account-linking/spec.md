# account-linking Specification (delta)

## Purpose

Tasterr-owned users and the external accounts (Plex, Jellyfin, Seerr) they
link: how sign-in resolves a user, how links are proven, created, and removed,
how admin and display identity derive from links, and the member account page.

## ADDED Requirements

### Requirement: Users are Tasterr-owned and hold linked accounts

A Tasterr user SHALL be identified only by its local id. External identities
SHALL be stored as linked accounts: a provider (`plex` or `seerr`), the
provider's stable account id, a display name, an optional avatar URL, an
optional Fernet-encrypted credential, sync attempt/success timestamps, and a
link time. A user SHALL hold at most one linked account per provider, and a
provider account SHALL be linked to at most one Tasterr user, both enforced by
unique database constraints. A link SHALL be created only from a successful
authentication of that account performed in the same request; no endpoint SHALL
let anyone, including an admin, assign or edit a link by id.

#### Scenario: One link per provider per user

- **WHEN** a user who already has a Plex link authenticates a different Plex
  account to link it
- **THEN** the link is refused with a generic 409 asking them to unlink first,
  and the existing link is unchanged

#### Scenario: One user per provider account

- **WHEN** a user authenticates a Plex or Seerr account already linked to
  another Tasterr user
- **THEN** the link is refused with a generic 409 that says the account belongs
  to another Tasterr account and explains how to resolve it, without naming
  that user

#### Scenario: Relinking the same account refreshes it

- **WHEN** a user authenticates the account they already have linked
- **THEN** its credential, display name, and avatar are refreshed in place

### Requirement: Sign-in resolves the user through linked accounts

Every sign-in SHALL resolve exactly one Tasterr user in this order: (1) the user
already linked to the sign-in account; otherwise (2) when the Seerr auto-link
attempt for this sign-in succeeded and that Seerr account is linked to a user,
that user, and the sign-in account SHALL be linked to them, except that when that
user already has a different account linked for the sign-in provider, sign-in
SHALL fail with the generic 409 conflict guidance and create nothing; otherwise
(3) a new user, with the sign-in account linked. Steps (2) and (3) SHALL be atomic with
the link writes so concurrent sign-ins cannot create two users for one account;
a unique-constraint conflict SHALL roll back and re-run the full resolution once.
No upstream call (sign-in, auto-link, admin or display read) SHALL run while a
database write transaction is open.
When Seerr is configured and the Seerr auto-link attempt for this sign-in hit an
outage, step (3) SHALL NOT run: a sign-in that would create a new user SHALL fail
with the generic upstream-unavailable error, so an existing member is never split
into a new empty user. An outage is only a transport error, a timeout, or HTTP
502, 503, or 504; every other Seerr response, including a 500 such as Seerr's
"login disabled" when it runs on the other media server, SHALL count as a
refusal. Sign-ins resolved at step (1) whose admission does not depend on Seerr
SHALL proceed; where Seerr is the sign-in gate, its outage still fails sign-in.

#### Scenario: Returning account signs in to its user

- **WHEN** an account already linked to a user signs in
- **THEN** that user's session is minted and no user is created

#### Scenario: Existing member's first Plex sign-in after upgrade

- **WHEN** a member whose user has only a Seerr link signs in with Plex and
  Seerr accepts that Plex token as the same Seerr account
- **THEN** they sign in to their existing user and gain a Plex link, keeping all
  signals and profile data

#### Scenario: Unknown account creates a user

- **WHEN** an account linked to no user signs in and no linked Seerr account
  matches
- **THEN** one new user is created with that account linked

#### Scenario: Seerr outage never creates a split user

- **WHEN** Seerr is configured but unreachable and an account linked to no user
  signs in
- **THEN** sign-in fails with the generic upstream error and no user or link is
  created

#### Scenario: Seerr outage does not block returning accounts

- **WHEN** Seerr is unreachable and an already-linked account signs in through a
  method whose admission does not depend on Seerr
- **THEN** sign-in succeeds at step (1)

#### Scenario: Seerr login disabled is a refusal

- **WHEN** Seerr answers the auto-link attempt with a non-outage error such as a
  500 "login disabled"
- **THEN** the attempt counts as a refusal, and, when the sign-in method's
  admission does not depend on Seerr, a new user may be created without a Seerr
  link

#### Scenario: Bridged user already has the provider linked

- **WHEN** step (2) finds a user who already has a different Plex account linked
  and the sign-in is with Plex
- **THEN** sign-in fails with the generic 409 conflict guidance and nothing is
  created

#### Scenario: Concurrent first sign-ins create one user

- **WHEN** two sign-ins for the same unlinked account complete concurrently
- **THEN** exactly one user and one link exist afterward and both sessions
  belong to that user

#### Scenario: Concurrent bridge sign-ins converge

- **WHEN** a member's Seerr local sign-in and Plex sign-in for the same Seerr
  account complete concurrently and the Plex transaction hits a constraint conflict
- **THEN** the Plex sign-in re-runs the full resolution, lands on the same user
  through step (2), and gains the Plex link

### Requirement: Seerr is auto-linked with the sign-in credentials

When Seerr is configured, each Plex sign-in SHALL attempt a Seerr login with the
same Plex token, and each Seerr local sign-in is itself that Seerr login. A
successful attempt SHALL link that Seerr account when the resolved user has no
Seerr link, has never unlinked Seerr (`users.seerr_unlinked_at` is null), and the
account is unlinked, and SHALL refresh the stored Seerr cookie
when it is the user's linked Seerr account. When the user's Seerr link is a
different Seerr account, the result SHALL be discarded. Credentials used for the
attempt SHALL NOT be stored or logged.

#### Scenario: Plex sign-in links Seerr silently

- **WHEN** a user with no Seerr link signs in with Plex and Seerr accepts the token
- **THEN** that Seerr account is linked with its encrypted cookie and requests
  are enabled without any further step

#### Scenario: Sign-in refreshes the Seerr cookie

- **WHEN** a user whose Seerr link matches the auto-link result signs in
- **THEN** the stored Seerr cookie is replaced with the fresh one

#### Scenario: Unlinked Seerr stays unlinked

- **WHEN** a member who unlinked Seerr later signs in with Plex and
  Seerr accepts those credentials
- **THEN** Seerr is not re-linked and no Seerr history is imported

#### Scenario: Mismatched Seerr account is ignored

- **WHEN** a user's Seerr link is a local Seerr account and their Plex sign-in
  logs into a different Seerr account
- **THEN** the existing Seerr link and cookie are unchanged

### Requirement: Admin derives from any linked account

At each sign-in, `is_admin` SHALL be re-derived from every linked account the
user holds, not only the sign-in account: a Seerr link grants admin when that
Seerr user's permissions (read by id with the global API key) include ADMIN (bit
2). A user SHALL be admin when any check grants it. When no check grants
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

### Requirement: Display identity follows a fixed account priority

At each sign-in, the user's display name and avatar URL SHALL be refreshed from
the highest-priority linked account that answers: Seerr, then Plex. Values from
the sign-in itself SHALL be used where available; otherwise stored link values
SHALL be used. Users SHALL NOT override their display name. Avatar URLs SHALL come
only from the Seerr user record or the plex.tv account. The SPA SHALL show the
user's initials, not an avatar image, for every user.

#### Scenario: Seerr name wins

- **WHEN** a user with Seerr and Plex links has different names on each
- **THEN** the Seerr display name is shown in the shell and household picker

#### Scenario: Plex-only user uses the Plex name

- **WHEN** a user has only a Plex link
- **THEN** the Plex account's name is shown and its avatar URL is stored

### Requirement: Members view and manage their own linked accounts

`GET /api/v1/account` SHALL require the shared session dependency and return,
for each provider configured on this server (a provider is configured when its
sign-in method is currently available; in this change both Plex and Seerr sign-in
are available exactly when Seerr and `TASTERR_SECRET_KEY` are configured), whether the caller has
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
Seerr). A link SHALL be created only when the account would be admitted by signing in
with it at that moment (for Plex, the active Plex sign-in gate, which in this change
is Seerr accepting the token); otherwise the attempt SHALL fail with a
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

### Requirement: Members can unlink accounts

`POST /api/v1/account/links/{provider}/unlink` with `{delete_history: bool}`
SHALL require a session, the same-origin check, and the authenticated mutation
bucket. It SHALL first cancel and await that user's in-flight sync for the
provider within its deadline, so no batch from it commits afterward, and SHALL
hold the same per-user scheduling guard as reset until it commits, so no new
sync can start in between; then delete the link and its credential; for a Plex link, clear the user's cached
Continue Watching entry; for a Seerr link, set `users.seerr_unlinked_at`
so sign-in auto-link no longer re-links Seerr; when
`delete_history` is true it SHALL also delete that source's imported signals
(`seed_request_history` for Seerr, `watched_plex` for Plex) and invalidate the
profile. It SHALL refuse with 409 when no other remaining link belongs to a sign-in method
that is currently available (as defined above), so a member
cannot strand themselves after a configuration change; the check and the delete
SHALL be one atomic operation so concurrent unlinks
cannot remove every link. Tasterr
sessions SHALL stay valid after unlinking, including one signed in with the
unlinked account. `is_admin` SHALL NOT change until the next sign-in.

#### Scenario: Unlink keeps history by default

- **WHEN** a member unlinks Plex with `delete_history` false
- **THEN** the link and token are gone, `watched_plex` signals remain, and no
  further Plex sync or Continue Watching read occurs

#### Scenario: Unlink can delete history

- **WHEN** a member unlinks Plex with `delete_history` true
- **THEN** their `watched_plex` signals are deleted and their profile is
  invalidated

#### Scenario: Last link cannot be removed

- **WHEN** a member tries to unlink their only linked account
- **THEN** the response is 409 and the link is unchanged

#### Scenario: Remaining link must still sign in

- **WHEN** Seerr is no longer configured and a member with Plex and Seerr links
  unlinks Plex
- **THEN** the response is 409 and the Plex link is unchanged

#### Scenario: Unlink stops an in-flight sync

- **WHEN** a member unlinks Plex with `delete_history` true while its history
  sync is running
- **THEN** the sync is cancelled before deletion and no `watched_plex` row is
  written afterward

#### Scenario: Concurrent unlinks keep one link

- **WHEN** a member with exactly two links unlinks both concurrently
- **THEN** exactly one unlink succeeds and the other returns 409

### Requirement: Members can delete their Tasterr account

`POST /api/v1/account/delete` SHALL require a session, the same-origin check, the
authenticated mutation bucket, and a confirmation string equal to the caller's
current display name. It SHALL cancel and await the caller's in-flight sync tasks
within their deadlines and hold the per-user scheduling guard until the delete
commits, then delete the user; the user's cached Continue Watching entry SHALL be
cleared; sessions, links, credentials,
signals, and profile SHALL be removed by cascade, and the response SHALL clear
the session cookie. Nothing SHALL be deleted in any upstream service.

#### Scenario: Deletion removes everything local

- **WHEN** a member confirms deletion with their display name
- **THEN** their user, sessions, links, signals, and profile are gone and the
  old session cookie returns 401

#### Scenario: Wrong confirmation deletes nothing

- **WHEN** the confirmation string does not match
- **THEN** the response is 422 and nothing is deleted

#### Scenario: Deleted accounts can sign in fresh

- **WHEN** a deleted member signs in again with a previously linked account
- **THEN** a new, empty user is created for them

### Requirement: Account page for every member

The SPA SHALL provide an `/account` route for every signed-in user, reached from
the avatar menu, while `/settings` stays admin-only. It SHALL show a Connected
accounts section with one card per configured provider (linked state, account
name, Link or Unlink in the sign-in button style) and a danger zone with "Delete
my Tasterr account". Unconfigured providers SHALL be hidden unless the member has them linked; a
linked provider that is no longer configured SHALL keep a card marked "no longer
available on this server" with Unlink. Unlink SHALL confirm
with an unticked "Also delete history imported from this account" option and
SHALL be disabled with "This is your only way to sign in" when no other link can
currently sign in. Deletion SHALL require
typing the display name and SHALL state that nothing is deleted in Plex or Seerr.
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

### Requirement: Links to an unconfigured provider are dormant

A link whose provider is no longer configured (its sign-in method is not
currently available) SHALL be dormant: no history sync is scheduled for it, no
Continue Watching or other media read uses it, it takes part in no admin check,
and it is not used for silent Seerr re-authentication or Seerr linking. Its
stored credential SHALL be kept until the member unlinks it or deletes their
account, so configuring the provider again resumes everything without relinking.
A dormant link SHALL NOT count as another way to sign in for the unlink rule. The
member SHALL still be able to unlink it.

#### Scenario: Removed provider stops all activity

- **WHEN** the operator removes Plex sign-in and a member with a Plex link loads
  Home
- **THEN** no Plex history sync is scheduled and no Continue Watching read runs

#### Scenario: Dormant link can be unlinked

- **WHEN** a member unlinks a dormant Plex link while another link can sign in
- **THEN** the link and its stored token are deleted

#### Scenario: Re-enabling resumes without relinking

- **WHEN** the operator configures the provider again
- **THEN** the member's existing link and credential work again with no action
  from them
