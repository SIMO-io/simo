#!/usr/bin/env bash
set -euo pipefail

# Runs SIMO regression tests using the packaged test settings.
# Assumptions:
# - PostgreSQL is available locally and the current DB user can create/drop DBs.
# - Python dependencies from `requirements.txt` are installed.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

cd "${SCRIPT_DIR}"

# Allow running without installing the package (uses local sources).
export PYTHONPATH="${SCRIPT_DIR}/src${PYTHONPATH:+:${PYTHONPATH}}"

export DJANGO_SETTINGS_MODULE="simo.test_settings"

# Allow selecting a subset of tests (label/module/class/method).
DJANGO_TEST_ARGS=("simo.tests")
if [ "$#" -gt 0 ]; then
  DJANGO_TEST_ARGS=("$@")
fi

echo "Tip: run a single test module like:"
echo "  bash packages/simo/run_tests.sh simo.tests.test_virtual_automations_hook"

# Writable filesystem root for migrations that create media files.
export SIMO_TEST_BASE_DIR="${SIMO_TEST_BASE_DIR:-/tmp/SIMO_test}"
mkdir -p "${SIMO_TEST_BASE_DIR}/_var/media" "${SIMO_TEST_BASE_DIR}/_var/static" "${SIMO_TEST_BASE_DIR}/_var/public_media" "${SIMO_TEST_BASE_DIR}/_var/logs"

export COVERAGE_FILE="${SIMO_TEST_BASE_DIR}/.coverage"
COVERAGE_HTML_DIR="${SIMO_TEST_BASE_DIR}/coverage_html"

if python -m coverage --version >/dev/null 2>&1; then
  python -m coverage erase
  python -m coverage run --branch --source=simo -m django test -v 2 --noinput "${DJANGO_TEST_ARGS[@]}"
  python -m coverage report -m --skip-covered
  python -m coverage html -d "${COVERAGE_HTML_DIR}" --skip-covered
  echo
  echo "Coverage HTML report: ${COVERAGE_HTML_DIR}/index.html"
else
  echo "WARNING: 'coverage' is not installed; running tests without coverage." >&2
  python -m django test -v 2 --noinput "${DJANGO_TEST_ARGS[@]}"
fi
