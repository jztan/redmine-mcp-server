"""OAuth scope advertisement for the Redmine MCP server.

This module is the single source of truth for the ``scopes_supported``
list returned by ``/.well-known/oauth-protected-resource`` and
``/.well-known/oauth-authorization-server/mcp``.

Scope identifiers are Redmine Doorkeeper scope names. In stock Redmine
6.x they match the permission name from ``lib/redmine/access_control.rb``.

Maintenance:
    1. When adding a new MCP tool, identify the underlying python-redmine
       endpoint it calls and the Redmine permission gating that endpoint.
    2. Verify the permission name is registered in
       ``lib/redmine/access_control.rb`` (Redmine 6.x source tree).
    3. Add the permission to ``READ_SCOPES`` if the tool is read-only,
       or ``WRITE_SCOPES`` if the tool mutates state.

Exclusions:
    - ``admin`` is never advertised. Tokens with admin scope bypass
      per-permission checks; default-advertising it would mean every
      consent screen requests full administrative access.
    - Vendor plugin scopes (Easy Redmine, RedmineUP, agile, checklists,
      CRM, products) are excluded. They vary by deployment; advertising
      scopes a Redmine doesn't recognize causes consent errors.
"""

from typing import Dict, Optional, Union

from ._env import _is_agile_enabled, _is_read_only_mode, _is_tags_enabled

# Redmine permissions used by the read-only MCP tools.
READ_SCOPES: list[str] = [
    "view_project",  # list_redmine_projects, summarize_project_status,
    # get_project_modules
    "search_project",  # search_entire_redmine, search_redmine_issues
    "view_members",  # list_project_members
    "view_issues",  # list_redmine_issues, get_redmine_issue,
    # list_subtasks, get_gantt_chart,
    # list_redmine_queries, list_redmine_versions,
    # summarize_project_status (issue queries).
    # Note: list_redmine_versions uses view_issues
    # because Redmine gates GET /projects/.../versions.json
    # on view_issues, not manage_versions (which is
    # a write permission).
    "view_documents",  # manage_document(action=list|get)
    "view_files",  # get_redmine_attachment, list_files
    "view_wiki_pages",  # manage_redmine_wiki_page(action=get|list)
    "view_time_entries",  # list_time_entries, list_time_entry_activities
    "view_private_notes",  # get_private_notes
    "view_issue_watchers",  # get_redmine_issue(include_watchers=True)
]

# Redmine permissions used by the mutation MCP tools.
WRITE_SCOPES: list[str] = [
    "add_issues",  # create_redmine_issue, copy_issue
    "edit_issues",  # update_redmine_issue
    "delete_issues",  # delete_redmine_issue
    "manage_subtasks",  # update_redmine_issue when parent_issue_id changes
    "manage_issue_relations",  # manage_issue_relation
    "add_issue_watchers",  # manage_issue_watcher(action=add)
    "delete_issue_watchers",  # manage_issue_watcher(action=remove)
    "add_issue_notes",  # update_redmine_issue notes-only carve-out
    "edit_issue_notes",  # manage_issue_note(action=edit)
    "set_notes_private",  # manage_issue_note(action=set_private)
    "log_time",  # manage_time_entry(action=create), import_time_entries
    "edit_time_entries",  # manage_time_entry(action=update)
    "manage_versions",  # manage_redmine_version
    "manage_categories",  # manage_issue_category
    "manage_wiki",  # wiki administration; not required by any MCP tool today
    "edit_wiki_pages",  # manage_redmine_wiki_page(action=create|update)
    "rename_wiki_pages",  # manage_redmine_wiki_page(action=rename)
    "delete_wiki_pages",  # manage_redmine_wiki_page(action=delete)
    "add_documents",  # manage_document(action=create)
    "edit_documents",  # manage_document(action=update)
    "delete_documents",  # advertised for parity; manage_document has no
    # delete action yet
    "manage_files",  # upload_file, delete_file
    "manage_members",  # manage_project_member
]

