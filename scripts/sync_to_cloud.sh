#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

SSH_TARGET="${AI_SPIDER_SSH_TARGET:-root@45.205.27.116}"
REMOTE_ROOT="${AI_SPIDER_REMOTE_ROOT:-/opt/ai-spider-app}"
BACKEND_SERVICE="${AI_SPIDER_BACKEND_SERVICE:-ai-spider-backend.service}"
PUBLIC_URL="${AI_SPIDER_PUBLIC_URL:-http://45.205.27.116:8081/}"
RELEASE="${AI_SPIDER_RELEASE:-$(date +%Y%m%d%H%M%S)}"

MODE="full"
RUN_TESTS=1
RUN_BUILD=1
RESTART_BACKEND=1
VERIFY_DEPLOY=1
DRY_RUN=0

usage() {
  cat <<'EOF'
Usage:
  scripts/sync_to_cloud.sh [options]

Default behavior:
  Run backend regression tests, build frontend, create a new cloud release,
  rsync project code, preserve cloud .env files, switch current symlink,
  restart backend service, and verify the deployment.

Options:
  --frontend-only     Copy current cloud release, replace frontend src/dist only, do not restart backend.
  --skip-tests        Do not run backend unittest regression suite.
  --skip-build        Do not run npm frontend build.
  --no-restart        Do not restart backend after switching release.
  --no-verify         Do not run HTTP/systemd verification after deploy.
  --dry-run           Print commands without changing local/cloud state.
  --release NAME      Use a fixed release name instead of current timestamp.
  -h, --help          Show this help.

Environment overrides:
  AI_SPIDER_SSH_TARGET       Default: root@45.205.27.116
  AI_SPIDER_REMOTE_ROOT      Default: /opt/ai-spider-app
  AI_SPIDER_BACKEND_SERVICE  Default: ai-spider-backend.service
  AI_SPIDER_PUBLIC_URL       Default: http://45.205.27.116:8081/
  AI_SPIDER_RELEASE          Default: timestamp

Examples:
  scripts/sync_to_cloud.sh
  scripts/sync_to_cloud.sh --frontend-only
  AI_SPIDER_SSH_TARGET=root@1.2.3.4 scripts/sync_to_cloud.sh --skip-tests

Notes:
  This script intentionally does not sync database rows, data/, logs/, worker_runs/,
  or any .env file. Database/business-data sync must stay a separate, backed-up
  operation.
EOF
}

log() {
  printf '\n==> %s\n' "$*"
}

die() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

run() {
  if [[ "${DRY_RUN}" == "1" ]]; then
    printf '[dry-run]'
    printf ' %q' "$@"
    printf '\n'
    return 0
  fi
  "$@"
}

remote() {
  if [[ "${DRY_RUN}" == "1" ]]; then
    printf '[dry-run] ssh %q' "${SSH_TARGET}"
    printf ' %q' "$*"
    printf '\n'
    return 0
  fi
  ssh "${SSH_TARGET}" "$@"
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || die "Required command not found: $1"
}

parse_args() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --frontend-only)
        MODE="frontend"
        RESTART_BACKEND=0
        ;;
      --skip-tests)
        RUN_TESTS=0
        ;;
      --skip-build)
        RUN_BUILD=0
        ;;
      --no-restart)
        RESTART_BACKEND=0
        ;;
      --no-verify)
        VERIFY_DEPLOY=0
        ;;
      --dry-run)
        DRY_RUN=1
        ;;
      --release)
        [[ $# -ge 2 ]] || die "--release requires a value"
        RELEASE="$2"
        shift
        ;;
      -h|--help)
        usage
        exit 0
        ;;
      *)
        die "Unknown option: $1"
        ;;
    esac
    shift
  done
}

preflight() {
  require_command ssh
  require_command rsync
  require_command curl

  if [[ "${RUN_BUILD}" == "1" ]]; then
    require_command npm
  fi
  if [[ "${RUN_TESTS}" == "1" && "${MODE}" == "full" ]]; then
    require_command python3
  fi

  [[ -f "${REPO_ROOT}/frontend/package.json" ]] || die "frontend/package.json not found"
  [[ -d "${REPO_ROOT}/backend/app" ]] || die "backend/app not found"
  [[ "${RELEASE}" =~ ^[A-Za-z0-9._-]+$ ]] || die "Unsafe release name: ${RELEASE}"
}

run_local_checks() {
  cd "${REPO_ROOT}"

  if [[ "${RUN_TESTS}" == "1" && "${MODE}" == "full" ]]; then
    log "Running backend regression tests"
    run python3 -m unittest backend.tests.test_flow_regressions
  fi

  if [[ "${RUN_BUILD}" == "1" ]]; then
    log "Building frontend"
    run npm --prefix frontend run build
  fi
}

check_remote_layout() {
  log "Checking remote deployment layout"
  remote "set -e
test -d '${REMOTE_ROOT}'
test -d '${REMOTE_ROOT}/releases'
test -L '${REMOTE_ROOT}/current'
test -x '${REMOTE_ROOT}/venv/bin/python'
readlink -f '${REMOTE_ROOT}/current'"
}

