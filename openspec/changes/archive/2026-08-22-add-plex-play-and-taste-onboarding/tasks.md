## 1. Plex Playback Links

- [x] 1.1 Extend `SeerrMediaInfo` with regular/4K status and Overseerr/Jellyseerr playback-link aliases, with recorded client fixtures for both flavors and unknown-field tolerance.
- [x] 1.2 Normalize available playback variants into validated web/app/Android-intent links, preserve Seerr-down degradation, and cover status, unsafe URL, API serialization, PublicConfig/boundary, and opt-in live-contract behavior.
- [x] 1.3 Add the initial accessible detail-modal Play control with regular-first/4K fallback and platform selection, covered by frontend rendering, href, absent-link, and focus tests (superseded by 9.2 and 10.2).

## 2. Onboarding State and API

- [x] 2.1 Add Alembic revision `0005` and the `User.taste_onboarding_seen` model field, covering fresh upgrade, existing-row default, rollback, and schema consistency.
- [x] 2.2 Reserve cold-start seeding before task dispatch so onboarding can distinguish pending from empty while preserving single-flight, failure cleanup, and non-blocking login tests.
- [x] 2.3 Add session-scoped onboarding status/submission endpoints that persist dismissal and batch existing `watchlist` signals with one profile refresh, covering validation, idempotence, CSRF, rate limiting, privacy, and mutation inventory.

## 3. Onboarding Home Experience

- [x] 3.1 Add generated-client wrappers/hooks and an inline Home taste picker using unique existing feed titles, with tests for pending polling, selection, Skip, persistence success, accessibility, and invisible failure/empty states.

## 4. Contracts

- [x] 4.1 Regenerate OpenAPI and frontend API types in the devcontainer and verify the committed schema contains only the intended secret-free fields.
- [x] 4.2 Run strict OpenSpec validation and fix every change-artifact issue.

## 5. Quality Gate

- [x] 5.1 Run `just check` inside the devcontainer and fix every backend/frontend failure.

## 6. Review Remediation

- [x] 6.1 Harden the initial playback-link edge cases by rejecting trailing fragments, suppressing the referrer, and covering mixed regular/4K fulfillment (the app fallback behavior was superseded by 10.2).
- [x] 6.2 Keep onboarding polling tied to successful pending responses, scope cached state to the signed-in user, and preserve selected title payloads across feed refreshes.
- [x] 6.3 Bound onboarding and direct signal TMDB ids to a database-safe integer range with endpoint regression tests.
- [x] 6.4 Regenerate contracts, run strict OpenSpec validation, and pass `just check` in the devcontainer.

## 7. Second Review Remediation

- [x] 7.1 Enforce the 12-title picker bound across feed refreshes and announce submission failures, with frontend regression coverage.
- [x] 7.2 Apply the shared database-safe TMDB id bound to the existing request mutation and cover rejection before any upstream or taste side effect.
- [x] 7.3 Regenerate contracts, run strict OpenSpec validation, and pass `just check` in the devcontainer.

## 8. Final Review Remediation

- [x] 8.1 Add an accessible Clear picks recovery path when retained selections leave the current feed window, and extend the cap regression through recovery and submission.
- [x] 8.2 Declare and specify the shared title-id bound in the modified `taste-signals` and `media-requests` capabilities.
- [x] 8.3 Run strict OpenSpec validation and pass `just check` in the devcontainer.

## 9. Live Device Remediation

- [x] 9.1 Record the household-user/PIN handoff limitation and specify separate Plex Web and Plex App controls with safe fallbacks.
- [x] 9.2 Implement the two accessible playback controls across desktop, Android, and iOS/iPadOS behavior, with focused frontend regression coverage.
- [x] 9.3 Run strict OpenSpec validation, pass `just check` in the devcontainer, and rebuild the isolated LAN test stack.

## 10. Handoff Reliability Remediation

- [x] 10.1 Update the proposal, design, and playback specs for partial-library playback, new-tab Plex Web recovery, removal of the timed app fallback, explicit experimental labeling, and the Jellyfin/Emby link limitation.
- [x] 10.2 Implement the backend and frontend handoff changes with focused partial-status, link-attribute, rendering, and absent/invalid-link regression coverage.
- [x] 10.3 Run strict OpenSpec validation and pass `just check` in the devcontainer.

## 11. Final Plex UX Remediation

- [x] 11.1 Specify plain-language experimental handoff guidance and a secure, best-effort auto-closing Plex approval window, including blocked, closed, and browser-severed fallbacks.
- [x] 11.2 Implement the handoff copy and approval-window lifecycle with focused frontend success, reopen, popup-blocked, manual-close, and failure coverage.
- [x] 11.3 Run strict OpenSpec validation, pass `just check` in the devcontainer, and rebuild and verify the isolated LAN test stack.

## 12. Pre-archive Review and Popup Return Remediation

- [x] 12.1 Reconcile the playback deltas with partial availability and the pinned OpenSpec parser, correct stale task prose, and specify accessible playback guidance plus best-effort popup focus return.
- [x] 12.2 Implement a protected sized Plex popup with severed-context recovery and focus return, reject Plex-token-bearing web URLs, align and describe playback controls, and make live playback checks portable and non-disclosing.
- [x] 12.3 Run focused regressions, pinned strict OpenSpec validation, `just check`, and rebuild and verify the isolated LAN test stack.

## 13. Final Security Review Remediation

- [x] 13.1 Specify symmetric token-parameter rejection for Plex web and app links and make the credential-rejection scenario archive-visible.
- [x] 13.2 Reject token-bearing app links before intent construction and pin app-link rejection, regular-over-4K selection, and failed-popup-disown behavior with focused regressions.
- [x] 13.3 Run focused regressions, pinned strict OpenSpec validation, `just check`, and rebuild and verify the isolated LAN test stack.

## 14. Pre-archive Regression Hardening

- [x] 14.1 Pin percent-encoded token names, whitespace padding, and non-default or malformed web ports in the playback-link rejection matrix.
- [x] 14.2 Run the focused regression, pinned strict OpenSpec validation, and `just check` in the devcontainer.
