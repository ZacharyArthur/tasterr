## ADDED Requirements

### Requirement: Detail overlay preserves one browsing context

The SPA detail overlay SHALL preserve the original browse location while the
user opens related titles. Related-title navigation SHALL replace the active
detail history entry so closing any related detail returns directly to the
original browse view. While a detail overlay is mounted, the underlying document
SHALL NOT scroll, and its prior scroll behavior SHALL be restored when the
overlay unmounts. Taste controls SHALL adopt newer server-provided flags when
refreshed detail data arrives for the same title.

#### Scenario: Related title closes to original browse view

- **WHEN** a user opens a title from a browse card, opens one or more titles from
  More like this, and then closes the detail overlay
- **THEN** the overlay closes directly to the original browse view without
  revealing each previously viewed detail

#### Scenario: Direct detail remains directly closable

- **WHEN** a user deep-links to a title, opens a related title, and closes the
  overlay
- **THEN** the app returns Home without revealing the first detail

#### Scenario: Background scrolling is locked and restored

- **WHEN** a detail overlay opens and later closes
- **THEN** the underlying document cannot scroll while open and its previous
  overflow behavior is restored on close

#### Scenario: Refreshed watchlist state replaces stale cached state

- **WHEN** a user changes a title's My List state, closes it, and reopens cached
  detail data before the refreshed server response arrives
- **THEN** the control adopts the refreshed server state without requiring an
  extra toggle

### Requirement: Title detail exposes a canonical external reference

`GET /api/v1/title/{type}/{id}` SHALL include a secret-free external URL for the
corresponding TMDB movie or TV page. The SPA SHALL render that server-provided
URL as an accessible external link from the detail view and open it in a separate
browsing context without granting the destination access to the opener.

#### Scenario: Movie detail links to its TMDB page

- **WHEN** an authenticated client requests a known movie detail
- **THEN** the response's external URL identifies that movie on TMDB

#### Scenario: TV detail links to its TMDB page

- **WHEN** an authenticated client requests a known TV detail
- **THEN** the response's external URL identifies that series on TMDB

#### Scenario: External link is isolated from the app

- **WHEN** the user activates the TMDB link in a detail view
- **THEN** it opens in a separate browsing context with opener access disabled
