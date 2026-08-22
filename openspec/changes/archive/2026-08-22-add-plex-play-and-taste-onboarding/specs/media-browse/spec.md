## ADDED Requirements

### Requirement: Title detail exposes playable library links

`GET /api/v1/title/{type}/{id}` SHALL surface the typed playback links resolved
with library availability. When Seerr is unavailable, unconfigured, reports the
title neither available nor partially available, or supplies no valid web link, the response SHALL contain no
usable Play target and SHALL still return the TMDB detail normally. No Plex token,
Seerr cookie, internal URL, or raw upstream body SHALL appear in the response.

#### Scenario: Available title includes playback links

- **WHEN** an authenticated client requests detail for an available title with
  valid Seerr links
- **THEN** its availability includes the server-validated web and platform link
  targets

#### Scenario: Seerr failure omits playback without failing detail

- **WHEN** playback links cannot be resolved because Seerr is unavailable
- **THEN** detail still returns with Unknown availability and no Play target

#### Scenario: Non-playable title has no Play target

- **WHEN** Seerr does not mark either title variant available or partially available
- **THEN** detail includes its non-available status but no usable playback link

### Requirement: Detail offers resilient Plex Web and Plex App controls

The detail modal SHALL render a Plex Web link alongside the request affordance for
an available or partially available title with a validated web target. When the chosen variant also
has a validated app target, it SHALL separately render a Plex App link so the user
chooses the destination instead of platform detection hiding the recoverable web path.
On Android, the app link SHALL use the server-provided `intent://` target so Plex
receives the tested `plex://preplay/` data and a missing app falls back to the web
target. On other platforms, the app link SHALL use the validated custom scheme
without scheduling a web fallback. The Plex Web link SHALL open in a new browsing
context so Tasterr remains available for a user-driven retry. The regular variant
SHALL be preferred over 4K, with 4K used when it is the only playable variant. The
controls SHALL carry an explicit experimental qualifier and SHALL be reachable and activatable with the same
keyboard/remote navigation and visible-focus behavior as adjacent detail controls.

#### Scenario: Web remains an explicit choice on every platform

- **WHEN** any user views an available title with a validated web target
- **THEN** Plex Web is offered directly even when a Plex App target is also available

#### Scenario: Plex Web preserves the browse session

- **WHEN** a user activates Plex Web
- **THEN** it opens in a new browsing context and leaves the Tasterr browse session
  available for another activation

#### Scenario: Partially available title remains playable

- **WHEN** Seerr marks a regular or 4K variant partially available with a validated
  web target
- **THEN** the Plex Web and optional Plex App controls use that variant's links

#### Scenario: Available Android title opens a fallback-capable intent

- **WHEN** an Android user activates Plex App for an available title with app and web
  links
- **THEN** the selected href targets the Plex Android package and contains the
  encoded web fallback supplied by the backend

#### Scenario: Missing app target leaves the reliable web path

- **WHEN** an available title has a web target but no validated app target
- **THEN** Plex Web is rendered and Plex App is omitted

#### Scenario: 4K is the only playable variant

- **WHEN** regular media is unavailable and the 4K variant is available with a
  valid web target
- **THEN** the Plex Web and optional Plex App controls use the 4K link set

#### Scenario: No usable link renders no control

- **WHEN** Seerr is down, the title is neither available nor partially available,
  or no valid web target exists
- **THEN** no Plex playback control is rendered and the rest of detail remains operable

#### Scenario: Playback controls disclose handoff reliability

- **WHEN** either Plex playback control is rendered
- **THEN** adjacent plain-language text identifies the handoff as experimental,
  advises retrying Plex Web after sign-in or user switching, and warns that Plex
  App may open Home instead of the title, including as the controls' accessible
  description

#### Scenario: Playback controls participate in modal navigation

- **WHEN** keyboard or remote focus reaches either playback control
- **THEN** it has visible focus, activates as a link, and remains inside the
  detail modal's focus trap
