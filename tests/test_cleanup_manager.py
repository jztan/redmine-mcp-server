"""
Tests for CleanupTaskManager class.

Tests cover:
- Initialization
- Start/stop lifecycle
- Cleanup loop behavior
- Status reporting
- Lazy initialization via _ensure_cleanup_started
"""

import pytest
import asyncio
import os
from unittest.mock import patch, AsyncMock


@pytest.mark.unit
class TestCleanupTaskManager:
    """Tests for CleanupTaskManager class."""

    @pytest.fixture
    def fresh_manager(self):
        """Create a fresh CleanupTaskManager instance."""
        import redmine_mcp_server.redmine_handler as handler

        return handler.CleanupTaskManager()

    @pytest.fixture
    def reset_global_state(self):
        """Reset global cleanup state before and after test."""
        import redmine_mcp_server.redmine_handler as handler

        # Store original state
        original_initialized = handler._cleanup_initialized
        original_manager = handler.cleanup_manager

        # Reset before test
        handler._cleanup_initialized = False
        handler.cleanup_manager = handler.CleanupTaskManager()

        yield

        # Restore after test
        handler._cleanup_initialized = original_initialized
        handler.cleanup_manager = original_manager

    def test_cleanup_manager_init(self, fresh_manager):
        """Test CleanupTaskManager initialization."""
        assert fresh_manager.task is None
        assert fresh_manager.manager is None
        assert fresh_manager.enabled is False
        assert fresh_manager.interval_seconds == 600  # 10 minutes default

    @pytest.mark.asyncio
    async def test_cleanup_manager_start_disabled(self, fresh_manager):
        """Test start() when AUTO_CLEANUP_ENABLED=false."""
        with patch.dict(os.environ, {"AUTO_CLEANUP_ENABLED": "false"}):
            await fresh_manager.start()

        assert fresh_manager.enabled is False
        assert fresh_manager.task is None
        assert fresh_manager.manager is None

    @pytest.mark.asyncio
    async def test_cleanup_manager_start_enabled(self, fresh_manager, tmp_path):
        """Test start() when AUTO_CLEANUP_ENABLED=true."""
        attachments_dir = tmp_path / "attachments"
        attachments_dir.mkdir()

        with patch.dict(
            os.environ,
            {
                "AUTO_CLEANUP_ENABLED": "true",
                "CLEANUP_INTERVAL_MINUTES": "5",
                "ATTACHMENTS_DIR": str(attachments_dir),
            },
        ):
            await fresh_manager.start()

        try:
            assert fresh_manager.enabled is True
            assert fresh_manager.task is not None
            assert fresh_manager.manager is not None
            assert fresh_manager.interval_seconds == 300  # 5 minutes
        finally:
            # Clean up the task
            await fresh_manager.stop()

    @pytest.mark.asyncio
    async def test_cleanup_manager_stop(self, fresh_manager, tmp_path):
        """Test graceful shutdown via stop()."""
        attachments_dir = tmp_path / "attachments"
        attachments_dir.mkdir()

        with patch.dict(
            os.environ,
            {"AUTO_CLEANUP_ENABLED": "true", "ATTACHMENTS_DIR": str(attachments_dir)},
        ):
            await fresh_manager.start()

        assert fresh_manager.task is not None

        await fresh_manager.stop()

        assert fresh_manager.task is None

    @pytest.mark.asyncio
    async def test_cleanup_manager_stop_when_not_started(self, fresh_manager):
        """Test stop() when no task is running."""
        # Should not raise any errors
        await fresh_manager.stop()
        assert fresh_manager.task is None

    def test_cleanup_manager_get_status_not_started(self, fresh_manager):
        """Test get_status() when manager is not started."""
        status = fresh_manager.get_status()

        assert status["enabled"] is False
        assert status["running"] is False
        assert status["interval_seconds"] == 600
        assert status["storage_stats"] is None

    @pytest.mark.asyncio
    async def test_cleanup_manager_get_status_running(self, fresh_manager, tmp_path):
        """Test get_status() when manager is running."""
        attachments_dir = tmp_path / "attachments"
        attachments_dir.mkdir()

        with patch.dict(
            os.environ,
            {"AUTO_CLEANUP_ENABLED": "true", "ATTACHMENTS_DIR": str(attachments_dir)},
        ):
            await fresh_manager.start()

        try:
            status = fresh_manager.get_status()

            assert status["enabled"] is True
            assert status["running"] is True
            assert status["storage_stats"] is not None
            assert "total_files" in status["storage_stats"]
        finally:
            await fresh_manager.stop()

    @pytest.mark.asyncio
    async def test_cleanup_loop_exception_handling(self, fresh_manager, tmp_path):
        """Test that cleanup loop continues after exceptions."""
        attachments_dir = tmp_path / "attachments"
        attachments_dir.mkdir()

        with patch.dict(
            os.environ,
            {
                "AUTO_CLEANUP_ENABLED": "true",
                "CLEANUP_INTERVAL_MINUTES": "0.01",  # Very short for testing
                "ATTACHMENTS_DIR": str(attachments_dir),
            },
        ):
            await fresh_manager.start()

            # Patch cleanup to raise exception
            with patch.object(
                fresh_manager.manager,
                "cleanup_expired_files",
                side_effect=Exception("Test error"),
            ):
                # Wait for a loop iteration
                await asyncio.sleep(0.5)

            # Task should still be running
            assert fresh_manager.task is not None
            assert not fresh_manager.task.done()

            await fresh_manager.stop()

    @pytest.mark.asyncio
    async def test_cleanup_manager_already_running(self, fresh_manager, tmp_path):
        """Test that starting an already running manager is safe (doesn't crash)."""
        attachments_dir = tmp_path / "attachments"
        attachments_dir.mkdir()

        with patch.dict(
            os.environ,
            {"AUTO_CLEANUP_ENABLED": "true", "ATTACHMENTS_DIR": str(attachments_dir)},
        ):
            await fresh_manager.start()

            # Task should be running after first start
            assert fresh_manager.task is not None
            assert fresh_manager.enabled is True

            # Calling start() again should not crash
            await fresh_manager.start()

            # Manager should still have a valid task
            assert fresh_manager.task is not None
            assert fresh_manager.enabled is True

            await fresh_manager.stop()


