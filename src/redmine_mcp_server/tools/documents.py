"""DMSF (Document Management System for Files) plugin tool.

Gated behind ``REDMINE_DMSF_ENABLED=true``. Uses the ``redmine_dmsf`` plugin
(GPL v2, https://github.com/danmunn/redmine_dmsf), which replaces Redmine's
built-in (web-UI-only) Documents module with a full document-management
system that exposes a REST API.

Endpoints used (DMSF plugin REST API):

- ``GET  /projects/{id}/dmsf.json`` — list (folder via ``folder_id``)
- ``GET  /dmsf_files/{id}.json`` — get metadata
- ``POST /uploads.json`` — upload binary, returns token (core endpoint)
- ``POST /projects/{id}/dmsf/commit_files.json`` — finalize upload
- ``POST /dmsf_files/{id}/revision/create.json`` — update (new revision)

DMSF design notes:

- Every update creates a **new revision**; there is no in-place mutation.
- Filenames are **immutable**. To replace content, upload a new revision
  with the same filename.
- DMSF replaces the built-in Documents module rather than complementing it.
  Existing native documents are not accessible via DMSF until migrated
  with ``rake redmine:dmsf_convert_documents`` on the server.
"""

import base64
import binascii
import io
import json
from typing import Any, Dict, List, Optional, Union

from .._client import _get_redmine_client
from .._decorators import ActionMode, action_dispatch
from .._env import _is_dmsf_enabled
from .._errors import _handle_redmine_error
from .._serialization import (
    _REDMINE_API_PAGE_CAP,
    _safe_isoformat,
    wrap_insecure_content,
)
from .._validation import _is_positive_int, _is_valid_project_id
from ..server import mcp

_DMSF_DISABLED_ERROR = {
    "error": (
        "DMSF (document management) support is disabled. "
        "Set REDMINE_DMSF_ENABLED=true to enable it. "
        "Requires the redmine_dmsf plugin installed on the Redmine server."
    )
}

# Fields the caller may update on an existing document via a new revision.
# Unknown keys are silently filtered out before reaching the API.
_DOCUMENT_WRITABLE_FIELDS = {
    "title",
    "description",
    "comment",
    "custom_fields",
}

# Match the file upload cap used by `upload_file` for consistency.
_DMSF_UPLOAD_MAX_SIZE_BYTES = 50 * 1024 * 1024


def _document_to_dict(node: Dict[str, Any]) -> Dict[str, Any]:
    """Serialize a DMSF API node (file / folder / link) into a stable dict.

    User-controlled fields (``title``, ``name``, ``description``, ``filename``)
    are wrapped in ``<insecure-content>`` boundary tags because they may
    contain prompt-injection payloads.
    """
    if not isinstance(node, dict):
        return {}
    raw_author = node.get("author")
    author = raw_author if isinstance(raw_author, dict) else {}
    return {
        "id": node.get("id"),
        "type": node.get("type"),
        "filename": wrap_insecure_content(node.get("filename", "")),
        "title": wrap_insecure_content(node.get("title", "")),
        "name": wrap_insecure_content(node.get("name", "")),
        "description": wrap_insecure_content(node.get("description", "")),
        "version": node.get("version"),
        "size": node.get("size"),
        "content_type": node.get("content_type"),
        "folder_id": node.get("folder_id"),
        "project_id": node.get("project_id"),
        "author": (
            {
                "id": author.get("id"),
                "name": wrap_insecure_content(author.get("name", "")),
            }
            if author
            else None
        ),
        "created_on": _safe_isoformat(node.get("created_on")),
        "updated_on": _safe_isoformat(node.get("updated_on")),
    }


async def _list_documents_action(
    project_id: Optional[Union[str, int]] = None,
    folder_id: Optional[int] = None,
    limit: int = 100,
    **_: Any,
) -> Union[List[Dict[str, Any]], Dict[str, Any]]:
    if not _is_valid_project_id(project_id):
        return {
            "error": (
                "project_id is required and must be a non-empty string "
                "identifier or positive integer."
            )
        }
    if folder_id is not None and not _is_positive_int(folder_id):
        return {"error": "folder_id must be a positive integer."}
    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
        return {"error": "limit must be a positive integer."}
    limit = min(limit, _REDMINE_API_PAGE_CAP)
    from .. import _client

    try:
        client = _get_redmine_client()
        url = f"{_client.REDMINE_URL}/projects/{project_id}/dmsf.json"
        params: Dict[str, Any] = {"limit": limit}
        if folder_id is not None:
            params["folder_id"] = folder_id
        payload = client.engine.request("get", url, params=params)
        # DMSF responses commonly wrap items under "dmsf" or return a list.
        if isinstance(payload, list):
            raw: List[Dict[str, Any]] = payload
        elif isinstance(payload, dict):
            raw = payload.get("dmsf") or payload.get("nodes") or []
            if not isinstance(raw, list):
                raw = []
        else:
            raw = []
        return [_document_to_dict(n) for n in raw[:limit]]
    except Exception as e:
        return _handle_redmine_error(
            e,
            f"listing DMSF documents in project {project_id}",
            {"resource_type": "documents", "resource_id": project_id},
        )


