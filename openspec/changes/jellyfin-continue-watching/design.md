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
- Plex behavior for Plex-only members is unchanged.

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
   under one key. The key is renamed to `continue-watching:user:{id}`; the
   existing `continue_watching_key` helper moves with it, so unlink and delete
   keep one call. A result with zero successful sources is cached as the empty
   negative entry. Alternative: per-source caches merged per request, rejected
   because it adds two keys and two invalidations for no user-visible gain.

3. **Jellyfin reads.** Two new client methods, both with the API key, explicit
   `userId`, `Fields=ProviderIds`, `EnableUserData=true`, and `Limit=50`:
   `GET /UserItems/Resume` (`IncludeItemTypes=Movie,Episode`, `MediaTypes=Video`)
   and `GET /Shows/NextUp` (`EnableResumable=false`, `EnableRewatching=false`).
   `JellyfinItem` gains optional `Type`, `RunTimeTicks`, `ParentIndexNumber`,
   `IndexNumber`, and `UserData.PlaybackPositionTicks`. Both endpoints exist on
   10.9+. A live contract confirms them.

4. **Jellyfin mapper lives in `catalog/jellyfin.py`.** It reads resume and
   next-up items concurrently, collects series ids from both, does one batched
   series lookup (≤100 ids, already bounded by two 50-item reads), and emits
   `ResumeCandidate`s. The TMDB-id validator currently private to
   `recommend/jellyfin_history.py` moves to `catalog/` (where both callers can
   import it without crossing the recommend boundary). Its behavior is unchanged.
   Next-up items without a series last-played time get the same negative-position
   sentinel Plex uses, so undated items stay after dated ones in source order.

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
- [Jellyfin's next-up can include long-idle series] → Jellyfin's own next-up
  date cutoff applies; Tasterr adds no extra filter.
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

- **Endpoints:** none added or changed. Home's response shape is unchanged.
- **Auth & sessions:** no credential handling changes. The Jellyfin API key
  stays server-side and is used only for reads scoped to the caller's linked
  Jellyfin user id, as the existing client rule requires (now listing resume
  and next-up).
- **Outbound HTTP:** both calls go through `clients/jellyfin.py` with the
  validated base URL, the existing timeout, no redirects, and the key only in
  the `Authorization` header. Responses are strictly parsed with unknown fields
  dropped. Volume is bounded: two 50-item reads plus one series batch per user
  per five minutes, under a ten-second deadline.
- **Data minimization / DB:** nothing is persisted. The cache holds only
  secret-free TMDB summaries with progress and context, and is cleared on
  unlink and account delete.
- **Frontend:** no change; existing cards render text and numbers only.
- **Dependencies:** none.
