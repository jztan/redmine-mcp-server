"""Live checks for manage_helpdesk_ticket against a Helpdesk sandbox (#378).

Skipped unless REDMINE_HELPDESK_TICKETS_ENABLED=true and /helpdesk_tickets
answers. Run against the 8082 sandbox:

    REDMINE_URL=http://localhost:8082 REDMINE_HELPDESK_TICKETS_ENABLED=true \\
        python -m pytest tests/test_helpdesk_integration.py -m integration -q

Every refusal is followed by a read showing the ticket unchanged.
"""

import os
import sys
from unittest.mock import patch

import pytest
import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from redmine_mcp_server._client import (  # noqa: E402
    REDMINE_API_KEY,
    REDMINE_PASSWORD,
    REDMINE_URL,
    REDMINE_USERNAME,
)
from redmine_mcp_server.tools.helpdesk import manage_helpdesk_ticket  # noqa: E402

TICKET = int(os.environ.get("REDMINE_TEST_HELPDESK_TICKET", "804"))
HOME_CONTACT = int(os.environ.get("REDMINE_TEST_HELPDESK_CONTACT", "374"))
HOME_EMAIL = os.environ.get("REDMINE_TEST_HELPDESK_EMAIL", "alice.probe@example.com")
OTHER_CONTACT = int(os.environ.get("REDMINE_TEST_HELPDESK_OTHER_CONTACT", "375"))
OTHER_EMAIL = os.environ.get(
    "REDMINE_TEST_HELPDESK_OTHER_EMAIL", "bob.probe@example.com"
)
PLAIN_ISSUE = int(os.environ.get("REDMINE_TEST_PLAIN_ISSUE", "307"))
OTHER_PROJECT_CONTACT = int(os.environ.get("REDMINE_TEST_OTHER_PROJECT_CONTACT", "0"))
NO_EMAIL_CONTACT = int(os.environ.get("REDMINE_TEST_NO_EMAIL_CONTACT", "0"))
FLAGS = {"REDMINE_HELPDESK_TICKETS_ENABLED": "true", "REDMINE_MCP_READ_ONLY": "false"}


def _probe(path):
    if not REDMINE_URL:
        return 0
    kwargs = {"timeout": 10}
    if REDMINE_API_KEY:
        kwargs["headers"] = {"X-Redmine-API-Key": REDMINE_API_KEY}
    elif REDMINE_USERNAME:
        kwargs["auth"] = (REDMINE_USERNAME, REDMINE_PASSWORD or "")
    try:
        return requests.get(f"{REDMINE_URL}{path}", **kwargs).status_code
    except requests.RequestException:
        return 0


pytestmark = [
    pytest.mark.integration,
    pytest.mark.asyncio,
    pytest.mark.skipif(
        os.environ.get("REDMINE_HELPDESK_TICKETS_ENABLED", "").lower() != "true",
        reason="REDMINE_HELPDESK_TICKETS_ENABLED is not true",
    ),
]


@pytest.fixture(scope="module", autouse=True)
def helpdesk_available():
    if _probe(f"/helpdesk_tickets/{TICKET}.json") != 200:
        pytest.skip("Helpdesk plugin not reachable on this Redmine")


async def run(**kwargs):
    with patch.dict(os.environ, FLAGS):
        return await manage_helpdesk_ticket(**kwargs)


async def contact_id_now():
    ticket = await run(action="get", issue_id=TICKET)
    assert "error" not in ticket, ticket
    return ticket["contact"]["id"]


@pytest.fixture
async def restore_contact():
    yield
    await run(action="set_contact", issue_id=TICKET, contact_id=HOME_CONTACT)
    assert await contact_id_now() == HOME_CONTACT


async def test_get():
    ticket = await run(action="get", issue_id=TICKET)
    assert ticket["issue_id"] == TICKET
    assert ticket["contact"]["id"] == HOME_CONTACT


async def test_get_plain_issue_is_refused():
    result = await run(action="get", issue_id=PLAIN_ISSUE)
    assert result == {"error": f"Issue {PLAIN_ISSUE} is not a Helpdesk ticket."}


async def test_set_by_id_and_back(restore_contact):
    result = await run(action="set_contact", issue_id=TICKET, contact_id=OTHER_CONTACT)
    assert result["contact"]["id"] == OTHER_CONTACT
    assert result["previous_contact"]["id"] == HOME_CONTACT
    assert OTHER_EMAIL in result["from_address"]


async def test_set_by_email_and_back(restore_contact):
    result = await run(action="set_contact", issue_id=TICKET, email=OTHER_EMAIL.upper())
    assert result["contact"]["id"] == OTHER_CONTACT
    back = await run(action="set_contact", issue_id=TICKET, email=HOME_EMAIL)
    assert back["contact"]["id"] == HOME_CONTACT


async def test_plain_issue_is_not_converted():
    result = await run(
        action="set_contact", issue_id=PLAIN_ISSUE, contact_id=OTHER_CONTACT
    )
    assert "not a Helpdesk ticket" in result["error"]
    again = await run(action="get", issue_id=PLAIN_ISSUE)
    assert "not a Helpdesk ticket" in again["error"]


async def test_unknown_email_creates_nothing():
    email = "nobody.at.all.378@example.com"
    result = await run(action="set_contact", issue_id=TICKET, email=email)
    assert "No contact in this issue's project" in result["error"]
    assert await contact_id_now() == HOME_CONTACT
    assert _probe(f"/contacts.json?search={email}") == 200  # still searchable
    # and still no such contact
    kwargs = {"timeout": 10, "auth": (REDMINE_USERNAME, REDMINE_PASSWORD or "")}
    found = requests.get(
        f"{REDMINE_URL}/contacts.json", params={"search": email}, **kwargs
    ).json()["contacts"]
    assert found == []


@pytest.mark.skipif(OTHER_PROJECT_CONTACT == 0, reason="seed the other-project contact")
async def test_other_project_contact_is_refused():
    result = await run(
        action="set_contact", issue_id=TICKET, contact_id=OTHER_PROJECT_CONTACT
    )
    assert "not linked to this issue's project" in result["error"]
    assert await contact_id_now() == HOME_CONTACT


@pytest.mark.skipif(NO_EMAIL_CONTACT == 0, reason="seed the no-email contact")
async def test_no_email_contact_is_refused():
    result = await run(
        action="set_contact", issue_id=TICKET, contact_id=NO_EMAIL_CONTACT
    )
    assert "has no email address" in result["error"]
    assert await contact_id_now() == HOME_CONTACT
