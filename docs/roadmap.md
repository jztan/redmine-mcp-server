# Roadmap

## Project Status

- **Current Version:** v2.9.0 (released 2026-08-01)
- **MCP Registry Status:** Published
- **Test Suite:** 1571 unit tests + 89 integration tests. Integration tests gate on environment: a sandbox Redmine, plugin flags (`REDMINE_AGILE_ENABLED` etc.), and the destructive OAuth test behind `RUN_DESTRUCTIVE_TESTS=1`. Tests that can't run in the current environment skip cleanly with a clear reason. Run them locally with `python tests/run_tests.py --all` or `--integration`.
- **Tools:** 45 core + 7 plugin-gated + 1 admin-gated (maximum 53 with all flags enabled). The core count includes the two `triage-board` tools (`show_triage_board`, plus the app-only `get_triage_board_data` which is registered but hidden from the model's tool list) and the two `project-dashboard` tools (`show_project_dashboard`, plus the app-only `get_project_dashboard_data`). Note: the 7 plugin tools are always registered and listed; their flag is enforced at call time (a disabled call returns an error), so disabling a plugin does not hide its tools. Only the 1 admin tool is conditionally registered (hidden unless `REDMINE_MCP_EXPOSE_ADMIN_TOOLS=true`).

---

## Tracking MCP 2026-07-28

The MCP spec [shipped on 2026-07-28](https://blog.modelcontextprotocol.io/posts/2026-07-28/) as scheduled: stateless protocol core (the `initialize` handshake and `Mcp-Session-Id` header are gone; protocol version, client identity, and capabilities travel in per-request `_meta`), the six OAuth/OIDC hardening SEPs, cacheable list results, and a formal extensions framework. Protocol-level work remains gated on FastMCP shipping stable support for the new spec; the goal is a single coordinated v3.0 release rather than two breaking cutovers.

**Gate status (2026-08-01):** opening, but not open. FastMCP released [v4.0.0b1](https://gofastmcp.com/changelog) on 2026-07-28, explicitly targeting the new spec: sessionless 2026-07-28 protocol with dual-serving of handshake-era clients from one deployment, stateless session state, the authorization SEPs (identity assertion per SEP-990, scope step-up per SEP-2350), and background tasks via the `io.modelcontextprotocol/tasks` extension (SEP-2663). It is still a beta; this project pins `fastmcp>=3.0.0,<4` and runs v3.4.5, which carries the Apps Phase 1 support (from v3.2.0) relied on by the Interactive UI (MCP Apps) track below (the `triage-board` slice shipped in v2.6.0, the `project-dashboard` view in v2.7.0). The v3.0 work starts when FastMCP 4 reaches a stable release worth migrating to.

**v3.0 scope (target: Q3 2026, gated on FastMCP):**

- [ ] **Stateless transport.** Adopt the new request model once FastMCP supports it. The `initialize` handshake and `Mcp-Session-Id` header are removed by the spec; per-request `_meta` replaces them.
- [ ] **Authorization hardening.** Fold the six OAuth/OIDC SEPs that ship with 2026-07-28 (mandatory `iss` validation per RFC 9207, OIDC `application_type` declaration, refresh-token handling improvements) onto the FastMCP-backed auth path that now exists (the introspection `oauth` mode shipped in v2.1, extended by the `oauth-proxy` mode in v2.3, and hardened in v2.8 with per-tool scope enforcement plus the opt-in self-AS discovery profile and `REDMINE_MCP_SCOPES` subsetting). Landing the SEP work on this foundation avoids a second breaking change for operators.
- [ ] **Error-code update.** Switch missing-resource errors from `-32002` to `-32602` on `/files/{file_id}`.
- [ ] **Cacheable list responses.** Add `ttlMs` / `cacheScope` hints to slow-changing read-only tools (`list_redmine_projects`, `list_redmine_issue_statuses`, `list_redmine_issue_priorities`, `list_redmine_trackers`, `list_redmine_users`, `list_redmine_versions`, `list_redmine_roles`, `list_project_members`, `list_time_entry_activities`).
- [ ] **JSON Schema 2020-12.** Use composition operators (`oneOf`, `anyOf`) where they improve `manage_X(action=...)` ergonomics.
- [ ] **W3C Trace Context propagation** in the OAuth middleware, added as part of the auth migration touch.

**v3.1+ (post-spec GA):**

- [ ] **Tasks Extension** for long-running operations: bulk `import_time_entries`, `search_entire_redmine`, `summarize_project_status`. Shipped in the final spec as the `io.modelcontextprotocol/tasks` extension (SEP-2663), and FastMCP 4 beta already carries background-task support, so this can ride the same migration.

Interactive UI via MCP Apps moved out of this list into its own near-term track below, since Apps already shipped (Jan 2026) and is not gated on the 2026-07-28 spec.

**Out of scope for this track:** SEP-2577 deprecates Roots, Sampling, and Logging in 2026-07-28, but the project uses none of them (no client-facing MCP logging either), so the removal window is a no-op.

---

## Interactive UI (MCP Apps)

Committed direction (2026-06-27): become a reference adopter of the official [MCP Apps extension](https://modelcontextprotocol.io/extensions/apps/overview) (`ext-apps`, spec 2026-01-26), letting the agent render live, interactive views in the conversation instead of text. This is **not gated on the 2026-07-28 spec track** above: Apps shipped in January 2026 and already renders in the major clients (Claude, Claude Desktop, ChatGPT, VS Code GitHub Copilot, Microsoft 365 Copilot, Goose, and more), and FastMCP carries Apps support (Phase 1 from v3.2.0). Prefab (FastMCP's UI layer) is optional: an App is just a tool that declares a `ui://` HTML resource the host renders in a sandboxed iframe, with the app calling tools back over postMessage, so the UI can be authored directly without that dependency.

**Prioritizing views with feedback.** Five candidate views are mocked up and open for feedback in [discussion #168](https://github.com/jztan/redmine-mcp-server/discussions/168): issue board, Gantt/timeline, project dashboard, time-sheet, and sprint burndown. That signal prioritizes which views come *after* the first slice, not whether Apps ships at all: the direction is already committed, and #168 has had little reach so far because outreach has not run, so its current quiet is a distribution artifact rather than a demand signal. The plan is to drive traffic to it as part of the visibility push (link it from the MCP/Redmine community posts) so it becomes a real experiment.

**First slice (shipped in v2.6.0).** A `triage-board` that renders live issues from `list_redmine_issues`, proven end-to-end in one target client. It was the cheapest view and seeds the committed Apps work, so it shipped without waiting on the #168 poll; the poll shapes view #2 onward. The two server-specific unknowns are settled: serving the `ui://` resource over the streamable-HTTP transport, and how the app's `tools/call` callbacks authenticate under the `oauth` / `oauth-proxy` modes (the auth-times-UI intersection, the genuinely hard part). Interactive write-back also shipped: dragging a card to another status column reassigns the issue's status via `update_redmine_issue` (an optimistic move that reverts with an explanation when Redmine rejects the transition; disabled in read-only mode).

- [x] Read-only `triage-board` slice rendered in one target client (Claude Desktop; self-loads, auto-resizes, columns fit the pane, styled to the #168 mockup)
- [x] Serve the `ui://` resource over streamable-HTTP: resolved. A `ui://` resource is a normal MCP resource read via `resources/read` over the existing `/mcp` transport, so no new HTTP route was needed.
- [x] Verify app-callback auth under the OAuth modes: proven at the server level. Under `oauth`, the app-callback tool `get_triage_board_data` is accepted with a valid Doorkeeper Bearer token (returns live issues) and rejected with 401 when the token is missing or invalid, exactly like any tool call. Under `oauth-proxy`, the server boots, protects `/mcp` (401 without a token), and advertises OAuth discovery (`authorization-server` metadata plus resource metadata at `/.well-known/oauth-protected-resource/mcp`). The app never contacts the server directly; the host forwards the callback over its own authenticated connection, so once a token is in the session the callback inherits it. Remaining optional confirmation: the live browser OAuth login through Claude Desktop under `oauth-proxy` (token minting via DCR + Redmine login), which is orthogonal to the callback mechanism.
- [x] Interactive write-back: drag-to-reassign issue status via `update_redmine_issue` (optimistic move, reverts on rejection; disabled in read-only mode). Shipped in v2.6.0.
- [ ] Drive traffic to [#168](https://github.com/jztan/redmine-mcp-server/discussions/168) via the visibility push to prioritize later views
- [x] Project dashboard view (open/closed, overdue, due-this-week, by-priority, recent activity; click any figure to drill into the matching issue list in-panel, Refresh re-fetches via the app-callable `get_project_dashboard_data`; read-only). Shipped in v2.7.0.
- [ ] Additional views prioritized by the #168 signal (Gantt/timeline, time-sheet, burndown)

> **Client note:** MCP hosts cache the `ui://` resource. After changing the board HTML, a server restart alone is not enough for an already-connected client (Claude Desktop) to pick it up: fully quit and reopen the client to refetch the resource.

---

## Under Consideration

- [ ] **Enterprise-Managed Authorization (EMA).** Anthropic's [enterprise-managed auth](https://claude.com/blog/enterprise-managed-auth) (beta, Okta-first) lets a Claude Team/Enterprise admin provision connector access centrally through the org's IdP, so users inherit access by group membership instead of each running a per-connector OAuth flow. It ships as an optional, additive extension to the MCP authorization spec ([`modelcontextprotocol/ext-auth`](https://github.com/modelcontextprotocol/ext-auth)), so it would not disturb the existing `legacy`/`legacy-per-user`/`oauth`/`oauth-proxy` modes. The structural mismatch: EMA assumes an enterprise IdP sits above the resource server, whereas this server's authorization server is Redmine's own Doorkeeper. Supporting it would mean a fifth auth mode that trusts IdP-issued tokens and maps the IdP subject to a Redmine user. That mapping (likely a Redmine-side OmniAuth/SSO bridge or service-account impersonation model), not the MCP plumbing, is the real blocker. Relevant only to operators who already front Redmine with Okta/Entra under Claude Enterprise; the `oauth-proxy` mode already covers centralized-OAuth needs for most self-hosters. Revisit when the extension graduates from beta and a user with that topology asks.

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

**Last Updated:** 2026-08-01
