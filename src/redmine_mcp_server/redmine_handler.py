"""
MCP tools for Redmine integration.

This module provides Model Context Protocol (MCP) tools for interacting with Redmine
project management systems. It includes functionality to retrieve issue details,
list projects, and manage Redmine data through MCP-compatible interfaces.

The module handles authentication via either API key or username/password credentials,
and provides comprehensive error handling for network and authentication issues.

Tools provided:
    - get_redmine_issue: Retrieve detailed information about a specific issue
    - list_redmine_projects: Get a list of all accessible Redmine projects

Environment Variables Required:
    - REDMINE_URL: Base URL of the Redmine instance
    - REDMINE_API_KEY: API key for authentication (preferred), OR
    - REDMINE_USERNAME + REDMINE_PASSWORD: Username/password authentication

Dependencies:
    - redminelib: Python library for Redmine API interactions
    - python-dotenv: Environment variable management
    - fastmcp: FastMCP server implementation
"""

import ipaddress  # noqa: F401  -- re-exported so tests can patch via redmine_handler
import socket  # noqa: F401  -- re-exported so tests can patch via redmine_handler
import asyncio  # noqa: F401  -- re-exported so tests can patch via redmine_handler
import json  # noqa: F401  -- re-exported for back-compat during refactor
import logging  # noqa: F401  -- re-exported for back-compat during refactor
from datetime import (  # noqa: F401  -- re-exported for back-compat during refactor
    datetime,
    timedelta,
)
from typing import (  # noqa: F401  -- re-exported for back-compat during refactor
    Any,
    Dict,
    List,
    Optional,
    Set,
    Union,
)
from urllib.parse import unquote, urlparse  # noqa: F401  -- re-exported

import httpx  # noqa: F401  -- re-exported so tests can patch via redmine_handler
from redminelib import Redmine  # noqa: F401  -- re-exported for test patching
from redminelib.exceptions import (  # noqa: F401  -- re-exported for back-compat
    ResourceNotFoundError,
    VersionMismatchError,
    ValidationError,
)
from ._validation import (  # noqa: F401  -- re-exported for back-compat during refactor
    _PROJECT_ID_PATTERN,
    _is_positive_int,
    _is_valid_project_id,
    _validate_hours,
)
from ._serialization import (  # noqa: F401  re-exported for back-compat
    _DEFAULT_LIST_RESULT_CAP,
    _REDMINE_API_PAGE_CAP,
    _coerce_json_safe,
    _iter_capped,
    _named_ref,
    _safe_isoformat,
    wrap_insecure_content,
)
from ._env import (  # noqa: F401  -- re-exported for back-compat during refactor
    _is_agile_enabled,
    _is_checklists_enabled,
    _is_crm_enabled,
    _is_products_enabled,
    _is_read_only_mode,
    _is_true_env,
)
from ._errors import (  # noqa: F401  -- re-exported for back-compat during refactor
    _READ_ONLY_ERROR,
    _SECRET_SCRUB_PATTERNS,
    _handle_redmine_error,
    _scrub_error_message,
)
from ._client import (  # noqa: F401  -- re-exported for back-compat during refactor
    REDMINE_API_KEY,
    REDMINE_AUTH_MODE,
    REDMINE_PASSWORD,
    REDMINE_SSL_CERT,
    REDMINE_SSL_CLIENT_CERT,
    REDMINE_SSL_VERIFY,
    REDMINE_URL,
    REDMINE_USERNAME,
    _build_legacy_client,
    _build_requests_config,
    _env_loaded,
    _env_paths,
    _get_redmine_client,
    _legacy_client,
    logger,
    redmine,
)
from ._cleanup import (  # noqa: F401  -- re-exported for back-compat during refactor
    CleanupTaskManager,
    _ensure_cleanup_started,
    cleanup_manager,
)
from ._ssrf import (  # noqa: F401  -- re-exported for back-compat during refactor
    _CONTROL_CHAR_RE,
    _DOWNLOAD_TIMEOUT,
    _FILE_DOWNLOAD_MAX_REDIRECTS,
    _MAX_FILENAME_LEN,
    _allow_private_fetch_urls,
    _download_file_url,
    _extract_content_disposition_filename,
    _is_hostname_safe_for_fetch,
    _is_ip_publicly_routable,
    _make_pinned_client,
    _sanitize_filename,
    _validate_fetch_url,
)
from ._custom_fields import (  # noqa: F401  -- re-exported for back-compat
    _DEFAULT_REQUIRED_CUSTOM_FIELD_VALUES,
    _STANDARD_ISSUE_UPDATE_FIELDS,
    _augment_fields_with_required_custom_fields,
    _coerce_update_custom_fields,
    _extract_missing_required_field_names,
    _extract_possible_values,
    _is_allowed_custom_field_value,
    _is_missing_custom_field_value,
    _is_required_custom_field_autofill_enabled,
    _is_standard_issue_update_key,
    _load_required_custom_field_defaults,
    _map_named_custom_fields_for_update,
    _normalize_field_label,
    _parse_create_issue_fields,
    _parse_optional_object_payload,
    _resolve_project_issue_custom_fields,
    _resolve_required_custom_field_value,
    _upsert_custom_field_entry,
)

