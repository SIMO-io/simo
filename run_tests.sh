#!/usr/bin/env bash
set -euo pipefail

# Runs SIMO regression tests using the packaged test settings.
# Assumptions:
# - PostgreSQL is available locally and the current DB user can create/drop DBs.
# - Python dependencies from `requirements.txt` are installed.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Allow running without installing the package (uses local sources).
export PYTHONPATH="${SCRIPT_DIR}/src${PYTHONPATH:+:${PYTHONPATH}}"

export DJANGO_SETTINGS_MODULE="simo.test_settings"

# Writable filesystem root for migrations that create media files.
export SIMO_TEST_BASE_DIR="${SIMO_TEST_BASE_DIR:-/tmp/SIMO_test}"
mkdir -p "${SIMO_TEST_BASE_DIR}/_var/media" "${SIMO_TEST_BASE_DIR}/_var/static" "${SIMO_TEST_BASE_DIR}/_var/public_media" "${SIMO_TEST_BASE_DIR}/_var/logs"

python -m django test simo.tests -v 2 --noinput
