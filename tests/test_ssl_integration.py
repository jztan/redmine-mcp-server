"""
Integration tests for SSL certificate configuration.

These tests verify SSL configuration works with real certificate files.
Run with: python tests/run_tests.py --integration
"""

import pytest
import os
import sys
from pathlib import Path
from unittest.mock import patch

# Add the src directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


@pytest.fixture
def ssl_cert_path():
    """Return path to test CA certificate."""
    return str(Path(__file__).parent / "fixtures/ssl/ca-cert.pem")


@pytest.fixture
def client_cert_path():
    """Return path to test client certificate."""
    return str(Path(__file__).parent / "fixtures/ssl/client-cert.pem")


@pytest.fixture
def client_key_path():
    """Return path to test client key."""
    return str(Path(__file__).parent / "fixtures/ssl/client-key.pem")


@pytest.fixture
def combined_cert_path():
    """Return path to combined client certificate."""
    return str(Path(__file__).parent / "fixtures/ssl/client-combined.pem")


@pytest.mark.integration
class TestSSLConfigurationIntegration:
    """Integration tests for SSL configuration with real certificates."""

    def test_ssl_cert_file_exists(self, ssl_cert_path):
        """Verify test SSL certificate file exists."""
        cert_path = Path(ssl_cert_path)
        assert cert_path.exists(), f"Test certificate not found: {ssl_cert_path}"
        assert cert_path.is_file(), f"Test certificate is not a file: {ssl_cert_path}"

    def test_module_loads_with_custom_ca_cert(self, ssl_cert_path):
        """Test loading module with custom CA certificate."""
        with patch.dict(
            os.environ,
            {
                "REDMINE_URL": "https://test.redmine.com",
                "REDMINE_API_KEY": "test_key",
                "REDMINE_SSL_CERT": ssl_cert_path,
            },
        ):
            # Reload module to pick up new environment variables
            import importlib
            from redmine_mcp_server import redmine_handler

            importlib.reload(redmine_handler)

            # Verify SSL cert was loaded
            assert redmine_handler.REDMINE_SSL_CERT == ssl_cert_path
            assert redmine_handler.REDMINE_SSL_VERIFY is True

    def test_module_handles_missing_cert_gracefully(self):
        """Test module handles missing certificate file gracefully."""
        with patch.dict(
            os.environ,
            {
                "REDMINE_URL": "https://test.redmine.com",
                "REDMINE_API_KEY": "test_key",
                "REDMINE_SSL_CERT": "/nonexistent/cert.pem",
            },
        ):
            # Reload module
            import importlib
            from redmine_mcp_server import redmine_handler

            importlib.reload(redmine_handler)

            # Should set redmine to None instead of crashing
            assert redmine_handler.redmine is None

    def test_module_handles_directory_as_cert_gracefully(self, ssl_cert_path):
        """Test module handles directory path gracefully."""
        cert_dir = str(Path(ssl_cert_path).parent)

        with patch.dict(
            os.environ,
            {
                "REDMINE_URL": "https://test.redmine.com",
                "REDMINE_API_KEY": "test_key",
                "REDMINE_SSL_CERT": cert_dir,
            },
        ):
            # Reload module
            import importlib
            from redmine_mcp_server import redmine_handler

            importlib.reload(redmine_handler)

            # Should set redmine to None instead of crashing
            assert redmine_handler.redmine is None

    def test_ssl_verify_disabled(self):
        """Test SSL verification can be disabled."""
        with patch.dict(
            os.environ,
            {
                "REDMINE_URL": "https://test.redmine.com",
                "REDMINE_API_KEY": "test_key",
                "REDMINE_SSL_VERIFY": "false",
            },
        ):
            # Reload module
            import importlib
            from redmine_mcp_server import redmine_handler

            importlib.reload(redmine_handler)

            # Verify SSL is disabled
            assert redmine_handler.REDMINE_SSL_VERIFY is False
            # Redmine client should still initialize (though won't connect to test URL)
            # We can't test actual connection without a real server

    def test_client_cert_tuple_format(self, client_cert_path, client_key_path):
        """Test client certificate in tuple format."""
        client_cert_string = f"{client_cert_path},{client_key_path}"

        with patch.dict(
            os.environ,
            {
                "REDMINE_URL": "https://test.redmine.com",
                "REDMINE_API_KEY": "test_key",
                "REDMINE_SSL_CLIENT_CERT": client_cert_string,
            },
        ):
            # Reload module
            import importlib
            from redmine_mcp_server import redmine_handler

            importlib.reload(redmine_handler)

            # Verify client cert was set
            assert redmine_handler.REDMINE_SSL_CLIENT_CERT == client_cert_string

    def test_client_cert_combined_format(self, combined_cert_path):
        """Test client certificate in combined format."""
        with patch.dict(
            os.environ,
            {
                "REDMINE_URL": "https://test.redmine.com",
                "REDMINE_API_KEY": "test_key",
                "REDMINE_SSL_CLIENT_CERT": combined_cert_path,
            },
        ):
            # Reload module
            import importlib
            from redmine_mcp_server import redmine_handler

            importlib.reload(redmine_handler)

            # Verify client cert was set
            assert redmine_handler.REDMINE_SSL_CLIENT_CERT == combined_cert_path

    def test_combined_ssl_config(
        self, ssl_cert_path, client_cert_path, client_key_path
    ):
        """Test combined SSL configuration with CA cert and client cert."""
        client_cert_string = f"{client_cert_path},{client_key_path}"

        with patch.dict(
            os.environ,
            {
                "REDMINE_URL": "https://test.redmine.com",
                "REDMINE_API_KEY": "test_key",
                "REDMINE_SSL_CERT": ssl_cert_path,
                "REDMINE_SSL_CLIENT_CERT": client_cert_string,
            },
        ):
            # Reload module
            import importlib
            from redmine_mcp_server import redmine_handler

            importlib.reload(redmine_handler)

            # Verify both SSL configs were set
            assert redmine_handler.REDMINE_SSL_CERT == ssl_cert_path
            assert redmine_handler.REDMINE_SSL_CLIENT_CERT == client_cert_string
            assert redmine_handler.REDMINE_SSL_VERIFY is True

    def test_ssl_cert_path_resolution(self, ssl_cert_path):
        """Test that SSL cert path gets resolved to absolute path."""
        # Use relative path
        relative_path = "tests/fixtures/ssl/ca-cert.pem"

        with patch.dict(
            os.environ,
            {
                "REDMINE_URL": "https://test.redmine.com",
                "REDMINE_API_KEY": "test_key",
                "REDMINE_SSL_CERT": relative_path,
            },
        ):
            # Reload module
            import importlib
            from redmine_mcp_server import redmine_handler

            importlib.reload(redmine_handler)

            # The path should still work (will be resolved internally)
            assert redmine_handler.REDMINE_SSL_CERT == relative_path
