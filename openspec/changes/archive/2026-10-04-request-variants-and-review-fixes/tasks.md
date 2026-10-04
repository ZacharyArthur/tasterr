## 1. Backend contracts

- [x] 1.1 Add typed fresh permissions, variant-aware wire requests and availability; verify permission matrix, identity, payload and status tests.
- [x] 1.2 Scope discovery and validate variant/destination/capabilities with graceful failure and bounds; verify API attribution, denial, outage, stale/invalid selection and reauth regressions.

## 2. Controls and integration

- [x] 2.1 Regenerate API types and implement explicit variants, defaults, advanced cancellation, loading/error/stale states and type-level query sharing; verify component tests and browser journeys including missing-4K upgrade.
- [x] 2.2 Correct archived docs and opt-in live contract to assert stored destination/variant through production client and version/cleanup; verify live collection without performing household requests.

## 3. Completion

- [x] 3.1 Run browser tests and OpenSpec validation, fix failures, archive supplemental change on this branch and inspect resulting spec/diff.
- [x] 3.2 Run just check inside the devcontainer and fix any failures.


Verification: devcontainer just check passed (754 backend, 132 frontend; 17
live tests excluded), just e2e passed (four local Chromium journeys), and strict
OpenSpec validation passed. Live contracts were collected but not executed;
real dispatch and the household installed version remain unverified.

## 4. Follow-up review

- [x] 4.1 Serialize cache invalidation with in-flight loads and add a concurrent regression.
- [x] 4.2 Validate bare 4K default configuration, preserve advanced non-default selection, regenerate capability types, and test API/discovery/UI behavior.
- [x] 4.3 Correct spec wording/duplicates/spacing, name permission flags, place comment/docs correctly, and rerun the gate and browser journeys before re-archiving.