create_full_release() {
  log "Creating remote release ${RELEASE}"
  remote "mkdir -p '${REMOTE_ROOT}/releases/${RELEASE}'"

  log "Rsyncing project code to release ${RELEASE}"
  run rsync -az --delete \
    --exclude='.git/' \
    --exclude='.env' \
    --exclude='.env.*' \
    --exclude='backend/.env' \
    --exclude='frontend/.env' \
    --exclude='frontend/.env.*' \
    --exclude='frontend/node_modules/' \
    --exclude='node_modules/' \
    --exclude='oss-storage/node_modules/' \
    --exclude='__pycache__/' \
    --exclude='.pytest_cache/' \
    --exclude='.mypy_cache/' \
    --exclude='.ruff_cache/' \
    --exclude='.DS_Store' \
    --exclude='data/' \
    --exclude='logs/' \
    --exclude='worker_runs/' \
    --exclude='*.pyc' \
    "${REPO_ROOT}/" "${SSH_TARGET}:${REMOTE_ROOT}/releases/${RELEASE}/"

  preserve_remote_env
  remote_sanity_check
}

ensure_remote_release_absent() {
  log "Checking remote release path"
  remote "test ! -e '${REMOTE_ROOT}/releases/${RELEASE}' || { echo 'release already exists: ${REMOTE_ROOT}/releases/${RELEASE}' >&2; exit 1; }"
}

create_frontend_release() {
  log "Copying current remote release to ${RELEASE}"
  remote "set -e; OLD=\$(readlink -f '${REMOTE_ROOT}/current'); NEW='${REMOTE_ROOT}/releases/${RELEASE}'; cp -a \"\$OLD\" \"\$NEW\""

  log "Rsyncing frontend source and build output"
  run rsync -az --delete "${REPO_ROOT}/frontend/dist/" "${SSH_TARGET}:${REMOTE_ROOT}/releases/${RELEASE}/frontend/dist/"
  run rsync -az --delete "${REPO_ROOT}/frontend/src/" "${SSH_TARGET}:${REMOTE_ROOT}/releases/${RELEASE}/frontend/src/"
  run rsync -az "${REPO_ROOT}/frontend/package.json" "${SSH_TARGET}:${REMOTE_ROOT}/releases/${RELEASE}/frontend/package.json"
  if [[ -f "${REPO_ROOT}/frontend/package-lock.json" ]]; then
    run rsync -az "${REPO_ROOT}/frontend/package-lock.json" "${SSH_TARGET}:${REMOTE_ROOT}/releases/${RELEASE}/frontend/package-lock.json"
  fi
}

preserve_remote_env() {
  log "Preserving cloud environment files"
  remote "set -e
NEW='${REMOTE_ROOT}/releases/${RELEASE}'
OLD=\$(readlink -f '${REMOTE_ROOT}/current')
for file in .env backend/.env frontend/.env; do
  if [ -f \"\$OLD/\$file\" ]; then
    mkdir -p \"\$NEW/\$(dirname \"\$file\")\"
    cp -p \"\$OLD/\$file\" \"\$NEW/\$file\"
    echo \"copied:\$file\"
  fi
done"
}

remote_sanity_check() {
  log "Running remote backend sanity check"
  remote "set -e
NEW='${REMOTE_ROOT}/releases/${RELEASE}'
OLD=\$(readlink -f '${REMOTE_ROOT}/current')
if ! cmp -s \"\$OLD/backend/requirements.txt\" \"\$NEW/backend/requirements.txt\"; then
  echo 'requirements changed; installing'
  '${REMOTE_ROOT}/venv/bin/pip' install -r \"\$NEW/backend/requirements.txt\"
fi
cd \"\$NEW/backend\"
'${REMOTE_ROOT}/venv/bin/python' -m py_compile app/main.py
PYTHONPATH=. '${REMOTE_ROOT}/venv/bin/python' - <<'PY'
from app.main import app
print(app.title)
PY"
}

switch_release() {
  log "Switching current symlink to ${RELEASE}"
  remote "set -e
chown -R root:root '${REMOTE_ROOT}/releases/${RELEASE}'
ln -sfn '${REMOTE_ROOT}/releases/${RELEASE}' '${REMOTE_ROOT}/current'
readlink -f '${REMOTE_ROOT}/current'"
}

restart_backend() {
  if [[ "${RESTART_BACKEND}" != "1" ]]; then
    log "Skipping backend restart"
    return 0
  fi

  log "Restarting backend service"
  remote "systemctl restart '${BACKEND_SERVICE}' && systemctl is-active '${BACKEND_SERVICE}'"
}

verify() {
  if [[ "${VERIFY_DEPLOY}" != "1" ]]; then
    log "Skipping verification"
    return 0
  fi

  log "Verifying public URL"
  run curl -fsSI --max-time 10 "${PUBLIC_URL}"

  log "Verifying backend health and services"
  remote "set -e
systemctl is-active '${BACKEND_SERVICE}'
systemctl is-active nginx
curl -fsS --max-time 10 http://127.0.0.1:8000/health
echo"
}

main() {
  parse_args "$@"
  preflight
  check_remote_layout
  run_local_checks
  ensure_remote_release_absent

  if [[ "${MODE}" == "frontend" ]]; then
    create_frontend_release
  else
    create_full_release
  fi

  switch_release
  restart_backend
  verify

  log "Deploy complete"
  printf 'release=%s\n' "${RELEASE}"
  printf 'current=%s/current\n' "${REMOTE_ROOT}"
}

main "$@"
