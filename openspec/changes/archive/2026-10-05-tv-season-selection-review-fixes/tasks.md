## 1. Request correctness

- [x] 1.1 Add typed Specials discovery, fail-closed submission validation and 202 rejection; verify client and API regression tests including no taste signal.
- [x] 1.2 Move movie-season validation before unconfigured fallback; verify configured and unconfigured rejection tests.

## 2. Frontend correctness

- [x] 2.1 Regenerate API types and share eligible seasons across picker/default equivalence; verify enabled/disabled/unreadable Specials and zero-episode/future season tests.
- [x] 2.2 Fix nested trap registration, key ownership and restoration; verify same-commit, callback-update, lower-removal and StrictMode cases plus real detail/picker Escape.
- [x] 2.3 Verify detail list omits Specials and browser fake enforces the whole-series body; run just e2e.

## 3. Final verification

- [x] 3.1 Run just check and fix any failures.

## 4. Follow-up review corrections

- [x] 4.1 Share current submission guards and handle sole eligible Specials explicitly; verify refreshed variant/default/advanced destination and direct Specials regressions.
- [x] 4.2 Add a URL/API-key-gated read-only Specials settings live test; verify collection and skipped behavior when unconfigured.
- [x] 4.3 Correct explicit-season contract/version wording, ignore braid/ and remove its review file; verify docs, git ignore matching and file absence.
- [x] 4.4 Run just e2e, validate matching archived/living requirements, then run just check and fix any failures.

## 5. Partial-request policy and variant stability

- [x] 5.1 Pin the implicit variant when the picker opens; verify Standard-to-4K and 4K-to-Standard regressions.
- [x] 5.2 Project strict partial/Specials settings and enforce the chosen regular-whole-series-only fallback; verify client, discovery, endpoint and stale-picker policy tests and regenerate types.
- [x] 5.3 Remove the approved inactive host venv, verify the named container volume remains available, and run the read-only live settings check with honest skip reporting.
- [x] 5.4 Run just e2e, validate matching archived/living requirements, then run just check and fix any failures.

## 6. Final closeout corrections

- [x] 6.1 Keep Quality hidden for Standard-only members after opening, cancelling or escaping the picker; verify the visibility and retained 4K recovery regressions.
- [x] 6.2 Remove only the empty inactive host node_modules directory and verify the named dependency volume remains available.
- [x] 6.3 Run just e2e, validate matching specs, then run just check and fix any failures.
