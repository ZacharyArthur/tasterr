# discovery-filtering Specification

## Purpose
Let households focus discovery on titles they cannot already watch while preserving intentional access and browsing during upstream outages.

## Requirements

### Requirement: Optional household discovery exclusions

When configured, discovery SHALL hide titles with a known available or partial regular or 4K library status and titles with a subscription provider matching any excluded service in the active household region. Pending/processing requests and rental/purchase-only matches SHALL remain eligible. Excluded services SHALL win over selected-service inclusion preferences, and their dedicated rails SHALL be omitted before fetching.

#### Scenario: Either playable library variant hides a title
- **WHEN** library hiding is enabled and a title has regular or 4K available/partial status
- **THEN** the title is excluded from discovery even if the other variant is missing or processing

#### Scenario: Subscription overlap hides a title
- **WHEN** a title is available by subscription on an excluded service in the active region and also on another service
- **THEN** it is excluded from discovery

#### Scenario: Non-matching availability remains eligible
- **WHEN** a title has only pending/processing library status, an excluded service only offers rental/purchase, or the subscription match is in another region
- **THEN** that fact alone does not exclude the title

#### Scenario: Selected and excluded service overlap
- **WHEN** a service is selected for discovery and also excluded
- **THEN** its rail is not fetched, exclusions win elsewhere, and selected-service preferences remain stored
- **AND** selected-service inclusion narrowing remains in effect, including when all selected services are excluded

### Requirement: Discovery coverage and intentional-access exemptions

Exclusions SHALL apply to home and paginated discovery rails, hero slides, household blend, and detail recommendations/similar lists. Personalized candidates SHALL be filtered before ranking without deleting taste signals or excluding source titles from taste learning. Search, My List, Continue Watching, and direct title details SHALL remain accessible. Hero eligibility SHALL be checked independently of any exempt fallback rail.

#### Scenario: All discovery seams enforce the same policy
- **WHEN** a confirmed excluded title occurs in a generic or personalized rail, an extra page, household blend, hero fallback, or detail suggestion
- **THEN** it is absent from that discovery surface

#### Scenario: Intentional access and taste sources survive
- **WHEN** a title is excluded from discovery but is searched, watchlisted, in progress, directly opened, or used as a positive recommendation source
- **THEN** those access and taste-learning paths remain functional

#### Scenario: Hero falls back to a surviving discovery rail
- **WHEN** filtering is active and Trending has no surviving rail
- **THEN** the hero uses the first surviving discovery rail instead of My List or Continue Watching
- **AND** hero eligibility remains independently checked; with filtering inactive the existing first-rail fallback remains

### Requirement: Bounded best-effort verification and refill

Active filtering SHALL reuse completed title checks within a request and bound total verification time across all its discovery surfaces, including availability-based ranking boosts while a household filter is enabled.

#### Details

Filtering is active for a request when library hiding or service exclusions are enabled, or when the caller has any personal exclusion. With only personal exclusions, ranking boosts SHALL keep their unfiltered availability lookup outside the verification budget, and the request's shared deadline SHALL still start at its first filtering step so that discover refill stays bounded by it. Unverified titles SHALL remain eligible on errors or deadline expiry. Subscription checks SHALL use current region-scoped catalog metadata rather than long-lived recommendation features. Discover-based rails SHALL attempt bounded refill of at most three source pages; fixed-list sources SHALL retain their existing bounds. Inactive filtering SHALL perform no new verification or refill work.

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
- **THEN** discovery retains existing source requests and performs no per-title verification lookups

### Requirement: Filtered-empty discovery is a successful outcome

Existing rail minimum sizes SHALL apply after filtering.

#### Details

With filtering active, a home with successfully fetched catalog sources but no eligible/full rails SHALL return a valid empty result rather than an upstream error, including successful sources containing zero titles. Actual total catalog failure SHALL retain the existing error behavior; underfilled exempt lists SHALL NOT count as catalog success. The UI SHALL explain that discovery settings can empty the feed, and saved settings SHALL invalidate stale discovery and household results.

#### Scenario: Exclusions remove every fetched title
- **WHEN** catalog fetches succeed but exclusions remove every title
- **THEN** home returns a successful empty feed and the UI offers an appropriate settings explanation

#### Scenario: Catalog genuinely fails
- **WHEN** all enabled catalog sources fail without successfully fetched items
- **THEN** the existing catalog failure behavior remains
- **AND** underfilled My List or Continue Watching content does not mask the failure

#### Scenario: Catalog succeeds with no titles
- **WHEN** filtering is active and catalog sources successfully return empty lists
- **THEN** home returns a successful empty feed

#### Scenario: Personalized-only sources succeed empty
- **WHEN** filtering is active, only personalized discovery rails are enabled, and a candidate source successfully returns usable cached or fresh data
- **THEN** home may return a successful empty feed when no eligible/full rail remains
- **AND** source detail recommendations/similar, discover and trending count as candidate sources, including empty lists; profile/vector construction, genre metadata, intentional lists and verification alone do not count

#### Scenario: Personalized sources have no success evidence
- **WHEN** no rail survives and no enabled catalog candidate source succeeds, including absent taste signals or all candidate sources failing
- **THEN** the existing catalog failure behavior remains even if verification excluded a title

#### Scenario: Personalized source succeeds despite ordinary source failures
- **WHEN** filtering is active, ordinary enabled catalog rails fail, and an enabled personalized rail successfully reads a candidate source, including a cached empty source
- **THEN** Home may return a successful empty feed when no rail survives
- **AND** an unrelated source detail does not establish success for a personalized rail that never uses it as a candidate source

#### Scenario: Saved settings clear stale discovery
- **WHEN** an admin changes discovery settings
- **THEN** subsequent displayed discovery and household results use the new settings
- **AND** confirmed save completion discards completed and pending household results, including requests made after returning Home while saving was pending; late old blend responses cannot restore them
- **AND** pending discovery reads are cancelled before invalidation so a late pre-save response cannot become the refreshed feed or title suggestions

#### Scenario: Ordinary member refetch preserves household picks
- **WHEN** household members refetch without navigating away from Home
- **THEN** completed picks and pending blend requests remain intact

### Requirement: Members' watched and dismissed titles stay out of discovery

Each request SHALL apply the caller's personal exclusions to every discovery
surface that household exclusions cover (Home and paginated rails, including
related-title rails, hero slides, household blend, and detail
recommendations/similar lists), with the same exemptions (Search, My List,
Continue Watching, and direct title detail).

#### Details

Personal exclusions SHALL be:

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
