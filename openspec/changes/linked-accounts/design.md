# Design: linked-accounts

## Context

Today `users.seerr_user_id` is the identity, `auth/login.py::upsert_user` keys on
it, and each `sessions` row carries `seerr_cookie` (plaintext) and
`plex_token_enc`. The rest of the app (signals, profiles, household, rails)
already keys on `users.id`, so the coupling is confined to auth, sessions, and
the callers that read session material: `api/request.py` (cookie and re-auth),
`api/home.py` and `api/taste.py` (Plex token, history trigger),
`api/recommendations.py` (reset), `api/destinations.py` and `recommend/seed.py`
(`seerr_user_id`).

This change is a refactor that users barely see: the same sign-in buttons, Seerr
still required. The later changes add sign-in methods on top of it.

## Decisions

### 1. One `linked_accounts` table, not per-provider columns

```
linked_accounts
  id               PK
  user_id          FK users.id ON DELETE CASCADE, indexed
  provider         String(16)   'plex' | 'seerr'   (jellyfin added later)
  external_id      String(64)   Plex cloud account id / Seerr user id, as text
  display_name     str
  avatar_url       str | None
  credential_enc   str | None   Fernet: Plex account token / Seerr cookie
  sync_attempted_at, sync_synced_at   DateTime | None
  linked_at        DateTime
  UNIQUE(provider, external_id), UNIQUE(user_id, provider)
```

Alternative: `users.plex_account_id`, `users.seerr_user_id`, ... columns. That
would be fewer joins but needs a migration per provider and duplicates the sync
timestamps per provider. One table keeps "linked account = history source" as a
single shape. `external_id` is text because providers disagree on id types.

`provider` is a `Literal` in Python, not a DB enum (SQLite), validated at the ORM
boundary like `signals.kind`.

### 2. Credentials are per account, encrypted, and survive logout

The Plex token and Seerr cookie move from the session to the link. Without this,
"link any combination" would mean nothing: a Plex link would work only in
sessions that started with Plex. Logout means "this device"; unlink and account
deletion mean "stop using this account". The Seerr cookie, plaintext on the
session today, becomes Fernet ciphertext like the Plex token (`auth/crypto.py`).

Trade-off, accepted by the maintainer: tokens of every linked user are now at
rest, not only tokens of active sessions. See Security considerations.

### 3. Sign-in resolution order

```
resolve(sign_in_account, seerr_login | None):
  1. link(provider, external_id) exists      → its user
  2. seerr_login and link('seerr', seerr_id) → that user; attach sign_in_account
  3. otherwise                               → new user; attach sign_in_account
  then: Seerr auto-link (decision 4), admin (5), display (6), mint session
```

Upstream calls (the sign-in itself, the Seerr auto-link) run first, outside any
transaction. Steps 1–3 and the link writes then run in one short transaction; the
unique constraints turn a concurrent duplicate
into an `IntegrityError`; the transaction rolls back and the full resolution
(steps 1–3) re-runs once, so a concurrent winner is found whether it created the
sign-in link (step 1) or the bridging Seerr link (step 2). The admin and
display reads run after that commit, again outside a transaction, and a second
short transaction updates `is_admin` and display identity and mints the session.
No upstream call ever runs while SQLite's single write lock is held, so a slow
Seerr can't push other writers past the busy timeout. In this
change, Seerr local sign-in has the Seerr account as both the sign-in account and
the Seerr login result, so step 1 always applies to existing users.

### 4. Seerr auto-link uses the same credentials

Plex sign-in already logs into Seerr with the Plex token, which is the gate in
this change. That result links Seerr when the user has none and the Seerr
account is free, refreshes the cookie when it matches, and is discarded when it
differs (the user deliberately linked another Seerr account). No email or
`plexId` matching: unverified emails would allow account takeover.

### 4a. An explicit Seerr unlink sticks

Auto-link fills an empty Seerr slot only for users who never unlinked Seerr.
Unlinking Seerr sets `users.seerr_unlinked_at`; sign-in skips auto-link while it
is set; linking Seerr manually from `/account` clears it. Without this, the next
Plex or Jellyfin sign-in would silently re-link Seerr and re-import history the
member just deleted. Decided in review round 2 over documenting the reconnect.

### 5. Admin = any link grants, re-derived at sign-in

`is_admin = any(check(link) for link in user.links)`, where this change has one
check: a Seerr link → `SeerrClient.user(id)` (global API key, read-only, already
used by destinations) → `permissions & ADMIN`. A grant from any check wins. With
no grant, the previous value is kept if *any* check errored, and admin becomes
false only when every check completed without granting. "Errored" means an outage
(transport, timeout, 502/503/504), the same definition as the Seerr auto-link; a
404 for a deleted upstream user or a 401 for a revoked token completes without a
grant, so deleting someone upstream does demote them at their next sign-in. A partial outage (Seerr
down for a Seerr admin who is a shared Plex user) can never demote. Later changes add the Plex owner and Jellyfin admin
checks to the same list.

### 6. Display identity: Seerr → Plex

Same priority as the household already sees. `PlexCloudAccount` gains the
plex.tv `title`/`thumb` fields for the Plex fallback.

### 7. Seerr request history becomes an incremental sync

The cold-start seed only runs for users with no signals. With linking, that
misses a Seerr link added after a user has signals, and requests made in Seerr's
own UI never reach the profile. The seed becomes a sync on the Seerr link, using
the same trigger, throttle (six hours), single-flight, and watermark pattern as
Plex history:

- first sync: full bounded history; later: requests created ≥ `synced_at − 24h`
  (filtered client-side from the existing paginated read);
