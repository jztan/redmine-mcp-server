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
#   (none currently — add lines below as needed, with CVE id and justification)
set -e
exec pip-audit \
  "$@"
