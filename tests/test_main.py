"""
Tests for main.py module.

Tests cover:
- get_version() function
- App initialization
"""

import pytest
from unittest.mock import patch


@pytest.mark.unit
class TestGetVersion:
    """Tests for get_version function."""

    def test_get_version_installed(self):
        """Test get_version returns version when package is installed."""
        from redmine_mcp_server.main import get_version

        with patch("redmine_mcp_server.main.version", return_value="1.2.3"):
            result = get_version()

        assert result == "1.2.3"

    def test_get_version_not_installed(self):
        """Test get_version returns 'dev' when package not installed."""
        from redmine_mcp_server.main import get_version
        from importlib.metadata import PackageNotFoundError

        with patch(
            "redmine_mcp_server.main.version", side_effect=PackageNotFoundError()
        ):
            result = get_version()

        assert result == "dev"


@pytest.mark.unit
class TestAppInitialization:
    """Tests for Starlette app initialization."""

    def test_app_is_created(self):
        """Test that the Starlette app is properly created."""
        from redmine_mcp_server.main import app

        assert app is not None
        # Verify it's a Starlette app (has routes attribute)
        assert hasattr(app, "routes")

    def test_app_has_expected_routes(self):
        """Test that app has the expected routes."""
        from redmine_mcp_server.main import app

        route_paths = [route.path for route in app.routes if hasattr(route, "path")]

        # Check for custom routes (the actual paths depend on FastMCP)
        assert len(route_paths) > 0


@pytest.mark.unit
class TestMainFunction:
    """Tests for main() entry point (limited coverage possible)."""

    def test_main_imports_correctly(self):
        """Test that main module imports without errors."""
        # Just importing should not raise
        from redmine_mcp_server import main

        assert hasattr(main, "main")
        assert hasattr(main, "get_version")
        assert hasattr(main, "app")

    def test_main_function_is_callable(self):
        """Test that main() function is callable."""
        from redmine_mcp_server.main import main

        assert callable(main)
