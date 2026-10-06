## Context

See proposal.md. The existing picker assumes all regular seasons equal Seerr's whole-series selection. Seerr 3.5.0 excludes zero-episode seasons and drops Specials unless enabled; a no-op maps to 202.

## Goals / Non-Goals

Retain the contributor's picker and optional season-array contract. Add only capability discovery and correctness fixes, without dependencies, durable state or configuration.

## Decisions

- Read `/api/v1/settings/public` through a typed Seerr client method. Parse two strict booleans: `enableSpecialEpisodes` and `partialRequestsEnabled`. Project effective TV capabilities `can_request_partial` and `can_request_specials`; Specials requires both flags. Missing flags default to false; unreadable or malformed settings disable both capabilities while preserving ordinary whole-series requests. Removing Specials was considered; the owner chose setting-aware support.
- Re-read the settings before creating any explicit season-list request. Reject all explicit lists with 422 when partial requests are disabled, including complete lists and [0]; unreadable settings yield generic failure without creation. Bare requests retain Seerr's regular-season "all" body and require no policy read. Check Specials support additionally when season 0 is present. Disabled support returns 422; a failed read returns the existing generic failure. Ordinary requests need no settings read. This catches stale discovery; changes after preflight remain non-atomic.
- Build one eligible season list in RequestButton: positive episode count, regular season or enabled Specials. Use it for picker triggering, defaults, All seasons and whole-series equivalence. Future seasons with episodes remain selectable.
- Share one current submission eligibility check across opening the picker, mutation and the Request button. A sole eligible Specials season is sent explicitly as [0] only while partial requests and Specials are enabled. Pin Standard/4K when the picker opens; a refreshed permission change blocks confirmation without switching the variant.
- Reject Seerr 202 before accepted-body fallbacks, so no status/cache/taste success side effects occur.
- Keep trap registration independent of Escape callback updates with React's effect event. Insert traps according to DOM containment, focus only the active trap, and restore focus only when removing it. Carry restoration targets past removed lower traps and preserve the original trigger for simultaneous nested mounts.
- Strengthen existing tests: actual detail/picker nesting, detail list excludes Specials, upstream fake checks the exact whole-series body for its 4K fixture.

The original proposal's claim that Seerr validates explicit season numbers against its catalog is incorrect. [Seerr 3.5.0](https://github.com/seerr-team/seerr/blob/v3.5.0/server/entity/MediaRequest.ts) uses explicit arrays as supplied, then removes disabled Specials and already requested or available seasons. Tasterr validates bounds and uniqueness but does not verify existence: a hand-crafted nonexistent season can consume the member's own quota. The picker derives numbers from TMDB; a second server-side catalog read remains out of scope.

The chosen policy deliberately permits only regular whole-series requests when partial requests are disabled or cannot be verified. Seerr's own UI can include enabled Specials in a forced full-season list; Tasterr leaves that case to Seerr instead of introducing catalog expansion or a server-side full-list validator. If policy permission disappears while a picker is open, confirmation creates no request, even when its old selection matched the whole series.

## Risks / Trade-offs

- Settings read adds one bounded request to TV discovery and explicit season-list submission; no retry and ordinary request degradation remain intact.
- A concurrent upstream setting change after validation cannot be made atomic across services; fresh submission validation narrows that window.
- No live Seerr credentials are assumed; source-pinned and mocked contract checks do not prove Sonarr dispatch.

## Security considerations

API checklist: existing session, CSRF, rate-limit and permission guards remain. Movie-season validation precedes unconfigured fallback. All inputs retain Pydantic validation, explicit response models and generic errors. No new mutation route or logging.

Outbound checklist: the new read uses a validated settings URL, fixed path, read key, five-second timeout and no retry. Parse only the two strict booleans, ignore other upstream fields, and never expose raw settings, keys, cookies, internal URLs or upstream bodies. Mutations still use only the member cookie.

Frontend checklist: season policy is rechecked at confirmation and the selected variant remains fixed. Text rendering and existing external URLs remain; no storage or secret changes. Focus and nested keyboard behavior have regressions; browser fixtures stay local. DB/auth/dependency checklists are unaffected.

## Migration Plan

No migration. Regenerate OpenAPI types, deploy code and specs together, and roll back the follow-up commit if needed.
