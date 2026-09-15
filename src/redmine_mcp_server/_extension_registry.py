"""The registered-extension list, kept out of the server import cycle.

:func:`oauth_scopes.advertised_scopes` has to read the registry, and it runs
while ``server.py`` is still executing its own module body: building the auth
provider is what fills ``scopes_supported``, and that happens before ``mcp``
is bound. So the registry cannot live in :mod:`.extensions`, which imports
``.server`` for the ``mcp`` an extension decorates its tools with -- that
import would be a cycle, and it would fail every OAuth-mode startup rather
than only the deployments that set ``REDMINE_MCP_EXTENSIONS``.

This module therefore imports nothing but :mod:`._env`. :mod:`.extensions`
re-exports both names, which is the surface an extension depends on; nothing
outside this package should import this module directly.
"""

from typing import TYPE_CHECKING, List

from ._env import _is_read_only_mode

if TYPE_CHECKING:  # pragma: no cover - annotations only
    from .extensions import ExtensionSpec

# Registered extensions in registration order, empty on a stock deployment.
# ``main.py`` reads it to report what each imported module added. Treat it as
# read-only from outside :func:`extensions.register_extension`, which is what
# runs the collision checks before anything lands here.
REGISTERED_EXTENSIONS: "List[ExtensionSpec]" = []


def extension_advertised_scopes() -> list[str]:
    """Scopes the registered extensions add to ``scopes_supported``.

    Read lists come from every family whose ``enabled()`` is true; write
    lists additionally require that the server is not read-only. That is
    the rule :func:`oauth_scopes.advertised_scopes` already applies to the
    built-in plugin lists, and gating on the same flag that gates the tools
    is what keeps a Redmine without the plugin from ever seeing a scope it
    does not recognize.
    """
    read_only = _is_read_only_mode()
    scopes: list[str] = []
    for spec in REGISTERED_EXTENSIONS:
        if not spec.enabled():
            continue
        scopes += list(spec.advertised_read_scopes)
        if not read_only:
            scopes += list(spec.advertised_write_scopes)
    return scopes
