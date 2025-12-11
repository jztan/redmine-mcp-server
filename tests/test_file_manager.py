"""Tests for AttachmentFileManager.

This module tests the file management utilities for attachment downloads,
including cleanup of expired files and storage statistics.
"""

import json
import pytest
from pathlib import Path
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

from redmine_mcp_server.file_manager import AttachmentFileManager


def create_attachment(
    base_dir: Path, file_id: str, content: bytes, expires_at: str
) -> Path:
    """Helper to create attachment with metadata for testing.

    Args:
        base_dir: Base directory for attachments
        file_id: UUID-like identifier for the attachment
        content: File content as bytes
        expires_at: ISO format expiration timestamp

    Returns:
        Path to the created UUID directory
    """
    uuid_dir = base_dir / file_id
    uuid_dir.mkdir(exist_ok=True)

    file_path = uuid_dir / "test_file.txt"
    file_path.write_bytes(content)

    metadata = {
        "file_id": file_id,
        "file_path": str(file_path),
        "expires_at": expires_at,
        "original_filename": "test_file.txt",
    }

    metadata_path = uuid_dir / "metadata.json"
    metadata_path.write_text(json.dumps(metadata))

    return uuid_dir


@pytest.mark.unit
class TestAttachmentFileManagerConstructor:
    """Test cases for AttachmentFileManager constructor."""

    def test_init_creates_directory(self, tmp_path):
        """Test that constructor creates directory if missing."""
        new_dir = tmp_path / "new_attachments"
        assert not new_dir.exists()

        manager = AttachmentFileManager(str(new_dir))

        assert new_dir.exists()
        assert new_dir.is_dir()
        assert manager.attachments_dir == new_dir

    def test_init_existing_directory(self, tmp_path):
        """Test that constructor works with existing directory."""
        existing_dir = tmp_path / "existing"
        existing_dir.mkdir()
        test_file = existing_dir / "existing_file.txt"
        test_file.write_text("existing content")

        manager = AttachmentFileManager(str(existing_dir))

        assert existing_dir.exists()
        assert test_file.exists()
        assert manager.attachments_dir == existing_dir


@pytest.mark.unit
class TestGetStorageStats:
    """Test cases for get_storage_stats method."""

    @pytest.fixture
    def file_manager(self, tmp_path):
        """Create AttachmentFileManager with temp directory."""
        return AttachmentFileManager(str(tmp_path))

    def test_stats_single_file(self, tmp_path, file_manager):
        """Test correct count and size for one file."""
        content = b"Hello, World!"
        expires_at = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        create_attachment(tmp_path, "uuid-1", content, expires_at)

        stats = file_manager.get_storage_stats()

        assert stats["total_files"] == 1
        assert stats["total_bytes"] == len(content)
        assert stats["total_mb"] == round(len(content) / 1024 / 1024, 2)

    def test_stats_multiple_files(self, tmp_path, file_manager):
        """Test correct totals for multiple files."""
        content1 = b"File one content"
        content2 = b"File two has more content here"
        content3 = b"Third file"
        expires_at = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()

        create_attachment(tmp_path, "uuid-1", content1, expires_at)
        create_attachment(tmp_path, "uuid-2", content2, expires_at)
        create_attachment(tmp_path, "uuid-3", content3, expires_at)

        stats = file_manager.get_storage_stats()

        expected_bytes = len(content1) + len(content2) + len(content3)
        assert stats["total_files"] == 3
        assert stats["total_bytes"] == expected_bytes
        assert stats["total_mb"] == round(expected_bytes / 1024 / 1024, 2)

    def test_stats_excludes_metadata(self, tmp_path, file_manager):
        """Test that metadata.json is not counted in stats."""
        content = b"Test content"
        expires_at = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        create_attachment(tmp_path, "uuid-1", content, expires_at)

        stats = file_manager.get_storage_stats()

        # Should only count the data file, not metadata.json
        assert stats["total_files"] == 1
        assert stats["total_bytes"] == len(content)

    def test_stats_empty_directory(self, file_manager):
        """Test returns zeros for empty directory."""
        stats = file_manager.get_storage_stats()

        assert stats["total_files"] == 0
        assert stats["total_bytes"] == 0
        assert stats["total_mb"] == 0.0

    def test_stats_missing_directory(self, tmp_path):
        """Test handles OSError gracefully when directory doesn't exist."""
        manager = AttachmentFileManager(str(tmp_path / "attachments"))
        # Remove the directory after creation
        manager.attachments_dir.rmdir()

        stats = manager.get_storage_stats()

        assert stats["total_files"] == 0
        assert stats["total_bytes"] == 0
        assert stats["total_mb"] == 0.0

    def test_stats_permission_denied(self, tmp_path, file_manager):
        """Test continues on unreadable files/directories."""
        content = b"Test content"
        expires_at = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        create_attachment(tmp_path, "uuid-1", content, expires_at)

        # Mock stat to raise OSError for individual files
        original_stat = Path.stat

        def mock_stat(self, **kwargs):
            if self.name == "test_file.txt":
                raise OSError("Permission denied")
            return original_stat(self, **kwargs)

        with patch.object(Path, "stat", mock_stat):
            stats = file_manager.get_storage_stats()

        # Should continue and return partial results (0 since file stat failed)
        assert stats["total_files"] == 0
        assert stats["total_bytes"] == 0


