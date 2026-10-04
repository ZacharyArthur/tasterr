## Context

See proposal.md. Seerr 3.3.0 stores explicit destination fields but dispatches by server id independently of is4k. Native request permissions and status dimensions are separate for each variant. Anime defaults are chosen upstream before explicit overrides.

## Goals / Non-Goals

Provide explicit variant requests with current permissions and preserved upstream defaults. Keep whole-series requests, upstream quotas/approval/rules, and the aggregate browse badge. No DB migration, dependency, server-side destination cache, or downstream download monitoring.

## Decisions

- Read current permissions with the global key at user/{server-derived Seerr user id}; validate returned identity. Do not persist a stale login snapshot or depend on an expired user cookie for reads. Request mutations retain the member cookie only.
- Require native movie/TV request or 4K permission; ADMIN implies all. MANAGE_REQUESTS grants advanced selection, not requesting. Advanced selection requires ADMIN, MANAGE_REQUESTS, or REQUEST_ADVANCED. Re-check before every submission.
- Bare 4K requests require a matching default 4K server for the media type, checked again before creation. Advanced members may explicitly choose a validated non-default 4K server; discovery exposes separate default capability and the UI blocks bare confirmation without it. Failed service reads retain the generic fallback.
- Serialize availability invalidation with the existing per-key loader lock so an older in-flight read cannot repopulate the cache after invalidation completes.
- Add is4k to server discovery and is_4k to requests. Validate selected server variant and its exact profile/folder. Validate the selected server only instead of re-reading every detail. Distinguish failed reads from invalid input.
- Retain aggregate availability and playback; add regular_status/four_k_status. A requested or available variant cannot be requested again, but the other missing variant can. Whole-series TV remains unchanged; partial variants are not offered for re-request.
- Start with Use Seerr defaults. Quality selection alone sends no destination fields, preserving anime routing and administrator rules. Advanced selections explicitly send all three fields. Server choices are variant-filtered and invalidated when refetched options change.
- Query discovery only for configured, known titles with a missing variant. Cache browser options by media type within the authenticated session; clear on session changes. Await initial discovery; on unavailable discovery retain bare standard submission, never infer 4K permission.
- Fetch discovery details concurrently with bounded concurrency; keep partial successful discovery, but fail closed when validating a selected destination. No speculative server cache.
- On mutation success patch only the requested variant in the detail cache, preserving the other variant and playback; invalidate server availability and browser batch availability reads. Failed requests and invalid selections are visible with retry/cancel and server-built fallback where returned.
- Live contract calls the production client, prefers a non-default combination, checks stored attribution/variant/destination and records version. Cleanup begins even after ambiguous submission failures. Stored fields prove persistence, not downstream delivery; native administrator rules can rewrite supplied fields.

## Security considerations

API: session default-deny on discovery/request; request retains CSRF and mutation rate limits. Explicit response models expose capability booleans and only permitted destination metadata. Positive bounded title id, nonnegative bounded server/profile ids, maximum 4096-character root folder, all-or-none overrides. No upstream error text or internal URL returned; fallback uses validated external configuration.

Auth: fresh server-derived permission reads, returned identity verified; no browser-supplied bitmask or stale local admin flag grants access. No credentials/token/session changes except the existing bounded reauth. Unknown permission response fails closed. No schema/migration or new persistent credential material.

Outbound: only clients/ issues HTTP; validated settings base URLs, bounded timeouts, typed untrusted JSON, no forwarded browser headers or raw responses. API key for scoped reads only; member cookie for request mutations only. Reauth retries once and preserves variant/destination.

Frontend: text/native selects, no raw HTML, secrets, browser storage, or client-built external links. Controls have labels, pending states, cancellation and alerts; fixture browser tests stay local. Logs and evidence contain generic outcomes/version only.

Dependencies: none. Database checklist is unaffected; no new tables/columns. Existing security headers, mutation inventory and session mechanisms remain intact.

## Risks / Trade-offs

- Upstream administrator rules may rewrite advanced choices -> describe successful submission, not guaranteed downstream delivery; verify persisted fields in opt-in tests.
- Fresh permission/status reads add latency -> bounded timeout and generic fallback, browser type-level discovery cache, targeted validation.
- Upstream request can dispatch before cleanup -> live suite requires operator-supplied disposable title; no automatic live run.
- Fork CI needs approval -> report action_required; local gate/browser checks provide evidence before publication.

## Migration Plan

Deploy backend and generated frontend together. No database migration. Rollback both together. Archive this supplemental change on the existing PR branch before publication.
