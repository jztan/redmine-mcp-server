"""Starlette HTTP routes mounted alongside the MCP endpoint.

Routes:
  - GET  /health         -> health_check (lightweight liveness probe; also
    probes Doorkeeper introspection in OAuth mode)
  - GET  /files/{id}     -> serve_attachment (UUID-validated file serving)
  - POST /uploads/{id}   -> receive_upload (ticketed staging of a caller's
    file, so its bytes never pass through the model -- #305)
  - GET  /cleanup/status -> cleanup_status (background-task stats)
"""

import base64
import hashlib
import json
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import httpx

from ._client import REDMINE_AUTH_MODE, httpx_ssl_kwargs
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
        async with httpx.AsyncClient(timeout=5, **httpx_ssl_kwargs()) as client:
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


async def _probe_redmine_legacy() -> tuple[str, str | None]:
    """Check Redmine connectivity for legacy (API key / password) auth mode.

    Calls ``GET /users/current.json`` using the configured credentials.

    Returns:
        ``("ok", None)`` — credentials valid and Redmine reachable.
        ``("unconfigured", "<reason>")`` — URL or credentials not set;
            health status is NOT degraded (server hasn't been configured yet).
        ``("unreachable", "<reason>")`` — credentials present but Redmine
            rejected or could not be reached; health status IS degraded.

    Not cached — auth failures should surface on every health poll.
    """
    from ._client import (
        REDMINE_API_KEY,
        REDMINE_PASSWORD,
        REDMINE_URL,
        REDMINE_USERNAME,
    )

    if not REDMINE_URL:
        return "unconfigured", "REDMINE_URL not set"
    if not (REDMINE_API_KEY or (REDMINE_USERNAME and REDMINE_PASSWORD)):
        return "unconfigured", "no credentials configured"

    # Use httpx directly against /users/current.json.
    # This endpoint works on Redmine 3.x and later (/my/account.json is
    # not reliably available on older instances).
    # Deliberately not via the client: this probe's job is to validate the
    # credentials and config the client is built from. Not because the
    # endpoint needs admin -- see the `get_current_user` note in
    # `oauth_scopes.py`.
    url = REDMINE_URL.rstrip("/") + "/users/current.json"
    try:
        if REDMINE_API_KEY:
            headers = {"X-Redmine-API-Key": REDMINE_API_KEY}
            auth = None
        else:
            headers = {}
            auth = (REDMINE_USERNAME, REDMINE_PASSWORD)
        async with httpx.AsyncClient(timeout=5, **httpx_ssl_kwargs()) as client:
            r = await client.get(url, headers=headers, auth=auth)
        if r.status_code == 200:
            return "ok", None
        logger.warning(
            "legacy_redmine_probe_failure status_code=%s url=%s", r.status_code, url
        )
        return "unreachable", f"HTTP {r.status_code}"
    except httpx.RequestError as exc:
        reason = type(exc).__name__
        logger.warning("legacy_redmine_probe_failure error=%s url=%s", reason, url)
        return "unreachable", reason


async def _probe_redmine_reachable() -> tuple[str, str | None]:
    """Reachability-only probe for legacy-per-user mode.

    There is no shared credential to authenticate with, so this only confirms
    the Redmine URL answers. Any HTTP response (even 401/403) means reachable.
    """
    from ._client import REDMINE_URL

    if not REDMINE_URL:
        return "unconfigured", "REDMINE_URL not set"
    url = REDMINE_URL.rstrip("/") + "/users/current.json"
    try:
        async with httpx.AsyncClient(timeout=5, **httpx_ssl_kwargs()) as client:
            await client.get(url)
        return "reachable_unauthenticated", None
    except httpx.RequestError as exc:
        reason = type(exc).__name__
        logger.warning("per_user_redmine_probe_failure error=%s url=%s", reason, url)
        return "unreachable", reason


