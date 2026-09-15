# Extensions: tools for in-house Redmine plugins

> **Provisional.** `redmine_mcp_server.extensions` is not a settled interface yet:
> the names it exports, and what they do, may still change in a minor release. Pin
> the server version an extension was written against, and re-read this page before
> moving that pin.

## What it is

[Supported Redmine Plugins](../README.md#supported-redmine-plugins) covers plugins
other people can install. A plugin written for one organization is a different
problem: its API is real, but no public server can carry a tool for it.
`REDMINE_MCP_EXTENSIONS` names Python modules to import at startup, each of which
registers a family of tools of its own — no fork to rebase on every release, and no
second MCP server to authenticate against.

## Configuration

`REDMINE_MCP_EXTENSIONS` names the modules, which are imported in order. Unset means
none, which is the usual case.

```bash
# In .env file, comma- or whitespace-separated
REDMINE_MCP_EXTENSIONS=acme_redmine_mcp.widgets
```

The server imports each module by name, so the package that provides it has to be
installed in the same environment the server runs in — the same virtualenv, or the
same container image when the server runs in Docker.

## Writing an extension

The module registers first and defines its tools second, because `@mcp.tool()`
reads a tool's annotations out of the table at decoration time:

```python
# acme_redmine_mcp/widgets.py -- installed alongside redmine-mcp-server
import json
from typing import Any, Literal

from redmine_mcp_server.extensions import (
    ActionMode,
    ExtensionSpec,
    ToolKind,
    action_dispatch,
    get_redmine_client,
    handle_redmine_error,
    is_true_env,
    mcp,
    offloaded,
    plugin_tag,
    redmine_url,
    register_extension,
    wrap_insecure_content,
)

FAMILY = "acme_widgets"

register_extension(
    ExtensionSpec(
        family=FAMILY,
        enabled=lambda: is_true_env("REDMINE_ACME_WIDGETS_ENABLED"),
        tool_kinds={"manage_widget": ToolKind.WRITE_DESTRUCTIVE},
        tool_scopes={
            "manage_widget": {
                "list": frozenset({"view_acme_widgets"}),
                "create": frozenset({"manage_acme_widgets"}),
            }
        },
        advertised_read_scopes=("view_acme_widgets",),
        advertised_write_scopes=("manage_acme_widgets",),
    )
)


def _widgets_url(project_id: str) -> str:
    return f"{redmine_url()}/projects/{project_id}/widgets.json"


@offloaded
def _list_widgets(project_id: str, name: str = "") -> dict:
    try:
        payload = get_redmine_client().engine.request("get", _widgets_url(project_id))
    except Exception as e:
        return handle_redmine_error(
            e, "list widgets", {"resource_type": "project", "resource_id": project_id}
        )
    return {
        "widgets": [
            {**w, "name": wrap_insecure_content(w.get("name", ""))}
            for w in payload.get("widgets", [])
        ]
    }


@offloaded
def _create_widget(project_id: str, name: str = "") -> dict:
    try:
        payload = get_redmine_client().engine.request(
            "post",
            _widgets_url(project_id),
            headers={"Content-Type": "application/json"},
            data=json.dumps({"widget": {"name": name}}),
        )
    except Exception as e:
        return handle_redmine_error(
            e, "create widget", {"resource_type": "project", "resource_id": project_id}
        )
    # A 201 with an empty body decodes to True, so normalize to a dict.
    return payload if isinstance(payload, dict) else {"success": True}


@action_dispatch({"list": ActionMode.READ, "create": ActionMode.WRITE})
async def _manage_widget_dispatch(action: str, **kwargs: Any) -> Any:
    return {"list": _list_widgets, "create": _create_widget}


@mcp.tool(tags={plugin_tag(FAMILY)})
async def manage_widget(
    action: Literal["list", "create"], project_id: str, name: str = ""
) -> dict:
    """List or create widgets on a project.

    Args:
        action: `list` or `create`.
        project_id: Project id or identifier.
        name: Widget name. Required for `create`.

    Returns:
        The plugin's JSON, or `{"error": ...}`.
    """
    return await _manage_widget_dispatch(action, project_id=project_id, name=name)
```

Nothing here is a second registration path. The spec's entries are merged into the
same three tables the built-in tools use — visibility, annotations, and per-tool
scopes — so the allow list and OAuth scope enforcement, which read those tables,
cover an extension's tools unchanged, and a name already taken by a built-in tool
or by another extension fails startup rather than replacing it.

The `plugin:<family>` tag on each tool is what ties it to its family: a tool
carrying it is listed only while that family's `enabled()` is true, exactly as the
vendor plugin tools follow their own `REDMINE_*_ENABLED` flag.

## What is checked at startup

Loading an extension fails closed. Every one of these stops the server rather than
serving a surface that does not match what the module declared:

- The module fails to import.
- A spec field is the wrong shape.
- The family name, or one of the tool names, is already taken by a built-in tool or
  by another extension.
- `tool_kinds` and `tool_scopes` name different tools.
- The module defines a tool that no spec of its own declares.
- The module declares a tool that it never defines.
- The module redefines a tool this server already had.
- The module defines a tool without its family's `plugin:<family>` tag.
- A per-action `tool_scopes` entry does not match the tool's `action` parameter
  (below).
- The tool registry cannot be read, so what the module defined cannot be compared
  with what it declared.
- The auth provider is one this server does not recognize while an extension has
  scopes to advertise.

**A per-action scope map is checked against the tool's `action` parameter.** When a
`tool_scopes` entry is a dict keyed by action, that parameter has to be annotated
`Literal[...]`, and the dict's keys have to equal the `Literal`'s values exactly. A
missing key, an extra key, a plain `str` action, an `Optional[Literal[...]]`, or a
tool with no `action` parameter at all fails startup. The scope middleware looks the
call's action up in that map, so an action the map does not name would otherwise
reach the plugin with no scope check at all.

One line per family goes to the log as the modules load:

```
extension loaded: family=acme_widgets enabled=true tools=1
```

and one more once the advertised scopes have been handed back to the auth provider:

```
extensions: advertised scopes refreshed (36 scopes)
```

The log is not the only place a family shows up. `get_mcp_server_info` reports one
`plugin_flags` key per registered family, named after the family, next to the
built-in keys (`agile`, `checklists`, `products`, `crm`, `deals`, `dmsf`, `tags`).
The example above adds `"acme_widgets": true`, so a client can see the extension
surface for itself rather than only the server's log.

## Scopes

**Scopes are Redmine permissions, not names this server invents.** Anything in
`advertised_read_scopes` or `advertised_write_scopes` has to be registered by the
plugin through `Redmine::AccessControl` on the target instance, *and* ticked on the
Redmine OAuth application, before the first deploy that advertises it. Otherwise
consent fails with `invalid_scope` for the whole list, not just the new entry. Write
lists are suppressed under `REDMINE_MCP_READ_ONLY`, and both lists are advertised
only while the family's `enabled()` is true — the same rule the built-in plugin
scopes follow, so a Redmine without the plugin never sees a scope it does not
recognize.

The auth provider is built before the extension modules are imported, so it holds a
scope list taken before any of them registered. Once they have loaded, the server
hands it the widened list and logs the count. That refresh happens in all three
authenticated modes:

| Mode | Provider | What the refresh reaches |
|---|---|---|
| `oauth` | `RedmineAuthProvider` | the scopes the server advertises |
| `oauth-proxy` | FastMCP `OAuthProxy` | the scopes the server advertises |
| `api-key-login` | `ApiKeyLoginProvider` | the scopes the server advertises, and the ones it grants at authorize time |

Both `/.well-known/oauth-protected-resource/mcp` and the authorization-server
metadata are built from that list when the HTTP app is assembled, which is after the
refresh, so a family's scopes reach the documents a client reads. A server with no
extensions configured registers nothing and its provider is never touched. If the
provider is one this server does not recognize and an extension has scopes to
advertise, startup fails rather than serving discovery documents that quietly omit
them.

`REDMINE_MCP_SCOPES` still narrows the result in `oauth` and `api-key-login`, and
still rejects a name that is not advertised, so an extension scope can be named
there only while its family is enabled.

## What stays the extension's job

Two guarantees stay the extension's own to keep, because neither is middleware.
[Read-only mode](tool-reference.md#read-only-mode) is enforced by the tool:
`action_dispatch` refuses a `WRITE` action under `REDMINE_MCP_READ_ONLY`, which is
why the example above routes its write through it rather than calling the API
directly, and a tool that neither goes through it nor opens with its own
`is_read_only_mode()` guard still writes. And the wrapping described in
[Prompt injection protection](tool-reference.md#prompt-injection-protection) is
applied by each tool to the fields it returns, so a tool that hands back
user-controlled Redmine text passes it through `wrap_insecure_content` itself.

## The surface

These are the names an extension may import from `redmine_mcp_server.extensions`:

| Purpose | Names |
|---|---|
| Registering a family | `ExtensionSpec`, `register_extension` |
| Defining tools | `mcp`, `plugin_tag`, `offloaded`, `in_thread`, `action_dispatch`, `ActionMode`, `ToolKind` |
| Reaching Redmine | `get_redmine_client`, `redmine_url`, `handle_redmine_error`, `READ_ONLY_ERROR` |
| Returning content | `wrap_insecure_content` |
| Validation and environment | `is_positive_int`, `is_true_env`, `is_read_only_mode`, `is_crm_enabled` |

The module docstring of `src/redmine_mcp_server/extensions.py` is the reference for
what each of them does. Nothing else in the package is a stable import: the private
helpers behind these names are renamed and moved as the server changes, and an
extension ships separately from this distribution, so it cannot follow such a
rename. Import from `redmine_mcp_server.extensions` only, and pin the version.
