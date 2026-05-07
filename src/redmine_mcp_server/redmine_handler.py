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

import base64
import binascii
import io
import ipaddress
import os
import socket
import uuid
import json
import re
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Union
from urllib.parse import unquote, urlparse

import httpx
from redminelib import Redmine  # noqa: F401  -- re-exported for test patching
from redminelib.exceptions import (
    ResourceNotFoundError,
    VersionMismatchError,
    ValidationError,
)
from fastmcp import FastMCP
from .file_manager import AttachmentFileManager
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
mcp = FastMCP("redmine_mcp_tools")


@mcp.custom_route("/health", methods=["GET"])
async def health_check(request):
    """Health check endpoint for container orchestration and monitoring."""
    from starlette.responses import JSONResponse

    # Initialize cleanup task on first health check (lazy initialization)
    await _ensure_cleanup_started()

    return JSONResponse(
        {
            "status": "ok",
            "service": "redmine_mcp_tools",
            "auth_mode": REDMINE_AUTH_MODE,
        }
    )


@mcp.custom_route("/files/{file_id}", methods=["GET"])
async def serve_attachment(request):
    """Serve downloaded attachment files via HTTP."""
    from starlette.responses import FileResponse
    from starlette.exceptions import HTTPException

    file_id = request.path_params["file_id"]

    # Security: Validate file_id format (proper UUID validation)
    try:
        uuid.UUID(file_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid file ID")

    # Load file metadata from UUID directory
    attachments_dir = Path(os.getenv("ATTACHMENTS_DIR", "./attachments"))
    uuid_dir = attachments_dir / file_id
    metadata_file = uuid_dir / "metadata.json"

    if not metadata_file.exists():
        raise HTTPException(status_code=404, detail="File not found or expired")

    try:
        # Read metadata
        with open(metadata_file, "r") as f:
            metadata = json.load(f)

        # Check expiry with proper timezone-aware datetime comparison
        expires_at_str = metadata.get("expires_at", "")
        if expires_at_str:
            expires_at = datetime.fromisoformat(expires_at_str.replace("Z", "+00:00"))
            if datetime.now(timezone.utc) > expires_at:
                # Clean up expired files
                try:
                    file_path = Path(metadata["file_path"])
                    if file_path.exists():
                        file_path.unlink()
                    metadata_file.unlink()
                    # Remove UUID directory if empty
                    if uuid_dir.exists() and not any(uuid_dir.iterdir()):
                        uuid_dir.rmdir()
                except OSError:
                    pass  # Log but don't fail if cleanup fails
                raise HTTPException(status_code=404, detail="File expired")

        # Validate file path security (must be within UUID directory)
        file_path = Path(metadata["file_path"]).resolve()
        uuid_dir_resolved = uuid_dir.resolve()
        try:
            file_path.relative_to(uuid_dir_resolved)
        except ValueError:
            raise HTTPException(status_code=403, detail="Access denied")

        # Serve file
        if not file_path.exists():
            raise HTTPException(status_code=404, detail="File not found")

        return FileResponse(
            path=str(file_path),
            filename=metadata["original_filename"],
            media_type=metadata.get("content_type", "application/octet-stream"),
        )

    except json.JSONDecodeError:
        raise HTTPException(status_code=500, detail="Corrupted metadata")
    except ValueError:
        # Invalid datetime format
        raise HTTPException(status_code=500, detail="Invalid metadata format")


@mcp.custom_route("/cleanup/status", methods=["GET"])
async def cleanup_status(request):
    """Get cleanup task status and statistics."""
    from starlette.responses import JSONResponse

    return JSONResponse(cleanup_manager.get_status())


_DEFAULT_REQUIRED_CUSTOM_FIELD_VALUES: Dict[str, Any] = {}

_STANDARD_ISSUE_UPDATE_FIELDS: Set[str] = {
    "subject",
    "description",
    "notes",
    "private_notes",
    "tracker_id",
    "status_id",
    "priority_id",
    "category_id",
    "fixed_version_id",
    "assigned_to_id",
    "parent_issue_id",
    "start_date",
    "due_date",
    "done_ratio",
    "estimated_hours",
    "is_private",
    "watcher_user_ids",
    "uploads",
    "deleted_attachment_ids",
    "custom_fields",
    "status_name",
}


def _fetch_agile_data(issue_id: int) -> Dict[str, Any]:
    """Fetch agile fields for an issue from the RedmineUP Agile endpoint.

    Returns a dict with story_points, agile_sprint_id, and agile_position.
    Raises on any HTTP error (caller is responsible for catching).
    """
    client = _get_redmine_client()
    url = f"{REDMINE_URL}/issues/{issue_id}/agile_data.json"
    payload = client.engine.request("get", url)
    agile_data = payload.get("agile_data", {}) or {}
    return {
        "story_points": agile_data.get("story_points"),
        "agile_sprint_id": agile_data.get("agile_sprint_id"),
        "agile_position": agile_data.get("position"),
    }


def _apply_agile_story_points(issue_id: int, story_points) -> None:
    """Write story_points for an issue via the RedmineUP Agile endpoint.

    Raises on any HTTP error (caller is responsible for catching).
    """
    client = _get_redmine_client()
    url = f"{REDMINE_URL}/issues/{issue_id}.json"
    payload = json.dumps(
        {"issue": {"agile_data_attributes": {"story_points": story_points}}}
    )
    client.engine.request(
        "put",
        url,
        headers={"Content-Type": "application/json"},
        data=payload,
    )


# ---------------------------------------------------------------------------
# Checklist helpers (requires RedmineUP Checklists plugin)
# ---------------------------------------------------------------------------


def _fetch_checklist_items(issue_id: int) -> List[Dict[str, Any]]:
    """Fetch checklist items for an issue from the RedmineUP Checklists endpoint.

    Returns a list of checklist item dicts.
    Raises on any HTTP error (caller is responsible for catching).
    """
    client = _get_redmine_client()
    url = f"{REDMINE_URL}/issues/{issue_id}/checklists.json"
    payload = client.engine.request("get", url)
    raw_items = payload if isinstance(payload, list) else payload.get("checklists", [])
    items = []
    for item in raw_items:
        items.append(
            {
                "id": item.get("id"),
                "subject": wrap_insecure_content(item.get("subject", "")),
                "is_done": item.get("is_done", False),
                "position": item.get("position"),
                "created_at": str(item.get("created_at") or ""),
                "updated_at": str(item.get("updated_at") or ""),
            }
        )
    return items


def _update_checklist_item_api(checklist_item_id: int, updates: Dict[str, Any]) -> Any:
    """Update a checklist item via the RedmineUP Checklists endpoint.

    Raises on any HTTP error (caller is responsible for catching).
    """
    client = _get_redmine_client()
    url = f"{REDMINE_URL}/checklists/{checklist_item_id}.json"
    payload = json.dumps({"checklist": updates})
    return client.engine.request(
        "put",
        url,
        headers={"Content-Type": "application/json"},
        data=payload,
    )


# ---------------------------------------------------------------------------
# Products helpers (requires RedmineUP Products plugin)
# ---------------------------------------------------------------------------


_PRODUCTS_DISABLED_ERROR = {
    "error": (
        "Products support is disabled. "
        "Set REDMINE_PRODUCTS_ENABLED=true to enable it. "
        "Requires the RedmineUP Products plugin."
    )
}

_PRODUCT_WRITABLE_FIELDS = {
    "name",
    "description",
    "price",
    "currency",
    "status_id",
    "code",
    "project_id",
    "category_id",
    "tag_list",
    "custom_fields",
}


def _product_to_dict(product: Dict[str, Any]) -> Dict[str, Any]:
    """Serialize a RedmineUP Products API response into a stable dict.

    Display-name fields (``name``, ``description``, ``code``) are wrapped in
    ``<insecure-content>`` boundary tags because they are user-controlled.
    """
    if not isinstance(product, dict):
        return {}
    raw_project = product.get("project")
    project = raw_project if isinstance(raw_project, dict) else {}
    raw_category = product.get("category")
    category = raw_category if isinstance(raw_category, dict) else {}
    return {
        "id": product.get("id"),
        "name": wrap_insecure_content(product.get("name", "")),
        "description": wrap_insecure_content(product.get("description", "")),
        "code": wrap_insecure_content(product.get("code", "")),
        "price": product.get("price"),
        "currency": product.get("currency"),
        "status_id": product.get("status_id"),
        "project": (
            {
                "id": project.get("id"),
                "name": wrap_insecure_content(project.get("name", "")),
            }
            if project
            else None
        ),
        "category": (
            {
                "id": category.get("id"),
                "name": wrap_insecure_content(category.get("name", "")),
            }
            if category
            else None
        ),
        "tags": product.get("tags") or [],
        "created_on": _safe_isoformat(product.get("created_on")),
        "updated_on": _safe_isoformat(product.get("updated_on")),
    }


# ---------------------------------------------------------------------------
# CRM (Contacts) helpers (requires RedmineUP CRM plugin)
# ---------------------------------------------------------------------------


_CRM_DISABLED_ERROR = {
    "error": (
        "Contacts (CRM) support is disabled. "
        "Set REDMINE_CRM_ENABLED=true to enable it. "
        "Requires the RedmineUP CRM plugin."
    )
}

_CONTACT_WRITABLE_FIELDS = {
    "first_name",
    "last_name",
    "middle_name",
    "company",
    "job_title",
    "phone",
    "email",
    "website",
    "skype_name",
    "birthday",
    "background",
    "address_attributes",
    "tag_list",
    "is_company",
    "assigned_to_id",
    "custom_fields",
    "visibility",
    "project_id",
}


def _contact_to_dict(contact: Dict[str, Any]) -> Dict[str, Any]:
    """Serialize a RedmineUP CRM API response into a stable dict.

    User-controlled fields are wrapped in ``<insecure-content>`` boundary
    tags. Contact PII (email, phone, address) is returned as-is to the
    caller but never logged via logger.* calls in this module.
    """
    if not isinstance(contact, dict):
        return {}
    raw_assigned = contact.get("assigned_to")
    assigned = raw_assigned if isinstance(raw_assigned, dict) else {}
    raw_address = contact.get("address")
    address = raw_address if isinstance(raw_address, dict) else {}
    return {
        "id": contact.get("id"),
        "first_name": wrap_insecure_content(contact.get("first_name", "")),
        "last_name": wrap_insecure_content(contact.get("last_name", "")),
        "middle_name": wrap_insecure_content(contact.get("middle_name", "")),
        "company": wrap_insecure_content(contact.get("company", "")),
        "job_title": wrap_insecure_content(contact.get("job_title", "")),
        "phone": contact.get("phone"),
        "email": contact.get("email"),
        "website": contact.get("website"),
        "skype_name": contact.get("skype_name"),
        "birthday": contact.get("birthday"),
        "background": wrap_insecure_content(contact.get("background", "")),
        "address": (
            {
                "street1": address.get("street1"),
                "street2": address.get("street2"),
                "city": address.get("city"),
                "region": address.get("region"),
                "country": address.get("country"),
                "postcode": address.get("postcode"),
            }
            if address
            else None
        ),
        "is_company": contact.get("is_company", False),
        "tags": contact.get("tags") or [],
        "visibility": contact.get("visibility"),
        "assigned_to": (
            {
                "id": assigned.get("id"),
                "name": wrap_insecure_content(assigned.get("name", "")),
            }
            if assigned
            else None
        ),
        "created_on": _safe_isoformat(contact.get("created_on")),
        "updated_on": _safe_isoformat(contact.get("updated_on")),
    }


# ---------------------------------------------------------------------------
# Module-level limits and timeouts.
# ---------------------------------------------------------------------------

# Cap a single base64 file upload at ~50 MiB decoded to protect the server
# from resource exhaustion. Larger files should be uploaded via a different
# mechanism (e.g., writing to disk first and passing a path).
_FILE_UPLOAD_MAX_SIZE_BYTES = 50 * 1024 * 1024

# Maximum filename length — typical POSIX limit for a single path component.
_MAX_FILENAME_LEN = 255

# Maximum entries in a single `import_time_entries` call. Redmine has no
# native bulk endpoint, so each entry is a sequential synchronous HTTP
# call; capping the batch prevents a single tool invocation from pinning
# the event loop for minutes.
_IMPORT_TIME_ENTRIES_MAX_BATCH = 500

# Per-phase timeouts for source_url downloads. Separated so a slow-loris
# style server can't stall us indefinitely on a single phase.
_DOWNLOAD_TIMEOUT = httpx.Timeout(connect=5.0, read=15.0, write=10.0, pool=5.0)

# Max redirects we follow when downloading via source_url. Each hop is
# SSRF-revalidated independently to defeat redirect-based bypasses.
_FILE_DOWNLOAD_MAX_REDIRECTS = 5


def _normalize_field_label(label: str) -> str:
    """Normalize a field label for case/spacing-insensitive comparisons."""
    return re.sub(r"[^a-z0-9]+", "", label.lower())


def _parse_create_issue_fields(
    fields: Optional[Union[Dict[str, Any], str]],
) -> Dict[str, Any]:
    """Parse create issue fields from dict or serialized string payload."""
    return _parse_optional_object_payload(fields, "fields")


def _parse_optional_object_payload(
    payload: Optional[Union[Dict[str, Any], str]], payload_name: str
) -> Dict[str, Any]:
    """Parse an optional payload from dict or serialized JSON object string."""
    if payload is None:
        return {}

    if isinstance(payload, dict):
        parsed: Any = dict(payload)
    elif isinstance(payload, str):
        raw = payload.strip()
        if not raw:
            return {}
        try:
            parsed = json.loads(raw)
        except Exception as e:
            raise ValueError(
                f"Invalid {payload_name} payload. Expected a dict or "
                "JSON object string."
            ) from e
    else:
        raise ValueError(
            f"Invalid {payload_name} payload. Expected a dict or JSON object string."
        )

    if parsed is None:
        raise ValueError(
            f"Invalid {payload_name} payload. Parsed value must be an object/dict."
        )

    if isinstance(parsed, dict) and set(parsed.keys()) == {payload_name}:
        wrapped = parsed.get(payload_name)
        if isinstance(wrapped, dict):
            parsed = wrapped

    if not isinstance(parsed, dict):
        raise ValueError(
            f"Invalid {payload_name} payload. Parsed value must be an object/dict."
        )

    return dict(parsed)


def _extract_possible_values(custom_field: Any) -> List[str]:
    """Extract possible values from a Redmine custom field in a robust way."""
    possible_values = getattr(custom_field, "possible_values", None) or []
    result: List[str] = []
    for value in possible_values:
        if isinstance(value, dict):
            extracted = value.get("value")
        else:
            extracted = getattr(value, "value", value)
        if extracted is not None:
            result.append(str(extracted))
    return result


def _load_required_custom_field_defaults() -> Dict[str, Any]:
    """Load normalized custom field defaults from env + built-in fallbacks."""
    defaults = dict(_DEFAULT_REQUIRED_CUSTOM_FIELD_VALUES)
    raw = os.getenv("REDMINE_REQUIRED_CUSTOM_FIELD_DEFAULTS", "").strip()
    if not raw:
        return defaults

    try:
        loaded = json.loads(raw)
        if isinstance(loaded, dict):
            for key, value in loaded.items():
                if key and value is not None:
                    defaults[_normalize_field_label(str(key))] = value
        else:
            logger.warning(
                "REDMINE_REQUIRED_CUSTOM_FIELD_DEFAULTS must be a JSON object."
            )
    except Exception as e:
        logger.warning(
            "Failed parsing REDMINE_REQUIRED_CUSTOM_FIELD_DEFAULTS as JSON: %s",
            e,
        )

    return defaults


def _is_required_custom_field_autofill_enabled() -> bool:
    """Check whether retry-based required custom field autofill is enabled."""
    return _is_true_env("REDMINE_AUTOFILL_REQUIRED_CUSTOM_FIELDS", "false")


def _extract_missing_required_field_names(error_message: str) -> List[str]:
    """Extract field names from relevant validation errors."""
    message = error_message or ""
    if "Validation failed:" in message:
        message = message.split("Validation failed:", 1)[1]

    # Handle common Redmine validation fragments that imply we should retry
    # required custom field autofill.
    markers = [
        "cannot be blank",
        "is not included in the list",
        "is invalid",
    ]

    missing_names: List[str] = []
    for item in [part.strip() for part in message.split(",") if part.strip()]:
        lower_item = item.lower()
        for marker in markers:
            marker_pos = lower_item.find(marker)
            if marker_pos == -1:
                continue
            field_name = item[:marker_pos].strip(" .:")
            if field_name:
                missing_names.append(field_name)
            break

    return missing_names


def _is_missing_custom_field_value(value: Any) -> bool:
    """Return True when a custom field value should be treated as missing."""
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip() == ""
    if isinstance(value, (list, tuple, set, dict)):
        return len(value) == 0
    return False


def _is_allowed_custom_field_value(value: Any, possible_values: List[str]) -> bool:
    """Check whether a value is compatible with field possible_values."""
    if not possible_values:
        return True
    if isinstance(value, (list, tuple, set)):
        return bool(value) and all(str(item) in possible_values for item in value)
    return str(value) in possible_values


def _resolve_required_custom_field_value(
    custom_field: Any, defaults: Dict[str, Any]
) -> Optional[Any]:
    """Resolve value from explicit defaults only (Redmine default/env override)."""
    name = str(getattr(custom_field, "name", "") or "")
    normalized_name = _normalize_field_label(name)
    possible_values = _extract_possible_values(custom_field)

    default_value = getattr(custom_field, "default_value", None)
    if not _is_missing_custom_field_value(
        default_value
    ) and _is_allowed_custom_field_value(default_value, possible_values):
        return default_value

    preferred = defaults.get(normalized_name)
    if not _is_missing_custom_field_value(preferred) and _is_allowed_custom_field_value(
        preferred, possible_values
    ):
        return preferred

    return None


def _augment_fields_with_required_custom_fields(
    project_id: int,
    issue_fields: Dict[str, Any],
    missing_field_names: List[str],
) -> Dict[str, Any]:
    """Populate missing required custom fields based on project metadata."""
    if not missing_field_names:
        return issue_fields

    missing_normalized = {_normalize_field_label(name) for name in missing_field_names}
    if not missing_normalized:
        return issue_fields

    project = _get_redmine_client().project.get(
        project_id, include="issue_custom_fields"
    )
    project_custom_fields = getattr(project, "issue_custom_fields", None) or []

    updated_fields = dict(issue_fields)
    existing_custom_fields = updated_fields.get("custom_fields", [])
    if existing_custom_fields is None:
        existing_custom_fields = []
    if not isinstance(existing_custom_fields, list):
        raise ValueError(
            "Invalid custom_fields payload. Expected a list of "
            "{'id': <int>, 'value': <value>} dictionaries."
        )

    merged_custom_fields: List[Dict[str, Any]] = []
    existing_entries_by_id: Dict[Any, Dict[str, Any]] = {}
    for entry in existing_custom_fields:
        if not isinstance(entry, dict):
            continue
        entry_copy = dict(entry)
        field_id = entry_copy.get("id")
        if field_id is not None and field_id not in existing_entries_by_id:
            existing_entries_by_id[field_id] = entry_copy
        merged_custom_fields.append(entry_copy)

    defaults = _load_required_custom_field_defaults()

    for custom_field in project_custom_fields:
        field_id = getattr(custom_field, "id", None)
        field_name = str(getattr(custom_field, "name", "") or "")
        if field_id is None or not field_name:
            continue

        normalized_name = _normalize_field_label(field_name)
        if normalized_name not in missing_normalized:
            continue

        possible_values = _extract_possible_values(custom_field)
        field_value = _resolve_required_custom_field_value(custom_field, defaults)
        if field_value is None:
            continue
        existing_entry = existing_entries_by_id.get(field_id)
        if existing_entry is not None:
            existing_value = existing_entry.get("value")
            if _is_missing_custom_field_value(existing_value) or (
                not _is_allowed_custom_field_value(existing_value, possible_values)
            ):
                existing_entry["value"] = field_value
            continue

        new_entry = {"id": field_id, "value": field_value}
        merged_custom_fields.append(new_entry)
        existing_entries_by_id[field_id] = new_entry

    if merged_custom_fields:
        updated_fields["custom_fields"] = merged_custom_fields

    return updated_fields


def _custom_fields_to_list(issue: Any) -> List[Dict[str, Any]]:
    """Convert issue custom_fields to a serializable list."""
    raw_custom_fields = getattr(issue, "custom_fields", None)
    if raw_custom_fields is None:
        return []

    custom_fields: List[Dict[str, Any]] = []
    try:
        iterator = iter(raw_custom_fields)
    except TypeError:
        return []

    for custom_field in iterator:
        if isinstance(custom_field, dict):
            field_id = custom_field.get("id")
            field_name = custom_field.get("name")
            field_value = custom_field.get("value")
        else:
            field_id = getattr(custom_field, "id", None)
            field_name = getattr(custom_field, "name", None)
            field_value = getattr(custom_field, "value", None)

        custom_fields.append(
            {
                "id": field_id,
                "name": field_name,
                "value": _coerce_json_safe(field_value),
            }
        )

    return custom_fields


def _issue_to_dict(issue: Any, include_custom_fields: bool = False) -> Dict[str, Any]:
    """Convert a python-redmine Issue object to a serializable dict."""
    # Use getattr for all potentially missing attributes (search API may not return all)
    assigned = getattr(issue, "assigned_to", None)
    project = getattr(issue, "project", None)
    status = getattr(issue, "status", None)
    priority = getattr(issue, "priority", None)
    author = getattr(issue, "author", None)

    issue_dict = {
        "id": getattr(issue, "id", None),
        "subject": getattr(issue, "subject", ""),
        "description": wrap_insecure_content(getattr(issue, "description", "")),
        "project": (
            {"id": project.id, "name": project.name} if project is not None else None
        ),
        "status": (
            {"id": status.id, "name": status.name} if status is not None else None
        ),
        "priority": (
            {"id": priority.id, "name": priority.name} if priority is not None else None
        ),
        "author": (
            {"id": author.id, "name": author.name} if author is not None else None
        ),
        "assigned_to": (
            {
                "id": assigned.id,
                "name": assigned.name,
            }
            if assigned is not None
            else None
        ),
        "created_on": _safe_isoformat(getattr(issue, "created_on", None)),
        "updated_on": _safe_isoformat(getattr(issue, "updated_on", None)),
    }

    if include_custom_fields:
        issue_dict["custom_fields"] = _custom_fields_to_list(issue)

    return issue_dict


def _coerce_update_custom_fields(
    custom_fields: Optional[Any],
) -> List[Dict[str, Any]]:
    """Normalize an update payload custom_fields value into Redmine format."""
    if custom_fields is None:
        return []
    if not isinstance(custom_fields, list):
        raise ValueError(
            "Invalid custom_fields payload. Expected a list of "
            "{'id': <int>, 'value': <value>} dictionaries."
        )

    normalized: List[Dict[str, Any]] = []
    for entry in custom_fields:
        if not isinstance(entry, dict):
            raise ValueError(
                "Invalid custom_fields payload. Expected a list of "
                "{'id': <int>, 'value': <value>} dictionaries."
            )
        if "id" not in entry:
            raise ValueError("Invalid custom_fields entry. Missing required 'id'.")
        normalized.append({"id": entry["id"], "value": entry.get("value")})
    return normalized


def _upsert_custom_field_entry(
    entries: List[Dict[str, Any]], field_id: Any, value: Any
) -> None:
    """Insert or replace a custom field entry by id."""
    for entry in entries:
        if entry.get("id") == field_id:
            entry["value"] = value
            return
    entries.append({"id": field_id, "value": value})


def _resolve_project_issue_custom_fields(issue_id: int) -> List[Any]:
    """Load project custom-field definitions for a given issue."""
    issue = _get_redmine_client().issue.get(issue_id)
    project = getattr(issue, "project", None)
    project_id = getattr(project, "id", None)
    if project_id is None:
        return []
    project_obj = _get_redmine_client().project.get(
        project_id, include="issue_custom_fields"
    )
    return list(getattr(project_obj, "issue_custom_fields", None) or [])


def _is_standard_issue_update_key(field_name: str) -> bool:
    """Return True when a field name should be passed through unchanged."""
    return field_name in _STANDARD_ISSUE_UPDATE_FIELDS


def _map_named_custom_fields_for_update(
    issue_id: int, update_fields: Dict[str, Any]
) -> Dict[str, Any]:
    """Map named custom fields in an update payload to custom_fields entries."""
    if not update_fields:
        return update_fields

    # Keep caller-provided custom_fields and merge name-based mappings into it.
    missing = object()
    custom_fields_raw = update_fields.pop("custom_fields", missing)
    custom_fields_provided = (
        custom_fields_raw is not missing and custom_fields_raw is not None
    )
    if custom_fields_raw is missing:
        custom_fields_raw = None
    merged_custom_fields = _coerce_update_custom_fields(custom_fields_raw)

    named_candidates = [
        field_name
        for field_name in update_fields.keys()
        if not _is_standard_issue_update_key(field_name)
    ]
    if not named_candidates:
        if custom_fields_provided:
            update_fields["custom_fields"] = merged_custom_fields
        return update_fields

    project_custom_fields = _resolve_project_issue_custom_fields(issue_id)
    by_normalized_name: Dict[str, Dict[str, Any]] = {}
    ambiguous_names: Set[str] = set()

    for custom_field in project_custom_fields:
        field_id = getattr(custom_field, "id", None)
        field_name = str(getattr(custom_field, "name", "") or "")
        if field_id is None or not field_name:
            continue
        normalized = _normalize_field_label(field_name)
        if not normalized:
            continue
        existing = by_normalized_name.get(normalized)
        if existing and existing.get("id") != field_id:
            ambiguous_names.add(normalized)
            continue
        by_normalized_name[normalized] = {
            "id": field_id,
            "name": field_name,
            "possible_values": _extract_possible_values(custom_field),
        }

    for normalized in ambiguous_names:
        by_normalized_name.pop(normalized, None)

    for candidate in named_candidates:
        normalized_candidate = _normalize_field_label(candidate)
        if normalized_candidate in ambiguous_names:
            raise ValueError(
                f"Ambiguous custom field name '{candidate}'. "
                "Use fields.custom_fields with explicit field IDs."
            )

        match = by_normalized_name.get(normalized_candidate)
        if match is None:
            continue

        value = update_fields.pop(candidate)
        possible_values = match["possible_values"]
        if not _is_missing_custom_field_value(
            value
        ) and not _is_allowed_custom_field_value(value, possible_values):
            raise ValueError(
                f"Invalid value '{value}' for custom field '{match['name']}'. "
                f"Allowed values: {possible_values}."
            )
        _upsert_custom_field_entry(merged_custom_fields, match["id"], value)

    if merged_custom_fields or custom_fields_provided:
        update_fields["custom_fields"] = merged_custom_fields

    return update_fields


def _resource_to_dict(resource: Any, resource_type: str) -> Dict[str, Any]:
    """
    Convert any Redmine resource to a serializable dict for search results.

    Args:
        resource: Python-redmine resource object (Issue, WikiPage, etc.)
        resource_type: Type identifier ('issues', 'wiki_pages', etc.)

    Returns:
        Dictionary with standardized fields for search results
    """
    base_dict: Dict[str, Any] = {
        "id": getattr(resource, "id", None),
        "type": resource_type,
    }

    # Extract title from various possible attributes
    if hasattr(resource, "subject"):
        base_dict["title"] = resource.subject
    elif hasattr(resource, "title"):
        base_dict["title"] = resource.title
    elif hasattr(resource, "name"):
        base_dict["title"] = resource.name
    else:
        base_dict["title"] = None

    # Extract project info
    if hasattr(resource, "project") and resource.project is not None:
        base_dict["project"] = (
            resource.project.name
            if hasattr(resource.project, "name")
            else str(resource.project)
        )
        base_dict["project_id"] = getattr(resource.project, "id", None)
    elif hasattr(resource, "project_id") and resource.project_id:
        # Fallback for search results that have project_id but not project object
        base_dict["project"] = None
        base_dict["project_id"] = resource.project_id
    else:
        base_dict["project"] = None
        base_dict["project_id"] = None

    # Extract status (issues have status, wiki pages don't)
    if hasattr(resource, "status"):
        base_dict["status"] = (
            resource.status.name
            if hasattr(resource.status, "name")
            else str(resource.status)
        )
    else:
        base_dict["status"] = None

    # Extract updated timestamp
    if hasattr(resource, "updated_on"):
        base_dict["updated_on"] = (
            str(resource.updated_on) if resource.updated_on else None
        )
    else:
        base_dict["updated_on"] = None

    # Extract description/excerpt (first 200 chars)
    if hasattr(resource, "description") and resource.description:
        raw_excerpt = (
            resource.description[:200] + "..."
            if len(resource.description) > 200
            else resource.description
        )
        base_dict["excerpt"] = wrap_insecure_content(raw_excerpt)
    elif hasattr(resource, "text") and resource.text:
        raw_excerpt = (
            resource.text[:200] + "..." if len(resource.text) > 200 else resource.text
        )
        base_dict["excerpt"] = wrap_insecure_content(raw_excerpt)
    else:
        base_dict["excerpt"] = None

    return base_dict


def _issue_to_dict_selective(
    issue: Any, fields: Optional[List[str]] = None
) -> Dict[str, Any]:
    """Convert a python-redmine Issue object to a dict with selected fields.

    Args:
        issue: The python-redmine Issue object to convert.
        fields: List of field names to include. If None, ["*"], or ["all"],
                returns all fields (same as _issue_to_dict). Invalid or
                missing fields are silently skipped.

    Available fields:
        - id: Issue ID
        - subject: Issue subject/title
        - description: Issue description
        - project: Project info (dict with id and name)
        - status: Status info (dict with id and name)
        - priority: Priority info (dict with id and name)
        - author: Author info (dict with id and name)
        - assigned_to: Assigned user info (dict with id and name, or None)
        - created_on: Creation timestamp (ISO format)
        - updated_on: Last update timestamp (ISO format)

    Returns:
        Dictionary containing only the requested fields.

    Examples:
        >>> _issue_to_dict_selective(issue, ["id", "subject"])
        {"id": 123, "subject": "Bug fix"}

        >>> _issue_to_dict_selective(issue, ["*"])
        # Returns all fields (same as _issue_to_dict)

        >>> _issue_to_dict_selective(issue, None)
        # Returns all fields (same as _issue_to_dict)
    """
    # Handle "all fields" cases
    if fields is None or fields == ["*"] or fields == ["all"]:
        return _issue_to_dict(issue)

    # Build field mapping with all available fields
    # Use getattr for all potentially missing attributes (search API may not return all)
    assigned = getattr(issue, "assigned_to", None)
    project = getattr(issue, "project", None)
    status = getattr(issue, "status", None)
    priority = getattr(issue, "priority", None)
    author = getattr(issue, "author", None)

    all_fields = {
        "id": getattr(issue, "id", None),
        "subject": getattr(issue, "subject", ""),
        "description": wrap_insecure_content(getattr(issue, "description", "")),
        "project": (
            {"id": project.id, "name": project.name} if project is not None else None
        ),
        "status": (
            {"id": status.id, "name": status.name} if status is not None else None
        ),
        "priority": (
            {"id": priority.id, "name": priority.name} if priority is not None else None
        ),
        "author": (
            {"id": author.id, "name": author.name} if author is not None else None
        ),
        "assigned_to": (
            {
                "id": assigned.id,
                "name": assigned.name,
            }
            if assigned is not None
            else None
        ),
        "created_on": _safe_isoformat(getattr(issue, "created_on", None)),
        "updated_on": _safe_isoformat(getattr(issue, "updated_on", None)),
    }

    # Return only requested fields (silently skip invalid field names)
    return {key: all_fields[key] for key in fields if key in all_fields}


def _journals_to_list(issue: Any) -> List[Dict[str, Any]]:
    """Convert journals on an issue object to a list of dicts."""
    raw_journals = getattr(issue, "journals", None)
    if raw_journals is None:
        return []

    journals: List[Dict[str, Any]] = []
    try:
        iterator = iter(raw_journals)
    except TypeError:
        return []

    for journal in iterator:
        notes = getattr(journal, "notes", "")
        if not notes:
            continue
        user = getattr(journal, "user", None)
        journals.append(
            {
                "id": journal.id,
                "user": (
                    {
                        "id": user.id,
                        "name": user.name,
                    }
                    if user is not None
                    else None
                ),
                "notes": wrap_insecure_content(notes),
                "created_on": _safe_isoformat(getattr(journal, "created_on", None)),
            }
        )
    return journals


def _attachments_to_list(issue: Any) -> List[Dict[str, Any]]:
    """Convert attachments on an issue object to a list of dicts."""
    raw_attachments = getattr(issue, "attachments", None)
    if raw_attachments is None:
        return []

    attachments: List[Dict[str, Any]] = []
    try:
        iterator = iter(raw_attachments)
    except TypeError:
        return []

    for attachment in iterator:
        attachments.append(
            {
                "id": attachment.id,
                # filename and description are attacker-controllable
                # (anyone who can attach to an issue sets them). Wrap
                # them in <insecure-content> boundary tags — matches the
                # treatment in _file_to_dict for project files.
                "filename": wrap_insecure_content(getattr(attachment, "filename", "")),
                "filesize": getattr(attachment, "filesize", 0),
                "content_type": getattr(attachment, "content_type", ""),
                "description": wrap_insecure_content(
                    getattr(attachment, "description", "")
                ),
                "content_url": getattr(attachment, "content_url", ""),
                "author": _named_ref(getattr(attachment, "author", None)),
                "created_on": _safe_isoformat(getattr(attachment, "created_on", None)),
            }
        )
    return attachments


def _version_to_dict(version: Any) -> Dict[str, Any]:
    """Convert a python-redmine Version object to a serializable dict."""
    project = getattr(version, "project", None)
    return {
        "id": getattr(version, "id", None),
        "name": getattr(version, "name", ""),
        "description": wrap_insecure_content(getattr(version, "description", "")),
        "status": getattr(version, "status", ""),
        "due_date": (
            str(version.due_date)
            if getattr(version, "due_date", None) is not None
            else None
        ),
        "sharing": getattr(version, "sharing", ""),
        "wiki_page_title": getattr(version, "wiki_page_title", ""),
        "project": (
            {"id": project.id, "name": project.name} if project is not None else None
        ),
        "created_on": _safe_isoformat(getattr(version, "created_on", None)),
        "updated_on": _safe_isoformat(getattr(version, "updated_on", None)),
    }


def _custom_field_trackers_to_list(custom_field: Any) -> List[Dict[str, Any]]:
    """Serialize custom field tracker bindings into a predictable list."""
    raw_trackers = getattr(custom_field, "trackers", None)
    if raw_trackers is None:
        return []

    try:
        iterator = iter(raw_trackers)
    except TypeError:
        return []

    trackers: List[Dict[str, Any]] = []
    for tracker in iterator:
        tracker_id = None
        tracker_name = None

        if isinstance(tracker, dict):
            tracker_id = tracker.get("id")
            tracker_name = tracker.get("name")
        else:
            tracker_id = getattr(tracker, "id", None)
            tracker_name = getattr(tracker, "name", None)

        if tracker_id is None and tracker_name is None:
            continue

        if tracker_id is not None:
            try:
                tracker_id = int(tracker_id)
            except (TypeError, ValueError):
                tracker_id = str(tracker_id)

        trackers.append({"id": tracker_id, "name": tracker_name})

    return trackers


def _custom_field_applies_to_tracker(
    custom_field: Any, tracker_id: Optional[int]
) -> bool:
    """Return whether a custom field is available for the given tracker."""
    if tracker_id is None:
        return True

    trackers = _custom_field_trackers_to_list(custom_field)
    if not trackers:
        # No tracker restrictions exposed by Redmine -> treat as globally available.
        return True

    for tracker in trackers:
        if tracker.get("id") == tracker_id:
            return True

    return False


def _custom_field_to_dict(custom_field: Any) -> Dict[str, Any]:
    """Convert project issue custom field metadata to a serializable dict."""
    return {
        "id": getattr(custom_field, "id", None),
        "name": getattr(custom_field, "name", ""),
        "field_format": getattr(custom_field, "field_format", ""),
        "is_required": bool(getattr(custom_field, "is_required", False)),
        "multiple": bool(getattr(custom_field, "multiple", False)),
        "default_value": getattr(custom_field, "default_value", None),
        "possible_values": _extract_possible_values(custom_field),
        "trackers": _custom_field_trackers_to_list(custom_field),
    }


@mcp.tool()
async def get_redmine_issue(
    issue_id: int,
    include_journals: bool = True,
    include_attachments: bool = True,
    include_custom_fields: bool = True,
    journal_limit: Optional[int] = None,
    journal_offset: int = 0,
    include_watchers: bool = False,
    include_relations: bool = False,
    include_children: bool = False,
) -> Dict[str, Any]:
    """Retrieve a specific Redmine issue by ID.

    Args:
        issue_id: The ID of the issue to retrieve
        include_journals: Whether to include journals (comments) in the result.
            Defaults to ``True``.
        include_attachments: Whether to include attachments metadata in the
            result. Defaults to ``True``.
        include_custom_fields: Whether to include custom fields in the
            result. Defaults to ``True``.
        journal_limit: Maximum number of journals to return. When set,
            enables journal pagination and adds ``journal_pagination``
            metadata to the response.
        journal_offset: Number of journals to skip (used with
            ``journal_limit``). Defaults to ``0``.

    Returns:
        A dictionary containing issue details. If ``include_journals`` is ``True``
        and the issue has journals, they will be returned under the ``"journals"``
        key. If ``include_attachments`` is ``True`` and attachments exist they
        will be returned under the ``"attachments"`` key. On failure a dictionary
        with an ``"error"`` key is returned.
        When ``REDMINE_AGILE_ENABLED=true``, the result also includes
        ``story_points``, ``agile_sprint_id``, and ``agile_position``
        fetched from the RedmineUP Agile plugin endpoint (omitted
        silently on any failure).
    """

    # Ensure cleanup task is started (lazy initialization)
    await _ensure_cleanup_started()
    try:
        # python-redmine is synchronous, so we don't use await here for the library call
        includes = []
        if include_journals:
            includes.append("journals")
        if include_attachments:
            includes.append("attachments")
        if include_watchers:
            includes.append("watchers")
        if include_relations:
            includes.append("relations")
        if include_children:
            includes.append("children")

        if includes:
            issue = _get_redmine_client().issue.get(
                issue_id, include=",".join(includes)
            )
        else:
            issue = _get_redmine_client().issue.get(issue_id)

        result = _issue_to_dict(issue, include_custom_fields=include_custom_fields)
        if include_journals:
            all_journals = _journals_to_list(issue)
            if journal_limit is not None:
                total = len(all_journals)
                offset = journal_offset
                paginated = all_journals[offset : offset + journal_limit]
                result["journals"] = paginated
                result["journal_pagination"] = {
                    "total": total,
                    "offset": offset,
                    "limit": journal_limit,
                    "count": len(paginated),
                    "has_more": (offset + journal_limit) < total,
                }
            else:
                result["journals"] = all_journals
        if include_attachments:
            result["attachments"] = _attachments_to_list(issue)

        if include_watchers:
            raw = getattr(issue, "watchers", None) or []
            result["watchers"] = [{"id": w.id, "name": w.name} for w in raw]
        if include_relations:
            raw = getattr(issue, "relations", None) or []
            result["relations"] = [
                {
                    "id": r.id,
                    "issue_id": r.issue_id,
                    "issue_to_id": r.issue_to_id,
                    "relation_type": r.relation_type,
                }
                for r in raw
            ]
        if include_children:
            raw = getattr(issue, "children", None) or []
            result["children"] = [
                {
                    "id": c.id,
                    "subject": getattr(c, "subject", ""),
                    "tracker": (
                        {"id": c.tracker.id, "name": c.tracker.name}
                        if getattr(c, "tracker", None)
                        else None
                    ),
                }
                for c in raw
            ]

        if _is_agile_enabled():
            try:
                agile = _fetch_agile_data(issue_id)
                result.update(agile)
            except Exception:
                pass  # Silently omit agile fields on any failure

        return result
    except Exception as e:
        return _handle_redmine_error(
            e,
            f"fetching issue {issue_id}",
            {"resource_type": "issue", "resource_id": issue_id},
        )


@mcp.tool()
async def list_redmine_projects() -> List[Dict[str, Any]]:
    """
    Lists all accessible projects in Redmine.
    Returns:
        A list of dictionaries, each representing a project.
    """
    try:
        projects = _get_redmine_client().project.all()
        return [
            {
                "id": project.id,
                "name": project.name,
                "identifier": project.identifier,
                "description": getattr(project, "description", ""),
                "created_on": _safe_isoformat(getattr(project, "created_on", None)),
            }
            for project in projects
        ]
    except Exception as e:
        return [_handle_redmine_error(e, "listing projects")]


@mcp.tool()
async def list_project_issue_custom_fields(
    project_id: Union[str, int], tracker_id: Optional[Union[str, int]] = None
) -> List[Dict[str, Any]]:
    """List issue custom fields configured for a project.

    Args:
        project_id: Project identifier (ID number or string identifier).
        tracker_id: Optional tracker ID to filter custom fields by applicability.

    Returns:
        A list of custom field metadata dictionaries. On failure a list containing
        a single dictionary with an ``"error"`` key is returned.
    """

    parsed_tracker_id: Optional[int] = None
    if tracker_id is not None:
        try:
            parsed_tracker_id = int(tracker_id)
        except (TypeError, ValueError):
            return [
                {
                    "error": (
                        f"Invalid tracker_id '{tracker_id}'. "
                        "Expected an integer tracker ID."
                    )
                }
            ]

    await _ensure_cleanup_started()

    try:
        project = _get_redmine_client().project.get(
            project_id, include="issue_custom_fields"
        )
        custom_fields = getattr(project, "issue_custom_fields", None) or []

        result: List[Dict[str, Any]] = []
        for custom_field in custom_fields:
            if not _custom_field_applies_to_tracker(custom_field, parsed_tracker_id):
                continue
            result.append(_custom_field_to_dict(custom_field))

        return result
    except Exception as e:
        return [
            _handle_redmine_error(
                e,
                f"listing issue custom fields for project {project_id}",
                {"resource_type": "project", "resource_id": project_id},
            )
        ]


@mcp.tool()
async def list_redmine_versions(
    project_id: Union[str, int],
    status_filter: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """List versions (roadmap milestones) for a Redmine project.

    Args:
        project_id: The project ID (numeric) or identifier (string).
        status_filter: Optional filter by version status.
            Allowed values: open, locked, closed.
            When None, all versions are returned.

    Returns:
        A list of version dictionaries. On failure a list containing
        a single dictionary with an ``"error"`` key is returned.
    """

    # Validate status_filter before making API call
    valid_statuses = {"open", "locked", "closed"}
    if status_filter is not None:
        status_filter = str(status_filter).lower()
        if status_filter not in valid_statuses:
            return [
                {
                    "error": (
                        f"Invalid status_filter '{status_filter}'. "
                        f"Allowed values: open, locked, closed"
                    )
                }
            ]

    await _ensure_cleanup_started()
    try:
        versions = _get_redmine_client().version.filter(project_id=project_id)
        result = []
        for version in versions:
            if status_filter is not None:
                if getattr(version, "status", "") != status_filter:
                    continue
            result.append(_version_to_dict(version))
        return result
    except Exception as e:
        return [
            _handle_redmine_error(
                e,
                f"listing versions for project {project_id}",
                {"resource_type": "project", "resource_id": project_id},
            )
        ]


@mcp.tool()
async def manage_redmine_version(
    action: str,
    project_id: Optional[Union[str, int]] = None,
    version_id: Optional[int] = None,
    name: Optional[str] = None,
    description: Optional[str] = None,
    status: Optional[str] = None,
    due_date: Optional[str] = None,
    sharing: Optional[str] = None,
    wiki_page_title: Optional[str] = None,
) -> Dict[str, Any]:
    """Create, update, or delete a Redmine version (milestone/roadmap entry).

    Args:
        action: Operation to perform. One of: ``create``, ``update``,
            ``delete``.
        project_id: Project ID or string identifier. Required for
            ``action="create"``.
        version_id: Numeric version ID. Required for ``action="update"``
            and ``action="delete"``.
        name: Version name. Required for ``action="create"``, optional
            for ``action="update"``.
        description: Version description text.
        status: Version status. Allowed values: ``open``, ``locked``,
            ``closed``. Defaults to ``open`` on create.
        due_date: Due date in ``YYYY-MM-DD`` format.
        sharing: Sharing scope. Allowed values: ``none``, ``descendants``,
            ``hierarchy``, ``tree``, ``system``. Defaults to ``none`` on
            create.
        wiki_page_title: Associated wiki page title.

    Returns:
        For ``create``/``update``: full version dictionary.
        For ``delete``: ``{"success": True, "version_id": ...,
        "message": "..."}``.
        On error: ``{"error": "..."}``.
    """
    _valid_actions = {"create", "update", "delete"}
    _valid_statuses = {"open", "locked", "closed"}

    if action not in _valid_actions:
        return {"error": f"Invalid action '{action}'. Allowed: create, update, delete"}

    if status is not None and status not in _valid_statuses:
        return {"error": f"Invalid status '{status}'. Allowed: open, locked, closed"}

    if action == "create":
        if project_id is None:
            return {"error": "project_id is required for action 'create'"}
        if name is None:
            return {"error": "name is required for action 'create'"}

        if _is_read_only_mode():
            return dict(_READ_ONLY_ERROR)

        await _ensure_cleanup_started()

        optional_fields: Dict[str, Any] = {
            "status": status if status is not None else "open",
            "sharing": sharing if sharing is not None else "none",
        }
        if description is not None:
            optional_fields["description"] = description
        if due_date is not None:
            optional_fields["due_date"] = due_date
        if wiki_page_title is not None:
            optional_fields["wiki_page_title"] = wiki_page_title

        try:
            version = _get_redmine_client().version.create(
                project_id=project_id,
                name=name,
                **optional_fields,
            )
            return _version_to_dict(version)
        except Exception as e:
            return _handle_redmine_error(
                e,
                f"creating version '{name}' in project {project_id}",
                {"resource_type": "version", "resource_id": name},
            )

    elif action == "update":
        if version_id is None:
            return {"error": "version_id is required for action 'update'"}

        _candidates = {
            "name": name,
            "description": description,
            "status": status,
            "due_date": due_date,
            "sharing": sharing,
            "wiki_page_title": wiki_page_title,
        }
        update_fields = {k: v for k, v in _candidates.items() if v is not None}

        if not update_fields:
            return {"error": "At least one field must be provided to update"}

        if _is_read_only_mode():
            return dict(_READ_ONLY_ERROR)

        await _ensure_cleanup_started()

        try:
            _get_redmine_client().version.update(version_id, **update_fields)
            version = _get_redmine_client().version.get(version_id)
            return _version_to_dict(version)
        except Exception as e:
            return _handle_redmine_error(
                e,
                f"updating version {version_id}",
                {"resource_type": "version", "resource_id": version_id},
            )

    else:  # action == "delete"
        if version_id is None:
            return {"error": "version_id is required for action 'delete'"}

        if _is_read_only_mode():
            return dict(_READ_ONLY_ERROR)

        await _ensure_cleanup_started()

        try:
            _get_redmine_client().version.delete(version_id)
            return {
                "success": True,
                "version_id": version_id,
                "message": "Version deleted successfully.",
            }
        except Exception as e:
            return _handle_redmine_error(
                e,
                f"deleting version {version_id}",
                {"resource_type": "version", "resource_id": version_id},
            )


@mcp.tool()
async def list_redmine_issues(
    project_id: Optional[Union[int, str]] = None,
    status_id: Optional[int] = None,
    tracker_id: Optional[int] = None,
    assigned_to_id: Optional[Union[int, str]] = None,
    priority_id: Optional[int] = None,
    fixed_version_id: Optional[int] = None,
    sort: Optional[str] = None,
    limit: Optional[int] = 25,
    offset: int = 0,
    include_pagination_info: bool = False,
    fields: Optional[List[str]] = None,
    filters: Optional[Dict[str, Any]] = None,
) -> Union[List[Dict[str, Any]], Dict[str, Any]]:
    """List Redmine issues with flexible filtering and pagination support.

    A general-purpose tool for listing issues from Redmine. Supports
    filtering by project, status, assignee, tracker, priority, and any
    other Redmine issue filter. Use this to list all issues in a project,
    find unassigned issues, or apply any combination of filters.

    Args:
        project_id: Filter by project (ID or string identifier).
        status_id: Filter by status ID.
        tracker_id: Filter by tracker ID.
        assigned_to_id: Filter by assignee. Use a numeric user ID or the
            special value 'me' to retrieve issues assigned to the currently
            authenticated user.
        priority_id: Filter by priority ID.
        fixed_version_id: Filter by target version/milestone ID.
        sort: Sort order (e.g., "updated_on:desc").
        limit: Maximum number of issues to return (default: 25, max: 1000).
        offset: Number of issues to skip for pagination (default: 0).
        include_pagination_info: Return structured response with pagination
            metadata (default: False).
        fields: List of field names to include in results (default: all).
            Available: id, subject, description, project, status, priority,
            author, assigned_to, created_on, updated_on.
        filters: Additional Redmine API filter parameters as a dict. Use this
            for any filter not listed above (e.g., {"cf_1": "value"}).

    Returns:
        List[Dict] (default) or Dict with 'issues' and 'pagination' keys.
        Issues are limited to prevent token overflow (25,000 token MCP limit).

    Examples:
        >>> await list_redmine_issues(project_id=1)
        [{"id": 1, "subject": "Issue 1", ...}, ...]

        >>> await list_redmine_issues(project_id="my-project", status_id=1)
        [{"id": 2, "subject": "Open issue", ...}, ...]

        >>> await list_redmine_issues(
        ...     project_id=1, limit=25, offset=50, include_pagination_info=True
        ... )
        {
            "issues": [...],
            "pagination": {"total": 150, "has_next": True, "next_offset": 75, ...}
        }

        >>> await list_redmine_issues(
        ...     project_id=1, fields=["id", "subject", "status"]
        ... )
        [{"id": 1, "subject": "Bug fix", "status": {...}}, ...]

    Performance:
        - Memory efficient: Uses server-side pagination
        - Token efficient: Default limit keeps response under 2000 tokens
        - Further reduce tokens: Use fields parameter for minimal data transfer
        - Time efficient: Typically <500ms for limit=25
    """

    # Ensure cleanup task is started (lazy initialization)
    await _ensure_cleanup_started()

    try:
        # Build Redmine API filter dict from explicit parameters
        redmine_api_filters: Dict[str, Any] = {}
        if project_id is not None:
            redmine_api_filters["project_id"] = project_id
        if status_id is not None:
            redmine_api_filters["status_id"] = status_id
        if tracker_id is not None:
            redmine_api_filters["tracker_id"] = tracker_id
        if assigned_to_id is not None:
            redmine_api_filters["assigned_to_id"] = assigned_to_id
        if priority_id is not None:
            redmine_api_filters["priority_id"] = priority_id
        if fixed_version_id is not None:
            redmine_api_filters["fixed_version_id"] = fixed_version_id
        if sort is not None:
            redmine_api_filters["sort"] = sort
        # Merge additional arbitrary Redmine filters if provided
        if filters:
            redmine_api_filters.update(filters)
        filters = redmine_api_filters

        # Log request for monitoring
        filter_keys = list(filters.keys()) if filters else []
        logging.info(
            f"Pagination request: limit={limit}, offset={offset}, filters={filter_keys}"
        )

        # Validate and sanitize parameters
        if limit is not None:
            if not isinstance(limit, int):
                try:
                    limit = int(limit)
                except (ValueError, TypeError):
                    logging.warning(
                        f"Invalid limit type {type(limit)}, using default 25"
                    )
                    limit = 25

            if limit <= 0:
                logging.debug(f"Limit {limit} <= 0, returning empty result")
                empty_result = []
                if include_pagination_info:
                    empty_result = {
                        "issues": [],
                        "pagination": {
                            "total": 0,
                            "limit": limit,
                            "offset": offset,
                            "count": 0,
                            "has_next": False,
                            "has_previous": False,
                            "next_offset": None,
                            "previous_offset": None,
                        },
                    }
                return empty_result

            # Cap at reasonable maximum
            original_limit = limit
            limit = min(limit, 1000)
            if original_limit > limit:
                logging.warning(
                    f"Limit {original_limit} exceeds maximum 1000, capped to {limit}"
                )

        # Validate offset
        if not isinstance(offset, int) or offset < 0:
            logging.warning(f"Invalid offset {offset}, reset to 0")
            offset = 0

        # Use python-redmine ResourceSet native pagination
        # Server-side filtering more efficient than client-side
        redmine_filters = {
            "offset": offset,
            "limit": min(limit or 25, 100),  # Redmine API max per request
            **filters,
        }

        # Get paginated issues from Redmine
        logging.debug(
            f"Calling _get_redmine_client().issue.filter with: {redmine_filters}"
        )
        issues = _get_redmine_client().issue.filter(**redmine_filters)

        # Convert ResourceSet to list (triggers server-side pagination)
        issues_list = list(issues)
        logging.debug(
            f"Retrieved {len(issues_list)} issues with offset={offset}, limit={limit}"
        )

        # Convert to dictionaries with optional field selection
        result_issues = [
            _issue_to_dict_selective(issue, fields) for issue in issues_list
        ]

        # Handle metadata response format
        if include_pagination_info:
            # Get total count from a separate query without offset/limit
            try:
                # Create clean query for total count (no pagination parameters)
                count_filters = {**filters}
                count_query = _get_redmine_client().issue.filter(**count_filters)
                # Must evaluate the query first to get accurate total_count
                list(count_query)  # Trigger evaluation
                total_count = count_query.total_count
                logging.debug(f"Got total count from separate query: {total_count}")
            except Exception as e:
                logging.warning(
                    f"Could not get total count: {e}, using estimated value"
                )
                # For unknown total, use a conservative estimate
                if len(result_issues) == limit:
                    # If we got a full page, there might be more
                    total_count = offset + len(result_issues) + 1
                else:
                    # If we got less than requested, this is likely the end
                    total_count = offset + len(result_issues)

            pagination_info = {
                "total": total_count,
                "limit": limit,
                "offset": offset,
                "count": len(result_issues),
                "has_next": len(result_issues) == limit,
                "has_previous": offset > 0,
                "next_offset": offset + limit if len(result_issues) == limit else None,
                "previous_offset": max(0, offset - limit) if offset > 0 else None,
            }

            result = {"issues": result_issues, "pagination": pagination_info}

            logging.info(
                f"Returning paginated response: {len(result_issues)} issues, "
                f"total={total_count}"
            )
            return result

        # Log success and return simple list
        logging.info(f"Successfully retrieved {len(result_issues)} issues")
        return result_issues

    except Exception as e:
        return [_handle_redmine_error(e, "listing issues")]


@mcp.tool()
async def search_redmine_issues(
    query: str,
    limit: Optional[int] = 25,
    offset: int = 0,
    include_pagination_info: bool = False,
    fields: Optional[List[str]] = None,
    scope: Optional[str] = None,
    open_issues: bool = False,
    options: Optional[Dict[str, Any]] = None,
) -> Union[List[Dict[str, Any]], Dict[str, Any]]:
    """Search Redmine issues matching a query string with pagination support.

    Performs text search across issues using the Redmine Search API.
    Supports server-side pagination to prevent MCP token overflow.

    Args:
        query: Text to search for in issues.
        limit: Maximum number of issues to return (default: 25, max: 1000).
        offset: Number of issues to skip for pagination (default: 0).
        include_pagination_info: Return structured response with pagination
            metadata (default: False).
        fields: List of field names to include in results (default: all).
            Available: id, subject, description, project, status, priority,
            author, assigned_to, created_on, updated_on.
        scope: Search scope. Values: "all", "my_project", "subprojects".
        open_issues: Search only open issues (default: False).
        options: Additional Redmine Search API parameters as a dict.

    Returns:
        List[Dict] (default) or Dict with 'issues' and 'pagination' keys.
        Issues are limited to prevent token overflow (25,000 token MCP limit).

    Examples:
        >>> await search_redmine_issues("bug fix")
        [{"id": 1, "subject": "Bug in login", ...}, ...]

        >>> await search_redmine_issues(
        ...     "performance", limit=10, offset=0, include_pagination_info=True
        ... )
        {
            "issues": [...],
            "pagination": {"limit": 10, "offset": 0, "has_next": True, ...}
        }

        >>> await search_redmine_issues("urgent", fields=["id", "subject", "status"])
        [{"id": 1, "subject": "Critical bug", "status": {...}}, ...]

        >>> await search_redmine_issues("bug", scope="my_project", open_issues=True)
        [{"id": 1, "subject": "Open bug in my project", ...}, ...]

    Note:
        The Redmine Search API does not provide total_count. Pagination
        metadata uses conservative estimation: has_next=True if result
        count equals limit.

        Search API Limitations: The Search API supports text search with
        scope and open_issues filters only. For advanced filtering by
        project_id, status_id, priority_id, etc., use list_redmine_issues()
        instead, which uses the Issues API with full filter support.

    Performance:
        - Memory efficient: Uses server-side pagination
        - Token efficient: Default limit keeps response under 2000 tokens
        - Further reduce tokens: Use fields parameter for minimal data transfer
    """

    try:
        # Build search options dict from explicit parameters
        search_options: Dict[str, Any] = {}
        if scope is not None:
            search_options["scope"] = scope
        if open_issues:
            search_options["open_issues"] = open_issues
        # Merge additional arbitrary search options if provided
        if options:
            search_options.update(options)
        options = search_options

        # Log request for monitoring
        option_keys = list(options.keys()) if options else []
        logging.info(
            f"Search request: query='{query}', limit={limit}, "
            f"offset={offset}, options={option_keys}"
        )

        # Validate and sanitize limit parameter
        if limit is not None:
            if not isinstance(limit, int):
                try:
                    limit = int(limit)
                except (ValueError, TypeError):
                    logging.warning(
                        f"Invalid limit type {type(limit)}, using default 25"
                    )
                    limit = 25

            if limit <= 0:
                logging.debug(f"Limit {limit} <= 0, returning empty result")
                empty_result = []
                if include_pagination_info:
                    empty_result = {
                        "issues": [],
                        "pagination": {
                            "limit": limit,
                            "offset": offset,
                            "count": 0,
                            "has_next": False,
                            "has_previous": False,
                            "next_offset": None,
                            "previous_offset": None,
                        },
                    }
                return empty_result

            # Cap at reasonable maximum
            original_limit = limit
            limit = min(limit, 1000)
            if original_limit > limit:
                logging.warning(
                    f"Limit {original_limit} exceeds maximum 1000, "
                    f"capped to {limit}"
                )

        # Validate offset
        if not isinstance(offset, int) or offset < 0:
            logging.warning(f"Invalid offset {offset}, reset to 0")
            offset = 0

        # Pass offset and limit to Redmine Search API
        search_params = {"offset": offset, "limit": limit, **options}

        # Perform search with pagination
        logging.debug(
            f"Calling _get_redmine_client().issue.search with: {search_params}"
        )
        results = _get_redmine_client().issue.search(query, **search_params)

        if results is None:
            results = []

        # Convert results to list
        issues_list = list(results)
        logging.debug(
            f"Retrieved {len(issues_list)} issues with "
            f"offset={offset}, limit={limit}"
        )

        # Convert to dictionaries with optional field selection
        result_issues = [
            _issue_to_dict_selective(issue, fields) for issue in issues_list
        ]

        # Handle metadata response format
        if include_pagination_info:
            # Search API doesn't provide total_count
            # Use conservative estimation
            pagination_info = {
                "limit": limit,
                "offset": offset,
                "count": len(result_issues),
                "has_next": len(result_issues) == limit,
                "has_previous": offset > 0,
                "next_offset": (
                    offset + limit if len(result_issues) == limit else None
                ),
                "previous_offset": max(0, offset - limit) if offset > 0 else None,
            }

            result = {"issues": result_issues, "pagination": pagination_info}

            logging.info(
                f"Returning paginated search response: " f"{len(result_issues)} issues"
            )
            return result

        # Log success and return simple list
        logging.info(f"Successfully searched and retrieved {len(result_issues)} issues")
        return result_issues

    except Exception as e:
        return _handle_redmine_error(e, f"searching issues with query '{query}'")


@mcp.tool()
async def create_redmine_issue(
    project_id: int,
    subject: str,
    description: str = "",
    fields: Optional[Union[Dict[str, Any], str]] = None,
    extra_fields: Optional[Union[Dict[str, Any], str]] = None,
) -> Dict[str, Any]:
    """Create a new issue in Redmine.

    Compatibility notes:
    - Supports serialized ``fields`` payload (JSON object string)
    - Supports optional ``extra_fields`` payload as object/JSON string
    - Retries once with auto-filled required custom fields if Redmine reports
      relevant validation errors on required custom fields (e.g. blank/invalid)
      and
      ``REDMINE_AUTOFILL_REQUIRED_CUSTOM_FIELDS=true``.
    """

    if _is_read_only_mode():
        return dict(_READ_ONLY_ERROR)

    try:
        issue_fields = _parse_create_issue_fields(fields)
    except ValueError as e:
        return {"error": str(e)}

    try:
        parsed_extra_fields = _parse_optional_object_payload(
            extra_fields, "extra_fields"
        )
    except ValueError as e:
        return {"error": str(e)}

    if parsed_extra_fields:
        issue_fields.update(parsed_extra_fields)

    # Prevent callers from overriding explicit positional parameters.
    issue_fields.pop("project_id", None)
    issue_fields.pop("subject", None)
    issue_fields.pop("description", None)
    issue_fields.pop("extra_fields", None)

    try:
        issue = _get_redmine_client().issue.create(
            project_id=project_id,
            subject=subject,
            description=description,
            **issue_fields,
        )
        return _issue_to_dict(issue)
    except ValidationError as e:
        if not _is_required_custom_field_autofill_enabled():
            return _handle_redmine_error(e, f"creating issue in project {project_id}")

        missing_names = _extract_missing_required_field_names(str(e))
        if not missing_names:
            return _handle_redmine_error(e, f"creating issue in project {project_id}")

        try:
            retry_fields = _augment_fields_with_required_custom_fields(
                project_id=project_id,
                issue_fields=issue_fields,
                missing_field_names=missing_names,
            )

            # Retry only when we have actually augmented payload.
            if retry_fields == issue_fields:
                return _handle_redmine_error(
                    e, f"creating issue in project {project_id}"
                )

            logger.info(
                "Retrying issue creation with auto-filled custom fields: %s",
                missing_names,
            )
            issue = _get_redmine_client().issue.create(
                project_id=project_id,
                subject=subject,
                description=description,
                **retry_fields,
            )
            return _issue_to_dict(issue)
        except Exception as retry_error:
            return _handle_redmine_error(
                retry_error, f"creating issue in project {project_id}"
            )
    except Exception as e:
        return _handle_redmine_error(e, f"creating issue in project {project_id}")


@mcp.tool()
async def update_redmine_issue(issue_id: int, fields: Dict[str, Any]) -> Dict[str, Any]:
    """Update an existing Redmine issue.

    In addition to standard Redmine fields, a ``status_name`` key may be
    provided in ``fields``. When present and ``status_id`` is not supplied, the
    function will look up the corresponding status ID and use it for the update.

    When ``REDMINE_AGILE_ENABLED=true``, a ``story_points`` key may also be
    provided in ``fields``; it is routed to the RedmineUP Agile plugin endpoint
    separately and is not passed to the standard Redmine update. When
    ``REDMINE_AGILE_ENABLED=false`` (default), ``story_points`` is silently
    ignored.

    Non-standard keys in ``fields`` are treated as candidate custom-field names.
    When a matching project custom field is found, it is translated into
    ``custom_fields`` entries for Redmine update payloads.
    """

    if _is_read_only_mode():
        return dict(_READ_ONLY_ERROR)

    update_fields = dict(fields)

    # Extract agile fields — not understood by python-redmine.
    # Use explicit key presence check so story_points=None (clear) still triggers
    # the agile endpoint (story_points is not None would skip it).
    story_points = None
    agile_update_needed = False
    if _is_agile_enabled():
        if "story_points" in update_fields:
            story_points = update_fields.pop("story_points")
            agile_update_needed = True
    else:
        update_fields.pop("story_points", None)

    # Convert status name to id if requested
    if "status_name" in update_fields and "status_id" not in update_fields:
        name = str(update_fields.pop("status_name")).lower()
        try:
            statuses = _get_redmine_client().issue_status.all()
            for status in statuses:
                if getattr(status, "name", "").lower() == name:
                    update_fields["status_id"] = status.id
                    break
        except Exception as e:
            logger.warning(f"Error resolving status name '{name}': {e}")

    try:
        if update_fields:
            update_fields = _map_named_custom_fields_for_update(issue_id, update_fields)
            _get_redmine_client().issue.update(issue_id, **update_fields)
        if agile_update_needed:
            try:
                _apply_agile_story_points(issue_id, story_points)
            except Exception as agile_e:
                return _handle_redmine_error(
                    agile_e,
                    f"updating agile story_points for issue {issue_id}",
                    {"resource_type": "issue", "resource_id": issue_id},
                )
        updated_issue = _get_redmine_client().issue.get(issue_id)
        return _issue_to_dict(updated_issue, include_custom_fields=True)
    except ValidationError as e:
        if not _is_required_custom_field_autofill_enabled():
            return _handle_redmine_error(
                e,
                f"updating issue {issue_id}",
                {"resource_type": "issue", "resource_id": issue_id},
            )

        missing_names = _extract_missing_required_field_names(str(e))
        if not missing_names:
            return _handle_redmine_error(
                e,
                f"updating issue {issue_id}",
                {"resource_type": "issue", "resource_id": issue_id},
            )

        try:
            issue = _get_redmine_client().issue.get(issue_id)
            project = getattr(issue, "project", None)
            project_id = getattr(project, "id", None)
            if project_id is None:
                return _handle_redmine_error(
                    e,
                    f"updating issue {issue_id}",
                    {"resource_type": "issue", "resource_id": issue_id},
                )

            retry_fields = _augment_fields_with_required_custom_fields(
                project_id=project_id,
                issue_fields=update_fields,
                missing_field_names=missing_names,
            )

            # Retry only when we have actually augmented payload.
            if retry_fields == update_fields:
                return _handle_redmine_error(
                    e,
                    f"updating issue {issue_id}",
                    {"resource_type": "issue", "resource_id": issue_id},
                )

            logger.info(
                "Retrying issue update with auto-filled custom fields: %s",
                missing_names,
            )
            _get_redmine_client().issue.update(issue_id, **retry_fields)
            if agile_update_needed:
                try:
                    _apply_agile_story_points(issue_id, story_points)
                except Exception as agile_e:
                    return _handle_redmine_error(
                        agile_e,
                        f"updating agile story_points for issue {issue_id}",
                        {"resource_type": "issue", "resource_id": issue_id},
                    )
            updated_issue = _get_redmine_client().issue.get(issue_id)
            return _issue_to_dict(updated_issue, include_custom_fields=True)
        except Exception as retry_error:
            return _handle_redmine_error(
                retry_error,
                f"updating issue {issue_id}",
                {"resource_type": "issue", "resource_id": issue_id},
            )
    except Exception as e:
        return _handle_redmine_error(
            e,
            f"updating issue {issue_id}",
            {"resource_type": "issue", "resource_id": issue_id},
        )


# ---------------------------------------------------------------------------
# Issue tracking helpers (relations, categories, journals)
# ---------------------------------------------------------------------------


_VALID_ISSUE_RELATION_TYPES: Set[str] = {
    "relates",
    "duplicates",
    "duplicated",
    "blocks",
    "blocked",
    "precedes",
    "follows",
    "copied_to",
    "copied_from",
}


def _issue_relation_to_dict(relation: Any) -> Dict[str, Any]:
    """Convert a python-redmine IssueRelation object to a serializable dict."""
    return {
        "id": getattr(relation, "id", None),
        "issue_id": getattr(relation, "issue_id", None),
        "issue_to_id": getattr(relation, "issue_to_id", None),
        "relation_type": getattr(relation, "relation_type", None),
        "delay": getattr(relation, "delay", None),
    }


def _issue_category_to_dict(category: Any) -> Dict[str, Any]:
    """Convert a python-redmine IssueCategory object to a serializable dict."""
    project = getattr(category, "project", None)
    assigned_to = getattr(category, "assigned_to", None)
    return {
        "id": getattr(category, "id", None),
        "name": wrap_insecure_content(getattr(category, "name", "")),
        "project": _named_ref(project),
        "assigned_to": _named_ref(assigned_to),
    }


def _journal_to_dict(journal: Any, include_private_flag: bool = True) -> Dict[str, Any]:
    """Convert a python-redmine IssueJournal to a serializable dict.

    Unlike `_journals_to_list`, this helper preserves empty-notes entries
    (since they can still carry field-change details) and optionally exposes
    the ``private_notes`` flag.
    """
    user = getattr(journal, "user", None)
    notes = getattr(journal, "notes", "") or ""
    entry: Dict[str, Any] = {
        "id": getattr(journal, "id", None),
        "user": (
            {"id": user.id, "name": getattr(user, "name", "")}
            if user is not None
            else None
        ),
        "notes": wrap_insecure_content(notes) if notes else "",
        "created_on": _safe_isoformat(getattr(journal, "created_on", None)),
    }
    if include_private_flag:
        entry["private_notes"] = bool(getattr(journal, "private_notes", False))
    return entry


# ---------------------------------------------------------------------------
# Issue tracking tools (copy, relations, subtasks, notes, watchers, categories)
# ---------------------------------------------------------------------------


@mcp.tool()
async def copy_issue(
    issue_id: int,
    project_id: Optional[Union[str, int]] = None,
    subject: Optional[str] = None,
    link_original: bool = True,
    copy_subtasks: bool = True,
    copy_attachments: bool = True,
    field_overrides: Optional[Union[Dict[str, Any], str]] = None,
) -> Dict[str, Any]:
    """Duplicate an existing Redmine issue with optional field overrides.

    Uses Redmine's native copy mechanism (``copy_from`` parameter) which
    preserves the original issue's fields while allowing selected overrides.

    Args:
        issue_id: ID of the source issue to copy.
        project_id: Target project for the new issue (ID or identifier).
            Defaults to the source issue's project when omitted.
        subject: Optional new subject for the copy. Defaults to the source
            issue's subject when omitted.
        link_original: When True (default), creates a ``copied_to``/
            ``copied_from`` relation between the original and the copy.
        copy_subtasks: When True (default), the source issue's subtasks are
            recursively copied.
        copy_attachments: When True (default), attachments are copied to
            the new issue.
        field_overrides: Optional dict (or JSON object string) of field
            values to override on the copy (e.g.,
            ``{"assigned_to_id": 5, "description": "..."}``).

    Returns:
        Dictionary containing the newly created issue. On failure a dict
        with an ``"error"`` key is returned.
    """

    if _is_read_only_mode():
        return dict(_READ_ONLY_ERROR)

    try:
        overrides = _parse_optional_object_payload(field_overrides, "field_overrides")
    except ValueError as e:
        return {"error": str(e)}

    # Prevent accidental overwrite of resolved positional-like params.
    overrides.pop("issue_id", None)
    overrides.pop("copy_from", None)

    if project_id is not None:
        overrides["project_id"] = project_id
    if subject is not None:
        overrides["subject"] = subject

    # python-redmine's copy() does `include or ('subtasks', 'attachments')`
    # (managers/standard.py:22-32) — meaning an EMPTY tuple is falsy and
    # silently falls back to copying both. We must pass a sentinel list
    # ['none'] when both flags are False so the library sees truthy input
    # without actually including subtasks or attachments.
    # Any other non-empty input (e.g. ['none']) produces no matching
    # copy_* parameter and therefore copies nothing.
    include_parts: List[str] = []
    if copy_subtasks:
        include_parts.append("subtasks")
    if copy_attachments:
        include_parts.append("attachments")
    if not include_parts:
        # Sentinel prevents the library's default-fallback. "none" is not a
        # recognized include, so no copy_none=1 is added to the request.
        include_parts = ["none"]
    include_tuple = tuple(include_parts)

    try:
        new_issue = _get_redmine_client().issue.copy(
            issue_id,
            link_original=link_original,
            include=include_tuple,
            **overrides,
        )
        return _issue_to_dict(new_issue, include_custom_fields=True)
    except Exception as e:
        return _handle_redmine_error(
            e,
            f"copying issue {issue_id}",
            {"resource_type": "issue", "resource_id": issue_id},
        )


@mcp.tool()
async def manage_issue_relation(
    action: str,
    issue_id: Optional[int] = None,
    issue_to_id: Optional[int] = None,
    relation_id: Optional[int] = None,
    relation_type: Optional[str] = None,
    delay: Optional[int] = None,
) -> Union[List[Dict[str, Any]], Dict[str, Any]]:
    """List, create, or delete a Redmine issue relation.

    Args:
        action: One of: ``list``, ``create``, ``delete``.
        issue_id: Source issue ID. Required for ``list`` and ``create``.
        issue_to_id: Target issue ID. Required for ``create``.
        relation_id: Relation ID. Required for ``delete``.
        relation_type: One of: ``relates``, ``duplicates``, ``duplicated``,
            ``blocks``, ``blocked``, ``precedes``, ``follows``,
            ``copied_to``, ``copied_from``. Defaults to ``relates`` for
            ``create``.
        delay: Delay in days for ``precedes`` / ``follows`` relations.

    Returns:
        ``list``: list of relation dicts.
        ``create``: relation dict.
        ``delete``: ``{"success": True, "deleted_relation_id": ...}``.
        On error: ``{"error": "..."}``.
    """
    _valid_actions = {"list", "create", "delete"}
    if action not in _valid_actions:
        return {"error": f"Invalid action '{action}'. Allowed: list, create, delete"}

    if action == "list":
        if issue_id is None:
            return {"error": "issue_id is required for action 'list'"}
        try:
            relations = _get_redmine_client().issue_relation.filter(issue_id=issue_id)
            return [_issue_relation_to_dict(r) for r in _iter_capped(relations)]
        except Exception as e:
            return _handle_redmine_error(
                e,
                f"listing relations for issue {issue_id}",
                {"resource_type": "issue", "resource_id": issue_id},
            )

    elif action == "create":
        if issue_id is None:
            return {"error": "issue_id is required for action 'create'"}
        if issue_to_id is None:
            return {"error": "issue_to_id is required for action 'create'"}

        _rt = relation_type if relation_type is not None else "relates"
        if _rt not in _VALID_ISSUE_RELATION_TYPES:
            return {
                "error": (
                    f"Invalid relation_type '{_rt}'. Must be one of: "
                    f"{', '.join(sorted(_VALID_ISSUE_RELATION_TYPES))}."
                )
            }

        if _is_read_only_mode():
            return dict(_READ_ONLY_ERROR)

        await _ensure_cleanup_started()

        try:
            params: Dict[str, Any] = {
                "issue_id": issue_id,
                "issue_to_id": issue_to_id,
                "relation_type": _rt,
            }
            if delay is not None:
                params["delay"] = delay
            relation = _get_redmine_client().issue_relation.create(**params)
            return _issue_relation_to_dict(relation)
        except Exception as e:
            return _handle_redmine_error(
                e,
                f"creating relation from issue {issue_id} to {issue_to_id}",
                {"resource_type": "issue", "resource_id": issue_id},
            )

    else:  # action == "delete"
        if relation_id is None:
            return {"error": "relation_id is required for action 'delete'"}

        if _is_read_only_mode():
            return dict(_READ_ONLY_ERROR)

        await _ensure_cleanup_started()

        try:
            _get_redmine_client().issue_relation.delete(relation_id)
            return {"success": True, "deleted_relation_id": relation_id}
        except Exception as e:
            return _handle_redmine_error(
                e,
                f"deleting relation {relation_id}",
                {"resource_type": "relation", "resource_id": relation_id},
            )


@mcp.tool()
async def list_subtasks(
    issue_id: int,
) -> Union[List[Dict[str, Any]], Dict[str, Any]]:
    """List subtasks (child issues) of a given Redmine issue.

    Retrieves all issues whose ``parent_issue_id`` equals the given
    ``issue_id``. To create a new subtask, use ``create_redmine_issue``
    with the ``parent_issue_id`` field set.

    Args:
        issue_id: ID of the parent issue.

    Returns:
        List of child issue dictionaries. On failure a list containing a
        single dictionary with an ``"error"`` key is returned.
    """
    try:
        # Include closed subtasks as well (status_id=*) to match Redmine's
        # parent/child display.
        children = _get_redmine_client().issue.filter(
            parent_id=issue_id,
            status_id="*",
        )
        return [_issue_to_dict(c) for c in _iter_capped(children)]
    except Exception as e:
        return _handle_redmine_error(
            e,
            f"listing subtasks for issue {issue_id}",
            {"resource_type": "issue", "resource_id": issue_id},
        )


@mcp.tool()
async def manage_issue_watcher(
    action: str,
    issue_id: int,
    user_id: int,
) -> Dict[str, Any]:
    """Add or remove a watcher on a Redmine issue. Requires Redmine 2.3.0+.

    Args:
        action: One of: ``add``, ``remove``.
        issue_id: ID of the issue.
        user_id: ID of the user to add or remove as a watcher.

    Returns:
        ``{"success": True, "issue_id": ..., "user_id": ...}`` on success.
        On error: ``{"error": "..."}``.
    """
    _valid_actions = {"add", "remove"}
    if action not in _valid_actions:
        return {"error": f"Invalid action '{action}'. Allowed: add, remove"}

    if not _is_positive_int(issue_id):
        return {"error": "issue_id must be a positive integer."}
    if not _is_positive_int(user_id):
        return {"error": "user_id must be a positive integer."}

    if _is_read_only_mode():
        return dict(_READ_ONLY_ERROR)

    await _ensure_cleanup_started()

    try:
        issue = _get_redmine_client().issue.get(issue_id)
        if action == "add":
            issue.watcher.add(user_id)
        else:
            issue.watcher.remove(user_id)
        return {"success": True, "issue_id": issue_id, "user_id": user_id}
    except Exception as e:
        return _handle_redmine_error(
            e,
            f"{action}ing watcher {user_id} on issue {issue_id}",
            {"resource_type": "issue", "resource_id": issue_id},
        )


@mcp.tool()
async def manage_issue_note(
    action: str,
    journal_id: int,
    notes: Optional[str] = None,
    private_notes: Optional[bool] = None,
    is_private: Optional[bool] = None,
) -> Dict[str, Any]:
    """Edit text or toggle privacy of a Redmine journal (issue note).

    Both actions are writes and are blocked in read-only mode.

    Args:
        action: One of: ``edit``, ``set_private``.
        journal_id: ID of the journal entry (required for both actions).
        notes: New notes text for ``edit`` (required; may be empty string
            to clear the note).
        private_notes: Optionally toggle private flag during ``edit``.
        is_private: Required for ``set_private`` -- ``True`` to mark
            private, ``False`` to make public.

    Returns:
        ``edit``: ``{"success": True, "journal_id": ..., "notes": ...,
        "private_notes": ...}``.
        ``set_private``: ``{"success": True, "journal_id": ...,
        "private_notes": <bool>}``.
        On error: ``{"error": "..."}``.
    """
    _valid_actions = {"edit", "set_private"}
    if action not in _valid_actions:
        return {"error": f"Invalid action '{action}'. Allowed: edit, set_private"}

    if _is_read_only_mode():
        return dict(_READ_ONLY_ERROR)

    if action == "edit":
        if notes is None:
            return {"error": "notes is required for action 'edit'"}
        try:
            params: Dict[str, Any] = {"notes": notes}
            if private_notes is not None:
                params["private_notes"] = bool(private_notes)
            _get_redmine_client().issue_journal.update(journal_id, **params)
            return {
                "success": True,
                "journal_id": journal_id,
                "notes": notes,
                "private_notes": (
                    bool(private_notes) if private_notes is not None else None
                ),
            }
        except Exception as e:
            return _handle_redmine_error(
                e,
                f"editing journal {journal_id}",
                {"resource_type": "journal", "resource_id": journal_id},
            )

    else:  # action == "set_private"
        if is_private is None:
            return {"error": "is_private is required for action 'set_private'"}
        try:
            _get_redmine_client().issue_journal.update(
                journal_id, private_notes=bool(is_private)
            )
            return {
                "success": True,
                "journal_id": journal_id,
                "private_notes": bool(is_private),
            }
        except Exception as e:
            return _handle_redmine_error(
                e,
                f"updating privacy of journal {journal_id}",
                {"resource_type": "journal", "resource_id": journal_id},
            )


@mcp.tool()
async def get_private_notes(issue_id: int) -> List[Dict[str, Any]]:
    """Retrieve only the private notes/journals of a Redmine issue.

    Fetches the issue's journals and filters for entries where
    ``private_notes`` is true. The authenticated user must have the
    "View private notes" permission for non-empty results.

    Args:
        issue_id: ID of the issue.

    Returns:
        List of private journal dictionaries, each containing ``id``,
        ``user``, ``notes``, ``created_on``, and ``private_notes: true``.
        On failure a list with a single ``"error"`` dict is returned.
    """
    try:
        issue = _get_redmine_client().issue.get(issue_id, include="journals")
        raw_journals = getattr(issue, "journals", None) or []

        private: List[Dict[str, Any]] = []
        try:
            iterator = iter(raw_journals)
        except TypeError:
            return []

        for journal in iterator:
            if not bool(getattr(journal, "private_notes", False)):
                continue
            # Skip entries with no notes body (private detail-only records).
            if not getattr(journal, "notes", ""):
                continue
            private.append(_journal_to_dict(journal, include_private_flag=True))
        return private
    except Exception as e:
        return [
            _handle_redmine_error(
                e,
                f"fetching private notes for issue {issue_id}",
                {"resource_type": "issue", "resource_id": issue_id},
            )
        ]


@mcp.tool()
async def manage_issue_category(
    action: str,
    project_id: Optional[Union[str, int]] = None,
    category_id: Optional[int] = None,
    name: Optional[str] = None,
    assigned_to_id: Optional[int] = None,
    reassign_to_id: Optional[int] = None,
) -> Union[List[Dict[str, Any]], Dict[str, Any]]:
    """List, create, update, or delete a Redmine issue category.

    Args:
        action: One of: ``list``, ``create``, ``update``, ``delete``.
        project_id: Project ID or identifier. Required for ``list`` and
            ``create``.
        category_id: Category ID. Required for ``update`` and ``delete``.
        name: Category name. Required for ``create``, optional for
            ``update`` (cannot be blank).
        assigned_to_id: Default assignee user ID. Optional for ``create``
            and ``update``.
        reassign_to_id: Reassign existing issues to this category ID on
            ``delete``. Optional.

    Returns:
        ``list``: list of category dicts.
        ``create``/``update``: category dict.
        ``delete``: ``{"success": True, "deleted_category_id": ...,
        "reassigned_to_id": ...}``.
        On error: ``{"error": "..."}``.
    """
    _valid_actions = {"list", "create", "update", "delete"}
    if action not in _valid_actions:
        return {
            "error": (
                f"Invalid action '{action}'. " "Allowed: list, create, update, delete"
            )
        }

    if action == "list":
        if project_id is None:
            return {"error": "project_id is required for action 'list'"}
        try:
            categories = _get_redmine_client().issue_category.filter(
                project_id=project_id
            )
            return [_issue_category_to_dict(c) for c in _iter_capped(categories)]
        except Exception as e:
            return _handle_redmine_error(
                e,
                f"listing issue categories for project {project_id}",
                {"resource_type": "project", "resource_id": project_id},
            )

    elif action == "create":
        if project_id is None:
            return {"error": "project_id is required for action 'create'"}
        if not name or not name.strip():
            return {"error": "Category 'name' is required."}

        if _is_read_only_mode():
            return dict(_READ_ONLY_ERROR)

        await _ensure_cleanup_started()

        try:
            params: Dict[str, Any] = {
                "project_id": project_id,
                "name": name.strip(),
            }
            if assigned_to_id is not None:
                params["assigned_to_id"] = assigned_to_id
            category = _get_redmine_client().issue_category.create(**params)
            return _issue_category_to_dict(category)
        except Exception as e:
            return _handle_redmine_error(
                e,
                f"creating issue category in project {project_id}",
                {"resource_type": "project", "resource_id": project_id},
            )

    elif action == "update":
        if category_id is None:
            return {"error": "category_id is required for action 'update'"}

        update_params: Dict[str, Any] = {}
        if name is not None:
            stripped = name.strip()
            if not stripped:
                return {"error": "Category 'name' cannot be empty."}
            update_params["name"] = stripped
        if assigned_to_id is not None:
            update_params["assigned_to_id"] = assigned_to_id

        if not update_params:
            return {"error": "No fields provided for update."}

        if _is_read_only_mode():
            return dict(_READ_ONLY_ERROR)

        await _ensure_cleanup_started()

        try:
            client = _get_redmine_client()
            client.issue_category.update(category_id, **update_params)
            updated = client.issue_category.get(category_id)
            return _issue_category_to_dict(updated)
        except Exception as e:
            return _handle_redmine_error(
                e,
                f"updating issue category {category_id}",
                {"resource_type": "issue_category", "resource_id": category_id},
            )

    else:  # action == "delete"
        if category_id is None:
            return {"error": "category_id is required for action 'delete'"}

        if _is_read_only_mode():
            return dict(_READ_ONLY_ERROR)

        await _ensure_cleanup_started()

        try:
            params = {}
            if reassign_to_id is not None:
                params["reassign_to_id"] = reassign_to_id
            _get_redmine_client().issue_category.delete(category_id, **params)
            return {
                "success": True,
                "deleted_category_id": category_id,
                "reassigned_to_id": reassign_to_id,
            }
        except Exception as e:
            return _handle_redmine_error(
                e,
                f"deleting issue category {category_id}",
                {"resource_type": "issue_category", "resource_id": category_id},
            )


@mcp.tool()
async def get_redmine_attachment_download_url(
    attachment_id: int,
) -> Dict[str, Any]:
    """Get HTTP download URL for a Redmine attachment.

    Downloads the attachment to server storage and returns a time-limited
    HTTP URL that clients can use to download the file. Expiry time and
    storage location are controlled by server configuration.

    Args:
        attachment_id: The ID of the attachment to retrieve

    Returns:
        Dict containing download_url, filename, content_type, size,
        expires_at, and attachment_id

    Raises:
        ResourceNotFoundError: If attachment ID doesn't exist
        Exception: For other download or processing errors
    """

    # Ensure cleanup task is started (lazy initialization)
    await _ensure_cleanup_started()

    try:
        # Get attachment metadata from Redmine
        attachment = _get_redmine_client().attachment.get(attachment_id)

        # Server-controlled configuration (secure)
        attachments_dir = Path(os.getenv("ATTACHMENTS_DIR", "./attachments"))
        expires_minutes = float(os.getenv("ATTACHMENT_EXPIRES_MINUTES", "60"))

        # Create secure storage directory
        attachments_dir.mkdir(parents=True, exist_ok=True)

        # Generate secure UUID-based filename
        file_id = str(uuid.uuid4())

        # Download using existing approach - keeps original filename
        downloaded_path = attachment.download(savepath=str(attachments_dir))

        # Get file info
        original_filename = getattr(
            attachment, "filename", f"attachment_{attachment_id}"
        )

        # Create organized storage with UUID directory
        uuid_dir = attachments_dir / file_id
        uuid_dir.mkdir(exist_ok=True)

        # Move file to UUID-based location using atomic operations
        final_path = uuid_dir / original_filename
        temp_path = uuid_dir / f"{original_filename}.tmp"

        # Atomic file move with error handling
        try:
            os.rename(downloaded_path, temp_path)
            os.rename(temp_path, final_path)
        except (OSError, IOError) as e:
            # Cleanup on failure
            try:
                if temp_path.exists():
                    temp_path.unlink()
                if Path(downloaded_path).exists():
                    Path(downloaded_path).unlink()
            except OSError:
                pass  # Best effort cleanup
            return {"error": f"Failed to store attachment: {str(e)}"}

        # Calculate expiry time (timezone-aware)
        expires_hours = expires_minutes / 60.0
        expires_at = datetime.now(timezone.utc) + timedelta(hours=expires_hours)

        # Store metadata atomically (following existing pattern)
        metadata = {
            "file_id": file_id,
            "attachment_id": attachment_id,
            "original_filename": original_filename,
            "file_path": str(final_path),
            "content_type": getattr(
                attachment, "content_type", "application/octet-stream"
            ),
            "size": final_path.stat().st_size,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "expires_at": expires_at.isoformat(),
        }

        metadata_file = uuid_dir / "metadata.json"
        temp_metadata = uuid_dir / "metadata.json.tmp"

        # Atomic metadata write with error handling
        try:
            with open(temp_metadata, "w") as f:
                json.dump(metadata, f, indent=2)
            os.rename(temp_metadata, metadata_file)
        except (OSError, IOError, ValueError) as e:
            # Cleanup on failure
            try:
                if temp_metadata.exists():
                    temp_metadata.unlink()
                if final_path.exists():
                    final_path.unlink()
            except OSError:
                pass  # Best effort cleanup
            return {"error": f"Failed to save metadata: {str(e)}"}

        # Generate server base URL from environment configuration
        # Use public configuration for external URLs
        public_host = os.getenv("PUBLIC_HOST", os.getenv("SERVER_HOST", "localhost"))
        public_port = os.getenv("PUBLIC_PORT", os.getenv("SERVER_PORT", "8000"))

        # Handle special case of 0.0.0.0 bind address
        if public_host == "0.0.0.0":
            public_host = "localhost"

        download_url = f"http://{public_host}:{public_port}/files/{file_id}"

        return {
            "download_url": download_url,
            "filename": original_filename,
            "content_type": metadata["content_type"],
            "size": metadata["size"],
            "expires_at": metadata["expires_at"],
            "attachment_id": attachment_id,
        }

    except Exception as e:
        return _handle_redmine_error(
            e,
            f"downloading attachment {attachment_id}",
            {"resource_type": "attachment", "resource_id": attachment_id},
        )


@mcp.tool()
async def summarize_project_status(project_id: int, days: int = 30) -> Dict[str, Any]:
    """Provide a summary of project status based on issue activity over the
    specified time period.

    Args:
        project_id: The ID of the project to summarize
        days: Number of days to look back for analysis. Defaults to 30.

    Returns:
        A dictionary containing project status summary with issue counts,
        activity metrics, and trends. On error, returns a dictionary with
        an "error" key.
    """

    try:
        # Validate project exists
        try:
            project = _get_redmine_client().project.get(project_id)
        except ResourceNotFoundError:
            return {"error": f"Project {project_id} not found."}

        # Calculate date range
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days)
        date_filter = f">={start_date.strftime('%Y-%m-%d')}"

        # Get issues created in the date range
        created_issues = list(
            _get_redmine_client().issue.filter(
                project_id=project_id, created_on=date_filter
            )
        )

        # Get issues updated in the date range
        updated_issues = list(
            _get_redmine_client().issue.filter(
                project_id=project_id, updated_on=date_filter
            )
        )

        # Analyze created issues
        created_stats = _analyze_issues(created_issues)

        # Analyze updated issues
        updated_stats = _analyze_issues(updated_issues)

        # Calculate trends
        total_created = len(created_issues)
        total_updated = len(updated_issues)

        # Get all project issues for context
        all_issues = list(_get_redmine_client().issue.filter(project_id=project_id))
        all_stats = _analyze_issues(all_issues)

        return {
            "project": {
                "id": project.id,
                "name": project.name,
                "identifier": getattr(project, "identifier", ""),
            },
            "analysis_period": {
                "days": days,
                "start_date": start_date.strftime("%Y-%m-%d"),
                "end_date": end_date.strftime("%Y-%m-%d"),
            },
            "recent_activity": {
                "issues_created": total_created,
                "issues_updated": total_updated,
                "created_breakdown": created_stats,
                "updated_breakdown": updated_stats,
            },
            "project_totals": {
                "total_issues": len(all_issues),
                "overall_breakdown": all_stats,
            },
            "insights": {
                "daily_creation_rate": round(total_created / days, 2),
                "daily_update_rate": round(total_updated / days, 2),
                "recent_activity_percentage": round(
                    (total_updated / len(all_issues) * 100) if all_issues else 0, 2
                ),
            },
        }

    except Exception as e:
        return _handle_redmine_error(
            e,
            f"summarizing project {project_id}",
            {"resource_type": "project", "resource_id": project_id},
        )


def _analyze_issues(issues: List[Any]) -> Dict[str, Any]:
    """Helper function to analyze a list of issues and return statistics."""
    if not issues:
        return {
            "by_status": {},
            "by_priority": {},
            "by_assignee": {},
            "total": 0,
        }

    status_counts = {}
    priority_counts = {}
    assignee_counts = {}

    for issue in issues:
        # Count by status
        status_name = getattr(issue.status, "name", "Unknown")
        status_counts[status_name] = status_counts.get(status_name, 0) + 1

        # Count by priority
        priority_name = getattr(issue.priority, "name", "Unknown")
        priority_counts[priority_name] = priority_counts.get(priority_name, 0) + 1

        # Count by assignee
        assigned_to = getattr(issue, "assigned_to", None)
        if assigned_to:
            assignee_name = getattr(assigned_to, "name", "Unknown")
            assignee_counts[assignee_name] = assignee_counts.get(assignee_name, 0) + 1
        else:
            assignee_counts["Unassigned"] = assignee_counts.get("Unassigned", 0) + 1

    return {
        "by_status": status_counts,
        "by_priority": priority_counts,
        "by_assignee": assignee_counts,
        "total": len(issues),
    }


@mcp.tool()
async def search_entire_redmine(
    query: str,
    resources: Optional[List[str]] = None,
    limit: int = 100,
    offset: int = 0,
) -> Dict[str, Any]:
    """
    Search for issues and wiki pages across the Redmine instance.

    Args:
        query: Text to search for. Case sensitivity controlled by server DB config.
        resources: Filter by resource types. Allowed: ['issues', 'wiki_pages']
                   Default: None (searches both issues and wiki_pages)
        limit: Maximum number of results to return (max 100)
        offset: Pagination offset for server-side pagination

    Returns:
        Dictionary containing search results, counts, and metadata.
        On error, returns {"error": "message"}.

    Note:
        v1.4 Scope Limitation: Only 'issues' and 'wiki_pages' are supported.
        Requires Redmine 3.3.0 or higher for search API support.
    """

    try:
        await _ensure_cleanup_started()

        # Validate and enforce scope limitation (v1.4)
        allowed_types = ["issues", "wiki_pages"]
        if resources:
            resources = [r for r in resources if r in allowed_types]
            if not resources:
                resources = allowed_types  # Fall back to default if all filtered
        else:
            resources = allowed_types

        # Cap limit at 100 (Redmine API maximum)
        limit = min(limit, 100)
        if limit <= 0:
            limit = 100

        # Build search options
        search_options = {
            "resources": resources,
            "limit": limit,
            "offset": offset,
        }

        # Execute search
        categorized_results = _get_redmine_client().search(query, **search_options)

        # Handle empty results (python-redmine returns None)
        if not categorized_results:
            return {
                "results": [],
                "results_by_type": {},
                "total_count": 0,
                "query": query,
            }

        # Process categorized results
        all_results = []
        results_by_type: Dict[str, int] = {}

        for resource_type, resource_set in categorized_results.items():
            # Skip 'unknown' category (plugin resources)
            if resource_type == "unknown":
                continue

            # Skip if not in allowed types
            if resource_type not in allowed_types:
                continue

            # Handle both ResourceSet and dict (for 'unknown')
            if hasattr(resource_set, "__iter__"):
                count = 0
                for resource in resource_set:
                    result_dict = _resource_to_dict(resource, resource_type)
                    all_results.append(result_dict)
                    count += 1
                if count > 0:
                    results_by_type[resource_type] = count

        return {
            "results": all_results,
            "results_by_type": results_by_type,
            "total_count": len(all_results),
            "query": query,
        }

    except VersionMismatchError:
        return {"error": "Search requires Redmine 3.3.0 or higher."}
    except Exception as e:
        return _handle_redmine_error(e, f"searching Redmine for '{query}'")


def _membership_to_dict(membership: Any) -> Dict[str, Any]:
    """Convert a project membership to a serializable dict."""
    user = getattr(membership, "user", None)
    group = getattr(membership, "group", None)
    project = getattr(membership, "project", None)
    roles = getattr(membership, "roles", None) or []

    result: Dict[str, Any] = {
        "id": getattr(membership, "id", None),
    }

    # User or group (memberships can be for either)
    if user is not None:
        result["user"] = _named_ref(user)
        result["group"] = None
    elif group is not None:
        result["user"] = None
        result["group"] = _named_ref(group)
    else:
        result["user"] = None
        result["group"] = None

    # Project info
    result["project"] = _named_ref(project)

    # Roles
    result["roles"] = []
    try:
        for role in roles:
            if isinstance(role, dict):
                result["roles"].append(
                    {
                        "id": role.get("id"),
                        "name": wrap_insecure_content(role.get("name", "")),
                    }
                )
            else:
                result["roles"].append(
                    {
                        "id": getattr(role, "id", None),
                        "name": wrap_insecure_content(getattr(role, "name", "")),
                    }
                )
    except TypeError:
        pass  # roles not iterable

    return result


def _time_entry_to_dict(time_entry: Any) -> Dict[str, Any]:
    """Convert a time entry to a serializable dict."""
    user = getattr(time_entry, "user", None)
    project = getattr(time_entry, "project", None)
    issue = getattr(time_entry, "issue", None)
    activity = getattr(time_entry, "activity", None)

    # `comments` is user-controlled free-form text. Wrap it in
    # <insecure-content> boundary tags so downstream LLMs treat it as
    # untrusted data rather than instructions.
    return {
        "id": getattr(time_entry, "id", None),
        "hours": getattr(time_entry, "hours", 0),
        "comments": wrap_insecure_content(getattr(time_entry, "comments", "")),
        "spent_on": (
            str(time_entry.spent_on)
            if getattr(time_entry, "spent_on", None) is not None
            else None
        ),
        "user": _named_ref(user),
        "project": _named_ref(project),
        "issue": ({"id": getattr(issue, "id", None)} if issue is not None else None),
        "activity": (_named_ref(activity) if activity is not None else None),
        "created_on": _safe_isoformat(getattr(time_entry, "created_on", None)),
        "updated_on": _safe_isoformat(getattr(time_entry, "updated_on", None)),
    }


def _wiki_page_to_dict(
    wiki_page: Any, include_attachments: bool = True
) -> Dict[str, Any]:
    """Convert a wiki page object to a dictionary.

    Args:
        wiki_page: Redmine wiki page object
        include_attachments: Whether to include attachment metadata

    Returns:
        Dictionary with wiki page data
    """
    result: Dict[str, Any] = {
        "title": wiki_page.title,
        "text": wrap_insecure_content(wiki_page.text),
        "version": wiki_page.version,
    }

    # Add optional timestamp fields
    if hasattr(wiki_page, "created_on"):
        result["created_on"] = (
            str(wiki_page.created_on) if wiki_page.created_on else None
        )
    else:
        result["created_on"] = None

    if hasattr(wiki_page, "updated_on"):
        result["updated_on"] = (
            str(wiki_page.updated_on) if wiki_page.updated_on else None
        )
    else:
        result["updated_on"] = None

    # Add author info
    if hasattr(wiki_page, "author"):
        result["author"] = {
            "id": wiki_page.author.id,
            "name": wiki_page.author.name,
        }

    # Add project info
    if hasattr(wiki_page, "project"):
        result["project"] = {
            "id": wiki_page.project.id,
            "name": wiki_page.project.name,
        }

    # Process attachments if requested
    if include_attachments and hasattr(wiki_page, "attachments"):
        result["attachments"] = []
        for attachment in wiki_page.attachments:
            att_dict = {
                "id": attachment.id,
                "filename": attachment.filename,
                "filesize": attachment.filesize,
                "content_type": attachment.content_type,
                "description": getattr(attachment, "description", ""),
                "created_on": (
                    str(attachment.created_on)
                    if hasattr(attachment, "created_on") and attachment.created_on
                    else None
                ),
            }
            result["attachments"].append(att_dict)

    return result


@mcp.tool()
async def manage_redmine_wiki_page(
    action: str,
    project_id: Union[str, int],
    wiki_page_title: Optional[str] = None,
    version: Optional[int] = None,
    include_attachments: bool = True,
    text: Optional[str] = None,
    comments: Optional[str] = None,
    new_title: Optional[str] = None,
    redirect_existing_links: bool = True,
) -> Union[List[Dict[str, Any]], Dict[str, Any]]:
    """List, get, create, update, delete, or rename a Redmine wiki page.

    Args:
        action: One of: ``list``, ``get``, ``create``, ``update``,
            ``delete``, ``rename``.
        project_id: Project identifier (required for all actions).
        wiki_page_title: Wiki page title. Required for all actions
            except ``list``.
        version: Specific version to retrieve (``get`` only, optional).
        include_attachments: Include attachment metadata in ``get``
            response. Default ``True``.
        text: Page content. Required for ``create`` and ``update``.
        comments: Change log comment. Optional for ``create`` and
            ``update``.
        new_title: New title for the page (required for ``rename``).
        redirect_existing_links: When ``True`` (default), the rename
            creates a redirect from ``wiki_page_title`` to ``new_title``.
            Passed to the API as ``"1"`` / ``"0"``.

    Returns:
        ``list``: list of page metadata dicts (no body text).
        ``get`` / ``create`` / ``update``: wiki page dict.
        ``delete``: ``{"success": True, "title": ..., "message": ...}``.
        ``rename``: ``{"success": True, ...}`` with the renamed page's
        metadata to confirm the title change actually applied.
        On error: ``{"error": "..."}``.
    """
    _valid_actions = {"list", "get", "create", "update", "delete", "rename"}
    if action not in _valid_actions:
        return {
            "error": (
                f"Invalid action '{action}'. "
                "Allowed: list, get, create, update, delete, rename"
            )
        }

    if action == "list":
        try:
            client = _get_redmine_client()
            pages = client.wiki_page.filter(project_id=project_id)
            items: List[Dict[str, Any]] = []
            for page in _iter_capped(pages):
                entry: Dict[str, Any] = {
                    "title": getattr(page, "title", None),
                    "version": getattr(page, "version", None),
                    "created_on": _safe_isoformat(getattr(page, "created_on", None)),
                    "updated_on": _safe_isoformat(getattr(page, "updated_on", None)),
                }
                parent = getattr(page, "parent", None)
                if parent is not None:
                    entry["parent_title"] = getattr(parent, "title", None)
                items.append(entry)
            return items
        except Exception as e:
            return _handle_redmine_error(
                e,
                f"listing wiki pages in project {project_id}",
                {"resource_type": "wiki pages", "resource_id": project_id},
            )

    # All non-list actions require wiki_page_title.
    if not isinstance(wiki_page_title, str) or not wiki_page_title.strip():
        return {
            "error": (
                f"wiki_page_title is required for action '{action}' "
                "and must be a non-empty string."
            )
        }

    if action == "get":
        try:
            if version:
                wiki_page = _get_redmine_client().wiki_page.get(
                    wiki_page_title, project_id=project_id, version=version
                )
            else:
                wiki_page = _get_redmine_client().wiki_page.get(
                    wiki_page_title, project_id=project_id
                )
            return _wiki_page_to_dict(wiki_page, include_attachments)
        except Exception as e:
            return _handle_redmine_error(
                e,
                f"fetching wiki page '{wiki_page_title}' in project {project_id}",
                {"resource_type": "wiki page", "resource_id": wiki_page_title},
            )

    elif action == "create":
        if text is None:
            return {"error": "text is required for action 'create'"}

        if _is_read_only_mode():
            return dict(_READ_ONLY_ERROR)

        await _ensure_cleanup_started()

        try:
            wiki_page = _get_redmine_client().wiki_page.create(
                project_id=project_id,
                title=wiki_page_title,
                text=text,
                comments=comments if comments else None,
            )
            return _wiki_page_to_dict(wiki_page)
        except Exception as e:
            return _handle_redmine_error(
                e,
                f"creating wiki page '{wiki_page_title}' in project {project_id}",
                {"resource_type": "wiki page", "resource_id": wiki_page_title},
            )

    elif action == "update":
        if text is None:
            return {"error": "text is required for action 'update'"}

        if _is_read_only_mode():
            return dict(_READ_ONLY_ERROR)

        await _ensure_cleanup_started()

        try:
            _get_redmine_client().wiki_page.update(
                wiki_page_title,
                project_id=project_id,
                text=text,
                comments=comments if comments else None,
            )
            wiki_page = _get_redmine_client().wiki_page.get(
                wiki_page_title, project_id=project_id
            )
            return _wiki_page_to_dict(wiki_page)
        except Exception as e:
            return _handle_redmine_error(
                e,
                f"updating wiki page '{wiki_page_title}' in project {project_id}",
                {"resource_type": "wiki page", "resource_id": wiki_page_title},
            )

    elif action == "delete":
        if _is_read_only_mode():
            return dict(_READ_ONLY_ERROR)

        await _ensure_cleanup_started()

        try:
            _get_redmine_client().wiki_page.delete(
                wiki_page_title, project_id=project_id
            )
            return {
                "success": True,
                "title": wiki_page_title,
                "message": f"Wiki page '{wiki_page_title}' deleted successfully.",
            }
        except Exception as e:
            return _handle_redmine_error(
                e,
                f"deleting wiki page '{wiki_page_title}' in project {project_id}",
                {"resource_type": "wiki page", "resource_id": wiki_page_title},
            )

    else:  # action == "rename"
        # Title validation runs before the read-only check so the
        # per-action structure matches the rest of this tool. The original
        # PR #98 ``rename_wiki_page`` checked read-only first; that ordering
        # only differs from this one when an invalid ``new_title`` is sent
        # while read-only mode is on.
        if not isinstance(new_title, str) or not new_title.strip():
            return {"error": "new_title must be a non-empty string."}
        if new_title == wiki_page_title:
            return {"error": "new_title must differ from wiki_page_title."}

        if _is_read_only_mode():
            return dict(_READ_ONLY_ERROR)

        await _ensure_cleanup_started()

        try:
            client = _get_redmine_client()

            # Redmine requires `text` on every wiki update; preserve the
            # existing body so the rename is a pure title change.
            existing = client.wiki_page.get(wiki_page_title, project_id=project_id)
            existing_text = getattr(existing, "text", "") or ""

            update_kwargs: Dict[str, Any] = {
                "project_id": project_id,
                "title": new_title,
                "text": existing_text,
            }
            if redirect_existing_links:
                update_kwargs["redirect_existing_links"] = "1"

            client.wiki_page.update(wiki_page_title, **update_kwargs)

            # If the API user lacks `rename_wiki_pages`, Redmine silently
            # drops the title change. Re-fetch at the new title to confirm.
            try:
                renamed = client.wiki_page.get(new_title, project_id=project_id)
            except Exception:
                return {
                    "error": (
                        "Rename appeared to succeed but the page is not "
                        f"reachable at '{new_title}'. The API user may lack "
                        "the 'rename_wiki_pages' permission (Redmine "
                        "silently drops the title change in that case)."
                    )
                }

            renamed_dict = _wiki_page_to_dict(renamed, include_attachments=False)
            return {"success": True, **renamed_dict}
        except Exception as e:
            return _handle_redmine_error(
                e,
                (
                    f"renaming wiki page '{wiki_page_title}' to "
                    f"'{new_title}' in project {project_id}"
                ),
                {"resource_type": "wiki page", "resource_id": wiki_page_title},
            )


@mcp.tool()
async def list_project_members(
    project_id: Union[str, int],
) -> List[Dict[str, Any]]:
    """List members of a Redmine project.

    Returns all users and groups that are members of the specified project,
    along with their assigned roles.

    Args:
        project_id: Project identifier (ID number or string identifier)

    Returns:
        A list of membership dictionaries containing user/group info and roles.
        On failure, a list containing a single dictionary with an "error" key.

    Examples:
        >>> await list_project_members("my-project")
        [
            {
                "id": 1,
                "user": {"id": 5, "name": "John Doe"},
                "group": null,
                "project": {"id": 1, "name": "My Project"},
                "roles": [{"id": 3, "name": "Developer"}]
            },
            ...
        ]
    """
    try:
        memberships = _get_redmine_client().project_membership.filter(
            project_id=project_id
        )
        return [_membership_to_dict(m) for m in memberships]
    except Exception as e:
        return [
            _handle_redmine_error(
                e,
                f"listing members for project {project_id}",
                {"resource_type": "project", "resource_id": project_id},
            )
        ]


# ---------------------------------------------------------------------------
# Project tools: modules + membership management
# ---------------------------------------------------------------------------


@mcp.tool()
async def list_redmine_roles() -> Union[List[Dict[str, Any]], Dict[str, Any]]:
    """List all roles defined in the Redmine instance.

    Returns basic role metadata (``id`` and ``name``) for every role
    configured in Redmine. Use this tool BEFORE calling
    ``add_project_member`` or ``update_project_member`` to discover the
    correct ``role_ids`` — role IDs vary between Redmine instances and
    must not be guessed.

    Returns:
        A list of role dictionaries, each with ``id`` and ``name``.
        On failure, a dict with an ``"error"`` key.

    Example:
        >>> await list_redmine_roles()
        [
            {"id": 3, "name": "Manager"},
            {"id": 4, "name": "Developer"},
            {"id": 5, "name": "Reporter"}
        ]
    """
    try:
        roles = _get_redmine_client().role.all()
        return [
            {
                "id": getattr(r, "id", None),
                "name": getattr(r, "name", ""),
            }
            for r in roles
        ]
    except Exception as e:
        return _handle_redmine_error(e, "listing roles")


@mcp.tool()
async def get_project_modules(
    project_id: Union[str, int],
) -> Dict[str, Any]:
    """Retrieve the enabled modules for a Redmine project.

    Modules control which features are visible/usable in a project
    (e.g., ``issue_tracking``, ``time_tracking``, ``wiki``, ``repository``).

    Args:
        project_id: Project identifier (numeric ID or string identifier).

    Returns:
        Dictionary with ``project_id``, ``project_name`` and
        ``enabled_modules`` (list of module name strings). On failure a
        dict with an ``"error"`` key is returned.

    Example:
        >>> await get_project_modules("my-project")
        {
            "project_id": 1,
            "project_name": "My Project",
            "enabled_modules": ["issue_tracking", "wiki", "time_tracking"]
        }
    """
    try:
        project = _get_redmine_client().project.get(
            project_id, include="enabled_modules"
        )
        raw_modules = getattr(project, "enabled_modules", None) or []

        module_names: List[str] = []
        try:
            iterator = iter(raw_modules)
        except TypeError:
            iterator = iter(())

        for mod in iterator:
            # python-redmine's Project.encode() converts enabled_modules
            # to a plain list of strings. Older versions / raw HTTP
            # responses may return dicts or resource-like objects.
            if isinstance(mod, str):
                name = mod
            elif isinstance(mod, dict):
                name = mod.get("name")
            else:
                name = getattr(mod, "name", None)
            if name:
                module_names.append(str(name))

        return {
            "project_id": getattr(project, "id", None),
            "project_name": getattr(project, "name", ""),
            "enabled_modules": module_names,
        }
    except Exception as e:
        return _handle_redmine_error(
            e,
            f"getting modules for project {project_id}",
            {"resource_type": "project", "resource_id": project_id},
        )


@mcp.tool()
async def manage_project_member(
    action: str,
    project_id: Optional[Union[str, int]] = None,
    membership_id: Optional[int] = None,
    user_id: Optional[int] = None,
    group_id: Optional[int] = None,
    role_ids: Optional[List[int]] = None,
) -> Dict[str, Any]:
    """Add, update, or remove a Redmine project membership.

    Args:
        action: Operation to perform. One of: ``add``, ``update``, ``remove``.
        project_id: Project ID or identifier. Required for ``action="add"``.
        membership_id: Membership ID. Required for ``action="update"`` and
            ``action="remove"``.
        user_id: User ID. Exactly one of ``user_id`` or ``group_id`` required
            for ``action="add"``.
        group_id: Group ID. Exactly one of ``user_id`` or ``group_id`` required
            for ``action="add"``.
        role_ids: Non-empty list of role IDs. Required for ``action="add"``
            and ``action="update"``. Use ``list_redmine_roles`` to discover
            valid role IDs.

    Returns:
        For ``add``/``update``: membership dictionary.
        For ``remove``: ``{"success": True, "deleted_membership_id": ...}``.
        On error: ``{"error": "..."}``.
    """
    _valid_actions = {"add", "update", "remove"}
    if action not in _valid_actions:
        return {"error": (f"Invalid action '{action}'. Allowed: add, update, remove")}

    if action == "add":
        if project_id is None:
            return {"error": "project_id is required for action 'add'"}
        if (user_id is None) == (group_id is None):
            return {"error": "Exactly one of user_id or group_id must be provided."}
        principal_candidate = user_id if user_id is not None else group_id
        if not _is_positive_int(principal_candidate):
            return {"error": "user_id / group_id must be a positive integer."}
        if not role_ids:
            return {
                "error": (
                    "At least one role_id must be provided. "
                    "Use `list_redmine_roles` to discover valid role IDs."
                )
            }
        if not isinstance(role_ids, list) or not all(
            _is_positive_int(r) for r in role_ids
        ):
            return {
                "error": (
                    "role_ids must be a list of positive integers. "
                    "Use `list_redmine_roles` to discover valid role IDs."
                )
            }

        if _is_read_only_mode():
            return dict(_READ_ONLY_ERROR)

        await _ensure_cleanup_started()

        # Redmine's POST /projects/{id}/memberships endpoint uses `user_id`
        # for BOTH users and groups (shared principal ID namespace).
        principal_id = user_id if user_id is not None else group_id

        try:
            membership = _get_redmine_client().project_membership.create(
                project_id=project_id,
                user_id=principal_id,
                role_ids=role_ids,
            )
            return _membership_to_dict(membership)
        except Exception as e:
            return _handle_redmine_error(
                e,
                f"adding member to project {project_id}",
                {"resource_type": "project", "resource_id": project_id},
            )

    elif action == "update":
        if membership_id is None:
            return {"error": "membership_id is required for action 'update'"}
        if not role_ids:
            return {
                "error": (
                    "At least one role_id must be provided. "
                    "Use `list_redmine_roles` to discover valid role IDs."
                )
            }
        if not isinstance(role_ids, list) or not all(
            _is_positive_int(r) for r in role_ids
        ):
            return {
                "error": (
                    "role_ids must be a list of positive integers. "
                    "Use `list_redmine_roles` to discover valid role IDs."
                )
            }

        if _is_read_only_mode():
            return dict(_READ_ONLY_ERROR)

        await _ensure_cleanup_started()

        try:
            client = _get_redmine_client()
            client.project_membership.update(membership_id, role_ids=role_ids)
            updated = client.project_membership.get(membership_id)
            return _membership_to_dict(updated)
        except Exception as e:
            return _handle_redmine_error(
                e,
                f"updating project membership {membership_id}",
                {"resource_type": "membership", "resource_id": membership_id},
            )

    else:  # action == "remove"
        if membership_id is None:
            return {"error": "membership_id is required for action 'remove'"}

        if _is_read_only_mode():
            return dict(_READ_ONLY_ERROR)

        await _ensure_cleanup_started()

        try:
            _get_redmine_client().project_membership.delete(membership_id)
            return {
                "success": True,
                "deleted_membership_id": membership_id,
            }
        except Exception as e:
            return _handle_redmine_error(
                e,
                f"removing project membership {membership_id}",
                {"resource_type": "membership", "resource_id": membership_id},
            )


# ---------------------------------------------------------------------------
# Project files: list, upload, delete
# ---------------------------------------------------------------------------


def _file_to_dict(file_obj: Any) -> Dict[str, Any]:
    """Convert a python-redmine File/Attachment object to a serializable dict.

    Returns standard metadata (id, filename, size, content_type, description,
    download URL, author, dates). Used by list_files and upload_file.

    ``filename`` and ``description`` are attacker-controllable (anyone who
    can upload to a project can set them). They are wrapped in
    ``<insecure-content>`` boundary tags so downstream LLMs treat them as
    untrusted data rather than instructions.
    """
    return {
        "id": getattr(file_obj, "id", None),
        "filename": wrap_insecure_content(getattr(file_obj, "filename", "")),
        "filesize": getattr(file_obj, "filesize", 0),
        "content_type": getattr(file_obj, "content_type", ""),
        "description": wrap_insecure_content(getattr(file_obj, "description", "")),
        "content_url": getattr(file_obj, "content_url", ""),
        "digest": getattr(file_obj, "digest", ""),
        "downloads": getattr(file_obj, "downloads", 0),
        "author": _named_ref(getattr(file_obj, "author", None)),
        "version": _named_ref(getattr(file_obj, "version", None)),
        "created_on": _safe_isoformat(getattr(file_obj, "created_on", None)),
    }


@mcp.tool()
async def list_files(
    project_id: Union[str, int],
) -> Union[List[Dict[str, Any]], Dict[str, Any]]:
    """List all files uploaded to a Redmine project.

    Returns file metadata (id, filename, size, content type, description,
    download URL, author, optional version/release) for every file
    uploaded under Project > Files.

    Note: This lists files from Redmine's core "Files" module (enabled per
    project via Settings > Modules > Files). It does NOT list issue
    attachments (use ``get_redmine_issue`` with ``include_attachments=True``
    for those) and does NOT list DMSF documents (pending separate tools).

    Args:
        project_id: Project identifier (numeric ID or string identifier).

    Returns:
        A list of file metadata dictionaries. On failure, a dict with an
        ``"error"`` key.

    Example:
        >>> await list_files("web")
        [
            {
                "id": 42,
                "filename": "spec.pdf",
                "filesize": 125678,
                "content_type": "application/pdf",
                "description": "Design spec v2",
                "content_url": "https://example.com/attachments/download/42/spec.pdf",
                "author": {"id": 5, "name": "Alice"},
                "version": {"id": 3, "name": "Release 1.0"},
                "created_on": "2026-04-10T10:30:00"
            }
        ]
    """
    try:
        files = _get_redmine_client().file.filter(project_id=project_id)
        return [_file_to_dict(f) for f in _iter_capped(files)]
    except Exception as e:
        return _handle_redmine_error(
            e,
            f"listing files for project {project_id}",
            {"resource_type": "project", "resource_id": project_id},
        )


def _allow_private_fetch_urls() -> bool:
    """Opt-in env flag that disables SSRF protection for `source_url`.

    Intended ONLY for development against a localhost Redmine instance or
    a localhost MCP gateway. Must never be set in production.
    """
    return _is_true_env("REDMINE_ALLOW_PRIVATE_FETCH_URLS", "false")


def _is_ip_publicly_routable(ip: ipaddress._BaseAddress) -> bool:
    """Return True if ``ip`` is publicly routable (not private/special)."""
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def _is_hostname_safe_for_fetch(
    hostname: str,
) -> Tuple[bool, Optional[str], Optional[str]]:
    """Resolve a hostname and return the first publicly routable IP.

    Rejects loopback, private, link-local (including 169.254.169.254 cloud
    metadata), reserved, multicast, and unspecified addresses to prevent SSRF.

    Returns ``(is_safe, error_message, resolved_ip)``. If safe, the caller
    SHOULD pin ``resolved_ip`` for the actual HTTP request to defeat DNS
    rebinding between our validation and httpx's own resolution.

    Error messages returned to callers are generic ("resolves to non-public
    address") and do not reveal the internal IP. The IP is logged instead
    (WARNING level) so operators can diagnose while attackers can't probe.

    Bypass for development only: ``REDMINE_ALLOW_PRIVATE_FETCH_URLS=true``.
    """
    if _allow_private_fetch_urls():
        # In dev mode, still resolve so we can pin the IP (consistency).
        try:
            addrinfo = socket.getaddrinfo(hostname, None)
            raw = addrinfo[0][4][0] if addrinfo else None
            ip_str = raw.split("%")[0] if raw and "%" in raw else raw
        except socket.gaierror:
            ip_str = None
        return True, None, ip_str

    if not hostname:
        return False, "Empty hostname in source_url.", None

    try:
        addrinfo = socket.getaddrinfo(hostname, None)
    except socket.gaierror:
        return False, f"Cannot resolve hostname '{hostname}'.", None

    if not addrinfo:
        return False, f"No addresses for hostname '{hostname}'.", None

    first_public_ip: Optional[str] = None
    for _family, _, _, _, sockaddr in addrinfo:
        ip_str = sockaddr[0]
        if "%" in ip_str:  # strip IPv6 scope ID (e.g. fe80::1%eth0)
            ip_str = ip_str.split("%")[0]
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            # Skip malformed addresses — still require at least one valid one.
            continue
        if not _is_ip_publicly_routable(ip):
            logger.warning(
                "Rejected SSRF target: %s resolved to non-public %s",
                hostname,
                ip_str,
            )
            # Fail on the first non-public hit — all resolutions must be safe
            # to avoid the attacker picking which IP httpx connects to.
            return (
                False,
                (
                    f"Refused to fetch from '{hostname}' (resolves to a "
                    "non-public address). Set "
                    "REDMINE_ALLOW_PRIVATE_FETCH_URLS=true for development only."
                ),
                None,
            )
        if first_public_ip is None:
            first_public_ip = ip_str

    if first_public_ip is None:
        return False, f"No usable public address for '{hostname}'.", None

    return True, None, first_public_ip


_CONTROL_CHAR_RE = re.compile(r"[\x00-\x1f\x7f]")


def _sanitize_filename(raw: str) -> Optional[str]:
    """Sanitize an untrusted filename from a URL path or HTTP header.

    - URL-decodes percent-encoded sequences
    - Strips any directory components (defeats `../../etc/passwd` and
      `C:\\windows\\system32\\cmd.exe` style traversal)
    - Rejects null bytes and other control characters
    - Caps length at ``_MAX_FILENAME_LEN`` (typical filesystem limit)

    Returns a safe basename, or ``None`` if the input cannot be salvaged.
    """
    if not raw:
        return None

    decoded = unquote(raw).strip().strip('"').strip("'")
    if not decoded:
        return None

    if _CONTROL_CHAR_RE.search(decoded):
        return None

    # Both os.path.basename and a manual split — different OS conventions.
    basename = os.path.basename(decoded.replace("\\", "/"))
    basename = basename.strip()
    if not basename or basename in (".", ".."):
        return None

    if len(basename) > _MAX_FILENAME_LEN:
        basename = basename[:_MAX_FILENAME_LEN]

    return basename


def _extract_content_disposition_filename(value: str) -> Optional[str]:
    """Extract a filename from a Content-Disposition header, sanitized."""
    if not value:
        return None
    # Prefer RFC 5987 filename* (e.g., filename*=UTF-8''hello.pdf)
    m = re.search(r"filename\*\s*=\s*[^']*'[^']*'([^;]+)", value, re.IGNORECASE)
    if not m:
        m = re.search(r'filename\s*=\s*"?([^";]+)"?', value, re.IGNORECASE)
    if not m:
        return None
    return _sanitize_filename(m.group(1))


def _make_pinned_client(
    hostname: Optional[str], resolved_ip: Optional[str]
) -> httpx.AsyncClient:
    """Build an httpx.AsyncClient for downloading a source_url.

    We validate the hostname via ``_is_hostname_safe_for_fetch`` on every
    hop before the request. An earlier iteration tried to pin the
    resolved IP into a custom httpx transport to defeat DNS rebinding,
    but rewriting the connect host broke TLS SNI (certs are valid for
    the hostname, not the IP) and failed for every real CDN.

    Current posture:
    - Per-hop hostname validation (hostname is resolved + checked right
      before the connect), narrowing the rebind window to microseconds.
    - Manual redirect handling with re-validation of each hop.
    - 50 MiB size cap as a blast-radius limit if a rebind slips through.

    The ``hostname`` / ``resolved_ip`` arguments are kept in the
    signature for future pinning work; they're currently unused.
    """
    _ = (hostname, resolved_ip)  # silence unused-arg linters
    return httpx.AsyncClient(timeout=_DOWNLOAD_TIMEOUT, follow_redirects=False)


def _validate_fetch_url(
    current_url: str,
) -> Tuple[Optional[Dict[str, Any]], Optional[str], Optional[str]]:
    """Validate a URL for a single download hop.

    Checks scheme, rejects embedded credentials (which would leak on
    redirect), resolves the hostname, and refuses non-public IPs.

    Returns ``(error_dict_or_None, hostname, resolved_ip)``.
    """
    parsed = urlparse(current_url)
    if parsed.scheme not in ("http", "https"):
        return (
            {"error": (f"Refused URL with unsupported scheme " f"'{parsed.scheme}'.")},
            None,
            None,
        )

    # Embedded credentials (http://user:pass@host) would leak to any
    # redirect target. Reject up front.
    if parsed.username or parsed.password:
        return (
            {"error": ("URLs with embedded credentials are not permitted.")},
            None,
            None,
        )

    hostname = parsed.hostname or ""
    safe, ssrf_err, resolved_ip = _is_hostname_safe_for_fetch(hostname)
    if not safe:
        return (
            {"error": ssrf_err or "Refused to fetch from this host."},
            None,
            None,
        )
    return None, hostname, resolved_ip


async def _download_file_url(
    source_url: str,
) -> Tuple[bytes, Optional[str], Optional[Dict[str, Any]]]:
    """Download a file from an HTTP(S) URL with SSRF + size protections.

    Defenses (in order):
    - Only http/https schemes accepted.
    - URLs with embedded credentials are refused (would leak on redirect).
    - Each URL hop is DNS-resolved and rejected if any resolved IP is
      private/loopback/link-local/reserved (blocks AWS/GCP/Azure metadata
      services, RFC1918 networks, and localhost). Override for dev only:
      ``REDMINE_ALLOW_PRIVATE_FETCH_URLS=true``.
    - Redirects are followed manually, up to ``_FILE_DOWNLOAD_MAX_REDIRECTS``
      hops, and every hop is re-validated against the SSRF filter.
    - Content-Length header is checked before streaming (fail-fast).
    - Streams response body with hard 50 MiB cap enforced mid-stream.
    - Separate connect/read/write timeouts to avoid slow-loris-style stalls.

    Note: DNS rebinding (attacker-controlled DNS returning a public IP to
    our check, then a private IP to httpx microseconds later) is a
    theoretical residual risk. Pinning the resolved IP was attempted but
    broke TLS SNI for real-world CDNs; the window between our check and
    httpx's connect is microseconds, and the 50 MiB cap bounds the
    blast-radius if a rebind does slip through.

    Returns ``(content_bytes, inferred_filename, error_dict)``:
    - On success: ``(bytes, sanitized_filename_or_None, None)``
    - On failure: ``(b"", None, {"error": "..."})``
    """

    def _err(msg: str) -> Tuple[bytes, Optional[str], Dict[str, Any]]:
        return b"", None, {"error": msg}

    current_url = source_url
    # Initial scheme + credentials check before even attempting DNS.
    parsed = urlparse(current_url)
    if parsed.scheme not in ("http", "https"):
        return _err(
            f"Unsupported URL scheme '{parsed.scheme}'. "
            "Only http:// and https:// are supported."
        )
    if parsed.username or parsed.password:
        return _err("URLs with embedded credentials are not permitted.")

    inferred: Optional[str] = None
    if parsed.path:
        inferred = _sanitize_filename(os.path.basename(parsed.path))

    redirects_followed = 0
    content_bytes = b""
    try:
        while True:
            err_dict, hostname, resolved_ip = _validate_fetch_url(current_url)
            if err_dict is not None:
                return b"", None, err_dict

            async with _make_pinned_client(
                hostname=hostname, resolved_ip=resolved_ip
            ) as hc:
                async with hc.stream("GET", current_url) as response:
                    # Follow redirects ourselves so every hop is revalidated.
                    if response.status_code in (301, 302, 303, 307, 308):
                        redirects_followed += 1
                        if redirects_followed > _FILE_DOWNLOAD_MAX_REDIRECTS:
                            return _err(
                                f"Too many redirects "
                                f"(> {_FILE_DOWNLOAD_MAX_REDIRECTS})."
                            )
                        location = response.headers.get("location", "")
                        if not location:
                            return _err(
                                f"Got redirect status {response.status_code} "
                                "with no Location header."
                            )
                        # Resolve the Location header relative to current URL.
                        current_url = str(httpx.URL(current_url).join(location))
                        continue

                    if response.status_code >= 400:
                        return _err(
                            f"Failed to fetch source_url: HTTP "
                            f"{response.status_code} {response.reason_phrase}"
                        )

                    # Fail-fast on an honest Content-Length that exceeds
                    # the cap (still enforced mid-stream if the server lies).
                    cl_header = response.headers.get("content-length")
                    if cl_header and cl_header.isdigit():
                        declared = int(cl_header)
                        if declared > _FILE_UPLOAD_MAX_SIZE_BYTES:
                            size_mb = declared / (1024 * 1024)
                            limit_mb = _FILE_UPLOAD_MAX_SIZE_BYTES / (1024 * 1024)
                            return _err(
                                f"Server declares file size {size_mb:.1f} MiB, "
                                f"exceeds {limit_mb:.0f} MiB limit."
                            )

                    # Use the server's filename only if the original URL
                    # didn't give us a usable one. Sanitize aggressively.
                    if not inferred:
                        inferred = _extract_content_disposition_filename(
                            response.headers.get("content-disposition", "")
                        )

                    buffer = io.BytesIO()
                    total = 0
                    async for chunk in response.aiter_bytes():
                        total += len(chunk)
                        if total > _FILE_UPLOAD_MAX_SIZE_BYTES:
                            size_mb = total / (1024 * 1024)
                            limit_mb = _FILE_UPLOAD_MAX_SIZE_BYTES / (1024 * 1024)
                            return _err(
                                f"Downloaded file too large: exceeds "
                                f"{limit_mb:.0f} MiB limit "
                                f"(received {size_mb:.1f} MiB so far)."
                            )
                        buffer.write(chunk)
                    content_bytes = buffer.getvalue()
                    break  # exits the redirect loop
    except httpx.TimeoutException:
        return _err(
            "Timed out fetching source_url. Check the URL or try a smaller file."
        )
    except httpx.RequestError as e:
        # Scrub the exception message — httpx can embed URLs with creds.
        safe_msg = _scrub_error_message(str(e))
        return _err(f"Failed to fetch source_url: {safe_msg}")

    if len(content_bytes) == 0:
        return _err("Downloaded content is empty. Check the source_url.")

    return content_bytes, inferred, None


@mcp.tool()
async def upload_file(
    project_id: Union[str, int],
    filename: Optional[str] = None,
    content_base64: Optional[str] = None,
    source_url: Optional[str] = None,
    description: Optional[str] = None,
    version_id: Optional[int] = None,
) -> Dict[str, Any]:
    """Upload a file to a Redmine project's Files section.

    **Content sources — provide exactly ONE of:**

    - ``source_url``: an HTTP(S) URL the server will download from.
      Use this when chaining with another MCP tool that returns a
      download URL (e.g., a Google Drive MCP's
      ``get_drive_file_download_url``), when the file is hosted on the
      public web, or when the file is served by another local MCP
      server over localhost. **Prefer this over content_base64** when a
      URL is available — no need to download-then-re-encode.
    - ``content_base64``: raw file bytes encoded as base64. Use this
      only when the caller already has the file content in memory.

    Under the hood this performs Redmine's standard two-step upload:
    ``POST /uploads.json`` to get a token, then
    ``POST /projects/{id}/files.json`` to attach it to the project.

    Args:
        project_id: Project identifier (numeric ID or string identifier).
        filename: Name the file should have in Redmine (e.g., ``spec.pdf``).
            Required when using ``content_base64``. Optional with
            ``source_url`` — if omitted, inferred from the URL path.
            Always prefer passing an explicit filename.
        content_base64: File content encoded as a base64 string. Mutually
            exclusive with ``source_url``.
        source_url: HTTP(S) URL to download the file from. Mutually
            exclusive with ``content_base64``.
        description: Optional human-readable description.
        version_id: Optional version/release ID to attach the file to
            (use ``list_redmine_versions`` to discover valid IDs).

    Returns:
        Dictionary containing the uploaded file's metadata. On failure, a
        dict with an ``"error"`` key is returned.

    Size limit:
        Uploads are capped at 50 MiB. For larger files, upload via the
        Redmine web UI.

    Examples:
        >>> # From a URL (chained from another MCP tool)
        >>> await upload_file(
        ...     project_id="web",
        ...     source_url="http://localhost:3012/attachments/abc-123",
        ...     filename="report.pdf",
        ...     description="Q2 report",
        ... )

        >>> # From base64 content
        >>> import base64
        >>> content = base64.b64encode(b"Hello world").decode("ascii")
        >>> await upload_file(
        ...     project_id="web",
        ...     filename="hello.txt",
        ...     content_base64=content,
        ... )
    """
    if _is_read_only_mode():
        return dict(_READ_ONLY_ERROR)

    # Exactly one of content_base64 / source_url must be provided.
    has_b64 = bool(content_base64)
    has_url = bool(source_url)
    if not has_b64 and not has_url:
        return {"error": "Either content_base64 or source_url must be provided."}
    if has_b64 and has_url:
        return {
            "error": ("Provide exactly ONE of content_base64 or source_url, not both.")
        }

    content_bytes: bytes

    if has_url:
        content_bytes, inferred_filename, fetch_error = await _download_file_url(
            source_url
        )
        if fetch_error is not None:
            return fetch_error
        # If caller didn't pass a filename, fall back to the URL-inferred one.
        if not filename or not filename.strip():
            filename = inferred_filename
        if not filename:
            return {
                "error": (
                    "Could not infer filename from source_url. "
                    "Please pass a filename argument."
                )
            }
    else:
        if not filename or not filename.strip():
            return {"error": "filename is required when using content_base64."}

        # Decode and validate size before any network call
        try:
            content_bytes = base64.b64decode(content_base64, validate=True)
        except (binascii.Error, ValueError) as e:
            return {"error": f"content_base64 is not valid base64. Details: {e}"}

        if len(content_bytes) == 0:
            return {"error": "Decoded file content is empty."}

        if len(content_bytes) > _FILE_UPLOAD_MAX_SIZE_BYTES:
            size_mb = len(content_bytes) / (1024 * 1024)
            limit_mb = _FILE_UPLOAD_MAX_SIZE_BYTES / (1024 * 1024)
            return {
                "error": (
                    f"File too large: {size_mb:.1f} MiB exceeds the "
                    f"{limit_mb:.0f} MiB upload limit."
                )
            }

    client = _get_redmine_client()
    try:
        # Step 1: upload raw bytes to /uploads.json, get token
        token = client.upload(io.BytesIO(content_bytes), filename=filename)["token"]

        # Step 2: create the File resource using the token
        create_params: Dict[str, Any] = {
            "project_id": project_id,
            "token": token,
            "filename": filename,
        }
        if description is not None:
            create_params["description"] = description
        if version_id is not None:
            create_params["version_id"] = version_id

        uploaded = client.file.create(**create_params)

        # Redmine returns HTTP 204 (empty body) on successful file creation,
        # so python-redmine's FileManager synthesizes a minimal response that
        # only contains the ID. Re-fetch the full attachment metadata so the
        # caller gets filename, size, content type, author, etc.
        uploaded_id = getattr(uploaded, "id", None)
        if uploaded_id is not None:
            try:
                full = client.attachment.get(uploaded_id)
                return _file_to_dict(full)
            except Exception:
                # If re-fetch fails for any reason, fall back to the minimal
                # response + the known fields we already have.
                pass
        result = _file_to_dict(uploaded)
        # Fallback enrichment when the re-fetch failed: ensure the caller at
        # least sees the filename and description they just uploaded.
        if not result.get("filename"):
            result["filename"] = filename
        if description is not None and not result.get("description"):
            result["description"] = description
        return result
    except Exception as e:
        return _handle_redmine_error(
            e,
            f"uploading file '{filename}' to project {project_id}",
            {"resource_type": "project", "resource_id": project_id},
        )


@mcp.tool()
async def delete_file(
    file_id: int,
    confirm_delete_any_attachment: bool = False,
) -> Dict[str, Any]:
    """Delete a file from a Redmine project.

    **Important:** Redmine's ``DELETE /attachments/{id}.json`` endpoint
    removes ANY attachment by ID, not just project files. If ``file_id``
    refers to an issue/wiki attachment (e.g., from
    ``get_redmine_issue(include_attachments=True)``), that attachment
    will be deleted from its issue.

    To avoid accidentally removing issue attachments when you meant to
    remove a project file, the tool verifies the target attachment is
    project-scoped (its ``container_type`` is ``Project``) before
    deleting. Pass ``confirm_delete_any_attachment=True`` to bypass this
    check when you explicitly want to delete an issue/wiki attachment.

    Args:
        file_id: ID of the attachment to delete (the ``id`` field returned
            by ``list_files`` or attachment-include responses).
        confirm_delete_any_attachment: When ``True``, skip the
            project-scope check and delete the attachment regardless of
            container type. Use only when you intentionally want to
            remove an issue/wiki/news attachment via this tool.

    Returns:
        Dictionary with ``success: true`` on success. On failure, a dict
        with an ``"error"`` key is returned.
    """
    if _is_read_only_mode():
        return dict(_READ_ONLY_ERROR)

    client = _get_redmine_client()

    if not confirm_delete_any_attachment:
        # Verify the target is a project file before deleting. Fetch the
        # attachment and check its container_type. This adds one GET but
        # prevents accidental deletion of issue attachments.
        try:
            attachment = client.attachment.get(file_id)
        except Exception as e:
            return _handle_redmine_error(
                e,
                f"verifying attachment {file_id} before delete",
                {"resource_type": "file", "resource_id": file_id},
            )

        container_type = getattr(attachment, "container_type", None)
        # Fail-closed: if container_type is missing, None, or empty (which
        # can happen on older Redmine versions), refuse the delete. The
        # caller can explicitly bypass via confirm_delete_any_attachment.
        if container_type != "Project":
            return {
                "error": (
                    f"Refusing to delete attachment {file_id}: "
                    f"container_type is {container_type!r}, not 'Project'. "
                    "If you intended to delete this attachment anyway, "
                    "re-invoke with confirm_delete_any_attachment=True."
                ),
                "attachment_id": file_id,
                "container_type": container_type,
            }

    try:
        client.attachment.delete(file_id)
        return {"success": True, "deleted_file_id": file_id}
    except Exception as e:
        return _handle_redmine_error(
            e,
            f"deleting file {file_id}",
            {"resource_type": "file", "resource_id": file_id},
        )


@mcp.tool()
async def list_time_entries(
    project_id: Optional[Union[str, int]] = None,
    issue_id: Optional[int] = None,
    user_id: Optional[Union[str, int]] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    limit: int = 25,
    offset: int = 0,
) -> Union[List[Dict[str, Any]], Dict[str, Any]]:
    """List time entries from Redmine with filtering and pagination.

    Retrieve time entries with optional filtering by project, issue, user,
    and date range. Supports pagination for handling large result sets.

    Args:
        project_id: Filter by project (ID number or string identifier).
        issue_id: Filter by issue ID.
        user_id: Filter by user ID. Use "me" for current user.
        from_date: Start date filter (YYYY-MM-DD format).
        to_date: End date filter (YYYY-MM-DD format).
        limit: Maximum number of entries to return (default: 25, max: 100).
        offset: Number of entries to skip for pagination (default: 0).

    Returns:
        A list of time entry dictionaries. On failure, a list containing
        a single dictionary with an "error" key.

    Examples:
        >>> await list_time_entries(project_id="my-project")
        [{"id": 1, "hours": 2.5, "comments": "Bug fix", ...}, ...]

        >>> await list_time_entries(issue_id=123, from_date="2024-01-01")
        [{"id": 2, "hours": 1.0, "issue": {"id": 123}, ...}, ...]

        >>> await list_time_entries(user_id="me", limit=10)
        [{"id": 3, "hours": 4.0, "user": {"id": 5, "name": "Current User"}, ...}]
    """
    try:
        # Build filter parameters
        filters: Dict[str, Any] = {
            "limit": min(limit, 100),
            "offset": offset,
        }

        if project_id is not None:
            filters["project_id"] = project_id
        if issue_id is not None:
            filters["issue_id"] = issue_id
        if user_id is not None:
            filters["user_id"] = user_id
        if from_date is not None:
            filters["from_date"] = from_date
        if to_date is not None:
            filters["to_date"] = to_date

        time_entries = _get_redmine_client().time_entry.filter(**filters)
        return [_time_entry_to_dict(te) for te in time_entries]

    except Exception as e:
        return [_handle_redmine_error(e, "listing time entries")]


@mcp.tool()
async def manage_time_entry(
    action: str,
    hours: Optional[float] = None,
    project_id: Optional[Union[str, int]] = None,
    issue_id: Optional[int] = None,
    user_id: Optional[int] = None,
    time_entry_id: Optional[int] = None,
    activity_id: Optional[int] = None,
    comments: Optional[str] = None,
    spent_on: Optional[str] = None,
) -> Dict[str, Any]:
    """Create or update a Redmine time entry.

    Args:
        action: One of: ``create``, ``update``.
        hours: Hours spent. Required for ``create``; optional for
            ``update`` (must be positive if provided).
        project_id: Project to log against. Required for ``create`` if
            ``issue_id`` is not provided.
        issue_id: Issue to log against. Required for ``create`` if
            ``project_id`` is not provided.
        user_id: Log on behalf of this user (``create`` only). Requires
            ``log_time_for_other_users`` permission.
        time_entry_id: Entry to update. Required for ``update``.
        activity_id: Activity ID (optional for both actions).
        comments: Description. Empty string clears the field on
            ``update``.
        spent_on: Date in ``YYYY-MM-DD`` format (optional).

    Returns:
        Time entry dictionary, or ``{"error": "..."}``.
    """
    _valid_actions = {"create", "update"}
    if action not in _valid_actions:
        return {"error": f"Invalid action '{action}'. Allowed: create, update"}

    if _is_read_only_mode():
        return dict(_READ_ONLY_ERROR)

    await _ensure_cleanup_started()

    if action == "create":
        if project_id is None and issue_id is None:
            return {"error": "Either project_id or issue_id must be provided."}

        hours_error = _validate_hours(hours)
        if hours_error is not None:
            return {"error": hours_error}

        if user_id is not None and not _is_positive_int(user_id):
            return {"error": "user_id must be a positive integer."}

        try:
            params: Dict[str, Any] = {"hours": hours}
            if project_id is not None:
                params["project_id"] = project_id
            if issue_id is not None:
                params["issue_id"] = issue_id
            if user_id is not None:
                params["user_id"] = user_id
            if activity_id is not None:
                params["activity_id"] = activity_id
            if comments is not None:
                params["comments"] = comments
            if spent_on is not None:
                params["spent_on"] = spent_on
            time_entry = _get_redmine_client().time_entry.create(**params)
            return _time_entry_to_dict(time_entry)
        except Exception as e:
            context = {}
            if issue_id:
                context = {"resource_type": "issue", "resource_id": issue_id}
            elif project_id:
                context = {"resource_type": "project", "resource_id": project_id}
            return _handle_redmine_error(e, "creating time entry", context)

    else:  # action == "update"
        if time_entry_id is None:
            return {"error": "time_entry_id is required for action 'update'"}

        update_params: Dict[str, Any] = {}
        if hours is not None:
            hours_error = _validate_hours(hours)
            if hours_error is not None:
                return {"error": hours_error}
            update_params["hours"] = hours
        if activity_id is not None:
            update_params["activity_id"] = activity_id
        if comments is not None:
            update_params["comments"] = comments
        if spent_on is not None:
            update_params["spent_on"] = spent_on

        if not update_params:
            return {"error": "No fields provided for update."}

        try:
            client = _get_redmine_client()
            client.time_entry.update(time_entry_id, **update_params)
            updated = client.time_entry.get(time_entry_id)
            return _time_entry_to_dict(updated)
        except Exception as e:
            return _handle_redmine_error(
                e,
                f"updating time entry {time_entry_id}",
                {"resource_type": "time entry", "resource_id": time_entry_id},
            )


@mcp.tool()
async def list_time_entry_activities(
    project_id: Optional[Union[str, int]] = None,
) -> Union[List[Dict[str, Any]], Dict[str, Any]]:
    """List available time entry activities from Redmine.

    Returns activity types that can be used when creating or updating time
    entries (e.g., Development, Design, Testing).

    When called without ``project_id``, returns all global activity types.

    When called with ``project_id``, returns project-specific activities via
    ``GET /projects/:id.json?include=time_entry_activities`` (Redmine 3.4.0+).
    Project-specific IDs differ from global ones — always use project-scoped
    activities when logging time against a specific project to avoid
    ``"Activity is not included in the list"`` errors.

    Args:
        project_id: Optional project identifier (ID number or string
            identifier). When provided, returns project-specific activities
            instead of global ones.

    Returns:
        Without ``project_id``: a list of activity dicts, each with
        ``id``, ``name``, ``active``, ``is_default``.

        With ``project_id``: a dict with ``project_id`` and ``activities``
        (same structure). If the project has no custom activities,
        ``activities`` is empty and a ``note`` field explains the fallback.

        On failure: a list containing a single dict with an ``"error"`` key.

    Examples:
        >>> await list_time_entry_activities()
        [{"id": 4, "name": "Development", "active": True, "is_default": False}, ...]

        >>> await list_time_entry_activities(project_id="my-project")
        {
            "project_id": "my-project",
            "activities": [{"id": 9, "name": "Development", ...}]
        }
    """
    if project_id is not None:
        try:
            project = _get_redmine_client().project.get(
                project_id, include="time_entry_activities"
            )
            activities = getattr(project, "time_entry_activities", None) or []
            result: Dict[str, Any] = {
                "project_id": project_id,
                "activities": [
                    {
                        "id": getattr(a, "id", None),
                        "name": getattr(a, "name", None),
                        "active": getattr(a, "active", None),
                        "is_default": getattr(a, "is_default", None),
                    }
                    for a in activities
                ],
            }
            if not result["activities"]:
                result["note"] = (
                    "No project-specific activities configured. "
                    "Use list_time_entry_activities for global activities."
                )
            return result
        except Exception as e:
            return [
                _handle_redmine_error(
                    e,
                    f"listing time entry activities for project {project_id}",
                    {"resource_type": "project", "resource_id": project_id},
                )
            ]

    try:
        activities = _get_redmine_client().enumeration.filter(
            resource="time_entry_activities"
        )
        return [
            {
                "id": getattr(a, "id", None),
                "name": getattr(a, "name", None),
                "active": getattr(a, "active", None),
                "is_default": getattr(a, "is_default", None),
            }
            for a in activities
        ]

    except Exception as e:
        return [_handle_redmine_error(e, "listing time entry activities")]


# ---------------------------------------------------------------------------
# Discovery / enumeration tools
#
# These help LLMs find valid IDs (trackers, statuses, priorities, users,
# saved queries) without guessing. Call these BEFORE create/update tools
# that require the corresponding ID.
# ---------------------------------------------------------------------------


@mcp.tool()
async def list_redmine_trackers() -> Union[List[Dict[str, Any]], Dict[str, Any]]:
    """List all trackers (issue types) defined in the Redmine instance.

    Trackers classify issues (e.g., Bug, Feature, Support). Use this tool
    to discover valid ``tracker_id`` values before calling
    ``create_redmine_issue`` or ``update_redmine_issue``.

    Returns:
        A list of tracker dictionaries with ``id``, ``name``, and
        ``description``. On failure, a dict with an ``"error"`` key.

    Example:
        >>> await list_redmine_trackers()
        [
            {"id": 1, "name": "Bug", "description": ""},
            {"id": 2, "name": "Feature", "description": ""},
            {"id": 3, "name": "Support", "description": ""}
        ]
    """
    try:
        trackers = _get_redmine_client().tracker.all()
        return [
            {
                "id": getattr(t, "id", None),
                "name": getattr(t, "name", ""),
                "description": getattr(t, "description", ""),
            }
            for t in trackers
        ]
    except Exception as e:
        return _handle_redmine_error(e, "listing trackers")


@mcp.tool()
async def list_redmine_issue_statuses() -> Union[List[Dict[str, Any]], Dict[str, Any]]:
    """List all issue statuses defined in the Redmine instance.

    Use this tool to discover valid ``status_id`` values before calling
    ``update_redmine_issue``. You can also pass a status name via the
    ``status_name`` field in ``update_redmine_issue``, which internally
    resolves the ID.

    Returns:
        A list of status dictionaries with ``id``, ``name``, and
        ``is_closed`` (whether this status counts as "closed"). On
        failure, a dict with an ``"error"`` key.

    Example:
        >>> await list_redmine_issue_statuses()
        [
            {"id": 1, "name": "New", "is_closed": False},
            {"id": 2, "name": "In Progress", "is_closed": False},
            {"id": 5, "name": "Closed", "is_closed": True}
        ]
    """
    try:
        statuses = _get_redmine_client().issue_status.all()
        return [
            {
                "id": getattr(s, "id", None),
                "name": getattr(s, "name", ""),
                "is_closed": bool(getattr(s, "is_closed", False)),
            }
            for s in statuses
        ]
    except Exception as e:
        return _handle_redmine_error(e, "listing issue statuses")


@mcp.tool()
async def list_redmine_issue_priorities() -> (
    Union[List[Dict[str, Any]], Dict[str, Any]]
):
    """List all issue priority levels defined in the Redmine instance.

    Use this tool to discover valid ``priority_id`` values before calling
    ``create_redmine_issue`` or ``update_redmine_issue``.

    Returns:
        A list of priority dictionaries with ``id``, ``name``,
        ``active``, and ``is_default``. On failure, a dict with an
        ``"error"`` key.

    Example:
        >>> await list_redmine_issue_priorities()
        [
            {"id": 1, "name": "Low", "active": True, "is_default": False},
            {"id": 2, "name": "Normal", "active": True, "is_default": True},
            {"id": 3, "name": "High", "active": True, "is_default": False}
        ]
    """
    try:
        priorities = _get_redmine_client().enumeration.filter(
            resource="issue_priorities"
        )
        return [
            {
                "id": getattr(p, "id", None),
                "name": getattr(p, "name", ""),
                "active": getattr(p, "active", None),
                "is_default": getattr(p, "is_default", None),
            }
            for p in priorities
        ]
    except Exception as e:
        return _handle_redmine_error(e, "listing issue priorities")


@mcp.tool()
async def list_redmine_users(
    name: Optional[str] = None,
    group_id: Optional[int] = None,
    limit: int = 25,
    offset: int = 0,
) -> Union[List[Dict[str, Any]], Dict[str, Any]]:
    """List Redmine users with optional filtering.

    Admin permission is required to list all users. Non-admin users may
    receive a 403. Use this tool to discover valid user IDs (e.g., for
    assignment, watchers, or time-entry authoring).

    Args:
        name: Optional case-insensitive substring to filter by (matches
            against login, firstname, lastname, and email).
        group_id: Optional group ID to filter users who belong to a
            specific group.
        limit: Maximum users to return (default 25, max 100).
        offset: Pagination offset. Default 0.

    Returns:
        A list of user dictionaries with ``id``, ``login``, ``firstname``,
        ``lastname``, ``mail`` (if visible), and ``created_on``. On
        failure, a dict with an ``"error"`` key.

    Example:
        >>> await list_redmine_users(name="alice")
        [{"id": 5, "login": "alice", "firstname": "Alice", ...}]
    """
    try:
        params: Dict[str, Any] = {"limit": max(1, min(limit, 100)), "offset": offset}
        if name:
            params["name"] = name
        if group_id is not None:
            params["group_id"] = group_id

        users = _get_redmine_client().user.filter(**params)
        return [
            {
                "id": getattr(u, "id", None),
                "login": getattr(u, "login", ""),
                "firstname": getattr(u, "firstname", ""),
                "lastname": getattr(u, "lastname", ""),
                "mail": getattr(u, "mail", ""),
                "created_on": _safe_isoformat(getattr(u, "created_on", None)),
            }
            for u in users
        ]
    except Exception as e:
        return _handle_redmine_error(e, "listing users")


@mcp.tool()
async def get_current_user() -> Dict[str, Any]:
    """Retrieve the currently authenticated user's profile.

    Resolves to ``GET /my/account.json`` under the hood. Works for any
    authenticated user (not admin-only). Useful when an LLM needs to
    identify "me" — for example, when a user says "log 2h on this issue
    for me", the LLM can call this tool to get the current user's ID.

    Returns:
        A dictionary with ``id``, ``login``, ``firstname``, ``lastname``,
        ``mail``, ``admin`` (bool), ``created_on``, and ``last_login_on``.
        On failure, a dict with an ``"error"`` key.

    Example:
        >>> await get_current_user()
        {"id": 5, "login": "alice", "firstname": "Alice", ..., "admin": False}
    """
    try:
        user = _get_redmine_client().user.get("current")
        return {
            "id": getattr(user, "id", None),
            "login": getattr(user, "login", ""),
            "firstname": getattr(user, "firstname", ""),
            "lastname": getattr(user, "lastname", ""),
            "mail": getattr(user, "mail", ""),
            "admin": bool(getattr(user, "admin", False)),
            "created_on": _safe_isoformat(getattr(user, "created_on", None)),
            "last_login_on": _safe_isoformat(getattr(user, "last_login_on", None)),
        }
    except Exception as e:
        return _handle_redmine_error(e, "fetching current user")


@mcp.tool()
async def list_redmine_queries() -> Union[List[Dict[str, Any]], Dict[str, Any]]:
    """List all saved custom queries visible to the current user.

    Custom queries are saved issue filters (defined via the Redmine web
    UI). Once discovered, the ``id`` can be passed to
    ``list_redmine_issues`` via a ``query_id`` filter to run the query.

    Note: This tool only READS queries. Redmine's REST API does not
    support creating, updating, or deleting saved queries.

    Returns:
        A list of query dictionaries with ``id``, ``name``,
        ``is_public``, and ``project_id`` (may be ``None`` for
        cross-project queries). On failure, a dict with an ``"error"``
        key.

    Example:
        >>> await list_redmine_queries()
        [
            {"id": 1, "name": "Open bugs", "is_public": True, "project_id": 10},
            {"id": 2, "name": "My tasks", "is_public": False, "project_id": None}
        ]
    """
    try:
        queries = _get_redmine_client().query.all()
        return [
            {
                "id": getattr(q, "id", None),
                "name": getattr(q, "name", ""),
                "is_public": bool(getattr(q, "is_public", False)),
                "project_id": getattr(q, "project_id", None),
            }
            for q in _iter_capped(queries)
        ]
    except Exception as e:
        return _handle_redmine_error(e, "listing saved queries")


@mcp.tool()
async def import_time_entries(
    entries: Union[List[Dict[str, Any]], str],
    stop_on_error: bool = False,
) -> Dict[str, Any]:
    """Bulk import multiple time entries in a single call.

    **Use this tool (NOT ``manage_time_entry(action="create")`` in a loop) whenever the
    user asks to:**
        - import a timesheet / weekly timesheet / monthly report
        - bulk log, batch log, or log multiple entries at once
        - import several entries, or any list of 2+ time entries
        - backfill time across many issues or dates
        - log the same activity for multiple team members at once
        - log a day's work spanning multiple issues

    **Prefer this tool over calling ``manage_time_entry(action="create")``
    N times** -- it reports partial failures via a
    ``succeeded``/``failed`` summary and supports ``stop_on_error`` for
    transactional-style behaviour. Calling
    ``manage_time_entry(action="create")`` in a loop gives no aggregate
    feedback and cannot continue past per-entry errors gracefully.

    Redmine has no native bulk-import endpoint, so this tool creates each
    entry individually via ``POST /time_entries.json`` under the hood.
    Per-entry errors are captured and returned alongside successes so a
    partial import still yields useful feedback.

    Each entry must be a dict (or JSON object) with the standard
    ``manage_time_entry(action="create")`` fields: ``hours`` (required),
    plus at least one of ``project_id``/``issue_id``. Optional fields:
    ``user_id`` (to log on behalf of a teammate), ``activity_id``,
    ``comments``, ``spent_on``.

    Args:
        entries: List of time entry dicts, OR a JSON array string. Capped
            at 500 entries per call — split larger imports into multiple
            invocations.
            Example: ``[{"hours": 1.5, "issue_id": 123, "comments": "..."}]``
        stop_on_error: When ``True``, abort the import on the first error.
            When ``False`` (default), continue past errors and report all
            successes/failures at the end.

    Returns:
        Dictionary with:
            - ``total``: total number of entries attempted
            - ``succeeded``: count of successfully created entries
            - ``failed``: count of failed entries
            - ``created``: list of created time entry dicts
            - ``errors``: list of ``{"index": i, "entry": {...}, "error": "..."}``
              for failed entries

    Example:
        >>> await import_time_entries([
        ...     {"hours": 2.0, "issue_id": 123, "comments": "Bug fix"},
        ...     {"hours": 1.0, "project_id": "web", "activity_id": 9},
        ... ])
        {"total": 2, "succeeded": 2, "failed": 0, "created": [...], "errors": []}
    """
    if _is_read_only_mode():
        return dict(_READ_ONLY_ERROR)

    # Parse input: accept either a list or a JSON array string.
    if isinstance(entries, str):
        try:
            parsed = json.loads(entries.strip())
        except Exception as e:
            return {
                "error": (
                    "Invalid entries payload. Expected a list of dicts or "
                    "a JSON array string."
                ),
                "details": str(e),
            }
        entries_list = parsed
    else:
        entries_list = entries

    if not isinstance(entries_list, list):
        return {
            "error": (
                "entries must be a list of time entry dicts, not "
                f"{type(entries_list).__name__}."
            )
        }

    if len(entries_list) > _IMPORT_TIME_ENTRIES_MAX_BATCH:
        return {
            "error": (
                f"Too many entries: {len(entries_list)} exceeds the "
                f"{_IMPORT_TIME_ENTRIES_MAX_BATCH}-per-call batch cap. "
                "Split the import into multiple calls."
            )
        }

    if not entries_list:
        return {
            "total": 0,
            "succeeded": 0,
            "failed": 0,
            "created": [],
            "errors": [],
        }

    created: List[Dict[str, Any]] = []
    errors: List[Dict[str, Any]] = []
    client = _get_redmine_client()

    for index, entry in enumerate(entries_list):
        # Yield to the event loop between synchronous HTTP calls so other
        # MCP requests (e.g., a status check) aren't starved during a
        # large import.
        if index > 0:
            await asyncio.sleep(0)
        if not isinstance(entry, dict):
            errors.append(
                {
                    "index": index,
                    "entry": entry,
                    "error": f"Entry at index {index} is not a dict.",
                }
            )
            if stop_on_error:
                break
            continue

        # Per-entry validation
        hours = entry.get("hours")
        hours_error = (
            _validate_hours(hours) if hours is not None else "hours is required."
        )
        if hours_error is not None:
            errors.append(
                {
                    "index": index,
                    "entry": entry,
                    "error": hours_error,
                }
            )
            if stop_on_error:
                break
            continue

        if entry.get("project_id") is None and entry.get("issue_id") is None:
            errors.append(
                {
                    "index": index,
                    "entry": entry,
                    "error": "Either project_id or issue_id is required.",
                }
            )
            if stop_on_error:
                break
            continue

        # Build create params — pass through only whitelisted keys
        allowed_keys = {
            "hours",
            "user_id",
            "project_id",
            "issue_id",
            "activity_id",
            "comments",
            "spent_on",
        }
        params = {k: v for k, v in entry.items() if k in allowed_keys and v is not None}

        # Separate the create from the serialization so a serialization
        # bug doesn't flip a successful create into a reported failure
        # (which would tempt callers to retry and create a duplicate).
        try:
            time_entry = client.time_entry.create(**params)
        except Exception as e:
            errors.append(
                {
                    "index": index,
                    "entry": entry,
                    "error": _scrub_error_message(str(e)),
                }
            )
            if stop_on_error:
                break
            continue

        try:
            created.append(_time_entry_to_dict(time_entry))
        except Exception as ser_err:
            logger.warning(
                "Serialization failed for time_entry at index %s: %s",
                index,
                ser_err,
            )
            # Record a minimal success marker so the caller knows the
            # entry exists, without marking it as failed.
            created.append(
                {
                    "id": getattr(time_entry, "id", None),
                    "warning": "serialization failed; entry was created",
                }
            )

    return {
        "total": len(entries_list),
        "succeeded": len(created),
        "failed": len(errors),
        "created": created,
        "errors": errors,
    }


# ---------------------------------------------------------------------------
# Checklist tools (requires RedmineUP Checklists plugin)
# ---------------------------------------------------------------------------


@mcp.tool()
async def get_checklist(issue_id: int) -> Dict[str, Any]:
    """Retrieve all checklist items for a Redmine issue.

    Requires the RedmineUP Checklists plugin and
    ``REDMINE_CHECKLISTS_ENABLED=true``.

    Args:
        issue_id: The ID of the issue whose checklist to retrieve.

    Returns:
        A dictionary with an ``items`` list of checklist item dicts,
        each containing ``id``, ``subject``, ``is_done``, ``position``,
        ``created_at``, and ``updated_at``. Also includes ``total_count``.
        Returns an error dict if the plugin is disabled or on failure.
    """
    if not _is_checklists_enabled():
        return {
            "error": (
                "Checklist support is disabled. "
                "Set REDMINE_CHECKLISTS_ENABLED=true to enable it."
            )
        }

    if not _is_positive_int(issue_id):
        return {"error": "issue_id must be a positive integer."}

    try:
        items = _fetch_checklist_items(issue_id)
        return {
            "issue_id": issue_id,
            "total_count": len(items),
            "items": items,
        }
    except Exception as e:
        return _handle_redmine_error(
            e,
            f"fetching checklist for issue {issue_id}",
            {"resource_type": "checklist", "resource_id": issue_id},
        )


@mcp.tool()
async def update_checklist_item(
    checklist_item_id: int,
    subject: Optional[str] = None,
    is_done: Optional[bool] = None,
    position: Optional[int] = None,
) -> Dict[str, Any]:
    """Update a checklist item's text, done state, or position.

    Requires the RedmineUP Checklists plugin and
    ``REDMINE_CHECKLISTS_ENABLED=true``. This is a write operation and
    is blocked when ``REDMINE_MCP_READ_ONLY=true``.

    Args:
        checklist_item_id: The ID of the checklist item to update.
        subject: New text for the checklist item (optional).
        is_done: New done state (optional).
        position: New position/order (optional).

    Returns:
        A success dict with the updated fields, or an error dict on failure.
    """
    if _is_read_only_mode():
        return dict(_READ_ONLY_ERROR)

    if not _is_checklists_enabled():
        return {
            "error": (
                "Checklist support is disabled. "
                "Set REDMINE_CHECKLISTS_ENABLED=true to enable it."
            )
        }

    if not _is_positive_int(checklist_item_id):
        return {"error": "checklist_item_id must be a positive integer."}

    updates: Dict[str, Any] = {}
    if subject is not None:
        updates["subject"] = subject
    if is_done is not None:
        if not isinstance(is_done, bool):
            return {"error": "is_done must be a boolean."}
        updates["is_done"] = is_done
    if position is not None:
        if not _is_positive_int(position):
            return {"error": "position must be a positive integer."}
        updates["position"] = position

    if not updates:
        return {
            "error": (
                "No fields to update. Provide at least one of: "
                "subject, is_done, position."
            )
        }

    try:
        _update_checklist_item_api(checklist_item_id, updates)
        return {
            "success": True,
            "checklist_item_id": checklist_item_id,
            "updated_fields": list(updates.keys()),
        }
    except Exception as e:
        return _handle_redmine_error(
            e,
            f"updating checklist item {checklist_item_id}",
            {"resource_type": "checklist_item", "resource_id": checklist_item_id},
        )


# ---------------------------------------------------------------------------
# Products tools (requires RedmineUP Products plugin)
# ---------------------------------------------------------------------------


@mcp.tool()
async def manage_product(
    action: str,
    project_id: Optional[Union[str, int]] = None,
    limit: int = 100,
    product_id: Optional[int] = None,
    name: Optional[str] = None,
    status_id: int = 1,
    description: Optional[str] = None,
    price: Optional[float] = None,
    currency: Optional[str] = None,
    code: Optional[str] = None,
    category_id: Optional[int] = None,
    tag_list: Optional[str] = None,
    custom_fields: Optional[List[Dict[str, Any]]] = None,
    fields: Optional[Dict[str, Any]] = None,
) -> Union[List[Dict[str, Any]], Dict[str, Any]]:
    """RedmineUP Products plugin tool. Combined CRUD-by-action.

    Actions: ``list``, ``get``, ``create``, ``update``.
    Requires ``REDMINE_PRODUCTS_ENABLED=true`` and the RedmineUP Products
    plugin.
    """
    if not _is_products_enabled():
        return dict(_PRODUCTS_DISABLED_ERROR)

    _valid_actions = {"list", "get", "create", "update"}
    if action not in _valid_actions:
        return {
            "error": (
                f"Invalid action '{action}'. " f"Allowed: {sorted(_valid_actions)}"
            )
        }

    if action == "list":
        if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
            return {"error": "limit must be a positive integer."}
        limit = min(limit, _REDMINE_API_PAGE_CAP)
        if project_id is not None and not _is_valid_project_id(project_id):
            return {
                "error": (
                    "project_id must be a non-empty string identifier or "
                    "positive integer."
                )
            }
        try:
            client = _get_redmine_client()
            url = (
                f"{REDMINE_URL}/projects/{project_id}/products.json"
                if project_id is not None
                else f"{REDMINE_URL}/products.json"
            )
            payload = client.engine.request("get", url, params={"limit": limit})
            raw = payload.get("products", []) if isinstance(payload, dict) else []
            return [_product_to_dict(p) for p in raw[:limit]]
        except Exception as e:
            return _handle_redmine_error(
                e,
                f"listing products (project_id={project_id})",
                {"resource_type": "products", "resource_id": project_id},
            )

    if action == "get":
        if not _is_positive_int(product_id):
            return {"error": "product_id must be a positive integer."}
        try:
            client = _get_redmine_client()
            url = f"{REDMINE_URL}/products/{product_id}.json"
            payload = client.engine.request("get", url)
            product = payload.get("product", {}) if isinstance(payload, dict) else {}
            if not product:
                return {"error": f"Product {product_id} not found."}
            return _product_to_dict(product)
        except Exception as e:
            return _handle_redmine_error(
                e,
                f"fetching product {product_id}",
                {"resource_type": "product", "resource_id": product_id},
            )

    # write actions below
    if _is_read_only_mode():
        return dict(_READ_ONLY_ERROR)
    await _ensure_cleanup_started()

    if action == "create":
        if not isinstance(name, str) or not name.strip():
            return {"error": "name must be a non-empty string."}
        if isinstance(status_id, bool) or status_id not in (1, 2):
            return {"error": "status_id must be 1 (Active) or 2 (Inactive)."}
        body: Dict[str, Any] = {"name": name, "status_id": status_id}
        if project_id is not None:
            body["project_id"] = project_id
        if description is not None:
            body["description"] = description
        if price is not None:
            body["price"] = price
        if currency is not None:
            body["currency"] = currency
        if code is not None:
            body["code"] = code
        if category_id is not None:
            if not _is_positive_int(category_id):
                return {"error": "category_id must be a positive integer."}
            body["category_id"] = category_id
        if tag_list is not None:
            body["tag_list"] = tag_list
        if custom_fields is not None:
            body["custom_fields"] = custom_fields
        try:
            client = _get_redmine_client()
            url = f"{REDMINE_URL}/products.json"
            payload = client.engine.request(
                "post",
                url,
                headers={"Content-Type": "application/json"},
                data=json.dumps({"product": body}),
            )
            product = payload.get("product", {}) if isinstance(payload, dict) else {}
            return _product_to_dict(product) if product else {"success": True}
        except Exception as e:
            return _handle_redmine_error(
                e,
                f"creating product '{name}'",
                {"resource_type": "product", "resource_id": name},
            )

    # action == "update"
    if not _is_positive_int(product_id):
        return {"error": "product_id must be a positive integer."}
    if not isinstance(fields, dict) or not fields:
        return {"error": "fields must be a non-empty dict."}
    filtered = {k: v for k, v in fields.items() if k in _PRODUCT_WRITABLE_FIELDS}
    if not filtered:
        return {
            "error": (
                "No writable fields provided. Allowed fields: "
                f"{sorted(_PRODUCT_WRITABLE_FIELDS)}"
            )
        }
    try:
        client = _get_redmine_client()
        url = f"{REDMINE_URL}/products/{product_id}.json"
        client.engine.request(
            "put",
            url,
            headers={"Content-Type": "application/json"},
            data=json.dumps({"product": filtered}),
        )
        return {
            "success": True,
            "product_id": product_id,
            "updated_fields": list(filtered.keys()),
        }
    except Exception as e:
        return _handle_redmine_error(
            e,
            f"updating product {product_id}",
            {"resource_type": "product", "resource_id": product_id},
        )


# ---------------------------------------------------------------------------
# Gantt tool (composite — uses core REST API only, no plugin required)
# ---------------------------------------------------------------------------


def _gantt_issue_to_dict(issue: Any) -> Dict[str, Any]:
    """Serialize an issue for Gantt output.

    Includes scheduling fields (``start_date``, ``due_date``, ``done_ratio``,
    ``estimated_hours``, ``parent``) that ``_issue_to_dict`` omits, plus
    relations when present.
    """
    parent = getattr(issue, "parent", None)
    parent_id: Optional[int] = None
    if parent is not None:
        parent_id = getattr(parent, "id", None)

    out: Dict[str, Any] = {
        "id": getattr(issue, "id", None),
        "subject": wrap_insecure_content(getattr(issue, "subject", "")),
        "tracker": _named_ref(getattr(issue, "tracker", None)),
        "status": _named_ref(getattr(issue, "status", None)),
        "assigned_to": _named_ref(getattr(issue, "assigned_to", None)),
        "start_date": _safe_isoformat(getattr(issue, "start_date", None)),
        "due_date": _safe_isoformat(getattr(issue, "due_date", None)),
        "done_ratio": getattr(issue, "done_ratio", 0),
        "estimated_hours": getattr(issue, "estimated_hours", None),
        "parent_id": parent_id,
    }

    rel_list: List[Dict[str, Any]] = []
    relations = getattr(issue, "relations", None)
    if relations is not None:
        for rel in _iter_capped(relations):
            rel_type = getattr(rel, "relation_type", None)
            if rel_type not in {"precedes", "blocks"}:
                continue
            rel_list.append(
                {
                    "id": getattr(rel, "id", None),
                    "relation_type": rel_type,
                    "issue_id": getattr(rel, "issue_id", None),
                    "issue_to_id": getattr(rel, "issue_to_id", None),
                    "delay": getattr(rel, "delay", None),
                }
            )
    out["relations"] = rel_list
    return out


def _gantt_version_to_dict(version: Any) -> Dict[str, Any]:
    return {
        "id": getattr(version, "id", None),
        "name": wrap_insecure_content(getattr(version, "name", "")),
        "due_date": _safe_isoformat(getattr(version, "due_date", None)),
        "status": getattr(version, "status", None),
    }


@mcp.tool()
async def get_gantt_chart(
    project_id: Union[str, int],
    start_date_after: Optional[str] = None,
    due_date_before: Optional[str] = None,
    include_closed: bool = False,
    limit: int = 250,
) -> Dict[str, Any]:
    """Retrieve project timeline (Gantt) data: issues with dates, dependencies,
    and milestones.

    Composite tool that aggregates ``GET /issues.json`` (with relations) and
    ``GET /projects/{id}/versions.json`` into a single structured response
    suitable for timeline analysis. Returns structured data, not an image.

    Use cases: "What's the current timeline for project X?", "Which issues
    are overdue?", "Show me the dependency chain on this project".

    Uses the core Redmine REST API only — no plugin required.

    Performance note: Redmine paginates issues at 25 per HTTP call by
    default, so a request for ``limit=500`` can trigger ~20 underlying
    API calls. Expect a few seconds of latency on large projects.

    Args:
        project_id: Project identifier (ID or string).
        start_date_after: Optional ``YYYY-MM-DD`` filter (issues whose
            ``start_date`` is on or after this date).
        due_date_before: Optional ``YYYY-MM-DD`` filter (issues whose
            ``due_date`` is on or before this date).
        include_closed: When ``True``, include closed issues. Default
            ``False``: only open issues are returned, which keeps response
            size and pagination cost low on long-lived projects.
        limit: Maximum number of issues to return (1-500, default 250).

    Returns:
        Dict with: ``project_id``, ``issues`` (list with date fields,
        progress, parent_id, relations), ``versions`` (list of milestones),
        ``total_count``.
    """
    if not _is_valid_project_id(project_id):
        return {
            "error": (
                "project_id must be a non-empty string identifier or "
                "positive integer."
            )
        }
    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
        return {"error": "limit must be a positive integer."}
    limit = min(limit, _DEFAULT_LIST_RESULT_CAP)

    try:
        client = _get_redmine_client()

        issue_filters: Dict[str, Any] = {
            "project_id": project_id,
            "include": "relations",
        }
        if include_closed:
            issue_filters["status_id"] = "*"
        if start_date_after:
            issue_filters["start_date"] = f">={start_date_after}"
        if due_date_before:
            issue_filters["due_date"] = f"<={due_date_before}"

        issues_resource = client.issue.filter(**issue_filters)
        issues_list = [
            _gantt_issue_to_dict(i) for i in _iter_capped(issues_resource, limit)
        ]

        try:
            versions_resource = client.version.filter(project_id=project_id)
            versions_list = [
                _gantt_version_to_dict(v) for v in _iter_capped(versions_resource)
            ]
        except Exception:
            versions_list = []

        return {
            "project_id": project_id,
            "total_count": len(issues_list),
            "issues": issues_list,
            "versions": versions_list,
        }
    except Exception as e:
        return _handle_redmine_error(
            e,
            f"fetching Gantt data for project {project_id}",
            {"resource_type": "gantt", "resource_id": project_id},
        )


# ---------------------------------------------------------------------------
# Contacts tools (requires RedmineUP CRM plugin)
# ---------------------------------------------------------------------------


@mcp.tool()
async def manage_contact(
    action: str,
    project_id: Optional[Union[str, int]] = None,
    search: Optional[str] = None,
    tags: Optional[str] = None,
    assigned_to_id: Optional[int] = None,
    limit: int = 100,
    contact_id: Optional[int] = None,
    include: Optional[str] = None,
    first_name: Optional[str] = None,
    last_name: Optional[str] = None,
    company: Optional[str] = None,
    email: Optional[str] = None,
    phone: Optional[str] = None,
    is_company: bool = False,
    visibility: int = 0,
    fields: Optional[Dict[str, Any]] = None,
) -> Union[List[Dict[str, Any]], Dict[str, Any]]:
    """RedmineUP CRM (Contacts) plugin tool. Combined CRUD-by-action.

    Actions: ``list``, ``get``, ``create``, ``update``, ``delete``,
    ``assign_to_project``, ``remove_from_project``.

    Requires ``REDMINE_CRM_ENABLED=true`` and the RedmineUP CRM plugin.
    """
    if not _is_crm_enabled():
        return dict(_CRM_DISABLED_ERROR)

    _valid_actions = {
        "list",
        "get",
        "create",
        "update",
        "delete",
        "assign_to_project",
        "remove_from_project",
    }
    if action not in _valid_actions:
        return {
            "error": (
                f"Invalid action '{action}'. " f"Allowed: {sorted(_valid_actions)}"
            )
        }

    # --- read actions ---

    if action == "list":
        if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
            return {"error": "limit must be a positive integer."}
        limit = min(limit, _REDMINE_API_PAGE_CAP)
        if project_id is not None and not _is_valid_project_id(project_id):
            return {
                "error": (
                    "project_id must be a non-empty string identifier or "
                    "positive integer."
                )
            }
        params: Dict[str, Any] = {"limit": limit}
        if project_id is not None:
            params["project_id"] = project_id
        if search is not None:
            params["search"] = search
        if tags is not None:
            params["tags"] = tags
        if assigned_to_id is not None:
            if not _is_positive_int(assigned_to_id):
                return {"error": "assigned_to_id must be a positive integer."}
            params["assigned_to_id"] = assigned_to_id
        try:
            client = _get_redmine_client()
            url = f"{REDMINE_URL}/contacts.json"
            payload = client.engine.request("get", url, params=params)
            raw = payload.get("contacts", []) if isinstance(payload, dict) else []
            return [_contact_to_dict(c) for c in raw[:limit]]
        except Exception as e:
            return _handle_redmine_error(
                e, "listing contacts", {"resource_type": "contacts"}
            )

    if action == "get":
        if not _is_positive_int(contact_id):
            return {"error": "contact_id must be a positive integer."}
        try:
            client = _get_redmine_client()
            url = f"{REDMINE_URL}/contacts/{contact_id}.json"
            params = {}
            if include:
                params["include"] = include
            payload = client.engine.request("get", url, params=params)
            contact = payload.get("contact", {}) if isinstance(payload, dict) else {}
            if not contact:
                return {"error": f"Contact {contact_id} not found."}
            return _contact_to_dict(contact)
        except Exception as e:
            return _handle_redmine_error(
                e,
                f"fetching contact {contact_id}",
                {"resource_type": "contact", "resource_id": contact_id},
            )

    # --- write actions ---
    if _is_read_only_mode():
        return dict(_READ_ONLY_ERROR)
    await _ensure_cleanup_started()

    if action == "create":
        if not _is_valid_project_id(project_id):
            return {
                "error": (
                    "project_id is required and must be a non-empty string "
                    "identifier or positive integer."
                )
            }
        if not isinstance(first_name, str) or not first_name.strip():
            return {"error": "first_name must be a non-empty string."}
        if not isinstance(is_company, bool):
            return {"error": "is_company must be a boolean."}
        if visibility not in (0, 1, 2):
            return {
                "error": "visibility must be 0 (Project), 1 (Public), or 2 (Private)."
            }
        body: Dict[str, Any] = {
            "project_id": project_id,
            "first_name": first_name,
            "is_company": is_company,
            "visibility": visibility,
        }
        if last_name is not None:
            body["last_name"] = last_name
        if company is not None:
            body["company"] = company
        if email is not None:
            body["email"] = email
        if phone is not None:
            body["phone"] = phone
        if fields:
            for k, v in fields.items():
                if k in _CONTACT_WRITABLE_FIELDS:
                    body[k] = v
        try:
            client = _get_redmine_client()
            url = f"{REDMINE_URL}/contacts.json"
            payload = client.engine.request(
                "post",
                url,
                headers={"Content-Type": "application/json"},
                data=json.dumps({"contact": body}),
            )
            contact = payload.get("contact", {}) if isinstance(payload, dict) else {}
            return _contact_to_dict(contact) if contact else {"success": True}
        except Exception as e:
            return _handle_redmine_error(
                e, "creating contact", {"resource_type": "contact"}
            )

    if action == "update":
        if not _is_positive_int(contact_id):
            return {"error": "contact_id must be a positive integer."}
        if not isinstance(fields, dict) or not fields:
            return {"error": "fields must be a non-empty dict."}
        filtered = {k: v for k, v in fields.items() if k in _CONTACT_WRITABLE_FIELDS}
        if not filtered:
            return {
                "error": (
                    "No writable fields provided. Allowed fields: "
                    f"{sorted(_CONTACT_WRITABLE_FIELDS)}"
                )
            }
        try:
            client = _get_redmine_client()
            url = f"{REDMINE_URL}/contacts/{contact_id}.json"
            client.engine.request(
                "put",
                url,
                headers={"Content-Type": "application/json"},
                data=json.dumps({"contact": filtered}),
            )
            return {
                "success": True,
                "contact_id": contact_id,
                "updated_fields": list(filtered.keys()),
            }
        except Exception as e:
            return _handle_redmine_error(
                e,
                f"updating contact {contact_id}",
                {"resource_type": "contact", "resource_id": contact_id},
            )

    if action == "delete":
        if not _is_positive_int(contact_id):
            return {"error": "contact_id must be a positive integer."}
        try:
            client = _get_redmine_client()
            url = f"{REDMINE_URL}/contacts/{contact_id}.json"
            client.engine.request("delete", url)
            return {
                "success": True,
                "contact_id": contact_id,
                "message": f"Contact {contact_id} deleted.",
            }
        except Exception as e:
            return _handle_redmine_error(
                e,
                f"deleting contact {contact_id}",
                {"resource_type": "contact", "resource_id": contact_id},
            )

    # action in {"assign_to_project", "remove_from_project"}
    if not _is_positive_int(contact_id):
        return {"error": "contact_id must be a positive integer."}
    if not _is_valid_project_id(project_id):
        return {
            "error": (
                "project_id must be a non-empty string identifier or "
                "positive integer."
            )
        }

    if action == "assign_to_project":
        try:
            client = _get_redmine_client()
            url = f"{REDMINE_URL}/contacts/{contact_id}/projects.json"
            client.engine.request(
                "post",
                url,
                headers={"Content-Type": "application/json"},
                data=json.dumps({"project": {"id": project_id}}),
            )
            return {
                "success": True,
                "contact_id": contact_id,
                "project_id": project_id,
            }
        except Exception as e:
            return _handle_redmine_error(
                e,
                f"assigning contact {contact_id} to project {project_id}",
                {"resource_type": "contact", "resource_id": contact_id},
            )

    # action == "remove_from_project"
    try:
        client = _get_redmine_client()
        url = f"{REDMINE_URL}/contacts/{contact_id}/projects/{project_id}.json"
        client.engine.request("delete", url)
        return {
            "success": True,
            "contact_id": contact_id,
            "project_id": project_id,
        }
    except Exception as e:
        return _handle_redmine_error(
            e,
            f"removing contact {contact_id} from project {project_id}",
            {"resource_type": "contact", "resource_id": contact_id},
        )


@mcp.tool()
async def cleanup_attachment_files() -> Dict[str, Any]:
    """Clean up expired attachment files and return storage statistics.

    Returns:
        A dictionary containing cleanup statistics and current storage usage.
        On error, a dictionary with "error" is returned.
    """
    try:
        attachments_dir = os.getenv("ATTACHMENTS_DIR", "./attachments")
        manager = AttachmentFileManager(attachments_dir)
        cleanup_stats = manager.cleanup_expired_files()
        storage_stats = manager.get_storage_stats()

        return {"cleanup": cleanup_stats, "current_storage": storage_stats}
    except Exception as e:
        logger.error(f"Error during attachment cleanup: {e}")
        return {"error": f"An error occurred during cleanup: {str(e)}"}


if __name__ == "__main__":
    # Initialize and run the server
    mcp.run(transport="stdio")
