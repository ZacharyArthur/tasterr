## MODIFIED Requirements

### Requirement: Seerr is auto-linked with the sign-in credentials

When Seerr is configured, each Plex sign-in SHALL attempt a Seerr login with the
same Plex token, each Jellyfin sign-in SHALL attempt Seerr's Jellyfin login with
the same username and password within that request, and each Seerr local sign-in
is itself that Seerr login. A Plex or Jellyfin attempt SHALL be skipped, without
contacting Seerr's login endpoint, when Seerr is known to refuse that method (as
defined in "Seerr login methods follow Seerr's own settings"); a skipped attempt
SHALL be treated exactly as a Seerr refusal. A Seerr refusal SHALL NOT block a
Jellyfin sign-in; a Seerr outage SHALL block only a sign-in that would create a
new user. A successful attempt SHALL link that Seerr account when the resolved
user has no Seerr link, has never unlinked Seerr (`users.seerr_unlinked_at` is
null), and the account is unlinked, and SHALL refresh the stored Seerr cookie
when it is the user's linked Seerr account. When the user's Seerr link is a
different Seerr account, the result SHALL be discarded. Credentials used for the
attempt SHALL NOT be stored or logged.

#### Scenario: Plex sign-in links Seerr silently

- **WHEN** a user with no Seerr link signs in with Plex and Seerr accepts the token
- **THEN** that Seerr account is linked with its encrypted cookie and requests
  are enabled without any further step

#### Scenario: Jellyfin sign-in links Seerr silently

- **WHEN** a user with no Seerr link signs in with Jellyfin and Seerr accepts the
  same Jellyfin credentials
- **THEN** that Seerr account is linked with its encrypted cookie and the
  password is discarded

#### Scenario: Jellyfin credentials are not sent to a Plex-backed Seerr

- **WHEN** a user signs in with Jellyfin and Seerr's public settings report a
  Plex media server
- **THEN** Seerr's Jellyfin login endpoint is not called, sign-in succeeds, and no
  Seerr link is created

#### Scenario: Unknown Seerr settings keep the attempt

- **WHEN** a user signs in with Jellyfin and Seerr's public settings cannot be
  read or lack the media server fields
- **THEN** the Seerr Jellyfin login is attempted as before

#### Scenario: Sign-in refreshes the Seerr cookie

- **WHEN** a user whose Seerr link matches the auto-link result signs in
- **THEN** the stored Seerr cookie is replaced with the fresh one

#### Scenario: Unlinked Seerr stays unlinked

- **WHEN** a member who unlinked Seerr later signs in with Plex or Jellyfin and
  Seerr accepts those credentials
- **THEN** Seerr is not re-linked and no Seerr history is imported

#### Scenario: Mismatched Seerr account is ignored

- **WHEN** a user's Seerr link is a local Seerr account and their Plex sign-in
  logs into a different Seerr account
- **THEN** the existing Seerr link and cookie are unchanged

### Requirement: Connect Seerr dialog names the active credentials

The Connect Seerr dialog, on the Account page and in the request control, SHALL
show a fixed caption above its credential fields naming the account they belong
to: "Sign in with your Seerr account email and password." for Seerr local
sign-in, and "Sign in with your Jellyfin username and password." for Seerr's
Jellyfin login. The dialog SHALL open on the Seerr local form when local sign-in
is offered, otherwise on the Jellyfin form when Seerr's Jellyfin login is
offered; when neither form is offered it SHALL show no credential form. The
"Use my Plex account" action SHALL appear whenever the `plex` method is offered
and usable by the member (they have a usable Plex link), whatever forms are
offered. The guidance defined in "Seerr login methods follow Seerr's own
settings" SHALL appear when the member has no usable Plex action and no
Jellyfin form is offered; the local form MAY show alongside it. So the dialog
shows guidance alone exactly when it offers no form and no Plex action. Only when both forms are offered,
a toggle SHALL be shown, labelled by the form it switches to: "Use Jellyfin
credentials" while the Seerr local form shows, and "Use Seerr email instead"
while the Jellyfin form shows.

#### Scenario: Default form names Seerr credentials

- **WHEN** a member opens the Connect Seerr dialog and local sign-in is offered
- **THEN** the Email and Password fields show under the Seerr account caption

#### Scenario: Switching to Jellyfin relabels the dialog

- **WHEN** a member chooses "Use Jellyfin credentials"
- **THEN** the Username and Password fields show under the Jellyfin caption and
  the toggle reads "Use Seerr email instead"

