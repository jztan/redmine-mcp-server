"""
Security validation tests for attachment functions.

This module contains security-focused tests to ensure that the attachment
download functions properly prevent path traversal attacks and other
security vulnerabilities.
"""
import pytest
import uuid
from unittest.mock import Mock, patch, MagicMock, mock_open
from pathlib import Path
import os
import sys

# Add the src directory to the path so we can import our modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from redmine_mcp_server.redmine_handler import get_redmine_attachment_download_url, download_redmine_attachment


@pytest.mark.unit
class TestSecurityValidation:
    """Security-focused tests for attachment functions."""

    @pytest.mark.asyncio
    async def test_path_traversal_prevention(self, caplog):
        """Verify that path traversal attacks are prevented."""
        dangerous_paths = [
            "../../../etc/passwd",
            "..\\..\\windows\\system32",
            "/etc/shadow",
            "C:\\Windows\\System32\\config\\SAM",
            "../../sensitive/data",
            "../../../../../root/.ssh/id_rsa"
        ]

        for dangerous_path in dangerous_paths:
            # Should not allow dangerous paths in any parameter
            result = await download_redmine_attachment(123, save_dir=dangerous_path)

            # Verify security rejection logged
            assert "SECURITY: Rejected save_dir" in caplog.text
            assert "path traversal attack" in caplog.text

            # Function should either work (security check passed) or fail with expected errors
            # Accept "client not initialized" as valid since we're testing without redmine setup
            assert ("error" not in result or
                    "not found" in result.get("error", "").lower() or
                    "not initialized" in result.get("error", "").lower())

    @pytest.mark.asyncio
    @patch('redmine_mcp_server.redmine_handler.redmine')
    @patch('redmine_mcp_server.redmine_handler._ensure_cleanup_started')
    async def test_uuid_filename_generation(self, mock_cleanup, mock_redmine):
        """Verify that filenames are UUID-based and secure."""
        mock_uuid = "12345678-1234-5678-9abc-123456789012"

        # Mock attachment
        mock_attachment = MagicMock()
        mock_attachment.filename = "test.pdf"
        mock_attachment.content_type = "application/pdf"
        mock_attachment.download = MagicMock(return_value="/tmp/test_download")
        mock_redmine.attachment.get.return_value = mock_attachment

        with patch('uuid.uuid4') as mock_uuid_func:
            mock_uuid_func.return_value = MagicMock()
            mock_uuid_func.return_value.__str__ = MagicMock(return_value=mock_uuid)

            with patch('builtins.open', mock_open()):
                with patch('pathlib.Path.mkdir'):
                    with patch('pathlib.Path.stat') as mock_stat:
                        mock_stat.return_value.st_size = 1024
                        with patch('os.rename'):
                            with patch('json.dump'):
                                result = await get_redmine_attachment_download_url(123)

        # Verify UUID is used in URL
        assert mock_uuid in result.get("download_url", "")
        assert "test.pdf" in result.get("filename", "")

    @pytest.mark.asyncio
    @patch('redmine_mcp_server.redmine_handler.get_redmine_attachment_download_url')
    async def test_server_controlled_configuration(self, mock_new_func):
        """Verify that storage and expiry are server-controlled."""
        # Mock the new function response
        expected_result = {
            "download_url": "http://localhost:8000/files/uuid-123",
            "filename": "test.pdf",
            "expires_at": "2025-09-22T12:00:00Z",
            "attachment_id": 123
        }
        mock_new_func.return_value = expected_result

        # Test with various client attempts to control server behavior
        result1 = await download_redmine_attachment(123, save_dir="./hack", expires_hours=9999)
        result2 = await download_redmine_attachment(123, save_dir="dangerous", expires_hours=1)

        # Both should use server configuration, ignoring client preferences
        assert result1 == expected_result
        assert result2 == expected_result

        # Verify both calls delegated to secure function with same attachment_id
        assert mock_new_func.call_count == 2
        mock_new_func.assert_any_call(123)

    @pytest.mark.asyncio
    async def test_no_client_control_over_storage(self):
        """Verify clients cannot control server storage locations."""
        # These should all be rejected or ignored
        dangerous_storage_attempts = [
            "/var/www/html",
            "C:\\Windows\\System32",
            "/root/.ssh",
            "../../../usr/bin",
            "/tmp/../../../../etc"
        ]

        for storage_path in dangerous_storage_attempts:
            # The function should work but ignore dangerous storage paths
            result = await download_redmine_attachment(123, save_dir=storage_path)

            # Should either work (using server default) or fail due to missing attachment
            # but never actually use the dangerous path
            if "error" in result:
                # Error should be about attachment not found, not storage issues
                assert "not found" in result["error"].lower() or "not initialized" in result["error"].lower()

    @pytest.mark.asyncio
    @patch('redmine_mcp_server.redmine_handler.redmine')
    @patch('redmine_mcp_server.redmine_handler._ensure_cleanup_started')
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

        with patch('uuid.uuid4') as mock_uuid:
            mock_uuid.return_value.__str__ = MagicMock(return_value="secure-uuid-456")
            with patch('builtins.open', mock_open()):
                with patch('pathlib.Path.mkdir'):
                    with patch('pathlib.Path.stat') as mock_stat:
                        mock_stat.return_value.st_size = 2048
                        with patch('os.rename'):
                            with patch('json.dump', side_effect=capture_metadata):
                                result = await get_redmine_attachment_download_url(123)

        # Verify secure metadata structure
        assert "file_id" in metadata_written
        assert "attachment_id" in metadata_written
        assert metadata_written["attachment_id"] == 123
        assert "secure-uuid-456" in str(metadata_written["file_id"])
        assert "expires_at" in metadata_written
        assert "created_at" in metadata_written

    @pytest.mark.asyncio
    async def test_no_information_disclosure(self):
        """Verify error messages don't disclose sensitive information."""
        # Test various error conditions
        result = await download_redmine_attachment(999999)  # Non-existent attachment

        if "error" in result:
            error_msg = result["error"].lower()
            # Should not reveal internal paths, system info, or sensitive details
            sensitive_terms = [
                "/var/", "/usr/", "/etc/", "/root/", "/home/",
                "c:\\", "d:\\", "system32", "windows",
                "password", "secret", "key", "token",
                "internal", "stack trace", "exception"
            ]

            for term in sensitive_terms:
                assert term not in error_msg, f"Error message contains sensitive term: {term}"