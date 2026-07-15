# Tasterr

Tasterr is a self-hosted, Netflix-style discovery front end for a household media
stack. It combines the TMDB catalog with Seerr identity, library state, and requests,
then learns a separate taste profile for each signed-in user.

Version 1.0 supports Plex or local Seerr sign-in, composed discovery rails, search,
title details, availability badges, requests attributed to the signed-in member,
per-user taste signals and recommendations, and admin-managed regions, services,
rails, and appearance. It intentionally does not bundle Seerr, play media, import
Plex history, or run more than one Tasterr process.

## Quick start with an existing Seerr

Prerequisites are Docker with Compose, a running Seerr instance, a TMDB v3 API key,
and a Seerr API key. A shared Docker network is not required when Seerr is reachable
through a routable LAN hostname or address.

1. Copy `.env.example` to `.env`.
2. Set `SEERR_INTERNAL_URL` to a URL reachable from inside the Tasterr container,
   such as `http://seerr.home.arpa:5055`. Set `SEERR_EXTERNAL_URL` to the URL
   household browsers use for Seerr.
3. Fill `TMDB_API_KEY`, `SEERR_API_KEY`, and a randomly
   generated `TASTERR_SECRET_KEY`.
4. Start and verify Tasterr:

   ```console
   docker compose up -d --build
   docker compose ps
   curl --fail http://127.0.0.1:8000/api/v1/health
   ```

Open `http://127.0.0.1:8000`, sign in with an existing Seerr account, and use the
Settings screen as a Seerr administrator to select the region, streaming services,
rails, theme, and accent. SQLite migrations run automatically on first boot.

When Seerr runs on this same Docker host in another Compose project, an optional
external-network override is available; see the configuration guide. It is not used
for Seerr on another host.

For a published image, set `TASTERR_IMAGE=ghcr.io/OWNER/REPOSITORY:1.0.0`, then use
`docker compose pull` followed by `docker compose up -d --no-build`.

## Living documentation

- [Configuration and operations](docs/CONFIGURATION.md): every variable, proxy/TLS,
  first boot, degraded modes, backups, upgrades, rollback, and troubleshooting.
- [Architecture](docs/ARCHITECTURE.md): process and module boundaries, auth/request/
  taste flows, storage, caches, and generated API types.
- [Security policy](SECURITY.md): supported releases and private vulnerability
  reporting. The developer threat model lives in [docs/SECURITY.md](docs/SECURITY.md).
- [Release procedure](docs/RELEASING.md): deterministic checks, audits, live
  contracts, image verification, and rollback.

The living OpenSpec specifications under `openspec/specs/` define current behavior.
The documents under `docs/PRD.md` and `docs/SPEC.md` preserve the founding rationale
and are intentionally frozen.
