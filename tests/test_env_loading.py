"""
Tests for .env file loading behavior.

These tests verify that the server correctly loads environment variables
from the user's current working directory, fixing issue #40 where pip-installed
packages would fail to find the .env file.
"""

import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest


class TestEnvLoading:
    """Tests for environment configuration loading."""

    def test_env_loading_from_cwd(self, tmp_path):
        """Test that .env is loaded from current working directory.

        This test verifies the fix for issue #40 where pip-installed packages
        failed to load .env from the user's working directory.
        """
        # Create a .env file in a temporary directory
        env_file = tmp_path / ".env"
        test_url = "http://test-redmine-from-cwd.example.com"
        test_api_key = "test_api_key_12345"
        env_file.write_text(
            f"REDMINE_URL={test_url}\n" f"REDMINE_API_KEY={test_api_key}\n"
        )

        # Create a test script that imports the module and checks the env vars
        test_script = tmp_path / "test_env_check.py"
        test_script.write_text(
            """
import sys
import os

# Clear any existing env vars to ensure we're testing fresh loading
for key in ['REDMINE_URL', 'REDMINE_API_KEY', 'REDMINE_USERNAME', 'REDMINE_PASSWORD']:
    os.environ.pop(key, None)

# Import the module which triggers env loading
from redmine_mcp_server.redmine_handler import REDMINE_URL, REDMINE_API_KEY

# Print the values for verification
print(f"REDMINE_URL={REDMINE_URL}")
print(f"REDMINE_API_KEY={REDMINE_API_KEY}")
"""
        )

        # Run the test script from the temp directory (simulating user's project)
        result = subprocess.run(
            [sys.executable, str(test_script)],
            cwd=str(tmp_path),
            capture_output=True,
            text=True,
            env={
                **os.environ,
                "PYTHONPATH": str(Path(__file__).parent.parent / "src"),
            },
        )

        # Verify the output
        assert result.returncode == 0, f"Script failed: {result.stderr}"
        assert f"REDMINE_URL={test_url}" in result.stdout, (
            f"Expected REDMINE_URL to be loaded from CWD .env. "
            f"stdout: {result.stdout}, stderr: {result.stderr}"
        )
        assert f"REDMINE_API_KEY={test_api_key}" in result.stdout, (
            f"Expected REDMINE_API_KEY to be loaded from CWD .env. "
            f"stdout: {result.stdout}, stderr: {result.stderr}"
        )

    def test_env_loading_warning_when_missing_url(self, tmp_path, capsys):
        """Test that warning is shown when REDMINE_URL is missing."""
        # Create an empty .env file
        env_file = tmp_path / ".env"
        env_file.write_text("# Empty config\n")

        # Create a test script that imports the module
        test_script = tmp_path / "test_warning.py"
        test_script.write_text(
            """
import sys
import os

# Clear any existing env vars
for key in ['REDMINE_URL', 'REDMINE_API_KEY', 'REDMINE_USERNAME', 'REDMINE_PASSWORD']:
    os.environ.pop(key, None)

# Import the module which triggers env loading and warnings
from redmine_mcp_server import redmine_handler
"""
        )

        result = subprocess.run(
            [sys.executable, str(test_script)],
            cwd=str(tmp_path),
            capture_output=True,
            text=True,
            env={
                **os.environ,
                "PYTHONPATH": str(Path(__file__).parent.parent / "src"),
            },
        )

        # The warning should be printed to stdout (via print())
        assert "WARNING" in result.stdout or "REDMINE_URL not set" in result.stdout, (
            f"Expected warning about missing REDMINE_URL. "
            f"stdout: {result.stdout}, stderr: {result.stderr}"
        )

    def test_env_loading_warning_when_missing_auth(self, tmp_path):
        """Test that warning is shown when authentication is missing."""
        # Create .env with URL but no auth
        env_file = tmp_path / ".env"
        env_file.write_text("REDMINE_URL=http://example.com\n")

        test_script = tmp_path / "test_auth_warning.py"
        test_script.write_text(
            """
import sys
import os

# Clear any existing env vars
for key in ['REDMINE_URL', 'REDMINE_API_KEY', 'REDMINE_USERNAME', 'REDMINE_PASSWORD']:
    os.environ.pop(key, None)

from redmine_mcp_server import redmine_handler
"""
        )

        result = subprocess.run(
            [sys.executable, str(test_script)],
            cwd=str(tmp_path),
            capture_output=True,
            text=True,
            env={
                **os.environ,
                "PYTHONPATH": str(Path(__file__).parent.parent / "src"),
            },
        )

        # Check for authentication warning
        assert (
            "WARNING" in result.stdout or "authentication" in result.stdout.lower()
        ), (
            f"Expected warning about missing authentication. "
            f"stdout: {result.stdout}, stderr: {result.stderr}"
        )

    def test_env_paths_priority(self):
        """Test that _env_paths list has correct priority order."""
        from redmine_mcp_server.redmine_handler import _env_paths

        assert len(_env_paths) >= 2, "Expected at least 2 env paths"
        # First path should be CWD
        assert (
            _env_paths[0] == Path.cwd() / ".env"
        ), "First env path should be current working directory"

    def test_cwd_env_takes_precedence_over_package_env(self, tmp_path):
        """Test that CWD .env takes precedence over package directory .env."""
        # Create .env in temp directory with specific values
        env_file = tmp_path / ".env"
        cwd_url = "http://cwd-takes-precedence.example.com"
        env_file.write_text(f"REDMINE_URL={cwd_url}\n" f"REDMINE_API_KEY=cwd_key\n")

        test_script = tmp_path / "test_precedence.py"
        test_script.write_text(
            """
import os

# Clear any existing env vars
for key in ['REDMINE_URL', 'REDMINE_API_KEY', 'REDMINE_USERNAME', 'REDMINE_PASSWORD']:
    os.environ.pop(key, None)

from redmine_mcp_server.redmine_handler import REDMINE_URL

print(f"REDMINE_URL={REDMINE_URL}")
"""
        )

        result = subprocess.run(
            [sys.executable, str(test_script)],
            cwd=str(tmp_path),
            capture_output=True,
            text=True,
            env={
                **os.environ,
                "PYTHONPATH": str(Path(__file__).parent.parent / "src"),
            },
        )

        assert result.returncode == 0, f"Script failed: {result.stderr}"
        assert f"REDMINE_URL={cwd_url}" in result.stdout, (
            f"CWD .env should take precedence. " f"stdout: {result.stdout}"
        )


class TestEnvLoadingUnit:
    """Unit tests that don't require subprocess."""

    def test_env_paths_variable_exists(self):
        """Test that _env_paths is defined in the module."""
        from redmine_mcp_server import redmine_handler

        assert hasattr(
            redmine_handler, "_env_paths"
        ), "_env_paths should be defined for env file search"

    def test_env_paths_contains_cwd(self):
        """Test that _env_paths contains current working directory."""
        from redmine_mcp_server.redmine_handler import _env_paths

        cwd_env = Path.cwd() / ".env"
        assert (
            cwd_env in _env_paths
        ), "Current working directory .env should be in search paths"

    def test_env_loaded_flag_exists(self):
        """Test that _env_loaded flag is defined."""
        from redmine_mcp_server import redmine_handler

        assert hasattr(
            redmine_handler, "_env_loaded"
        ), "_env_loaded flag should be defined"