@pytest.mark.unit
class TestCleanupExpiredFilesHappyPath:
    """Test cases for cleanup_expired_files - happy path scenarios."""

    @pytest.fixture
    def file_manager(self, tmp_path):
        """Create AttachmentFileManager with temp directory."""
        return AttachmentFileManager(str(tmp_path))

    def test_cleanup_single_expired_file(self, tmp_path, file_manager):
        """Test one expired file is cleaned."""
        content = b"Expired content"
        expired_time = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        uuid_dir = create_attachment(tmp_path, "uuid-expired", content, expired_time)

        result = file_manager.cleanup_expired_files()

        assert result["cleaned_files"] == 1
        assert result["cleaned_bytes"] == len(content)
        assert not uuid_dir.exists()

    def test_cleanup_multiple_expired_files(self, tmp_path, file_manager):
        """Test multiple expired files are cleaned."""
        content1 = b"First expired"
        content2 = b"Second expired file"
        expired_time = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()

        uuid_dir1 = create_attachment(tmp_path, "uuid-1", content1, expired_time)
        uuid_dir2 = create_attachment(tmp_path, "uuid-2", content2, expired_time)

        result = file_manager.cleanup_expired_files()

        assert result["cleaned_files"] == 2
        assert result["cleaned_bytes"] == len(content1) + len(content2)
        assert not uuid_dir1.exists()
        assert not uuid_dir2.exists()

    def test_cleanup_keeps_non_expired_files(self, tmp_path, file_manager):
        """Test non-expired files are untouched."""
        content = b"Not expired yet"
        future_time = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        uuid_dir = create_attachment(tmp_path, "uuid-valid", content, future_time)

        result = file_manager.cleanup_expired_files()

        assert result["cleaned_files"] == 0
        assert result["cleaned_bytes"] == 0
        assert uuid_dir.exists()
        assert (uuid_dir / "test_file.txt").exists()
        assert (uuid_dir / "metadata.json").exists()

    def test_cleanup_mixed_files(self, tmp_path, file_manager):
        """Test mix of expired and non-expired files."""
        expired_content = b"This one is expired"
        valid_content = b"This one is still valid"

        expired_time = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        future_time = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()

        expired_dir = create_attachment(
            tmp_path, "uuid-expired", expired_content, expired_time
        )
        valid_dir = create_attachment(tmp_path, "uuid-valid", valid_content, future_time)

        result = file_manager.cleanup_expired_files()

        assert result["cleaned_files"] == 1
        assert result["cleaned_bytes"] == len(expired_content)
        assert not expired_dir.exists()
        assert valid_dir.exists()

    def test_cleanup_returns_accurate_stats(self, tmp_path, file_manager):
        """Test stats (files, bytes, MB) are correct."""
        content = b"X" * 1024 * 1024  # 1 MB
        expired_time = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        create_attachment(tmp_path, "uuid-1mb", content, expired_time)

        result = file_manager.cleanup_expired_files()

        assert result["cleaned_files"] == 1
        assert result["cleaned_bytes"] == 1024 * 1024
        assert result["cleaned_mb"] == 1.0


