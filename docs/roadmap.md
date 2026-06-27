# Roadmap

## Project Status

- **Current Version:** v2.4.0 (released 2026-06-27)
- **On Develop (unreleased):** nothing queued
- **MCP Registry Status:** Published
- **Test Suite:** 1309 unit tests + 85 integration tests. Integration tests gate on environment: a sandbox Redmine, plugin flags (`REDMINE_AGILE_ENABLED` etc.), and the destructive OAuth test behind `RUN_DESTRUCTIVE_TESTS=1`. Tests that can't run in the current environment skip cleanly with a clear reason. Run them locally with `python tests/run_tests.py --all` or `--integration`.
- **Tools:** 40 core + 5 plugin-gated + 1 admin-gated (maximum 46 with all flags enabled)

---

## Latest Release

**v2.4.0** (2026-06-27) shipped the promotional demo page (GitHub Pages, deployed on version tags), the `get_redmine_issue` fix that restores journal field-change `details` and stops dropping field-only journals ([#161](https://github.com/jztan/redmine-mcp-server/issues/161), [#163](https://github.com/jztan/redmine-mcp-server/pull/163)), a direct `joserfc` floor clearing CVE-2026-48990, and prompt-injection wrapping extended to journal field-change values. Recent lineage: hosted OAuth (`oauth-proxy` mode) landed in **v2.3.0** (2026-06-12), and **v2.3.1** (2026-06-20) cleared CVE dependency bumps and removed the unused `fastapi[standard]` tree. See [`CHANGELOG.md`](../CHANGELOG.md) for full per-release detail.

Nothing is currently queued for the next release; `[Unreleased]` in [`CHANGELOG.md`](../CHANGELOG.md) is empty. The next substantial efforts are the MCP 2026-07-28 spec track and the interactive-UI (MCP Apps) work below.

---

## Tracking MCP 2026-07-28

The MCP spec [release candidate locked on 2026-05-21](https://blog.modelcontextprotocol.io/posts/2026-07-28-release-candidate/), with GA targeted for 2026-07-28. Protocol-level work is gated on FastMCP shipping support for the new spec; the goal is a single coordinated v3.0 release rather than two breaking cutovers.

**Gate status (2026-06-27):** still closed. FastMCP latest is [v3.4.1](https://gofastmcp.com/changelog) (2026-06-05) with no 2026-07-28 support yet (stateless transport, per-request `_meta`, or the new OAuth/OIDC SEPs); it does carry Apps Phase 1 from v3.2.0, relevant to the Interactive UI (MCP Apps) track below. The official Python SDK targets beta 2026-06-30 and stable v2 2026-07-27. Spec timeline unchanged.

**v3.0 scope (target: Q3 2026, gated on FastMCP):**

- [ ] **Stateless transport.** Adopt the new request model once FastMCP supports it. The `initialize` handshake and `Mcp-Session-Id` header are removed by the spec; per-request `_meta` replaces them.
- [ ] **Authorization hardening.** Fold the six OAuth/OIDC SEPs that ship with 2026-07-28 (mandatory `iss` validation per RFC 9207, OIDC `application_type` declaration, refresh-token handling improvements) onto the FastMCP-backed auth path that now exists (the introspection `oauth` mode shipped in v2.1, extended by the `oauth-proxy` mode in v2.3). Landing the SEP work on this foundation avoids a second breaking change for operators.
- [ ] **Error-code update.** Switch missing-resource errors from `-32002` to `-32602` on `/files/{file_id}`.
- [ ] **Cacheable list responses.** Add `ttlMs` / `cacheScope` hints to slow-changing read-only tools (`list_redmine_projects`, `list_redmine_issue_statuses`, `list_redmine_issue_priorities`, `list_redmine_trackers`, `list_redmine_users`, `list_redmine_versions`, `list_redmine_roles`, `list_project_members`, `list_time_entry_activities`).
- [ ] **JSON Schema 2020-12.** Use composition operators (`oneOf`, `anyOf`) where they improve `manage_X(action=...)` ergonomics.
- [ ] **W3C Trace Context propagation** in the OAuth middleware, added as part of the auth migration touch.

**v3.1+ (post-spec GA):**

- [ ] **Tasks Extension** for long-running operations: bulk `import_time_entries`, `search_entire_redmine`, `summarize_project_status`.

Interactive UI via MCP Apps moved out of this list into its own near-term track below, since Apps already shipped (Jan 2026) and is not gated on the 2026-07-28 spec.

**Out of scope for this track:** Roots and Sampling are deprecated by 2026-07-28 but the project does not use them, so the 12-month removal window is a no-op.

---

## Interactive UI (MCP Apps)

Committed direction (2026-06-27): become a reference adopter of the official [MCP Apps extension](https://modelcontextprotocol.io/extensions/apps/overview) (`ext-apps`, spec 2026-01-26), letting the agent render live, interactive views in the conversation instead of text. This is **not gated on the 2026-07-28 spec track** above: Apps shipped in January 2026 and already renders in the major clients (Claude, Claude Desktop, ChatGPT, VS Code GitHub Copilot, Microsoft 365 Copilot, Goose, and more), and FastMCP carries Apps support (Phase 1 from v3.2.0). Prefab (FastMCP's UI layer) is optional: an App is just a tool that declares a `ui://` HTML resource the host renders in a sandboxed iframe, with the app calling tools back over postMessage, so the UI can be authored directly without that dependency.

**Validating demand first.** Five candidate views are mocked up and open for feedback in [discussion #168](https://github.com/jztan/redmine-mcp-server/discussions/168): issue board, Gantt/timeline, project dashboard, time-sheet, and sprint burndown. Which views get built, and how far interactivity goes, is gated on that signal rather than assumed.

**First slice (planned).** A read-only `triage-board` that renders live issues from `list_redmine_issues`, proven end-to-end in one target client before any write-back is wired. Two server-specific unknowns to settle in design: serving the `ui://` resource over the streamable-HTTP transport, and how the app's `tools/call` callbacks authenticate under the `oauth` / `oauth-proxy` modes (the auth-times-UI intersection is the genuinely hard part). Interactive writes (for example drag-to-reassign via `update_redmine_issue`) follow once rendering is proven.

- [ ] Validate view demand via [#168](https://github.com/jztan/redmine-mcp-server/discussions/168)
- [ ] Read-only `triage-board` slice rendered in one target client
- [ ] Resolve `ui://`-over-streamable-HTTP serving and app-callback auth under the OAuth modes
- [ ] Interactive write-back, plus additional views prioritized by the #168 signal

---

## Under Consideration

- [ ] **MCP Prompts (workflow layer) — parked, not planned.** The idea: named, parameterized prompts (`triage-sprint`, `standup-digest`, etc.) that compose the existing tools into one-invocation slash-command workflows via a `@mcp.prompt()` decorator in a new `prompts.py`. **Why it is parked, not scheduled:** there is no evidence of user demand, and the value-add is thin: a strong client model already orchestrates the tools from a plain-English request, so the only real benefit is correctness-scaffolding for weaker models plus saving a retyped paragraph on repeated workflows. The motives that survive scrutiny (making the promo demo's sprint-triage narrative a real capability instead of client-side fiction; seeding future MCP Apps work) are internal, not user pain. **If revisited:** validate cheaply by shipping exactly one prompt (`triage-sprint`, which the demo already narrates) and watch for any usage or request signal before committing to a "layer." Reconsider in earnest only if the Interactive UI (MCP Apps) track lands and needs workflow definitions to render.

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

**Last Updated:** 2026-06-27
