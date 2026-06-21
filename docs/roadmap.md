# Roadmap

## Project Status

- **Current Version:** v2.2.0 (released 2026-06-06)
- **On Develop (unreleased):** v2.3 candidate: hosted OAuth via the `oauth-proxy` auth mode ([#153](https://github.com/jztan/redmine-mcp-server/pull/153)), plus hardening ([#154](https://github.com/jztan/redmine-mcp-server/pull/154), [#155](https://github.com/jztan/redmine-mcp-server/pull/155)) and tooling/doc fixes ([#156](https://github.com/jztan/redmine-mcp-server/pull/156), [#157](https://github.com/jztan/redmine-mcp-server/pull/157))
- **MCP Registry Status:** Published
- **Test Suite:** 1305 unit tests + 85 integration tests. Integration tests gate on environment: a sandbox Redmine, plugin flags (`REDMINE_AGILE_ENABLED` etc.), and the destructive OAuth test behind `RUN_DESTRUCTIVE_TESTS=1`. Tests that can't run in the current environment skip cleanly with a clear reason. Run them locally with `python tests/run_tests.py --all` or `--integration`.
- **Tools:** 40 core + 5 plugin-gated + 1 admin-gated (maximum 46 with all flags enabled)

---

## Next Release

**v2.3: hosted OAuth (`oauth-proxy` auth mode).** The MCP server can now act as the OAuth authorization server for MCP clients (serving Dynamic Client Registration plus `/authorize`, `/token`, `/register`) and proxy the upstream flow to Redmine/Doorkeeper, keeping consent on Redmine. This resolves split-host OAuth discovery for clients that require DCR or RFC 8414 metadata, which the introspection-based `oauth` mode (shipped in v2.1) could not provide ([#140](https://github.com/jztan/redmine-mcp-server/issues/140), verified end-to-end in VS Code on a split-host Redmine 6.1.1 deployment). Merged to develop with client redirect-URI and secret-handling hardening, awaiting release cut via `python scripts/release.py minor` per [`RELEASE_SOP.md`](../RELEASE_SOP.md). See `[Unreleased]` in [`CHANGELOG.md`](../CHANGELOG.md) for the full diff.

---

## Tracking MCP 2026-07-28

The MCP spec [release candidate locked on 2026-05-21](https://blog.modelcontextprotocol.io/posts/2026-07-28-release-candidate/), with GA targeted for 2026-07-28. Protocol-level work is gated on FastMCP shipping support for the new spec; the goal is a single coordinated v3.0 release rather than two breaking cutovers.

**v3.0 scope (target: Q3 2026, gated on FastMCP):**

- [ ] **Stateless transport.** Adopt the new request model once FastMCP supports it. The `initialize` handshake and `Mcp-Session-Id` header are removed by the spec; per-request `_meta` replaces them.
- [ ] **Authorization hardening.** Fold the six OAuth/OIDC SEPs that ship with 2026-07-28 (mandatory `iss` validation per RFC 9207, OIDC `application_type` declaration, refresh-token handling improvements) onto the FastMCP-backed auth path that now exists (the introspection `oauth` mode shipped in v2.1, extended by the `oauth-proxy` mode in v2.3). Landing the SEP work on this foundation avoids a second breaking change for operators.
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

- [ ] **OpenTelemetry observability.** Optional `opentelemetry-sdk` dependency. Zero overhead when unconfigured; production-grade tracing (tool calls, Redmine API latency, error rates) when the OTEL SDK is present. Would need to document OTEL configuration in [`contributing.md`](contributing.md). Note: the 2026-07-28 spec deprecates protocol-level logging in favor of stderr or OpenTelemetry, so this item is increasingly aligned with the upstream direction.

- [ ] **Enterprise-Managed Authorization (EMA).** Anthropic's [enterprise-managed auth](https://claude.com/blog/enterprise-managed-auth) (beta, Okta-first) lets a Claude Team/Enterprise admin provision connector access centrally through the org's IdP, so users inherit access by group membership instead of each running a per-connector OAuth flow. It ships as an optional, additive extension to the MCP authorization spec ([`modelcontextprotocol/ext-auth`](https://github.com/modelcontextprotocol/ext-auth)), so it would not disturb the existing `legacy`/`oauth`/`oauth-proxy` modes. The structural mismatch: EMA assumes an enterprise IdP sits above the resource server, whereas this server's authorization server is Redmine's own Doorkeeper. Supporting it would mean a fourth auth mode that trusts IdP-issued tokens and maps the IdP subject to a Redmine user. That mapping (likely a Redmine-side OmniAuth/SSO bridge or service-account impersonation model), not the MCP plumbing, is the real blocker. Relevant only to operators who already front Redmine with Okta/Entra under Claude Enterprise; the `oauth-proxy` mode already covers centralized-OAuth needs for most self-hosters. Revisit when the extension graduates from beta and a user with that topology asks.

---

## Only If Users Request

These are not planned. They will be considered only if users open issues asking for them:

- YAML response format option
- User instructions file (`REDMINE_INSTRUCTIONS`)
- Bulk operations beyond `import_time_entries`

---

## Release History

For per-release detail (features, fixes, CVE patches, contributor credits, breaking changes), see:

- [`CHANGELOG.md`](../CHANGELOG.md) — canonical changelog, every version since v0.1
- [GitHub Releases](https://github.com/jztan/redmine-mcp-server/releases) — release notes with installation instructions

---

**Last Updated:** 2026-06-21