if not REDMINE_URL:
    logger.warning(
        "REDMINE_URL not set. "
        "Please create a .env file in your working directory with REDMINE_URL defined."
    )
elif REDMINE_AUTH_MODE != "oauth" and not (
    REDMINE_API_KEY or (REDMINE_USERNAME and REDMINE_PASSWORD)
):
    logger.warning(
        "No Redmine authentication configured. "
        "Please set REDMINE_API_KEY or REDMINE_USERNAME/REDMINE_PASSWORD "
        "in your .env file, or set REDMINE_AUTH_MODE=oauth."
    )


# Initialize FastMCP server
# Re-exported for back-compat during refactor
from .server import mcp  # noqa: E402,F401

# Re-exported for back-compat during refactor
from ._http_routes import (  # noqa: E402,F401
    cleanup_status,
    health_check,
    serve_attachment,
)

# Register HTTP routes on the FastMCP instance. Functions live in _http_routes
# but the @mcp.custom_route decorator must be applied here where `mcp` exists.
mcp.custom_route("/health", methods=["GET"])(health_check)
mcp.custom_route("/files/{file_id}", methods=["GET"])(serve_attachment)
mcp.custom_route("/cleanup/status", methods=["GET"])(cleanup_status)


# ---------------------------------------------------------------------------
# Issue tools: get/list/search/create/update/copy issues, plus subtasks,
# relations, watchers, notes, and categories.
#
# Tool definitions live in ``tools/issues.py``; re-exported below for
# back-compat with existing test imports.
# ---------------------------------------------------------------------------
# noqa comments below: re-exported for back-compat during refactor
from .tools.issues import (  # noqa: E402,F401
    _VALID_ISSUE_RELATION_TYPES,
    _apply_agile_story_points,
    _attachments_to_list,
    _custom_fields_to_list,
    _fetch_agile_data,
    _issue_category_to_dict,
    _issue_relation_to_dict,
    _issue_to_dict,
    _issue_to_dict_selective,
    _journal_to_dict,
    _journals_to_list,
    copy_issue,
    create_redmine_issue,
    get_private_notes,
    get_redmine_issue,
    list_redmine_issues,
    list_subtasks,
    manage_issue_category,
    manage_issue_note,
    manage_issue_relation,
    manage_issue_watcher,
    search_redmine_issues,
    update_redmine_issue,
)

# ---------------------------------------------------------------------------
# Project management tools: list/manage projects, versions, memberships,
# roles, modules, status summaries.
#
# Tool definitions live in ``tools/projects.py``; re-exported below for
# back-compat with existing test imports.
# ---------------------------------------------------------------------------
# noqa comments below: re-exported for back-compat during refactor
from .tools.projects import (  # noqa: E402,F401
    _analyze_issues,
    _custom_field_applies_to_tracker,
    _custom_field_to_dict,
    _custom_field_trackers_to_list,
    _membership_to_dict,
    _version_to_dict,
    get_project_modules,
    list_project_issue_custom_fields,
    list_project_members,
    list_redmine_projects,
    list_redmine_roles,
    list_redmine_versions,
    manage_project_member,
    manage_redmine_version,
    summarize_project_status,
)

