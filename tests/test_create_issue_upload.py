"""`description_upload_id` on `create_redmine_issue` (#326).

#316 gave the *update* path a way to set a long description from a staged
file. Creation did not get it, which is the wrong way round: at creation the
whole text is new by definition, so there is nothing to patch and every
character has to be written out into the tool argument. The issue that
prompted #313 carries 42,561 of them, and it was created through this tool.
"""

import uuid
from unittest.mock import MagicMock, patch

import pytest

from redmine_mcp_server import _upload_store
from redmine_mcp_server.tools.issues import create_redmine_issue

LONG_DESCRIPTION = "<p>Ein Absatz, der sich wiederholt.</p>\n" * 1200


@pytest.fixture
def attachments_dir(tmp_path, monkeypatch):
    path = tmp_path / "attachments"
    path.mkdir()
    monkeypatch.setenv("ATTACHMENTS_DIR", str(path))
    monkeypatch.delenv("REDMINE_MCP_READ_ONLY", raising=False)
    return path


def _stage(content: bytes) -> str:
    issued = _upload_store.create_ticket(filename="description.html")
    record, reason = _upload_store.redeem_ticket(issued["upload_id"], issued["ticket"])
    assert reason is None
    _upload_store.staged_path(record).write_bytes(content)
    _upload_store.mark_ready(issued["upload_id"], record, len(content), "x")
    return issued["upload_id"]


def _created_issue():
    issue = MagicMock()
    issue.id = 43376
    issue.subject = "Neu"
    issue.description = ""
    return issue


@pytest.mark.unit
class TestTheStagedTextReachesRedmine:
    @pytest.mark.asyncio
    async def test_it_arrives_as_the_description(self, attachments_dir):
        upload_id = _stage("<p>Ein neuer Text mit Ümläuten.</p>".encode("utf-8"))

        with patch("redmine_mcp_server._client.redmine") as mock_redmine:
            mock_redmine.issue.create.return_value = _created_issue()

            await create_redmine_issue(
                project_id=1,
                subject="Neu",
                description_upload_id=upload_id,
            )

            sent = mock_redmine.issue.create.call_args
            assert sent.kwargs["description"] == "<p>Ein neuer Text mit Ümläuten.</p>"

    @pytest.mark.asyncio
    async def test_a_long_one_arrives_whole(self, attachments_dir):
        """The case the issue is about: none of it passes through a token."""
        upload_id = _stage(LONG_DESCRIPTION.encode("utf-8"))

        with patch("redmine_mcp_server._client.redmine") as mock_redmine:
            mock_redmine.issue.create.return_value = _created_issue()

            await create_redmine_issue(
                project_id=1,
                subject="Neu",
                description_upload_id=upload_id,
            )

            sent = mock_redmine.issue.create.call_args
            assert sent.kwargs["description"] == LONG_DESCRIPTION
            assert len(sent.kwargs["description"]) > 40000

    @pytest.mark.asyncio
    async def test_the_other_fields_still_go_along(self, attachments_dir):
        upload_id = _stage(b"<p>neu</p>")

        with patch("redmine_mcp_server._client.redmine") as mock_redmine:
            mock_redmine.issue.create.return_value = _created_issue()

            await create_redmine_issue(
                project_id=1,
                subject="Neu",
                fields={"tracker_id": 3, "priority_id": 2},
                description_upload_id=upload_id,
            )

            sent = mock_redmine.issue.create.call_args
            assert sent.kwargs["description"] == "<p>neu</p>"
            assert sent.kwargs["tracker_id"] == 3
            assert sent.kwargs["priority_id"] == 2
            assert sent.kwargs["subject"] == "Neu"


@pytest.mark.unit
class TestTheTwoSourcesAreExclusive:
    @pytest.mark.asyncio
    async def test_both_at_once_are_refused_without_creating(self, attachments_dir):
        upload_id = _stage(b"<p>neu</p>")

        with patch("redmine_mcp_server._client.redmine") as mock_redmine:
            result = await create_redmine_issue(
                project_id=1,
                subject="Neu",
                description="<p>auch neu</p>",
                description_upload_id=upload_id,
            )

            assert "error" in result
            assert "one way at a time" in result["error"]
            assert "description_upload_id" in result["error"]
            mock_redmine.issue.create.assert_not_called()

    @pytest.mark.asyncio
    async def test_an_empty_description_is_not_a_second_source(self, attachments_dir):
        """`description` defaults to `""`, so an explicit empty one is no clash.

        Refusing it would reject a call that asks for exactly one thing.
        """
        upload_id = _stage(b"<p>neu</p>")

        with patch("redmine_mcp_server._client.redmine") as mock_redmine:
            mock_redmine.issue.create.return_value = _created_issue()

            result = await create_redmine_issue(
                project_id=1,
                subject="Neu",
                description="",
                description_upload_id=upload_id,
            )

            assert "error" not in result
            sent = mock_redmine.issue.create.call_args
            assert sent.kwargs["description"] == "<p>neu</p>"