async def _get_document_action(
    document_id: Optional[int] = None,
    **_: Any,
) -> Dict[str, Any]:
    if not _is_positive_int(document_id):
        return {"error": "document_id must be a positive integer."}
    from .. import _client

    try:
        client = _get_redmine_client()
        url = f"{_client.REDMINE_URL}/dmsf_files/{document_id}.json"
        payload = client.engine.request("get", url)
        doc = (
            payload.get("dmsf_file") or payload.get("document") or {}
            if isinstance(payload, dict)
            else {}
        )
        if not doc:
            return {"error": f"Document {document_id} not found."}
        return _document_to_dict(doc)
    except Exception as e:
        return _handle_redmine_error(
            e,
            f"fetching DMSF document {document_id}",
            {"resource_type": "document", "resource_id": document_id},
        )


def _decode_content_base64(content_base64: str) -> Union[bytes, Dict[str, str]]:
    """Decode and size-check base64 content. Returns bytes or an error dict."""
    try:
        content_bytes = base64.b64decode(content_base64, validate=True)
    except (binascii.Error, ValueError) as e:
        return {"error": f"content_base64 is not valid base64. Details: {e}"}
    if len(content_bytes) == 0:
        return {"error": "Decoded file content is empty."}
    if len(content_bytes) > _DMSF_UPLOAD_MAX_SIZE_BYTES:
        size_mb = len(content_bytes) / (1024 * 1024)
        limit_mb = _DMSF_UPLOAD_MAX_SIZE_BYTES / (1024 * 1024)
        return {
            "error": (
                f"File too large: {size_mb:.1f} MiB exceeds the "
                f"{limit_mb:.0f} MiB upload limit."
            )
        }
    return content_bytes


async def _create_document_action(
    project_id: Optional[Union[str, int]] = None,
    filename: Optional[str] = None,
    content_base64: Optional[str] = None,
    title: Optional[str] = None,
    description: Optional[str] = None,
    comment: Optional[str] = None,
    folder_id: Optional[int] = None,
    version: Optional[str] = None,
    custom_fields: Optional[List[Dict[str, Any]]] = None,
    **_: Any,
) -> Dict[str, Any]:
    if not _is_valid_project_id(project_id):
        return {
            "error": (
                "project_id is required and must be a non-empty string "
                "identifier or positive integer."
            )
        }
    if not isinstance(filename, str) or not filename.strip():
        return {"error": "filename is required and must be a non-empty string."}
    if not isinstance(content_base64, str) or not content_base64.strip():
        return {"error": "content_base64 is required and must be a non-empty string."}
    if folder_id is not None and not _is_positive_int(folder_id):
        return {"error": "folder_id must be a positive integer."}

    decoded = _decode_content_base64(content_base64)
    if isinstance(decoded, dict):
        return decoded
    content_bytes: bytes = decoded
    from .. import _client

    try:
        client = _get_redmine_client()

        # Step 1: upload raw bytes to /uploads.json, get token (core endpoint).
        # DMSF accepts the same token mechanism as core file uploads.
        token = client.upload(io.BytesIO(content_bytes), filename=filename)["token"]

        # Step 2: commit the upload with metadata via the DMSF endpoint.
        commit_url = (
            f"{_client.REDMINE_URL}/projects/{project_id}/dmsf/commit_files.json"
        )
        commit_body: Dict[str, Any] = {
            "token": token,
            "filename": filename,
        }
        if title is not None:
            commit_body["title"] = title
        if description is not None:
            commit_body["description"] = description
        if comment is not None:
            commit_body["comment"] = comment
        if folder_id is not None:
            commit_body["folder_id"] = folder_id
        if version is not None:
            commit_body["version"] = version
        if custom_fields is not None:
            commit_body["custom_fields"] = custom_fields

        payload = client.engine.request(
            "post",
            commit_url,
            headers={"Content-Type": "application/json"},
            data=json.dumps({"dmsf_file": commit_body}),
        )
        doc = (
            payload.get("dmsf_file") or payload.get("document") or {}
            if isinstance(payload, dict)
            else {}
        )
        return _document_to_dict(doc) if doc else {"success": True}
    except Exception as e:
        return _handle_redmine_error(
            e,
            f"creating DMSF document '{filename}' in project {project_id}",
            {"resource_type": "document", "resource_id": filename},
        )


