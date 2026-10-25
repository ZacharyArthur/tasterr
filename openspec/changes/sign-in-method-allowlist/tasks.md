## 1. Setting and environment lock

- [ ] 1.1 Add `disabled_sign_in_methods` to `RuntimeSettings` (unique, known names, default empty). Verify with tests: defaults, round-trip, duplicates and unknown names rejected, old documents valid.
- [ ] 1.2 Add `TASTERR_SIGN_IN_METHODS` to `Settings` (JSON allowlist, 1–3 unique known names; `[]`, null, empty, or unknown fails boot) and fold it into the lock list and `resolve_runtime`. Verify with settings tests for each valid and invalid form and that the stored value is preserved under the lock.

## 2. Configured vs offered

- [ ] 2.1 Rename `provider_available` to `provider_configured`, add `sign_in_offered`, and give the sign-in routes their own offered-checking dependencies while link routes keep the configured check. Verify with API tests: a hidden method's sign-in endpoints return 503 with no upstream call; its link endpoints still work; `/auth/methods` reflects the allowlist and stays booleans-only.
- [ ] 2.2 Use `sign_in_offered` for `can_unlink` and the unlink 409, and add `sign_in` to `AccountProvider`. Verify with tests: the last offered method can't be unlinked; a configured-but-hidden provider reports `available: true, sign_in: false`; Plex history and Continue Watching still schedule for a hidden but configured Plex.

## 3. Admin settings

- [ ] 3.1 Return the effective offered methods, lock flag, configured methods, and `sign_in_link_counts` from admin GET settings. Verify with tests that counts group members by configured linked sign-in-provider set (only `plex`, `jellyfin`, `seerr`) and include no identities.
- [ ] 3.2 Refuse a PUT that leaves the saving admin with no offered method (409, nothing stored). Verify with tests for the refusal, a successful narrowing, and a locked save that ignores the submitted value.

## 4. Frontend

- [ ] 4.1 Regenerate `api.gen.ts`; add sign-in method checkboxes to Settings (not-configured disabled, read-only when locked, cannot uncheck all, stranded-member preview from counts). Verify with Vitest cases for each state and the preview arithmetic.
- [ ] 4.2 Add the Account page warning when no linked provider has `sign_in`, naming offered methods, and label hidden-but-linked providers "Not used for sign-in". Verify with Vitest cases.
- [ ] 4.3 Confirm the login screen needs no logic change by adding a Vitest case where `/auth/methods` reports only Jellyfin and only "Continue with Jellyfin" renders.

## 5. Documentation

- [ ] 5.1 Document the setting, `TASTERR_SIGN_IN_METHODS`, the configured-vs-offered distinction, stranded-member behavior, and lockout recovery in `docs/CONFIGURATION.md`, `.env.example`, and `compose.example.yaml` (commented, like the other optional overrides). Verify `test_docs.py` and `test_env_example.py` pass under `just check`.

## 6. Gate

- [ ] 6.1 Before archiving, compare each MODIFIED block in `specs/` with the current `openspec/specs/` text and fold in anything a change archived since this one was written added. Verify with `openspec validate sign-in-method-allowlist --strict`.
- [ ] 6.2 Run `just check` inside the devcontainer and fix any failures until it passes.
