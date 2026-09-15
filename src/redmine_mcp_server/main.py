"""
Main entry point for the MCP Redmine server.

This module uses FastMCP's native HTTP transport for MCP protocol communication.
The server runs with built-in HTTP endpoints and handles MCP requests natively.

Endpoints:
    - /mcp: Handles MCP requests via streamable HTTP transport.

Modules:
    - .tools: Per-resource MCP tool registrations (issues, projects, ...).
    - .server: Shared FastMCP instance.
    - .extensions: Hook for out-of-tree tool modules (REDMINE_MCP_EXTENSIONS).
"""

import importlib
import logging
import os
from contextlib import asynccontextmanager

import uvicorn
from importlib.metadata import version, PackageNotFoundError
from starlette.applications import Starlette
from starlette.routing import Mount, Route

# Configure basic logging before importing modules that log during init
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

from . import tools  # noqa: E402,F401  -- triggers @mcp.tool registration
from . import apps  # noqa: E402,F401  -- triggers MCP App registration
from . import _http_routes  # noqa: E402,F401  -- registers HTTP custom routes
from . import _cleanup  # noqa: E402
from .server import AUTH_PROVIDER, mcp, refresh_advertised_scopes  # noqa: E402
from ._mount import (  # noqa: E402
    mcp_mount_prefix,
    mcp_path_for_http_app,
)

logger = logging.getLogger(__name__)

from ._env import get_extension_modules  # noqa: E402
from ._plugin_visibility import apply_plugin_visibility, plugin_tag  # noqa: E402
from ._tool_allow_list import (  # noqa: E402
    _TOOL_KEY_PREFIX,
    build_tool_allow_list,
    registered_tool_names,
)
from ._extension_registry import REGISTERED_EXTENSIONS  # noqa: E402


def _registered_tool_objects() -> dict[str, object]:
    """Tool name -> the registered object, from the registry the allow list reads.

    :func:`._tool_allow_list.registered_tool_names` answers which names
    exist; :func:`_assert_import_matches_specs` also has to know whether a
    name still points at the same object, so it reads the one structure
    that helper reads rather than opening a second private path into
    FastMCP.
    """
    components = getattr(getattr(mcp, "_local_provider", None), "_components", None)
    if components is None:
        return {}
    return {
        key[len(_TOOL_KEY_PREFIX) :].split("@", 1)[0]: component
        for key, component in components.items()
        if key.startswith(_TOOL_KEY_PREFIX)
    }


def _action_values(tool: object) -> list[str] | None:
    """The values a tool's ``action`` parameter accepts, or ``None``.

    Read from the JSON schema FastMCP built for the tool, where a ``Literal``
    renders as ``enum``, or as ``const`` when it has one value. Anything
    else -- no ``action`` parameter, a plain ``str``, an ``Optional`` Literal
    -- is ``None``: there is no closed set of actions to hold a scope map to.
    """
    schema = getattr(tool, "parameters", None)
    if not isinstance(schema, dict):
        return None
    action = schema.get("properties", {}).get("action")
    if not isinstance(action, dict):
        return None
    if isinstance(action.get("const"), str):
        return [action["const"]]
    values = action.get("enum")
    if isinstance(values, list) and all(isinstance(v, str) for v in values):
        return values
    return None


