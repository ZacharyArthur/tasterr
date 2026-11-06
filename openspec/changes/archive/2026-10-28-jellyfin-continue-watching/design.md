## Context

See proposal.md for motivation. Current state:

- `PlexCatalogService.continue_watching(user_id, token)` caches the final
  `list[MediaSummary]` under `plex:continue-watching:user:{id}` (ttl 300 s, no
  stale). Internally it builds `_Candidate(media_type, tmdb_id, timestamp,
  server_index, progress_percent, context)`, merges them with
  `_merge_candidates`, caps at 20, and resolves each through
  `CatalogService.detail` (`_resume_item`).
- `continue_watching_provider` in `rails/registry.py` exists only when the
  `RailContext` carries a Plex service and token. `api/home.py` builds those from
  the Plex link.
- `JellyfinClient` already does user-scoped API-key reads (`/Items?userId=`), a
  batched series lookup returning `ProviderIds` and `UserData`, and strict
  parsing. `recommend/jellyfin_history.py` already has the TMDB-id validation
  and episode→series collapse.
- The `jellyfin-integration` design targets Jellyfin 10.9+ and uses the
  `?userId=` query style that 10.9 and 10.10 both serve.
- Unlink and account delete invalidate `continue_watching_key(user_id)`.

## Goals / Non-Goals

**Goals:**
- One rail, one cache entry, one TMDB-resolution cap across both sources.
- Plex-only mapping, ordering, and cache semantics are unchanged. Source and
  shared TMDB-resolution timing follow the separate budgets in decision 2.

**Non-Goals:**
- A general media-server abstraction. Only the post-mapping candidate step is
  shared.

## Decisions

1. **Share the candidate step, not the sources.** Move `_Candidate`'s
   source-neutral shape, the merge rule, and TMDB resolution into a small
   `catalog/resume.py`: `ResumeCandidate(media_type, tmdb_id, timestamp,
   source_rank, progress_percent, context)`, `merge(candidates)`, and
   `resolve(catalog, candidates)`. Plex keeps everything up to canonical
   candidates; `source_rank` is `(0, server_index)` for Plex and `(1, 0)` for
   Jellyfin, so the existing tie-break order (timestamp, progress, then server)
   becomes timestamp, progress, Plex before Jellyfin, then server, with no
   change for Plex-only members. Alternative: merge two finished
   `MediaSummary` lists, rejected because it would allow 40 TMDB resolutions and
   lose the per-title newest-activity rule.

2. **Cache once, at the rail.** The cache moves from `PlexCatalogService` to a
   single `continue_watching(...)` function in `catalog/resume.py` that gathers
   the enabled sources concurrently (each under its own ten-second deadline,
   each mapping its failure to "no contribution"), merges, resolves, and caches
   under one key. Shared TMDB resolution has a separate ten-second deadline
   starting after source collection. Expiry cancels resolution and caches an
   empty result, without stale serving. This permits approximately twenty seconds
   for a cold rail; it preserves a healthy source's resolution budget when its
   peer times out. A single ten-second rail budget was rejected because a hanging
   source could exhaust it before healthy candidates resolve. The key is renamed
   to `continue-watching:user:{id}`; the
   existing `continue_watching_key` helper moves with it. Successful media link
   saves, unlink, and account deletion invalidate that key so source changes
   cannot leave a cached single-source or negative rail. A successful media
   sign-in also invalidates after `complete_login` returns,
   covering links added through the Seerr bridge and refreshed Plex credentials.
   A result with zero successful sources is cached as the empty negative entry.
   Alternative: per-source caches merged per request, rejected
   because it adds two keys and two invalidations for no user-visible gain.

3. **Jellyfin reads.** Two new client methods, both with the API key, explicit
   `userId`, `Fields=ProviderIds`, `EnableUserData=true`, and `Limit=50`:
   `GET /UserItems/Resume` (`IncludeItemTypes=Movie,Episode`, `MediaTypes=Video`)
   and `GET /Shows/NextUp` (`EnableResumable=false`, `EnableRewatching=false`).
   `JellyfinItem` gains optional `Type`, `RunTimeTicks`, `ParentIndexNumber`,
   `IndexNumber`, and `UserData.PlaybackPositionTicks`. Both endpoints exist on
   10.9+. Opt-in live contracts cover them. The existing `played_items` method
   also supplies one user-scoped page of 100 played episodes, newest DatePlayed
   first, with explicit user data and no pagination.