async def _update_document_action(
    document_id: Optional[int] = None,
    fields: Optional[Dict[str, Any]] = None,
    **_: Any,
) -> Dict[str, Any]:
    if not _is_positive_int(document_id):
        return {"error": "document_id must be a positive integer."}
    if not isinstance(fields, dict) or not fields:
        return {"error": "fields must be a non-empty dict."}
    filtered = {k: v for k, v in fields.items() if k in _DOCUMENT_WRITABLE_FIELDS}
    if not filtered:
        return {
            "error": (
                "No writable fields provided. Allowed fields: "
                f"{sorted(_DOCUMENT_WRITABLE_FIELDS)}. "
                "Note: DMSF filenames are immutable; to replace content, "
                "create a new revision via the create action with the same "
                "filename."
            )
        }
    from .. import _client

    try:
        client = _get_redmine_client()
        url = f"{_client.REDMINE_URL}/dmsf_files/{document_id}/revision/create.json"
        client.engine.request(
            "post",
            url,
            headers={"Content-Type": "application/json"},
            data=json.dumps({"dmsf_file_revision": filtered}),
        )
        return {
            "success": True,
            "document_id": document_id,
            "updated_fields": list(filtered.keys()),
            "note": (
                "DMSF created a new revision; previous revisions remain "
                "accessible via the document's revision history."
            ),
        }
    except Exception as e:
        return _handle_redmine_error(
            e,
            f"updating DMSF document {document_id}",
            {"resource_type": "document", "resource_id": document_id},
        )


@action_dispatch(
    {
        "list": ActionMode.READ,
        "get": ActionMode.READ,
        "create": ActionMode.WRITE,
        "update": ActionMode.WRITE,
    }
)
async def _manage_document_dispatch(action: str, **kwargs: Any) -> Any:
    return {
        "list": _list_documents_action,
        "get": _get_document_action,
        "create": _create_document_action,
        "update": _update_document_action,
    }


@mcp.tool()
async def manage_document(
    action: str,
    project_id: Optional[Union[str, int]] = None,
    folder_id: Optional[int] = None,
    limit: int = 100,
    document_id: Optional[int] = None,
    filename: Optional[str] = None,
    content_base64: Optional[str] = None,
    title: Optional[str] = None,
    description: Optional[str] = None,
    comment: Optional[str] = None,
    version: Optional[str] = None,
    custom_fields: Optional[List[Dict[str, Any]]] = None,
    fields: Optional[Dict[str, Any]] = None,
) -> Union[List[Dict[str, Any]], Dict[str, Any]]:
    """Manage DMSF documents (list / get / create / update).

    Requires the ``redmine_dmsf`` plugin and ``REDMINE_DMSF_ENABLED=true``.

    Actions:
        * ``list``    — list documents in a project (or a DMSF folder).
        * ``get``     — fetch a single document's metadata by ID.
        * ``create``  — upload a new document. Two-step under the hood:
                        ``POST /uploads.json`` → token, then
                        ``POST /projects/{id}/dmsf/commit_files.json``.
                        Accepts file content as ``content_base64``.
                        Capped at 50 MiB decoded.
        * ``update``  — update document metadata. **Creates a new revision**
                        (DMSF is versioned; in-place mutation is not
                        supported). DMSF filenames are immutable — to
                        replace content, ``create`` a new revision with
                        the same filename.

    Args:
        action: One of ``list``, ``get``, ``create``, ``update``.
        project_id: Required for ``list`` and ``create``. Project identifier
            (numeric ID or short-name string).
        folder_id: Optional DMSF folder ID for ``list`` and ``create``.
        limit: Max results for ``list`` (1-100, default 100).
        document_id: Required for ``get`` and ``update``.
        filename: Required for ``create``. Becomes the immutable filename
            for all future revisions.
        content_base64: Required for ``create``. Raw file bytes as base64.
        title: Optional human-readable title (``create``).
        description: Optional description (``create``).
        comment: Optional revision comment (``create``).
        version: Optional version label (``create``).
        custom_fields: Optional list of ``{"id": N, "value": ...}`` dicts.
        fields: For ``update``: dict of metadata to update. Allowed keys:
            ``title``, ``description``, ``comment``, ``custom_fields``.
            Unknown keys are silently filtered.

    Returns:
        For ``list``: list of document metadata dicts.
        For ``get`` / ``create``: a single document metadata dict.
        For ``update``: success dict with ``updated_fields``.
        On any failure: ``{"error": "..."}``.
    """
    if not _is_dmsf_enabled():
        return dict(_DMSF_DISABLED_ERROR)
    return await _manage_document_dispatch(
        action,
        project_id=project_id,
        folder_id=folder_id,
        limit=limit,
        document_id=document_id,
        filename=filename,
        content_base64=content_base64,
        title=title,
        description=description,
        comment=comment,
        version=version,
        custom_fields=custom_fields,
        fields=fields,
    )
