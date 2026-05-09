"""
Security validation tests for attachment functions.

This module contains security-focused tests to ensure that the attachment
download functions properly prevent path traversal attacks and other
security vulnerabilities.
"""

import os
import sys

import pytest
from unittest.mock import patch, MagicMock

# Add the src directory to the path so we can import our modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from redmine_mcp_server.tools.files import (  # noqa: E402
    get_redmine_attachment,
)


@pytest.mark.unit
class TestGetRedmineAttachmentSecurity:
    """Security tests for get_redmine_attachment."""

    def _mock_attachment(self, filename="safe.pdf"):
        att = MagicMock()
        att.filename = filename
        att.content_type = "application/pdf"
        att.content_url = "https://redmine.example.com/attachments/download/1/safe.pdf"
        return att

    def _mock_stream(self, chunks=None):
        response = MagicMock()
        response.iter_content = MagicMock(return_value=iter(chunks or [b"data"]))
        return response

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.redmine")
    @patch("redmine_mcp_server._cleanup._ensure_cleanup_started")
    async def test_path_traversal_filename_sanitized(
        self, mock_cleanup, mock_redmine, tmp_path, monkeypatch
    ):
        """A filename like ../../etc/passwd must be reduced to basename only."""
        monkeypatch.setenv("ATTACHMENTS_DIR", str(tmp_path))
        monkeypatch.delenv("PUBLIC_HOST", raising=False)

        mock_redmine.attachment.get.return_value = self._mock_attachment(
            filename="../../etc/passwd"
        )
        mock_redmine.download.return_value = self._mock_stream()

        result = await get_redmine_attachment(1)

        assert "error" not in result
        # The file written to disk must live inside the UUID dir, not escape it
        file_path = result.get("file_path", "")
        assert "etc" not in file_path or file_path.startswith(str(tmp_path))
        # Basename of path must be "passwd", not a traversal component
        assert os.path.basename(file_path) == "passwd"

    @pytest.mark.asyncio
    @patch("redmine_mcp_server._client.redmine")
    @patch("redmine_mcp_server._cleanup._ensure_cleanup_started")
    async def test_byte_cap_leaves_no_partial_files(
        self, mock_cleanup, mock_redmine, tmp_path, monkeypatch
    ):
        """When the byte cap is exceeded, no partial or temp files remain."""
        monkeypatch.setenv("ATTACHMENTS_DIR", str(tmp_path))
        monkeypatch.setenv("ATTACHMENT_MAX_DOWNLOAD_BYTES", "5")
        monkeypatch.delenv("PUBLIC_HOST", raising=False)

        mock_redmine.attachment.get.return_value = self._mock_attachment()
        mock_redmine.download.return_value = self._mock_stream([b"123456"])

        result = await get_redmine_attachment(1)

        assert "error" in result
        remaining = list(tmp_path.rglob("*"))
        data_files = [p for p in remaining if p.is_file()]
        assert data_files == [], f"Leftover files after cap abort: {data_files}"