# RedmineUP Agile plugin permissions, advertised only when the agile
# feature is explicitly enabled (see below). Kept out of READ_SCOPES so
# a non-agile deployment never advertises a scope Redmine can't resolve.
AGILE_READ_SCOPES: list[str] = [
    "view_agile_queries",  # get_redmine_issue agile fetch:
    # AgileBoardsController#agile_data (GET
    # /issues/{id}/agile_data.json)
]

# AlphaNodes additional_tags plugin permissions, advertised only when the
# tags feature is explicitly enabled (see below). Kept out of READ_SCOPES so
# a deployment without the plugin never advertises a scope Redmine can't
# resolve.
TAGS_READ_SCOPES: list[str] = [
    "view_issue_tags",  # get_redmine_issue tags array: the plugin injects
    # ``tags`` into GET /issues/{id}.json only when the
    # caller holds this permission.
]

# AlphaNodes additional_tags write permissions, advertised only when the tags
# feature is enabled AND the server is not read-only. create_redmine_issue /
# update_redmine_issue accept a ``tag_list``; the plugin's safe_attributes gate
# requires create_issue_tags (may add new tags) or edit_issue_tags (existing
# tags only), so both are advertised to cover either grant.
TAGS_WRITE_SCOPES: list[str] = [
    "create_issue_tags",
    "edit_issue_tags",
]


def advertised_scopes() -> list[str]:
    """Return the OAuth scopes to advertise in discovery documents.

    Returns ``READ_SCOPES`` only when ``REDMINE_MCP_READ_ONLY`` is truthy
    (per :func:`_is_read_only_mode`); otherwise ``READ_SCOPES +
    WRITE_SCOPES``. When ``REDMINE_AGILE_ENABLED`` is truthy (per
    :func:`_is_agile_enabled`), the read-only :data:`AGILE_READ_SCOPES`
    are appended in both modes so the OAuth token can reach the agile
    endpoints. Gating on the same flag that gates the agile tools means a
    non-agile Redmine never sees an unrecognized plugin scope. The same
    applies to :data:`TAGS_READ_SCOPES` under ``REDMINE_TAGS_ENABLED``;
    :data:`TAGS_WRITE_SCOPES` are additionally appended unless the server
    is read-only, since they gate ``tag_list`` writes. Always returns a
    fresh list so callers cannot mutate the source of truth.
    """
    if _is_read_only_mode():
        scopes = list(READ_SCOPES)
    else:
        scopes = list(READ_SCOPES) + list(WRITE_SCOPES)
    if _is_agile_enabled():
        scopes += list(AGILE_READ_SCOPES)
    if _is_tags_enabled():
        scopes += list(TAGS_READ_SCOPES)
        if not _is_read_only_mode():
            scopes += list(TAGS_WRITE_SCOPES)
    return scopes


# ---------------------------------------------------------------------------
# Per-tool scope enforcement map (#185).
#
# Consumed by ScopeEnforcementMiddleware. Values are either:
#   - frozenset[str]: required scopes regardless of arguments, or
#   - dict[action, frozenset[str]]: per-action requirements for
#     manage_X(action=...) tools; unknown actions pass through so the
#     tool's own invalid-action error surfaces.
#
# Semantics: token must hold ALL scopes in the matching entry.
# frozenset() means any authenticated token may call the tool (no
# Redmine permission gates it, or Redmine itself requires admin and
# admin tokens bypass this map anyway).
#
# Boundary: this map gates each tool's base permission only. Argument-
# conditional permissions (manage_subtasks when parent_issue_id changes,
# set_notes_private via update flags, create_issue_tags/edit_issue_tags
# for tag_list, plugin permissions for RedmineUP products/contacts/
# checklists) remain enforced by Redmine's own role and scope checks.
#
# Anti-drift: tests/test_scope_enforcement.py asserts every registered
# tool is mapped and every enforced scope is advertised.
# ---------------------------------------------------------------------------

