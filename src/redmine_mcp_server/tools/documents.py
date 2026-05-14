"""DMSF (Document Management System for Files) plugin tool.

Gated behind ``REDMINE_DMSF_ENABLED=true``. Uses the ``redmine_dmsf`` plugin
(GPL v2, https://github.com/danmunn/redmine_dmsf), which replaces Redmine's
built-in (web-UI-only) Documents module with a full document-management
system that exposes a REST API.

Endpoints used (DMSF plugin REST API):

- ``GET  /projects/{id}/dmsf.json`` — list (folder via ``folder_id``)
- ``GET  /dmsf_files/{id}.json`` — get metadata (legacy route preserved
  for show)
- ``POST /uploads.json`` — upload binary, returns token (core endpoint)
- ``POST /projects/{id}/dmsf/commit.json`` — finalize upload as a DMSF
  document (controller action ``dmsf_upload#commit``; reads
  ``params[:attachments][:uploaded_file]`` and ``[:folder_id]``)
- ``POST /dmsf/files/{id}/revision/create.json`` — update by creating a
  new revision. Note the slash form (``dmsf/files``), not the legacy
  underscore form (``dmsf_files``) which only exists for the show route.

DMSF design notes:

- Every update creates a **new revision**; there is no in-place mutation.
- ``title`` and ``name`` are **required** by ``create_revision`` (the
  controller calls ``.scrub.strip`` on both unconditionally). When the
  caller omits either, ``_update_document_action`` pre-fetches the
  current document and uses the existing values.
- The caller-facing ``filename`` parameter on ``create`` is sent to DMSF
  as the ``name`` key inside ``attachments.uploaded_file``. The upload
  helper reads ``committed_file[:name]`` (not ``[:filename]``) and
  assigns it to both ``DmsfFile.name`` and ``DmsfFileRevision.name``.
- ``name`` is the document filename, and DMSF supports renaming via
  revisions: when an update's ``name`` differs from the parent file's
  current name, the controller assigns the new name back onto the
  ``DmsfFile``. (Earlier docs claiming "filenames are immutable" were
  wrong.)
- The caller's ``custom_fields`` parameter maps to DMSF's
  ``custom_field_values`` key in both the commit and revision-create
  request bodies.
- DMSF's commit response is intentionally sparse:
  ``{"dmsf_files": [{"id": N, "name": "..."}], "total_count": N}``.
  Follow up with ``action="get"`` for full metadata.
- A caller-supplied ``version`` string on ``create`` (e.g. ``"1.2.3"``)
  is split into ``version_major`` / ``version_minor`` / ``version_patch``
  and nested inside ``attachments.uploaded_file`` (where DMSF's commit
  helper reads them). ``update`` does **not** expose version control —
  DMSF auto-increments the patch version on each new revision. Note the
  asymmetry: ``commit`` reads version fields nested inside the uploaded
  file dict, whereas ``create_revision`` reads them from top-level
  ``params``. The MCP tool covers the more common case
  (version-at-upload-time).
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
#
# Note: ``name`` is included intentionally — DMSF supports renaming a
# document by creating a new revision with a different ``name``
# (``dmsf_files_controller#create_revision`` assigns it back to the
# parent ``DmsfFile``). The caller's ``custom_fields`` key is mapped to
# DMSF's ``custom_field_values`` in the request body.
_DOCUMENT_WRITABLE_FIELDS = {
    "title",
    "name",
    "description",
    "comment",
    "custom_fields",
}

# Match the file upload cap used by `upload_file` for consistency.
_DMSF_UPLOAD_MAX_SIZE_BYTES = 50 * 1024 * 1024


def _document_to_dict(node: Dict[str, Any]) -> Dict[str, Any]:
    """Serialize a DMSF API node (file / folder / link) into a stable dict.

    DMSF returns two different shapes for the same logical document depending
    on the endpoint:

    - ``GET /projects/{id}/dmsf.json`` (list) returns flat nodes:
      ``{"id", "type", "filename", "title", ...}``
    - ``GET /dmsf_files/{id}.json`` (single) nests current metadata under the
      latest entry of ``dmsf_file_revisions``: most fields (``description``,
      ``size``, ``mime_type``, ``user_id``, ``created_at``, ``updated_at``)
      live there, and the filename is exposed as ``name`` (not ``filename``).

    This serializer merges both shapes into one stable representation, falling
    back to the latest revision when a field is missing at the top level.

    User-controlled fields (``title``, ``name``, ``description``, ``filename``)
    are wrapped in ``<insecure-content>`` boundary tags because they may
    contain prompt-injection payloads.
    """
    if not isinstance(node, dict):
        return {}

    # The latest revision is the highest-id entry; DMSF returns them in
    # ascending order so the last element is the current one. Fall back to
    # max-by-id when the order can't be assumed.
    revisions = node.get("dmsf_file_revisions")
    if isinstance(revisions, list) and revisions:
        latest = revisions[-1]
        if not isinstance(latest, dict):
            latest = {}
    else:
        latest = {}

    # Author can arrive as a nested dict (list endpoint) or as a bare user_id
    # on the latest revision (single endpoint). Normalize to either a
    # ``{"id", "name"}`` dict or ``None``.
    raw_author = node.get("author") or latest.get("author")
    if isinstance(raw_author, dict):
        author: Optional[Dict[str, Any]] = {
            "id": raw_author.get("id"),
            "name": wrap_insecure_content(raw_author.get("name", "")),
        }
    elif latest.get("user_id") is not None:
        author = {"id": latest.get("user_id"), "name": None}
    else:
        author = None

    filename = node.get("filename") or node.get("name") or ""

    return {
        "id": node.get("id"),
        "type": node.get("type"),
        "filename": wrap_insecure_content(filename),
        "title": wrap_insecure_content(node.get("title") or latest.get("title") or ""),
        "name": wrap_insecure_content(node.get("name", "")),
        "description": wrap_insecure_content(
            node.get("description") or latest.get("description") or ""
        ),
        "version": node.get("version") or latest.get("version"),
        "size": (
            node.get("size") if node.get("size") is not None else latest.get("size")
        ),
        "content_type": node.get("content_type") or latest.get("mime_type"),
        "folder_id": node.get("folder_id"),
        "project_id": node.get("project_id"),
        "author": author,
        "created_on": _safe_isoformat(
            node.get("created_on") or latest.get("created_at")
        ),
        "updated_on": _safe_isoformat(
            node.get("updated_on") or latest.get("updated_at")
        ),
    }


def _extract_dmsf_single_doc(payload: Any) -> Dict[str, Any]:
    """Pull a single DMSF document dict out of any of the response shapes.

    Variants we tolerate:
      - ``{"dmsf_file": {...}}``           -- most common single-resource shape
      - ``{"document": {...}}``            -- older / alternate plugin builds
      - ``{"dmsf": {"dmsf_file": {...}}}`` -- defensive: same outer wrapping
        as the list endpoint, in case a plugin version applies it to
        single resources too

    Returns ``{}`` when no recognized shape is found, so callers can
    distinguish missing/unparseable payloads from real data.
    """
    if not isinstance(payload, dict):
        return {}
    for key in ("dmsf_file", "document"):
        node = payload.get(key)
        if isinstance(node, dict):
            return node
    wrapper = payload.get("dmsf")
    if isinstance(wrapper, dict):
        for key in ("dmsf_file", "document"):
            node = wrapper.get(key)
            if isinstance(node, dict):
                return node
    return {}


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
        # DMSF's actual list response is:
        #   {"dmsf": {"dmsf_nodes": [...], "total_count": N}}
        # i.e. payload["dmsf"] is a *dict* (not a list). Earlier code
        # assumed payload["dmsf"] was a list and silently emptied the
        # result. Be defensive: also accept a bare list (older versions
        # observed in the wild) and the legacy "nodes" key.
        if isinstance(payload, list):
            raw: List[Dict[str, Any]] = payload
        elif isinstance(payload, dict):
            dmsf_wrapper = payload.get("dmsf")
            if isinstance(dmsf_wrapper, dict):
                raw = dmsf_wrapper.get("dmsf_nodes") or dmsf_wrapper.get("nodes") or []
            elif isinstance(dmsf_wrapper, list):
                raw = dmsf_wrapper
            else:
                raw = payload.get("nodes") or []
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
        doc = _extract_dmsf_single_doc(payload)
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


def _split_dmsf_version(version: str) -> Union[Dict[str, str], Dict[str, str]]:
    """Split a caller-supplied version string into DMSF's three-part shape.

    Accepts ``"X"``, ``"X.Y"``, or ``"X.Y.Z"`` and pads missing parts with
    ``"0"``. Each part must be a non-negative integer; non-numeric input
    is rejected with an error dict (the marker key is ``"error"``, so the
    caller can distinguish success from failure).
    """
    parts = (str(version).split(".") + ["0", "0", "0"])[:3]
    for part in parts:
        if not part.isdigit():
            return {
                "error": (
                    f"Invalid version '{version}'. Expected 'X', 'X.Y', "
                    "or 'X.Y.Z' where each part is a non-negative integer."
                )
            }
    return {
        "version_major": parts[0],
        "version_minor": parts[1],
        "version_patch": parts[2],
    }


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

    # Pre-validate version splitting before the network round-trip.
    version_parts: Optional[Dict[str, str]] = None
    if version is not None:
        split = _split_dmsf_version(version)
        if "error" in split:
            return split
        version_parts = split

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

        # Step 2: POST /projects/{id}/dmsf/commit.json (DMSF's REST commit
        # action `dmsf_upload#commit`). The controller reads
        # ``params[:attachments]``, picks the entries keyed ``uploaded_file``,
        # and uses ``params[:attachments][:folder_id]`` for folder targeting.
        #
        # Body shape verified against ``dmsf_upload_helper.rb`` (which the
        # commit action calls into):
        #   - key for the filename is ``name`` (NOT ``filename``) — the helper
        #     does ``committed_file[:name]`` and assigns it to both
        #     ``DmsfFile.name`` and ``DmsfFileRevision.name``
        #   - version is split into ``version_major`` / ``version_minor`` /
        #     ``version_patch``, nested inside the uploaded_file dict (the
        #     ``create_revision`` controller for updates reads these
        #     top-level instead — different convention per endpoint)
        #   - custom fields key is ``custom_field_values`` (NOT
        #     ``custom_fields``)
        commit_url = f"{_client.REDMINE_URL}/projects/{project_id}/dmsf/commit.json"
        uploaded_file: Dict[str, Any] = {
            "token": token,
            "name": filename,
        }
        if title is not None:
            uploaded_file["title"] = title
        if description is not None:
            uploaded_file["description"] = description
        if comment is not None:
            uploaded_file["comment"] = comment
        if version_parts is not None:
            uploaded_file.update(version_parts)
        if custom_fields is not None:
            uploaded_file["custom_field_values"] = custom_fields

        attachments_body: Dict[str, Any] = {"uploaded_file": uploaded_file}
        if folder_id is not None:
            attachments_body["folder_id"] = folder_id

        payload = client.engine.request(
            "post",
            commit_url,
            headers={"Content-Type": "application/json"},
            data=json.dumps({"attachments": attachments_body}),
        )

        # DMSF's commit response is intentionally sparse: each entry is
        # ``{"id": N, "name": "..."}`` (no description / size / mime /
        # timestamps). Callers who need full metadata should follow up
        # with action="get".
        files = payload.get("dmsf_files", []) if isinstance(payload, dict) else []
        if not files or not isinstance(files[0], dict):
            return {"success": True}
        created = _document_to_dict(files[0])
        created["note"] = (
            "DMSF's commit response only includes id + name. "
            "Call action='get' with the returned id for full metadata "
            "(description, size, version, timestamps, etc.)."
        )
        return created
    except Exception as e:
        return _handle_redmine_error(
            e,
            f"creating DMSF document '{filename}' in project {project_id}",
            {"resource_type": "document", "resource_id": filename},
        )


def _fetch_current_dmsf_doc(document_id: int) -> Dict[str, Any]:
    """Fetch the current document via the show endpoint and return the
    raw (unwrapped) dict. Used by ``_update_document_action`` to obtain
    the required ``title`` and ``name`` when the caller has not supplied
    overrides (``dmsf_files_controller#create_revision`` calls
    ``.scrub.strip`` on both unconditionally, so nil values crash the
    server)."""
    from .. import _client

    client = _get_redmine_client()
    url = f"{_client.REDMINE_URL}/dmsf_files/{document_id}.json"
    payload = client.engine.request("get", url)
    return _extract_dmsf_single_doc(payload)


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
                f"{sorted(_DOCUMENT_WRITABLE_FIELDS)}."
            )
        }
    from .. import _client

    try:
        # `title` and `name` are required by DMSF's create_revision action
        # (the controller does .scrub.strip on both unconditionally). When
        # the caller omits either, pull the current value from the show
        # endpoint so we don't 500 the server.
        current = _fetch_current_dmsf_doc(document_id)
        if not current:
            return {"error": f"Document {document_id} not found."}

        revision_body: Dict[str, Any] = {
            "title": filtered.get("title", current.get("title") or ""),
            "name": filtered.get("name", current.get("name") or ""),
        }
        if "description" in filtered:
            revision_body["description"] = filtered["description"]
        if "comment" in filtered:
            revision_body["comment"] = filtered["comment"]
        if "custom_fields" in filtered:
            # DMSF reads this key, not "custom_fields", in both
            # commit and create_revision paths.
            revision_body["custom_field_values"] = filtered["custom_fields"]

        client = _get_redmine_client()
        # Canonical route is /dmsf/files/:id/revision/create (with slash);
        # the underscore form /dmsf_files/:id/... only exists for GET-show
        # legacy compatibility and 404s on this POST.
        url = f"{_client.REDMINE_URL}/dmsf/files/{document_id}/revision/create.json"
        client.engine.request(
            "post",
            url,
            headers={"Content-Type": "application/json"},
            data=json.dumps({"dmsf_file_revision": revision_body}),
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
                        ``POST /projects/{id}/dmsf/commit.json``. Accepts
                        file content as ``content_base64`` (capped at
                        50 MiB decoded). DMSF's commit response only
                        includes ``id`` + ``name``; call ``get`` with the
                        returned id for full metadata.
        * ``update``  — update document metadata. **Creates a new revision**
                        (DMSF is versioned; in-place mutation is not
                        supported). Supports renaming via the ``name``
                        field in ``fields``. Required fields (``title``,
                        ``name``) are auto-populated from the current
                        document when not supplied.

    Args:
        action: One of ``list``, ``get``, ``create``, ``update``.
        project_id: Required for ``list`` and ``create``. Project identifier
            (numeric ID or short-name string).
        folder_id: Optional DMSF folder ID for ``list`` and ``create``.
        limit: Max results for ``list`` (1-100, default 100).
        document_id: Required for ``get`` and ``update``.
        filename: Required for ``create``. Used as the initial filename;
            can be changed later by passing ``name`` in ``update``'s
            ``fields`` dict. Sent to DMSF as the ``name`` key inside
            ``attachments.uploaded_file`` (the upload helper reads
            ``committed_file[:name]``, not ``[:filename]``).
        content_base64: Required for ``create``. Raw file bytes as base64.
        title: Optional human-readable title (``create``).
        description: Optional description (``create``).
        comment: Optional revision comment (``create``).
        version: Optional semantic version label for the new revision on
            ``create`` (e.g. ``"1.0"``, ``"1.2.3"``). Accepts ``"X"``,
            ``"X.Y"``, or ``"X.Y.Z"`` and pads missing parts with ``"0"``.
            DMSF stores major/minor/patch as separate integer columns;
            the tool splits the string on ``.`` before sending. Each part
            must be a non-negative integer.
        custom_fields: Optional list of ``{"id": N, "value": ...}`` dicts.
            Sent to DMSF as ``custom_field_values``.
        fields: For ``update``: dict of metadata to change. Allowed keys:
            ``title``, ``name`` (rename), ``description``, ``comment``,
            ``custom_fields``. Unknown keys are silently filtered.

    Returns:
        For ``list``: list of document metadata dicts.
        For ``get``: a single document metadata dict.
        For ``create``: a sparse dict (``id`` + ``name`` only) plus a
            ``note`` pointing at ``action="get"`` for full metadata —
            DMSF's commit endpoint deliberately returns just the id+name.
        For ``update``: success dict with ``updated_fields`` and a ``note``
            confirming a new revision was created.
        On any failure: ``{"error": "..."}``.

    Limitations:
        Setting a custom revision version on ``update`` is not exposed by
        this tool — DMSF auto-increments the patch version when a new
        revision is created. ``create`` supports a ``version`` string
        (e.g. ``"1.0"`` / ``"1.2.3"``), but ``update`` does not. Use the
        Redmine web UI if you need explicit version control on existing
        documents.
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
