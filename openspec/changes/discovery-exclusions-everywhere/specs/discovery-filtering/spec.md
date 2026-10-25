## ADDED Requirements

### Requirement: Members' watched and dismissed titles stay out of discovery

Each request SHALL apply the caller's personal exclusions to every discovery
surface that household exclusions cover (Home and paginated rails, including
related-title rails, hero slides, household blend, and detail
recommendations/similar lists), with the same exemptions (Search, My List,
Continue Watching, and direct title detail). Personal exclusions SHALL be:

- every title with an active `not_interested` signal from the caller, always;
- while the household `hide_watched_items` setting is on, every title with any
  stored watched signal from the caller (every `watched_*` kind), movie or
  series, whether or not that signal's taste source is switched off.

They SHALL be read from the caller's own stored signals only, SHALL require no
upstream call, SHALL NOT consume the shared verification budget, and SHALL still
apply after that budget's deadline has expired. A request
with any personal exclusion SHALL count as having active filtering, so refill,
hero eligibility, and filtered-empty rules apply. Personal exclusions SHALL NOT
delete or alter any signal, SHALL NOT change taste learning, and SHALL never
affect another member's results except through household blend's existing
participant veto.

#### Scenario: Watched title leaves generic rails

- **WHEN** watched hiding is on and a member has a `watched_plex` signal for a
  trending title
- **THEN** that title is absent from that member's Trending rail, extra pages,
  hero, and detail suggestions, and present for a member who has not watched it

#### Scenario: Related-title rail skips watched candidates

- **WHEN** watched hiding is on and a Because You Watched rail's candidates
  include a title the member watched
- **THEN** that title is not in the rail

#### Scenario: Not interested hides everywhere regardless of setting

- **WHEN** watched hiding is off and a member marks a title Not interested
- **THEN** it is absent from every discovery surface for that member and still
  reachable through Search and direct detail

#### Scenario: Retracting Not interested restores the title

- **WHEN** a member retracts Not interested for a title they have not watched
- **THEN** the title is eligible for discovery again

#### Scenario: Switched-off source still hides

- **WHEN** watched hiding is on and a member has switched Jellyfin history off but
  keeps `watched_jellyfin` rows
- **THEN** those titles stay hidden from discovery while no longer shaping the
  profile

#### Scenario: Cleared history unhides

- **WHEN** a member clears their Plex history
- **THEN** titles hidden only because of `watched_plex` become eligible again

#### Scenario: Watched series is hidden

- **WHEN** watched hiding is on and a member has watched one episode of a series
- **THEN** the series is absent from discovery and still shown in Continue
  Watching when it is in progress

#### Scenario: Exempt surfaces keep watched titles

- **WHEN** watched hiding is on
- **THEN** Search, My List, Continue Watching, and direct title detail still
  return watched titles

#### Scenario: Personal exclusions cost no verification

- **WHEN** a request's only active filtering is personal exclusions
- **THEN** no availability or title-facts lookup runs to apply them, and refill
  of an emptied discover rail stays within three pages
- **AND** personal exclusions still apply to rails filtered after the shared
  verification deadline has expired

## MODIFIED Requirements

### Requirement: Bounded best-effort verification and refill

Active filtering SHALL reuse completed title checks within a request and bound total verification time across all its discovery surfaces, including availability-based ranking boosts while a household filter is enabled. Filtering is active for a request when library hiding or service exclusions are enabled, or when the caller has any personal exclusion. With only personal exclusions, ranking boosts SHALL keep their unfiltered availability lookup outside the verification budget, and the request's shared deadline SHALL still start at its first filtering step so that discover refill stays bounded by it. Unverified titles SHALL remain eligible on errors or deadline expiry. Subscription checks SHALL use current region-scoped catalog metadata rather than long-lived recommendation features. Discover-based rails SHALL attempt bounded refill of at most three source pages; fixed-list sources SHALL retain their existing bounds. Inactive filtering SHALL perform no new verification or refill work.

#### Scenario: Outage does not multiply verification waits
- **WHEN** many titles need verification across multiple rails and an upstream stalls
- **THEN** unfinished verification is cancelled at one shared deadline and unresolved titles remain eligible without another unbounded boost batch

#### Scenario: Current metadata overrides old feature data
- **WHEN** persisted recommendation features list an excluded provider but current catalog metadata does not
- **THEN** the old feature data alone does not hide the candidate

#### Scenario: Discover refill is bounded
- **WHEN** filtering removes titles from a discover source
- **THEN** it seeks eligible replacements within three pages, source exhaustion, and the verification budget, whichever bound is reached first
- **AND** additional page fetches use the remaining deadline and retain earlier results on expiry

#### Scenario: Overlapping checks reuse request-local failures
- **WHEN** simultaneous discovery and ranking-boost checks request the same title during an outage
- **THEN** they share the request-local verification result without caching failures globally or consuming duplicate verification slots

#### Scenario: Personal-only refill stays within the deadline
- **WHEN** only personal exclusions apply, they remove titles from a discover rail's first page so refill is needed, and TMDB stalls on page 2
- **THEN** the rail returns its surviving page-1 titles once the shared deadline expires, without waiting for the stalled page

#### Scenario: Defaults preserve existing behavior
- **WHEN** both household filters are disabled and the caller has no personal exclusion
- **THEN** discovery retains existing source requests and performs no exclusion lookups