async def health_check(request):
    """Health check endpoint for container orchestration and monitoring.

    In OAuth and OAuth proxy modes, also probes Doorkeeper's
    ``/oauth/introspect`` to surface upstream availability that was lost in
    the 503->401 collapse when FastMCP native auth replaced the bespoke
    middleware.

    In legacy mode, probes ``GET /users/current.json`` to verify the configured
    API key (or username/password) is accepted by Redmine.

    In legacy-per-user mode there is no shared credential, so it probes
    ``GET /users/current.json`` unauthenticated to confirm URL reachability
    only. Any HTTP response (including 401 or 403) counts as reachable; only
    transport failures degrade status.

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

    if REDMINE_AUTH_MODE in {"oauth", "oauth-proxy"}:
        probe_status, detail = await _probe_introspection()
        checks: dict = {"introspection": probe_status}
        if detail:
            checks["introspection_detail"] = detail
        response["checks"] = checks
        if probe_status != "ok":
            response["status"] = "degraded"
    elif REDMINE_AUTH_MODE in {"legacy-per-user", "api-key-login"}:
        probe_status, detail = await _probe_redmine_reachable()
        checks: dict = {"redmine": probe_status}
        if detail:
            checks["redmine_detail"] = detail
        response["checks"] = checks
        if probe_status == "unreachable":
            response["status"] = "degraded"
    else:
        probe_status, detail = await _probe_redmine_legacy()
        checks: dict = {"redmine": probe_status}
        if detail:
            checks["redmine_detail"] = detail
        response["checks"] = checks
        # "unconfigured" means the server hasn't been set up yet — not a
        # runtime failure, so don't degrade. Only degrade on "unreachable".
        if probe_status == "unreachable":
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
        with open(metadata_file, "r", encoding="utf-8") as f:
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


async def receive_upload(request):
    """Stage a caller's file against a single-use ticket (#305).

    The counterpart to ``serve_attachment``. A caller asks
    ``create_upload_ticket`` for a slot, sends the bytes here with one HTTP
    request, and then names the resulting ``upload_id`` in ``uploads``. The
    file therefore travels from the caller's disk to this server directly,
    instead of being retyped into a tool argument as base64.

    Guarded the way ``/files/{file_id}`` is guarded: by an unguessable
    string with a short TTL, not by the MCP session's own auth, which does
    not reach these Starlette routes. The ticket buys exactly one upload of
    a bounded size and nothing else.

    Body is the raw file: ``application/octet-stream`` (or anything else --
    the body is read as-is), or ``multipart/form-data`` with a single
    ``file`` part. The ticket goes in ``X-Upload-Ticket``.
    """
    from starlette.responses import JSONResponse

    from . import _upload_store

    upload_id = request.path_params["upload_id"]
    ticket = request.headers.get("x-upload-ticket", "")

    record, reason = _upload_store.redeem_ticket(upload_id, ticket)
    if record is None:
        # 404 for everything unknown, so the endpoint cannot be used to
        # tell an existing upload_id from a wrong ticket.
        status = 410 if "expired" in reason or "already been used" in reason else 404
        return JSONResponse({"error": reason}, status_code=status)

    max_bytes = _upload_store.get_max_upload_bytes()
    target = _upload_store.staged_path(record)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_suffix(target.suffix + ".tmp")

    digest = hashlib.sha256()
    size = 0
    content_type = request.headers.get("content-type", "")

    try:
        if content_type.startswith("multipart/form-data"):
            form = await request.form()
            part = form.get("file")
            if part is None or not hasattr(part, "read"):
                _upload_store.discard(upload_id)
                return JSONResponse(
                    {"error": "multipart body needs a single 'file' part."},
                    status_code=400,
                )
            with open(temp, "wb") as fh:
                while True:
                    chunk = await part.read(65536)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > max_bytes:
                        fh.close()
                        _upload_store.discard(upload_id)
                        return JSONResponse(
                            {"error": f"Upload exceeds the {max_bytes}-byte limit."},
                            status_code=413,
                        )
                    digest.update(chunk)
                    fh.write(chunk)
        else:
            with open(temp, "wb") as fh:
                async for chunk in request.stream():
                    if not chunk:
                        continue
                    size += len(chunk)
                    if size > max_bytes:
                        fh.close()
                        _upload_store.discard(upload_id)
                        return JSONResponse(
                            {"error": f"Upload exceeds the {max_bytes}-byte limit."},
                            status_code=413,
                        )
                    digest.update(chunk)
                    fh.write(chunk)
    except OSError as exc:
        _upload_store.discard(upload_id)
        logger.warning("Staging upload %s failed: %s", upload_id, exc)
        return JSONResponse({"error": "Could not store the upload."}, status_code=500)

    if size == 0:
        _upload_store.discard(upload_id)
        return JSONResponse({"error": "Upload body was empty."}, status_code=400)

    os.replace(str(temp), str(target))
    sha256 = digest.hexdigest()
    _upload_store.mark_ready(upload_id, record, size, sha256)

    logger.info("Staged upload %s (%d bytes)", upload_id, size)
    return JSONResponse(
        {
            "upload_id": upload_id,
            "filename": record.get("original_filename"),
            "size": size,
            "sha256": sha256,
            "expires_at": record.get("expires_at"),
        }
    )


# Register HTTP routes on the FastMCP instance. The decorator must be applied
# at import time (when this module is imported by main.py / tests).
mcp.custom_route("/health", methods=["GET"])(health_check)
mcp.custom_route("/files/{file_id}", methods=["GET"])(serve_attachment)
mcp.custom_route("/uploads/{upload_id}", methods=["POST"])(receive_upload)
mcp.custom_route("/cleanup/status", methods=["GET"])(cleanup_status)
