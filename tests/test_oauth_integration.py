"""Live OAuth integration tests against a sandbox Redmine.

Prerequisites (all required, otherwise the suite skips):
  - REDMINE_URL: reachable sandbox Redmine
  - REDMINE_INTROSPECT_CLIENT_ID / _SECRET: confidential OAuth app in the
    sandbox with protected_resource? permission
  - REDMINE_OAUTH_TEST_TOKEN: a valid end-user bearer issued by a user-flow
    OAuth app in the same sandbox

Run with: python tests/run_tests.py --integration

The "revoked token" test is destructive (invalidates the test bearer) and
gated behind RUN_DESTRUCTIVE_TESTS=1. See docs/contributing.md.
"""

import base64
import os
from unittest.mock import MagicMock, patch

import httpx
import pytest

pytestmark = pytest.mark.integration

REDMINE_URL = (os.environ.get("REDMINE_URL") or "").rstrip("/")
CLIENT_ID = os.environ.get("REDMINE_INTROSPECT_CLIENT_ID")
CLIENT_SECRET = os.environ.get("REDMINE_INTROSPECT_CLIENT_SECRET")
TEST_TOKEN = os.environ.get("REDMINE_OAUTH_TEST_TOKEN")
RUN_DESTRUCTIVE = os.environ.get("RUN_DESTRUCTIVE_TESTS") == "1"


def _skip_if_unconfigured():
    missing = [
        name
        for name, val in [
            ("REDMINE_URL", REDMINE_URL),
            ("REDMINE_INTROSPECT_CLIENT_ID", CLIENT_ID),
            ("REDMINE_INTROSPECT_CLIENT_SECRET", CLIENT_SECRET),
            ("REDMINE_OAUTH_TEST_TOKEN", TEST_TOKEN),
        ]
        if not val
    ]
    if missing:
        pytest.skip(
            "Live OAuth integration not configured. " f"Missing: {', '.join(missing)}"
        )


@pytest.fixture(autouse=True)
def _check_config():
    _skip_if_unconfigured()


def _basic_auth_header() -> str:
    return "Basic " + base64.b64encode(f"{CLIENT_ID}:{CLIENT_SECRET}".encode()).decode()


@pytest.mark.asyncio
async def test_real_introspection_call_succeeds():
    """Smoke test: introspection client can introspect the test token."""
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(
            f"{REDMINE_URL}/oauth/introspect",
            headers={
                "Authorization": _basic_auth_header(),
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={"token": TEST_TOKEN, "token_type_hint": "access_token"},
        )
    assert r.status_code == 200, f"introspect returned {r.status_code}: {r.text}"
    body = r.json()
    assert body.get("active") is True, (
        "Test token is inactive per introspection. Either it expired, or "
        "the introspection client lacks protected_resource? permission."
    )
    assert body.get("scope"), "Active token must have a non-empty scope"


@pytest.mark.asyncio
async def test_unknown_token_rejected():
    """Random opaque string should yield {"active": false} via introspection."""
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(
            f"{REDMINE_URL}/oauth/introspect",
            headers={
                "Authorization": _basic_auth_header(),
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={
                "token": "definitely-not-a-real-token",
                "token_type_hint": "access_token",
            },
        )
    assert r.status_code == 200
    assert r.json().get("active") is False


@pytest.mark.asyncio
async def test_end_to_end_tool_call_via_mcp():
    """Valid bearer + a real MCP tool call. Verifies the full request path."""
    from redmine_mcp_server import _client

    access = MagicMock()
    access.token = TEST_TOKEN
    with (
        patch.object(_client, "REDMINE_URL", REDMINE_URL),
        patch.object(_client, "redmine", None),
        patch.object(_client, "_legacy_client", None),
        patch("redmine_mcp_server._client.get_access_token", return_value=access),
    ):
        redmine = _client._get_redmine_client()
        # Cheap read call to prove the bearer is forwarded correctly.
        projects = list(redmine.project.all()[:1])
        assert isinstance(projects, list)


@pytest.mark.asyncio
async def test_scope_advertising_subset_of_sandbox_scopes():
    """advertised_scopes() must overlap with the scopes the sandbox issues."""
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(
            f"{REDMINE_URL}/oauth/introspect",
            headers={
                "Authorization": _basic_auth_header(),
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={"token": TEST_TOKEN, "token_type_hint": "access_token"},
        )
    sandbox_scopes = set((r.json().get("scope") or "").split())
    from redmine_mcp_server.oauth_scopes import advertised_scopes

    our_scopes = set(advertised_scopes())
    assert our_scopes & sandbox_scopes, (
        "No overlap between advertised scopes and sandbox-issued scopes. "
        "Possible name drift between oauth_scopes.py and live Doorkeeper config."
    )


@pytest.mark.skipif(not RUN_DESTRUCTIVE, reason="set RUN_DESTRUCTIVE_TESTS=1 to enable")
@pytest.mark.asyncio
async def test_revoked_token_rejected():
    """DESTRUCTIVE: revokes the test bearer, then asserts it's rejected.

    After this test runs, REDMINE_OAUTH_TEST_TOKEN is invalid and must be
    re-minted before re-running the integration suite.
    """
    async with httpx.AsyncClient(timeout=10) as client:
        rev = await client.post(
            f"{REDMINE_URL}/oauth/revoke",
            data={"token": TEST_TOKEN},
        )
        assert rev.status_code in (200, 204)
        r = await client.post(
            f"{REDMINE_URL}/oauth/introspect",
            headers={
                "Authorization": _basic_auth_header(),
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={"token": TEST_TOKEN, "token_type_hint": "access_token"},
        )
    assert r.status_code == 200
    assert r.json().get("active") is False
