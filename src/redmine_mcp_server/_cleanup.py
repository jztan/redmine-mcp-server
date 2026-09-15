"""Background cleanup: expired attachments, and expired OAuth state on disk."""

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .file_manager import AttachmentFileManager

logger = logging.getLogger("redmine_mcp_server")

# The auth modes that keep encrypted state in a FileTreeStore. Each writes
# under FASTMCP_HOME/<mode name>/.
AUTH_STATE_MODES = ("oauth-proxy", "api-key-login")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _auth_state_sweep_applies() -> bool:
    return os.getenv("REDMINE_AUTH_MODE", "legacy").lower() in AUTH_STATE_MODES


def sweep_expired_auth_state(home: Path, now: Optional[datetime] = None) -> int:
    """Delete expired records from the OAuth state stores under ``home``.

    ``FileTreeStore`` stops serving a record once its TTL passes but never
    deletes the file, and the endpoints that write most of these records
    (``/register``, ``/authorize``) are unauthenticated. The store writes
    ``expires_at`` in plaintext next to the encrypted value, so this needs no
    key.

    Layout is ``<subdir>/<key fingerprint>/<collection>/<key>.json``. Only
    record files are touched: the ``<collection>-info.json`` metadata sits one
    level up, directories stay because the store expects them to exist, and a
    file without a readable ``expires_at`` (no TTL, or not a record) is kept.
    Every fingerprint directory is swept, so state left behind by a rotated
    signing key goes too once it expires.

    Returns the number of files deleted.
    """
    now = now or _utcnow()
    removed = 0
    for subdir in AUTH_STATE_MODES:
        for path in Path(home, subdir).glob("*/*/*.json"):
            try:
                with open(path, encoding="utf-8") as handle:
                    inode = os.fstat(handle.fileno()).st_ino
                    record = json.load(handle)
                expires_at = datetime.fromisoformat(record["expires_at"])
                if expires_at > now:
                    continue
                # The store replaces a file by renaming a new one over it, so
                # a changed inode means a fresh write landed after the read.
                if os.stat(path).st_ino != inode:
                    continue
                path.unlink()
                removed += 1
            except (OSError, ValueError, TypeError, KeyError):
                continue
    return removed


class CleanupTaskManager:
    """Manages the background cleanup task lifecycle."""

    def __init__(self):
        self.task: Optional[asyncio.Task] = None
        self.manager: Optional[AttachmentFileManager] = None
        self.enabled = False
        self.sweep_auth_state = False
        self.interval_seconds = 600  # 10 minutes default

    async def start(self):
        """Start the cleanup task if enabled.

        Attachment cleanup follows AUTO_CLEANUP_ENABLED. The OAuth state sweep
        is not optional: in the modes that keep that state it always runs, on
        the same interval.
        """
        self.enabled = os.getenv("AUTO_CLEANUP_ENABLED", "false").lower() == "true"
        self.sweep_auth_state = _auth_state_sweep_applies()

        if not self.enabled and not self.sweep_auth_state:
            logger.info("Automatic cleanup is disabled (AUTO_CLEANUP_ENABLED=false)")
            return

        interval_minutes = float(os.getenv("CLEANUP_INTERVAL_MINUTES", "10"))
        self.interval_seconds = interval_minutes * 60

        if self.enabled:
            attachments_dir = os.getenv("ATTACHMENTS_DIR", "./attachments")
            self.manager = AttachmentFileManager(attachments_dir)
            logger.info(
                f"Starting automatic cleanup task "
                f"(interval: {interval_minutes} minutes, "
                f"directory: {attachments_dir})"
            )
        if self.sweep_auth_state:
            logger.info(
                f"Expired OAuth state under FASTMCP_HOME will be deleted "
                f"every {interval_minutes} minutes"
            )

        self.task = asyncio.create_task(self._cleanup_loop())

    async def _run_once(self):
        """One cleanup pass."""
        if self.manager:
            stats = self.manager.cleanup_expired_files()
            if stats["cleaned_files"] > 0:
                logger.info(
                    f"Automatic cleanup completed: "
                    f"removed {stats['cleaned_files']} files, "
                    f"freed {stats['cleaned_mb']}MB"
                )
            else:
                logger.debug("Automatic cleanup: no expired files found")

        if self.sweep_auth_state:
            from fastmcp import settings

            # Off the event loop: the directory is as large as the traffic
            # that filled it.
            removed = await asyncio.to_thread(
                sweep_expired_auth_state, Path(settings.home), _utcnow()
            )
            if removed:
                logger.info(f"Deleted {removed} expired OAuth state file(s)")

    async def _cleanup_loop(self):
        """The main cleanup loop."""
        # Initial delay to let server fully start
        await asyncio.sleep(10)

        while True:
            try:
                await self._run_once()

                # Wait for next interval
                await asyncio.sleep(self.interval_seconds)

            except asyncio.CancelledError:
                logger.info("Cleanup task cancelled, shutting down")
                raise
            except Exception as e:
                logger.error(f"Error in cleanup task: {e}", exc_info=True)
                # Continue running, wait before retry
                await asyncio.sleep(min(self.interval_seconds, 300))

    async def stop(self):
        """Stop the cleanup task gracefully."""
        if self.task and not self.task.done():
            logger.info("Stopping cleanup task...")
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
            self.task = None
            logger.info("Cleanup task stopped")

    def get_status(self) -> dict:
        """Get current status of cleanup task."""
        return {
            "enabled": self.enabled,
            "running": self.task and not self.task.done() if self.task else False,
            "interval_seconds": self.interval_seconds,
            "auth_state_sweep": self.sweep_auth_state,
            "storage_stats": (
                self.manager.get_storage_stats() if self.manager else None
            ),
        }


# Initialize cleanup manager
cleanup_manager = CleanupTaskManager()


# Global flag to track if cleanup has been initialized
_cleanup_initialized = False


async def _ensure_cleanup_started():
    """Ensure cleanup task is started (lazy initialization)."""
    global _cleanup_initialized
    if not _cleanup_initialized:
        cleanup_enabled = os.getenv("AUTO_CLEANUP_ENABLED", "false").lower() == "true"
        if cleanup_enabled or _auth_state_sweep_applies():
            await cleanup_manager.start()
            _cleanup_initialized = True
            logger.info("Cleanup task initialized")
        else:
            logger.info("Cleanup disabled (AUTO_CLEANUP_ENABLED=false)")
            _cleanup_initialized = (
                True  # Mark as "initialized" to avoid repeated checks
            )
