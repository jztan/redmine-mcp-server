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
    "view_issue_watchers",  # manage_issue_watcher(action=list)
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
    "add_issue_notes",  # manage_issue_note(action=create)
    "edit_issue_notes",  # manage_issue_note(action=update)
    "set_notes_private",  # manage_issue_note with private flag
    "log_time",  # manage_time_entry(action=create), import_time_entries
    "edit_time_entries",  # manage_time_entry(action=update|delete)
    "manage_versions",  # manage_redmine_version
    "manage_categories",  # manage_issue_category
    "manage_wiki",  # manage_redmine_wiki_page(action=create|update|delete)
    "edit_wiki_pages",  # manage_redmine_wiki_page(action=update)
    "add_documents",  # manage_document(action=create)
    "edit_documents",  # manage_document(action=update)
    "delete_documents",  # manage_document(action=delete)
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
