"""Starlette HTTP routes mounted alongside the MCP endpoint.

Routes:
  - GET /health         -> health_check (lightweight liveness probe; also
    probes Doorkeeper introspection in OAuth mode)
  - GET /files/{id}     -> serve_attachment (UUID-validated file serving)
  - GET /cleanup/status -> cleanup_status (background-task stats)
"""

import base64
import json
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import httpx

from ._client import REDMINE_AUTH_MODE
from ._env import (
    get_health_introspection_ttl_seconds,
    get_introspection_credentials,
)
from .server import mcp

logger = logging.getLogger("redmine_mcp_server")

# Module-level probe cache: {"ts": <monotonic seconds>, "result": (status, detail)|None}
_probe_cache: dict = {"ts": 0.0, "result": None}


async def _probe_introspection_uncached() -> tuple[str, Optional[str]]:
    """POST a synthetic token to Doorkeeper's /oauth/introspect.

    Returns ("ok", None) if reachable (200 response, any body).
    Returns ("unreachable", "<reason>") on transport failure or non-200.

    A 200 with ``{"active": false}`` for the synthetic token IS healthy:
    it proves the endpoint is reachable and our client credentials work.
    """
    redmine_url = (os.environ.get("REDMINE_URL") or "").rstrip("/")
    if not redmine_url:
        return "unreachable", "REDMINE_URL not set"
    client_id, client_secret = get_introspection_credentials()
    if not (client_id and client_secret):
        return "unreachable", "introspection credentials not configured"

    creds = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    headers = {
        "Authorization": f"Basic {creds}",
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.post(
                f"{redmine_url}/oauth/introspect",
                headers=headers,
                data={"token": "health-probe-synthetic-token"},
            )
            if r.status_code == 200:
                return "ok", None
            logger.warning(
                "introspection_upstream_failure status_code=%s url=%s",
                r.status_code,
                f"{redmine_url}/oauth/introspect",
            )
            return "unreachable", f"HTTP {r.status_code}"
    except httpx.RequestError as e:
        logger.warning(
            "introspection_upstream_failure error=%s url=%s",
            type(e).__name__,
            f"{redmine_url}/oauth/introspect",
        )
        return "unreachable", type(e).__name__


async def _probe_introspection() -> tuple[str, Optional[str]]:
    """Cached wrapper around _probe_introspection_uncached."""
    ttl = get_health_introspection_ttl_seconds()
    now = time.monotonic()
    if _probe_cache["result"] is not None and (now - _probe_cache["ts"]) < ttl:
        return _probe_cache["result"]
    result = await _probe_introspection_uncached()
    _probe_cache["ts"] = now
    _probe_cache["result"] = result
    return result


async def health_check(request):
    """Health check endpoint for container orchestration and monitoring.

    In OAuth mode, also probes Doorkeeper's ``/oauth/introspect`` to surface
    upstream availability that was lost in the 503->401 collapse when
    FastMCP native auth replaced the bespoke middleware.

    Returns HTTP 200 in both healthy and degraded states so container
    orchestrators continue treating the endpoint as a binary liveness
    probe; monitoring systems should inspect the JSON ``status`` field.
    """
    from starlette.responses import JSONResponse

    # Lazy lookup so tests patching _cleanup._ensure_cleanup_started
    # observe the override.
    from . import _cleanup

    # Initialize cleanup task on first health check (lazy initialization)
    await _cleanup._ensure_cleanup_started()

    response: dict = {
        "status": "ok",
        "service": "redmine_mcp_tools",
        "auth_mode": REDMINE_AUTH_MODE,
    }

    if REDMINE_AUTH_MODE == "oauth":
        probe_status, detail = await _probe_introspection()
        checks: dict = {"introspection": probe_status}
        if detail:
            checks["introspection_detail"] = detail
        response["checks"] = checks
        if probe_status != "ok":
            response["status"] = "degraded"

    return JSONResponse(response)


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

    # Lazy lookup so tests patching _cleanup.cleanup_manager
    # observe the override.
    from . import _cleanup

    return JSONResponse(_cleanup.cleanup_manager.get_status())


# Register HTTP routes on the FastMCP instance. The decorator must be applied
# at import time (when this module is imported by main.py / tests).
mcp.custom_route("/health", methods=["GET"])(health_check)
mcp.custom_route("/files/{file_id}", methods=["GET"])(serve_attachment)
mcp.custom_route("/cleanup/status", methods=["GET"])(cleanup_status)
