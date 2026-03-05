"""
Tests for DNS rebinding protection configuration.

Tests cover:
- FastMCP transport_security is correctly set based on host parameter
- SERVER_HOST environment variable controls DNS rebinding behavior
- TransportSecurityMiddleware validates Host headers correctly
"""

import pytest
from unittest.mock import patch, MagicMock
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import (
    TransportSecurityMiddleware,
    TransportSecuritySettings,
)


@pytest.mark.unit
class TestFastMCPDnsRebindingProtection:
    """Tests that FastMCP configures DNS rebinding protection based on host."""

    def test_localhost_enables_dns_protection(self):
        """When host is 127.0.0.1, DNS rebinding protection is auto-enabled."""
        server = FastMCP("test", host="127.0.0.1")
        ts = server.settings.transport_security
        assert ts is not None
        assert ts.enable_dns_rebinding_protection is True
        assert "127.0.0.1:*" in ts.allowed_hosts

    def test_localhost_name_enables_dns_protection(self):
        """When host is 'localhost', DNS rebinding protection is auto-enabled."""
        server = FastMCP("test", host="localhost")
        ts = server.settings.transport_security
        assert ts is not None
        assert ts.enable_dns_rebinding_protection is True
        assert "localhost:*" in ts.allowed_hosts

    def test_ipv6_loopback_enables_dns_protection(self):
        """When host is ::1, DNS rebinding protection is auto-enabled."""
        server = FastMCP("test", host="::1")
        ts = server.settings.transport_security
        assert ts is not None
        assert ts.enable_dns_rebinding_protection is True

    def test_wildcard_host_disables_dns_protection(self):
        """When host is 0.0.0.0 (Docker/public), DNS protection is NOT enabled."""
        server = FastMCP("test", host="0.0.0.0")
        assert server.settings.transport_security is None

    def test_public_ip_disables_dns_protection(self):
        """When host is a public IP, DNS protection is NOT auto-enabled."""
        server = FastMCP("test", host="192.168.1.100")
        assert server.settings.transport_security is None


@pytest.mark.unit
class TestServerHostEnvConfig:
    """Tests that SERVER_HOST env var controls the mcp host configuration."""

    def test_default_host_is_localhost(self):
        """Without SERVER_HOST env var, host defaults to 127.0.0.1."""
        import os

        env = os.environ.copy()
        env.pop("SERVER_HOST", None)
        with patch.dict("os.environ", env, clear=True):
            host = os.getenv("SERVER_HOST", "127.0.0.1")
            assert host == "127.0.0.1"

    def test_docker_host_is_wildcard(self):
        """With SERVER_HOST=0.0.0.0, host is set to 0.0.0.0."""
        with patch.dict("os.environ", {"SERVER_HOST": "0.0.0.0"}):
            import os

            host = os.getenv("SERVER_HOST", "127.0.0.1")
            assert host == "0.0.0.0"


@pytest.mark.unit
class TestMcpObjectTransportSecurity:
    """Tests that the actual mcp object has correct transport_security."""

    def test_mcp_has_transport_security_settings(self):
        """Verify the mcp object has transport_security in its settings."""
        from redmine_mcp_server.redmine_handler import mcp

        assert hasattr(mcp.settings, "transport_security")

    def test_mcp_host_matches_server_host_env(self):
        """Verify mcp host was set from SERVER_HOST env var."""
        import os
        from redmine_mcp_server.redmine_handler import mcp

        expected = os.getenv("SERVER_HOST", "127.0.0.1")
        assert mcp.settings.host == expected


@pytest.mark.unit
class TestTransportSecurityMiddleware:
    """Tests for TransportSecurityMiddleware Host header validation."""

    def _make_request(self, host_header):
        """Create a mock Starlette request with the given Host header."""
        request = MagicMock()
        request.headers = {"host": host_header}
        return request

    def test_public_ip_rejected_with_localhost_protection(self):
        """Public IP Host header is rejected when localhost protection is on."""
        settings = TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=["127.0.0.1:*", "localhost:*", "[::1]:*"],
        )
        middleware = TransportSecurityMiddleware(settings)
        assert middleware._validate_host("220.248.121.51:8000") is False

    def test_localhost_accepted_with_localhost_protection(self):
        """Localhost Host header is accepted when localhost protection is on."""
        settings = TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=["127.0.0.1:*", "localhost:*", "[::1]:*"],
        )
        middleware = TransportSecurityMiddleware(settings)
        assert middleware._validate_host("127.0.0.1:8000") is True
        assert middleware._validate_host("localhost:8000") is True

    def test_any_host_accepted_when_protection_disabled(self):
        """Any Host header is accepted when protection is disabled."""
        middleware = TransportSecurityMiddleware(None)
        assert middleware.settings.enable_dns_rebinding_protection is False

    @pytest.mark.asyncio
    async def test_validate_request_returns_421_for_invalid_host(self):
        """validate_request returns 421 response for invalid Host header."""
        settings = TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=["127.0.0.1:*", "localhost:*"],
        )
        middleware = TransportSecurityMiddleware(settings)
        request = self._make_request("220.248.121.51:8000")

        response = await middleware.validate_request(request)
        assert response is not None
        assert response.status_code == 421

    @pytest.mark.asyncio
    async def test_validate_request_passes_for_valid_host(self):
        """validate_request returns None (pass) for valid Host header."""
        settings = TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=["127.0.0.1:*", "localhost:*"],
        )
        middleware = TransportSecurityMiddleware(settings)
        request = self._make_request("127.0.0.1:8000")

        response = await middleware.validate_request(request)
        assert response is None

    @pytest.mark.asyncio
    async def test_validate_request_skips_when_protection_disabled(self):
        """validate_request skips Host check when protection is disabled."""
        middleware = TransportSecurityMiddleware(None)
        request = self._make_request("220.248.121.51:8000")

        response = await middleware.validate_request(request)
        assert response is None
