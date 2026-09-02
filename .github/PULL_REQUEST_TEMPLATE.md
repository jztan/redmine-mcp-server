<!-- Thanks for contributing! See docs/contributing.md for setup and conventions.
     For features or non-trivial changes, please open an issue first so the
     approach can be discussed before you write code. Small bug fixes and doc
     typos can skip this. -->

## Summary

<!-- What this changes and why. Link the issue it addresses: Fixes #N -->

## Changes

-

## Testing

<!-- Commands you ran and their results, e.g. `python tests/run_tests.py --all`, new tests added. -->

## Checklist

- [ ] Linked to an issue above, or this is a small fix that doesn't need one
- [ ] `python tests/run_tests.py --all` passes (activate `.venv` first)
- [ ] `uv run black --check src/` and `uv run flake8 src/ --max-line-length=88` are clean
- [ ] `CHANGELOG.md` [Unreleased] has a bullet for user-facing changes
- [ ] No manual version bumps: `pyproject.toml`, `server.json`, and CHANGELOG version headers are managed by the release script
- [ ] Docs updated where behavior changed: README stays concise, details go to `docs/tool-reference.md`
- [ ] Change works with both local (`uv run python -m redmine_mcp_server.main`) and Docker (`docker-compose up`) deployments