ToolScopeEntry = Union[frozenset, Dict[str, frozenset]]

TOOL_SCOPES: Dict[str, ToolScopeEntry] = {
    # --- projects ---
    "list_redmine_projects": frozenset({"view_project"}),
    "get_project_modules": frozenset({"view_project"}),
    "list_project_trackers": frozenset({"view_project"}),
    "summarize_project_status": frozenset({"view_project", "view_issues"}),
    "list_project_members": frozenset({"view_members"}),
    # GET /roles.json needs authentication only.
    "list_redmine_roles": frozenset(),
    # GET /custom_fields.json is admin-gated by Redmine itself.
    "list_project_issue_custom_fields": frozenset(),
    "manage_project_member": frozenset({"manage_members"}),
    # Redmine gates GET /projects/.../versions.json on view_issues.
    "list_redmine_versions": frozenset({"view_issues"}),
    "manage_redmine_version": frozenset({"manage_versions"}),
    # --- issues ---
    "list_redmine_issues": frozenset({"view_issues"}),
    "get_redmine_issue": frozenset({"view_issues"}),
    "list_subtasks": frozenset({"view_issues"}),
    "list_redmine_queries": frozenset({"view_issues"}),
    "get_gantt_chart": frozenset({"view_issues"}),
    "search_redmine_issues": frozenset({"search_project"}),
    "create_redmine_issue": frozenset({"add_issues"}),
    "copy_issue": frozenset({"add_issues"}),
    "update_redmine_issue": frozenset({"edit_issues"}),
    "delete_redmine_issue": frozenset({"delete_issues"}),
    "get_private_notes": frozenset({"view_issues", "view_private_notes"}),
    "manage_issue_relation": {
        "list": frozenset({"view_issues"}),
        "create": frozenset({"manage_issue_relations"}),
        "delete": frozenset({"manage_issue_relations"}),
    },
    "manage_issue_watcher": {
        "add": frozenset({"add_issue_watchers"}),
        "remove": frozenset({"delete_issue_watchers"}),
    },
    "manage_issue_note": {
        "edit": frozenset({"edit_issue_notes"}),
        "set_private": frozenset({"set_notes_private"}),
    },
    "manage_issue_category": {
        "list": frozenset({"view_issues"}),
        "create": frozenset({"manage_categories"}),
        "update": frozenset({"manage_categories"}),
        "delete": frozenset({"manage_categories"}),
    },
    # --- search ---
    "search_entire_redmine": frozenset({"search_project"}),
    # --- enumerations (authentication only, no Redmine permission) ---
    "list_redmine_trackers": frozenset(),
    "list_redmine_issue_statuses": frozenset(),
    "list_redmine_issue_priorities": frozenset(),
    # GET /users.json is admin-gated by Redmine itself.
    "list_redmine_users": frozenset(),
    "get_current_user": frozenset(),
    # --- meta ---
    "get_mcp_server_info": frozenset(),
    # --- files / attachments ---
    "get_redmine_attachment": frozenset({"view_files"}),
    "list_files": frozenset({"view_files"}),
    "upload_file": frozenset({"manage_files"}),
    "delete_file": frozenset({"manage_files"}),
    # Local attachment-store maintenance; no Redmine call. Registered
    # only when REDMINE_MCP_EXPOSE_ADMIN_TOOLS is truthy.
    "cleanup_attachment_files": frozenset(),
    # --- documents ---
    "manage_document": {
        "list": frozenset({"view_documents"}),
        "get": frozenset({"view_documents"}),
        "create": frozenset({"add_documents"}),
        "update": frozenset({"edit_documents"}),
    },
    # --- wiki ---
    "manage_redmine_wiki_page": {
        "list": frozenset({"view_wiki_pages"}),
        "get": frozenset({"view_wiki_pages"}),
        "create": frozenset({"edit_wiki_pages"}),
        "update": frozenset({"edit_wiki_pages"}),
        "rename": frozenset({"rename_wiki_pages"}),
        "delete": frozenset({"delete_wiki_pages"}),
    },
    # --- time tracking ---
    "list_time_entries": frozenset({"view_time_entries"}),
    "list_time_entry_activities": frozenset({"view_time_entries"}),
    "import_time_entries": frozenset({"log_time"}),
    "manage_time_entry": {
        "create": frozenset({"log_time"}),
        "update": frozenset({"edit_time_entries"}),
    },
    # --- checklists (RedmineUP plugin; vendor scopes are not advertised,
    # so gate on the host-issue permissions; the plugin's own
    # view_checklists/edit_checklists checks remain with Redmine) ---
    "get_checklist": frozenset({"view_issues"}),
    "create_checklist_item": frozenset({"edit_issues"}),
    "update_checklist_item": frozenset({"edit_issues"}),
    # --- products / CRM (RedmineUP plugins; vendor scopes are not
    # advertised and cannot be required; Redmine enforces its own
    # plugin permissions) ---
    "manage_product": frozenset(),
    "manage_contact": frozenset(),
    # --- MCP Apps (read-only issue queries) ---
    "show_triage_board": frozenset({"view_issues"}),
    "get_triage_board_data": frozenset({"view_issues"}),
    "show_project_dashboard": frozenset({"view_issues"}),
    "get_project_dashboard_data": frozenset({"view_issues"}),
}