def _assert_import_matches_specs(
    module_name: str,
    specs: list,
    names_before: set,
    objects_before: dict,
) -> None:
    """Hold one extension module to what it registered, or fail startup.

    :func:`extensions.register_extension` checks the spec against the three
    tables, which is what keeps an extension from taking an entry that is
    already someone else's. It cannot check the other half: that the module
    then defined the tools it described, only those, and with the actions
    its scope maps name. The two halves are written in different places in
    the module and nothing but this ties them together.

    Each mismatch is a ``RuntimeError`` naming the module and the tools,
    because each leaves a tool on the surface that one of the tables does
    not describe:

    - a tool the import added that no spec declares has no scope entry of
      its own, so the scope middleware has nothing to enforce on it;
    - a tool a spec declares that the import did not define is a table
      entry for nothing, which the anti-drift cross-checks read as drift;
    - a per-action scope map whose keys are not exactly the tool's
      ``action`` Literal, or one on a tool whose ``action`` is not a Literal
      at all: :func:`oauth_scopes.scopes_for_action` lets an action the map
      does not name through with no scope check, so the map has to cover a
      closed set, and only a Literal is one;
    - a pre-existing tool whose object changed means the module decorated a
      name this server already had. FastMCP's duplicate policy on ``mcp``
      is ``warn``, which logs and replaces, so nothing else stops it;
    - a tool added without the ``plugin:<family>`` tag of one of the
      import's own families is not reached by
      :func:`._plugin_visibility.apply_plugin_visibility`, so the family
      flag cannot hide it and it is listed even where the plugin is absent.

    Also a ``RuntimeError`` if the tool registry cannot be enumerated at
    all. The allow list reads the same private registry and treats it as
    best-effort, but it only spots typos with it; here it is what ties a
    module's tools to its spec, and everything else about loading an
    extension fails closed.
    """
    if not names_before:
        raise RuntimeError(
            "Cannot enumerate the registered tools, so the tools "
            f"'{module_name}' defines cannot be checked against what it "
            "declares. FastMCP's component registry, which this reads, has "
            "moved; an extension is not loaded on an unchecked import."
        )

    objects_after = _registered_tool_objects()
    added = registered_tool_names(mcp) - names_before
    declared = set()
    for spec in specs:
        declared |= set(spec.tool_kinds)

    undeclared = sorted(added - declared)
    if undeclared:
        raise RuntimeError(
            f"Extension module '{module_name}' defined tool(s) no "
            f"ExtensionSpec it registered declares: {', '.join(undeclared)}. "
            "A tool with no tool_kinds entry carries no annotations and a "
            "tool with no tool_scopes entry is not gated, so name every one "
            "of them in the spec."
        )

    missing = sorted(declared - added)
    if missing:
        raise RuntimeError(
            f"Extension module '{module_name}' declared tool(s) it never "
            f"defined: {', '.join(missing)}. The tables would carry an entry "
            "for a tool that does not exist, which is the drift the "
            "cross-checks over TOOL_KINDS and TOOL_SCOPES report."
        )

    for spec in specs:
        for tool_name, entry in spec.tool_scopes.items():
            if not isinstance(entry, dict):
                continue
            accepted = _action_values(objects_after[tool_name])
            if accepted is None:
                raise RuntimeError(
                    f"Extension module '{module_name}' gives {tool_name} "
                    "per-action scopes, but the tool has no action parameter "
                    "typed as a Literal of the actions it accepts. An action "
                    "the map does not name runs with no scope check, so the "
                    "map is held to the Literal, and only a Literal is a "
                    "closed set to hold it to."
                )
            unmapped = sorted(set(accepted) - set(entry))
            unaccepted = sorted(set(entry) - set(accepted))
            if unmapped or unaccepted:
                raise RuntimeError(
                    f"Extension module '{module_name}' gives {tool_name} "
                    "per-action scopes that do not match its action Literal. "
                    "Accepted but not in tool_scopes: "
                    f"{', '.join(unmapped) or 'none'}; in tool_scopes but not "
                    f"accepted: {', '.join(unaccepted) or 'none'}. An action "
                    "the map does not name runs with no scope check, and one "
                    "the tool does not accept is an entry for nothing."
                )

    replaced = sorted(
        name
        for name, component in objects_before.items()
        if objects_after.get(name) is not component
    )
    if replaced:
        raise RuntimeError(
            f"Extension module '{module_name}' replaced tool(s) this server "
            f"already had: {', '.join(replaced)}. Redefining a name that is "
            "already on the surface is how an extension would take over a "
            "built-in tool while keeping its scope entry. Pick names of "
            "your own."
        )

    family_tags = {plugin_tag(spec.family) for spec in specs}
    untagged = sorted(
        name
        for name in added
        if not (getattr(objects_after[name], "tags", None) or set()) & family_tags
    )
    if untagged:
        raise RuntimeError(
            f"Extension module '{module_name}' defined tool(s) without the "
            f"tag of any family it registered: {', '.join(untagged)}. "
            "Visibility is by tag, so a tool missing "
            f"tags={{plugin_tag(family)}} ({', '.join(sorted(family_tags))}) "
            "is listed even where the plugin is not installed."
        )


