#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
WORKER_ENV="${WORKER_ENV_FILE:-${REPO_ROOT}/.env.worker.local}"
WORKER_PYTHON="${WORKER_PYTHON:-${REPO_ROOT}/.venv-worker/bin/python}"

if [[ -f "${WORKER_ENV}" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "${WORKER_ENV}"
  set +a
fi

if [[ ! -x "${WORKER_PYTHON}" ]]; then
  WORKER_PYTHON="$(command -v python3)"
fi

cd "${REPO_ROOT}"
exec "${WORKER_PYTHON}" -u -m worker.main "$@"
