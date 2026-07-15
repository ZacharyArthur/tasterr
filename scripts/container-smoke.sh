#!/usr/bin/env bash
set -euo pipefail

# This smoke owns a unique Compose project, image tag, default network, env file,
# and named volume. It never reads the deployment .env.
suffix="${GITHUB_RUN_ID:-local}-$$-$(date +%s)"
project="tasterr-smoke-${suffix}"
image="${project}:test"
network="${project}_default"
volume="${project}_tasterr-data"
env_file="$(mktemp -t tasterr-smoke.XXXXXX.env)"
container=""

cleanup() {
    status=$?
    set +e
    docker compose --project-name "$project" --env-file "$env_file" down \
        --volumes --remove-orphans >/dev/null 2>&1
    docker image rm --force "$image" >/dev/null 2>&1
    docker network rm "$network" >/dev/null 2>&1
    rm -f "$env_file"
    return "$status"
}
trap cleanup EXIT INT TERM

command -v docker >/dev/null
docker compose version >/dev/null

chmod 600 "$env_file"
{
    printf '%s\n' \
        'TMDB_API_KEY=container-smoke-placeholder' \
        'SEERR_INTERNAL_URL=http://seerr.invalid:5055' \
        'SEERR_EXTERNAL_URL=https://seerr.invalid' \
        'SEERR_API_KEY=container-smoke-placeholder' \
        'TASTERR_SECRET_KEY=container-smoke-placeholder' \
        'TASTERR_FORWARDED_ALLOW_IPS=127.0.0.1' \
        "TASTERR_IMAGE=$image" \
        'TASTERR_HTTP_PORT=0' \
        "TASTERR_ENV_FILE=$env_file"
} >"$env_file"

compose() {
    docker compose --project-name "$project" --env-file "$env_file" "$@"
}

wait_healthy() {
    container="$(compose ps --quiet tasterr)"
    if [[ -z "$container" ]]; then
        echo "container smoke: Tasterr container was not created" >&2
        return 1
    fi
    for _ in $(seq 1 60); do
        status="$(docker inspect --format '{{.State.Health.Status}}' "$container")"
        if [[ "$status" == "healthy" ]]; then
            return 0
        fi
        if [[ "$status" == "unhealthy" ]]; then
            compose logs --no-color tasterr >&2
            return 1
        fi
        sleep 1
    done
    compose logs --no-color tasterr >&2
    echo "container smoke: healthcheck timed out" >&2
    return 1
}

compose config --quiet
compose build tasterr
compose up --detach --no-build tasterr
wait_healthy

docker exec "$container" python -c \
    "import urllib.request; assert urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=3).status == 200"
docker exec "$container" python -c \
    "import urllib.request; body = urllib.request.urlopen('http://127.0.0.1:8000/', timeout=3).read(); assert b'<div id=\"root\"></div>' in body"

uid="$(docker exec "$container" id -u)"
if [[ "$uid" == "0" ]]; then
    echo "container smoke: runtime uid must be non-root" >&2
    exit 1
fi
docker exec "$container" test -f /data/tasterr.db
docker exec "$container" python -c \
    "import sqlite3; db = sqlite3.connect('/data/tasterr.db'); db.execute('CREATE TABLE container_smoke (marker TEXT PRIMARY KEY)'); db.execute('INSERT INTO container_smoke VALUES (?)', ('persisted',)); db.commit(); db.close()"

compose up --detach --no-build --force-recreate tasterr
wait_healthy
docker exec "$container" python -c \
    "import sqlite3; db = sqlite3.connect('/data/tasterr.db'); row = db.execute('SELECT marker FROM container_smoke').fetchone(); db.close(); assert row == ('persisted',)"

echo "container smoke: health, SPA, non-root uid, and volume persistence passed"

# Successful runs also prove the cleanup routine removed every owned resource.
cleanup
trap - EXIT INT TERM
if docker container inspect "$container" >/dev/null 2>&1 \
    || docker network inspect "$network" >/dev/null 2>&1 \
    || docker image inspect "$image" >/dev/null 2>&1 \
    || docker volume inspect "$volume" >/dev/null 2>&1; then
    echo "container smoke: disposable Docker resource survived cleanup" >&2
    exit 1
fi
