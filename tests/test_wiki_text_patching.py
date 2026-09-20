"""Changing a long wiki page without writing it out: `text_edits` and
`text_upload_id` on `manage_redmine_wiki_page` (#325)."""

import os
import sys
from unittest.mock import Mock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from redmine_mcp_server import _upload_store  # noqa: E402
from redmine_mcp_server.tools.wiki import manage_redmine_wiki_page  # noqa: E402

PAGE = "h1. Betrieb\r\n\r\nStand: offen\r\n\r\n" + "Eine Zeile mit Ümläuten.\r\n" * 400


@pytest.fixture
def attachments_dir(tmp_path, monkeypatch):
    path = tmp_path / "attachments"
    path.mkdir()
    monkeypatch.setenv("ATTACHMENTS_DIR", str(path))
    monkeypatch.delenv("REDMINE_MCP_READ_ONLY", raising=False)
    return path


@pytest.fixture
def mock_redmine():
    with patch("redmine_mcp_server._client.redmine") as mock:
        yield mock


def _page(text=PAGE, version=3):
    page = Mock()
    page.title = "Page"
    page.text = text
    page.version = version
    page.created_on = "2026-09-20T10:00:00Z"
    page.updated_on = "2026-09-20T10:00:00Z"
    page.attachments = []
    return page


def _stage(content: bytes) -> str:
    issued = _upload_store.create_ticket(filename="page.textile")
    record, reason = _upload_store.redeem_ticket(issued["upload_id"], issued["ticket"])
    assert reason is None
    _upload_store.staged_path(record).write_bytes(content)
    _upload_store.mark_ready(issued["upload_id"], record, len(content), "x")
    return issued["upload_id"]


async def _update(**kwargs):
    return await manage_redmine_wiki_page(
        action="update", project_id="proj", wiki_page_title="Page", **kwargs
    )


class TestTextEdits:
    @pytest.mark.asyncio
    async def test_only_the_named_passage_changes(self, mock_redmine):
        mock_redmine.wiki_page.get.return_value = _page()

        result = await _update(
            text_edits=[{"find": "Stand: offen", "replace": "Stand: erledigt"}]
        )

        assert "error" not in result
        _, kwargs = mock_redmine.wiki_page.update.call_args
        assert kwargs["text"] == PAGE.replace("Stand: offen", "Stand: erledigt")

    @pytest.mark.asyncio
    async def test_the_write_carries_the_version_that_was_patched(self, mock_redmine):
        mock_redmine.wiki_page.get.return_value = _page(version=8)

        await _update(text_edits=[{"find": "Stand: offen", "replace": "x"}])

        _, kwargs = mock_redmine.wiki_page.update.call_args
        assert kwargs["version"] == 8

    @pytest.mark.asyncio
    async def test_a_page_that_moved_on_is_refused_before_writing(self, mock_redmine):
        mock_redmine.wiki_page.get.return_value = _page(version=8)

        result = await _update(
            text_edits=[{"find": "Stand: offen", "replace": "x"}],
            expected_version=7,
        )

        assert "Edit conflict" in result["error"]
        assert "8" in result["error"]
        mock_redmine.wiki_page.update.assert_not_called()

    @pytest.mark.asyncio
    async def test_an_ambiguous_find_writes_nothing(self, mock_redmine):
        mock_redmine.wiki_page.get.return_value = _page()

        result = await _update(text_edits=[{"find": "Ümläuten", "replace": "x"}])

        assert "text_edits[0]" in result["error"]
        mock_redmine.wiki_page.update.assert_not_called()

    @pytest.mark.asyncio
    async def test_the_page_is_not_echoed_back(self, mock_redmine):
        mock_redmine.wiki_page.get.return_value = _page()

        result = await _update(text_edits=[{"find": "Stand: offen", "replace": "x"}])

        assert "text" not in result
        assert result["text_length"] == len(PAGE.replace("Stand: offen", "x"))
        assert result["version"] == 3

    @pytest.mark.asyncio
    async def test_there_is_nothing_to_patch_on_create(self, mock_redmine):
        result = await manage_redmine_wiki_page(
            action="create",
            project_id="proj",
            wiki_page_title="Page",
            text_edits=[{"find": "a", "replace": "b"}],
        )

        assert "text_edits" in result["error"]
        mock_redmine.wiki_page.create.assert_not_called()


class TestTextUploadId:
    @pytest.mark.asyncio
    async def test_update_takes_the_staged_text(self, mock_redmine, attachments_dir):
        mock_redmine.wiki_page.get.return_value = _page()
        upload_id = _stage(PAGE.encode("utf-8"))

        result = await _update(text_upload_id=upload_id, expected_version=3)

        assert "error" not in result
        _, kwargs = mock_redmine.wiki_page.update.call_args
        assert kwargs["text"] == PAGE
        assert kwargs["version"] == 3
        assert "text" not in result
        assert result["text_length"] == len(PAGE)

    @pytest.mark.asyncio
    async def test_create_takes_the_staged_text(self, mock_redmine, attachments_dir):
        mock_redmine.wiki_page.create.return_value = _page(version=1)
        upload_id = _stage(PAGE.encode("utf-8"))

        result = await manage_redmine_wiki_page(
            action="create",
            project_id="proj",
            wiki_page_title="Page",
            text_upload_id=upload_id,
        )

        assert "error" not in result
        _, kwargs = mock_redmine.wiki_page.create.call_args
        assert kwargs["text"] == PAGE
        assert "text" not in result

    @pytest.mark.asyncio
    async def test_a_file_that_is_not_utf8_writes_nothing(
        self, mock_redmine, attachments_dir
    ):
        upload_id = _stage(b"\xff\xfe not text")

        result = await _update(text_upload_id=upload_id)

        assert "UTF-8" in result["error"]
        mock_redmine.wiki_page.update.assert_not_called()


class TestOneSourceAtATime:
    @pytest.mark.asyncio
    async def test_two_sources_are_refused_by_name(self, mock_redmine):
        result = await _update(
            text="whole page", text_edits=[{"find": "a", "replace": "b"}]
        )

        assert "text, text_edits" in result["error"]
        mock_redmine.wiki_page.update.assert_not_called()

    @pytest.mark.asyncio
    async def test_a_plain_text_update_still_returns_the_page(self, mock_redmine):
        mock_redmine.wiki_page.get.return_value = _page(text="whole page")

        result = await _update(text="whole page")

        assert "whole page" in result["text"]
        assert "text_length" not in result
