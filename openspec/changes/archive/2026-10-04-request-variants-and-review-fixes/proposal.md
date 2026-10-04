## Why

The picker can misclassify 4K requests, override anime defaults, and hide upstream failures. Extend the existing media-request capability to support explicit standard and 4K variants while preserving Seerr permissions and defaults.

## What Changes

- Support standard and 4K movie/whole-series requests independently, including missing variants of existing titles.
- Enforce fresh Seerr request, media-specific 4K, and advanced permissions server-side.
- Preserve Seerr defaults unless an advanced destination is explicitly chosen.
- Fix discovery races, stale selections, upstream failures, input bounds, and contract tests.
- **BREAKING**: discovery returns a permission-scoped options envelope instead of an unrestricted array.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `media-requests`: request variants, fresh permission gates, validation, and resilient controls.
- `media-availability`: separate standard/4K status alongside the aggregate badge.

## Impact

Seerr client, request/discovery endpoints, availability mapping, generated API types, controls and tests. No new dependencies or database migrations. Implemented on the existing request-destination-override PR branch so review fixes land atomically.

## Non-goals

Season selection, download monitoring, new infrastructure, and automatic live requests. Real dispatch remains operator-verified.
