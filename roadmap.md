# Roadmap

## Project Status

- **Current Version:** v2.0.1 (released 2026-05-22)
- **On Develop (unreleased):** v2.1 — FastMCP v3 native auth migration ([PR #132](https://github.com/jztan/redmine-mcp-server/pull/132))
- **MCP Registry Status:** Published
- **Test Suite:** 1285 unit tests + 85 integration tests. Integration tests gate on environment: a sandbox Redmine, plugin flags (`REDMINE_AGILE_ENABLED` etc.), and the destructive OAuth test behind `RUN_DESTRUCTIVE_TESTS=1`. Tests that can't run in the current environment skip cleanly with a clear reason.
- **Tools:** 40 core + 5 plugin-gated + 1 admin-gated (maximum 46 with all flags enabled)

---

## Next Release

**v2.1 — FastMCP v3 native auth migration.** Merged to develop, awaiting release cut. Cut via `python scripts/release.py minor` per [`RELEASE_SOP.md`](RELEASE_SOP.md). See `[Unreleased]` in [`CHANGELOG.md`](CHANGELOG.md) for the full diff.

---

## Tracking MCP 2026-07-28

The MCP spec [release candidate locked on 2026-05-21](https://blog.modelcontextprotocol.io/posts/2026-07-28-release-candidate/), with GA targeted for 2026-07-28. Protocol-level work is gated on FastMCP shipping support for the new spec; the goal is a single coordinated v3.0 release rather than two breaking cutovers.

**v3.0 scope (target: Q3 2026, gated on FastMCP):**

- [ ] **Stateless transport.** Adopt the new request model once FastMCP supports it. The `initialize` handshake and `Mcp-Session-Id` header are removed by the spec; per-request `_meta` replaces them.
- [ ] **Authorization hardening.** Fold the six OAuth/OIDC SEPs that ship with 2026-07-28 (mandatory `iss` validation per RFC 9207, OIDC `application_type` declaration, refresh-token handling improvements) into the FastMCP v3 auth path landing in v2.1. Doing the SEP work and the v3 auth migration in one release avoids a second breaking change for operators.
- [ ] **Error-code update.** Switch missing-resource errors from `-32002` to `-32602` on `/files/{file_id}`.
- [ ] **Cacheable list responses.** Add `ttlMs` / `cacheScope` hints to slow-changing read-only tools (`list_redmine_projects`, `list_redmine_issue_statuses`, `list_redmine_issue_priorities`, `list_redmine_trackers`, `list_redmine_users`, `list_redmine_versions`, `list_redmine_roles`, `list_project_members`, `list_time_entry_activities`).
- [ ] **JSON Schema 2020-12.** Use composition operators (`oneOf`, `anyOf`) where they improve `manage_X(action=...)` ergonomics.
- [ ] **W3C Trace Context propagation** in the OAuth middleware, added as part of the auth migration touch.

**v3.1+ (post-spec GA):**

- [ ] **Tasks Extension** for long-running operations: bulk `import_time_entries`, `search_entire_redmine`, `summarize_project_status`.
- [ ] **MCP Apps** (server-rendered UI) experimentation, only once adoption is clear.

**Out of scope for this track:** Roots and Sampling are deprecated by 2026-07-28 but the project does not use them, so the 12-month removal window is a no-op.

---

## Under Consideration

- [ ] **OpenTelemetry observability.** Optional `opentelemetry-sdk` dependency. Zero overhead when unconfigured; production-grade tracing (tool calls, Redmine API latency, error rates) when the OTEL SDK is present. Would need to document OTEL configuration in [`docs/contributing.md`](docs/contributing.md). Note: the 2026-07-28 spec deprecates protocol-level logging in favor of stderr or OpenTelemetry, so this item is increasingly aligned with the upstream direction.

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

**Last Updated:** 2026-05-24
