# Roadmap

## Project Status

- **Current Version:** v2.0.1 (released 2026-05-22)
- **On Develop (unreleased):** v2.1 — FastMCP v3 native auth migration ([PR #132](https://github.com/jztan/redmine-mcp-server/pull/132))
- **MCP Registry Status:** Published
- **Test Suite:** 1365 tests passing (1285 unit + 80 integration; 5 integration skipped — 4 behind `REDMINE_AGILE_ENABLED`, 1 destructive OAuth test behind `RUN_DESTRUCTIVE_TESTS=1`)
- **Tools:** 40 core + 5 plugin-gated + 1 admin-gated (maximum 46 with all flags enabled)

---

## Next Release

**v2.1 — FastMCP v3 native auth migration.** Merged to develop, awaiting release cut. Cut via `python scripts/release.py minor` per [`RELEASE_SOP.md`](RELEASE_SOP.md). See `[Unreleased]` in [`CHANGELOG.md`](CHANGELOG.md) for the full diff.

---

## Under Consideration

- [ ] **OpenTelemetry observability.** Optional `opentelemetry-sdk` dependency. Zero overhead when unconfigured; production-grade tracing (tool calls, Redmine API latency, error rates) when the OTEL SDK is present. Would need to document OTEL configuration in [`docs/contributing.md`](docs/contributing.md).

---

## Only If Users Request

These are not planned. They will be considered only if users open issues asking for them:

- YAML response format option
- User instructions file (`REDMINE_INSTRUCTIONS`)
- Bulk operations beyond `import_time_entries`

---

## Release History

For per-release detail (features, fixes, CVE patches, contributor credits, breaking changes), see:

- [`CHANGELOG.md`](CHANGELOG.md) — canonical changelog, every version since v0.1
- [GitHub Releases](https://github.com/jztan/redmine-mcp-server/releases) — release notes with installation instructions

---

**Last Updated:** 2026-05-22
