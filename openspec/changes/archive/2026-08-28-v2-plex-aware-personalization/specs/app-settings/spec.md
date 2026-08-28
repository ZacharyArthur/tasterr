## ADDED Requirements

### Requirement: V2 rail capabilities are independently admin-toggleable

The server-owned rail type registry SHALL add `continue-watching`,
`unexpected-picks`, and `household-blend` with the user-facing labels **Continue
Watching**, **Picks You Wouldn't Usually Watch**, and **Something for Everyone
Tonight**. Each type SHALL be absent from the default disabled set and therefore
enabled for existing/fresh settings until an admin disables it. Disablement SHALL
gate the corresponding provider/member/blend work before any Plex, profile, or
catalog fetch. Existing stored settings SHALL remain valid without a migration or
bootstrap rewrite.

#### Scenario: Existing settings enable new types by default

- **WHEN** an existing runtime document predates the v2 enum members
- **THEN** all three v2 types are enabled because none is in its disabled set

#### Scenario: Admin can disable one V2 rail only

- **WHEN** an admin saves `continue-watching` in the disabled set
- **THEN** Continue Watching performs no Plex work while unexpected picks,
  household blend, and all other enabled rail types remain available

#### Scenario: Settings API owns V2 descriptors

- **WHEN** an admin reads settings
- **THEN** the returned rail descriptors include the exact three v2 ids/labels and
  no secret/capability state
