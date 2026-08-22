## ADDED Requirements

### Requirement: Availability carries validated Plex playback links

Normalization SHALL carry a Seerr media variant's Plex web and app links in the
typed, secret-free Availability model whenever its status is available or
partially available. The client boundary SHALL accept both Overseerr's `plexUrl`
and Jellyseerr's `mediaUrl`, plus
`iOSPlexUrl`, and SHALL accept the corresponding `plexUrl4k`/`mediaUrl4k` and
`iOSPlexUrl4k` variants. A web link SHALL be retained only when it is a
credential-free HTTPS URL on `app.plex.tv`; an app link SHALL be retained only
when it is a fragment-free `plex://preplay/` URL. Neither link form SHALL carry an
`X-Plex-Token` parameter. The backend SHALL construct any Android intent URL from
those validated inputs and include an encoded web fallback; the browser SHALL NOT
assemble it.

Jellyseerr deployments backed by Jellyfin or Emby can emit `mediaUrl` pointing at
the configured Jellyfin or Emby host. The `app.plex.tv` allowlist SHALL reject that
link, so no Plex playback control is expected for that deployment.

#### Scenario: Overseerr aliases normalize

- **WHEN** available `mediaInfo` contains `plexUrl` and `iOSPlexUrl`
- **THEN** Availability contains the validated regular web/app links and an
  Android intent with the web link as its browser fallback

#### Scenario: Jellyseerr aliases normalize

- **WHEN** available `mediaInfo` contains `mediaUrl` and `iOSPlexUrl`
- **THEN** Availability contains the same downstream link shape as Overseerr

#### Scenario: 4K-only title remains playable

- **WHEN** `status4k` is available and only the 4K link aliases are populated
- **THEN** Availability is available and carries the validated 4K playback links

#### Scenario: Partially available media carries links

- **WHEN** a regular or 4K media variant is partially available and supplies valid
  playback links
- **THEN** Availability retains that variant's validated playback links

#### Scenario: Mixed regular and 4K states use highest fulfillment

- **WHEN** regular and 4K variants report different fulfillment states
- **THEN** Availability exposes the highest overall state and retains playback
  links only for each variant independently marked available or partially available

#### Scenario: Unsafe upstream link is dropped

- **WHEN** Seerr supplies a web or app link outside the accepted
  scheme/host/path or credential contract
- **THEN** normalization omits that link and does not return it to the browser

#### Scenario: Token-bearing playback link is dropped

- **WHEN** a web or app link carries an `X-Plex-Token` parameter in any casing
- **THEN** normalization rejects that link before it or a derived Android intent
  can be serialized to the browser

#### Scenario: Non-playable variant has no playback links

- **WHEN** Seerr does not mark either regular or 4K media available or partially
  available
- **THEN** Availability carries no usable playback link even if stray link fields
  were present upstream

### Requirement: Live Seerr playback-link contract is opt-in

The pytest-marked live Seerr suite SHALL validate the available-title link shape
against an operator-supplied household title while printing only the Seerr version
and generic outcomes. It SHALL NOT print URLs, title ids, or upstream bodies, and
it SHALL remain excluded from `just check` and CI.

#### Scenario: Live suite validates configured link aliases

- **WHEN** the live suite runs with a Plex-backed available household title configured
- **THEN** it confirms that typed media info exposes usable playback-link fields
  without recording their values

#### Scenario: Ordinary gate remains offline

- **WHEN** `just check` runs
- **THEN** no live playback-link contract executes
