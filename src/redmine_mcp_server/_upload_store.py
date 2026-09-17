"""Staging area for files a caller uploads over HTTP, before they reach Redmine.

The point of this module is what it keeps *out* of the conversation. An MCP
client cannot pipe a file into a tool argument: whatever ends up in
``content_base64`` is written by the model, character by character, and a
payload of a few thousand characters does not reliably survive that (#305).

So the bytes take the side channel this server already uses in the other
direction. ``/files/{file_id}`` hands out a downloaded attachment against an
unguessable id; ``POST /uploads/{upload_id}`` accepts one against a
single-use ticket. The model sees a path in a shell command and a UUID coming
back, and nothing long passes through it.

Staged files live under ``ATTACHMENTS_DIR`` in the same UUID directories with
the same ``metadata.json`` shape the download path writes, so
``AttachmentFileManager`` expires and sweeps them without knowing they exist.
"""

import hashlib
import hmac
import json
import os
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

# A ticket is worth a single upload of a bounded size, and only for a few
# minutes. It is not a credential for anything else, which is why it can be
# handed to the model at all.
_TICKET_BYTES = 32
_DEFAULT_TICKET_MINUTES = 15.0

# Cap a staged upload at the same ~50 MiB a direct upload gets.
_DEFAULT_MAX_UPLOAD_BYTES = 50 * 1024 * 1024

_STATE_PENDING = "pending"
_STATE_READY = "ready"


def _attachments_dir() -> Path:
    """Where staged uploads live. Resolved per call so a late env var counts."""
    return Path(os.getenv("ATTACHMENTS_DIR", "./attachments"))


def get_ticket_minutes() -> float:
    """Minutes a ticket and its staged file stay valid."""
    try:
        value = float(os.getenv("REDMINE_MCP_UPLOAD_TICKET_MINUTES", ""))
    except ValueError:
        return _DEFAULT_TICKET_MINUTES
    return value if value > 0 else _DEFAULT_TICKET_MINUTES


def get_max_upload_bytes() -> int:
    """Byte cap for a single staged upload."""
    try:
        value = int(os.getenv("REDMINE_MCP_UPLOAD_MAX_BYTES", ""))
    except ValueError:
        return _DEFAULT_MAX_UPLOAD_BYTES
    return value if value > 0 else _DEFAULT_MAX_UPLOAD_BYTES


def _hash_ticket(ticket: str) -> str:
    """Hash a ticket for storage, so the record never holds the live secret."""
    return hashlib.sha256(ticket.encode("utf-8")).hexdigest()


def _record_path(upload_id: str) -> Path:
    return _attachments_dir() / upload_id / "metadata.json"


def _write_record(upload_id: str, record: Dict[str, Any]) -> None:
    """Write a record atomically, the way the download path does."""
    uuid_dir = _attachments_dir() / upload_id
    uuid_dir.mkdir(parents=True, exist_ok=True)
    final = uuid_dir / "metadata.json"
    temp = uuid_dir / "metadata.json.tmp"
    with open(temp, "w", encoding="utf-8") as fh:
        json.dump(record, fh, indent=2)
    # replace, not rename: marking a slot ready rewrites a record that is
    # already there, and os.rename refuses an existing target on Windows.
    os.replace(str(temp), str(final))


def _read_record(upload_id: str) -> Optional[Dict[str, Any]]:
    path = _record_path(upload_id)
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as fh:
            record = json.load(fh)
    except (json.JSONDecodeError, OSError):
        return None
    return record if isinstance(record, dict) else None


def _is_expired(record: Dict[str, Any]) -> bool:
    raw = record.get("expires_at") or ""
    if not raw:
        return False
    try:
        expires_at = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return True
    return datetime.now(timezone.utc) > expires_at


def _safe_filename(filename: Optional[str], upload_id: str) -> str:
    """Basename only, and never empty -- this becomes a path segment."""
    candidate = os.path.basename((filename or "").strip())
    return candidate or f"upload_{upload_id}"