- skips titles with an existing `request` signal (a Tasterr request would
  otherwise count 3.0 + 2.0);
- the existing unique-per-title index keeps repeat imports idempotent.

Reset no longer imports inline: it clears state and evaluates the Seerr trigger,
with Plex waiting on it as usual. One import path, one single-flight guard, and
no second full sync on the next Home load. The response becomes `204` (the SPA
never read `seeded_signals`); Home is briefly unpersonalized until the
background sync lands.

### 8. Migration `0007` signs everyone out

Dropping the UNIQUE `seerr_user_id` column and adding `AUTOINCREMENT` both force
SQLite to rebuild `users`. The app engine turns foreign keys on for every
connection and SQLite ignores that pragma inside an open transaction, so a
rebuild inside `engine.begin()` would fire every child table's `ON DELETE
CASCADE` and wipe all signals and profiles (reproduced in review). `db/migrate.py`
therefore opens a connection, runs `PRAGMA foreign_keys=OFF` before beginning
the migration transaction, runs `PRAGMA foreign_key_check` after upgrade (failing
boot if it reports rows), and re-enables enforcement. Because nothing cascades while
enforcement is off, the downgrade deletes the removed users' signals, profiles,
sessions, and links explicitly.

Session rows hold the only copies of today's cookies and tokens, and there's no
reliable way to know which Plex account a session token belongs to without
calling plex.tv during migration. So the migration creates Seerr links from
`seerr_user_id` (no credential), deletes all sessions, and drops the old columns.
At their first Plex sign-in, members land on their existing user through
resolution step 2. Plex sync timestamps are dropped. The first Plex sync after
relinking re-reads the 365-day window, and existing `watched_plex` rows absorb it
idempotently.

Alternative rejected: lazily migrating each session's material on first use. It
saves one sign-in but leaves migration code in the hot path indefinitely.

### 9. Account API shape

| Endpoint | Guard | Notes |
|---|---|---|
| `GET /account` | session | configured providers, linked state, name, `linked_at`, `can_unlink` |
| `POST /account/links/plex/pin`, `.../pin/poll` | session, same-origin, login bucket (create only; the poll is handle-gated and exempt, like sign-in's) | same `PinStore` handles as sign-in; poll links instead of minting a session |
| `POST /account/links/seerr` `{method: plex}` or `{method: local, email, password}` | session, same-origin, mutation + login buckets | `plex` uses the stored Plex token |
| `POST /account/links/{provider}/unlink` `{delete_history}` | session, same-origin, mutation bucket | 409 unless another remaining link can currently sign in |
| `POST /account/delete` `{confirm}` | session, same-origin, mutation bucket | cancels sync tasks, cascades, clears cookie |

Mutations stay `POST`, matching the rest of the API. A link conflict returns a
generic 409 that never names the other user.

### 10. Request control reuses `re_auth_required`

"No Seerr link" and "lapsed cookie without a Plex link to refresh it" both need
the same fix (authenticate to Seerr), so they share the existing status, and the
SPA's message becomes a "Connect Seerr" dialog backed by
`POST /account/links/seerr`. No new status value.

## Risks / Trade-offs

- **One-time sign-in for everyone.** Called out in release notes.
- **Larger at-rest credential set.** Mitigated by encryption, deletion on
  unlink/delete, and the user's ability to revoke at plex.tv.
- **Seerr cookie lifetime.** Not verified; members without a Plex link may see
  "Connect Seerr" when Seerr's own session lapses. Same as today's local members.
- **Duplicate users** can still arise (two unlinked accounts with no common
  Seerr account); resolved by self-service deletion, not merging.

## Security considerations

**Any new or changed API endpoint** (`/account*`, `/auth/*`, `/request`):
- All `/account*` routes use `require_session` (default-deny); every mutation
  adds `require_same_origin` and the mutation bucket; link routes that forward
  credentials or create PINs also take the tight login bucket. Each new mutation
  is added to the mutation-inventory regression.
- Pydantic bodies: `provider` and `method` are `Literal`s; `email`/`password`
  bounded strings; `confirm` must equal the caller's display name.
- Explicit response models: no provider ids, credentials, sync internals, or
  other users' data. Conflict, rejection, and upstream errors are generic; a 409
  never reveals which user owns an account.
- Logs record outcomes only (`account: link plex succeeded`), never ids, names,
  tokens, cookies, or credentials.

**Auth & session code:**
- Credentials are forwarded to Seerr/plex.tv once and never stored; only the
  resulting Plex token and Seerr cookie are stored, encrypted, on the link.
- Every sign-in still mints a fresh token; logout still deletes the row. Session
  rows no longer hold any upstream material.
- Links come only from in-request authentication (no admin assignment). This
  prevents a Tasterr admin from impersonating someone else's Seerr account.
- Admin re-derivation never widens on error: an erroring check grants nothing,
  and it can only preserve the previous value, never set it to true.
- Account deletion cancels in-flight sync tasks before deleting, so no
  background write recreates rows for a deleted user.

**Outbound HTTP:** no new upstream endpoints beyond the plex.tv account fields
(`title`, `thumb`) parsed into the existing typed model; base URLs unchanged.

**Frontend:** account names render as text; no credential reaches JS; the PIN
popup reuses the opener-severing flow from sign-in.

**Database & migrations:** `credential_enc` is Fernet ciphertext (justified
above). Migration `0007` copies no secret material (it deletes session rows
rather than moving their credentials) and logs nothing sensitive. FK cascades
cover deletion.

**Dependencies:** none added.
