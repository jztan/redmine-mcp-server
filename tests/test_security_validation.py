"""
Security validation tests for attachment functions.

This module contains security-focused tests to ensure that the attachment
download functions properly prevent path traversal attacks and other
security vulnerabilities.
"""

import os
import sys

import pytest
from unittest.mock import patch, MagicMock, mock_open

# Add the src directory to the path so we can import our modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from redmine_mcp_server.redmine_handler import (  # noqa: E402
    get_redmine_attachment_download_url,
)


@pytest.mark.unit
class TestSecurityValidation:
    """Security-focused tests for attachment functions."""

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    @patch("redmine_mcp_server.redmine_handler._ensure_cleanup_started")
    async def test_uuid_filename_generation(self, mock_cleanup, mock_redmine):
        """Verify that filenames are UUID-based and secure."""
        mock_uuid = "12345678-1234-5678-9abc-123456789012"

        # Mock attachment
        mock_attachment = MagicMock()
        mock_attachment.filename = "test.pdf"
        mock_attachment.content_type = "application/pdf"
        mock_attachment.download = MagicMock(return_value="/tmp/test_download")
        mock_redmine.attachment.get.return_value = mock_attachment

        with patch("uuid.uuid4") as mock_uuid_func:
            mock_uuid_func.return_value = MagicMock()
            mock_uuid_func.return_value.__str__ = MagicMock(return_value=mock_uuid)

            with patch("builtins.open", mock_open()):
                with patch("pathlib.Path.mkdir"):
                    with patch("pathlib.Path.stat") as mock_stat:
                        mock_stat.return_value.st_size = 1024
                        with patch("os.rename"):
                            with patch("json.dump"):
                                result = await get_redmine_attachment_download_url(123)

        # Verify UUID is used in URL
        assert mock_uuid in result.get("download_url", "")
        assert "test.pdf" in result.get("filename", "")

    @pytest.mark.asyncio
    @patch("redmine_mcp_server.redmine_handler.redmine")
    @patch("redmine_mcp_server.redmine_handler._ensure_cleanup_started")
    async def test_secure_metadata_storage(self, mock_cleanup, mock_redmine):
        """Verify metadata is stored securely with proper validation."""
        # Mock successful attachment retrieval
        mock_attachment = MagicMock()
        mock_attachment.filename = "safe_file.pdf"
        mock_attachment.content_type = "application/pdf"
        mock_attachment.download = MagicMock(return_value="/tmp/downloaded")
        mock_redmine.attachment.get.return_value = mock_attachment

        metadata_written = {}

        def capture_metadata(data, f=None, **kwargs):
            metadata_written.update(data)

        with patch("uuid.uuid4") as mock_uuid:
            mock_uuid.return_value.__str__ = MagicMock(return_value="secure-uuid-456")
            with patch("builtins.open", mock_open()):
                with patch("pathlib.Path.mkdir"):
                    with patch("pathlib.Path.stat") as mock_stat:
                        mock_stat.return_value.st_size = 2048
                        with patch("os.rename"):
                            with patch("json.dump", side_effect=capture_metadata):
                                await get_redmine_attachment_download_url(123)

        # Verify secure metadata structure
        assert "file_id" in metadata_written
        assert "attachment_id" in metadata_written
        assert metadata_written["attachment_id"] == 123
        assert "secure-uuid-456" in str(metadata_written["file_id"])
        assert "expires_at" in metadata_written
        assert "created_at" in metadata_written