@pytest.mark.unit
class TestABadUploadIsReportedNotGuessed:
    @pytest.mark.asyncio
    async def test_non_utf8_refuses_the_call(self, attachments_dir):
        upload_id = _stage(bytes([0xFF, 0xFE]) + b" not text")

        with patch("redmine_mcp_server._client.redmine") as mock_redmine:
            result = await create_redmine_issue(
                project_id=1, subject="Neu", description_upload_id=upload_id
            )

            assert "not valid UTF-8" in result["error"]
            mock_redmine.issue.create.assert_not_called()

    @pytest.mark.asyncio
    async def test_an_unknown_upload_id_refuses_the_call(self, attachments_dir):
        with patch("redmine_mcp_server._client.redmine") as mock_redmine:
            result = await create_redmine_issue(
                project_id=1, subject="Neu", description_upload_id=str(uuid.uuid4())
            )

            assert "error" in result
            mock_redmine.issue.create.assert_not_called()

    @pytest.mark.asyncio
    async def test_a_ticket_that_never_received_a_file_refuses_the_call(
        self, attachments_dir
    ):
        issued = _upload_store.create_ticket(filename="description.html")

        with patch("redmine_mcp_server._client.redmine") as mock_redmine:
            result = await create_redmine_issue(
                project_id=1,
                subject="Neu",
                description_upload_id=issued["upload_id"],
            )

            assert "never received a file" in result["error"]
            mock_redmine.issue.create.assert_not_called()


@pytest.mark.unit
class TestADescriptionInTheFieldsPayload:
    """#333: it used to be dropped for the parameter's default, and the issue
    was created empty with nothing said about it. update_redmine_issue takes
    its description in fields, so the habit carries over easily."""

    @pytest.mark.asyncio
    async def test_it_is_refused_without_creating(self, attachments_dir):
        with patch("redmine_mcp_server._client.redmine") as mock_redmine:
            result = await create_redmine_issue(
                project_id=1,
                subject="Neu",
                fields={"tracker_id": 3, "description": "<p>geht verloren</p>"},
            )

            assert "description" in result["error"]
            mock_redmine.issue.create.assert_not_called()

    @pytest.mark.asyncio
    async def test_extra_fields_is_refused_the_same_way(self, attachments_dir):
        with patch("redmine_mcp_server._client.redmine") as mock_redmine:
            result = await create_redmine_issue(
                project_id=1,
                subject="Neu",
                extra_fields={"description": "<p>geht verloren</p>"},
            )

            assert "description" in result["error"]
            mock_redmine.issue.create.assert_not_called()

    @pytest.mark.asyncio
    async def test_an_empty_one_loses_nothing_and_is_allowed(self, attachments_dir):
        with patch("redmine_mcp_server._client.redmine") as mock_redmine:
            mock_redmine.issue.create.return_value = _created_issue()

            result = await create_redmine_issue(
                project_id=1,
                subject="Neu",
                description="<p>kurz</p>",
                fields={"description": "", "tracker_id": 3},
            )

            assert "error" not in result
            sent = mock_redmine.issue.create.call_args
            assert sent.kwargs["description"] == "<p>kurz</p>"
            assert sent.kwargs["tracker_id"] == 3


@pytest.mark.unit
class TestTheOrdinaryCallIsUnchanged:
    @pytest.mark.asyncio
    async def test_a_plain_description_still_works(self, attachments_dir):
        with patch("redmine_mcp_server._client.redmine") as mock_redmine:
            mock_redmine.issue.create.return_value = _created_issue()

            await create_redmine_issue(
                project_id=1, subject="Neu", description="<p>kurz</p>"
            )

            sent = mock_redmine.issue.create.call_args
            assert sent.kwargs["description"] == "<p>kurz</p>"

    @pytest.mark.asyncio
    async def test_no_description_at_all_still_works(self, attachments_dir):
        with patch("redmine_mcp_server._client.redmine") as mock_redmine:
            mock_redmine.issue.create.return_value = _created_issue()

            await create_redmine_issue(project_id=1, subject="Neu")

            sent = mock_redmine.issue.create.call_args
            assert sent.kwargs["description"] == ""
