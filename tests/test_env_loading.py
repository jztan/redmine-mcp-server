"""
Test cases for environment variable loading from .env file.

This module tests that the .env file is correctly loaded from the current
working directory where the user runs the server, fixing the issue where
environment variables were only loaded from the package-relative path.
"""

import os
import sys
import pytest
import tempfile
import shutil
import subprocess
from pathlib import Path


# Test scripts executed in subprocesses for clean environment testing
LOAD_DOTENV_SCRIPT = """
import os
from dotenv import load_dotenv
load_dotenv()
print("REDMINE_URL=" + str(os.getenv('REDMINE_URL')))
print("REDMINE_API_KEY=" + str(os.getenv('REDMINE_API_KEY')))
"""

LOAD_PRIORITY_SCRIPT = """
import os
import sys
from dotenv import load_dotenv
# First load from current directory (simulating our fix)
load_dotenv()
# Then try to load from another location (this shouldn't override)
load_dotenv(dotenv_path=sys.argv[1])
print("REDMINE_URL=" + str(os.getenv('REDMINE_URL')))
print("REDMINE_API_KEY=" + str(os.getenv('REDMINE_API_KEY')))
"""

LOAD_HANDLER_SCRIPT = """
import os
from redmine_mcp_server import redmine_handler
print("REDMINE_URL=" + str(os.getenv('REDMINE_URL')))
print("REDMINE_API_KEY=" + str(os.getenv('REDMINE_API_KEY')))
print("REDMINE_CLIENT_INITIALIZED=" + str(redmine_handler.redmine is not None))
"""


def get_clean_env():
    """Get environment variables without Redmine-related vars."""
    excluded_keys = ["REDMINE_URL", "REDMINE_API_KEY",
                     "REDMINE_USERNAME", "REDMINE_PASSWORD"]
    return {k: v for k, v in os.environ.items() if k not in excluded_keys}


class TestEnvLoading:
    """Test cases for .env file loading behavior."""

    @pytest.fixture
    def temp_project_dir(self):
        """Create a temporary directory simulating a user's project directory."""
        temp_dir = tempfile.mkdtemp(prefix="redmine_mcp_test_")
        yield temp_dir
        # Cleanup
        shutil.rmtree(temp_dir, ignore_errors=True)

    @pytest.mark.unit
    def test_load_dotenv_from_current_directory(self, temp_project_dir):
        """Test that .env is loaded from current working directory.

        This tests the fix for the issue where users' .env files in their
        project directories were not being loaded because load_dotenv was
        using a path relative to the module location.

        We use a subprocess to ensure a clean environment without pre-loaded
        environment variables from the test process.
        """
        # Create a .env file in the temp directory (simulating user's project)
        env_file = Path(temp_project_dir) / ".env"
        env_file.write_text(
            "REDMINE_URL=https://test-from-cwd.example.com\n"
            "REDMINE_API_KEY=test_api_key_from_cwd\n"
        )

        result = subprocess.run(
            [sys.executable, "-c", LOAD_DOTENV_SCRIPT],
            cwd=temp_project_dir,
            capture_output=True,
            text=True,
            env=get_clean_env()
        )

        assert "REDMINE_URL=https://test-from-cwd.example.com" in result.stdout
        assert "REDMINE_API_KEY=test_api_key_from_cwd" in result.stdout

    @pytest.mark.unit
    def test_env_loading_priority(self, temp_project_dir):
        """Test that current working directory .env takes priority.

        When both the current working directory and the package-relative
        location have .env files, the current working directory should
        be loaded first (giving it priority since load_dotenv doesn't
        override existing variables by default).
        """
        # Create a .env file in the temp directory
        env_file = Path(temp_project_dir) / ".env"
        env_file.write_text(
            "REDMINE_URL=https://user-project.example.com\n"
            "REDMINE_API_KEY=user_api_key\n"
        )

        # Create another temp directory with different .env
        other_dir = tempfile.mkdtemp()
        other_env = Path(other_dir) / ".env"
        other_env.write_text(
            "REDMINE_URL=https://other-location.example.com\n"
            "REDMINE_API_KEY=other_api_key\n"
        )

        try:
            result = subprocess.run(
                [sys.executable, "-c", LOAD_PRIORITY_SCRIPT, str(other_env)],
                cwd=temp_project_dir,
                capture_output=True,
                text=True,
                env=get_clean_env()
            )

            # The first loaded values should be preserved
            assert "REDMINE_URL=https://user-project.example.com" in result.stdout
            assert "REDMINE_API_KEY=user_api_key" in result.stdout
        finally:
            shutil.rmtree(other_dir, ignore_errors=True)

    @pytest.mark.unit
    def test_redmine_handler_loads_env_from_cwd(self, temp_project_dir):
        """Test that redmine_handler.py loads .env from current working directory.

        This is the actual test for the bug fix - verifying that when the
        module is imported from a user's project directory, their .env file
        is loaded and used to initialize the Redmine client.

        We use a subprocess to ensure the module is freshly imported in a clean
        environment.
        """
        # Create a .env file in the temp directory
        env_file = Path(temp_project_dir) / ".env"
        env_file.write_text(
            "REDMINE_URL=https://test-redmine-server.example.com\n"
            "REDMINE_API_KEY=test_api_key_12345\n"
        )

        result = subprocess.run(
            [sys.executable, "-c", LOAD_HANDLER_SCRIPT],
            cwd=temp_project_dir,
            capture_output=True,
            text=True,
            env=get_clean_env()
        )

        # Verify environment variables were loaded
        assert "REDMINE_URL=https://test-redmine-server.example.com" in result.stdout, (
            f"Expected REDMINE_URL to be loaded from .env in cwd. "
            f"stdout: {result.stdout}, stderr: {result.stderr}"
        )
        assert "REDMINE_API_KEY=test_api_key_12345" in result.stdout

        # Verify the Redmine client was initialized
        assert "REDMINE_CLIENT_INITIALIZED=True" in result.stdout, (
            f"Redmine client should be initialized when REDMINE_URL and "
            f"REDMINE_API_KEY are set in .env file in current working directory. "
            f"stdout: {result.stdout}, stderr: {result.stderr}"
        )
