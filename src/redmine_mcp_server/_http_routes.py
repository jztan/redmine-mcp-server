"""Starlette HTTP routes mounted alongside the MCP endpoint.

Routes:
  - GET /health         -> health_check (lightweight liveness probe)
  - GET /files/{id}     -> serve_attachment (UUID-validated file serving)
  - GET /cleanup/status -> cleanup_status (background-task stats)
"""

import json
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

from ._client import REDMINE_AUTH_MODE

logger = logging.getLogger("redmine_mcp_server")


async def health_check(request):
    """Health check endpoint for container orchestration and monitoring."""
    from starlette.responses import JSONResponse

    # Lazy lookup so tests patching redmine_handler._ensure_cleanup_started
    # observe the override.
    from . import redmine_handler

    # Initialize cleanup task on first health check (lazy initialization)
    await redmine_handler._ensure_cleanup_started()

    return JSONResponse(
        {
            "status": "ok",
            "service": "redmine_mcp_tools",
            "auth_mode": REDMINE_AUTH_MODE,
        }
    )


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


async def cleanup_status(request):
    """Get cleanup task status and statistics."""
    from starlette.responses import JSONResponse

    # Lazy lookup so tests patching redmine_handler.cleanup_manager
    # observe the override.
    from . import redmine_handler

    return JSONResponse(redmine_handler.cleanup_manager.get_status())