def _load_extensions() -> None:
    """Import every module ``REDMINE_MCP_EXTENSIONS`` names, in order.

    Runs after the built-in tool modules, so an extension that reuses a
    built-in tool name is refused rather than winning the race, and before
    plugin visibility, so the families it registers get their first
    on/off pass with everything else.

    Each import is held to its own specs by
    :func:`_assert_import_matches_specs`, and one line per registered family
    goes to the log, which is the only account of the extension surface a
    deployment can read without a token. An import that raises -- a typo in
    the variable, a missing dependency, a name collision -- stops the
    server: an extension registers tools and the scopes that gate them, so
    half of one is not a thing to serve.

    Finally, and only when something registered, the auth provider is told
    the widened scope list. It was built while ``server.py`` ran its own
    body, so it holds a snapshot taken before any of this; without the
    refresh an extension's scopes reach ``advertised_scopes()`` but not the
    documents served at ``/.well-known/``. A stock server registers nothing
    and its provider is never touched.

    Extracted from module scope so tests can drive it without reloading
    this module, which would rebuild the app and re-run every import for
    its side effects.
    """
    registered_at_entry = len(REGISTERED_EXTENSIONS)
    for name in get_extension_modules():
        already = len(REGISTERED_EXTENSIONS)
        names_before = registered_tool_names(mcp)
        objects_before = _registered_tool_objects()
        try:
            importlib.import_module(name)
        except Exception as exc:
            raise RuntimeError(
                f"REDMINE_MCP_EXTENSIONS names '{name}', which failed to "
                f"load: {exc}"
            ) from exc
        new_specs = REGISTERED_EXTENSIONS[already:]
        _assert_import_matches_specs(name, new_specs, names_before, objects_before)
        for spec in new_specs:
            logger.info(
                "extension loaded: family=%s enabled=%s tools=%d",
                spec.family,
                "true" if spec.enabled() else "false",
                len(spec.tool_kinds),
            )

    if len(REGISTERED_EXTENSIONS) > registered_at_entry:
        refresh_advertised_scopes(AUTH_PROVIDER)
        if AUTH_PROVIDER is not None:
            logger.info(
                "extensions: advertised scopes refreshed (%d scopes)",
                len(AUTH_PROVIDER.scopes_supported),
            )


_load_extensions()

# Hide plugin-gated tools whose plugin flag is off. Runs once at import,
# after every tool module has registered and after load_dotenv (the first
# tool module imports _client, which loads .env).
PLUGIN_VISIBILITY = apply_plugin_visibility(mcp)
_hidden = sorted(f for f, on in PLUGIN_VISIBILITY.items() if not on)
if _hidden:
    logger.info(
        "Plugin tool families hidden from tools/list (flag off): %s",
        ", ".join(_hidden),
    )

# Narrow the surface to REDMINE_MCP_ALLOW_TOOLS, if configured. Middleware
# rather than a visibility pass, so it filters whatever list the framework
# hands it and cannot widen the surface if FastMCP moves its internals.
TOOL_ALLOW_LIST = build_tool_allow_list(mcp)
if TOOL_ALLOW_LIST is not None:
    mcp.add_middleware(TOOL_ALLOW_LIST)
    logger.info(
        "Tool allow list active: %d name(s) allowed (%s). Plugin flags still "
        "apply, so a listed tool whose flag is off stays hidden.",
        len(TOOL_ALLOW_LIST.allowed),
        ", ".join(sorted(TOOL_ALLOW_LIST.allowed)),
    )

