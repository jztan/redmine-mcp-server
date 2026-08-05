"""Tests for SSL settings surviving environment overrides (issue #197).

``requests`` fills an unset per-request ``verify`` from ``REQUESTS_CA_BUNDLE``
/ ``CURL_CA_BUNDLE`` and that value wins over ``session.verify``. python-redmine
never passes a per-request ``verify``, so an env CA bundle silently re-enables
verification even when ``REDMINE_SSL_VERIFY=false``.

These tests also cover the httpx-based call sites, which talk to the same
Redmine host and previously ignored the SSL configuration entirely.
"""

import os
from unittest.mock import patch

import pytest

from redmine_mcp_server import _client


@pytest.fixture
def cert_file(tmp_path):
    path = tmp_path / "ca.crt"
    path.write_text("-----BEGIN CERTIFICATE-----\nFAKE\n")
    return path


class TestRequestsConfigEnvOverride:
    """`_build_requests_config()` must pin an explicit verify decision."""

    def test_verify_disabled_stops_trusting_env(self):
        with patch.object(_client, "REDMINE_SSL_VERIFY", False):
            config = _client._build_requests_config()

        assert config["verify"] is False
        assert config["trust_env"] is False

    def test_custom_cert_stops_trusting_env(self, cert_file):
        with (
            patch.object(_client, "REDMINE_SSL_VERIFY", True),
            patch.object(_client, "REDMINE_SSL_CERT", str(cert_file)),
        ):
            config = _client._build_requests_config()

        assert config["verify"] == str(cert_file.resolve())
        assert config["trust_env"] is False

    def test_default_verification_keeps_trusting_env(self):
        with (
            patch.object(_client, "REDMINE_SSL_VERIFY", True),
            patch.object(_client, "REDMINE_SSL_CERT", None),
            patch.object(_client, "REDMINE_SSL_CLIENT_CERT", None),
        ):
            config = _client._build_requests_config()

        assert config == {}

    def test_client_cert_alone_keeps_trusting_env(self):
        with (
            patch.object(_client, "REDMINE_SSL_VERIFY", True),
            patch.object(_client, "REDMINE_SSL_CERT", None),
            patch.object(_client, "REDMINE_SSL_CLIENT_CERT", "/client.pem"),
        ):
            config = _client._build_requests_config()

        assert config == {"cert": "/client.pem"}

    def test_proxy_env_is_carried_over_when_env_trust_is_off(self):
        with (
            patch.object(_client, "REDMINE_SSL_VERIFY", False),
            patch.object(_client, "REDMINE_URL", "https://redmine.local"),
            patch.dict(
                os.environ, {"HTTPS_PROXY": "http://proxy.local:3128"}, clear=False
            ),
        ):
            config = _client._build_requests_config()

        assert config["proxies"]["https"] == "http://proxy.local:3128"

    def test_no_proxy_host_gets_no_proxies(self):
        with (
            patch.object(_client, "REDMINE_SSL_VERIFY", False),
            patch.object(_client, "REDMINE_URL", "https://redmine.local"),
            patch.dict(
                os.environ,
                {"HTTPS_PROXY": "http://proxy.local:3128", "NO_PROXY": "redmine.local"},
                clear=False,
            ),
        ):
            config = _client._build_requests_config()

        assert not config.get("proxies")


class TestHttpxSSLKwargs:
    """`httpx_ssl_kwargs()` mirrors the requests config for httpx clients."""

    def test_verify_disabled(self):
        with patch.object(_client, "REDMINE_SSL_VERIFY", False):
            assert _client.httpx_ssl_kwargs() == {"verify": False}

    def test_custom_cert(self, cert_file):
        with (
            patch.object(_client, "REDMINE_SSL_VERIFY", True),
            patch.object(_client, "REDMINE_SSL_CERT", str(cert_file)),
        ):
            assert _client.httpx_ssl_kwargs() == {"verify": str(cert_file.resolve())}

    def test_client_cert_included(self):
        with (
            patch.object(_client, "REDMINE_SSL_VERIFY", False),
            patch.object(_client, "REDMINE_SSL_CLIENT_CERT", "/cert.pem,/key.pem"),
        ):
            kwargs = _client.httpx_ssl_kwargs()

        assert kwargs["cert"] == ("/cert.pem", "/key.pem")

    def test_defaults_are_empty(self):
        with (
            patch.object(_client, "REDMINE_SSL_VERIFY", True),
            patch.object(_client, "REDMINE_SSL_CERT", None),
            patch.object(_client, "REDMINE_SSL_CLIENT_CERT", None),
        ):
            assert _client.httpx_ssl_kwargs() == {}

    def test_settings_apply_to_the_redmine_host(self):
        with (
            patch.object(_client, "REDMINE_SSL_VERIFY", False),
            patch.object(_client, "REDMINE_URL", "https://redmine.local"),
        ):
            kwargs = _client.httpx_ssl_kwargs(
                "https://redmine.local/attachments/1/a.pdf"
            )

        assert kwargs == {"verify": False}

    def test_settings_do_not_leak_to_other_hosts(self):
        with (
            patch.object(_client, "REDMINE_SSL_VERIFY", False),
            patch.object(_client, "REDMINE_URL", "https://redmine.local"),
        ):
            kwargs = _client.httpx_ssl_kwargs("https://cdn.example.com/a.pdf")

        assert kwargs == {}


class _ClientSpy:
    """Stand-in for httpx.AsyncClient that records its constructor kwargs."""

    def __init__(self, calls, response=None):
        self.calls = calls
        self.response = response

    def __call__(self, *args, **kwargs):
        self.calls.append(kwargs)
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, *args, **kwargs):
        return self.response

    async def post(self, *args, **kwargs):
        return self.response


