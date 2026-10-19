# Design: jellyfin-integration

## Context

After the first two changes, sign-in methods resolve users through links, the
login screen renders methods from `/auth/methods`, and Plex history sync is a
per-link background task with a throttle and watermark. Jellyfin slots into each
of those.

## Decisions

### 1. Server API key + stored user id; no per-user token

Agreed in design review. Reads use the API key scoped to the linked Jellyfin
user id:

| Need | Call (API key) |
|---|---|
| Admin, display name | `GET /Users/{id}` → `Name`, `Policy.IsAdministrator` |
| Played movies | user-scoped items query: `IncludeItemTypes=Movie`, `Filters=IsPlayed`, `Recursive=true`, `Fields=ProviderIds`, `SortBy=DatePlayed`, `SortOrder=Descending`, paged |
| Played episodes | same with `IncludeItemTypes=Episode` → `SeriesId`, `UserData.LastPlayedDate` |
| Series TMDB ids | items query with `Ids=` (≤100) and `Fields=ProviderIds` |

Exact query parameters are confirmed against the live contract test (Jellyfin
10.9+/10.10+) before implementation is marked done.

Trade-off: the API key has admin-level access to Jellyfin, like the Seerr API key
Tasterr already holds. In exchange, there are no per-user Jellyfin secrets at
rest and nothing breaks when a user signs out of all their Jellyfin devices.

### 2. Sign-in: authenticate once, then log the token out

`AuthenticateByName` is the only way to prove a password, and it creates a
Jellyfin session ("device"). Logging out the returned token right away
(`POST /Sessions/Logout` with that token) keeps Tasterr from piling up entries in
the user's Jellyfin device list. A failed logout is logged generically and
ignored; the token is never stored. The client sends a stable `DeviceId` derived
from the secret key (like `plex_client_identifier`), so Jellyfin sees one device.

### 3. Gate = the Jellyfin server itself

Accounts exist only on the configured server, and Jellyfin refuses disabled
users, so no extra allowlist is needed.

### 4. Seerr auto-link with the same credentials

During Jellyfin sign-in, the same username/password are passed once to Seerr's
Jellyfin login (`/api/v1/auth/jellyfin`, username + password), using the
`linked-accounts` auto-link rules. This is what bridges an existing Seerr-keyed
user to their new Jellyfin link. The parameters Seerr expects after its initial
setup are confirmed in the live Seerr contract test.

### 5. History mapping

- Movies: `ProviderIds.Tmdb` → `(movie, id)` when it parses to a valid id.
- Episodes: grouped by `SeriesId`; one batched series lookup per ≤100 series;
  `(tv, series Tmdb id)` with the newest `LastPlayedDate` in the group. An
  episode's own `Tmdb` provider id is an *episode* id and is never used.
- Bounds mirror Plex: 365-day first window, 24-hour overlap, pages of 100,
  ≤500 rows per type, 30-second deadline, ≤100 facts per write transaction,
  watermark only on complete reads.

The write path (upsert latest-watch fact, invalidate profile) is shared with Plex
history by parameterizing the kind. That is the only shared code; the Jellyfin
and Plex readers stay separate (two implementations don't justify a media-server
abstraction).

### 6. Signal kind `watched_jellyfin`, not reusing `watched_plex`

Separate kinds keep each source independently toggleable and clearable
(`taste-source-preferences`) and keep unlink's history deletion exact. A title
watched on both servers gets two facts, which is honest: two independent
observations.

### 7. Admin and display

`Policy.IsAdministrator` (and not `IsDisabled`) joins the any-link admin list. Display priority becomes
Seerr → Plex → Jellyfin. Jellyfin `PrimaryImageTag` avatars are served from the
internal URL, which must never reach the browser, so Jellyfin contributes no
avatar (backlog item for a proxy route).

## Risks / Trade-offs

- **API key blast radius:** a leaked Jellyfin API key is full server admin.
  Same class as the Seerr API key; env-only, never logged, header-only.
- **Jellyfin API drift** between 10.8/10.9/10.10 (`/Users/{id}/Items` vs
  `/Items?userId=`): pinned by the live contract test; the client uses
  `/Items?userId=`, which 10.9 and 10.10 both serve.
- **Large libraries:** the 500-row cap per type drops older overflow on stale
  windows, same as Plex.

## Security considerations

**Any new or changed API endpoint:**
- `POST /auth/jellyfin` is pre-login by nature: same-origin check, tight login
  bucket, Pydantic body (bounded strings), generic 401 (no user enumeration),
  generic 502/503, explicit response model. Logs carry outcome only.
- `POST /account/links/jellyfin` and the Seerr `jellyfin` method: session,
  same-origin, mutation and login buckets; added to the mutation inventory.
- `/auth/methods` gains a boolean only.

**Auth & session code:**
- Exposure: Jellyfin sees every Tasterr sign-in as coming from Tasterr's own
  address, so exposing Tasterr exposes Jellyfin password sign-in. Jellyfin's
  local-network-only access rules don't apply, and Jellyfin's failed-attempt
  lockout is bounded only by Tasterr's login bucket (10/min per client IP), so
  repeated wrong passwords from outside can lock a member's Jellyfin account.
  Empty passwords are refused unless `JELLYFIN_ALLOW_EMPTY_PASSWORD=true`
  (env-only, default false); the README and CONFIGURATION docs say all of this.
  Allowing passwordless accounts only from local clients is a backlog idea.
- Jellyfin passwords are forwarded to Jellyfin (and once to Seerr) and never
  stored or logged. The Jellyfin access token is logged out and discarded.
- Links are created only from in-request authentication.
- Jellyfin admin grants follow the any-link rule: an erroring check grants
  nothing and can only preserve the previous value.

**Outbound HTTP (`clients/jellyfin.py`):**
- Base URL from validated settings only (SSRF-safe); no user-supplied URL.
- Explicit timeouts; no redirects; bounded pagination and batch sizes.
- API key and tokens only in the `Authorization` header, never in URLs (no
  `api_key` query parameter).
- Upstream JSON parsed into typed models with unknown fields dropped; browser
  headers never forwarded.

**Frontend:** Jellyfin names render as text; no Jellyfin URL or image reaches
the browser; the Jellyfin mark is inline SVG.

**Database & migrations:** no new secret columns; Jellyfin links have a null
credential. Migration `0008`'s upgrade only changes the index and copies no data;
its downgrade deletes Jellyfin data and link-less users, removing their child rows
explicitly because foreign keys are off during migrations.

**Dependencies:** none added.
