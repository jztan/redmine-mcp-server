"""MCP ToolAnnotations classification for every registered tool (#204).

This module is the single source of truth for the behavior hints returned
in ``tools/list``. It deliberately mirrors the shape of ``oauth_scopes.py``:
one central per-tool table plus an anti-drift test.

Annotations are advisory client metadata. Per the MCP specification they are
hints only, and "clients MUST consider tool annotations to be untrusted
unless they come from trusted servers". Authorization is still enforced by
the OAuth scope middleware and by ``REDMINE_MCP_READ_ONLY``.

Only non-default values are emitted. The MCP schema defaults are
``readOnlyHint=false``, ``destructiveHint=true``, ``idempotentHint=false``.

Maintenance:
    1. When adding a new MCP tool, add it here with the kind that matches
       what it can actually do.
    2. Classification is by effect on Redmine state. A tool that only reads
       Redmine is READ even if it writes an ephemeral local cache file.
    3. Mixed ``manage_X(action=...)`` tools take the conservative union of
       their actions. Annotations cannot vary by the ``action`` argument.
    4. Never infer the kind from ``TOOL_SCOPES``. An empty scope set can mean
       either a read or a mutating plugin/local operation.
"""

import enum
from typing import Dict, Optional

from mcp.types import ToolAnnotations


class ToolKind(enum.Enum):
    """Behavior class of a tool, independent of deployment configuration."""

    READ = "read"
    WRITE_ADDITIVE = "write_additive"
    WRITE_DESTRUCTIVE = "write_destructive"
    WRITE_DESTRUCTIVE_IDEMPOTENT = "write_destructive_idempotent"


# destructiveHint on a READ tool is formally redundant (the field is
# meaningful only when readOnlyHint == false), but it is emitted anyway to
# guard against a naive client that reads destructiveHint without first
# checking readOnlyHint.
_BY_KIND: Dict[ToolKind, ToolAnnotations] = {
    ToolKind.READ: ToolAnnotations(readOnlyHint=True, destructiveHint=False),
    ToolKind.WRITE_ADDITIVE: ToolAnnotations(readOnlyHint=False, destructiveHint=False),
    ToolKind.WRITE_DESTRUCTIVE: ToolAnnotations(readOnlyHint=False),
    ToolKind.WRITE_DESTRUCTIVE_IDEMPOTENT: ToolAnnotations(
        readOnlyHint=False, idempotentHint=True
    ),
}

TOOL_KINDS: Dict[str, ToolKind] = {
    # --- projects ---
    "list_redmine_projects": ToolKind.READ,
    "get_project_modules": ToolKind.READ,
    "list_project_trackers": ToolKind.READ,
    "summarize_project_status": ToolKind.READ,
    "list_project_members": ToolKind.READ,
    "manage_project_member": ToolKind.WRITE_DESTRUCTIVE,  # add/update/remove
    "list_redmine_versions": ToolKind.READ,
    "manage_redmine_version": ToolKind.WRITE_DESTRUCTIVE,  # create/update/delete
    # --- issues ---
    "list_redmine_issues": ToolKind.READ,
    "get_redmine_issue": ToolKind.READ,
    "list_subtasks": ToolKind.READ,
    "list_redmine_queries": ToolKind.READ,
    "get_gantt_chart": ToolKind.READ,
    "search_redmine_issues": ToolKind.READ,
    "get_private_notes": ToolKind.READ,
    "create_redmine_issue": ToolKind.WRITE_ADDITIVE,
    "copy_issue": ToolKind.WRITE_ADDITIVE,
    # Not idempotent: the notes-only carve-out (oauth_scopes.py) means a
    # repeat call appends a second journal note.
    "update_redmine_issue": ToolKind.WRITE_DESTRUCTIVE,
    "delete_redmine_issue": ToolKind.WRITE_DESTRUCTIVE_IDEMPOTENT,
    "manage_issue_relation": ToolKind.WRITE_DESTRUCTIVE,
    # add/remove are arguably set-semantics and therefore idempotent, but the
    # conservative-union rule for mixed tools applies. A wrong idempotent=true
    # is the more expensive error.
    "manage_issue_watcher": ToolKind.WRITE_DESTRUCTIVE,
    "manage_issue_note": ToolKind.WRITE_DESTRUCTIVE,
    "manage_issue_category": ToolKind.WRITE_DESTRUCTIVE,
    # --- checklists (plugin) ---
    "get_checklist": ToolKind.READ,
    "create_checklist_item": ToolKind.WRITE_ADDITIVE,
    "update_checklist_item": ToolKind.WRITE_DESTRUCTIVE_IDEMPOTENT,
    # --- wiki ---
    "manage_redmine_wiki_page": ToolKind.WRITE_DESTRUCTIVE,
    # --- documents ---
    "manage_document": ToolKind.WRITE_DESTRUCTIVE,
    # --- time tracking ---
    "list_time_entries": ToolKind.READ,
    "list_time_entry_activities": ToolKind.READ,
    "manage_time_entry": ToolKind.WRITE_DESTRUCTIVE,
    "import_time_entries": ToolKind.WRITE_ADDITIVE,
    # --- files and attachments ---
    # READ: does not touch Redmine state. It writes an ephemeral file into
    # ATTACHMENTS_DIR that the background cleanup manager expires.
    "get_redmine_attachment": ToolKind.READ,
    "list_files": ToolKind.READ,
    "upload_file": ToolKind.WRITE_ADDITIVE,
    "delete_file": ToolKind.WRITE_DESTRUCTIVE_IDEMPOTENT,
    # Empty scope set like list_redmine_roles, but it deletes files. This is
    # why annotations cannot be inferred from scope membership.
    "cleanup_attachment_files": ToolKind.WRITE_DESTRUCTIVE_IDEMPOTENT,
    # --- search ---
    "search_entire_redmine": ToolKind.READ,
    # --- enumeration ---
    "list_redmine_roles": ToolKind.READ,
    "list_project_issue_custom_fields": ToolKind.READ,
    "list_redmine_trackers": ToolKind.READ,
    "list_redmine_issue_statuses": ToolKind.READ,
    "list_redmine_issue_priorities": ToolKind.READ,
    "list_redmine_users": ToolKind.READ,
    # --- meta ---
    "get_current_user": ToolKind.READ,
    "get_mcp_server_info": ToolKind.READ,
    # --- RedmineUP plugins ---
    # Empty scope sets, but all four are mixed read/write dispatchers.
    "manage_product": ToolKind.WRITE_DESTRUCTIVE,
    "manage_contact": ToolKind.WRITE_DESTRUCTIVE,
    "manage_deal": ToolKind.WRITE_DESTRUCTIVE,
    # --- MCP Apps ---
    "show_triage_board": ToolKind.READ,
    "get_triage_board_data": ToolKind.READ,
    "show_project_dashboard": ToolKind.READ,
    "get_project_dashboard_data": ToolKind.READ,
}


def annotations_for(tool_name: str) -> Optional[ToolAnnotations]:
    """Return a fresh ToolAnnotations for a tool, or None if unclassified.

    Returns a copy: ToolAnnotations is a mutable pydantic model, so handing
    out the shared per-kind instance would let one caller's mutation leak
    into every other tool of the same kind.
    """
    kind = TOOL_KINDS.get(tool_name)
    return _BY_KIND[kind].model_copy() if kind else None