REDMINE_AUTH_MODE = os.environ.get("REDMINE_AUTH_MODE", "legacy").lower()
AUTHENTICATED_AUTH_MODES = {"oauth", "oauth-proxy", "api-key-login"}


def get_version() -> str:
    """Get package version from metadata."""
    try:
        return version("redmine-mcp-server")
    except PackageNotFoundError:
        return "dev"


def build_authenticated_app(mcp_instance, auth_provider):
    """Build a mounted ASGI app for authenticated modes."""
    mcp_path = mcp_path_for_http_app()
    mcp_app = mcp_instance.http_app(path=mcp_path, stateless_http=True)

    routes = list(auth_provider.get_well_known_routes(mcp_path=mcp_path))
    routes.extend(
        [
            Route("/health", _http_routes.health_check, methods=["GET"]),
            Route(
                "/files/{file_id}",
                _http_routes.serve_attachment,
                methods=["GET"],
            ),
            Route(
                "/cleanup/status",
                _http_routes.cleanup_status,
                methods=["GET"],
            ),
            Mount(mcp_mount_prefix(), app=mcp_app),
        ]
    )

    @asynccontextmanager
    async def lifespan(app):
        async with mcp_app.lifespan(app):
            # The OAuth endpoints write state to disk without authentication,
            # so its sweep starts with the server rather than waiting for the
            # first tool call or health check (#289).
            await _cleanup._ensure_cleanup_started()
            try:
                yield
            finally:
                await _cleanup.cleanup_manager.stop()

    return Starlette(routes=routes, lifespan=lifespan)


def build_app():
    """Build the ASGI app."""
    if REDMINE_AUTH_MODE == "legacy-per-user":
        from ._per_user import assert_startup_attestation

        assert_startup_attestation()

    if REDMINE_AUTH_MODE in AUTHENTICATED_AUTH_MODES and AUTH_PROVIDER is not None:
        return build_authenticated_app(mcp, AUTH_PROVIDER)

    return mcp.http_app(stateless_http=True)


# Export the Starlette app for testing and external use
# Must run before build_app(): custom_route registers on the FastMCP instance,
# and http_app() snapshots those routes. Imported only in this mode so legacy
# deployments never pull in the OAuth machinery, matching server.py.
if REDMINE_AUTH_MODE == "api-key-login":
    from . import _api_key_login_routes  # noqa: E402,F401  -- registers /login

app = build_app()

# Log version at module load time so it appears regardless of how the server is started
logger.info("Redmine MCP Server v%s", get_version())
logger.info("Auth mode: %s", REDMINE_AUTH_MODE)

# Imported lazily, matching server.py: legacy deployments should not pull in
# the OAuthProxy machinery just to skip logging about it.
if REDMINE_AUTH_MODE == "oauth-proxy":
    from ._oauth_proxy import log_oauth_proxy_store_path

    log_oauth_proxy_store_path(REDMINE_AUTH_MODE)

if REDMINE_AUTH_MODE == "api-key-login":
    from ._api_key_login import log_api_key_login_store_path

    log_api_key_login_store_path(REDMINE_AUTH_MODE)


def main():
    """Main entry point for the console script."""
    # Note: .env is already loaded during _client import
    # Note: version/auth mode are logged at module level
    # (works for both direct and uvicorn invocation)

    host = os.getenv("SERVER_HOST", "127.0.0.1")
    port = int(os.getenv("SERVER_PORT", "8000"))

    # Run with our app directly so custom routes (well-known endpoints) are served
    uvicorn.run(app, host=host, port=port, log_config=None)


if __name__ == "__main__":
    main()