def create_ticket(
    filename: Optional[str] = None,
    content_type: Optional[str] = None,
) -> Dict[str, Any]:
    """Reserve an upload slot and return the ticket that redeems it.

    The ticket is returned once and never stored in the clear.
    """
    upload_id = str(uuid.uuid4())
    ticket = secrets.token_urlsafe(_TICKET_BYTES)
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(minutes=get_ticket_minutes())
    name = _safe_filename(filename, upload_id)

    _write_record(
        upload_id,
        {
            "file_id": upload_id,
            "kind": "upload",
            "state": _STATE_PENDING,
            "ticket_sha256": _hash_ticket(ticket),
            "original_filename": name,
            # AttachmentFileManager expects this key; the file is not there
            # yet, and its cleanup guards on existence.
            "file_path": str((_attachments_dir() / upload_id / name).resolve()),
            "content_type": content_type or "application/octet-stream",
            "size": 0,
            "created_at": now.isoformat(),
            "expires_at": expires_at.isoformat(),
        },
    )

    return {
        "upload_id": upload_id,
        "ticket": ticket,
        "filename": name,
        "expires_at": expires_at.isoformat(),
        "max_bytes": get_max_upload_bytes(),
    }


def redeem_ticket(
    upload_id: str, ticket: str
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Check a ticket against a pending slot.

    Returns ``(record, None)`` when the slot may be written, or
    ``(None, reason)``. The reason is deliberately the same string for a
    wrong ticket and an unknown id, so the endpoint cannot be used to probe
    which upload ids exist.
    """
    try:
        uuid.UUID(upload_id)
    except ValueError:
        return None, "Unknown upload_id or invalid ticket."

    record = _read_record(upload_id)
    if record is None or record.get("kind") != "upload":
        return None, "Unknown upload_id or invalid ticket."

    expected = record.get("ticket_sha256") or ""
    if not expected or not hmac.compare_digest(expected, _hash_ticket(ticket or "")):
        return None, "Unknown upload_id or invalid ticket."

    if _is_expired(record):
        return None, "This upload ticket has expired."

    if record.get("state") != _STATE_PENDING:
        return None, "This upload ticket has already been used."

    return record, None


def staged_path(record: Dict[str, Any]) -> Path:
    return Path(record["file_path"])


def mark_ready(upload_id: str, record: Dict[str, Any], size: int, sha256: str) -> None:
    """Close the slot: the ticket stops working, the bytes stay until the TTL.

    The ticket hash is kept rather than dropped. It is the hash of a token
    that can no longer be redeemed -- the state check refuses it -- and
    keeping it is what lets a caller that retries hear "already used" instead
    of the blanket "unknown", which would send it hunting for the wrong bug.
    """
    record = dict(record)
    record["state"] = _STATE_READY
    record["size"] = size
    record["sha256"] = sha256
    _write_record(upload_id, record)


def discard(upload_id: str) -> None:
    """Drop a slot and whatever landed in it, best effort."""
    uuid_dir = _attachments_dir() / upload_id
    try:
        for path in uuid_dir.iterdir():
            if path.is_file():
                path.unlink()
        uuid_dir.rmdir()
    except OSError:
        pass


def read_staged(
    upload_id: str,
) -> Tuple[bytes, Optional[str], Optional[Dict[str, str]]]:
    """Read a staged upload for attaching.

    Returns ``(content_bytes, filename, None)`` or ``(b"", None, {"error": ...})``.
    The file is left in place; the cleanup manager expires it on the TTL, so a
    retry after a failed Redmine call does not need a fresh upload.
    """
    try:
        uuid.UUID(upload_id)
    except ValueError:
        return b"", None, {"error": f"upload_id is not a valid id: {upload_id}"}

    record = _read_record(upload_id)
    if record is None or record.get("kind") != "upload":
        return (
            b"",
            None,
            {
                "error": (
                    f"No staged upload {upload_id}. Create one with "
                    "create_upload_ticket and POST the file to the returned "
                    "upload_url before attaching it."
                )
            },
        )

    if record.get("state") != _STATE_READY:
        return (
            b"",
            None,
            {
                "error": (
                    f"Upload {upload_id} was reserved but never received a "
                    "file. POST the bytes to the upload_url first."
                )
            },
        )

    if _is_expired(record):
        return (
            b"",
            None,
            {
                "error": (
                    f"Staged upload {upload_id} has expired. Create a new "
                    "ticket and send the file again."
                )
            },
        )

    path = staged_path(record)
    try:
        content_bytes = path.read_bytes()
    except OSError as exc:
        return b"", None, {"error": f"Could not read staged upload: {exc}"}

    return content_bytes, record.get("original_filename"), None
