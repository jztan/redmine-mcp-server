"""File management utilities for attachment downloads."""

import json
from datetime import datetime, timezone
from pathlib import Path


class AttachmentFileManager:
    """Manages downloaded attachment files and cleanup."""

    def __init__(self, attachments_dir: str = "attachments"):
        self.attachments_dir = Path(attachments_dir)
        self.attachments_dir.mkdir(exist_ok=True)

    def cleanup_expired_files(self) -> dict:
        """Remove expired files and return cleanup stats."""
        now = datetime.now(timezone.utc)
        cleaned_files = 0
        cleaned_size = 0

        # Search for metadata.json files in UUID directories with
        # robustness
        try:
            uuid_dirs = [d for d in self.attachments_dir.iterdir() if d.is_dir()]
        except OSError:
            return {"cleaned_files": 0, "cleaned_bytes": 0, "cleaned_mb": 0.0}

        for uuid_dir in uuid_dirs:
            metadata_file = uuid_dir / "metadata.json"
            if not metadata_file.exists():
                continue

            try:
                with open(metadata_file, "r") as f:
                    metadata = json.load(f)

                # Parse expiry timestamp (timezone-aware)
                expires_at_str = metadata.get("expires_at", "")
                if expires_at_str:
                    expires_at = datetime.fromisoformat(
                        expires_at_str.replace("Z", "+00:00")
                    )
                    if now > expires_at:
                        # Remove data file
                        file_path = Path(metadata["file_path"])
                        if file_path.exists():
                            cleaned_size += file_path.stat().st_size
                            file_path.unlink()

                        # Remove metadata
                        metadata_file.unlink()

                        # Remove UUID directory if empty
                        uuid_dir = metadata_file.parent
                        if uuid_dir.exists() and not any(uuid_dir.iterdir()):
                            uuid_dir.rmdir()

                        cleaned_files += 1

            except (json.JSONDecodeError, KeyError, OSError, ValueError):
                # Remove corrupted metadata files and attempt cleanup
                try:
                    uuid_dir = metadata_file.parent
                    metadata_file.unlink()
                    # Try to remove any remaining files in the UUID directory
                    for file_path in uuid_dir.iterdir():
                        if file_path.is_file():
                            file_path.unlink()
                    if uuid_dir.exists() and not any(uuid_dir.iterdir()):
                        uuid_dir.rmdir()
                    cleaned_files += 1
                except OSError:
                    pass  # Ignore cleanup failures

        return {
            "cleaned_files": cleaned_files,
            "cleaned_bytes": cleaned_size,
            "cleaned_mb": round(cleaned_size / 1024 / 1024, 2),
        }

    def get_storage_stats(self) -> dict:
        """Get current storage usage statistics."""
        total_files = 0
        total_size = 0

        # Count files in UUID directories (exclude metadata.json) with error handling
        try:
            uuid_dirs = [d for d in self.attachments_dir.iterdir() if d.is_dir()]
        except OSError:
            return {"total_files": 0, "total_bytes": 0, "total_mb": 0.0}

        for uuid_dir in uuid_dirs:
            try:
                for file_path in uuid_dir.iterdir():
                    if file_path.is_file() and file_path.name != "metadata.json":
                        try:
                            total_files += 1
                            total_size += file_path.stat().st_size
                        except OSError:
                            # Skip files we can't stat (permission issues, etc.)
                            continue
            except OSError:
                # Skip directories we can't access
                continue

        return {
            "total_files": total_files,
            "total_bytes": total_size,
            "total_mb": round(total_size / 1024 / 1024, 2),
        }