# ---------------------------------------------------------------------------
# Time tracking tools: list, manage, activities, bulk import
#
# Tool definitions live in ``tools/time_tracking.py``; re-exported below for
# back-compat with existing test imports.
# ---------------------------------------------------------------------------
# noqa comments below: re-exported for back-compat during refactor
from .tools.time_tracking import (  # noqa: E402,F401
    _IMPORT_TIME_ENTRIES_MAX_BATCH,
    _time_entry_to_dict,
    import_time_entries,
    list_time_entries,
    list_time_entry_activities,
    manage_time_entry,
)

# ---------------------------------------------------------------------------
# Discovery / enumeration tools
#
# Tool definitions live in ``tools/enumeration.py``; re-exported below for
# back-compat with existing test imports.
# ---------------------------------------------------------------------------
# noqa comments below: re-exported for back-compat during refactor
from .tools.enumeration import (  # noqa: E402,F401
    get_current_user,
    list_redmine_issue_priorities,
    list_redmine_issue_statuses,
    list_redmine_queries,
    list_redmine_trackers,
    list_redmine_users,
)

# ---------------------------------------------------------------------------
# Products tools (requires RedmineUP Products plugin)
#
# Tool definition lives in ``tools/products.py``; re-exported below for
# back-compat with existing test imports.
# ---------------------------------------------------------------------------
# noqa comments below: re-exported for back-compat during refactor
from .tools.products import (  # noqa: E402,F401
    _PRODUCT_WRITABLE_FIELDS,
    _PRODUCTS_DISABLED_ERROR,
    _product_to_dict,
    manage_product,
)

# ---------------------------------------------------------------------------
# Gantt tool (composite — uses core REST API only, no plugin required)
#
# Tool definition lives in ``tools/gantt.py``; re-exported below for
# back-compat with existing test imports.
# ---------------------------------------------------------------------------
# noqa comments below: re-exported for back-compat during refactor
from .tools.gantt import (  # noqa: E402,F401
    _gantt_issue_to_dict,
    _gantt_version_to_dict,
    get_gantt_chart,
)

# ---------------------------------------------------------------------------
# Checklists tools (requires RedmineUP Checklists plugin)
#
# Tool definitions live in ``tools/checklists.py``; re-exported below for
# back-compat with existing test imports.
# ---------------------------------------------------------------------------
# noqa comments below: re-exported for back-compat during refactor
from .tools.checklists import (  # noqa: E402,F401
    _fetch_checklist_items,
    _update_checklist_item_api,
    get_checklist,
    update_checklist_item,
)

# ---------------------------------------------------------------------------
# Contacts tool (requires RedmineUP CRM plugin)
#
# Tool definition lives in ``tools/contacts.py``; re-exported below for
# back-compat with existing test imports.
# ---------------------------------------------------------------------------
# noqa comments below: re-exported for back-compat during refactor
from .tools.contacts import (  # noqa: E402,F401
    _CONTACT_WRITABLE_FIELDS,
    _CRM_DISABLED_ERROR,
    _contact_to_dict,
    manage_contact,
)

# noqa comments below: re-exported for back-compat during refactor
from .tools.files import (  # noqa: E402,F401
    _FILE_UPLOAD_MAX_SIZE_BYTES,
    _file_to_dict,
    cleanup_attachment_files,
    delete_file,
    get_redmine_attachment_download_url,
    list_files,
    upload_file,
)

# noqa comments below: re-exported for back-compat during refactor
from .tools.search import (  # noqa: E402,F401
    _resource_to_dict,
    search_entire_redmine,
)

# noqa comments below: re-exported for back-compat during refactor
from .tools.wiki import (  # noqa: E402,F401
    _wiki_page_to_dict,
    manage_redmine_wiki_page,
)

if __name__ == "__main__":
    # Initialize and run the server
    mcp.run(transport="stdio")
