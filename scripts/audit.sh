#!/usr/bin/env bash
# Shared pip-audit invocation. Used by:
#   - .github/workflows/dependency-audit.yml
#   - .github/workflows/publish-pypi.yml
#   - scripts/release.py (preflight)
#
# Keep the ignore list here, in one place, so local preflight and CI cannot drift.
#
# Invocation pattern from callers:
#   uv export --no-hashes --no-emit-project > /tmp/requirements-audit.txt
#   bash scripts/audit.sh -r /tmp/requirements-audit.txt --strict
#
# Ignored vulnerabilities (no upstream fix, or false-positive for our usage):
#   CVE-2026-114605 dnspython: the fix (2.9.0) needs Python 3.11, so Python 3.10
#     stays on 2.8.0. dnspython only comes in through email-validator, which
#     pydantic calls with check_deliverability=False. Python 3.11+ locks 2.9.1.
#     Drop this entry with Python 3.10 support.
set -e
exec pip-audit \
  --ignore-vuln CVE-2026-114605 \
  "$@"