def scopes_for_action(
    entry: ToolScopeEntry, arguments: Optional[dict]
) -> Optional[frozenset]:
    """Resolve the scope requirement for one call.

    Flat entries apply regardless of arguments. Dict entries key on the
    call's ``action`` argument; an unknown or missing action returns
    ``None`` (pass through) so the tool's own invalid-action or
    missing-argument error surfaces instead of a scope denial.
    """
    if isinstance(entry, dict):
        action = (arguments or {}).get("action")
        if not isinstance(action, str):
            # Non-string actions cannot match a map key; pass through so
            # argument validation rejects them cleanly.
            return None
        return entry.get(action)
    return entry


def tool_visible(entry: ToolScopeEntry, token_scopes: set) -> bool:
    """True when a token can invoke the tool (any action, for dict entries)."""
    if isinstance(entry, dict):
        return any(req <= token_scopes for req in entry.values())
    return entry <= token_scopes


# update_redmine_issue carve-out (#185 review): a notes-only update is
# Redmine's "add a comment" operation. Redmine gates it on
# add_issue_notes (Issue#notes_addable?), not edit_issues, so a
# commenter token must pass and an edit-only token must be denied,
# mirroring Redmine's own check. Attaching uploads or touching any
# other field remains a real edit.
_NOTES_ONLY_FIELDS = frozenset({"notes", "private_notes"})
_NOTES_ONLY_SCOPES = frozenset({"add_issue_notes"})


def _is_notes_only_update(arguments: Optional[dict]) -> bool:
    args = arguments or {}
    fields = args.get("fields")
    if not isinstance(fields, dict) or not fields:
        return False
    if args.get("uploads"):
        return False
    return set(fields) <= _NOTES_ONLY_FIELDS


def required_scopes_for_call(
    tool_name: str, entry: ToolScopeEntry, arguments: Optional[dict]
) -> Optional[frozenset]:
    """Scope requirement for one call: per-tool carve-outs, then the map."""
    if tool_name == "update_redmine_issue" and _is_notes_only_update(arguments):
        return _NOTES_ONLY_SCOPES
    return scopes_for_action(entry, arguments)


def tool_visible_for(tool_name: str, entry: ToolScopeEntry, token_scopes: set) -> bool:
    """Visibility for tools/list, including per-tool carve-outs."""
    if tool_name == "update_redmine_issue":
        return tool_visible(entry, token_scopes) or (_NOTES_ONLY_SCOPES <= token_scopes)
    return tool_visible(entry, token_scopes)
