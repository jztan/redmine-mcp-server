"""Background attachment-cleanup task management."""

import asyncio
import logging
import os
from typing import Optional

from .file_manager import AttachmentFileManager

logger = logging.getLogger("redmine_mcp_server")


class CleanupTaskManager:
    """Manages the background cleanup task lifecycle."""

    def __init__(self):
        self.task: Optional[asyncio.Task] = None
        self.manager: Optional[AttachmentFileManager] = None
        self.enabled = False
        self.interval_seconds = 600  # 10 minutes default

    async def start(self):
        """Start the cleanup task if enabled."""
        self.enabled = os.getenv("AUTO_CLEANUP_ENABLED", "false").lower() == "true"

        if not self.enabled:
            logger.info("Automatic cleanup is disabled (AUTO_CLEANUP_ENABLED=false)")
            return

        interval_minutes = float(os.getenv("CLEANUP_INTERVAL_MINUTES", "10"))
        self.interval_seconds = interval_minutes * 60
        attachments_dir = os.getenv("ATTACHMENTS_DIR", "./attachments")

        self.manager = AttachmentFileManager(attachments_dir)

        logger.info(
            f"Starting automatic cleanup task "
            f"(interval: {interval_minutes} minutes, "
            f"directory: {attachments_dir})"
        )

        self.task = asyncio.create_task(self._cleanup_loop())

    async def _cleanup_loop(self):
        """The main cleanup loop."""
        # Initial delay to let server fully start
        await asyncio.sleep(10)

        while True:
            try:
                stats = self.manager.cleanup_expired_files()
                if stats["cleaned_files"] > 0:
                    logger.info(
                        f"Automatic cleanup completed: "
                        f"removed {stats['cleaned_files']} files, "
                        f"freed {stats['cleaned_mb']}MB"
                    )
                else:
                    logger.debug("Automatic cleanup: no expired files found")

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
        if cleanup_enabled:
            await cleanup_manager.start()
            _cleanup_initialized = True
            logger.info("Cleanup task initialized via MCP tool call")
        else:
            logger.info("Cleanup disabled (AUTO_CLEANUP_ENABLED=false)")
            _cleanup_initialized = (
                True  # Mark as "initialized" to avoid repeated checks
            )