#### Scenario: Switching back restores the Seerr form

- **WHEN** a member on the Jellyfin form chooses "Use Seerr email instead"
- **THEN** the Email and Password fields and the Seerr account caption return and
  the toggle reads "Use Jellyfin credentials"

#### Scenario: No Jellyfin option still names the credentials

- **WHEN** Jellyfin is not offered, local sign-in is offered, and a member opens
  the dialog
- **THEN** no toggle is shown and the Seerr local form shows under the Seerr
  account caption

#### Scenario: Neither form offered shows guidance only

- **WHEN** neither Seerr local sign-in nor Seerr's Jellyfin login is offered, the
  member has no usable Plex method, and they open the dialog
- **THEN** no credential form, toggle, or Plex action is shown, only the guidance

#### Scenario: Neither form offered keeps the Plex action

- **WHEN** Seerr is Plex-backed with media server login on and local login off,
  and a member with a usable Plex link opens the dialog
- **THEN** "Use my Plex account" is shown with no credential form, toggle, or
  guidance

#### Scenario: Local login refused opens the Jellyfin form

- **WHEN** Seerr is known to refuse local login, accepts Jellyfin login, and
  Jellyfin is configured
- **THEN** the dialog opens on the Jellyfin form under the Jellyfin caption with
  no toggle

## ADDED Requirements

### Requirement: Seerr login methods follow Seerr's own settings

Tasterr SHALL derive, from Seerr's public settings, whether Seerr accepts each
Seerr login method: `plex` when Seerr reports a Plex media server and media
server login enabled; `jellyfin` when Seerr reports a Jellyfin media server and
media server login enabled; `local` when Seerr reports local login enabled. A
method is **known refused** only when the settings were read and the relevant
fields are present, well-typed, and do not satisfy that condition. Otherwise
(Seerr unconfigured, unreachable, a failed or malformed read, a missing field, or
an unrecognized media server value) the method is **unknown** and SHALL be
treated as accepted, preserving prior behavior. An Emby media server SHALL count
as refusing `plex` and `jellyfin`. The read SHALL be cached for a bounded time,
SHALL keep serving the last known value through a bounded outage window, and
SHALL never block browsing.

`GET /api/v1/account` SHALL include `seerr_accepts` with one boolean per method
(`plex`, `jellyfin`, `local`), false only when known refused. It SHALL carry no
other Seerr configuration. `POST /api/v1/account/links/seerr` with a method that
is known refused SHALL return 409 with a fixed message stating Seerr does not
accept that sign-in method, SHALL NOT forward the submitted credentials or stored
token to Seerr, and SHALL store nothing. This check SHALL run after the existing
availability checks (503 rules are unchanged).

The Account page SHALL offer only Seerr link methods that are not known refused.
When the member has no Seerr link, no usable `plex` method (offered and backed by
their usable Plex link), and no offered `jellyfin` method, the page SHALL explain
the remaining options in plain text, alongside the local form when `local` is
offered: link Plex when Seerr accepts Plex, or ask the
household admin for a Seerr local account when Seerr accepts local login, or that
requests are unavailable for this account otherwise.

#### Scenario: Plex-backed Seerr hides the Jellyfin method

- **WHEN** Seerr reports a Plex media server with media server login and local
  login enabled, and a member opens the Account page
- **THEN** `seerr_accepts` is `plex: true, jellyfin: false, local: true` and the
  Seerr section offers no Jellyfin option

#### Scenario: Refused method is not forwarded

- **WHEN** a member posts a Seerr link with method `jellyfin` while Seerr is
  known to refuse Jellyfin login
- **THEN** the response is 409 with the fixed explanation, Seerr receives no
  login call, and nothing is stored

#### Scenario: Unreadable settings keep every method

- **WHEN** Seerr's public settings cannot be read and no value is cached
- **THEN** `seerr_accepts` reports every method true and the Account page offers
  the same methods as before this change

#### Scenario: Jellyfin-only member is told what to do

- **WHEN** a member with only a Jellyfin link opens the Account page and Seerr
  accepts only Plex and local login
- **THEN** the Seerr section offers local sign-in and explains that the household
  admin can create a Seerr local account, or that linking Plex enables requests

#### Scenario: Summary carries no Seerr configuration

- **WHEN** the account summary is inspected
- **THEN** `seerr_accepts` contains only three booleans and no media server name,
  URL, or other Seerr setting
