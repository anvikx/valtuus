#!/usr/bin/env bash
# Runs on the server. Starts one image tag and rolls back when it is not healthy.
#
#   pull <tag> -> up --wait --+-- healthy ---> save <tag> as last good, prune
#                             |
#                             +-- unhealthy -> print logs, start last good tag, exit 1
#
# Usage: REGISTRY=ghcr.io/org/repo ./deploy.sh <tag>
set -euo pipefail

readonly LAST_GOOD_FILE=".last_good_tag"
readonly WAIT_TIMEOUT_SECONDS=90
readonly LOG_LINES=100

# CI copies scripts/deploy.sh next to docker-compose.yml with its folder kept, so the
# compose project root is one level up (same layout as the repo).
cd "$(dirname "$0")/.."

usage() {
  echo "Usage: REGISTRY=<registry> $0 <tag>" >&2
  exit 2
}

start_tag() {
  IMAGE_TAG="$1" docker compose up -d --no-build --remove-orphans \
    --wait --wait-timeout "${WAIT_TIMEOUT_SECONDS}"
}

rollback() {
  docker compose logs --tail "${LOG_LINES}" backend || true

  if [[ ! -f "${LAST_GOOD_FILE}" ]]; then
    echo "No last good tag. Nothing to roll back to." >&2
    return
  fi

  local last_good
  last_good="$(<"${LAST_GOOD_FILE}")"
  echo "Rolling back to ${last_good}" >&2
  SKIP_DATABASE_MIGRATIONS=true start_tag "${last_good}" || echo "Rollback to ${last_good} failed" >&2
}

main() {
  if [[ $# -ne 1 || -z "${REGISTRY:-}" ]]; then
    usage
  fi

  local tag="$1"
  export REGISTRY

  IMAGE_TAG="${tag}" docker compose pull

  if ! SKIP_DATABASE_MIGRATIONS=false start_tag "${tag}"; then
    echo "Deploy of ${tag} is not healthy" >&2
    rollback
    exit 1
  fi

  echo "${tag}" >"${LAST_GOOD_FILE}"
  docker image prune -af
  echo "Deployed ${tag}"
}

main "$@"
