# Design: plex-direct-login

## Context

Builds on `linked-accounts`: sign-in already resolves Tasterr users through
links, and Seerr auto-link is a separate step. What remains Seerr-dependent is
the *gate*: `get_auth_context` returns 503 without Seerr, and the Plex PIN poll
fails if Seerr refuses the token. Plex resource discovery
(`PlexMediaClient.discover_servers`) keeps up to four owned-first resources.

## Decisions

### 1. Gate on resource membership, checked every sign-in

`PLEX_SERVER_ID` is compared against `clientIdentifier` in the account's plex.tv
resources (the same `/api/v2/resources` read discovery already performs). Owner,
shared, and Plex Home users all appear there. The check runs on **every** Plex
sign-in, including linked accounts, so removing someone's share revokes their
Tasterr access at their next sign-in. Existing sessions are not revoked, but see
decision 7: no session outlives 90 days, so the next sign-in always comes.

If the resources read fails, sign-in fails closed with the generic upstream
error. A plex.tv outage blocks new Plex sign-ins but never browsing for signed-in
users.

Alternatives rejected (agreed in design review): an admin-managed account
allowlist (per-member admin work), an approval queue (new UI, friction), and
admitting any plex.tv account (unacceptable).

### 2. Gate selection

| `PLEX_SERVER_ID` | Seerr | Plex sign-in gate | Seerr auto-link |
|---|---|---|---|
| set | any | server membership | attempted when Seerr configured; refusal ignored; outage blocks only a would-be new user |
| unset | configured | Seerr accepts token (today) | is the gate |
| unset | unconfigured | Plex sign-in unavailable | — |

Existing installs (Seerr, no `PLEX_SERVER_ID`) behave exactly as after
`linked-accounts`.

### 3. Pin discovery for media reads; gate and owner check skip probing

When the setting is present, discovery filters resources to that one id before
connection probing, so history and Continue Watching pin in one place. Without
the setting, the four-resource behavior stays.

The sign-in gate and the owner admin check read only the plex.tv resources list
(`clientIdentifier`, `owned`), once per sign-in, with no PMS connection probing.
Probing would add latency to every sign-in and would turn a PMS that is merely
offline into "no access" or "not owner".

### 4. Owner admin check

`resource.owned` for the pinned resource from the plex.tv resources list (no
probing), via the Plex link's token, reusing the same read as the gate when the
sign-in is a Plex sign-in. Added to the
any-link admin list from `linked-accounts`, whose rule keeps the previous value
when a check errors without any grant.
Without `PLEX_SERVER_ID` there is no Plex admin check: "owns some Plex server"
is not meaningful.

### 5. `/auth/methods` instead of extending `/health` or `/config`

`/config` is session-gated and the login screen runs before a session exists.
`/health` is a liveness probe; overloading it couples the login UI to the
container healthcheck. A dedicated unauthenticated endpoint returning booleans
matches the precedent `/health` already sets for unauthenticated booleans.

### 6. Login screen

Stacked full-width pills (`rounded-full`, app surface/border tokens, service mark
on the left, "Continue with …" label), using existing Tailwind tokens and inline
SVG marks, with no icon library. Methods needing credentials expand their form in
place. The Plex popup and approval-link recovery flow stays exactly as specified.
The marks follow each project's published brand assets, used only to identify
the sign-in method.

### 7. Absolute 90-day session lifetime

Sessions keep the 30-day sliding window and also expire 90 days after
`created_at`, whatever the activity. `resolve_session` checks both;
the sliding refresh never extends `expires_at` past `created_at + 90 days`, and
the refreshed cookie's `Max-Age` is capped the same way so the browser and
server agree. Every member therefore signs in at least quarterly, which re-runs
the `PLEX_SERVER_ID` check and admin derivation. Alternatives rejected in design
review: documenting the gap only (unbounded), and revoking sessions from the
background Plex sync (Plex-linked users only, and wrong for members who also
sign in with Jellyfin).

## Risks / Trade-offs

- **plex.tv outage blocks new Plex sign-ins** when gated by server. Accepted:
  fail-closed is the safer default for an access gate.
- **Share revocation is not immediate.** Sliding sessions alone would let a
  revoked member keep access indefinitely by visiting monthly; the 90-day
  absolute cap (decision 7) bounds both revocation and admin demotion to 90
  days at most. Immediate cut-off needs admin user management (deferred).
- **A share revoked after linking** can still strand a member who has unlinked
  every other account: linking checks admission once. Documented; immediate
  cut-off needs admin user management (backlog).
- **Misconfigured `PLEX_SERVER_ID`** (wrong id) locks everyone out of Plex
  sign-in. Mitigated by boot-time format validation and by documenting where to
  find the id (Plex Web → Settings → General, or `/identity`).

## Security considerations

**Any new or changed API endpoint:**
- `GET /auth/methods` is unauthenticated by explicit decision (pre-login need),
  returns only booleans, makes no upstream call, and has an explicit response
  model. A `PublicConfig`-style regression asserts no URL/id/secret field.
- Plex PIN routes keep their same-origin, rate-limit, opaque-handle, and POST-only
  rules; refusals stay generic (no "you lack server access" vs "unknown account"
  distinction beyond the generic 401).

**Auth & session code:**
- Sessions gain a 90-day absolute lifetime; the sliding refresh and cookie
  `Max-Age` never extend past it, so access and admin changes apply within 90 days.
- The server-membership gate is evaluated on every sign-in and every Plex link;
  an existing link never bypasses it.
- The gate fails closed on upstream error.
- `PLEX_SERVER_ID` is an env-only deployment setting (validated: 1–64 letters,
  digits, hyphens); it never reaches the browser.

**Outbound HTTP:** no new upstream endpoints; discovery gains a filter before
probing, which reduces probes. All Plex connection checklist items still apply to
the single pinned resource.

**Frontend:** service marks are static inline SVG; no external image loads; no
credential in JS.

**Database:** no change.

**Dependencies:** none added.
