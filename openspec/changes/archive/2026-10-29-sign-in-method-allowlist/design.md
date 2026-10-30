## Context

See proposal.md for motivation. Current state:

- `provider_available(settings, provider)` in `api/auth.py` is
  configuration-only. It feeds `/auth/methods`, the sign-in and link
  dependencies (`get_plex_auth_context` and others are shared by sign-in and
  link endpoints), the account summary `available`, `can_unlink`, the unlink
  409 check, and Jellyfin-method Seerr linking.
- Dormancy, history scheduling, and Continue Watching already use the
  `settings.*_configured` properties directly, not `provider_available`.
- `RuntimeSettings` stores `disabled_rail_types`. Environment locks exist for
  `hide_library_items` and `excluded_service_ids` (`locked_discovery_fields`,
  `resolve_runtime`).

## Goals / Non-Goals

**Goals:**
- Two clear predicates, each with one home: configured and offered for sign-in.
- No way for a save to lock out the saving admin; an environment recovery path.

**Non-Goals:**
- Changing link, dormancy, or data behavior for configured providers.

## Decisions

1. **Stored as a denylist, configured as an allowlist.** Runtime JSON stores
   `disabled_sign_in_methods`, mirroring `disabled_rail_types`, so old documents
   need no migration and a future method defaults to offered. The environment
   variable is an allowlist (`TASTERR_SIGN_IN_METHODS=["jellyfin"]`), because
   that is what the request asked for and it reads naturally in Compose. Its
   validation mirrors `TASTERR_EXCLUDED_SERVICE_IDS` (JSON array, explicit null
   rejected), plus non-empty. It joins the existing lock mechanism by extending
   `resolve_runtime` and the lock list.

2. **Split the predicate.** Rename the existing function to
   `provider_configured` (all current link, summary-availability, and
   Seerr-via-Jellyfin uses), and add `sign_in_offered(settings, runtime,
   provider) = provider_configured(...) and provider not in disabled`. Use it in
   `/auth/methods`, new sign-in-only dependencies, `can_unlink`, and the unlink
   check. Sign-in endpoints and link endpoints stop sharing a dependency: each
   `get_*_auth_context` gains a sign-in variant that checks
   `sign_in_offered`, and the link routes keep the configured check.
   Alternative: a flag on the shared dependency, rejected because which check
   applies should be visible at the route.

3. **Save guard on the server, preview on the client.** The PUT computes the
   saving admin's configured links against the resulting effective allowlist and
   returns 409 when none remain. The preview needs data about other members, so
   GET settings returns `sign_in_link_counts` (at most seven entries, counts only)
   and the SPA subtracts. Alternative: a dry-run endpoint, rejected as a second
   round trip for the same data.

4. **`/auth/methods` reads runtime settings.** It stays unauthenticated and
   upstream-free; it gains one local SQLite read of the runtime document, the same
   read every page already does.

5. **Seerr auto-link is unchanged.** Not offering Seerr email sign-in does not
   stop Plex or Jellyfin sign-in from linking Seerr. That is linking, and members
   still need it for requests.

## Risks / Trade-offs

- [An admin strands everyone except themselves] → the preview count before
  saving, persistent Account warnings, and sessions continuing up to the 90-day
  cap.
- [The only admin loses their link upstream (e.g. a Plex account is removed)
  after the allowlist excludes their other methods] → `TASTERR_SIGN_IN_METHODS`
  recovers access without touching the database; documented.
- [`seerr-media-server-awareness` adds its cached Seerr helper beside
  `provider_available`] → whichever change lands second uses the renamed
  `provider_configured`; it's a mechanical rebase with no behavior change.
- [A hidden method is still linkable, which could look inconsistent] → the
  Account page labels such providers as "Not used for sign-in".

## Migration Plan

No schema migration. Image-only rollback is safe: older images ignore the extra
runtime field and simply offer every configured method again.

## Security considerations

- **Endpoints:** sign-in endpoints for methods that aren't offered fail before
  any upstream call with the existing generic 503, so no method or account
  information is revealed. `/auth/methods` still returns booleans only, and the
  allowlist itself is never exposed. The settings PUT keeps admin, CSRF, and
  admin-bucket protections; the field is an enum list validated by Pydantic.
  Settings GET adds aggregate counts only.
- **Auth & sessions:** strictly narrows sign-in. Sessions are not revoked
  (documented trade-off, bounded by the existing 30/90-day expiry). Admin
  derivation is unchanged. The PIN handle binding between sign-in and linking
  is unchanged, so a link PIN still can't complete a sign-in for a hidden method.
- **Outbound HTTP:** none added; refused methods make no upstream call.
- **Configuration:** the new environment variable is non-secret and
  boot-validated; invalid values fail closed (boot error) rather than offering
  nothing.
- **Frontend, DB, dependencies:** fixed strings only; non-secret runtime JSON
  field; no new dependency.
