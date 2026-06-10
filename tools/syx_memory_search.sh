#!/usr/bin/env bash
set -euo pipefail

CALLER_DIR="$(pwd)"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEFAULT_REPO_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
ENV_FILE="${SCRIPT_DIR}/config/syx.env"

if [[ -f "${ENV_FILE}" ]]; then
  set -a
  source "${ENV_FILE}"
  set +a
fi

SYX_REPO_DIR="${SYX_REPO_DIR:-${DEFAULT_REPO_DIR}}"
SYX_BASE_URL="${SYX_BASE_URL:-http://127.0.0.1:8000}"

if [[ -x "${SYX_REPO_DIR}/venv/bin/python" ]]; then
  PYTHON_BIN="${SYX_PYTHON:-${SYX_REPO_DIR}/venv/bin/python}"
else
  PYTHON_BIN="${SYX_PYTHON:-python3}"
fi

usage() {
  echo "usage: $(basename "$0") --project-name <project> --query <query> [--category <category>] [--base-url <url>]" >&2
  echo "   or: $(basename "$0") <project> <query> [category]" >&2
}

PROJECT_NAME=""
QUERY=""
CATEGORY="SYNTHESIS"
BASE_URL="${SYX_BASE_URL}"

if [[ "${1:-}" == "--project-name" ]]; then
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --project-name)
        PROJECT_NAME="${2:-}"
        shift 2
        ;;
      --query)
        QUERY="${2:-}"
        shift 2
        ;;
      --category)
        CATEGORY="${2:-SYNTHESIS}"
        shift 2
        ;;
      --base-url)
        BASE_URL="${2:-${SYX_BASE_URL}}"
        shift 2
        ;;
      *)
        echo "error: unknown argument: $1" >&2
        usage
        exit 2
        ;;
    esac
  done
else
  PROJECT_NAME="${1:-}"
  QUERY="${2:-}"
  CATEGORY="${3:-SYNTHESIS}"
fi

if [[ -z "${PROJECT_NAME}" ]]; then
  echo "error: project name is required" >&2
  usage
  exit 2
fi

if [[ -z "${QUERY}" ]]; then
  echo "error: query is required" >&2
  usage
  exit 2
fi

if [[ ! -d "${SYX_REPO_DIR}" ]]; then
  echo "error: SYX_REPO_DIR does not exist: ${SYX_REPO_DIR}" >&2
  exit 4
fi

if [[ -z "${SYX_AGENT_TOKEN:-}" ]]; then
  echo "error: SYX_AGENT_TOKEN is not set" >&2
  exit 5
fi

cleanup() {
  cd "${CALLER_DIR}" || true
}

trap cleanup EXIT

cd "${SYX_REPO_DIR}"

"${PYTHON_BIN}" tools/agent_memory_search.py \
  --project-name "${PROJECT_NAME}" \
  --query "${QUERY}" \
  --category "${CATEGORY}" \
  --base-url "${BASE_URL}" \
  --pretty