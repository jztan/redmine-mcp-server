"""File operation tools: list, upload (with SSRF-protected URL fetch),
delete, attachment download URL generation, and cleanup of expired files.
"""

import base64
import binascii
import io
import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from .._cleanup import _ensure_cleanup_started
from .._client import _get_redmine_client, logger
from .._env import _is_read_only_mode
from .._errors import _READ_ONLY_ERROR, _handle_redmine_error
from .._serialization import (
    _iter_capped,
    _named_ref,
    _safe_isoformat,
    wrap_insecure_content,
)
from .._ssrf import _download_file_url
from ..file_manager import AttachmentFileManager
from ..server import mcp

# ---------------------------------------------------------------------------
# Module-level limits.
# ---------------------------------------------------------------------------

# Cap a single base64 file upload at ~50 MiB decoded to protect the server
# from resource exhaustion. Larger files should be uploaded via a different
# mechanism (e.g., writing to disk first and passing a path).
_FILE_UPLOAD_MAX_SIZE_BYTES = 50 * 1024 * 1024


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