4. **Jellyfin mapper lives in `catalog/jellyfin.py`.** It reads resume and
   next-up items and the bounded played-episode page concurrently, collects series
   ids only from resume and next-up, does one batched
   series lookup (≤100 ids, already bounded by two 50-item reads), and emits
   `ResumeCandidate`s. The TMDB-id validator currently private to
   `recommend/jellyfin_history.py` moves to `catalog/` (where both callers can
   import it without crossing the recommend boundary). Its behavior is unchanged.
   Normal episode playback on Jellyfin 10.9 writes the episode's activity date;
   a series date is not a reliable substitute. Next-up uses the newest matching
   episode date from the bounded page, then the series' own date if supplied,
   then Plex's negative-position sentinel. Undated items stay after dated ones
   in source order. Only resume/next-up rows become candidates; this read writes
   no signals or history watermark.

5. **Gating mirrors Plex.** `RailContext` gains the Jellyfin client and the
   linked Jellyfin user id (no secret involved; the client already holds the
   key). `api/home.py` sets them only when Jellyfin is configured and the user
   has a Jellyfin link. The provider exists when either source is present and
   the rail type is enabled. Gating happens before cache access.

6. **No new browser fields.** Cards already render `progress_percent` and
   `context`; detail is the existing Tasterr title detail.

## Risks / Trade-offs

- [The cache key rename drops in-flight Plex entries once at deploy] → at most
  one extra Plex load per user, five minutes after the restart that already
  empties the in-process cache.
- [Jellyfin's next-up can include long-idle series] → Tasterr sends no date cutoff;
  Jellyfin 10.9 defaults to no next-up date restriction. Tasterr deliberately adds
  no extra filter. A series outside the 100
  most recent played episodes uses its own date or the position fallback; no
  unbounded history scan is performed.
- [A single API key reads any user's resume data] → every read takes the user
  id from the caller's own link, server-side; tests assert the parameter on each
  call, and the live contract checks two users never see each other's items.
- [Jellyfin API drift before 10.9] → unsupported per the existing integration
  design; on unexpected shapes the client raises a typed error and the source
  contributes nothing.

## Migration Plan

No schema or configuration change. Image-only rollback is safe; the cache is
in-process.

## Security considerations

- **Endpoints:** no new routes or browser fields. Home retains its session
  dependency and typed `HomeFeed` response. Unlink retains its session,
  same-origin check, mutation rate limit, and per-user scheduling guard. All
  Jellyfin user ids come from the caller's own link; no browser-supplied provider
  id or headers are forwarded. Upstream failures remain generic, with no raw
  bodies, internal URLs, identities, or credentials logged or returned.
- **Auth & sessions:** no credential handling changes. The Jellyfin API key
  stays server-side and is used only for reads scoped to the caller's linked
  Jellyfin user id, as the existing client rule requires (now listing resume
  and next-up).
- **Outbound HTTP:** all reads go through `clients/jellyfin.py` with the
  validated base URL, the existing timeout, no redirects, and the key only in
  the `Authorization` header. Responses are strictly parsed with unknown fields
  dropped. Volume is bounded: two 50-item reads, one 100-episode activity page,
  and one series batch of at most 100 ids per user per five minutes, under the
  source's ten-second deadline. Shared TMDB resolution has its own ten-second
  deadline. All extra episode reads carry the same linked user id.
- **Data minimization / DB:** nothing is persisted. The cache holds only
  secret-free TMDB summaries with progress and context, and is cleared on
  media link save, unlink, and account delete. No columns or migrations are added and no new DB
  writes are introduced. Existing SQLAlchemy unlink/delete operations continue
  to cancel and await history work under the scheduling guard before commit.
  The Home regression inspects every SQLite table after the read, verifies no
  item ids, positions, or progress were stored, and verifies no signal was added.
- **Frontend:** no change; existing cards render text and numbers only.
- **Dependencies:** none.

## Verification notes

- Compared all four MODIFIED requirement blocks against the living specs. Only
  the intended Jellyfin contribution, shared rail/cache, gating, and unlink
  changes differ; no intervening requirement text needed to be folded in. Delta
  spec wording was unchanged at initial archive. The approved review follow-up
  updates only the Jellyfin and Plex delta wording to describe bounded episode
  activity, distinct source/TMDB deadlines, and media-link cache invalidation;
  their living requirements are updated identically. The account-linking and
  app-settings deltas remain unchanged.
- Both new live contract cases are collected under the `live` marker. They seed
  distinct playback state on two disposable users and check resume/next-up
  isolation; account teardown removes that state. Live execution was not part of
  this local batch. It requires explicit disposable-user permission, server
  coordinates, and suitable library fixtures. Outcomes printed by the cases
  contain no user, item, credential, or server values.
