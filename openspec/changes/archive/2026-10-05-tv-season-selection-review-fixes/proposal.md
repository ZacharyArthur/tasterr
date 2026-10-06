## Why

Season selection can report success when Seerr creates no request, offer disabled Specials, and include empty seasons outside Seerr's whole-series contract. This follow-up hardens the existing media-requests capability before PR #40 lands.

## What Changes

- Honor Seerr partial-request policy: disabled/unverified support permits only regular whole-series requests; Specials use Seerr in this mode.
- Pin the requested variant while a season dialog is open.
- Discover Specials support from Seerr public settings and enforce it at submission.
- Select only seasons with episodes; preserve the unchanged whole-series body.
- Treat Seerr 202 as failure without a taste signal.
- Fix nested focus precedence/restoration and configuration-independent movie validation.
- Cover the detail season list, nested Escape, and whole-series browser contract.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `media-requests`: capability-aware Specials, eligible season defaults and no-op request rejection.

## Impact

Seerr client, request/destination API, generated frontend types, season picker, shared focus trap and regression tests. No new dependencies, configuration or migrations. Preserve the original contribution and append fixes to the existing PR branch.

## Non-goals

Live Sonarr dispatch verification, new request UI, and changes to quota or approval rules.