@pytest.mark.unit
class TestCleanupExpiredFilesErrorHandling:
    """Test cases for cleanup_expired_files - error handling scenarios."""

    @pytest.fixture
    def file_manager(self, tmp_path):
        """Create AttachmentFileManager with temp directory."""
        return AttachmentFileManager(str(tmp_path))

    def test_cleanup_corrupted_json(self, tmp_path, file_manager):
        """Test handles malformed JSON in metadata."""
        uuid_dir = tmp_path / "uuid-corrupted"
        uuid_dir.mkdir()

        # Create corrupted metadata.json
        metadata_path = uuid_dir / "metadata.json"
        metadata_path.write_text("{ invalid json }")

        # Create a data file
        data_file = uuid_dir / "data.txt"
        data_file.write_text("some data")

        result = file_manager.cleanup_expired_files()

        # Corrupted files should be cleaned up
        assert result["cleaned_files"] == 1
        # Size is NOT counted for corrupted files
        assert result["cleaned_bytes"] == 0
        assert not uuid_dir.exists()

    def test_cleanup_missing_metadata_fields(self, tmp_path, file_manager):
        """Test handles missing expires_at/file_path fields."""
        uuid_dir = tmp_path / "uuid-incomplete"
        uuid_dir.mkdir()

        # Create metadata without file_path
        metadata = {"file_id": "uuid-incomplete", "expires_at": "2020-01-01T00:00:00Z"}
        metadata_path = uuid_dir / "metadata.json"
        metadata_path.write_text(json.dumps(metadata))

        data_file = uuid_dir / "data.txt"
        data_file.write_text("some data")

        result = file_manager.cleanup_expired_files()

        # Should be cleaned due to KeyError on file_path access
        assert result["cleaned_files"] == 1
        assert not uuid_dir.exists()

    def test_cleanup_file_already_deleted(self, tmp_path, file_manager):
        """Test handles file gone before cleanup."""
        uuid_dir = tmp_path / "uuid-missing-file"
        uuid_dir.mkdir()

        # Create metadata pointing to non-existent file
        metadata = {
            "file_id": "uuid-missing-file",
            "file_path": str(uuid_dir / "nonexistent.txt"),
            "expires_at": (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
        }
        metadata_path = uuid_dir / "metadata.json"
        metadata_path.write_text(json.dumps(metadata))

        result = file_manager.cleanup_expired_files()

        # Should still clean up the metadata and directory
        assert result["cleaned_files"] == 1
        assert result["cleaned_bytes"] == 0  # No file to count
        assert not uuid_dir.exists()

    def test_cleanup_permission_denied(self, tmp_path, file_manager):
        """Test handles OSError on file deletion gracefully.

        When unlink fails with OSError, the code catches it and attempts cleanup.
        The cleanup path (lines 62-73) tries to delete metadata.json first,
        then remaining files. If all cleanup attempts fail, it silently passes.
        """
        content = b"Cannot delete me"
        expired_time = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        uuid_dir = create_attachment(tmp_path, "uuid-locked", content, expired_time)

        # Mock unlink to raise OSError for data files (but allow metadata.json)
        original_unlink = Path.unlink

        def mock_unlink(self, **kwargs):
            if self.name == "test_file.txt":
                raise OSError("Permission denied")
            return original_unlink(self, **kwargs)

        with patch.object(Path, "unlink", mock_unlink):
            result = file_manager.cleanup_expired_files()

        # The cleanup handles error gracefully:
        # 1. First unlink of data file fails (OSError)
        # 2. Exception caught, enters cleanup path (line 62)
        # 3. metadata.json is deleted successfully
        # 4. Attempts to delete remaining files, but data file deletion fails again
        # 5. rmdir fails because directory is not empty
        # 6. Inner OSError caught, silently passes (line 73)
        # Result: cleaned_files is NOT incremented because inner cleanup failed
        assert result["cleaned_files"] == 0

        # The directory still exists because cleanup failed
        assert uuid_dir.exists()
        # metadata.json was deleted in cleanup attempt
        assert not (uuid_dir / "metadata.json").exists()
        # data file still exists due to permission error
        assert (uuid_dir / "test_file.txt").exists()

    def test_cleanup_empty_directory(self, file_manager):
        """Test empty attachments dir returns zero stats."""
        result = file_manager.cleanup_expired_files()

        assert result["cleaned_files"] == 0
        assert result["cleaned_bytes"] == 0
        assert result["cleaned_mb"] == 0.0

    def test_cleanup_empty_expires_at(self, tmp_path, file_manager):
        """Test empty expires_at string means file is NOT cleaned."""
        uuid_dir = tmp_path / "uuid-no-expiry"
        uuid_dir.mkdir()

        # Create metadata with empty expires_at
        file_path = uuid_dir / "test_file.txt"
        file_path.write_text("content")

        metadata = {
            "file_id": "uuid-no-expiry",
            "file_path": str(file_path),
            "expires_at": "",  # Empty string
        }
        metadata_path = uuid_dir / "metadata.json"
        metadata_path.write_text(json.dumps(metadata))

        result = file_manager.cleanup_expired_files()

        # File should NOT be cleaned because expires_at is empty
        assert result["cleaned_files"] == 0
        assert uuid_dir.exists()
        assert file_path.exists()


@pytest.mark.unit
class TestCleanupExpiredFilesTimezone:
    """Test cases for cleanup_expired_files - timezone handling."""

    @pytest.fixture
    def file_manager(self, tmp_path):
        """Create AttachmentFileManager with temp directory."""
        return AttachmentFileManager(str(tmp_path))

    def test_cleanup_utc_z_format(self, tmp_path, file_manager):
        """Test parses '2025-01-01T00:00:00Z' format correctly."""
        content = b"Z format timestamp"
        # Use a definitely past date with Z suffix
        uuid_dir = create_attachment(
            tmp_path, "uuid-z-format", content, "2020-01-01T00:00:00Z"
        )

        result = file_manager.cleanup_expired_files()

        assert result["cleaned_files"] == 1
        assert not uuid_dir.exists()

    def test_cleanup_timezone_offset_format(self, tmp_path, file_manager):
        """Test parses '+00:00' format correctly."""
        content = b"Offset format timestamp"
        # Use a definitely past date with +00:00 suffix
        uuid_dir = create_attachment(
            tmp_path, "uuid-offset-format", content, "2020-01-01T00:00:00+00:00"
        )

        result = file_manager.cleanup_expired_files()

        assert result["cleaned_files"] == 1
        assert not uuid_dir.exists()
