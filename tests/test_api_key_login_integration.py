"""Live checks for api-key-login key validation against a real Redmine.

What the unit tests mock is the one thing that can differ between Redmine
versions: what ``GET /users/current.json`` answers for a valid key, for an
admin's key, and for a wrong one. Everything else in the mode is our own code
and is covered hermetically in ``test_api_key_login.py``.

Configure with a Redmine that has the REST API enabled and a **non-admin**
user's API key::

    REDMINE_URL=http://127.0.0.1:18080
    REDMINE_API_KEY_LOGIN_TEST_KEY=<that user's API access key>
    REDMINE_API_KEY_LOGIN_TEST_ADMIN_KEY=<optional, an admin's key>

Run the same file once per version with ``REDMINE_URL`` pointed at each.
Unset, everything here skips with a reason.
"""

import os

import pytest
from dotenv import load_dotenv

from redmine_mcp_server._api_key_login import (
    RedmineUnavailable,
    fetch_redmine_identity,
)

load_dotenv()

pytestmark = pytest.mark.integration

REDMINE_URL = (os.environ.get("REDMINE_URL") or "").rstrip("/")
TEST_KEY = os.environ.get("REDMINE_API_KEY_LOGIN_TEST_KEY")
ADMIN_KEY = os.environ.get("REDMINE_API_KEY_LOGIN_TEST_ADMIN_KEY")


def _skip_if_unconfigured():
    missing = [
        name
        for name, val in [
            ("REDMINE_URL", REDMINE_URL),
            ("REDMINE_API_KEY_LOGIN_TEST_KEY", TEST_KEY),
        ]
        if not val
    ]
    if missing:
        pytest.skip(
            "Live api-key-login integration not configured. "
            f"Missing: {', '.join(missing)}"
        )


@pytest.fixture(autouse=True)
def _check_config():
    _skip_if_unconfigured()


async def test_a_valid_key_yields_the_identity_the_binding_needs():
    identity = await fetch_redmine_identity(REDMINE_URL, TEST_KEY)

    assert identity is not None, "Redmine rejected the configured test key"
    assert isinstance(identity["id"], int)
    assert identity["login"]
    # The admin gate reads this, so the type matters as much as the value.
    assert identity["admin"] is False


async def test_a_wrong_key_is_rejected_rather_than_erroring():
    # A 401 must come back as None so the caller can charge an attempt; only a
    # transport failure is allowed to raise.
    assert await fetch_redmine_identity(REDMINE_URL, "f" * 40) is None


@pytest.mark.skipif(
    not ADMIN_KEY, reason="REDMINE_API_KEY_LOGIN_TEST_ADMIN_KEY not configured"
)
async def test_an_admin_key_reports_itself_as_admin():
    """Without this the admin gate would silently pass everyone through."""
    identity = await fetch_redmine_identity(REDMINE_URL, ADMIN_KEY)

    assert identity is not None
    assert identity["admin"] is True


async def test_an_unreachable_redmine_raises_instead_of_denying():
    # Port 1 answers nothing; the login route turns this into a 502 and keeps
    # the transaction, because the user's key may be perfectly good.
    with pytest.raises(RedmineUnavailable):
        await fetch_redmine_identity("http://127.0.0.1:1", TEST_KEY)
