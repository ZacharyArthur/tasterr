## 1. Preferences

- [x] 1.1 Add validated runtime preferences, optional env overrides and admin lock metadata; verify default compatibility, validation, precedence and underlying-value preservation with settings/API tests.

## 2. Discovery policy

- [x] 2.1 Implement request-scoped eligibility checks, shared deadline and bounded library boost reads; test variant/region/subscription rules, current metadata, cancellation, reuse and inactive behavior.
- [x] 2.2 Wire all discovery seams, exemptions, bounded discover refill and filtered-empty handling; test home/extra/hero, candidates, household blend, child suggestions, intentional access and genuine upstream failure.

## 3. Controls and delivery

- [x] 3.1 Add labelled admin controls, lock/overlap/failure explanations, region reset and stale-household reset; verify frontend interaction tests and regenerate API types.
- [x] 3.2 Document configuration and best-effort semantics; validate OpenSpec and deliver a fresh-reviewer prompt covering correctness, completeness and project constraints.
- [x] 3.3 Run `just check` inside the devcontainer and fix any failures.

## Validation

- Latest review-correction gate, run as `vscode` in the devcontainer: `just check` passed; 828 backend tests, 144 frontend tests, generated-type freshness, type/lint/boundary checks and production build. Seventeen opt-in live tests were deselected; the pre-existing third-party TestClient/httpx deprecation warning remains.
- Devcontainer `just e2e`: four existing real-backend browser smoke journeys passed against local fixtures. New controls/filter behavior are covered by unit/API/interaction regressions; no live household contract run was performed.
- `openspec validate discovery-exclusions --strict` and `git diff --check`: passed.
- Final read-only reviews approved the confirmed scope. The historical handoff is retained in review-save-race-prompt.md; three superseded handoffs were removed before archival. Both pre-existing local commits remain intact. Archived on the branch at 2026-10-04-discovery-exclusions with all six added requirements synced to the living specs. The existing app-settings Purpose placeholder was replaced with a description of its current scope.
- New local coverage includes personalized-only successful-empty/cache-hit versus failed/no-signal sources, verification-only outage classification, delayed settings saves with completed/pending blends after navigation, regular-TV/4K-movie availability and Seerr failure, explicit rail/hero survivors, strict integer inputs, and real-cache refill cancellation/query narrowing. The 4,096-entry catalog capacity is approved but has not been measured on a live household; best-effort bounds remain unchanged.
- Latest corrections additionally cover pending initial Home/extra-rail reads resolved after confirmed saves, session changes during query cancellation, discovery-first hero fallback under active filtering, drained title availability on errors/cancellation, bounded verification lock recovery, hybrid personalized success amid ordinary-source failure and exclusion-limit feedback.
- Final post-archive checks: `just check` passed (828 backend and 144 frontend tests), `just e2e` passed (four journeys), affected app-settings/discovery-filtering living specs passed strict validation and staged whitespace checks passed. A broader strict check flags eleven pre-existing Purpose placeholders in unrelated living specs; no requirements were changed there.

## 4. Review corrections

- [x] 4.1 Bound refill fetches by the shared deadline, coordinate overlapping verification, distinguish successful empty sources from failures, reject explicit null overrides, keep missing service exclusions removable, and preserve household blends across ordinary refetches. Add regressions including real production dependency wiring; clarify docs/specs and deliver a follow-up review prompt after the devcontainer gate passes.
- [x] 4.2 Record explicit personalized candidate-source success without treating verification as catalog success; clear completed and pending household results when a delayed settings save completes. Raise catalog cache to 4,096 entries, use structured verification cancellation and strict excluded IDs, simplify filter ownership/creation, improve loading labels and local production/cache/race coverage. Update review handoff and pass devcontainer gates.
- [x] 4.3 Cancel pending discovery reads before confirmed-save invalidation while retaining session guards; regress delayed initial feeds and late responses. Prefer discovery rails for the active-filter hero fallback, drain title availability on all exits, strengthen lock-release and hybrid source-success coverage, reuse the service limit and show its reached state. Update the handoff and pass devcontainer gates.
- [x] 4.4 Exercise unrelated profile-detail success in the failed Unexpected Picks fixture, suppress editable-limit advice under environment locks and distinguish failed service options. Preserve cached-feed refresh behavior and the existing shared clock for empty-source refills, clarify the composer documentation, and pass final devcontainer gates before archiving.