class _Response:
    status_code = 200

    @staticmethod
    def json():
        return {"user": {"id": 1, "login": "test", "firstname": "T", "lastname": "U"}}


@pytest.fixture
def ssl_disabled():
    with (
        patch.object(_client, "REDMINE_SSL_VERIFY", False),
        patch.object(_client, "REDMINE_SSL_CERT", None),
        patch.object(_client, "REDMINE_SSL_CLIENT_CERT", None),
        patch.object(_client, "REDMINE_URL", "https://redmine.local"),
    ):
        yield


class TestHttpxCallSitesUseSSLConfig:
    """Every httpx client aimed at Redmine honors the SSL configuration."""

    @pytest.mark.asyncio
    async def test_legacy_health_probe(self, ssl_disabled):
        from redmine_mcp_server import _http_routes

        calls = []
        with (
            patch.object(_client, "REDMINE_API_KEY", "key"),
            patch("httpx.AsyncClient", _ClientSpy(calls, _Response())),
        ):
            await _http_routes._probe_redmine_legacy()

        assert calls and calls[0]["verify"] is False

    @pytest.mark.asyncio
    async def test_per_user_reachability_probe(self, ssl_disabled):
        from redmine_mcp_server import _http_routes

        calls = []
        with patch("httpx.AsyncClient", _ClientSpy(calls, _Response())):
            await _http_routes._probe_redmine_reachable()

        assert calls and calls[0]["verify"] is False

    @pytest.mark.asyncio
    async def test_introspection_probe(self, ssl_disabled):
        from redmine_mcp_server import _http_routes

        calls = []
        with (
            patch.object(
                _http_routes,
                "get_introspection_credentials",
                lambda: ("id", "secret"),
            ),
            patch.dict(
                os.environ, {"REDMINE_URL": "https://redmine.local"}, clear=False
            ),
            patch("httpx.AsyncClient", _ClientSpy(calls, _Response())),
        ):
            await _http_routes._probe_introspection_uncached()

        assert calls and calls[0]["verify"] is False

    @pytest.mark.asyncio
    async def test_server_info_current_user(self, ssl_disabled):
        from redmine_mcp_server.tools import meta

        calls = []
        with (
            patch.object(_client, "REDMINE_API_KEY", "key"),
            patch("httpx.AsyncClient", _ClientSpy(calls, _Response())),
        ):
            await meta._fetch_current_user_info()

        assert calls and calls[0]["verify"] is False

    def test_attachment_download_client_on_redmine_host(self, ssl_disabled):
        from redmine_mcp_server import _ssrf

        calls = []
        with patch("httpx.AsyncClient", _ClientSpy(calls)):
            _ssrf._make_pinned_client(
                "redmine.local", "10.0.0.1", "https://redmine.local/attachments/1/a.pdf"
            )

        assert calls and calls[0]["verify"] is False

    def test_attachment_download_client_on_other_host(self, ssl_disabled):
        from redmine_mcp_server import _ssrf

        calls = []
        with patch("httpx.AsyncClient", _ClientSpy(calls)):
            _ssrf._make_pinned_client(
                "cdn.example.com", "93.184.216.34", "https://cdn.example.com/a.pdf"
            )

        assert calls and "verify" not in calls[0]


class TestConflictingEnvDiagnostics:
    """Explicit SSL settings warn about env vars that would fight them."""

    def test_ca_bundle_env_is_reported(self, caplog):
        with (
            patch.object(_client, "REDMINE_SSL_VERIFY", False),
            patch.dict(
                os.environ, {"REQUESTS_CA_BUNDLE": "/etc/ssl/corp.pem"}, clear=True
            ),
        ):
            with caplog.at_level("WARNING", logger="redmine_mcp_server"):
                _client._build_requests_config()

        assert "REQUESTS_CA_BUNDLE" in caplog.text

    def test_https_proxy_is_reported(self, caplog):
        with (
            patch.object(_client, "REDMINE_SSL_VERIFY", False),
            patch.object(_client, "REDMINE_URL", "https://redmine.local"),
            patch.dict(
                os.environ, {"HTTPS_PROXY": "https://proxy.local:3128"}, clear=True
            ),
        ):
            with caplog.at_level("WARNING", logger="redmine_mcp_server"):
                _client._build_requests_config()

        assert "HTTPS_PROXY" in caplog.text

    def test_clean_env_says_nothing(self, caplog):
        with (
            patch.object(_client, "REDMINE_SSL_VERIFY", False),
            patch.dict(os.environ, {}, clear=True),
        ):
            with caplog.at_level("WARNING", logger="redmine_mcp_server"):
                _client._build_requests_config()

        assert "REQUESTS_CA_BUNDLE" not in caplog.text
        assert "HTTPS_PROXY" not in caplog.text

    def test_default_verification_says_nothing(self, caplog):
        with (
            patch.object(_client, "REDMINE_SSL_VERIFY", True),
            patch.object(_client, "REDMINE_SSL_CERT", None),
            patch.object(_client, "REDMINE_SSL_CLIENT_CERT", None),
            patch.dict(
                os.environ, {"REQUESTS_CA_BUNDLE": "/etc/ssl/corp.pem"}, clear=True
            ),
        ):
            with caplog.at_level("WARNING", logger="redmine_mcp_server"):
                _client._build_requests_config()

        assert "REQUESTS_CA_BUNDLE" not in caplog.text
