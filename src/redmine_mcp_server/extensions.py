"""Let an out-of-tree package add MCP tools for an in-house Redmine plugin.

Plenty of Redmine installations run a plugin written for one organization.
Its JSON API is real, its users would like an agent to reach it, and no
public server can carry a tool for it. The alternatives without this module
are a fork, which costs a rebase on every release, or a second MCP server
next to this one, which doubles the auth setup. So instead a separate Python
package registers its tools here at startup::

    REDMINE_MCP_EXTENSIONS=acme_redmine_mcp.widgets

This module is provisional. Its names and the shape of :class:`ExtensionSpec`
may still change in a minor release while the hook settles, so an extension
should pin the server version it was written against.

``main.py`` imports each named module in order, after the built-in tool
modules and before plugin visibility is applied. The module calls
:func:`register_extension` first and defines its tools second::

    from redmine_mcp_server.extensions import (
        ExtensionSpec,
        ToolKind,
        is_true_env,
        mcp,
        plugin_tag,
        register_extension,
    )

    register_extension(
        ExtensionSpec(
            family="acme_widgets",
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

    @mcp.tool(tags={plugin_tag("acme_widgets")})
    async def manage_widget(action: str, project_id: str) -> dict:
        ...

The order inside the module is not a style preference: ``@mcp.tool()``
reads the tool's annotations out of ``TOOL_KINDS`` at decoration time, so
the entry has to be there before the decorator runs.

This is not a second way to register a tool. An extension's tools go
through the same three tables the built-in ones do -- ``PLUGIN_FLAGS`` for
visibility, ``TOOL_KINDS`` for annotations, ``TOOL_SCOPES`` for scope
enforcement -- so the allow list and the scope middleware, both of which
read those tables, cover them unchanged, and the anti-drift cross-checks
hold them to the same kind/scope agreement (only the assertions that count
this tree's own inventory subtract them). What an extension cannot do is
take a name that is already in one of those tables; that raises and fails
startup, because a silent overwrite of a built-in tool's scope entry is the
one mistake here that opens an endpoint rather than closing one.

The other half of that agreement is checked around the import itself:
``main.py`` compares the tool registry before and after, and refuses a
module that defines a tool no spec of its own declares, declares one it
never defines, gives a tool per-action scopes whose keys are not its
``action`` Literal, redefines a tool this server already had, or defines
one without its family's ``plugin:<family>`` tag. FastMCP's duplicate-tool
policy on ``mcp`` is ``warn``, which logs and replaces, so nothing else
would stop the redefinition.

Read-only mode is the exception, and the one thing a tool here has to
apply itself: nothing in the middleware stack enforces it, so a built-in
write tool either goes through :func:`action_dispatch`, which refuses a
``WRITE`` action under ``REDMINE_MCP_READ_ONLY``, or opens with its own
``is_read_only_mode()`` guard. An extension's write tools do the same. The
same is true of ``wrap_insecure_content`` on user-controlled text.

Besides the spec, the names in ``__all__`` are the rest of the contract:
the building blocks a tool needs, re-exported without their leading
underscore. An extension ships separately from this distribution and
cannot follow a rename of a private helper, so this module, and not the
private module layout, is what it depends on.
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import NoReturn

from . import _client
from ._annotations import TOOL_KINDS, ToolKind
from ._decorators import ActionMode, action_dispatch
from ._env import (
    SERVER_INFO_PLUGIN_FLAGS,
    _is_crm_enabled,
    _is_read_only_mode,
    _is_true_env,
)
from ._errors import _READ_ONLY_ERROR, _handle_redmine_error
from ._extension_registry import REGISTERED_EXTENSIONS
from ._offload import in_thread, offloaded
from ._plugin_visibility import PLUGIN_FLAGS, plugin_tag
from ._serialization import wrap_insecure_content
from ._validation import _is_positive_int, _reject_non_scalar_filter_values
from .oauth_scopes import TOOL_SCOPES, ToolScopeEntry
from .server import mcp

__all__ = [
    "ActionMode",
    "ExtensionSpec",
    "READ_ONLY_ERROR",
    "ToolKind",
    "action_dispatch",
    "get_redmine_client",
    "handle_redmine_error",
    "in_thread",
    "is_crm_enabled",
    "is_positive_int",
    "is_read_only_mode",
    "is_true_env",
    "mcp",
    "offloaded",
    "plugin_tag",
    "redmine_url",
    "register_extension",
    "wrap_insecure_content",
]

# Public aliases for the helpers every plugin tool in this tree uses. These
# are bindings, not wrappers, which is exactly how the built-in tool modules
# import them, so an extension behaves the same under the same test patches.
get_redmine_client = _client._get_redmine_client
handle_redmine_error = _handle_redmine_error
READ_ONLY_ERROR = _READ_ONLY_ERROR
is_crm_enabled = _is_crm_enabled
is_positive_int = _is_positive_int
is_read_only_mode = _is_read_only_mode
is_true_env = _is_true_env


def redmine_url() -> str | None:
    """The configured Redmine base URL, read at call time.

    A function rather than a re-exported constant because
    ``_client.REDMINE_URL`` is a module attribute: ``load_dotenv`` fills it
    at import and the tests patch it afterwards. An extension that bound it
    at its own import time would hold whatever was there first. Every
    built-in plugin tool reads it through the module for the same reason.
    """
    return _client.REDMINE_URL


@dataclass(frozen=True, kw_only=True)
class ExtensionSpec:
    """What one extension family contributes to the server's tables.

    Keyword-only: an extension ships separately from this distribution, so
    the order of the fields must never become something it can depend on.
    :func:`register_extension` type-checks every one of them before any
    table is touched, because a field of the wrong shape shows up much
    later -- as an unannotated tool, or as one scope per character in
    ``scopes_supported`` -- rather than where it was written.

    Attributes:
        family: Name of the family, unique across ``PLUGIN_FLAGS`` and
            across the built-in keys of ``get_mcp_server_info``'s
            ``plugin_flags`` (``_env.SERVER_INFO_PLUGIN_FLAGS``), which
            are not the same set. It becomes the FastMCP tag
            ``plugin:<family>``, which every tool the extension defines
            carries as ``tags={plugin_tag(family)}``.
        enabled: Whether this family's tools are listed. Called on every
            visibility pass, on every :func:`oauth_scopes.advertised_scopes`
            call, and once at startup for the log line, so it reads its
            answer rather than caching it -- usually
            ``lambda: is_true_env("REDMINE_ACME_WIDGETS_ENABLED")``.
        tool_kinds: Tool name -> :class:`ToolKind`, merged into
            ``TOOL_KINDS``. One entry per tool the extension defines, and
            no more: a stale entry is as much a drift as a missing one.
        tool_scopes: Tool name -> the scopes a token must hold, merged into
            ``TOOL_SCOPES``. Either a ``frozenset`` covering the whole tool
            or a ``dict`` keyed by the ``action`` argument, the two shapes
            ``TOOL_SCOPES`` already uses. ``frozenset()`` means any
            authenticated token, which is the honest entry when Redmine
            gates the endpoint on project membership rather than on a
            permission. A ``dict`` has to name exactly the actions its
            tool accepts, and the tool's ``action`` parameter has to be a
            ``Literal`` of them: an action the map does not name resolves
            to no requirement at all and the call reaches the tool
            unchecked, so ``main.py`` compares the keys with the Literal
            after the import and refuses a mismatch, or an ``action`` that
            is not a Literal.
        advertised_read_scopes: Redmine permissions to add to
            ``scopes_supported`` while the family is enabled -- in
            :func:`oauth_scopes.advertised_scopes` and, once ``main.py``
            has refreshed the auth provider, in the documents served at
            ``/.well-known/`` that a client actually consents against.
            Needed only for a permission this server does not advertise
            already, which in practice means one the plugin declares
            itself. An ordered sequence, and never a bare ``str``: a
            ``str`` is a sequence of its own characters, so one would
            advertise a scope per letter.
        advertised_write_scopes: The same, and additionally suppressed in
            read-only mode.
        issue_update_keys: Issue attributes ``update_redmine_issue`` may
            write while the family is enabled, in addition to Redmine's
            own. A key it does not know is taken for a custom field
            *label*, and the labels are matched with the non-alphanumerics
            stripped, so an attribute named ``easy_sprint_id`` collides
            with a custom field called "Easy Sprint ID" and the value
            lands in the wrong place. Names here are passed through
            untouched instead, and never reach label matching.
        issue_query_filters: Filter name -> the query parameters that have
            to ride along for the server to honour it, usually ``{}``.
            ``list_redmine_issues`` refuses a filter name it does not know,
            because Redmine drops an unregistered filter and answers 200
            with the collection unnarrowed -- which a caller cannot tell
            apart from a filter that matched everything. Registering here
            widens that list while the family is enabled, without opening
            it. The parameters are merged into the request only when that
            filter is part of the call, and never over a value the caller
            set, so a request that names none of them is unchanged.
    """

    family: str
    enabled: Callable[[], bool]
    tool_kinds: Mapping[str, ToolKind]
    tool_scopes: Mapping[str, ToolScopeEntry]
    advertised_read_scopes: Sequence[str] = ()
    advertised_write_scopes: Sequence[str] = ()
    issue_update_keys: Sequence[str] = ()
    issue_query_filters: Mapping[str, Mapping[str, object]] = MappingProxyType({})


def _reject(where: str, problem: str) -> NoReturn:
    """Raise the one error type a bad registration produces."""
    raise RuntimeError(f"{where} {problem}")


def _check_scope_set(where: str, field: str, value: object) -> None:
    """A required-scope set: a ``frozenset`` of non-empty Redmine permissions."""
    if not isinstance(value, frozenset):
        _reject(
            where,
            f"maps {field} to {value!r}, which is not a frozenset. The scope "
            "middleware intersects this with the token's scopes, so it has "
            "to be the same shape TOOL_SCOPES already uses.",
        )
    for scope in value:
        if not isinstance(scope, str) or not scope:
            _reject(
                where,
                f"has a scope in {field} that is not a non-empty str: "
                f"{scope!r}. A scope is the name of a Redmine permission.",
            )


def _check_scope_sequence(where: str, field: str, value: object) -> None:
    """An advertised-scope list: an ordered sequence, never a bare string."""
    if isinstance(value, str):
        _reject(
            where,
            f"passes a bare str as {field}: {value!r}. A str is a sequence "
            "of its own characters, so this would advertise one scope per "
            f"letter. Pass a one-tuple instead: ({value!r},).",
        )
    if not isinstance(value, Sequence):
        _reject(
            where,
            f"maps {field} to {value!r}, which is not a sequence. It has to "
            "be ordered, because it is appended to scopes_supported and two "
            "restarts of the same deployment must serve the same document.",
        )
    for scope in value:
        if not isinstance(scope, str) or not scope:
            _reject(
                where,
                f"has an entry in {field} that is not a non-empty str: "
                f"{scope!r}. Each one is the name of a Redmine permission.",
            )


def _check_issue_update_keys(where: str, value: object) -> None:
    """Issue attributes to pass through: an ordered sequence of names."""
    if isinstance(value, str):
        _reject(
            where,
            f"passes a bare str as issue_update_keys: {value!r}. A str is a "
            "sequence of its own characters, so this would declare one "
            f"single-letter attribute per letter. Pass a one-tuple: ({value!r},).",
        )
    if not isinstance(value, Sequence):
        _reject(
            where,
            f"maps issue_update_keys to {value!r}, which is not a sequence.",
        )
    for key in value:
        if not isinstance(key, str) or not key:
            _reject(
                where,
                f"has an entry in issue_update_keys that is not a non-empty "
                f"str: {key!r}. Each one is the name of an issue attribute as "
                "the Redmine API spells it.",
            )


def _check_issue_query_filters(where: str, value: object) -> None:
    """Filter names mapped to the query parameters that ride with them."""
    if not isinstance(value, Mapping):
        _reject(
            where,
            f"maps issue_query_filters to {value!r}, which is not a mapping. "
            "It is filter name -> the parameters that have to accompany it, "
            "so a filter needing none maps to an empty dict.",
        )
    for name, params in value.items():
        if not isinstance(name, str) or not name:
            _reject(
                where,
                f"has a key in issue_query_filters that is not a non-empty "
                f"str: {name!r}. The key is the filter name a caller passes "
                "to list_redmine_issues.",
            )
        if not isinstance(params, Mapping):
            _reject(
                where,
                f"maps issue_query_filters[{name!r}] to {params!r}, which is "
                "not a mapping. Pass {} when the filter needs no companion "
                "parameters.",
            )
        for key in params:
            if not isinstance(key, str) or not key:
                _reject(
                    where,
                    f"has a parameter name in issue_query_filters[{name!r}] "
                    f"that is not a non-empty str: {key!r}.",
                )
        problem = _reject_non_scalar_filter_values(dict(params))
        if problem:
            _reject(
                where,
                f"has a value in issue_query_filters[{name!r}] that cannot go "
                f"on the wire as a query parameter. {problem}",
            )


def _validate_spec(spec: ExtensionSpec) -> None:
    """Check every field's shape before the spec can reach a table.

    A dataclass records what it was handed; it does not check it. Each
    field here is read much later and by something else -- the decorator,
    the middleware, the visibility pass, the discovery document -- so a
    wrong shape surfaces far from the line that wrote it, and in the case
    of a bare ``str`` in an advertised list it surfaces as a plausible
    document full of single-letter scopes. Failing here names the field.
    """
    if not isinstance(spec.family, str) or not spec.family:
        _reject(
            "ExtensionSpec",
            f"has family={spec.family!r}, which is not a non-empty str. The "
            "family names the visibility flag and the tag plugin:<family> "
            "that every one of the extension's tools carries.",
        )
    where = f"Extension family '{spec.family}'"

    if not callable(spec.enabled):
        _reject(
            where,
            f"has enabled={spec.enabled!r}, which is not callable. It is "
            "called on every visibility pass and every advertised_scopes() "
            "call, so it reads the flag rather than holding an answer taken "
            "at import.",
        )

    for field, table in (
        ("tool_kinds", spec.tool_kinds),
        ("tool_scopes", spec.tool_scopes),
    ):
        for name in table:
            if not isinstance(name, str) or not name:
                _reject(
                    where,
                    f"has a key in {field} that is not a non-empty str: "
                    f"{name!r}. The key is the tool's name on the MCP "
                    "surface.",
                )

    for name, kind in spec.tool_kinds.items():
        if not isinstance(kind, ToolKind):
            _reject(
                where,
                f"maps tool_kinds[{name!r}] to {kind!r}, which is not a "
                "ToolKind. annotations_for() looks the value up in a table "
                "keyed by the enum and hands back nothing for anything "
                "else, so the tool would ship unannotated.",
            )

    for name, entry in spec.tool_scopes.items():
        if isinstance(entry, dict):
            for action, required in entry.items():
                if not isinstance(action, str) or not action:
                    _reject(
                        where,
                        f"has a key in tool_scopes[{name!r}] that is not a "
                        f"non-empty str: {action!r}. The key is the value of "
                        "the tool's action argument.",
                    )
                _check_scope_set(where, f"tool_scopes[{name!r}][{action!r}]", required)
        else:
            _check_scope_set(where, f"tool_scopes[{name!r}]", entry)

    for field in ("advertised_read_scopes", "advertised_write_scopes"):
        _check_scope_sequence(where, field, getattr(spec, field))

    _check_issue_update_keys(where, spec.issue_update_keys)
    _check_issue_query_filters(where, spec.issue_query_filters)


def _check_issue_seams(spec: ExtensionSpec) -> None:
    """Refuse an issue attribute or filter that is already spoken for.

    The two tables this widens are read per call rather than merged into a
    module constant, so a duplicate would not overwrite anything -- it would
    simply be silent, and silence is what both seams exist to remove. A name
    Redmine already defines usually means the built-in support caught up with
    the extension, which is worth being told about rather than carrying
    forever.

    The imports are local: ``tools.issues`` reaches the whole tool tree, and
    an extension module importing this one during ``main``'s import loop must
    not drag that in a second time through a different path. By then
    ``main.py`` has imported ``tools`` already, so both modules are in
    ``sys.modules`` and the lookup is free.
    """
    from ._custom_fields import _STANDARD_ISSUE_UPDATE_FIELDS
    from ._validation import _RESERVED_QUERY_KEYS
    from .tools.issues import _ISSUE_QUERY_FILTER_NAMES, _ISSUE_REQUEST_PARAM_KEYS

    where = f"Extension family '{spec.family}'"
    update_keys = set(spec.issue_update_keys)
    filters = dict(spec.issue_query_filters)

    taken = sorted(update_keys & _STANDARD_ISSUE_UPDATE_FIELDS)
    if taken:
        _reject(
            where,
            f"declares issue_update_keys Redmine itself defines: "
            f"{', '.join(taken)}. They are passed through already, so drop "
            "them from the spec rather than declaring them twice.",
        )

    taken = sorted(name for name in filters if name in _ISSUE_QUERY_FILTER_NAMES)
    if taken:
        _reject(
            where,
            f"declares issue_query_filters Redmine itself registers: "
            f"{', '.join(taken)}. list_redmine_issues accepts them already.",
        )

    for other in REGISTERED_EXTENSIONS:
        clash = sorted(update_keys & set(other.issue_update_keys))
        if clash:
            _reject(
                where,
                f"declares issue_update_keys already claimed by family "
                f"'{other.family}': {', '.join(clash)}. An attribute has one "
                "meaning on the wire, so two families cannot own it.",
            )
        clash = sorted(set(filters) & set(other.issue_query_filters))
        if clash:
            _reject(
                where,
                f"declares issue_query_filters already claimed by family "
                f"'{other.family}': {', '.join(clash)}. Whichever registered "
                "last would decide the parameters sent with it.",
            )

    for name, params in filters.items():
        reserved = sorted(set(params) & _RESERVED_QUERY_KEYS)
        if reserved:
            _reject(
                where,
                f"has issue_query_filters[{name!r}] setting {', '.join(reserved)}. "
                "Redmine reads those as the query's own filter definition and "
                "discards every filter built from the rest of the request.",
            )
        owned = sorted(set(params) & _ISSUE_REQUEST_PARAM_KEYS)
        if owned:
            _reject(
                where,
                f"has issue_query_filters[{name!r}] setting "
                f"{', '.join(owned)}, which list_redmine_issues owns: they "
                "carry the caller's paging, sorting and includes.",
            )


def register_extension(spec: ExtensionSpec) -> None:
    """Merge one extension's entries into the server's tables.

    Call it from the extension module's top level, before defining the
    tools it describes.

    Every conflict raises ``RuntimeError``, which fails startup rather than
    degrading. A family or tool name that is already taken would otherwise
    replace a built-in entry, and the entry most worth protecting is the
    scope one: it is what stands between a token and an endpoint. A family
    is checked against two sets, because they differ: ``PLUGIN_FLAGS``,
    where a name collision means two families sharing one visibility
    switch, and the built-in keys of ``get_mcp_server_info``'s
    ``plugin_flags``, where it means a client is told the wrong thing. The
    spec's own shape is checked first, by :func:`_validate_spec`, since a
    field of the wrong type is not something the table checks below would
    notice. All checks run before anything is merged, so a rejected
    registration leaves the tables exactly as it found them.
    """
    _validate_spec(spec)
    kinds = dict(spec.tool_kinds)
    scopes = dict(spec.tool_scopes)

    if spec.family in PLUGIN_FLAGS:
        raise RuntimeError(
            f"Extension family '{spec.family}' is already registered. A "
            "family owns the visibility tag plugin:<family>, so two of them "
            "would share one on/off switch. Rename one."
        )

    if spec.family in SERVER_INFO_PLUGIN_FLAGS:
        raise RuntimeError(
            f"Extension family '{spec.family}' is a built-in key of "
            "get_mcp_server_info's plugin_flags. The registered families "
            "are merged into that dict after the built-in flags, so this "
            f"family would replace the '{spec.family}' entry, and a client "
            "reading it to decide whether the built-in support is "
            "available would get the extension's flag instead. Rename the "
            "family."
        )

    only_kinds = sorted(set(kinds) - set(scopes))
    only_scopes = sorted(set(scopes) - set(kinds))
    if only_kinds or only_scopes:
        raise RuntimeError(
            f"Extension family '{spec.family}' declares tool_kinds and "
            "tool_scopes over different tools -- only in tool_kinds: "
            f"{', '.join(only_kinds) or 'none'}; only in tool_scopes: "
            f"{', '.join(only_scopes) or 'none'}. Every tool needs both: "
            "one with no kind reaches clients unannotated, and one with no "
            "scopes is denied by the scope middleware."
        )

    for table_name, table, declared in (
        ("TOOL_KINDS", TOOL_KINDS, kinds),
        ("TOOL_SCOPES", TOOL_SCOPES, scopes),
    ):
        taken = sorted(set(declared) & set(table))
        if taken:
            raise RuntimeError(
                f"Extension family '{spec.family}' declares tool(s) already "
                f"in {table_name}: {', '.join(taken)}. A tool name is global "
                "on the MCP surface, so pick names of your own."
            )

    _check_issue_seams(spec)

    PLUGIN_FLAGS[spec.family] = spec.enabled
    TOOL_KINDS.update(kinds)
    TOOL_SCOPES.update(scopes)
    REGISTERED_EXTENSIONS.append(spec)
