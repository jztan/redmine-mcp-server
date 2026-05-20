"""OAuth scope advertisement for the Redmine MCP server.

This module is the single source of truth for the ``scopes_supported``
list returned by ``/.well-known/oauth-protected-resource`` and
``/.well-known/oauth-authorization-server``.

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

from ._env import _is_read_only_mode

# Redmine permissions used by the read-only MCP tools.
READ_SCOPES: list[str] = [
    "view_project",  # list_redmine_projects, summarize_project_status,
    # get_project_modules
    "search_project",  # search_entire_redmine, search_redmine_issues
    "view_members",  # list_project_members
    "view_issues",  # list_redmine_issues, get_redmine_issue,
    # list_subtasks, get_gantt_chart,
    # list_redmine_queries, list_redmine_versions,
    # summarize_project_status (issue queries)
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
    "manage_documents",  # manage_document(action=create|update|delete)
    "manage_files",  # upload_file, delete_file
    "manage_members",  # manage_project_member
]


def advertised_scopes() -> list[str]:
    """Return the OAuth scopes to advertise in discovery documents.

    Returns ``READ_SCOPES`` only when ``REDMINE_MCP_READ_ONLY`` is truthy
    (per :func:`_is_read_only_mode`); otherwise ``READ_SCOPES +
    WRITE_SCOPES``. Always returns a fresh list so callers cannot mutate
    the source of truth.
    """
    if _is_read_only_mode():
        return list(READ_SCOPES)
    return list(READ_SCOPES) + list(WRITE_SCOPES)