@pytest.mark.unit
class TestEnsureCleanupStarted:
    """Tests for _ensure_cleanup_started function."""

    @pytest.fixture
    def reset_global_state(self):
        """Reset global cleanup state."""
        import redmine_mcp_server.redmine_handler as handler

        original_initialized = handler._cleanup_initialized
        handler._cleanup_initialized = False

        yield handler

        handler._cleanup_initialized = original_initialized

    @pytest.mark.asyncio
    async def test_ensure_cleanup_started_when_enabled(
        self, reset_global_state, tmp_path
    ):
        """Test lazy initialization when cleanup is enabled."""
        handler = reset_global_state
        attachments_dir = tmp_path / "attachments"
        attachments_dir.mkdir()

        with patch.dict(
            os.environ,
            {"AUTO_CLEANUP_ENABLED": "true", "ATTACHMENTS_DIR": str(attachments_dir)},
        ):
            with patch.object(
                handler.cleanup_manager, "start", new_callable=AsyncMock
            ) as mock_start:
                await handler._ensure_cleanup_started()

                mock_start.assert_called_once()

        assert handler._cleanup_initialized is True

    @pytest.mark.asyncio
    async def test_ensure_cleanup_started_when_disabled(self, reset_global_state):
        """Test lazy initialization when cleanup is disabled."""
        handler = reset_global_state

        with patch.dict(os.environ, {"AUTO_CLEANUP_ENABLED": "false"}):
            await handler._ensure_cleanup_started()

        # Should still mark as initialized to avoid repeated checks
        assert handler._cleanup_initialized is True

    @pytest.mark.asyncio
    async def test_ensure_cleanup_started_idempotent(self, reset_global_state):
        """Test that multiple calls don't reinitialize."""
        handler = reset_global_state
        handler._cleanup_initialized = True

        with patch.object(
            handler.cleanup_manager, "start", new_callable=AsyncMock
        ) as mock_start:
            await handler._ensure_cleanup_started()
            await handler._ensure_cleanup_started()

            mock_start.assert_not_called()
