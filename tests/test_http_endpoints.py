"""
Tests for HTTP endpoints in the MCP server.

Tests cover:
- /health endpoint
- /files/{file_id} endpoint (serve_attachment)
- /cleanup/status endpoint
"""

import pytest
import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, AsyncMock
from httpx import ASGITransport, AsyncClient


@pytest.mark.unit
class TestHealthEndpoint:
    """Tests for GET /health endpoint."""

    @pytest.fixture
    def app(self):
        """Get the Starlette app for testing."""
        from redmine_mcp_server.main import app

        return app

    @pytest.mark.asyncio
    async def test_health_check_returns_ok(self, app):
        """Test that /health returns 200 with status ok."""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            with patch(
                "redmine_mcp_server.redmine_handler._ensure_cleanup_started",
                new_callable=AsyncMock,
            ):
                response = await client.get("/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["service"] == "redmine_mcp_tools"

    @pytest.mark.asyncio
    async def test_health_check_initializes_cleanup(self, app):
        """Test that /health triggers cleanup initialization."""
        with patch(
            "redmine_mcp_server.redmine_handler._ensure_cleanup_started",
            new_callable=AsyncMock,
        ) as mock_ensure:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                await client.get("/health")

            mock_ensure.assert_called_once()


@pytest.mark.unit
class TestServeAttachmentEndpoint:
    """Tests for GET /files/{file_id} endpoint."""

    @pytest.fixture
    def app(self):
        """Get the Starlette app for testing."""
        from redmine_mcp_server.main import app

        return app

    @pytest.fixture
    def temp_attachments_dir(self, tmp_path):
        """Create a temporary attachments directory."""
        attachments_dir = tmp_path / "attachments"
        attachments_dir.mkdir()
        return attachments_dir

    @pytest.fixture
    def valid_file_setup(self, temp_attachments_dir):
        """Set up a valid file with metadata."""
        file_id = str(uuid.uuid4())
        uuid_dir = temp_attachments_dir / file_id
        uuid_dir.mkdir()

        # Create test file
        test_file = uuid_dir / "test_document.pdf"
        test_file.write_bytes(b"PDF content here")

        # Create metadata
        expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
        metadata = {
            "file_path": str(test_file),
            "original_filename": "test_document.pdf",
            "content_type": "application/pdf",
            "expires_at": expires_at.isoformat(),
        }
        metadata_file = uuid_dir / "metadata.json"
        metadata_file.write_text(json.dumps(metadata))

        return {
            "file_id": file_id,
            "attachments_dir": temp_attachments_dir,
            "uuid_dir": uuid_dir,
            "test_file": test_file,
            "metadata_file": metadata_file,
        }

    @pytest.mark.asyncio
    async def test_serve_attachment_invalid_uuid(self, app):
        """Test that invalid UUID returns 400."""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/files/not-a-valid-uuid")

        assert response.status_code == 400
        assert "Invalid file ID" in response.text

    @pytest.mark.asyncio
    async def test_serve_attachment_not_found(self, app, temp_attachments_dir):
        """Test that non-existent file returns 404."""
        valid_uuid = str(uuid.uuid4())

        with patch.dict(os.environ, {"ATTACHMENTS_DIR": str(temp_attachments_dir)}):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.get(f"/files/{valid_uuid}")

        assert response.status_code == 404
        assert "not found or expired" in response.text

    @pytest.mark.asyncio
    async def test_serve_attachment_expired(self, app, temp_attachments_dir):
        """Test that expired file returns 404 and cleans up."""
        file_id = str(uuid.uuid4())
        uuid_dir = temp_attachments_dir / file_id
        uuid_dir.mkdir()

        # Create expired metadata
        expired_at = datetime.now(timezone.utc) - timedelta(hours=1)
        test_file = uuid_dir / "expired_file.txt"
        test_file.write_bytes(b"expired content")

        metadata = {
            "file_path": str(test_file),
            "original_filename": "expired_file.txt",
            "content_type": "text/plain",
            "expires_at": expired_at.isoformat(),
        }
        metadata_file = uuid_dir / "metadata.json"
        metadata_file.write_text(json.dumps(metadata))

        with patch.dict(os.environ, {"ATTACHMENTS_DIR": str(temp_attachments_dir)}):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.get(f"/files/{file_id}")

        assert response.status_code == 404
        assert "expired" in response.text.lower()

    @pytest.mark.asyncio
    async def test_serve_attachment_success(self, app, valid_file_setup):
        """Test successful file serving."""
        with patch.dict(
            os.environ, {"ATTACHMENTS_DIR": str(valid_file_setup["attachments_dir"])}
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.get(f"/files/{valid_file_setup['file_id']}")

        assert response.status_code == 200
        assert response.content == b"PDF content here"
        assert "application/pdf" in response.headers.get("content-type", "")

    @pytest.mark.asyncio
    async def test_serve_attachment_corrupted_metadata(self, app, temp_attachments_dir):
        """Test that corrupted metadata returns 500."""
        file_id = str(uuid.uuid4())
        uuid_dir = temp_attachments_dir / file_id
        uuid_dir.mkdir()

        # Create corrupted metadata
        metadata_file = uuid_dir / "metadata.json"
        metadata_file.write_text("not valid json{{{")

        with patch.dict(os.environ, {"ATTACHMENTS_DIR": str(temp_attachments_dir)}):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.get(f"/files/{file_id}")

        assert response.status_code == 500
        assert "Corrupted metadata" in response.text

    @pytest.mark.asyncio
    async def test_serve_attachment_path_traversal_blocked(
        self, app, temp_attachments_dir
    ):
        """Test that path traversal attempts are blocked."""
        file_id = str(uuid.uuid4())
        uuid_dir = temp_attachments_dir / file_id
        uuid_dir.mkdir()

        # Create metadata with path traversal attempt
        metadata = {
            "file_path": "/etc/passwd",  # Attempt to read system file
            "original_filename": "passwd",
            "content_type": "text/plain",
            "expires_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
        }
        metadata_file = uuid_dir / "metadata.json"
        metadata_file.write_text(json.dumps(metadata))

        with patch.dict(os.environ, {"ATTACHMENTS_DIR": str(temp_attachments_dir)}):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.get(f"/files/{file_id}")

        assert response.status_code == 403
        assert "Access denied" in response.text

    @pytest.mark.asyncio
    async def test_serve_attachment_file_missing(self, app, temp_attachments_dir):
        """Test when metadata exists but file is missing."""
        file_id = str(uuid.uuid4())
        uuid_dir = temp_attachments_dir / file_id
        uuid_dir.mkdir()

        # Valid metadata pointing to non-existent file
        missing_file = uuid_dir / "missing_file.txt"
        metadata = {
            "file_path": str(missing_file),
            "original_filename": "missing_file.txt",
            "content_type": "text/plain",
            "expires_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
        }
        metadata_file = uuid_dir / "metadata.json"
        metadata_file.write_text(json.dumps(metadata))

        with patch.dict(os.environ, {"ATTACHMENTS_DIR": str(temp_attachments_dir)}):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.get(f"/files/{file_id}")

        assert response.status_code == 404
        assert "File not found" in response.text


@pytest.mark.unit
class TestCleanupStatusEndpoint:
    """Tests for GET /cleanup/status endpoint."""

    @pytest.fixture
    def app(self):
        """Get the Starlette app for testing."""
        from redmine_mcp_server.main import app

        return app

    @pytest.mark.asyncio
    async def test_cleanup_status_returns_status(self, app):
        """Test that /cleanup/status returns manager status."""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/cleanup/status")

        assert response.status_code == 200
        data = response.json()
        assert "enabled" in data
        assert "running" in data
        assert "interval_seconds" in data

    @pytest.mark.asyncio
    async def test_cleanup_status_with_manager_running(self, app):
        """Test cleanup status when manager is running."""
        from redmine_mcp_server import redmine_handler

        mock_status = {
            "enabled": True,
            "running": True,
            "interval_seconds": 600,
            "storage_stats": {"total_files": 5, "total_mb": 1.5},
        }

        with patch.object(
            redmine_handler.cleanup_manager, "get_status", return_value=mock_status
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.get("/cleanup/status")

            assert response.status_code == 200
            data = response.json()
            assert data["enabled"] is True
            assert data["running"] is True
            assert data["storage_stats"]["total_files"] == 5
